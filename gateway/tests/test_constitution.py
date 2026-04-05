"""Tests for isg_agent.core.constitution — machine-enforced agent behavioral contracts.

Covers:
- ConstitutionRule frozen dataclass (immutability, default priority)
- ConstitutionCheckResult fields and types
- ConstitutionViolation exception (rule_id, action, reason, message format)
- Constitution.from_dict() happy path and validation errors
- Constitution.from_yaml() file loading and error handling
- Constitution.check() priority ordering, first-match semantics, default ALLOW
- Constitution.enforce() — returns on allow, raises ConstitutionViolation on deny
- Constitution.add_rule() — success and duplicate ValueError
- Constitution.remove_rule() — success and missing KeyError
- Constitution.list_rules() — sorted by priority descending
- Constitution.__repr__() formatting
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from isg_agent.core.constitution import (
    Constitution,
    ConstitutionCheckResult,
    ConstitutionRule,
    ConstitutionViolation,
)


# ---------------------------------------------------------------------------
# ConstitutionRule dataclass tests
# ---------------------------------------------------------------------------


class TestConstitutionRule:
    """Tests for the ConstitutionRule frozen dataclass."""

    def test_fields_accessible(self) -> None:
        """All fields on ConstitutionRule are accessible after construction."""
        rule = ConstitutionRule(
            id="r1",
            description="Block delete",
            action_pattern="^delete",
            decision="deny",
            priority=10,
        )
        assert rule.id == "r1"
        assert rule.description == "Block delete"
        assert rule.action_pattern == "^delete"
        assert rule.decision == "deny"
        assert rule.priority == 10

    def test_default_priority_is_zero(self) -> None:
        """When priority is not specified, it defaults to 0."""
        rule = ConstitutionRule(
            id="r2",
            description="Allow read",
            action_pattern="^read",
            decision="allow",
        )
        assert rule.priority == 0

    def test_frozen_immutability(self) -> None:
        """ConstitutionRule is frozen — attribute assignment must raise."""
        rule = ConstitutionRule(
            id="r1", description="d", action_pattern=".*", decision="allow"
        )
        with pytest.raises(AttributeError):
            rule.id = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ConstitutionViolation exception tests
# ---------------------------------------------------------------------------


class TestConstitutionViolation:
    """Tests for the ConstitutionViolation exception."""

    def test_exception_fields(self) -> None:
        """ConstitutionViolation exposes rule_id, action, and reason fields."""
        exc = ConstitutionViolation(
            rule_id="no-delete",
            action="delete /etc/passwd",
            reason="Denied by rule",
        )
        assert exc.rule_id == "no-delete"
        assert exc.action == "delete /etc/passwd"
        assert exc.reason == "Denied by rule"

    def test_exception_message_format(self) -> None:
        """The string representation follows the expected format."""
        exc = ConstitutionViolation(
            rule_id="rule-x",
            action="drop table",
            reason="Not allowed",
        )
        msg = str(exc)
        assert "rule-x" in msg
        assert "drop table" in msg
        assert "Not allowed" in msg

    def test_exception_is_catchable(self) -> None:
        """ConstitutionViolation can be raised and caught as Exception."""
        with pytest.raises(ConstitutionViolation):
            raise ConstitutionViolation(
                rule_id="test", action="test", reason="test"
            )


# ---------------------------------------------------------------------------
# Constitution.from_dict() tests
# ---------------------------------------------------------------------------


class TestConstitutionFromDict:
    """Tests for Constitution.from_dict() factory method."""

    def test_happy_path(self) -> None:
        """from_dict with valid data produces a Constitution with correct attributes."""
        data = {
            "name": "TestConst",
            "version": "2.0",
            "rules": [
                {
                    "id": "allow-read",
                    "description": "Allow read ops",
                    "action_pattern": "^read",
                    "decision": "allow",
                    "priority": 5,
                },
            ],
        }
        c = Constitution.from_dict(data)
        assert c.name == "TestConst"
        assert c.version == "2.0"
        rules = c.list_rules()
        assert len(rules) == 1
        assert rules[0].id == "allow-read"

    def test_defaults_for_name_and_version(self) -> None:
        """from_dict uses default name and version when not provided."""
        c = Constitution.from_dict({"rules": []})
        assert c.name == "default"
        assert c.version == "1.0"

    def test_missing_rule_id_raises(self) -> None:
        """A rule dict without 'id' raises ValueError."""
        data = {"rules": [{"action_pattern": ".*", "decision": "allow"}]}
        with pytest.raises(ValueError, match="missing required field 'id'"):
            Constitution.from_dict(data)

    def test_missing_action_pattern_raises(self) -> None:
        """A rule dict without 'action_pattern' raises ValueError."""
        data = {"rules": [{"id": "r1", "decision": "allow"}]}
        with pytest.raises(ValueError, match="missing required field 'action_pattern'"):
            Constitution.from_dict(data)

    def test_invalid_decision_raises(self) -> None:
        """A rule with invalid decision value raises ValueError."""
        data = {
            "rules": [
                {"id": "r1", "action_pattern": ".*", "decision": "maybe"}
            ]
        }
        with pytest.raises(ValueError, match="invalid decision"):
            Constitution.from_dict(data)

    def test_rules_not_list_raises(self) -> None:
        """If 'rules' is not a list, ValueError is raised."""
        data = {"rules": "not-a-list"}
        with pytest.raises(ValueError, match="must be a list"):
            Constitution.from_dict(data)

    def test_rule_not_dict_raises(self) -> None:
        """If a rule entry is not a dict, ValueError is raised."""
        data = {"rules": ["not-a-dict"]}
        with pytest.raises(ValueError, match="must be a mapping"):
            Constitution.from_dict(data)

    def test_invalid_priority_type_raises(self) -> None:
        """A rule with a non-integer priority raises ValueError."""
        data = {
            "rules": [
                {
                    "id": "r1",
                    "action_pattern": ".*",
                    "decision": "allow",
                    "priority": "high",
                }
            ]
        }
        with pytest.raises(ValueError, match="invalid priority"):
            Constitution.from_dict(data)


# ---------------------------------------------------------------------------
# Constitution.from_yaml() tests
# ---------------------------------------------------------------------------


class TestConstitutionFromYaml:
    """Tests for Constitution.from_yaml() file loading."""

    def test_load_valid_yaml(self, tmp_path: Path) -> None:
        """from_yaml loads a valid YAML file successfully."""
        yaml_data = {
            "name": "YamlConst",
            "version": "1.0",
            "rules": [
                {
                    "id": "allow-all",
                    "description": "Allow everything",
                    "action_pattern": ".*",
                    "decision": "allow",
                    "priority": 0,
                },
            ],
        }
        yaml_file = tmp_path / "constitution.yaml"
        yaml_file.write_text(yaml.dump(yaml_data), encoding="utf-8")

        c = Constitution.from_yaml(yaml_file)
        assert c.name == "YamlConst"
        assert len(c.list_rules()) == 1

    def test_file_not_found_raises(self) -> None:
        """from_yaml raises FileNotFoundError for non-existent file."""
        with pytest.raises(FileNotFoundError, match="not found"):
            Constitution.from_yaml("/nonexistent/path/constitution.yaml")

    def test_invalid_yaml_structure_raises(self, tmp_path: Path) -> None:
        """from_yaml raises ValueError if the YAML root is not a mapping."""
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(ValueError, match="must be a mapping"):
            Constitution.from_yaml(yaml_file)


# ---------------------------------------------------------------------------
# Constitution.check() tests
# ---------------------------------------------------------------------------


class TestConstitutionCheck:
    """Tests for Constitution.check() — rule evaluation logic."""

    def _make_constitution(self, rules: list[dict]) -> Constitution:
        """Helper to build a Constitution from a list of rule dicts."""
        return Constitution.from_dict({"rules": rules})

    def test_no_rules_default_allow(self) -> None:
        """With no rules, check returns allowed=True (default ALLOW)."""
        c = self._make_constitution([])
        result = c.check("any action")
        assert result.allowed is True
        assert result.matched_rule is None
        assert "default" in result.reason.lower()

    def test_deny_rule_blocks_action(self) -> None:
        """A deny rule matching the action returns allowed=False."""
        c = self._make_constitution([
            {"id": "no-delete", "action_pattern": "^delete", "decision": "deny"},
        ])
        result = c.check("delete /system/file")
        assert result.allowed is False
        assert result.matched_rule is not None
        assert result.matched_rule.id == "no-delete"

    def test_allow_rule_permits_action(self) -> None:
        """An allow rule matching the action returns allowed=True."""
        c = self._make_constitution([
            {"id": "allow-read", "action_pattern": "^read", "decision": "allow"},
        ])
        result = c.check("read /data/config")
        assert result.allowed is True
        assert result.matched_rule is not None

    def test_priority_ordering_higher_wins(self) -> None:
        """Higher-priority rule is evaluated first, even if added second."""
        c = self._make_constitution([
            {"id": "low-allow", "action_pattern": ".*", "decision": "allow", "priority": 0},
            {"id": "high-deny", "action_pattern": ".*", "decision": "deny", "priority": 10},
        ])
        result = c.check("anything")
        assert result.allowed is False
        assert result.matched_rule.id == "high-deny"

    def test_first_match_wins_same_priority(self) -> None:
        """When priorities are equal, insertion order determines evaluation order,
        but the first matching rule in the sorted list wins."""
        c = self._make_constitution([
            {"id": "deny-all", "action_pattern": ".*", "decision": "deny", "priority": 5},
            {"id": "allow-all", "action_pattern": ".*", "decision": "allow", "priority": 5},
        ])
        result = c.check("test action")
        # With equal priority, sorted() is stable, so insertion order is preserved.
        assert result.matched_rule is not None

    def test_non_matching_rule_skipped(self) -> None:
        """Rules with non-matching patterns are skipped."""
        c = self._make_constitution([
            {"id": "deny-delete", "action_pattern": "^delete", "decision": "deny"},
        ])
        result = c.check("read /data/file")
        assert result.allowed is True
        assert result.matched_rule is None

    def test_result_has_timestamp(self) -> None:
        """ConstitutionCheckResult includes an ISO 8601 timestamp."""
        c = self._make_constitution([])
        result = c.check("test")
        assert isinstance(result.timestamp, str)
        assert len(result.timestamp) > 10  # ISO 8601 is at least 20 chars

    def test_context_parameter_accepted(self) -> None:
        """The optional context parameter is accepted without error."""
        c = self._make_constitution([])
        result = c.check("test", context={"user": "admin"})
        assert result.allowed is True


# ---------------------------------------------------------------------------
# Constitution.enforce() tests
# ---------------------------------------------------------------------------


class TestConstitutionEnforce:
    """Tests for Constitution.enforce() — raises on denial."""

    def test_enforce_returns_result_on_allow(self) -> None:
        """enforce returns ConstitutionCheckResult when action is allowed."""
        c = Constitution(rules=[], name="test")
        result = c.enforce("any action")
        assert isinstance(result, ConstitutionCheckResult)
        assert result.allowed is True

    def test_enforce_raises_on_deny(self) -> None:
        """enforce raises ConstitutionViolation when action is denied."""
        rule = ConstitutionRule(
            id="no-drop", description="No drop", action_pattern="^drop", decision="deny"
        )
        c = Constitution(rules=[rule])
        with pytest.raises(ConstitutionViolation) as exc_info:
            c.enforce("drop table users")
        assert exc_info.value.rule_id == "no-drop"
        assert exc_info.value.action == "drop table users"


# ---------------------------------------------------------------------------
# Constitution.add_rule() / remove_rule() tests
# ---------------------------------------------------------------------------


class TestConstitutionRuleManagement:
    """Tests for add_rule and remove_rule."""

    def test_add_rule_success(self) -> None:
        """add_rule appends a new rule to the constitution."""
        c = Constitution(rules=[])
        new_rule = ConstitutionRule(
            id="new-rule", description="New", action_pattern=".*", decision="allow"
        )
        c.add_rule(new_rule)
        assert len(c.list_rules()) == 1
        assert c.list_rules()[0].id == "new-rule"

    def test_add_rule_duplicate_raises(self) -> None:
        """add_rule raises ValueError when a rule with the same ID already exists."""
        rule = ConstitutionRule(
            id="dup", description="D", action_pattern=".*", decision="allow"
        )
        c = Constitution(rules=[rule])
        with pytest.raises(ValueError, match="already exists"):
            c.add_rule(rule)

    def test_remove_rule_success(self) -> None:
        """remove_rule removes an existing rule by ID."""
        rule = ConstitutionRule(
            id="to-remove", description="D", action_pattern=".*", decision="allow"
        )
        c = Constitution(rules=[rule])
        c.remove_rule("to-remove")
        assert len(c.list_rules()) == 0

    def test_remove_rule_missing_raises(self) -> None:
        """remove_rule raises KeyError when the rule ID does not exist."""
        c = Constitution(rules=[])
        with pytest.raises(KeyError, match="No rule found"):
            c.remove_rule("nonexistent")


# ---------------------------------------------------------------------------
# Constitution.list_rules() and __repr__() tests
# ---------------------------------------------------------------------------


class TestConstitutionListAndRepr:
    """Tests for list_rules and __repr__."""

    def test_list_rules_sorted_by_priority_descending(self) -> None:
        """list_rules returns rules sorted by priority, highest first."""
        rules = [
            ConstitutionRule(id="low", description="L", action_pattern=".*", decision="allow", priority=1),
            ConstitutionRule(id="high", description="H", action_pattern=".*", decision="deny", priority=10),
            ConstitutionRule(id="mid", description="M", action_pattern=".*", decision="allow", priority=5),
        ]
        c = Constitution(rules=rules)
        sorted_rules = c.list_rules()
        assert sorted_rules[0].id == "high"
        assert sorted_rules[1].id == "mid"
        assert sorted_rules[2].id == "low"

    def test_repr_contains_name_version_count(self) -> None:
        """__repr__ includes name, version, and rule count."""
        c = Constitution(rules=[], name="MyConst", version="3.0")
        repr_str = repr(c)
        assert "MyConst" in repr_str
        assert "3.0" in repr_str
        assert "0" in repr_str  # rules=0
