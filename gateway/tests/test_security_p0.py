"""P0 tests for security.py — CommandFilter "dd" substring false positive fix.

Verifies that the denylist entry "dd" blocks the actual dd command but does NOT
cause false positives on commands that merely contain the substring "dd" (e.g.
"add", "oddity").
"""

from isg_agent.core.security import CommandFilter


class TestCommandFilterDdFalsePositive:
    """Tests that single-word denylist entries use exact command-name matching."""

    def test_dd_command_is_blocked(self) -> None:
        """The actual 'dd' command with arguments must be blocked."""
        cf = CommandFilter()
        result = cf.check("dd if=/dev/zero of=/dev/null bs=1M count=10")
        assert not result.allowed, f"Expected 'dd' to be blocked, got: {result.reason}"
        assert "dd" in result.reason.lower()

    def test_add_command_is_not_blocked(self) -> None:
        """'add file.txt' must NOT be blocked — 'add' is not 'dd'."""
        cf = CommandFilter()
        result = cf.check("add file.txt")
        # "add" is not in the allowlist either, so it should be "not allowed" for a
        # different reason — but it must NOT mention the "dd" denied pattern.
        assert "denied" not in result.reason.lower() or "dd" not in result.reason.lower(), (
            f"'add' was incorrectly blocked by 'dd' denylist entry: {result.reason}"
        )

    def test_oddity_command_is_not_blocked(self) -> None:
        """'oddity' must NOT be blocked — 'oddity' is not 'dd'."""
        cf = CommandFilter()
        result = cf.check("oddity --help")
        assert "denied" not in result.reason.lower() or "dd" not in result.reason.lower(), (
            f"'oddity' was incorrectly blocked by 'dd' denylist entry: {result.reason}"
        )

    def test_bare_dd_is_blocked(self) -> None:
        """A bare 'dd' command with no arguments must be blocked."""
        cf = CommandFilter()
        result = cf.check("dd")
        assert not result.allowed, "Bare 'dd' should be blocked"

    def test_multiword_denied_pattern_still_works(self) -> None:
        """Multi-word denied patterns like 'rm -rf /' still use substring matching."""
        cf = CommandFilter()
        result = cf.check("rm -rf /")
        assert not result.allowed, "'rm -rf /' should be blocked"

    def test_curl_is_blocked(self) -> None:
        """Single-word denylist entry 'curl' blocks the curl command."""
        cf = CommandFilter()
        result = cf.check("curl https://example.com")
        assert not result.allowed, "'curl' should be blocked"

    def test_allowed_command_passes(self) -> None:
        """An allowed command like 'python3' should pass."""
        cf = CommandFilter()
        result = cf.check("python3 script.py")
        assert result.allowed, f"'python3' should be allowed, got: {result.reason}"

    def test_malformed_command_is_denied(self) -> None:
        """Commands with unclosed quotes are denied (fail-closed)."""
        cf = CommandFilter()
        result = cf.check("echo 'unclosed")
        assert not result.allowed, "Malformed commands should be denied"
