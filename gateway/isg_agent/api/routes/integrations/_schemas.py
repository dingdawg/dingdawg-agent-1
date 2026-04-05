"""Pydantic request/body schemas for the notify-integrations API.

All models live here so every sub-module can import them without
circular dependencies.  No FastAPI or route logic in this file.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class EmailConfigRequest(BaseModel):
    """Body for configuring SendGrid on an agent."""

    api_key: str = Field(..., min_length=1, description="SendGrid API key.")
    from_email: str = Field(..., min_length=1, max_length=254, description="Verified sender email address.")
    from_name: Optional[str] = Field(default="", max_length=100, description="Display name for outbound emails.")


class SmsConfigRequest(BaseModel):
    """Body for configuring Twilio on an agent."""

    account_sid: str = Field(..., min_length=1, description="Twilio Account SID.")
    auth_token: str = Field(..., min_length=1, description="Twilio Auth Token.")
    from_number: str = Field(..., min_length=1, max_length=20, description="Twilio source phone number (E.164 format).")


class VapiConfigRequest(BaseModel):
    """Body for configuring Vapi voice on an agent."""

    api_key: str = Field(..., min_length=1, description="Vapi API key.")
    voice_model: Optional[str] = Field(default="eleven_multilingual_v2", description="ElevenLabs voice model.")
    first_message: Optional[str] = Field(
        default="Hi! How can I help you today?",
        max_length=500,
        description="Opening message spoken to callers.",
    )


class GoogleCalendarCallbackRequest(BaseModel):
    """Body for completing the Google Calendar OAuth2 flow.

    The ``state`` field carries an HMAC-signed ``agent_id`` that was
    round-tripped through the Google OAuth consent screen.  This lets
    the callback use a single FIXED redirect URI (no ``{agent_id}``
    path segment) while still associating tokens with the correct agent.
    """

    code: str = Field(..., min_length=1, description="OAuth2 authorisation code received from Google redirect.")
    state: str = Field(..., min_length=1, description="HMAC-signed state parameter containing the agent_id.")


class DisconnectRequest(BaseModel):
    """Body for disconnecting any integration."""

    integration: str = Field(
        ...,
        description="Integration name: 'google_calendar', 'sendgrid', 'email', 'twilio', 'sms', 'vapi', 'voice'.",
    )


class TestIntegrationRequest(BaseModel):
    """Body for testing a configured integration."""

    integration: str = Field(
        ...,
        description="Integration to test: 'sendgrid', 'email', 'twilio', 'sms'.",
    )
