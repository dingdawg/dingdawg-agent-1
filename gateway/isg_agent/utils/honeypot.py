"""Honeypot field validation — Part 2 of Bot Prevention Layer 0.

Honeypot fields are invisible HTML inputs that look legitimate to bots but
are hidden from real users (CSS: position absolute, left -9999px, etc.).
Real users never fill them. Bots that auto-fill all fields always will.

Server-side logic:
    - If the honeypot field is empty (or absent), allow the request.
    - If the honeypot field has ANY value, silently reject (return fake success).
    - Log the event for monitoring.

Never raise an HTTPException on honeypot failure — always return fake 200
to avoid teaching bot authors what triggered the block.

Usage::

    from isg_agent.utils.honeypot import check_honeypot

    result = check_honeypot(honeypot_value=form_data.get("website"))
    if result.is_bot:
        logger.warning("Honeypot triggered: %s", result.reason)
        # Return FAKE success — do NOT create account
        return AuthResponse(user_id="fake", email=email, access_token="fake")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

__all__ = [
    "HoneypotResult",
    "check_honeypot",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HoneypotResult:
    """Result of a honeypot field validation check.

    Attributes
    ----------
    is_bot:
        True if the honeypot field was filled (bot detected).
    reason:
        Human-readable reason for the bot classification, or None if clean.
    trigger:
        The raw value that triggered the detection, or None if clean.
    """

    is_bot: bool
    reason: Optional[str]
    trigger: Optional[str]


def check_honeypot(honeypot_value: Optional[str]) -> HoneypotResult:
    """Check whether the honeypot field was filled by a bot.

    Parameters
    ----------
    honeypot_value:
        The value submitted in the honeypot field. None or empty string means
        the field was left blank (as expected for real users).

    Returns
    -------
    HoneypotResult
        Result with ``is_bot=True`` if the field was filled, ``False`` otherwise.

    Notes
    -----
    - An empty string is treated as clean (field submitted but empty).
    - Whitespace-only strings are treated as bot activity (bots may pad values).
    - None is treated as clean (field was not submitted at all).

    Example
    -------
    ::

        result = check_honeypot(honeypot_value=request.body.get("website"))
        if result.is_bot:
            logger.warning("Honeypot triggered from IP %s: %s", client_ip, result.reason)
            # Return fake success — never raise HTTPException
            return _fake_success_response()
    """
    # None = field absent from form submission. Clean.
    if honeypot_value is None:
        return HoneypotResult(is_bot=False, reason=None, trigger=None)

    # Empty string = field submitted but empty. Clean (expected for real users).
    if honeypot_value == "":
        return HoneypotResult(is_bot=False, reason=None, trigger=None)

    # Any non-empty value — including whitespace-only — is a bot signal.
    # Bots may pad with spaces; real users never touch this field.
    trigger = honeypot_value
    reason = f"honeypot field filled with value (len={len(trigger.strip())} chars)"
    logger.warning(
        "Bot prevention: honeypot triggered. Value length=%d",
        len(trigger),
    )
    return HoneypotResult(is_bot=True, reason=reason, trigger=trigger)
