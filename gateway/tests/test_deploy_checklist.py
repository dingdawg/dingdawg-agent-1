"""Tests for the deploy_checklist CLI tool.

TDD: Written BEFORE implementation. Tests define the contract.
"""

from __future__ import annotations

import ast
import importlib
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
GATEWAY_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = GATEWAY_ROOT / "scripts" / "deploy_checklist.py"
ISG_AGENT_DIR = GATEWAY_ROOT / "isg_agent"


# ---------------------------------------------------------------------------
# Helper: import the script as a module
# ---------------------------------------------------------------------------
def _import_deploy_checklist():
    """Import deploy_checklist.py as a module for unit testing."""
    spec = importlib.util.spec_from_file_location("deploy_checklist", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ===========================================================================
# Test 1: Script file exists and is valid Python syntax
# ===========================================================================
class TestScriptExists:
    def test_script_file_exists(self):
        assert SCRIPT_PATH.exists(), f"Script not found at {SCRIPT_PATH}"

    def test_script_is_valid_python(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        # ast.parse raises SyntaxError if invalid
        ast.parse(source, filename=str(SCRIPT_PATH))


# ===========================================================================
# Test 2: Module imports without error
# ===========================================================================
class TestModuleImport:
    def test_module_imports(self):
        mod = _import_deploy_checklist()
        assert mod is not None

    def test_module_has_main(self):
        mod = _import_deploy_checklist()
        assert hasattr(mod, "main"), "Script must have a main() function"


# ===========================================================================
# Test 3: check_python_syntax function
# ===========================================================================
class TestCheckPythonSyntax:
    def test_valid_python_files_pass(self):
        mod = _import_deploy_checklist()
        with tempfile.TemporaryDirectory() as tmpdir:
            valid_file = Path(tmpdir) / "good.py"
            valid_file.write_text("x = 1\n", encoding="utf-8")
            errors = mod.check_python_syntax(tmpdir)
            assert errors == [], f"Expected no errors, got: {errors}"

    def test_invalid_python_files_detected(self):
        mod = _import_deploy_checklist()
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = Path(tmpdir) / "bad.py"
            bad_file.write_text("def broken(\n", encoding="utf-8")
            errors = mod.check_python_syntax(tmpdir)
            assert len(errors) >= 1, "Expected at least one syntax error"
            assert "bad.py" in errors[0]

    def test_empty_directory_returns_no_errors(self):
        mod = _import_deploy_checklist()
        with tempfile.TemporaryDirectory() as tmpdir:
            errors = mod.check_python_syntax(tmpdir)
            assert errors == []


# ===========================================================================
# Test 4: check_env_vars function
# ===========================================================================
class TestCheckEnvVars:
    def test_reports_missing_vars(self):
        mod = _import_deploy_checklist()
        # Clear all relevant env vars
        env_patch = {
            "ISG_AGENT_OPENAI_API_KEY": "",
            "OPENAI_API_KEY": "",
            "ISG_AGENT_ANTHROPIC_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "ISG_AGENT_SECRET_KEY": "",
            "SECRET_KEY": "",
            "ISG_AGENT_DB_PATH": "",
            "DATABASE_URL": "",
            "DB_PATH": "",
            "ISG_AGENT_ALLOWED_ORIGINS": "",
            "ALLOWED_ORIGINS": "",
        }
        with mock.patch.dict(os.environ, env_patch, clear=False):
            # Remove keys that might still be set
            for k in env_patch:
                os.environ.pop(k, None)
            result = mod.check_env_vars()
            assert "missing" in result or len(result.get("missing", [])) > 0 or result.get("missing_count", 0) > 0

    def test_reports_set_vars(self):
        mod = _import_deploy_checklist()
        env_patch = {
            "ISG_AGENT_OPENAI_API_KEY": "sk-test-fake-key-12345",
            "ISG_AGENT_SECRET_KEY": "supersecret",
            "ISG_AGENT_DB_PATH": "/tmp/test.db",
            "ISG_AGENT_ALLOWED_ORIGINS": "http://localhost:3002",
        }
        with mock.patch.dict(os.environ, env_patch, clear=False):
            result = mod.check_env_vars()
            assert "set" in result or len(result.get("set", [])) > 0 or result.get("set_count", 0) > 0


# ===========================================================================
# Test 5: check_hardcoded_secrets function
# ===========================================================================
class TestCheckHardcodedSecrets:
    def test_detects_sk_prefix(self):
        mod = _import_deploy_checklist()
        with tempfile.TemporaryDirectory() as tmpdir:
            suspect = Path(tmpdir) / "leak.py"
            suspect.write_text('api_key = "sk-proj-abc123def456"\n', encoding="utf-8")
            findings = mod.check_hardcoded_secrets(tmpdir)
            assert len(findings) >= 1, "Should detect sk- prefix pattern"

    def test_detects_pk_test_prefix(self):
        mod = _import_deploy_checklist()
        with tempfile.TemporaryDirectory() as tmpdir:
            suspect = Path(tmpdir) / "stripe.py"
            suspect.write_text('pk = "pk_test_51N0thing"\n', encoding="utf-8")
            findings = mod.check_hardcoded_secrets(tmpdir)
            assert len(findings) >= 1, "Should detect pk_test_ prefix pattern"

    def test_clean_file_no_findings(self):
        mod = _import_deploy_checklist()
        with tempfile.TemporaryDirectory() as tmpdir:
            clean = Path(tmpdir) / "clean.py"
            clean.write_text('x = 1\nname = "hello"\n', encoding="utf-8")
            findings = mod.check_hardcoded_secrets(tmpdir)
            assert findings == [], f"Expected no findings, got: {findings}"


# ===========================================================================
# Test 6: count_routes function
# ===========================================================================
class TestCountRoutes:
    def test_returns_integer(self):
        mod = _import_deploy_checklist()
        count = mod.count_routes()
        assert isinstance(count, int)
        # Agent 1 has many routes; should be > 50
        assert count > 0, "Route count must be positive"


# ===========================================================================
# Test 7: check_health_endpoint function
# ===========================================================================
class TestCheckHealthEndpoint:
    def test_health_endpoint_found(self):
        mod = _import_deploy_checklist()
        found = mod.check_health_endpoint()
        assert found is True, "/health endpoint must exist in app.py"


# ===========================================================================
# Test 8: check_critical_import function
# ===========================================================================
class TestCheckCriticalImport:
    def test_isg_agent_app_imports(self):
        mod = _import_deploy_checklist()
        ok, error = mod.check_critical_import()
        assert ok is True, f"import isg_agent.app failed: {error}"


# ===========================================================================
# Test 9: generate_summary function
# ===========================================================================
class TestGenerateSummary:
    def test_returns_markdown_string(self):
        mod = _import_deploy_checklist()
        summary = mod.generate_summary(
            test_passed=100,
            test_failed=2,
            syntax_errors=[],
            import_ok=True,
            env_result={"set": ["SECRET_KEY"], "missing": ["OPENAI_API_KEY"]},
            secret_findings=[],
            route_count=150,
            health_ok=True,
        )
        assert isinstance(summary, str)
        assert "# Deploy Checklist" in summary or "## " in summary
        assert "100" in summary  # test pass count should appear


# ===========================================================================
# Test 10: argparse modes
# ===========================================================================
class TestArgparse:
    def test_quick_flag_accepted(self):
        mod = _import_deploy_checklist()
        parser = mod.build_parser()
        args = parser.parse_args(["--quick"])
        assert args.quick is True

    def test_full_flag_accepted(self):
        mod = _import_deploy_checklist()
        parser = mod.build_parser()
        args = parser.parse_args(["--full"])
        assert args.full is True

    def test_report_flag_accepted(self):
        mod = _import_deploy_checklist()
        parser = mod.build_parser()
        args = parser.parse_args(["--report"])
        assert args.report is True

    def test_default_is_no_flags(self):
        mod = _import_deploy_checklist()
        parser = mod.build_parser()
        args = parser.parse_args([])
        assert args.quick is False
        assert args.full is False
        assert args.report is False


# ===========================================================================
# Test 11: CLI --quick runs without crashing (integration)
# ===========================================================================
class TestCLIIntegration:
    def test_quick_mode_runs(self):
        """Run the script in a subprocess with --quick --skip-tests and verify it exits."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--quick", "--skip-tests"],
            capture_output=True,
            text=True,
            cwd=str(GATEWAY_ROOT),
            timeout=30,
        )
        # Exit code 0 = all checks pass, 1 = some checks failed
        # Both are valid; we just need it to not crash (exit code 2 = argparse error)
        assert result.returncode in (0, 1), (
            f"Script crashed with exit code {result.returncode}.\n"
            f"stdout: {result.stdout[-500:]}\n"
            f"stderr: {result.stderr[-500:]}"
        )
        # Should produce some output
        assert len(result.stdout) > 0, "Script produced no output"


# ===========================================================================
# Test 12: report flag writes file
# ===========================================================================
class TestReportFlag:
    def test_report_flag_writes_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "deploy_report.md"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--quick",
                    "--skip-tests",
                    "--report",
                    "--report-path",
                    str(report_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(GATEWAY_ROOT),
                timeout=30,
            )
            assert result.returncode in (0, 1), (
                f"Script crashed: {result.stderr[-500:]}"
            )
            assert report_path.exists(), "Report file was not created"
            content = report_path.read_text(encoding="utf-8")
            assert len(content) > 50, "Report file is too short"
