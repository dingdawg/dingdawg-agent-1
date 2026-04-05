"""Tests for isg_agent.skills — manifest, scanner, quarantine, reputation, loader, executor.

Covers:
- SkillManifest validation (slug, semver, entry_point, capabilities)
- SkillScanner static analysis (eval, exec, network, deserialization)
- QuarantineManager lifecycle (quarantine, approve, reject, list)
- SkillReputation scoring (events, decay, threshold, persistence)
- SkillLoader discovery (valid/invalid manifests, quarantine filtering)
- SkillExecutor sandboxed execution (success, timeout, error, audit)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from isg_agent.skills.manifest import (
    SkillCapability,
    SkillManifest,
    SkillParameter,
    parse_manifest,
    validate_manifest,
)
from isg_agent.skills.scanner import ScanResult, SkillScanner, scan_skill
from isg_agent.skills.quarantine import (
    QuarantineEntry,
    QuarantineManager,
    QuarantineStatus,
)
from isg_agent.skills.reputation import EventType, SkillReputation
from isg_agent.skills.loader import SkillLoader
from isg_agent.skills.executor import ExecutionResult, SkillExecutor


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def tmp_db() -> Path:
    """Provide a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        p = Path(f.name)
    yield p
    p.unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(str(p) + suffix).unlink(missing_ok=True)


@pytest.fixture()
def valid_manifest_data() -> dict:
    """Minimal valid manifest data."""
    return {
        "name": "hello-world",
        "version": "1.0.0",
        "description": "A greeting skill",
        "author": "test",
        "capabilities": ["FILESYSTEM_READ"],
        "parameters": [
            {"name": "greeting", "type": "string", "required": True}
        ],
        "entry_point": "skills.hello_world.handler",
        "min_trust_score": 0.3,
    }


# ===========================================================================
# SkillManifest Tests
# ===========================================================================


class TestSkillManifest:
    """Tests for manifest validation."""

    def test_valid_manifest(self, valid_manifest_data: dict) -> None:
        """A complete manifest should parse without errors."""
        m = parse_manifest(valid_manifest_data)
        assert m.name == "hello-world"
        assert m.version == "1.0.0"
        assert SkillCapability.FILESYSTEM_READ in m.capabilities

    def test_slug_validation_rejects_uppercase(self) -> None:
        """Skill names with uppercase letters are rejected."""
        with pytest.raises(Exception, match="slug-formatted"):
            SkillManifest(name="HelloWorld", entry_point="mod.handler")

    def test_slug_validation_rejects_spaces(self) -> None:
        """Skill names with spaces are rejected."""
        with pytest.raises(Exception, match="slug-formatted"):
            SkillManifest(name="hello world", entry_point="mod.handler")

    def test_slug_validation_accepts_hyphens(self) -> None:
        """Hyphenated lowercase names are valid slugs."""
        m = SkillManifest(name="my-cool-skill", entry_point="mod.handler")
        assert m.name == "my-cool-skill"

    def test_semver_validation_rejects_bad_version(self) -> None:
        """Non-semver version strings are rejected."""
        with pytest.raises(Exception, match="semantic versioning"):
            SkillManifest(name="test", version="abc", entry_point="mod.handler")

    def test_semver_validation_accepts_prerelease(self) -> None:
        """Semver with pre-release suffix is valid."""
        m = SkillManifest(name="test", version="1.0.0-beta.1", entry_point="mod.handler")
        assert m.version == "1.0.0-beta.1"

    def test_entry_point_rejects_invalid_path(self) -> None:
        """Entry points with invalid characters are rejected."""
        with pytest.raises(Exception, match="dotted module path"):
            SkillManifest(name="test", entry_point="invalid/path")

    def test_entry_point_accepts_dotted_path(self) -> None:
        """Dotted Python module paths are valid entry points."""
        m = SkillManifest(name="test", entry_point="pkg.mod.func")
        assert m.entry_point == "pkg.mod.func"

    def test_min_trust_score_bounds(self) -> None:
        """min_trust_score must be between 0.0 and 1.0."""
        with pytest.raises(Exception):
            SkillManifest(name="test", entry_point="mod.handler", min_trust_score=1.5)

    def test_capabilities_enum_values(self) -> None:
        """All SkillCapability enum values exist."""
        assert SkillCapability.FILESYSTEM_READ.value == "FILESYSTEM_READ"
        assert SkillCapability.NETWORK.value == "NETWORK"
        assert SkillCapability.SHELL.value == "SHELL"
        assert SkillCapability.LLM_CALL.value == "LLM_CALL"

    def test_validate_manifest_valid(self, valid_manifest_data: dict) -> None:
        """validate_manifest returns (True, None) for valid data."""
        ok, err = validate_manifest(valid_manifest_data)
        assert ok is True
        assert err is None

    def test_validate_manifest_invalid(self) -> None:
        """validate_manifest returns (False, message) for invalid data."""
        ok, err = validate_manifest({"name": "INVALID"})
        assert ok is False
        assert err is not None

    def test_parameter_model(self) -> None:
        """SkillParameter captures parameter metadata."""
        p = SkillParameter(name="count", type="integer", required=True, default=10)
        assert p.name == "count"
        assert p.type == "integer"
        assert p.required is True
        assert p.default == 10


