#!/usr/bin/env python3
"""
DingDawg Health Monitor — detects backend outages, domain mismatches, and API regressions.

Designed to catch the specific failure mode that triggered this tool:
  - Railway redeploy changed the backend URL
  - Vercel BACKEND_URL env var still pointed to the old dead domain
  - Result: 502s, login failures, command crashes — discovered manually

Run manually:    python3 scripts/health_monitor.py
Run via cron:    */5 * * * * cd /home/joe-rangel/Desktop/DingDawg-Agent-1/gateway && python3 scripts/health_monitor.py --cron
Silent (no TTY): python3 scripts/health_monitor.py --cron 2>&1 >> ~/.mila/health_monitor.log

Exit codes:
  0 — all checks passed
  1 — one or more checks failed
"""

import datetime
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Known production endpoints — update these if Railway domain changes.
# The whole point of this script is to make that update the ONLY manual step.
# Read from env var to avoid hardcoding internal infrastructure URLs in source.
# Set BACKEND_URL in your shell or .env.local before running.
# ---------------------------------------------------------------------------
RAILWAY_URL = os.environ.get("BACKEND_URL", "https://api.dingdawg.com")
VERCEL_URL = "https://app.dingdawg.com"
OLD_RAILWAY_URL = "https://isg-agent-production.up.railway.app"  # should be dead/404

# ---------------------------------------------------------------------------
# Health checks table:
#   (name, url, expected_status, is_critical, description)
#
# is_critical=True  → failure blocks exit 0, triggers notify-send
# is_critical=False → failure is reported as WARN, does not block exit 0
#                     (informational — useful for flagging domain drift)
# ---------------------------------------------------------------------------
CHECKS = [
    # Backend core
    (
        "Backend Health",
        f"{RAILWAY_URL}/health",
        200,
        True,
        "Railway backend /health must return 200 with JSON body",
    ),
    (
        "Backend Health Body",
        f"{RAILWAY_URL}/health",
        200,
        True,
        "Response body must contain 'status' key",
    ),
    (
        "Admin Auth Gate",
        f"{RAILWAY_URL}/api/v1/admin/whoami",
        401,
        True,
        "Admin endpoints require auth — 401 means auth layer is running",
    ),
    (
        "Auth Refresh Exists",
        f"{RAILWAY_URL}/auth/refresh",
        405,
        True,
        "POST-only endpoint returns 405 on GET — confirms auth routes registered",
    ),
    (
        "Docs Gated",
        f"{RAILWAY_URL}/docs",
        404,
        True,
        "OpenAPI docs must NOT be publicly exposed",
    ),
    (
        "Onboarding Sectors",
        f"{RAILWAY_URL}/api/v1/onboarding/sectors",
        200,
        True,
        "Public endpoint — returns industry list without auth",
    ),
    # Frontend
    (
        "Frontend Live",
        f"{VERCEL_URL}",
        200,
        True,
        "Vercel frontend must return 200",
    ),
    # Domain mismatch detection — THIS is the core failure mode we are guarding against.
    # If Vercel's BACKEND_URL env var is stale, /health proxied through Vercel will
    # return 502 while the direct Railway URL returns 200. That delta = mismatch.
    (
        "Frontend→Backend Proxy (health)",
        f"{VERCEL_URL}/health",
        200,
        True,
        "Vercel rewrite rule must forward /health to Railway — 502 = domain mismatch",
    ),
    (
        "Frontend→Backend Proxy (auth)",
        f"{VERCEL_URL}/auth/refresh",
        405,
        True,
        "Vercel must proxy /auth/* to Railway — 502 = domain mismatch",
    ),
    # Old domain resurrection detection
    (
        "Old Domain Dead",
        f"{OLD_RAILWAY_URL}/health",
        0,  # expected: unreachable (DNS/connection failure) or any non-200
        False,
        "Old Railway URL should be unreachable — resurrection means traffic leakage",
    ),
]

# Log file path (no external deps — plain text)
LOG_PATH = os.path.expanduser("~/.mila/health_monitor.log")


# ---------------------------------------------------------------------------
# HTTP probe
# ---------------------------------------------------------------------------

def check_url(url: str, expected_status: int, timeout: int = 10) -> tuple[int, str, bool]:
    """Probe a URL and return (actual_status, body_snippet, passed).

    Interprets expected_status=0 as "should be unreachable" — any connection
    failure counts as a PASS for that check (old domain dead check).
    """
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")[:500]
            actual = resp.status
            if expected_status == 0:
                # Old domain came back alive — this is a FAIL
                return (actual, body, False)
            return (actual, body, actual == expected_status)
    except urllib.error.HTTPError as exc:
        actual = exc.code
        reason = str(exc.reason)
        if expected_status == 0:
            # HTTP error from old domain = it IS responding = FAIL
            return (actual, reason, False)
        return (actual, reason, actual == expected_status)
    except urllib.error.URLError as exc:
        reason = str(exc.reason)
        if expected_status == 0:
            # Connection refused / DNS failure = old domain unreachable = PASS
            return (0, f"unreachable ({reason})", True)
        return (0, f"unreachable ({reason})", False)
    except Exception as exc:  # noqa: BLE001
        reason = str(exc)
        if expected_status == 0:
            return (0, f"error ({reason})", True)
        return (0, f"error ({reason})", False)


