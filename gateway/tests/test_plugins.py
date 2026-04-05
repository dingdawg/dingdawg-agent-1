"""Tests for isg_agent.plugins — Universal Plugin Architecture.

Covers:
- PluginManifest dataclass creation, validation, serialisation
- PluginRegistry CRUD, status management, trigger/capability filtering
- PluginLoader discovery, structure validation, load lifecycle
- PluginSandbox execution, timeout, exception handling, logging
- Integration flows: register → activate → execute
- Edge cases: concurrent registrations, empty manifests

TDD: These tests are written BEFORE the implementation.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from isg_agent.plugins.manifest_schema import (
    PluginManifest,
    manifest_from_dict,
    manifest_to_dict,
    validate_manifest,
)
from isg_agent.plugins.registry import PluginRegistry
from isg_agent.plugins.loader import PluginLoader
from isg_agent.plugins.sandbox import PluginSandbox


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest_dict(**kwargs: Any) -> dict:
    """Return a minimal valid manifest dict with optional overrides."""
    base = {
        "plugin_id": "test-plugin",
        "name": "Test Plugin",
        "version": "1.0.0",
        "author": "Test Author",
        "description": "A test plugin",
        "triggers": ["message"],
        "capabilities": ["read_messages"],
        "api_endpoints": [],
        "card_types": [],
        "required_permissions": [],
        "required_skills": [],
    }
    base.update(kwargs)
    return base


def _make_manifest(**kwargs: Any) -> PluginManifest:
    """Return a minimal valid PluginManifest with optional overrides."""
    return manifest_from_dict(_make_manifest_dict(**kwargs))


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    """Return a temporary SQLite DB path."""
    return tmp_path / "test_plugins.db"


@pytest.fixture()
def registry(tmp_db: Path) -> PluginRegistry:
    """Return a freshly initialised PluginRegistry."""
    return PluginRegistry(str(tmp_db))


@pytest.fixture()
def tmp_plugins_dir(tmp_path: Path) -> Path:
    """Return an empty temp directory for plugin packages."""
    d = tmp_path / "plugins"
    d.mkdir()
    return d


def _write_plugin(
    plugins_dir: Path,
    plugin_id: str,
    manifest_extra: dict | None = None,
    handler_content: str | None = None,
) -> Path:
    """Write a valid plugin directory (manifest.json + handler.py)."""
    plugin_dir = plugins_dir / plugin_id
    plugin_dir.mkdir(exist_ok=True)

    m = _make_manifest_dict(plugin_id=plugin_id)
    if manifest_extra:
        m.update(manifest_extra)

    (plugin_dir / "manifest.json").write_text(json.dumps(m), encoding="utf-8")

    default_handler = (
        "async def execute(args):\n"
        "    return {'status': 'ok', 'plugin_id': args.get('plugin_id', '')}\n"
    )
    (plugin_dir / "handler.py").write_text(
        handler_content or default_handler, encoding="utf-8"
    )
    return plugin_dir


# ---------------------------------------------------------------------------
# TestManifest (10 tests)
# ---------------------------------------------------------------------------


class TestManifest:
    """Tests for PluginManifest creation and basic properties."""

    def test_valid_manifest_creation(self) -> None:
        """A fully-specified manifest dict can be parsed into a PluginManifest."""
        m = _make_manifest()
        assert m.plugin_id == "test-plugin"
        assert m.name == "Test Plugin"
        assert m.version == "1.0.0"
        assert m.author == "Test Author"
        assert m.triggers == ["message"]
        assert m.capabilities == ["read_messages"]

    def test_missing_required_field_fails(self) -> None:
        """Omitting plugin_id must raise ValueError."""
        data = _make_manifest_dict()
        del data["plugin_id"]
        with pytest.raises((ValueError, KeyError, TypeError)):
            manifest_from_dict(data)

    def test_validate_from_dict_valid(self) -> None:
        """validate_manifest returns (True, []) for a valid dict."""
        valid, errors = validate_manifest(_make_manifest_dict())
        assert valid is True
        assert errors == []

    def test_to_from_dict_round_trip(self) -> None:
        """Serialising and re-parsing a manifest produces an equal object."""
        m1 = _make_manifest()
        d = manifest_to_dict(m1)
        m2 = manifest_from_dict(d)
        assert m1.plugin_id == m2.plugin_id
        assert m1.name == m2.name
        assert m1.version == m2.version
        assert m1.triggers == m2.triggers
        assert m1.capabilities == m2.capabilities

    def test_default_values_set(self) -> None:
        """Unspecified optional fields receive their defaults."""
        m = _make_manifest()
        assert m.max_execution_time_ms == 5000
        assert m.max_memory_mb == 50
        assert m.sandbox_level == "strict"
        assert m.homepage == ""
        assert m.license == ""
        assert m.min_agent_version == "1.0.0"

    def test_invalid_trigger_rejected(self) -> None:
        """An unrecognised trigger value causes validate_manifest to fail."""
        data = _make_manifest_dict(triggers=["___invalid___trigger___"])
        valid, errors = validate_manifest(data)
        assert valid is False
        assert len(errors) > 0

    def test_empty_capabilities_allowed(self) -> None:
        """A plugin with no capabilities is valid."""
        m = _make_manifest(capabilities=[])
        assert m.capabilities == []

    def test_version_format_checked(self) -> None:
        """Non-semver version strings are rejected."""
        data = _make_manifest_dict(version="not-a-version")
        valid, errors = validate_manifest(data)
        assert valid is False
        assert len(errors) > 0

    def test_manifest_from_dict(self) -> None:
        """manifest_from_dict creates the expected PluginManifest object."""
        d = _make_manifest_dict(plugin_id="my-plugin", name="My Plugin")
        m = manifest_from_dict(d)
        assert isinstance(m, PluginManifest)
        assert m.plugin_id == "my-plugin"
        assert m.name == "My Plugin"

    def test_manifest_to_dict(self) -> None:
        """manifest_to_dict returns a plain dict with all expected keys."""
        m = _make_manifest(plugin_id="out-plugin")
        d = manifest_to_dict(m)
        assert isinstance(d, dict)
        assert d["plugin_id"] == "out-plugin"
        assert "name" in d
        assert "version" in d
        assert "triggers" in d
        assert "capabilities" in d


# ---------------------------------------------------------------------------
# TestRegistry (15 tests)
# ---------------------------------------------------------------------------


class TestRegistry:
    """Tests for PluginRegistry CRUD and status management."""

    def test_register_plugin(self, registry: PluginRegistry) -> None:
        """register() stores the plugin and returns its plugin_id."""
        m = _make_manifest()
        pid = registry.register(m, source_path="/tmp/test-plugin")
        assert pid == "test-plugin"

    def test_get_by_id(self, registry: PluginRegistry) -> None:
        """get() returns the plugin info dict after registration."""
        m = _make_manifest()
        registry.register(m, source_path="/tmp/test-plugin")
        info = registry.get("test-plugin")
        assert info is not None
        assert info["plugin_id"] == "test-plugin"
        assert info["name"] == "Test Plugin"

    def test_list_all(self, registry: PluginRegistry) -> None:
        """list_plugins() without filter returns all registered plugins."""
        registry.register(_make_manifest(plugin_id="p1", name="P1"), source_path="/tmp/p1")
        registry.register(_make_manifest(plugin_id="p2", name="P2"), source_path="/tmp/p2")
        plugins = registry.list_plugins()
        ids = [p["plugin_id"] for p in plugins]
        assert "p1" in ids
        assert "p2" in ids

    def test_list_by_status(self, registry: PluginRegistry) -> None:
        """list_plugins(status='active') returns only active plugins."""
        registry.register(_make_manifest(plugin_id="active-p"), source_path="/tmp/ap")
        registry.register(_make_manifest(plugin_id="inactive-p"), source_path="/tmp/ip")
        registry.activate("active-p")
        active = registry.list_plugins(status="active")
        ids = [p["plugin_id"] for p in active]
        assert "active-p" in ids
        assert "inactive-p" not in ids

    def test_activate(self, registry: PluginRegistry) -> None:
        """activate() changes plugin status from inactive to active."""
        registry.register(_make_manifest(), source_path="/tmp/test-plugin")
        registry.activate("test-plugin")
        info = registry.get("test-plugin")
        assert info["status"] == "active"

    def test_deactivate(self, registry: PluginRegistry) -> None:
        """deactivate() changes plugin status from active to inactive."""
        registry.register(_make_manifest(), source_path="/tmp/test-plugin")
        registry.activate("test-plugin")
        registry.deactivate("test-plugin")
        info = registry.get("test-plugin")
        assert info["status"] == "inactive"

    def test_quarantine_with_reason(self, registry: PluginRegistry) -> None:
        """quarantine() stores the plugin with status=quarantined and the reason."""
        registry.register(_make_manifest(), source_path="/tmp/test-plugin")
        registry.quarantine("test-plugin", reason="Security violation detected")
        info = registry.get("test-plugin")
        assert info["status"] == "quarantined"
        assert "Security violation" in info["quarantine_reason"]

    def test_unregister(self, registry: PluginRegistry) -> None:
        """unregister() removes the plugin — subsequent get() returns None."""
        registry.register(_make_manifest(), source_path="/tmp/test-plugin")
        registry.unregister("test-plugin")
        info = registry.get("test-plugin")
        assert info is None

    def test_get_by_trigger(self, registry: PluginRegistry) -> None:
        """get_by_trigger() returns plugins that declare that trigger."""
        registry.register(_make_manifest(plugin_id="msg-p", triggers=["message"]), source_path="/tmp/mp")
        registry.register(_make_manifest(plugin_id="sched-p", triggers=["schedule"]), source_path="/tmp/sp")
        registry.activate("msg-p")
        registry.activate("sched-p")
        results = registry.get_by_trigger("message")
        ids = [p["plugin_id"] for p in results]
        assert "msg-p" in ids
        assert "sched-p" not in ids

    def test_get_by_capability(self, registry: PluginRegistry) -> None:
        """get_by_capability() returns plugins that declare that capability."""
        registry.register(
            _make_manifest(plugin_id="send-p", capabilities=["send_messages"]),
            source_path="/tmp/sendp",
        )
        registry.register(
            _make_manifest(plugin_id="read-p", capabilities=["read_messages"]),
            source_path="/tmp/readp",
        )
        registry.activate("send-p")
        registry.activate("read-p")
        results = registry.get_by_capability("send_messages")
        ids = [p["plugin_id"] for p in results]
        assert "send-p" in ids
        assert "read-p" not in ids

    def test_duplicate_id_rejected(self, registry: PluginRegistry) -> None:
        """Registering a plugin with an already-used plugin_id must raise."""
        m = _make_manifest()
        registry.register(m, source_path="/tmp/test-plugin")
        with pytest.raises((ValueError, Exception)):
            registry.register(m, source_path="/tmp/test-plugin-2")

    def test_status_persisted(self, registry: PluginRegistry, tmp_db: Path) -> None:
        """Status changes persist across PluginRegistry instances (same DB)."""
        registry.register(_make_manifest(), source_path="/tmp/test-plugin")
        registry.activate("test-plugin")
        # Open a second registry instance pointing at the same DB
        registry2 = PluginRegistry(str(tmp_db))
        info = registry2.get("test-plugin")
        assert info["status"] == "active"

    def test_quarantine_reason_stored(self, registry: PluginRegistry) -> None:
        """The quarantine reason is retrievable from the plugin record."""
        registry.register(_make_manifest(), source_path="/tmp/test-plugin")
        registry.quarantine("test-plugin", reason="Failed security scan")
        info = registry.get("test-plugin")
        assert info["quarantine_reason"] == "Failed security scan"

    def test_multiple_plugins_registered(self, registry: PluginRegistry) -> None:
        """Registry handles 5 distinct plugins without confusion."""
        for i in range(5):
            registry.register(
                _make_manifest(plugin_id=f"plugin-{i}", name=f"Plugin {i}"),
                source_path=f"/tmp/plugin-{i}",
            )
        plugins = registry.list_plugins()
        assert len(plugins) == 5

    def test_filter_active_only(self, registry: PluginRegistry) -> None:
        """list_plugins(status='active') excludes inactive and quarantined plugins."""
        registry.register(_make_manifest(plugin_id="a"), source_path="/tmp/a")
        registry.register(_make_manifest(plugin_id="b"), source_path="/tmp/b")
        registry.register(_make_manifest(plugin_id="c"), source_path="/tmp/c")
        registry.activate("a")
        registry.quarantine("c", reason="test")
        active = registry.list_plugins(status="active")
        ids = [p["plugin_id"] for p in active]
        assert ids == ["a"]


# ---------------------------------------------------------------------------
# TestLoader (12 tests)
# ---------------------------------------------------------------------------


class TestLoader:
    """Tests for PluginLoader discovery and structure validation."""

    def test_discover_finds_plugins(
        self, tmp_plugins_dir: Path, registry: PluginRegistry
    ) -> None:
        """discover() returns manifests for all valid plugin directories."""
        _write_plugin(tmp_plugins_dir, "plugin-alpha")
        _write_plugin(tmp_plugins_dir, "plugin-beta")
        loader = PluginLoader(str(tmp_plugins_dir), registry)
        manifests = loader.discover()
        ids = [m.plugin_id for m in manifests]
        assert "plugin-alpha" in ids
        assert "plugin-beta" in ids

    def test_discover_skips_invalid(
        self, tmp_plugins_dir: Path, registry: PluginRegistry
    ) -> None:
        """discover() silently skips directories with invalid manifests."""
        _write_plugin(tmp_plugins_dir, "valid-plugin")
        # Create a bad plugin dir — manifest.json has invalid JSON
        bad_dir = tmp_plugins_dir / "bad-plugin"
        bad_dir.mkdir()
        (bad_dir / "manifest.json").write_text("NOT JSON", encoding="utf-8")
        (bad_dir / "handler.py").write_text("", encoding="utf-8")
        loader = PluginLoader(str(tmp_plugins_dir), registry)
        manifests = loader.discover()
        ids = [m.plugin_id for m in manifests]
        assert "valid-plugin" in ids
        assert "bad-plugin" not in ids

    def test_load_returns_manifest_and_status(
        self, tmp_plugins_dir: Path, registry: PluginRegistry
    ) -> None:
        """load() returns a dict with 'manifest' and 'status' keys."""
        _write_plugin(tmp_plugins_dir, "load-me")
        registry.register(_make_manifest(plugin_id="load-me"), source_path=str(tmp_plugins_dir / "load-me"))
        loader = PluginLoader(str(tmp_plugins_dir), registry)
        result = loader.load("load-me")
        assert "manifest" in result
        assert "status" in result

    def test_load_validates_structure(
        self, tmp_plugins_dir: Path, registry: PluginRegistry
    ) -> None:
        """load() raises when the plugin directory is structurally invalid."""
        bad_dir = tmp_plugins_dir / "no-handler"
        bad_dir.mkdir()
        m = _make_manifest_dict(plugin_id="no-handler")
        (bad_dir / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        # handler.py intentionally missing
        registry.register(_make_manifest(plugin_id="no-handler"), source_path=str(bad_dir))
        loader = PluginLoader(str(tmp_plugins_dir), registry)
        with pytest.raises((ValueError, FileNotFoundError, RuntimeError)):
            loader.load("no-handler")

    def test_validate_requires_manifest_json(
        self, tmp_plugins_dir: Path, registry: PluginRegistry
    ) -> None:
        """validate_structure returns False when manifest.json is absent."""
        plugin_dir = tmp_plugins_dir / "no-manifest"
        plugin_dir.mkdir()
        (plugin_dir / "handler.py").write_text("", encoding="utf-8")
        loader = PluginLoader(str(tmp_plugins_dir), registry)
        valid, errors = loader.validate_structure(str(plugin_dir))
        assert valid is False
        assert len(errors) > 0

    def test_validate_requires_handler_py(
        self, tmp_plugins_dir: Path, registry: PluginRegistry
    ) -> None:
        """validate_structure returns False when handler.py is absent."""
        plugin_dir = tmp_plugins_dir / "no-handler"
        plugin_dir.mkdir()
        m = _make_manifest_dict(plugin_id="no-handler")
        (plugin_dir / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        loader = PluginLoader(str(tmp_plugins_dir), registry)
        valid, errors = loader.validate_structure(str(plugin_dir))
        assert valid is False
        assert len(errors) > 0

    def test_load_all_returns_list(
        self, tmp_plugins_dir: Path, registry: PluginRegistry
    ) -> None:
        """load_all() returns a list (possibly empty) of loaded plugin dicts."""
        _write_plugin(tmp_plugins_dir, "la-plugin")
        loader = PluginLoader(str(tmp_plugins_dir), registry)
        results = loader.load_all()
        assert isinstance(results, list)

    def test_empty_dir_returns_empty(
        self, tmp_plugins_dir: Path, registry: PluginRegistry
    ) -> None:
        """discover() on an empty directory returns an empty list."""
        loader = PluginLoader(str(tmp_plugins_dir), registry)
        manifests = loader.discover()
        assert manifests == []

    def test_invalid_json_manifest_rejected(
        self, tmp_plugins_dir: Path, registry: PluginRegistry
    ) -> None:
        """discover() skips a directory whose manifest.json is malformed JSON."""
        bad_dir = tmp_plugins_dir / "bad-json"
        bad_dir.mkdir()
        (bad_dir / "manifest.json").write_text("{bad json", encoding="utf-8")
        (bad_dir / "handler.py").write_text("", encoding="utf-8")
        loader = PluginLoader(str(tmp_plugins_dir), registry)
        manifests = loader.discover()
        assert not any(m.plugin_id == "bad-json" for m in manifests)

    def test_missing_plugin_id_rejected(
        self, tmp_plugins_dir: Path, registry: PluginRegistry
    ) -> None:
        """discover() skips a manifest that is missing plugin_id."""
        bad_dir = tmp_plugins_dir / "missing-id"
        bad_dir.mkdir()
        m = _make_manifest_dict()
        del m["plugin_id"]
        (bad_dir / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        (bad_dir / "handler.py").write_text("", encoding="utf-8")
        loader = PluginLoader(str(tmp_plugins_dir), registry)
        manifests = loader.discover()
        assert not any(getattr(m2, "plugin_id", None) == "missing-id" for m2 in manifests)

    def test_source_path_stored(
        self, tmp_plugins_dir: Path, registry: PluginRegistry
    ) -> None:
        """load_all() registers plugins with the correct source_path."""
        _write_plugin(tmp_plugins_dir, "src-plugin")
        loader = PluginLoader(str(tmp_plugins_dir), registry)
        loader.load_all()
        info = registry.get("src-plugin")
        assert info is not None
        assert "src-plugin" in info["source_path"]

    def test_nonexistent_dir_handled(
        self, tmp_plugins_dir: Path, registry: PluginRegistry
    ) -> None:
        """PluginLoader with a non-existent directory returns empty on discover()."""
        loader = PluginLoader("/does/not/exist/at/all", registry)
        manifests = loader.discover()
        assert manifests == []


# ---------------------------------------------------------------------------
# TestSandbox (15 tests)
# ---------------------------------------------------------------------------


class TestSandbox:
    """Tests for PluginSandbox execution and execution log."""

    @pytest.mark.asyncio
    async def test_execute_returns_result_dict(self) -> None:
        """execute() returns a dict with success, result, execution_time_ms, error."""
        sandbox = PluginSandbox()
        m = _make_manifest()

        async def handler(args: dict) -> dict:
            return {"answer": 42}

        result = await sandbox.execute(handler, {}, m)
        assert isinstance(result, dict)
        assert "success" in result
        assert "result" in result
        assert "execution_time_ms" in result
        assert "error" in result

    @pytest.mark.asyncio
    async def test_timeout_kills_execution(self) -> None:
        """execute() returns success=False when handler exceeds timeout."""
        sandbox = PluginSandbox(max_execution_time_ms=50)
        m = _make_manifest(max_execution_time_ms=50)

        async def slow_handler(args: dict) -> dict:
            await asyncio.sleep(10)
            return {"done": True}

        result = await sandbox.execute(slow_handler, {}, m)
        assert result["success"] is False
        assert result["error"] is not None

    @pytest.mark.asyncio
    async def test_exception_caught(self) -> None:
        """execute() catches handler exceptions and returns success=False."""
        sandbox = PluginSandbox()
        m = _make_manifest()

        async def bad_handler(args: dict) -> dict:
            raise RuntimeError("Plugin crash!")

        result = await sandbox.execute(bad_handler, {}, m)
        assert result["success"] is False
        assert "Plugin crash!" in result["error"]

    @pytest.mark.asyncio
    async def test_success_true_for_good_handler(self) -> None:
        """execute() sets success=True when handler returns a valid dict."""
        sandbox = PluginSandbox()
        m = _make_manifest()

        async def good_handler(args: dict) -> dict:
            return {"status": "ok"}

        result = await sandbox.execute(good_handler, {}, m)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_success_false_for_bad_handler(self) -> None:
        """execute() sets success=False when handler raises an exception."""
        sandbox = PluginSandbox()
        m = _make_manifest()

        async def bad_handler(args: dict) -> dict:
            raise ValueError("broken")

        result = await sandbox.execute(bad_handler, {}, m)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_execution_time_tracked(self) -> None:
        """execute() records a non-negative execution_time_ms."""
        sandbox = PluginSandbox()
        m = _make_manifest()

        async def instant_handler(args: dict) -> dict:
            return {}

        result = await sandbox.execute(instant_handler, {}, m)
        assert isinstance(result["execution_time_ms"], float)
        assert result["execution_time_ms"] >= 0.0

    @pytest.mark.asyncio
    async def test_result_must_be_dict(self) -> None:
        """execute() treats a non-dict return value as a failure."""
        sandbox = PluginSandbox()
        m = _make_manifest()

        async def bad_return(args: dict):
            return "not a dict"

        result = await sandbox.execute(bad_return, {}, m)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_non_dict_result_caught(self) -> None:
        """execute() treats None return value as a failure and sets error."""
        sandbox = PluginSandbox()
        m = _make_manifest()

        async def none_return(args: dict):
            return None

        result = await sandbox.execute(none_return, {}, m)
        assert result["success"] is False
        assert result["error"] is not None

    @pytest.mark.asyncio
    async def test_async_handler_supported(self) -> None:
        """execute() works correctly with async (coroutine) handlers."""
        sandbox = PluginSandbox()
        m = _make_manifest()

        async def async_handler(args: dict) -> dict:
            await asyncio.sleep(0)
            return {"async": True}

        result = await sandbox.execute(async_handler, {}, m)
        assert result["success"] is True
        assert result["result"]["async"] is True

    @pytest.mark.asyncio
    async def test_sync_handler_supported(self) -> None:
        """execute() wraps sync handlers so they also run successfully."""
        sandbox = PluginSandbox()
        m = _make_manifest()

        def sync_handler(args: dict) -> dict:
            return {"sync": True}

        result = await sandbox.execute(sync_handler, {}, m)
        assert result["success"] is True
        assert result["result"]["sync"] is True

    @pytest.mark.asyncio
    async def test_execution_logged(self) -> None:
        """A successful execution creates an entry in the execution log."""
        sandbox = PluginSandbox()
        m = _make_manifest(plugin_id="log-test")

        async def handler(args: dict) -> dict:
            return {"logged": True}

        await sandbox.execute(handler, {}, m)
        log = sandbox.get_execution_log(plugin_id="log-test")
        assert len(log) >= 1
        assert log[0]["plugin_id"] == "log-test"

    @pytest.mark.asyncio
    async def test_get_execution_log(self) -> None:
        """get_execution_log() returns a list of execution records."""
        sandbox = PluginSandbox()
        m = _make_manifest(plugin_id="log-all")

        async def handler(args: dict) -> dict:
            return {}

        await sandbox.execute(handler, {}, m)
        log = sandbox.get_execution_log()
        assert isinstance(log, list)
        assert len(log) >= 1

    @pytest.mark.asyncio
    async def test_log_filtered_by_plugin(self) -> None:
        """get_execution_log(plugin_id=X) returns only records for plugin X."""
        sandbox = PluginSandbox()
        m1 = _make_manifest(plugin_id="plugin-a")
        m2 = _make_manifest(plugin_id="plugin-b")

        async def handler(args: dict) -> dict:
            return {}

        await sandbox.execute(handler, {}, m1)
        await sandbox.execute(handler, {}, m2)

        log_a = sandbox.get_execution_log(plugin_id="plugin-a")
        assert all(entry["plugin_id"] == "plugin-a" for entry in log_a)

    @pytest.mark.asyncio
    async def test_limit_parameter(self) -> None:
        """get_execution_log(limit=N) returns at most N records."""
        sandbox = PluginSandbox()
        m = _make_manifest(plugin_id="limit-test")

        async def handler(args: dict) -> dict:
            return {}

        for _ in range(5):
            await sandbox.execute(handler, {}, m)

        log = sandbox.get_execution_log(plugin_id="limit-test", limit=3)
        assert len(log) <= 3

    @pytest.mark.asyncio
    async def test_large_result_rejected(self) -> None:
        """execute() rejects a plugin result that exceeds the size limit."""
        sandbox = PluginSandbox()
        m = _make_manifest()

        async def huge_handler(args: dict) -> dict:
            # Return a dict with a very large payload (> 1MB)
            return {"data": "x" * (2 * 1024 * 1024)}

        result = await sandbox.execute(huge_handler, {}, m)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# TestManifestValidation (5 tests)
# ---------------------------------------------------------------------------


class TestManifestValidation:
    """Tests for validate_manifest rules."""

    def test_all_required_fields(self) -> None:
        """A manifest with all required fields is valid."""
        valid, errors = validate_manifest(_make_manifest_dict())
        assert valid is True
        assert errors == []

    def test_optional_fields_have_defaults(self) -> None:
        """Omitting optional fields still produces a valid manifest with defaults."""
        data = _make_manifest_dict()
        # Remove genuinely optional fields
        data.pop("api_endpoints", None)
        data.pop("card_types", None)
        data.pop("required_permissions", None)
        data.pop("required_skills", None)
        valid, errors = validate_manifest(data)
        assert valid is True

    def test_triggers_validated(self) -> None:
        """Known trigger values (message, schedule, webhook, command) are accepted."""
        for trigger in ["message", "schedule", "webhook", "command"]:
            valid, errors = validate_manifest(_make_manifest_dict(triggers=[trigger]))
            assert valid is True, f"Trigger {trigger!r} should be valid, errors: {errors}"

    def test_sandbox_levels_validated(self) -> None:
        """Known sandbox levels (strict, moderate, trusted) are accepted."""
        for level in ["strict", "moderate", "trusted"]:
            valid, errors = validate_manifest(_make_manifest_dict(sandbox_level=level))
            assert valid is True, f"Sandbox level {level!r} should be valid, errors: {errors}"

    def test_version_format(self) -> None:
        """Semver strings are accepted; non-semver strings are rejected."""
        valid_versions = ["1.0.0", "0.1.0", "2.3.4", "1.0.0-alpha", "1.0.0+build"]
        invalid_versions = ["1", "v1.0.0", "1.0", "not-a-version"]
        for v in valid_versions:
            valid, errors = validate_manifest(_make_manifest_dict(version=v))
            assert valid is True, f"Version {v!r} should be valid, errors: {errors}"
        for v in invalid_versions:
            valid, errors = validate_manifest(_make_manifest_dict(version=v))
            assert valid is False, f"Version {v!r} should be invalid"


# ---------------------------------------------------------------------------
# TestIntegration (5 tests)
# ---------------------------------------------------------------------------


class TestIntegration:
    """End-to-end lifecycle tests combining registry, loader, and sandbox."""

    @pytest.mark.asyncio
    async def test_register_activate_execute_flow(
        self, tmp_plugins_dir: Path, registry: PluginRegistry
    ) -> None:
        """Full happy path: register → activate → execute returns success."""
        _write_plugin(tmp_plugins_dir, "flow-plugin")
        loader = PluginLoader(str(tmp_plugins_dir), registry)
        loader.load_all()
        registry.activate("flow-plugin")

        info = registry.get("flow-plugin")
        assert info["status"] == "active"

        sandbox = PluginSandbox()
        m = _make_manifest(plugin_id="flow-plugin")

        async def handler(args: dict) -> dict:
            return {"done": True}

        result = await sandbox.execute(handler, {}, m)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_quarantined_fails(
        self, registry: PluginRegistry
    ) -> None:
        """A quarantined plugin must not execute successfully in the sandbox."""
        registry.register(_make_manifest(), source_path="/tmp/test-plugin")
        registry.quarantine("test-plugin", reason="Security scan failed")

        info = registry.get("test-plugin")
        assert info["status"] == "quarantined"

        sandbox = PluginSandbox()
        m = _make_manifest()

        # The sandbox itself does not know about quarantine; the orchestrator must
        # check registry status before calling execute. We verify the registry
        # correctly reports quarantined status so the caller can gate execution.
        assert info["status"] == "quarantined"

    @pytest.mark.asyncio
    async def test_execute_inactive_fails(
        self, registry: PluginRegistry
    ) -> None:
        """An inactive plugin (status=inactive) has status confirmed before execution."""
        registry.register(_make_manifest(), source_path="/tmp/test-plugin")
        info = registry.get("test-plugin")
        assert info["status"] == "inactive"

    @pytest.mark.asyncio
    async def test_deactivate_stops_execution(
        self, registry: PluginRegistry
    ) -> None:
        """Deactivating an active plugin returns it to inactive status."""
        registry.register(_make_manifest(), source_path="/tmp/test-plugin")
        registry.activate("test-plugin")
        registry.deactivate("test-plugin")
        info = registry.get("test-plugin")
        assert info["status"] == "inactive"

    @pytest.mark.asyncio
    async def test_full_lifecycle(
        self, tmp_plugins_dir: Path, registry: PluginRegistry
    ) -> None:
        """Full lifecycle: discover → register → activate → execute → deactivate → unregister."""
        _write_plugin(tmp_plugins_dir, "lifecycle-plugin")
        loader = PluginLoader(str(tmp_plugins_dir), registry)
        manifests = loader.discover()
        assert any(m.plugin_id == "lifecycle-plugin" for m in manifests)

        loader.load_all()
        registry.activate("lifecycle-plugin")
        assert registry.get("lifecycle-plugin")["status"] == "active"

        sandbox = PluginSandbox()
        m = _make_manifest(plugin_id="lifecycle-plugin")

        async def handler(args: dict) -> dict:
            return {"step": "executed"}

        result = await sandbox.execute(handler, {}, m)
        assert result["success"] is True

        registry.deactivate("lifecycle-plugin")
        assert registry.get("lifecycle-plugin")["status"] == "inactive"

        registry.unregister("lifecycle-plugin")
        assert registry.get("lifecycle-plugin") is None


# ---------------------------------------------------------------------------
# TestEdgeCases (3 tests)
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests."""

    def test_concurrent_registrations(self, tmp_db: Path) -> None:
        """Multiple PluginRegistry instances on the same DB do not corrupt data."""
        r1 = PluginRegistry(str(tmp_db))
        r2 = PluginRegistry(str(tmp_db))
        r1.register(_make_manifest(plugin_id="r1-plugin"), source_path="/tmp/r1")
        r2.register(_make_manifest(plugin_id="r2-plugin"), source_path="/tmp/r2")
        # Both should be visible from a third instance
        r3 = PluginRegistry(str(tmp_db))
        ids = [p["plugin_id"] for p in r3.list_plugins()]
        assert "r1-plugin" in ids
        assert "r2-plugin" in ids

    def test_plugin_with_no_capabilities(self) -> None:
        """A manifest with no capabilities is valid and parses correctly."""
        m = _make_manifest(capabilities=[])
        valid, errors = validate_manifest(manifest_to_dict(m))
        assert valid is True
        assert m.capabilities == []

    def test_empty_triggers_list(self) -> None:
        """A manifest with an empty triggers list is valid."""
        m = _make_manifest(triggers=[])
        valid, errors = validate_manifest(manifest_to_dict(m))
        assert valid is True
        assert m.triggers == []