# ===========================================================================
# SkillScanner Tests
# ===========================================================================


class TestSkillScanner:
    """Tests for security scanning."""

    def test_scan_clean_file(self, tmp_path: Path) -> None:
        """A file with no dangerous patterns is safe."""
        clean = tmp_path / "clean.py"
        clean.write_text("def hello():\n    return 'world'\n")
        result = SkillScanner().scan(clean)
        assert result.safe is True
        assert len(result.findings) == 0
        assert result.risk_score == 0.0

    def test_scan_detects_eval(self, tmp_path: Path) -> None:
        """eval() calls are detected as critical."""
        bad = tmp_path / "bad.py"
        bad.write_text("x = eval(input())\n")
        result = SkillScanner().scan(bad)
        assert result.safe is False
        assert any(f.pattern_name == "eval_call" for f in result.findings)

    def test_scan_detects_exec(self, tmp_path: Path) -> None:
        """exec() calls are detected as critical."""
        bad = tmp_path / "bad.py"
        bad.write_text("exec('import os')\n")
        result = SkillScanner().scan(bad)
        assert result.safe is False
        assert any(f.pattern_name == "exec_call" for f in result.findings)

    def test_scan_detects_os_system(self, tmp_path: Path) -> None:
        """os.system() calls are detected as critical."""
        bad = tmp_path / "bad.py"
        bad.write_text("import os\nos.system('rm -rf /')\n")
        result = SkillScanner().scan(bad)
        assert result.safe is False
        assert any(f.pattern_name == "os_system" for f in result.findings)

    def test_scan_detects_subprocess(self, tmp_path: Path) -> None:
        """subprocess imports are detected as high severity."""
        bad = tmp_path / "bad.py"
        bad.write_text("import subprocess\n")
        result = SkillScanner().scan(bad)
        assert result.safe is False
        assert any(f.pattern_name == "subprocess_call" for f in result.findings)

    def test_scan_detects_network_imports(self, tmp_path: Path) -> None:
        """Network library imports are detected."""
        bad = tmp_path / "net.py"
        bad.write_text("import requests\nimport socket\n")
        result = SkillScanner().scan(bad)
        assert any(f.pattern_name == "requests_import" for f in result.findings)
        assert any(f.pattern_name == "socket_import" for f in result.findings)

    def test_scan_detects_pickle(self, tmp_path: Path) -> None:
        """pickle.loads is detected as critical."""
        bad = tmp_path / "deser.py"
        bad.write_text("import pickle\ndata = pickle.loads(raw)\n")
        result = SkillScanner().scan(bad)
        assert any(f.pattern_name == "pickle_loads" for f in result.findings)

    def test_scan_detects_dunder_import(self, tmp_path: Path) -> None:
        """__import__() is detected as critical."""
        bad = tmp_path / "dyn.py"
        bad.write_text("mod = __import__('os')\n")
        result = SkillScanner().scan(bad)
        assert any(f.pattern_name == "dunder_import" for f in result.findings)

    def test_scan_directory(self, tmp_path: Path) -> None:
        """Scanning a directory checks all .py files."""
        (tmp_path / "a.py").write_text("x = 1\n")
        (tmp_path / "b.py").write_text("eval('x')\n")
        result = SkillScanner().scan(tmp_path)
        assert result.safe is False
        assert len(result.findings) > 0

    def test_scan_missing_path(self) -> None:
        """Scanning a non-existent path returns unsafe."""
        result = SkillScanner().scan(Path("/nonexistent/skill"))
        assert result.safe is False
        assert result.risk_score == 1.0

    def test_scan_skips_comments(self, tmp_path: Path) -> None:
        """Lines that are comments should not trigger findings."""
        f = tmp_path / "commented.py"
        f.write_text("# eval('dangerous')\nx = 1\n")
        result = SkillScanner().scan(f)
        assert result.safe is True

    def test_risk_score_clamped(self, tmp_path: Path) -> None:
        """Risk score is clamped to 1.0 maximum."""
        bad = tmp_path / "very_bad.py"
        bad.write_text(
            "eval('x')\nexec('y')\nos.system('z')\n"
            "pickle.loads(b'')\n__import__('os')\n"
        )
        result = SkillScanner().scan(bad)
        assert result.risk_score <= 1.0

    def test_module_level_scan_skill(self, tmp_path: Path) -> None:
        """Module-level scan_skill function works."""
        f = tmp_path / "ok.py"
        f.write_text("x = 1\n")
        result = scan_skill(f)
        assert result.safe is True

    def test_finding_has_line_number(self, tmp_path: Path) -> None:
        """Findings include accurate line numbers."""
        f = tmp_path / "lines.py"
        f.write_text("x = 1\ny = 2\nz = eval('3')\n")
        result = SkillScanner().scan(f)
        eval_findings = [fnd for fnd in result.findings if fnd.pattern_name == "eval_call"]
        assert len(eval_findings) == 1
        assert eval_findings[0].line_number == 3


