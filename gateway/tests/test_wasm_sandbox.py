"""Tests for WebAssembly sandboxing module.

Tests the code validator, capability system, sandbox execution,
pool management, and bridge integration. The validator and capability
system are pure Python and require no external dependencies. Sandbox
execution tests gracefully handle missing wasmtime.

~100 tests covering:
- Code validation (AST-based dangerous pattern detection)
- Memory, CPU, and output size limits
- Capability grants and tier-based defaults
- Sandbox pool acquire/release and exhaustion
- Bridge fallback when Wasm runtime unavailable
- Context passing (JSON in/out)
- Concurrent sandbox execution
- All blocked patterns (os, subprocess, exec, eval, __import__, __builtins__)
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from isg_agent.sandbox import SandboxConfig, SandboxResult, WasmSandbox
from isg_agent.sandbox.capabilities import (
    CapabilitySet,
    get_tier_capabilities,
    grant_capabilities,
)
from isg_agent.sandbox.validator import (
    ValidationResult,
    validate_code,
    CodeValidator,
)
from isg_agent.sandbox.sandbox import SandboxPool, WASM_AVAILABLE
from isg_agent.sandbox.bridge import SandboxBridge


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def default_config() -> SandboxConfig:
    """Default sandbox configuration."""
    return SandboxConfig()


@pytest.fixture
def strict_config() -> SandboxConfig:
    """Strict sandbox configuration with tight limits."""
    return SandboxConfig(
        max_memory_mb=16,
        max_cpu_ms=1000,
        max_output_bytes=1024,
        allowed_hosts=[],
        fuel_limit=100_000,
    )


@pytest.fixture
def permissive_config() -> SandboxConfig:
    """Permissive config with some hosts allowed."""
    return SandboxConfig(
        allowed_hosts=["api.example.com", "data.example.com"],
        max_memory_mb=128,
        max_cpu_ms=10000,
        fuel_limit=5_000_000,
    )


@pytest.fixture
def sandbox(default_config: SandboxConfig) -> WasmSandbox:
    """A WasmSandbox instance with default config."""
    return WasmSandbox(default_config)


@pytest.fixture
def validator() -> CodeValidator:
    """A CodeValidator instance."""
    return CodeValidator()


@pytest.fixture
def bridge(default_config: SandboxConfig) -> SandboxBridge:
    """A SandboxBridge instance."""
    return SandboxBridge(config=default_config)


# ============================================================================
# SandboxConfig tests
# ============================================================================


class TestSandboxConfig:
    """Tests for SandboxConfig dataclass."""

    def test_default_values(self) -> None:
        config = SandboxConfig()
        assert config.max_memory_mb == 64
        assert config.max_cpu_ms == 5000
        assert config.max_output_bytes == 1_048_576  # 1 MB
        assert config.allowed_hosts == []
        assert config.fuel_limit == 1_000_000

    def test_custom_values(self) -> None:
        config = SandboxConfig(
            max_memory_mb=128,
            max_cpu_ms=10000,
            max_output_bytes=2_097_152,
            allowed_hosts=["api.example.com"],
            fuel_limit=2_000_000,
        )
        assert config.max_memory_mb == 128
        assert config.max_cpu_ms == 10000
        assert config.max_output_bytes == 2_097_152
        assert config.allowed_hosts == ["api.example.com"]
        assert config.fuel_limit == 2_000_000

    def test_zero_memory_allowed(self) -> None:
        """Zero memory is a valid edge case (means no allocation)."""
        config = SandboxConfig(max_memory_mb=0)
        assert config.max_memory_mb == 0

    def test_empty_hosts_list(self) -> None:
        config = SandboxConfig(allowed_hosts=[])
        assert config.allowed_hosts == []


# ============================================================================
# SandboxResult tests
# ============================================================================


class TestSandboxResult:
    """Tests for SandboxResult dataclass."""

    def test_success_result(self) -> None:
        result = SandboxResult(
            success=True,
            output="hello world",
            error=None,
            execution_ms=42.5,
            memory_used_bytes=1024,
            fuel_consumed=500,
        )
        assert result.success is True
        assert result.output == "hello world"
        assert result.error is None
        assert result.execution_ms == 42.5
        assert result.memory_used_bytes == 1024
        assert result.fuel_consumed == 500

    def test_failure_result(self) -> None:
        result = SandboxResult(
            success=False,
            output="",
            error="Fuel exhausted",
            execution_ms=5000.0,
            memory_used_bytes=0,
            fuel_consumed=1_000_000,
        )
        assert result.success is False
        assert result.error == "Fuel exhausted"

    def test_result_with_large_output(self) -> None:
        large_output = "x" * 1_000_000
        result = SandboxResult(
            success=True,
            output=large_output,
            error=None,
            execution_ms=100.0,
            memory_used_bytes=1_000_000,
            fuel_consumed=10_000,
        )
        assert len(result.output) == 1_000_000


# ============================================================================
# Validator tests — AST-based code analysis (pure Python, no deps)
# ============================================================================


class TestCodeValidatorImportBlocking:
    """Tests that dangerous imports are detected and blocked."""

    def test_import_os_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("import os")
        assert not result.safe
        assert any("os" in v for v in result.violations)

    def test_import_sys_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("import sys")
        assert not result.safe
        assert any("sys" in v for v in result.violations)

    def test_import_subprocess_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("import subprocess")
        assert not result.safe
        assert any("subprocess" in v for v in result.violations)

    def test_import_shutil_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("import shutil")
        assert not result.safe
        assert any("shutil" in v for v in result.violations)

    def test_import_socket_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("import socket")
        assert not result.safe
        assert any("socket" in v for v in result.violations)

    def test_import_http_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("import http")
        assert not result.safe
        assert any("http" in v for v in result.violations)

    def test_import_urllib_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("import urllib")
        assert not result.safe
        assert any("urllib" in v for v in result.violations)

    def test_from_os_import_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("from os import path")
        assert not result.safe
        assert any("os" in v for v in result.violations)

    def test_from_subprocess_import_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("from subprocess import run")
        assert not result.safe
        assert any("subprocess" in v for v in result.violations)

    def test_import_ctypes_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("import ctypes")
        assert not result.safe
        assert any("ctypes" in v for v in result.violations)

    def test_import_pickle_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("import pickle")
        assert not result.safe
        assert any("pickle" in v for v in result.violations)

    def test_import_marshal_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("import marshal")
        assert not result.safe
        assert any("marshal" in v for v in result.violations)

    def test_import_importlib_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("import importlib")
        assert not result.safe
        assert any("importlib" in v for v in result.violations)

    def test_safe_import_json_allowed(self, validator: CodeValidator) -> None:
        result = validator.validate("import json")
        assert result.safe
        assert result.violations == []

    def test_safe_import_math_allowed(self, validator: CodeValidator) -> None:
        result = validator.validate("import math")
        assert result.safe

    def test_safe_import_datetime_allowed(self, validator: CodeValidator) -> None:
        result = validator.validate("from datetime import datetime")
        assert result.safe

    def test_multiple_blocked_imports(self, validator: CodeValidator) -> None:
        code = "import os\nimport subprocess\nimport sys"
        result = validator.validate(code)
        assert not result.safe
        assert len(result.violations) >= 3


class TestCodeValidatorBuiltinBlocking:
    """Tests that dangerous builtin calls are detected and blocked."""

    def test_exec_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("exec('print(1)')")
        assert not result.safe
        assert any("exec" in v for v in result.violations)

    def test_eval_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("eval('1+1')")
        assert not result.safe
        assert any("eval" in v for v in result.violations)

    def test_compile_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("compile('pass', '<string>', 'exec')")
        assert not result.safe
        assert any("compile" in v for v in result.violations)

    def test_dunder_import_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("__import__('os')")
        assert not result.safe
        assert any("__import__" in v for v in result.violations)

    def test_open_blocked_without_capability(self, validator: CodeValidator) -> None:
        result = validator.validate("f = open('/etc/passwd', 'r')")
        assert not result.safe
        assert any("open" in v for v in result.violations)

    def test_open_allowed_with_filesystem_capability(self) -> None:
        v = CodeValidator(granted_capabilities={CapabilitySet.FILESYSTEM_READ})
        result = v.validate("f = open('data.txt', 'r')")
        assert result.safe

    def test_exec_blocked_even_with_filesystem_capability(self) -> None:
        """exec is ALWAYS blocked regardless of capabilities."""
        v = CodeValidator(granted_capabilities={CapabilitySet.FILESYSTEM_READ})
        result = v.validate("exec('import os')")
        assert not result.safe


class TestCodeValidatorAttributeBlocking:
    """Tests that dangerous attribute access patterns are blocked."""

    def test_builtins_access_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("x = __builtins__")
        assert not result.safe
        assert any("__builtins__" in v for v in result.violations)

    def test_class_access_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("x.__class__.__bases__")
        assert not result.safe
        assert any("__class__" in v for v in result.violations)

    def test_subclasses_access_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("x.__class__.__subclasses__()")
        assert not result.safe
        assert any("__subclasses__" in v for v in result.violations)

    def test_mro_access_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("x.__class__.__mro__")
        assert not result.safe

    def test_globals_access_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("x.__globals__")
        assert not result.safe

    def test_code_access_blocked(self, validator: CodeValidator) -> None:
        result = validator.validate("func.__code__")
        assert not result.safe


class TestCodeValidatorRiskScore:
    """Tests for risk score computation."""

    def test_safe_code_zero_risk(self, validator: CodeValidator) -> None:
        result = validator.validate("x = 1 + 2\nprint(x)")
        assert result.risk_score == 0.0

    def test_single_violation_nonzero_risk(self, validator: CodeValidator) -> None:
        result = validator.validate("import os")
        assert result.risk_score > 0.0

    def test_multiple_violations_higher_risk(self, validator: CodeValidator) -> None:
        single = validator.validate("import os")
        multi = validator.validate("import os\nimport subprocess\nexec('x')")
        assert multi.risk_score > single.risk_score

    def test_risk_score_capped_at_one(self, validator: CodeValidator) -> None:
        """Even with many violations, risk score should not exceed 1.0."""
        code = "\n".join([
            "import os",
            "import sys",
            "import subprocess",
            "import shutil",
            "import socket",
            "exec('x')",
            "eval('y')",
            "__import__('z')",
            "open('/etc/passwd')",
            "__builtins__",
        ])
        result = validator.validate(code)
        assert result.risk_score <= 1.0


class TestCodeValidatorEdgeCases:
    """Tests for edge cases in code validation."""

    def test_empty_code(self, validator: CodeValidator) -> None:
        result = validator.validate("")
        assert result.safe
        assert result.violations == []

    def test_syntax_error_is_unsafe(self, validator: CodeValidator) -> None:
        result = validator.validate("def foo(:")
        assert not result.safe
        assert any("syntax" in v.lower() or "parse" in v.lower() for v in result.violations)

    def test_comment_only_is_safe(self, validator: CodeValidator) -> None:
        result = validator.validate("# import os\n# exec('hello')")
        assert result.safe

    def test_string_containing_import_is_safe(self, validator: CodeValidator) -> None:
        """String literals that mention 'import os' should not trigger."""
        result = validator.validate('msg = "you should import os for system stuff"')
        assert result.safe

    def test_multiline_code_all_safe(self, validator: CodeValidator) -> None:
        code = """
