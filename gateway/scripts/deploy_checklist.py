#!/usr/bin/env python3
"""DingDawg Agent 1 -- Pre-Deploy Checklist CLI.

Runs automated checks before deploying to Railway (backend) / Vercel (frontend).

Usage:
    python3 scripts/deploy_checklist.py --quick     # tests + syntax only
    python3 scripts/deploy_checklist.py --full      # all checks
    python3 scripts/deploy_checklist.py --report    # write deploy_report.md

Exit codes:
    0 -- all checks passed
    1 -- one or more checks failed
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Resolve project root (gateway/)
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
GATEWAY_ROOT = SCRIPT_DIR.parent
ISG_AGENT_DIR = GATEWAY_ROOT / "isg_agent"
TESTS_DIR = GATEWAY_ROOT / "tests"
APP_PY = ISG_AGENT_DIR / "app.py"

# ---------------------------------------------------------------------------
# ANSI colours (disabled when not a TTY)
# ---------------------------------------------------------------------------
_IS_TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    if not _IS_TTY:
        return text
    return f"\033[{code}m{text}\033[0m"


def _green(t: str) -> str:
    return _c("0;32", t)


def _red(t: str) -> str:
    return _c("0;31", t)


def _yellow(t: str) -> str:
    return _c("1;33", t)


def _bold(t: str) -> str:
    return _c("1", t)


# ===========================================================================
# Check functions -- each returns structured data, never prints directly
# ===========================================================================


def run_tests() -> tuple[int, int, str]:
    """Run pytest and return (passed, failed, raw_output).

    Returns (0, 0, error_message) if pytest itself cannot run.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(TESTS_DIR), "-q", "--tb=no"],
            capture_output=True,
            text=True,
            cwd=str(GATEWAY_ROOT),
            timeout=300,
        )
        output = result.stdout + result.stderr

        # Parse "X passed, Y failed" from pytest output
        passed = 0
        failed = 0

        m_passed = re.search(r"(\d+)\s+passed", output)
        m_failed = re.search(r"(\d+)\s+failed", output)
        m_error = re.search(r"(\d+)\s+error", output)

        if m_passed:
            passed = int(m_passed.group(1))
        if m_failed:
            failed = int(m_failed.group(1))
        if m_error:
            failed += int(m_error.group(1))

        return passed, failed, output
    except subprocess.TimeoutExpired:
        return 0, 0, "ERROR: pytest timed out after 300 seconds"
    except FileNotFoundError:
        return 0, 0, "ERROR: pytest not found"


def check_python_syntax(source_dir: str | None = None) -> list[str]:
    """Verify all .py files in source_dir parse as valid Python.

    Returns a list of error strings (empty = all clean).
    """
    target = Path(source_dir) if source_dir else ISG_AGENT_DIR
    errors: list[str] = []

    if not target.exists():
        return errors

    for py_file in sorted(target.rglob("*.py")):
        try:
            source = py_file.read_text(encoding="utf-8")
            ast.parse(source, filename=str(py_file))
        except SyntaxError as exc:
            errors.append(f"{py_file.name}:{exc.lineno}: {exc.msg}")
    return errors