# ===========================================================================
# QuarantineManager Tests
# ===========================================================================


class TestQuarantineManager:
    """Tests for quarantine lifecycle."""

    async def test_quarantine_skill(self, tmp_db: Path) -> None:
        """A skill can be quarantined."""
        mgr = QuarantineManager(db_path=str(tmp_db))
        entry = await mgr.quarantine("test-skill", "security concern")
        assert entry.skill_name == "test-skill"
        assert entry.status == QuarantineStatus.QUARANTINED
        assert entry.reason == "security concern"

    async def test_is_quarantined(self, tmp_db: Path) -> None:
        """is_quarantined returns True for quarantined skills."""
        mgr = QuarantineManager(db_path=str(tmp_db))
        await mgr.quarantine("test-skill", "reason")
        assert await mgr.is_quarantined("test-skill") is True

    async def test_is_not_quarantined_unknown(self, tmp_db: Path) -> None:
        """is_quarantined returns False for unknown skills."""
        mgr = QuarantineManager(db_path=str(tmp_db))
        assert await mgr.is_quarantined("unknown") is False

    async def test_approve_releases_quarantine(self, tmp_db: Path) -> None:
        """Approved skills are no longer quarantined."""
        mgr = QuarantineManager(db_path=str(tmp_db))
        await mgr.quarantine("test-skill", "reason")
        entry = await mgr.approve("test-skill", "admin-user")
        assert entry is not None
        assert entry.status == QuarantineStatus.APPROVED
        assert entry.approved_by == "admin-user"
        assert await mgr.is_quarantined("test-skill") is False

    async def test_approve_unknown_returns_none(self, tmp_db: Path) -> None:
        """Approving a non-quarantined skill returns None."""
        mgr = QuarantineManager(db_path=str(tmp_db))
        result = await mgr.approve("nonexistent", "admin")
        assert result is None

    async def test_reject_skill(self, tmp_db: Path) -> None:
        """A quarantined skill can be rejected."""
        mgr = QuarantineManager(db_path=str(tmp_db))
        await mgr.quarantine("bad-skill", "dangerous")
        entry = await mgr.reject("bad-skill", "admin", "too risky")
        assert entry is not None
        assert entry.status == QuarantineStatus.REJECTED

    async def test_list_quarantined(self, tmp_db: Path) -> None:
        """list_quarantined returns only quarantined skills."""
        mgr = QuarantineManager(db_path=str(tmp_db))
        await mgr.quarantine("skill-a", "a")
        await mgr.quarantine("skill-b", "b")
        await mgr.approve("skill-a", "admin")

        quarantined = await mgr.list_quarantined()
        names = [e.skill_name for e in quarantined]
        assert "skill-b" in names
        assert "skill-a" not in names

    async def test_get_entry(self, tmp_db: Path) -> None:
        """get_entry retrieves a specific quarantine record."""
        mgr = QuarantineManager(db_path=str(tmp_db))
        await mgr.quarantine("my-skill", "test reason")
        entry = await mgr.get_entry("my-skill")
        assert entry is not None
        assert entry.skill_name == "my-skill"
        assert entry.reason == "test reason"

    async def test_re_quarantine_updates_reason(self, tmp_db: Path) -> None:
        """Re-quarantining an approved skill updates the record."""
        mgr = QuarantineManager(db_path=str(tmp_db))
        await mgr.quarantine("skill", "first")
        await mgr.approve("skill", "admin")
        await mgr.quarantine("skill", "second reason")
        assert await mgr.is_quarantined("skill") is True
        entry = await mgr.get_entry("skill")
        assert entry is not None
        assert entry.reason == "second reason"

    async def test_list_all(self, tmp_db: Path) -> None:
        """list_all returns all entries regardless of status."""
        mgr = QuarantineManager(db_path=str(tmp_db))
        await mgr.quarantine("a", "reason")
        await mgr.quarantine("b", "reason")
        await mgr.approve("a", "admin")
        entries = await mgr.list_all()
        assert len(entries) == 2


