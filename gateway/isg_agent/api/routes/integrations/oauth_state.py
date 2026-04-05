"""HMAC-signed OAuth state helpers.

These functions create and verify the signed ``state`` parameter used
during Google OAuth2 flows.  Signing prevents an attacker from forging a
callback that associates OAuth tokens with an arbitrary agent.

The same scheme is used by ``isg_agent.api.routes.oauth._sign_state``.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac


def sign_oauth_state(agent_id: str, secret_key: str) -> str:
    """Create an HMAC-signed state parameter encoding the agent_id.

    Format: ``{agent_id}:{hmac_hex_16}``
    """
    sig = _hmac.new(
        secret_key.encode("utf-8"),
        agent_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]
    return f"{agent_id}:{sig}"


def verify_oauth_state(state: str, secret_key: str) -> str | None:
    """Verify and extract the agent_id from a signed state parameter.

    Returns the agent_id string if the HMAC signature is valid, or
    ``None`` if the state is missing, malformed, or tampered with.
    """
    if not state or ":" not in state:
        return None
    agent_id, sig = state.rsplit(":", 1)
    if not agent_id or not sig:
        return None
    expected = _hmac.new(
        secret_key.encode("utf-8"),
        agent_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]
    if not _hmac.compare_digest(sig, expected):
        return None
    return agent_id


# Private-name aliases kept for backward compat (the original file used
# underscore-prefixed names; the thin router re-exports them under those names).
_sign_oauth_state = sign_oauth_state
_verify_oauth_state = verify_oauth_state