def check_health_body(url: str, timeout: int = 10) -> tuple[bool, str]:
    """Secondary check: verify /health response body contains 'status' JSON key."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(body)
            if "status" in data:
                return (True, f"status={data['status']!r}")
            return (False, f"body has no 'status' key: {body[:200]}")
    except json.JSONDecodeError as exc:
        return (False, f"body is not valid JSON: {exc}")
    except Exception as exc:  # noqa: BLE001
        return (False, str(exc))


# ---------------------------------------------------------------------------
# Desktop notification (best-effort — fails silently on headless)
# ---------------------------------------------------------------------------

def notify(title: str, message: str) -> None:
    """Send an urgency=critical desktop notification via notify-send.

    Silently swallows all errors — notification is never load-bearing.
    Headless environments (cron without DISPLAY) will skip this gracefully.
    """
    try:
        subprocess.run(
            ["notify-send", "--urgency=critical", title, message],
            timeout=5,
            capture_output=True,
        )
    except Exception:  # noqa: BLE001
        pass  # notify-send absence or headless — intentional silent catch


# ---------------------------------------------------------------------------
# Log persistence
# ---------------------------------------------------------------------------

def write_log(timestamp: str, failures: list[str]) -> None:
    """Append failures to the persistent log file at LOG_PATH."""
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{timestamp} | FAILURES: {'; '.join(failures)}\n")
    except OSError as exc:
        # Log write failure is not fatal — print to stderr and continue
        print(f"[WARN] Could not write log to {LOG_PATH}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    is_cron = "--cron" in sys.argv
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    results: list[tuple[str, str, int, int, bool, str, bool]] = []
    critical_failures: list[str] = []
    warn_failures: list[str] = []

    for name, url, expected, is_critical, desc in CHECKS:
        # Special case: "Backend Health Body" reuses the /health response
        # but validates the JSON structure rather than status code
        if name == "Backend Health Body":
            passed, detail = check_health_body(url)
            actual_status = 200 if passed else 0
            body = detail
        else:
            actual_status, body, passed = check_url(url, expected)

        results.append((name, url, expected, actual_status, passed, body, is_critical))

        if not passed:
            failure_msg = f"{name}: expected {expected}, got {actual_status}"
            if is_critical:
                critical_failures.append(failure_msg)
            else:
                warn_failures.append(failure_msg)

    # -------------------------------------------------------------------------
    # Domain mismatch diagnosis: if Railway is UP but Vercel proxy is DOWN,
    # print an explicit actionable message.
    # -------------------------------------------------------------------------
    railway_ok = any(
        passed
        for name, _, _, _, passed, _, _ in results
        if name == "Backend Health"
    )
    proxy_ok = any(
        passed
        for name, _, _, _, passed, _, _ in results
        if name == "Frontend→Backend Proxy (health)"
    )
    domain_mismatch = railway_ok and not proxy_ok

    # -------------------------------------------------------------------------
    # Output — always in manual mode; only on failure in cron mode
    # -------------------------------------------------------------------------
    all_failures = critical_failures + warn_failures
    has_critical = len(critical_failures) > 0

    if not is_cron or has_critical:
        print()
        print("=" * 64)
        print(f"DingDawg Health Monitor — {timestamp}")
        print("=" * 64)

        for name, url, expected, actual, passed, body, is_critical in results:
            if name == "Backend Health Body":
                # Display body check differently — it's a content check, not status
                tag = "PASS" if passed else "FAIL"
                print(f"  [{tag}] {name}: {body}")
                if not passed:
                    print(f"         URL: {url}")
                continue

            tag = "PASS" if passed else ("FAIL" if is_critical else "WARN")
            exp_label = f"unreachable" if expected == 0 else str(expected)
            act_label = f"unreachable" if actual == 0 else str(actual)
            print(f"  [{tag}] {name}: {act_label} (expected {exp_label})")
            if not passed:
                print(f"         URL: {url}")
                print(f"         Body: {body[:200]}")

        print("=" * 64)

        if domain_mismatch:
            print()
            print("  *** DOMAIN MISMATCH DETECTED ***")
            print("  Railway backend is UP but Vercel proxy is returning errors.")
            print("  Most likely cause: Vercel BACKEND_URL env var points to old Railway domain.")
            print("  Fix: Vercel dashboard → Settings → Environment Variables → update BACKEND_URL")
            print(f"  Correct value: {RAILWAY_URL}")

        if all_failures:
            print()
            print(f"  CRITICAL FAILURES ({len(critical_failures)}):" if critical_failures else "  CRITICAL FAILURES: none")
            for msg in critical_failures:
                print(f"    - {msg}")
            if warn_failures:
                print(f"  WARNINGS ({len(warn_failures)}):")
                for msg in warn_failures:
                    print(f"    - {msg}")

            if has_critical:
                notify_msg = f"{len(critical_failures)} health check(s) failed:\n" + "\n".join(critical_failures[:3])
                if domain_mismatch:
                    notify_msg = "DOMAIN MISMATCH: Update Vercel BACKEND_URL\n" + notify_msg
                notify("DingDawg ALERT", notify_msg)
                write_log(timestamp, critical_failures)
        else:
            print()
            passed_count = len(results)
            print(f"  All {passed_count} checks passed.")

    return 1 if has_critical else 0


if __name__ == "__main__":
    sys.exit(main())