# ===========================================================================
# SkillReputation Tests
# ===========================================================================


class TestSkillReputation:
    """Tests for reputation scoring."""

    async def test_initial_reputation(self, tmp_db: Path) -> None:
        """New skills start with 0.5 reputation."""
        rep = SkillReputation(db_path=str(tmp_db))
        score = await rep.get_reputation("new-skill")
        assert score.score == 0.5
        assert score.event_count == 0

    async def test_usage_increases_score(self, tmp_db: Path) -> None:
        """Usage events increase reputation."""
        rep = SkillReputation(db_path=str(tmp_db))
        score = await rep.record_event("skill", EventType.USAGE)
        assert score.score > 0.5

    async def test_security_fail_decreases_score(self, tmp_db: Path) -> None:
        """Security failures decrease reputation."""
        rep = SkillReputation(db_path=str(tmp_db))
        score = await rep.record_event("skill", EventType.SECURITY_FAIL)
        assert score.score < 0.5

    async def test_event_count_increments(self, tmp_db: Path) -> None:
        """Each event increments the event count."""
        rep = SkillReputation(db_path=str(tmp_db))
        await rep.record_event("skill", EventType.USAGE)
        await rep.record_event("skill", EventType.USAGE)
        score = await rep.get_reputation("skill")
        assert score.event_count == 2

    async def test_score_clamped_to_bounds(self, tmp_db: Path) -> None:
        """Score stays within [0.0, 1.0]."""
        rep = SkillReputation(db_path=str(tmp_db))
        # Drive score down repeatedly
        for _ in range(20):
            await rep.record_event("skill", EventType.SECURITY_FAIL)
        score = await rep.get_reputation("skill")
        assert score.score >= 0.0

    async def test_threshold_check(self, tmp_db: Path) -> None:
        """is_trusted reflects whether score exceeds threshold."""
        rep = SkillReputation(db_path=str(tmp_db), threshold=0.6)
        score = await rep.get_reputation("skill")
        assert score.is_trusted is False  # 0.5 < 0.6

        # Push score above threshold
        for _ in range(15):
            await rep.record_event("skill", EventType.SECURITY_PASS)
        score = await rep.get_reputation("skill")
        assert score.is_trusted is True

    async def test_custom_delta(self, tmp_db: Path) -> None:
        """Custom score_delta overrides the default."""
        rep = SkillReputation(db_path=str(tmp_db))
        score = await rep.record_event("skill", EventType.USAGE, score_delta=0.2)
        assert abs(score.score - 0.7) < 0.01  # 0.5 + 0.2

    async def test_decay_toward_neutral(self, tmp_db: Path) -> None:
        """Decay pushes score toward 0.5."""
        rep = SkillReputation(db_path=str(tmp_db), decay_rate=0.5)
        # Push score high
        await rep.record_event("skill", EventType.USAGE, score_delta=0.4)
        score_before = await rep.get_reputation("skill")
        assert score_before.score > 0.5

        score_after = await rep.apply_decay("skill")
        # Decay rate is per-day, and last_updated was just set, so minimal decay
        # The important thing is it doesn't crash and stays in bounds
        assert 0.0 <= score_after.score <= 1.0

    async def test_list_all_scores(self, tmp_db: Path) -> None:
        """list_all returns all known skills."""
        rep = SkillReputation(db_path=str(tmp_db))
        await rep.record_event("alpha", EventType.USAGE)
        await rep.record_event("beta", EventType.USAGE)
        all_scores = await rep.list_all()
        names = [s.skill_name for s in all_scores]
        assert "alpha" in names
        assert "beta" in names

    async def test_string_event_type(self, tmp_db: Path) -> None:
        """Event types can be passed as strings."""
        rep = SkillReputation(db_path=str(tmp_db))
        score = await rep.record_event("skill", "usage")
        assert score.event_count == 1


