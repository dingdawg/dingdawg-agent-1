"""Extended auth endpoints: password reset and email verification.

Endpoints
---------
POST /auth/forgot-password          — send a password reset email (real token)
POST /auth/reset-password           — consume token, set new password
GET  /auth/verify-email/{token}     — verify email address via magic link
POST /auth/resend-verification      — resend a verification email

All rate-limited. All token-related responses are generic to prevent
information disclosure.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from isg_agent.auth.email_verification import (
    EmailVerificationManager,
    VerificationRateLimitedError,
    VerificationTokenExpiredError,
    VerificationTokenInvalidError,
    VerificationTokenUsedError,
)
from isg_agent.auth.password_reset import (
    PasswordResetManager,
    RateLimitedError,
    TokenExpiredError,
    TokenInvalidError,
    TokenUsedError,
)

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth-extended"])

# ---------------------------------------------------------------------------
# Config (module-level, set by app startup)
# ---------------------------------------------------------------------------

_db_path: str = "data/agent.db"
_frontend_url: str = "https://app.dingdawg.com"


def _set_auth_extended_config(db_path: str, frontend_url: str) -> None:
    """Set module-level config (called from app lifespan)."""
    global _db_path, _frontend_url  # noqa: PLW0603
    _db_path = db_path
    _frontend_url = frontend_url.rstrip("/")
    logger.info(
        "auth_extended configured: db=%s frontend=%s",
        _db_path,
        _frontend_url,
    )


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ForgotPasswordRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return v.strip().lower()


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password_complexity(cls, v: str) -> str:
        import re
        missing: list[str] = []
        if len(v) < 8:
            missing.append("at least 8 characters")
        if not re.search(r"[A-Z]", v):
            missing.append("at least 1 uppercase letter")
        if not re.search(r"[0-9]", v):
            missing.append("at least 1 digit")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", v):
            missing.append("at least 1 special character (!@#$%^&* etc.)")
        if missing:
            raise ValueError("Password must contain: " + ", ".join(missing))
        return v


class ResendVerificationRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return v.strip().lower()


# ---------------------------------------------------------------------------
# Email HTML templates
# ---------------------------------------------------------------------------

_RESET_EMAIL_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Reset your DingDawg password</title>
</head>
<body style="margin:0;padding:0;background:#0d0d0d;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d0d0d;padding:40px 16px;">
    <tr>
      <td align="center">
        <table width="100%" style="max-width:520px;background:#1a1a1a;border-radius:12px;
               border:1px solid #2a2a2a;overflow:hidden;">
          <!-- Header -->
          <tr>
            <td style="padding:32px 32px 0;text-align:center;">
              <span style="font-size:28px;">&#9889;</span>
              <h1 style="color:#f5c842;font-size:22px;margin:8px 0 4px;">DingDawg Agent</h1>
              <p style="color:#888;font-size:13px;margin:0;">Password Reset Request</p>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:24px 32px;">
              <p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px;">
                We received a request to reset the password for your account.
                Click the button below to set a new password.
              </p>
              <div style="text-align:center;margin:28px 0;">
                <a href="{reset_url}"
                   style="display:inline-block;padding:14px 32px;background:#f5c842;
                          color:#0d0d0d;font-weight:700;font-size:15px;border-radius:8px;
                          text-decoration:none;">
                  Reset My Password
                </a>
              </div>
              <p style="color:#888;font-size:12px;line-height:1.6;margin:20px 0 0;
                        border-top:1px solid #2a2a2a;padding-top:20px;">
                This link expires in <strong style="color:#f5c842;">1 hour</strong>.
                If you did not request a password reset, you can safely ignore this email.
                <br><br>
                Or copy this link into your browser:<br>
                <span style="color:#f5c842;word-break:break-all;">{reset_url}</span>
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding:16px 32px 24px;text-align:center;">
              <p style="color:#555;font-size:11px;margin:0;">
                &copy; 2026 DingDawg &middot;
                <a href="https://dingdawg.com" style="color:#555;">dingdawg.com</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

_RESET_EMAIL_TEXT = (
    "Reset your DingDawg password\n\n"
    "Click the link below to set a new password (expires in 1 hour):\n\n"
    "{reset_url}\n\n"
    "If you did not request a password reset, ignore this email.\n"
)

_VERIFY_EMAIL_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Verify your DingDawg account</title>
</head>
<body style="margin:0;padding:0;background:#0d0d0d;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d0d0d;padding:40px 16px;">
    <tr>
      <td align="center">
        <table width="100%" style="max-width:520px;background:#1a1a1a;border-radius:12px;
               border:1px solid #2a2a2a;overflow:hidden;">
          <!-- Header -->
          <tr>
            <td style="padding:32px 32px 0;text-align:center;">
              <span style="font-size:28px;">&#9889;</span>
              <h1 style="color:#f5c842;font-size:22px;margin:8px 0 4px;">DingDawg Agent</h1>
              <p style="color:#888;font-size:13px;margin:0;">Welcome! One more step.</p>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:24px 32px;">
              <p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px;">
                Thanks for signing up! Please verify your email address to unlock
                all platform features, including creating your own AI agents.
              </p>
              <div style="text-align:center;margin:28px 0;">
                <a href="{verify_url}"
                   style="display:inline-block;padding:14px 32px;background:#f5c842;
                          color:#0d0d0d;font-weight:700;font-size:15px;border-radius:8px;
                          text-decoration:none;">
                  Verify My Email
                </a>
              </div>
              <p style="color:#888;font-size:12px;line-height:1.6;margin:20px 0 0;
                        border-top:1px solid #2a2a2a;padding-top:20px;">
                This link expires in <strong style="color:#f5c842;">24 hours</strong>.
                If you didn't create a DingDawg account, ignore this email.
                <br><br>
                Or copy this link into your browser:<br>
                <span style="color:#f5c842;word-break:break-all;">{verify_url}</span>
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding:16px 32px 24px;text-align:center;">
              <p style="color:#555;font-size:11px;margin:0;">
                &copy; 2026 DingDawg &middot;
                <a href="https://dingdawg.com" style="color:#555;">dingdawg.com</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

_VERIFY_EMAIL_TEXT = (
    "Welcome to DingDawg!\n\n"
    "Please verify your email address to unlock all features:\n\n"
    "{verify_url}\n\n"
    "This link expires in 24 hours.\n"
)

_WELCOME_EMAIL_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Welcome to DingDawg!</title>
</head>
<body style="margin:0;padding:0;background:#0d0d0d;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d0d0d;padding:40px 16px;">
    <tr>
      <td align="center">
        <table width="100%" style="max-width:520px;background:#1a1a1a;border-radius:12px;
               border:1px solid #2a2a2a;overflow:hidden;">
          <!-- Header -->
          <tr>
            <td style="padding:32px 32px 0;text-align:center;">
              <span style="font-size:28px;">&#9889;</span>
              <h1 style="color:#f5c842;font-size:22px;margin:8px 0 4px;">Welcome to DingDawg!</h1>
              <p style="color:#888;font-size:13px;margin:0;">Your account is ready.</p>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:24px 32px;">
              <p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px;">
                Thanks for joining DingDawg! Here&rsquo;s how to get started:
              </p>
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="padding:10px 0;border-bottom:1px solid #2a2a2a;">
                    <span style="color:#f5c842;font-weight:700;font-size:15px;">1.</span>
                    <span style="color:#e0e0e0;font-size:15px;margin-left:8px;">
                      Verify your email to unlock all features
                    </span>
                  </td>
                </tr>
                <tr>
                  <td style="padding:10px 0;border-bottom:1px solid #2a2a2a;">
                    <span style="color:#f5c842;font-weight:700;font-size:15px;">2.</span>
                    <span style="color:#e0e0e0;font-size:15px;margin-left:8px;">
                      Create your first AI agent
                    </span>
                  </td>
                </tr>
                <tr>
                  <td style="padding:10px 0;">
                    <span style="color:#f5c842;font-weight:700;font-size:15px;">3.</span>
                    <span style="color:#e0e0e0;font-size:15px;margin-left:8px;">
                      Deploy your agent to your business
                    </span>
                  </td>
                </tr>
              </table>
              <div style="text-align:center;margin:28px 0;">
                <a href="https://app.dingdawg.com/dashboard"
                   style="display:inline-block;padding:14px 32px;background:#f5c842;
                          color:#0d0d0d;font-weight:700;font-size:15px;border-radius:8px;
                          text-decoration:none;">
                  Go to Dashboard
                </a>
              </div>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding:16px 32px 24px;text-align:center;">
              <p style="color:#555;font-size:11px;margin:0;">
                &copy; 2026 DingDawg &middot;
                <a href="https://dingdawg.com" style="color:#555;">dingdawg.com</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

_WELCOME_EMAIL_TEXT = (
    "Welcome to DingDawg!\n\n"
    "Your account is ready. Here's how to get started:\n\n"
    "1. Verify your email to unlock all features\n"
    "2. Create your first AI agent\n"
    "3. Deploy your agent to your business\n\n"
    "Go to your dashboard: https://app.dingdawg.com/dashboard\n"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_sendgrid(request: Request):  # type: ignore[return]
    """Return the SendGrid connector from app state, or None if not configured."""
    return getattr(request.app.state, "sendgrid", None)


def _get_db_path() -> str:
    return _db_path


def _get_frontend_url() -> str:
    return _frontend_url


# ---------------------------------------------------------------------------
# Password Reset Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/forgot-password",
    summary="Request a password reset email",
    status_code=200,
)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
) -> dict:
    """Send a password reset email.

    Always returns 200 regardless of whether the email is registered —
    never reveals if an account exists (prevents email enumeration).
    """
    db_path = _get_db_path()
    manager = PasswordResetManager(db_path=db_path)

    # Look up the user — silently do nothing if not found
    user = await manager.get_user_by_email(body.email)

    if user is not None:
        try:
            token = await manager.create_token(user_id=user["id"])
        except RateLimitedError:
            # Still return 200 — don't reveal rate limit status to caller
            logger.info(
                "Password reset rate limited for email=%s (returning 200 anyway)",
                body.email,
            )
            return {
                "message": (
                    "If an account exists with that email, "
                    "a password reset link will be sent."
                )
            }

        reset_url = f"{_get_frontend_url()}/reset-password/{token}"

        sendgrid = _get_sendgrid(request)
        if sendgrid is not None:
            try:
                result = await sendgrid.send_email(
                    agent_id="platform",
                    to_email=body.email,
                    subject="Reset your DingDawg password",
                    body=_RESET_EMAIL_TEXT.format(reset_url=reset_url),
                    html_body=_RESET_EMAIL_HTML.format(reset_url=reset_url),
                )
                if not result.get("success"):
                    logger.error(
                        "SendGrid failed for password reset email=%s: %s",
                        body.email,
                        result.get("error"),
                    )
            except Exception as exc:
                logger.error(
                    "Exception sending password reset email=%s: %s",
                    body.email,
                    exc,
                )
        else:
            logger.warning(
                "SendGrid not configured — password reset URL for %s: %s",
                body.email,
                reset_url,
            )

    return {
        "message": (
            "If an account exists with that email, "
            "a password reset link will be sent."
        )
    }


@router.post(
    "/reset-password",
    summary="Set a new password using a reset token",
    status_code=200,
)
async def reset_password(
    body: ResetPasswordRequest,
) -> dict:
    """Consume a password reset token and update the user's password.

    Returns 400 for invalid, expired, or already-used tokens.
    Returns 200 on success with a message to redirect to login.
    """
    from isg_agent.api.routes.auth import _hash_password

    db_path = _get_db_path()
    manager = PasswordResetManager(db_path=db_path)

    new_password_hash, new_salt = _hash_password(body.new_password)

    try:
        user_id = await manager.consume_token_and_reset_password(
            token=body.token,
            new_password_hash=new_password_hash,
            new_salt=new_salt,
        )
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link has expired. Please request a new one.",
        )
    except TokenUsedError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link has already been used.",
        )
    except TokenInvalidError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token.",
        )

    logger.info("Password reset successful for user_id=%s", user_id)
    return {"message": "Password updated successfully. Please log in with your new password."}


# ---------------------------------------------------------------------------
# Email Verification Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/verify-email/{token}",
    summary="Verify email address via magic link",
    status_code=200,
)
async def verify_email(
    token: str,
) -> dict:
    """Consume an email verification token and mark the user as verified.

    Returns 200 on success. Returns 400 for invalid/expired/used tokens.
    """
    db_path = _get_db_path()
    manager = EmailVerificationManager(db_path=db_path)

    try:
        user_id = await manager.verify_token(token)
    except VerificationTokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This verification link has expired. Please request a new one.",
        )
    except VerificationTokenUsedError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This verification link has already been used.",
        )
    except VerificationTokenInvalidError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification link.",
        )

    logger.info("Email verified for user_id=%s", user_id)
    return {
        "message": "Email verified successfully.",
        "verified": True,
    }


@router.post(
    "/resend-verification",
    summary="Resend a verification email",
    status_code=200,
)
async def resend_verification(
    body: ResendVerificationRequest,
    request: Request,
) -> dict:
    """Resend the email verification link for an account.

    Always returns 200 regardless of whether the email is registered.
    If the user is already verified, the email is not re-sent.
    """
    db_path = _get_db_path()
    reset_manager = PasswordResetManager(db_path=db_path)
    verify_manager = EmailVerificationManager(db_path=db_path)

    user = await reset_manager.get_user_by_email(body.email)

    if user is not None:
        # Check if already verified — don't spam verified users
        already_verified = await verify_manager.is_email_verified(user["id"])
        if not already_verified:
            try:
                # rate_limit=True enforces 1 resend per 5 minutes per user.
                token = await verify_manager.create_token(
                    user_id=user["id"], rate_limit=True
                )
                verify_url = f"{_get_frontend_url()}/verify-email/{token}"

                sendgrid = _get_sendgrid(request)
                if sendgrid is not None:
                    try:
                        result = await sendgrid.send_email(
                            agent_id="platform",
                            to_email=body.email,
                            subject="Verify your DingDawg account",
                            body=_VERIFY_EMAIL_TEXT.format(verify_url=verify_url),
                            html_body=_VERIFY_EMAIL_HTML.format(verify_url=verify_url),
                        )
                        if not result.get("success"):
                            logger.error(
                                "SendGrid failed for verification email=%s: %s",
                                body.email,
                                result.get("error"),
                            )
                    except Exception as exc:
                        logger.error(
                            "Exception sending verification email=%s: %s",
                            body.email,
                            exc,
                        )
                else:
                    logger.warning(
                        "SendGrid not configured — verification URL for %s: %s",
                        body.email,
                        verify_url,
                    )
            except VerificationRateLimitedError:
                # Silently swallow — always return 200 to prevent timing attacks.
                # The email is simply not sent; the user must wait out the window.
                logger.info(
                    "Resend verification rate limited for email=%s (returning 200)",
                    body.email,
                )
            except Exception as exc:
                logger.error(
                    "Error creating verification token for email=%s: %s",
                    body.email,
                    exc,
                )

    return {
        "message": (
            "If an account exists with that email that hasn't been verified, "
            "a new verification link will be sent."
        )
    }