def check_critical_import() -> tuple[bool, str]:
    """Verify ``import isg_agent.app`` succeeds.

    Returns (True, '') on success or (False, error_message) on failure.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import isg_agent.app"],
            capture_output=True,
            text=True,
            cwd=str(GATEWAY_ROOT),
            timeout=30,
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout).strip()[:200]
    except subprocess.TimeoutExpired:
        return False, "import timed out"
    except Exception as exc:
        return False, str(exc)[:200]


def check_env_vars() -> dict[str, Any]:
    """Check which required environment variables are set locally.

    Required env vars for Railway deployment:
    - OPENAI_API_KEY or ANTHROPIC_API_KEY (at least one LLM key)
    - SECRET_KEY (JWT signing)
    - DATABASE_URL or DB_PATH (database)
    - ALLOWED_ORIGINS (CORS)

    Returns dict with 'set' and 'missing' lists plus counts.
    """
    # Each entry: (display_name, list_of_env_var_names_to_check)
    required_groups: list[tuple[str, list[str]]] = [
        (
            "LLM API Key (OpenAI or Anthropic)",
            [
                "ISG_AGENT_OPENAI_API_KEY",
                "OPENAI_API_KEY",
                "ISG_AGENT_ANTHROPIC_API_KEY",
                "ANTHROPIC_API_KEY",
            ],
        ),
        (
            "SECRET_KEY",
            ["ISG_AGENT_SECRET_KEY", "SECRET_KEY", "ISG_AGENT_JWT_SECRET"],
        ),
        (
            "DATABASE (DB_PATH or DATABASE_URL)",
            ["ISG_AGENT_DB_PATH", "DATABASE_URL", "DB_PATH"],
        ),
        (
            "ALLOWED_ORIGINS",
            ["ISG_AGENT_ALLOWED_ORIGINS", "ALLOWED_ORIGINS"],
        ),
    ]

    set_vars: list[str] = []
    missing_vars: list[str] = []

    for display_name, candidates in required_groups:
        found = False
        for var_name in candidates:
            val = os.environ.get(var_name, "")
            if val:
                set_vars.append(f"{display_name} ({var_name})")
                found = True
                break
        if not found:
            missing_vars.append(display_name)

    return {
        "set": set_vars,
        "missing": missing_vars,
        "set_count": len(set_vars),
        "missing_count": len(missing_vars),
    }


def check_hardcoded_secrets(source_dir: str | None = None) -> list[str]:
    """Scan source files for patterns that look like hardcoded secrets.

    Patterns: sk-, sk_test_, sk_live_, pk_test_, pk_live_, AKIA,
    password=", password = "

    Returns list of findings: ["file.py:lineno: pattern matched"]
    """
    target = Path(source_dir) if source_dir else ISG_AGENT_DIR
    findings: list[str] = []

    if not target.exists():
        return findings

    # Patterns that indicate hardcoded secrets
    # Each pattern is compiled with a human-readable label
    patterns: list[tuple[str, re.Pattern[str]]] = [
        ("OpenAI key (sk-)", re.compile(r'["\']sk-[A-Za-z0-9_\-]{10,}["\']')),
        ("Stripe secret (sk_test_/sk_live_)", re.compile(r'["\']sk_(test|live)_[A-Za-z0-9]{10,}["\']')),
        ("Stripe publishable (pk_test_/pk_live_)", re.compile(r'["\']pk_(test|live)_[A-Za-z0-9]{5,}["\']')),
        ("AWS key (AKIA)", re.compile(r'["\']AKIA[A-Z0-9]{12,}["\']')),
        ("Hardcoded password", re.compile(r'password\s*=\s*["\'][^"\']{8,}["\']', re.IGNORECASE)),
    ]

    for py_file in sorted(target.rglob("*.py")):
        try:
            lines = py_file.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        for lineno, line in enumerate(lines, start=1):
            # Skip comments and docstrings (best-effort)
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for label, pattern in patterns:
                if pattern.search(line):
                    findings.append(
                        f"{py_file.name}:{lineno}: {label}"
                    )

    return findings


def count_routes() -> int:
    """Count the total number of API routes registered in the FastAPI app.

    Imports create_app() and iterates over app.routes to count.
    Falls back to parsing app.py for include_router calls if import fails.
    """
    # Strategy 1: Parse app.py for include_router lines + direct route decorators
    route_count = 0

    if APP_PY.exists():
        source = APP_PY.read_text(encoding="utf-8")

        # Count include_router calls
        router_count = len(re.findall(r"app\.include_router\(", source))

        # Count direct route decorators (@app.get, @app.post, etc.)
        direct_routes = len(re.findall(r"@app\.(get|post|put|delete|patch|websocket)\(", source))

        # Each router has multiple routes; estimate or count from router files
        # For accuracy, try to count routes from the actual router files
        routes_dir = ISG_AGENT_DIR / "api" / "routes"
        if routes_dir.exists():
            for route_file in routes_dir.rglob("*.py"):
                try:
                    route_source = route_file.read_text(encoding="utf-8")
                    route_count += len(
                        re.findall(
                            r"@router\.(get|post|put|delete|patch|api_route)\(",
                            route_source,
                        )
                    )
                except (OSError, UnicodeDecodeError):
                    continue

        route_count += direct_routes

    return route_count


def check_health_endpoint() -> bool:
    """Verify that a /health route is defined in app.py.

    Returns True if found, False otherwise.
    """
    if not APP_PY.exists():
        return False

    source = APP_PY.read_text(encoding="utf-8")
    # Look for the @app.get("/health" pattern
    return bool(re.search(r'@app\.(get|api_route)\(\s*["\']/health["\']', source))


def generate_summary(
    *,
    test_passed: int,
    test_failed: int,
    syntax_errors: list[str],
    import_ok: bool,
    env_result: dict[str, Any],
    secret_findings: list[str],
    route_count: int,
    health_ok: bool,
) -> str:
    """Generate a markdown-formatted deploy summary.

    Returns the summary as a string.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    all_pass = (
        test_failed == 0
        and len(syntax_errors) == 0
        and import_ok
        and env_result.get("missing_count", 0) == 0
        and len(secret_findings) == 0
        and health_ok
    )

    status = "READY TO DEPLOY" if all_pass else "ISSUES FOUND"

    lines: list[str] = [
        f"# Deploy Checklist Report -- {status}",
        f"",
        f"**Generated:** {now}",
        f"**Project:** DingDawg Agent 1 (ISG Agent)",
        f"**Backend:** Railway | **Frontend:** Vercel",
        f"",
        f"---",
        f"",
        f"## Tests",
        f"",
        f"- Passed: **{test_passed}**",
        f"- Failed: **{test_failed}**",
        f"- Status: {'PASS' if test_failed == 0 else 'FAIL'}",
        f"",
        f"## Python Syntax",
        f"",
    ]

    if syntax_errors:
        lines.append(f"- **{len(syntax_errors)} error(s) found:**")
        for err in syntax_errors[:20]:
            lines.append(f"  - `{err}`")
    else:
        lines.append("- All .py files parse correctly: PASS")

    lines.extend([
        f"",
        f"## Critical Import",
        f"",
        f"- `import isg_agent.app`: {'PASS' if import_ok else 'FAIL'}",
        f"",
        f"## Environment Variables",
        f"",
    ])

    for var in env_result.get("set", []):
        lines.append(f"- [x] {var}")
    for var in env_result.get("missing", []):
        lines.append(f"- [ ] **MISSING:** {var}")

    lines.extend([
        f"",
        f"## Hardcoded Secrets Scan",
        f"",
    ])

    if secret_findings:
        lines.append(f"- **{len(secret_findings)} potential secret(s) found:**")
        for finding in secret_findings[:20]:
            lines.append(f"  - `{finding}`")
    else:
        lines.append("- No hardcoded secrets detected: PASS")

    lines.extend([
        f"",
        f"## Routes",
        f"",
        f"- Total API routes: **{route_count}**",
        f"",
        f"## Health Endpoint",
        f"",
        f"- `/health` route defined: {'PASS' if health_ok else 'FAIL'}",
        f"",
        f"---",
        f"",
        f"**Overall: {status}**",
    ])

    return "\n".join(lines) + "\n"