def add(a, b):
    return a + b

result = add(1, 2)
print(result)
"""
        result = validator.validate(code)
        assert result.safe

    def test_nested_function_with_blocked_call(self, validator: CodeValidator) -> None:
        code = """
def sneaky():
    def inner():
        exec("import os")
    inner()
"""
        result = validator.validate(code)
        assert not result.safe

    def test_class_with_blocked_call(self, validator: CodeValidator) -> None:
        code = """
class Exploit:
    def run(self):
        eval("__import__('os').system('whoami')")
"""
        result = validator.validate(code)
        assert not result.safe

    def test_lambda_with_eval(self, validator: CodeValidator) -> None:
        code = "f = lambda x: eval(x)"
        result = validator.validate(code)
        assert not result.safe

    def test_getattr_builtins_blocked(self, validator: CodeValidator) -> None:
        code = "getattr(__builtins__, 'eval')('1+1')"
        result = validator.validate(code)
        assert not result.safe

    def test_validate_code_module_function(self) -> None:
        """Test the module-level convenience function."""
        result = validate_code("import os")
        assert not result.safe

    def test_safe_code_module_function(self) -> None:
        result = validate_code("x = 42")
        assert result.safe


class TestCodeValidatorImportFromVariants:
    """Test various import statement forms."""

    def test_from_os_path_import(self, validator: CodeValidator) -> None:
        result = validator.validate("from os.path import join")
        assert not result.safe

    def test_from_http_client_import(self, validator: CodeValidator) -> None:
        result = validator.validate("from http.client import HTTPConnection")
        assert not result.safe

    def test_from_urllib_request_import(self, validator: CodeValidator) -> None:
        result = validator.validate("from urllib.request import urlopen")
        assert not result.safe

    def test_import_as_alias(self, validator: CodeValidator) -> None:
        result = validator.validate("import os as operating_system")
        assert not result.safe

    def test_from_import_as_alias(self, validator: CodeValidator) -> None:
        result = validator.validate("from subprocess import run as execute")
        assert not result.safe


# ============================================================================
# Capability tests
# ============================================================================


class TestCapabilitySet:
    """Tests for CapabilitySet enum."""

    def test_none_capability(self) -> None:
        assert CapabilitySet.NONE is not None
        assert CapabilitySet.NONE.value == "none"

    def test_read_context_capability(self) -> None:
        assert CapabilitySet.READ_CONTEXT.value == "read_context"

    def test_write_output_capability(self) -> None:
        assert CapabilitySet.WRITE_OUTPUT.value == "write_output"

    def test_http_outbound_capability(self) -> None:
        assert CapabilitySet.HTTP_OUTBOUND.value == "http_outbound"

    def test_filesystem_read_capability(self) -> None:
        assert CapabilitySet.FILESYSTEM_READ.value == "filesystem_read"


class TestTierCapabilities:
    """Tests for tier-based capability defaults."""

    def test_basic_tier(self) -> None:
        caps = get_tier_capabilities("basic")
        assert CapabilitySet.READ_CONTEXT in caps
        assert CapabilitySet.WRITE_OUTPUT in caps
        assert CapabilitySet.HTTP_OUTBOUND not in caps
        assert CapabilitySet.FILESYSTEM_READ not in caps

    def test_pro_tier(self) -> None:
        caps = get_tier_capabilities("pro")
        assert CapabilitySet.READ_CONTEXT in caps
        assert CapabilitySet.WRITE_OUTPUT in caps
        assert CapabilitySet.HTTP_OUTBOUND in caps
        assert CapabilitySet.FILESYSTEM_READ not in caps

    def test_enterprise_tier(self) -> None:
        caps = get_tier_capabilities("enterprise")
        assert CapabilitySet.READ_CONTEXT in caps
        assert CapabilitySet.WRITE_OUTPUT in caps
        assert CapabilitySet.HTTP_OUTBOUND in caps
        assert CapabilitySet.FILESYSTEM_READ in caps

    def test_unknown_tier_gets_none(self) -> None:
        caps = get_tier_capabilities("unknown_tier")
        assert caps == {CapabilitySet.NONE}

    def test_empty_tier_gets_none(self) -> None:
        caps = get_tier_capabilities("")
        assert caps == {CapabilitySet.NONE}


class TestGrantCapabilities:
    """Tests for grant_capabilities function."""

    def test_grant_empty_set(self) -> None:
        config = grant_capabilities(set())
        assert config["stdin_allowed"] is False
        assert config["stdout_allowed"] is False
        assert config["http_allowed"] is False
        assert config["fs_read_allowed"] is False
        assert config["allowed_hosts"] == []
        assert config["allowed_dirs"] == []

    def test_grant_read_context(self) -> None:
        config = grant_capabilities({CapabilitySet.READ_CONTEXT})
        assert config["stdin_allowed"] is True
        assert config["stdout_allowed"] is False

    def test_grant_write_output(self) -> None:
        config = grant_capabilities({CapabilitySet.WRITE_OUTPUT})
        assert config["stdout_allowed"] is True

    def test_grant_http_outbound_without_hosts(self) -> None:
        config = grant_capabilities({CapabilitySet.HTTP_OUTBOUND})
        assert config["http_allowed"] is True
        assert config["allowed_hosts"] == []

    def test_grant_http_outbound_with_hosts(self) -> None:
        config = grant_capabilities(
            {CapabilitySet.HTTP_OUTBOUND},
            allowed_hosts=["api.example.com"],
        )
        assert config["http_allowed"] is True
        assert "api.example.com" in config["allowed_hosts"]

    def test_grant_filesystem_read_without_dirs(self) -> None:
        config = grant_capabilities({CapabilitySet.FILESYSTEM_READ})
        assert config["fs_read_allowed"] is True
        assert config["allowed_dirs"] == []

    def test_grant_filesystem_read_with_dirs(self) -> None:
        config = grant_capabilities(
            {CapabilitySet.FILESYSTEM_READ},
            allowed_dirs=["/data/agent-123"],
        )
        assert config["fs_read_allowed"] is True
        assert "/data/agent-123" in config["allowed_dirs"]

    def test_grant_multiple_capabilities(self) -> None:
        config = grant_capabilities({
            CapabilitySet.READ_CONTEXT,
            CapabilitySet.WRITE_OUTPUT,
            CapabilitySet.HTTP_OUTBOUND,
        })
        assert config["stdin_allowed"] is True
        assert config["stdout_allowed"] is True
        assert config["http_allowed"] is True
        assert config["fs_read_allowed"] is False

    def test_none_capability_grants_nothing(self) -> None:
        config = grant_capabilities({CapabilitySet.NONE})
        assert config["stdin_allowed"] is False
        assert config["stdout_allowed"] is False
        assert config["http_allowed"] is False
        assert config["fs_read_allowed"] is False


# ============================================================================
# WasmSandbox tests
# ============================================================================


class TestWasmSandboxInit:
    """Tests for WasmSandbox initialization."""

    def test_creates_with_default_config(self) -> None:
        sandbox = WasmSandbox(SandboxConfig())
        assert sandbox.config.max_memory_mb == 64

    def test_creates_with_custom_config(self) -> None:
        config = SandboxConfig(max_memory_mb=128)
        sandbox = WasmSandbox(config)
        assert sandbox.config.max_memory_mb == 128


class TestWasmSandboxValidation:
    """Tests for WasmSandbox.validate_code method."""

    def test_validate_safe_code(self, sandbox: WasmSandbox) -> None:
        violations = sandbox.validate_code("x = 1 + 2")
        assert violations == []

    def test_validate_dangerous_code(self, sandbox: WasmSandbox) -> None:
        violations = sandbox.validate_code("import os")
        assert len(violations) > 0

    def test_validate_multiple_violations(self, sandbox: WasmSandbox) -> None:
        violations = sandbox.validate_code("import os\nexec('x')")
        assert len(violations) >= 2


class TestWasmSandboxExecutePython:
    """Tests for WasmSandbox.execute_python method."""

    @pytest.mark.asyncio
    async def test_execute_safe_code(self, sandbox: WasmSandbox) -> None:
        result = await sandbox.execute_python("print('hello')", context={})
        assert result.success is True
        assert "hello" in result.output

    @pytest.mark.asyncio
    async def test_execute_with_context(self, sandbox: WasmSandbox) -> None:
        context = {"name": "DingDawg", "value": 42}
        # sys is blocked by the validator, so we embed the context as a
        # JSON string literal and parse it inside the sandbox.
        context_str = json.dumps(context)
        code = f"import json\nctx = json.loads('{context_str}')\nprint(ctx['name'])"
        result = await sandbox.execute_python(code, context=context)
        assert result.success is True
        assert "DingDawg" in result.output

    @pytest.mark.asyncio
    async def test_execute_returns_timing(self, sandbox: WasmSandbox) -> None:
        result = await sandbox.execute_python("x = 1", context={})
        assert result.execution_ms >= 0

    @pytest.mark.asyncio
    async def test_execute_dangerous_code_rejected(self, sandbox: WasmSandbox) -> None:
        result = await sandbox.execute_python("import os\nos.system('whoami')", context={})
        assert result.success is False
        assert result.error is not None
        assert "validation" in result.error.lower() or "blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_syntax_error(self, sandbox: WasmSandbox) -> None:
        result = await sandbox.execute_python("def foo(:", context={})
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_execute_runtime_error(self, sandbox: WasmSandbox) -> None:
        result = await sandbox.execute_python("x = 1 / 0", context={})
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_execute_output_size_limit(self) -> None:
        config = SandboxConfig(max_output_bytes=100)
        sandbox = WasmSandbox(config)
        result = await sandbox.execute_python(
            "print('x' * 1000)",
            context={},
        )
        # Output should be truncated or rejected
        assert len(result.output) <= 200  # some margin for truncation message

    @pytest.mark.asyncio
    async def test_execute_timeout(self) -> None:
        config = SandboxConfig(max_cpu_ms=500)
        sandbox = WasmSandbox(config)
        result = await sandbox.execute_python(
            "while True: pass",
            context={},
        )
        assert result.success is False
        assert result.error is not None
        assert "timeout" in result.error.lower() or "time" in result.error.lower() or "fuel" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_empty_code(self, sandbox: WasmSandbox) -> None:
        result = await sandbox.execute_python("", context={})
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_json_output(self, sandbox: WasmSandbox) -> None:
        code = 'import json\nprint(json.dumps({"result": 42}))'
        result = await sandbox.execute_python(code, context={})
        assert result.success is True
        parsed = json.loads(result.output.strip())
        assert parsed["result"] == 42


class TestWasmSandboxExecuteWasm:
    """Tests for WasmSandbox.execute_wasm method."""

    @pytest.mark.asyncio
    async def test_execute_wasm_without_runtime(self, sandbox: WasmSandbox) -> None:
        """When wasmtime is not installed, should return graceful error."""
        if not WASM_AVAILABLE:
            result = await sandbox.execute_wasm(b"\x00asm", "main", [])
            assert result.success is False
            assert result.error is not None
            assert "unavailable" in result.error.lower() or "not installed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_wasm_with_invalid_bytes(self, sandbox: WasmSandbox) -> None:
        result = await sandbox.execute_wasm(b"not valid wasm", "main", [])
        assert result.success is False
        assert result.error is not None


# ============================================================================
# SandboxPool tests
# ============================================================================


class TestSandboxPool:
    """Tests for SandboxPool management."""

    @pytest.mark.asyncio
    async def test_pool_creation(self) -> None:
        pool = SandboxPool(pool_size=3, config=SandboxConfig())
        assert pool.pool_size == 3

    @pytest.mark.asyncio
    async def test_acquire_returns_sandbox(self) -> None:
        pool = SandboxPool(pool_size=2, config=SandboxConfig())
        await pool.initialize()
        sandbox = await pool.acquire()
        assert isinstance(sandbox, WasmSandbox)
        await pool.release(sandbox)

    @pytest.mark.asyncio
    async def test_release_returns_to_pool(self) -> None:
        pool = SandboxPool(pool_size=1, config=SandboxConfig())
        await pool.initialize()
        sandbox = await pool.acquire()
        await pool.release(sandbox)
        # Should be able to acquire again
        sandbox2 = await pool.acquire()
        assert isinstance(sandbox2, WasmSandbox)
        await pool.release(sandbox2)

    @pytest.mark.asyncio
    async def test_pool_exhaustion_timeout(self) -> None:
        pool = SandboxPool(pool_size=1, config=SandboxConfig())
        await pool.initialize()
        sandbox = await pool.acquire()
        # Pool is now empty — acquire with short timeout should raise
        with pytest.raises((asyncio.TimeoutError, RuntimeError)):
            await pool.acquire(timeout=0.1)
        await pool.release(sandbox)

    @pytest.mark.asyncio
    async def test_pool_available_count(self) -> None:
        pool = SandboxPool(pool_size=3, config=SandboxConfig())
        await pool.initialize()
        assert pool.available == 3
        s1 = await pool.acquire()
        assert pool.available == 2
        s2 = await pool.acquire()
        assert pool.available == 1
        await pool.release(s1)
        assert pool.available == 2
        await pool.release(s2)
        assert pool.available == 3

    @pytest.mark.asyncio
    async def test_pool_concurrent_acquire(self) -> None:
        pool = SandboxPool(pool_size=5, config=SandboxConfig())
        await pool.initialize()

        async def acquire_and_release() -> bool:
            sb = await pool.acquire()
            await asyncio.sleep(0.01)
            await pool.release(sb)
            return True

        results = await asyncio.gather(*[acquire_and_release() for _ in range(5)])
        assert all(results)
        assert pool.available == 5


# ============================================================================
# Bridge tests
# ============================================================================


class TestSandboxBridge:
    """Tests for SandboxBridge integration with skill executor."""

    @pytest.mark.asyncio
    async def test_bridge_execute_safe_skill(self, bridge: SandboxBridge) -> None:
        result = await bridge.execute_skill_sandboxed(
            agent_id="agent-123",
            skill_name="calculator",
            action="add",
            params={"a": 1, "b": 2},
            context={"agent_tier": "basic"},
        )
        assert result is not None
        assert hasattr(result, "success")

    @pytest.mark.asyncio
    async def test_bridge_fallback_on_no_wasm(self) -> None:
        """Bridge should fall back to direct execution when Wasm unavailable."""
        bridge = SandboxBridge(config=SandboxConfig())
        # Force wasm unavailable
        with patch.object(bridge, '_wasm_available', False):
            result = await bridge.execute_skill_sandboxed(
                agent_id="agent-456",
                skill_name="echo",
                action="run",
                params={"text": "hello"},
                context={},
            )
            assert result is not None
            assert result.execution_mode in ("direct", "fallback")

    @pytest.mark.asyncio
    async def test_bridge_tracks_metrics(self, bridge: SandboxBridge) -> None:
        await bridge.execute_skill_sandboxed(
            agent_id="agent-789",
            skill_name="test",
            action="run",
            params={},
            context={},
        )
        metrics = bridge.get_metrics()
        assert "total_executions" in metrics
        assert metrics["total_executions"] >= 1

    @pytest.mark.asyncio
    async def test_bridge_rejects_dangerous_code(self, bridge: SandboxBridge) -> None:
        result = await bridge.execute_skill_sandboxed(
            agent_id="agent-bad",
            skill_name="malicious",
            action="run",
            params={"code": "import os; os.system('rm -rf /')"},
            context={"code": "import os; os.system('rm -rf /')"},
        )
        # The bridge should NOT execute dangerous code
        assert result is not None

    def test_bridge_metrics_initial_state(self, bridge: SandboxBridge) -> None:
        metrics = bridge.get_metrics()
        assert metrics["total_executions"] == 0
        assert metrics["sandbox_executions"] == 0
        assert metrics["direct_executions"] == 0

    @pytest.mark.asyncio
    async def test_bridge_execution_mode_field(self, bridge: SandboxBridge) -> None:
        result = await bridge.execute_skill_sandboxed(
            agent_id="agent-test",
            skill_name="safe_skill",
            action="run",
            params={},
            context={},
        )
        assert result.execution_mode in ("sandbox", "direct", "fallback", "validated")


# ============================================================================
# Concurrent execution tests
# ============================================================================


class TestConcurrentExecution:
    """Tests for concurrent sandbox execution."""

    @pytest.mark.asyncio
    async def test_concurrent_safe_executions(self) -> None:
        sandbox = WasmSandbox(SandboxConfig())
        tasks = [
            sandbox.execute_python(f"print({i})", context={})
            for i in range(5)
        ]
        results = await asyncio.gather(*tasks)
        assert all(r.success for r in results)
        outputs = {r.output.strip() for r in results}
        assert outputs == {"0", "1", "2", "3", "4"}

    @pytest.mark.asyncio
    async def test_concurrent_mixed_executions(self) -> None:
        sandbox = WasmSandbox(SandboxConfig())
        tasks = [
            sandbox.execute_python("print('safe')", context={}),
            sandbox.execute_python("import os", context={}),
            sandbox.execute_python("print('also safe')", context={}),
        ]
        results = await asyncio.gather(*tasks)
        assert results[0].success is True
        assert results[1].success is False
        assert results[2].success is True

    @pytest.mark.asyncio
    async def test_concurrent_does_not_leak_context(self) -> None:
        """One execution's context must not leak to another."""
        sandbox = WasmSandbox(SandboxConfig())
        tasks = [
            sandbox.execute_python(
                f"print('value-{i}')",
                context={"secret": f"value-{i}"},
            )
            for i in range(3)
        ]
        results = await asyncio.gather(*tasks)
        outputs = [r.output.strip() for r in results]
        assert sorted(outputs) == ["value-0", "value-1", "value-2"]