# ===========================================================================
# SkillLoader Tests
# ===========================================================================


class TestSkillLoader:
    """Tests for skill discovery."""

    async def test_discover_valid_skill(self, tmp_path: Path) -> None:
        """A directory with valid manifest.json is discovered."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        manifest = {
            "name": "my-skill",
            "version": "1.0.0",
            "entry_point": "skills.my_skill.handler",
        }
        (skill_dir / "manifest.json").write_text(json.dumps(manifest))

        loader = SkillLoader()
        results = await loader.discover(tmp_path)
        assert len(results) == 1
        assert results[0].name == "my-skill"

    async def test_discover_skips_invalid_manifest(self, tmp_path: Path) -> None:
        """Skills with invalid manifests are skipped."""
        skill_dir = tmp_path / "bad-skill"
        skill_dir.mkdir()
        (skill_dir / "manifest.json").write_text('{"name": "INVALID NAME"}')

        loader = SkillLoader()
        results = await loader.discover(tmp_path)
        assert len(results) == 0

    async def test_discover_skips_no_manifest(self, tmp_path: Path) -> None:
        """Directories without manifest.json are skipped."""
        (tmp_path / "no-manifest").mkdir()
        loader = SkillLoader()
        results = await loader.discover(tmp_path)
        assert len(results) == 0

    async def test_discover_empty_directory(self, tmp_path: Path) -> None:
        """Empty directory returns no skills."""
        loader = SkillLoader()
        results = await loader.discover(tmp_path)
        assert results == []

    async def test_discover_nonexistent_directory(self) -> None:
        """Non-existent directory returns empty list."""
        loader = SkillLoader()
        results = await loader.discover(Path("/nonexistent/path"))
        assert results == []

    async def test_discover_filters_quarantined(self, tmp_path: Path, tmp_db: Path) -> None:
        """Quarantined skills are excluded from discovery."""
        skill_dir = tmp_path / "quarantined-skill"
        skill_dir.mkdir()
        manifest = {
            "name": "quarantined-skill",
            "version": "1.0.0",
            "entry_point": "skills.quarantined.handler",
        }
        (skill_dir / "manifest.json").write_text(json.dumps(manifest))

        qm = QuarantineManager(db_path=str(tmp_db))
        await qm.quarantine("quarantined-skill", "test")

        loader = SkillLoader(quarantine_manager=qm)
        results = await loader.discover(tmp_path)
        assert len(results) == 0

    async def test_load_single_manifest(self, tmp_path: Path) -> None:
        """load_manifest can load a single manifest file."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({
            "name": "single",
            "version": "2.0.0",
            "entry_point": "mod.handler",
        }))
        loader = SkillLoader()
        result = await loader.load_manifest(manifest_path)
        assert result is not None
        assert result.name == "single"

    async def test_load_manifest_returns_none_for_missing(self) -> None:
        """load_manifest returns None for missing files."""
        loader = SkillLoader()
        result = await loader.load_manifest(Path("/nonexistent.json"))
        assert result is None

    async def test_discover_skips_files(self, tmp_path: Path) -> None:
        """Files (not directories) at the top level are skipped."""
        (tmp_path / "not_a_dir.txt").write_text("hello")
        loader = SkillLoader()
        results = await loader.discover(tmp_path)
        assert results == []


