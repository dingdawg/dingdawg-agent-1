"use client";

/**
 * usePasskey — React hook for WebAuthn/Passkey authentication.
 *
 * Wraps 4 passkey API endpoints with browser WebAuthn credential API:
 *   POST /api/v1/auth/passkey/register/begin     — start registration
 *   POST /api/v1/auth/passkey/register/complete  — finish registration
 *   POST /api/v1/auth/passkey/authenticate/begin    — start authentication
 *   POST /api/v1/auth/passkey/authenticate/complete — finish authentication
 *
 * Challenge / credential ID conversion:
 *   base64url string → ArrayBuffer (for create/get options)
 *   ArrayBuffer      → base64url string (for sending response to server)
 */

import { useState, useCallback } from "react";
import { post } from "@/services/api/client";

// ─── Types ─────────────────────────────────────────────────────────────────────

export interface PasskeyAuthResult {
  access_token: string;
  user_id: string;
  email: string;
}

export interface PasskeyHookReturn {
  registerPasskey: (deviceName?: string) => Promise<boolean>;
  authenticateWithPasskey: (email: string) => Promise<PasskeyAuthResult | null>;
  isSupported: boolean;
  isLoading: boolean;
  error: string | null;
}

// ─── Binary / base64url helpers ────────────────────────────────────────────────

function base64urlToBuffer(base64url: string): ArrayBuffer {
  const base64 = base64url.replace(/-/g, "+").replace(/_/g, "/");
  const pad =
    base64.length % 4 === 0 ? "" : "=".repeat(4 - (base64.length % 4));
  const binary = atob(base64 + pad);
  const buffer = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    buffer[i] = binary.charCodeAt(i);
  }
  return buffer.buffer;
}

function bufferToBase64url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// ─── Server response shapes ────────────────────────────────────────────────────

interface RegisterBeginResponse {
  session_id: string;
  options: {
    challenge: string;
    rp: { name: string; id?: string };
    user: { id: string; name: string; displayName: string };
    pubKeyCredParams: Array<{ type: string; alg: number }>;
    timeout?: number;
    attestation?: AttestationConveyancePreference;
    authenticatorSelection?: AuthenticatorSelectionCriteria;
  };
}

interface AuthenticateBeginResponse {
  session_id: string;
  options: {
    challenge: string;
    timeout?: number;
    rpId?: string;
    allowCredentials?: Array<{ type: string; id: string }>;
    userVerification?: UserVerificationRequirement;
  };
}

interface RegisterCompleteResponse {
  verified: boolean;
  message?: string;
}

// ─── Hook ──────────────────────────────────────────────────────────────────────

export function usePasskey(): PasskeyHookReturn {
  const isSupported =
    typeof window !== "undefined" && !!window.PublicKeyCredential;

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── Register ────────────────────────────────────────────────────────────────

  const registerPasskey = useCallback(
    async (deviceName?: string): Promise<boolean> => {
      if (!isSupported) {
        setError("Passkeys are not supported in this browser.");
        return false;
      }

      setIsLoading(true);
      setError(null);

      try {
        // Step 1: get creation options from server
        const beginData = await post<RegisterBeginResponse>(
          "/api/v1/auth/passkey/register/begin",
          { device_name: deviceName ?? "My Device" }
        );

        const { session_id, options } = beginData;

        // Step 2: build PublicKeyCredentialCreationOptions
        const createOptions: PublicKeyCredentialCreationOptions = {
          challenge: base64urlToBuffer(options.challenge),
          rp: options.rp,
          user: {
            id: base64urlToBuffer(options.user.id),
            name: options.user.name,
            displayName: options.user.displayName,
          },
          pubKeyCredParams: options.pubKeyCredParams as PublicKeyCredentialParameters[],
          timeout: options.timeout,
          attestation: options.attestation,
          authenticatorSelection: options.authenticatorSelection,
        };

        // Step 3: invoke browser WebAuthn credential creation
        const credential = (await navigator.credentials.create({
          publicKey: createOptions,
        })) as PublicKeyCredential | null;

        if (!credential) {
          setError("Credential creation was cancelled or failed.");
          return false;
        }

        const response = credential.response as AuthenticatorAttestationResponse;

        // Step 4: send credential to server
        const completePayload = {
          session_id,
          credential_id: credential.id,
          raw_id: bufferToBase64url(credential.rawId),
          response: {
            client_data_json: bufferToBase64url(response.clientDataJSON),
            attestation_object: bufferToBase64url(response.attestationObject),
          },
          type: credential.type,
          device_name: deviceName ?? "My Device",
        };

        const result = await post<RegisterCompleteResponse>(
          "/api/v1/auth/passkey/register/complete",
          completePayload
        );

        if (!result.verified) {
          setError(result.message ?? "Passkey registration failed.");
          return false;
        }

        return true;
      } catch (err: unknown) {
        // DOMException from navigator.credentials.create() is expected on cancel
        const message =
          err instanceof Error ? err.message : "Passkey registration failed.";
        setError(message);
        return false;
      } finally {
        setIsLoading(false);
      }
    },
    [isSupported]
  );

  // ── Authenticate ────────────────────────────────────────────────────────────

  const authenticateWithPasskey = useCallback(
    async (email: string): Promise<PasskeyAuthResult | null> => {
      if (!isSupported) {
        setError("Passkeys are not supported in this browser.");
        return null;
      }

      if (!email) {
        setError("Email is required for passkey authentication.");
        return null;
      }

      setIsLoading(true);
      setError(null);

      try {
        // Step 1: get assertion options from server
        const beginData = await post<AuthenticateBeginResponse>(
          "/api/v1/auth/passkey/authenticate/begin",
          { email }
        );

        const { session_id, options } = beginData;

        // Step 2: build PublicKeyCredentialRequestOptions
        const allowCredentials: PublicKeyCredentialDescriptor[] | undefined =
          options.allowCredentials?.map((cred) => ({
            type: cred.type as PublicKeyCredentialType,
            id: base64urlToBuffer(cred.id),
          }));

        const getOptions: PublicKeyCredentialRequestOptions = {
          challenge: base64urlToBuffer(options.challenge),
          timeout: options.timeout,
          rpId: options.rpId,
          allowCredentials,
          userVerification: options.userVerification,
        };

        // Step 3: invoke browser WebAuthn assertion
        const assertion = (await navigator.credentials.get({
          publicKey: getOptions,
        })) as PublicKeyCredential | null;

        if (!assertion) {
          setError("Passkey authentication was cancelled or failed.");
          return null;
        }

        const response = assertion.response as AuthenticatorAssertionResponse;

        // Step 4: send assertion to server
        const completePayload = {
          session_id,
          email,
          credential_id: assertion.id,
          raw_id: bufferToBase64url(assertion.rawId),
          response: {
            client_data_json: bufferToBase64url(response.clientDataJSON),
            authenticator_data: bufferToBase64url(response.authenticatorData),
            signature: bufferToBase64url(response.signature),
            user_handle: response.userHandle
              ? bufferToBase64url(response.userHandle)
              : null,
          },
          type: assertion.type,
        };

        const result = await post<PasskeyAuthResult>(
          "/api/v1/auth/passkey/authenticate/complete",
          completePayload
        );

        return result;
      } catch (err: unknown) {
        const message =
          err instanceof Error ? err.message : "Passkey authentication failed.";
        setError(message);
        return null;
      } finally {
        setIsLoading(false);
      }
    },
    [isSupported]
  );

  return {
    registerPasskey,
    authenticateWithPasskey,
    isSupported,
    isLoading,
    error,
  };
}
