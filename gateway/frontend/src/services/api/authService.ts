/**
 * Authentication service — register, login, logout.
 *
 * Backend endpoints:
 *   POST /auth/register  — { email, password }
 *   POST /auth/login     — { email, password }
 */

import { get, post } from "./client";

export interface AuthTokens {
  access_token: string;
  token_type: string;
}

export interface UserInfo {
  id: string;
  email: string;
}

export interface RegisterResponse {
  user_id: string;
  email: string;
  access_token: string;
  token_type: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  email: string;
}

/** Extra fields passed to register for bot prevention and legal consent (all optional). */
export interface RegisterBotFields {
  /** Honeypot field value — must be empty for real users. */
  website?: string;
  /** Cloudflare Turnstile verification token. */
  turnstile_token?: string;
  /** Unix timestamp (seconds) when the page was loaded, for timing analysis. */
  page_load_at?: number;
  /** Whether the user accepted the Terms of Service and Privacy Policy. */
  terms_accepted?: boolean;
  /** ISO 8601 timestamp of when the user accepted the terms (legal audit trail). */
  terms_accepted_at?: string;
}

/**
 * Register a new user account.
 *
 * Bot Prevention Layer 0:
 *   - website: honeypot field (empty = human, filled = bot silent reject)
 *   - turnstile_token: Cloudflare Turnstile challenge token
 *   - page_load_at: page load timestamp for timing analysis
 */
export async function register(
  email: string,
  password: string,
  botFields?: RegisterBotFields
): Promise<RegisterResponse> {
  return post<RegisterResponse>("/auth/register", {
    email,
    password,
    website: botFields?.website ?? "",
    turnstile_token: botFields?.turnstile_token ?? "",
    ...(botFields?.page_load_at !== undefined
      ? { page_load_at: botFields.page_load_at }
      : {}),
    terms_accepted: botFields?.terms_accepted ?? false,
    ...(botFields?.terms_accepted_at !== undefined
      ? { terms_accepted_at: botFields.terms_accepted_at }
      : {}),
  });
}

/**
 * Log in with email and password.
 * Returns access_token + user info.
 */
export async function login(
  email: string,
  password: string
): Promise<LoginResponse> {
  return post<LoginResponse>("/auth/login", { email, password });
}

/**
 * Log out — client-side only (clear tokens from memory).
 */
export function logout(): void {
  // Token clearing handled by authStore
}

/**
 * Get current user profile (validates token is still valid server-side).
 */
export async function getMe(): Promise<LoginResponse> {
  return get<LoginResponse>("/auth/me");
}

/**
 * Server-side logout — invalidate the current token by hashing it into
 * the revoked_tokens table.  Failure is non-fatal; client state is
 * cleared regardless.
 */
export async function serverLogout(): Promise<void> {
  try {
    await post<{ message: string }>("/auth/logout");
  } catch {
    // Logout failure is non-fatal — clear client state regardless
  }
}

/**
 * Request a password reset email for the given address.
 * Always resolves with a 200 (backend prevents email enumeration).
 */
export async function forgotPassword(
  email: string
): Promise<{ message: string }> {
  return post<{ message: string }>("/auth/forgot-password", { email });
}

/**
 * Consume a reset token and set a new password.
 */
export async function resetPassword(
  token: string,
  newPassword: string
): Promise<{ message: string }> {
  return post<{ message: string }>("/auth/reset-password", {
    token,
    new_password: newPassword,
  });
}

/**
 * Verify an email address via a magic-link token.
 */
export async function verifyEmail(
  token: string
): Promise<{ message: string; verified: boolean }> {
  return (
    await import("./client").then((m) => m.get)
  )<{ message: string; verified: boolean }>(`/auth/verify-email/${token}`);
}

/**
 * Resend the verification email for an account.
 * Always resolves with 200 (no information leak).
 */
export async function resendVerification(
  email: string
): Promise<{ message: string }> {
  return post<{ message: string }>("/auth/resend-verification", { email });
}

// ---------------------------------------------------------------------------
// MFA / 2FA
// ---------------------------------------------------------------------------

export interface MfaSetupResponse {
  secret: string;
  otpauth_uri: string;
}

export interface MfaVerifySetupResponse {
  backup_codes: string[];
  mfa_enabled: boolean;
}

export interface MfaChallengeResponse {
  user_id: string;
  email: string;
  access_token: string;
  token_type: string;
  remember_device_set: boolean;
}

export interface MfaStatusResponse {
  mfa_enabled: boolean;
  has_phone: boolean;
  backup_codes_remaining: number;
}

/** GET /auth/mfa/status — current MFA state for logged-in user. */
export async function getMfaStatus(): Promise<MfaStatusResponse> {
  return get<MfaStatusResponse>("/auth/mfa/status");
}

/** POST /auth/mfa/setup — generate TOTP secret + QR URI. Requires Bearer. */
export async function mfaSetupStart(): Promise<MfaSetupResponse> {
  return post<MfaSetupResponse>("/auth/mfa/setup", {});
}

/** POST /auth/mfa/verify-setup — confirm first TOTP code, activate MFA, receive backup codes. */
export async function mfaVerifySetup(
  secret: string,
  code: string
): Promise<MfaVerifySetupResponse> {
  return post<MfaVerifySetupResponse>("/auth/mfa/verify-setup", { secret, code });
}

/** POST /auth/mfa/challenge — verify TOTP/backup/SMS during login flow. */
export async function mfaChallenge(params: {
  challenge_token: string;
  code: string;
  code_type: "totp" | "backup" | "sms";
  remember_device: boolean;
}): Promise<MfaChallengeResponse> {
  return post<MfaChallengeResponse>("/auth/mfa/challenge", params);
}

/** POST /auth/mfa/sms — send SMS OTP during login challenge. */
export async function mfaSendSms(
  challenge_token: string
): Promise<{ message: string }> {
  return post<{ message: string }>("/auth/mfa/sms", { challenge_token });
}

/** POST /auth/mfa/disable — disable MFA (requires password + TOTP). */
export async function mfaDisable(
  password: string,
  totp_code: string
): Promise<{ message: string }> {
  return post<{ message: string }>("/auth/mfa/disable", { password, totp_code });
}

/** POST /auth/mfa/phone — register phone number for SMS OTP. */
export async function mfaRegisterPhone(
  phone_number: string
): Promise<{ message: string }> {
  return post<{ message: string }>("/auth/mfa/phone", { phone_number });
}