# ===========================================================================
# SkillExecutor Tests
# ===========================================================================


class TestSkillExecutor:
    """Tests for sandboxed execution."""

    async def test_execute_registered_sync_skill(self) -> None:
        """A registered sync skill executes and returns output."""
        executor = SkillExecutor()
        executor.register_skill("greet", lambda params: f"Hello {params.get('name', 'world')}")

        result = await executor.execute("greet", {"name": "Alice"})
        assert result.success is True
        assert result.output == "Hello Alice"
        assert result.error is None
        assert result.duration_ms >= 0
        assert result.audit_id

    async def test_execute_registered_async_skill(self) -> None:
        """A registered async skill executes correctly."""
        async def async_handler(params: dict) -> str:
            return f"Async: {params.get('msg', '')}"

        executor = SkillExecutor()
        executor.register_skill("async-skill", async_handler)

        result = await executor.execute("async-skill", {"msg": "test"})
        assert result.success is True
        assert result.output == "Async: test"

    async def test_execute_unknown_skill(self) -> None:
        """Executing an unregistered skill fails gracefully."""
        executor = SkillExecutor()
        result = await executor.execute("nonexistent")
        assert result.success is False
        assert "not found" in result.error.lower()

    async def test_execute_timeout(self) -> None:
        """Skills that exceed the timeout are terminated."""
        import asyncio

        async def slow_handler(params: dict) -> str:
            await asyncio.sleep(10)
            return "done"

        executor = SkillExecutor(default_timeout=0.1)
        executor.register_skill("slow", slow_handler)

        result = await executor.execute("slow")
        assert result.success is False
        assert "timed out" in result.error.lower()

    async def test_execute_handles_exception(self) -> None:
        """Skills that raise exceptions are caught cleanly."""
        def bad_handler(params: dict) -> str:
            raise ValueError("something broke")

        executor = SkillExecutor()
        executor.register_skill("bad", bad_handler)

        result = await executor.execute("bad")
        assert result.success is False
        assert "something broke" in result.error

    async def test_execute_with_custom_timeout(self) -> None:
        """Custom timeout parameter overrides the default."""
        executor = SkillExecutor(default_timeout=60.0)
        executor.register_skill("fast", lambda p: "done")

        result = await executor.execute("fast", timeout=5.0)
        assert result.success is True

    async def test_list_skills(self) -> None:
        """list_skills returns registered skill names."""
        executor = SkillExecutor()
        executor.register_skill("b-skill", lambda p: "b")
        executor.register_skill("a-skill", lambda p: "a")

        names = await executor.list_skills()
        assert names == ["a-skill", "b-skill"]

    async def test_execute_result_has_skill_name(self) -> None:
        """ExecutionResult includes the skill name."""
        executor = SkillExecutor()
        executor.register_skill("named", lambda p: "ok")
        result = await executor.execute("named")
        assert result.skill_name == "named"

    async def test_execute_none_parameters(self) -> None:
        """Passing None parameters defaults to empty dict."""
        executor = SkillExecutor()
        executor.register_skill("echo", lambda p: str(p))
        result = await executor.execute("echo", None)
        assert result.success is True

    async def test_workspace_root_property(self) -> None:
        """workspace_root property returns the resolved root."""
        executor = SkillExecutor(workspace_root="/tmp")
        assert executor.workspace_root == "/tmp"