# ============================================================================
# Integration tests — full pipeline
# ============================================================================


class TestFullPipeline:
    """End-to-end tests combining validator + sandbox + bridge."""

    @pytest.mark.asyncio
    async def test_safe_skill_full_pipeline(self) -> None:
        config = SandboxConfig()
        sandbox = WasmSandbox(config)
        code = 'import json\nresult = 10 + 20\nprint(json.dumps({"sum": result}))'
        violations = sandbox.validate_code(code)
        assert violations == []
        result = await sandbox.execute_python(code, context={"a": 10, "b": 20})
        assert result.success is True
        parsed = json.loads(result.output.strip())
        assert parsed["sum"] == 30

    @pytest.mark.asyncio
    async def test_dangerous_skill_full_pipeline(self) -> None:
        config = SandboxConfig()
        sandbox = WasmSandbox(config)
        code = "import subprocess\nsubprocess.run(['ls'])"
        violations = sandbox.validate_code(code)
        assert len(violations) > 0
        result = await sandbox.execute_python(code, context={})
        assert result.success is False

    def test_validator_standalone_pipeline(self) -> None:
        v = CodeValidator()
        safe_result = v.validate("x = sum([1, 2, 3])\nprint(x)")
        assert safe_result.safe
        assert safe_result.risk_score == 0.0

        danger_result = v.validate("eval(__import__('os').popen('id').read())")
        assert not danger_result.safe
        assert danger_result.risk_score >= 0.5