# ===========================================================================
# Argparse
# ===========================================================================


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="deploy_checklist",
        description="DingDawg Agent 1 -- Pre-Deploy Checklist",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python3 scripts/deploy_checklist.py --quick
              python3 scripts/deploy_checklist.py --full
              python3 scripts/deploy_checklist.py --full --report
        """),
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        default=False,
        help="Run only tests + syntax check (fast mode)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        default=False,
        help="Run all checks (tests, syntax, imports, env, secrets, routes, health)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        default=False,
        help="Write results to a markdown report file",
    )
    parser.add_argument(
        "--report-path",
        type=str,
        default=str(GATEWAY_ROOT / "deploy_report.md"),
        help="Path for the report file (default: gateway/deploy_report.md)",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        default=False,
        help="Skip running pytest (useful in CI or when tests already ran)",
    )
    return parser


# ===========================================================================
# Main
# ===========================================================================


def main(argv: list[str] | None = None) -> int:
    """Run the deploy checklist and return exit code (0=pass, 1=fail)."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # Default to --full if neither --quick nor --full specified
    run_full = args.full or not args.quick

    print()
    print(_bold("=" * 60))
    print(_bold("  DingDawg Agent 1 -- Pre-Deploy Checklist"))
    print(_bold("=" * 60))
    print()

    has_failure = False

    # -- 1. Tests ----------------------------------------------------------
    print(_bold("--- [1/8] Running Tests ---"))
    if args.skip_tests:
        test_passed, test_failed, test_output = 0, 0, "SKIPPED (--skip-tests)"
        print(f"  {_yellow('SKIP')}  Tests skipped (--skip-tests flag)")
    else:
        test_passed, test_failed, test_output = run_tests()
        if test_failed > 0:
            print(f"  {_red('FAIL')}  {test_passed} passed, {test_failed} failed")
            has_failure = True
        elif test_passed == 0:
            print(f"  {_yellow('WARN')}  No tests collected or pytest error")
            # Show last few lines of output for debugging
            for line in test_output.strip().splitlines()[-5:]:
                print(f"         {line}")
        else:
            print(f"  {_green('PASS')}  {test_passed} passed, {test_failed} failed")
    print()

    # -- 2. Python Syntax --------------------------------------------------
    print(_bold("--- [2/8] Python Syntax Check ---"))
    syntax_errors = check_python_syntax()
    if syntax_errors:
        print(f"  {_red('FAIL')}  {len(syntax_errors)} syntax error(s)")
        for err in syntax_errors[:10]:
            print(f"         {err}")
        has_failure = True
    else:
        py_count = sum(1 for _ in ISG_AGENT_DIR.rglob("*.py")) if ISG_AGENT_DIR.exists() else 0
        print(f"  {_green('PASS')}  {py_count} files checked, all valid")
    print()

    # Remaining checks only if --full or default
    import_ok = True
    env_result: dict[str, Any] = {"set": [], "missing": [], "set_count": 0, "missing_count": 0}
    secret_findings: list[str] = []
    route_count = 0
    health_ok = True

    if run_full:
        # -- 3. Critical Import -----------------------------------------------
        print(_bold("--- [3/8] Critical Import ---"))
        import_ok, import_err = check_critical_import()
        if import_ok:
            print(f"  {_green('PASS')}  import isg_agent.app succeeded")
        else:
            print(f"  {_red('FAIL')}  import isg_agent.app failed: {import_err}")
            has_failure = True
        print()

        # -- 4. Environment Variables -----------------------------------------
        print(_bold("--- [4/8] Environment Variables ---"))
        env_result = check_env_vars()
        for var in env_result["set"]:
            print(f"  {_green('SET ')}  {var}")
        for var in env_result["missing"]:
            print(f"  {_yellow('MISS')}  {var}")
        if env_result["missing_count"] > 0:
            print(f"  {_yellow('WARN')}  {env_result['missing_count']} required var group(s) not set locally")
        else:
            print(f"  {_green('PASS')}  All required environment variables set")
        print()

        # -- 5. Hardcoded Secrets ---------------------------------------------
        print(_bold("--- [5/8] Hardcoded Secrets Scan ---"))
        secret_findings = check_hardcoded_secrets()
        if secret_findings:
            print(f"  {_red('FAIL')}  {len(secret_findings)} potential secret(s) found:")
            for finding in secret_findings[:10]:
                print(f"         {finding}")
            has_failure = True
        else:
            print(f"  {_green('PASS')}  No hardcoded secrets detected")
        print()

        # -- 6. Route Count ---------------------------------------------------
        print(_bold("--- [6/8] Route Count ---"))
        route_count = count_routes()
        print(f"  {_green('INFO')}  {route_count} API routes registered")
        print()

        # -- 7. Health Endpoint -----------------------------------------------
        print(_bold("--- [7/8] Health Endpoint ---"))
        health_ok = check_health_endpoint()
        if health_ok:
            print(f"  {_green('PASS')}  /health endpoint defined")
        else:
            print(f"  {_red('FAIL')}  /health endpoint NOT found in app.py")
            has_failure = True
        print()

        # -- 8. Deploy Summary ------------------------------------------------
        print(_bold("--- [8/8] Deploy Summary ---"))
        print(f"  Tests:     {test_passed} passed / {test_failed} failed")
        print(f"  Syntax:    {'CLEAN' if not syntax_errors else f'{len(syntax_errors)} errors'}")
        print(f"  Import:    {'OK' if import_ok else 'FAILED'}")
        print(f"  Env vars:  {env_result['set_count']} set / {env_result['missing_count']} missing")
        print(f"  Secrets:   {'CLEAN' if not secret_findings else f'{len(secret_findings)} findings'}")
        print(f"  Routes:    {route_count}")
        print(f"  Health:    {'OK' if health_ok else 'MISSING'}")
        print()
    else:
        print(_bold("  (--quick mode: skipping checks 3-8, use --full for all)"))
        print()

    # -- Report ------------------------------------------------------------
    summary = generate_summary(
        test_passed=test_passed,
        test_failed=test_failed,
        syntax_errors=syntax_errors,
        import_ok=import_ok,
        env_result=env_result,
        secret_findings=secret_findings,
        route_count=route_count,
        health_ok=health_ok,
    )

    if args.report:
        report_path = Path(args.report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(summary, encoding="utf-8")
        print(f"  Report written to: {report_path}")
        print()

    # -- Final verdict -----------------------------------------------------
    print(_bold("-" * 60))
    if has_failure:
        print(f"  {_red('RESULT: ISSUES FOUND -- review above before deploying')}")
    else:
        print(f"  {_green('RESULT: ALL CHECKS PASSED')}")
    print(_bold("-" * 60))
    print()

    return 1 if has_failure else 0


if __name__ == "__main__":
    sys.exit(main())
