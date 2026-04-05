"""Inbound webhook endpoints: receive events from SendGrid, Twilio, and Google Calendar.

These endpoints are PUBLIC — no JWT required.  Each service uses its own
authentication mechanism:

- SendGrid Inbound Parse: HTTP Basic Auth (username/password configured via
  ISG_AGENT_SENDGRID_INBOUND_USER + ISG_AGENT_SENDGRID_INBOUND_PASS env vars).
- Twilio: HMAC-SHA1 signature validation via X-Twilio-Signature header
  (validated against ISG_AGENT_TWILIO_AUTH_TOKEN env var; skipped when not set).
- Google Calendar push: validates X-Goog-Channel-ID and X-Goog-Resource-State
  headers.

All inbound messages are normalised to an ``InboundMessage`` dataclass.
The target agent is looked up from the recipient address/number via the
AgentRegistry.  If found, the message is processed by the AgentRuntime and
an optional outbound response is queued.

External services (SendGrid, Twilio, Google) expect a fast HTTP 200 ACK.
Agent processing errors do NOT propagate back — the endpoint always returns
200 so the external service does not retry unnecessarily.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

__all__ = ["router", "InboundMessage"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks-inbound"])


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class InboundMessage:
    """Normalised representation of an inbound event from any channel.

    Attributes
    ----------
    source:
        Channel origin — ``"email"``, ``"sms"``, or ``"calendar"``.
    sender:
        Email address or E.164 phone number of the originating party.
    subject:
        Email subject line; empty string for SMS and calendar events.
    body:
        Message text body.  For calendar push events this is the resource
        state string (e.g. ``"exists"``).
    agent_id:
        UUID of the target agent resolved from the recipient address.
        Empty string when no matching agent was found.
    raw_payload:
        The original parsed request body preserved for audit purposes.
    timestamp:
        ISO 8601 UTC timestamp when the webhook was received.
    """

    source: str
    sender: str
    subject: str
    body: str
    agent_id: str
    raw_payload: dict
    timestamp: str


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _check_sendgrid_basic_auth(request: Request) -> bool:
    """Validate the HTTP Basic Auth header for SendGrid Inbound Parse.

    Compares against ISG_AGENT_SENDGRID_INBOUND_USER and
    ISG_AGENT_SENDGRID_INBOUND_PASS environment variables.

    Returns True if credentials are valid, False otherwise.
    """
    expected_user = os.environ.get("ISG_AGENT_SENDGRID_INBOUND_USER", "")
    expected_pass = os.environ.get("ISG_AGENT_SENDGRID_INBOUND_PASS", "")

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        return False

    try:
        encoded = auth_header[len("Basic "):]
        decoded = base64.b64decode(encoded).decode("utf-8")
        parts = decoded.split(":", 1)
        if len(parts) != 2:
            return False
        username, password = parts[0], parts[1]
    except Exception:
        return False

    # Constant-time comparison to prevent timing attacks
    user_ok = hmac.compare_digest(username, expected_user)
    pass_ok = hmac.compare_digest(password, expected_pass)
    return user_ok and pass_ok


def _check_twilio_signature(request: Request, form_params: dict[str, str]) -> bool:
    """Validate the Twilio HMAC-SHA1 webhook signature.

    If ISG_AGENT_TWILIO_AUTH_TOKEN is not configured, validation is skipped
    and the request is allowed through (permissive dev-mode behaviour).

    Returns True if signature is valid or validation is skipped, False if
    signature is present but invalid.
    """
    auth_token = os.environ.get("ISG_AGENT_TWILIO_AUTH_TOKEN", "")
    if not auth_token:
        # Dev mode: no token configured → allow all
        logger.warning("Twilio auth token not configured — webhook signature validation skipped")
        return True

    twilio_sig = request.headers.get("X-Twilio-Signature", "")
    if not twilio_sig:
        # Token configured but no signature header → reject
        return False

    # Reconstruct the URL used for signature generation
    url = str(request.url)

    # Sort params and concatenate
    sorted_params = sorted(form_params.items())
    s = url + "".join(f"{k}{v}" for k, v in sorted_params)

    expected_sig = base64.b64encode(
        hmac.new(auth_token.encode(), s.encode(), hashlib.sha1).digest()
    ).decode()

    return hmac.compare_digest(twilio_sig, expected_sig)


# ---------------------------------------------------------------------------
# Agent lookup helper
# ---------------------------------------------------------------------------


async def _lookup_agent_from_recipient(
    recipient: str,
    request: Request,
) -> Optional[str]:
    """Attempt to resolve a target agent_id from a recipient address.

    For email addresses the local part (before @) is treated as the agent
    handle.  For multiple comma-separated recipients, the first address is
    used.

    Parameters
    ----------
    recipient:
        Recipient email address or phone number from the inbound message.
    request:
        The FastAPI request object (used to access app.state.agent_registry).

    Returns
    -------
    str or None
        The agent UUID if found, or None if no matching agent exists.
    """
    if not recipient:
        return None

    # Strip leading/trailing whitespace and take first if comma-separated
    first_recipient = recipient.strip().split(",")[0].strip()

    # Extract handle from email address
    handle: str = first_recipient
    if "@" in first_recipient:
        handle = first_recipient.split("@")[0].strip()
        # Remove angle brackets if present (e.g. "Name <handle@domain.com>")
        if "<" in handle:
            handle = handle.split("<")[-1].strip().rstrip(">")

    if not handle:
        return None

    registry = getattr(request.app.state, "agent_registry", None)
    if registry is None:
        return None

    try:
        agent = await registry.get_agent_by_handle(handle)
        return agent.id if agent is not None else None
    except Exception:
        logger.exception("Agent registry lookup failed for handle %r", handle)
        return None


# ---------------------------------------------------------------------------
# Internal processing helper
# ---------------------------------------------------------------------------


async def _process_inbound_message(
    msg: InboundMessage,
    request: Request,
) -> Optional[str]:
    """Process an InboundMessage through the AgentRuntime.

    Creates a temporary session, runs the message through process_message,
    and returns the agent's response content.

    Returns the response content string, or None if processing failed or the
    runtime is unavailable.
    """
    if not msg.agent_id:
        return None

    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        logger.warning("AgentRuntime not available; cannot process inbound message")
        return None

    try:
        session_mgr = runtime._sessions  # noqa: SLF001
        # Use a synthetic user_id for webhook-originated messages
        synthetic_user_id = f"webhook:{msg.source}:{msg.sender or 'unknown'}"
        session = await session_mgr.create_session(
            user_id=synthetic_user_id,
            agent_id=msg.agent_id,
        )

        # Build a contextual message body including subject when present
        full_message = msg.body
        if msg.subject:
            full_message = f"[Subject: {msg.subject}]\n{msg.body}"

        agent_response = await runtime.process_message(
            session_id=session.session_id,
            user_message=full_message,
            user_id=synthetic_user_id,
        )
        return agent_response.content
    except Exception:
        logger.exception(
            "Failed to process inbound %s message via AgentRuntime", msg.source
        )
        return None


# ---------------------------------------------------------------------------
# SendGrid inbound email endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/sendgrid/inbound",
    status_code=status.HTTP_200_OK,
    summary="Receive inbound email from SendGrid Inbound Parse",
)
async def sendgrid_inbound(request: Request) -> dict:
    """Receive and process an inbound email delivered by SendGrid Inbound Parse.

    PUBLIC endpoint — authenticated via HTTP Basic Auth credentials configured
    in ISG_AGENT_SENDGRID_INBOUND_USER and ISG_AGENT_SENDGRID_INBOUND_PASS.

    SendGrid sends a POST with a JSON or multipart body containing:
    - ``from``     : sender email address
    - ``to``       : recipient email address (maps to agent handle)
    - ``subject``  : email subject
    - ``text``     : plain-text body
    - ``html``     : HTML body (fallback when text is absent)

    The endpoint resolves the target agent from the ``to`` address, processes
    the email through the AgentRuntime, and returns 200 immediately.

    Returns 401 if Basic Auth credentials are invalid.
    """
    # Validate Basic Auth
    if not _check_sendgrid_basic_auth(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing SendGrid inbound credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )

    # Parse body — SendGrid can send JSON or form data
    try:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            body = await request.json()
        elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            form = await request.form()
            body = dict(form)
        else:
            # Attempt JSON first, fall back to empty
            try:
                body = await request.json()
            except Exception:
                body = {}
    except Exception:
        logger.warning("Failed to parse SendGrid inbound body")
        body = {}

    sender = str(body.get("from", ""))
    recipient = str(body.get("to", ""))
    subject = str(body.get("subject", ""))
    text_body = str(body.get("text", ""))
    html_body = str(body.get("html", ""))
    message_body = text_body or html_body

    # Resolve target agent from recipient
    agent_id = await _lookup_agent_from_recipient(recipient, request)

    msg = InboundMessage(
        source="email",
        sender=sender,
        subject=subject,
        body=message_body,
        agent_id=agent_id or "",
        raw_payload=dict(body),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    # Process through AgentRuntime (best-effort — errors do not break the ACK)
    response_text = await _process_inbound_message(msg, request)

    result: dict = {"status": "ok"}
    if agent_id:
        result["agent_id"] = agent_id
    if response_text is not None:
        result["response"] = response_text

    logger.info(
        "SendGrid inbound: from=%r to=%r subject=%r agent_id=%r",
        sender,
        recipient,
        subject,
        agent_id,
    )
    return result


# ---------------------------------------------------------------------------
# Twilio inbound SMS endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/twilio/inbound",
    status_code=status.HTTP_200_OK,
    summary="Receive inbound SMS from Twilio",
)
async def twilio_inbound(request: Request) -> dict:
    """Receive and process an inbound SMS delivered by Twilio.

    PUBLIC endpoint — authenticated via Twilio HMAC-SHA1 signature in the
    ``X-Twilio-Signature`` header, validated against
    ISG_AGENT_TWILIO_AUTH_TOKEN.  When the env var is not set, signature
    validation is skipped (dev-mode permissive behaviour).

    Twilio sends a form-encoded POST with:
    - ``From``       : sender phone number (E.164)
    - ``To``         : recipient phone number
    - ``Body``       : message text
    - ``MessageSid`` : unique message identifier

    Returns 401 if signature validation fails when an auth token is configured.
    """
    # Parse form data
    try:
        form = await request.form()
        form_params = {k: str(v) for k, v in form.items()}
    except Exception:
        form_params = {}

    # Validate Twilio signature
    if not _check_twilio_signature(request, form_params):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Twilio signature validation failed.",
        )

    sender = form_params.get("From", "")
    recipient = form_params.get("To", "")
    message_body = form_params.get("Body", "")

    # Resolve target agent from recipient phone number (match by phone config)
    # For now, agent lookup by phone is best-effort via handle registry
    agent_id = await _lookup_agent_from_recipient(recipient, request)

    msg = InboundMessage(
        source="sms",
        sender=sender,
        subject="",
        body=message_body,
        agent_id=agent_id or "",
        raw_payload=form_params,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    response_text = await _process_inbound_message(msg, request)

    result: dict = {"status": "ok"}
    if agent_id:
        result["agent_id"] = agent_id
    if response_text is not None:
        result["response"] = response_text

    logger.info(
        "Twilio inbound SMS: from=%r to=%r agent_id=%r",
        sender,
        recipient,
        agent_id,
    )
    return result


# ---------------------------------------------------------------------------
# Google Calendar push notification endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/google-calendar/push",
    status_code=status.HTTP_200_OK,
    summary="Receive Google Calendar push notifications",
)
async def google_calendar_push(request: Request) -> dict:
    """Receive a Google Calendar resource change push notification.

    PUBLIC endpoint — validated by checking required Google-supplied headers.

    Google sends a POST with the following headers:
    - ``X-Goog-Channel-ID``     : the watch channel ID (required)
    - ``X-Goog-Resource-State`` : resource state — ``sync``, ``exists``, or
      ``not_exists`` (required)
    - ``X-Goog-Resource-ID``    : the resource being watched
    - ``X-Goog-Resource-URI``   : URI of the resource (optional)

    A ``sync`` state is the initial verification ping sent by Google when the
    watch channel is established.

    Returns 400 if required headers are missing.
    Returns 200 immediately with ``{"status": "ok"}`` or
    ``{"status": "acknowledged"}`` for sync events.
    """
    channel_id = request.headers.get("X-Goog-Channel-ID", "")
    resource_state = request.headers.get("X-Goog-Resource-State", "")
    resource_id = request.headers.get("X-Goog-Resource-ID", "")

    if not channel_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required header: X-Goog-Channel-ID",
        )

    if not resource_state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required header: X-Goog-Resource-State",
        )

    # Sync events are Google's initial channel verification ping
    if resource_state == "sync":
        logger.info(
            "Google Calendar channel established: channel_id=%r resource_id=%r",
            channel_id,
            resource_id,
        )
        return {"status": "acknowledged", "channel_id": channel_id}

    # Build a calendar InboundMessage for change events
    msg = InboundMessage(
        source="calendar",
        sender="",
        subject="",
        body=resource_state,
        agent_id="",  # Calendar lookup requires channel-to-agent mapping (future)
        raw_payload={
            "channel_id": channel_id,
            "resource_state": resource_state,
            "resource_id": resource_id,
        },
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    logger.info(
        "Google Calendar push: channel_id=%r resource_state=%r resource_id=%r",
        channel_id,
        resource_state,
        resource_id,
    )

    return {"status": "ok", "channel_id": channel_id, "resource_state": resource_state}
