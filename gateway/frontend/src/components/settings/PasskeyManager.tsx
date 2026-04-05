"use client";

/**
 * PasskeyManager — Settings panel for managing registered passkeys.
 *
 * Displays the list of registered passkeys for the current user.
 * Allows adding new passkeys via the usePasskey hook.
 * Uses glass-panel styling matching existing settings components.
 *
 * Backend endpoints:
 *   GET  /api/v1/auth/passkey/credentials — list registered credentials
 *   POST /api/v1/auth/passkey/register/begin + complete — add new passkey
 */

import { useState, useEffect, useCallback } from "react";
import { KeyRound, Plus, AlertTriangle, CheckCircle } from "lucide-react";
import { usePasskey } from "@/hooks/usePasskey";
import { get } from "@/services/api/client";

// ─── Types ─────────────────────────────────────────────────────────────────────

export interface Passkey {
  credential_id: string;
  device_name: string;
  created_at: string;
  last_used_at: string | null;
}

// ─── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(iso: string | null): string {
  if (!iso) return "Never";
  try {
    return new Intl.DateTimeFormat(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

// ─── Component ─────────────────────────────────────────────────────────────────

export function PasskeyManager() {
  const { registerPasskey, isSupported, isLoading: isRegistering, error: registerError } =
    usePasskey();

  const [passkeys, setPasskeys] = useState<Passkey[]>([]);
  const [isFetching, setIsFetching] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);

  // ── Fetch passkeys ──────────────────────────────────────────────────────────

  const fetchPasskeys = useCallback(async () => {
    setIsFetching(true);
    setFetchError(null);
    try {
      const data = await get<Passkey[]>("/api/v1/auth/passkey/credentials");
      setPasskeys(Array.isArray(data) ? data : []);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? null;
      // Endpoint may not exist yet — treat 404 as empty list, not an error
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 404) {
        setPasskeys([]);
      } else {
        setFetchError(detail ?? "Failed to load passkeys.");
      }
    } finally {
      setIsFetching(false);
    }
  }, []);

  useEffect(() => {
    fetchPasskeys();
  }, [fetchPasskeys]);

  // ── Add passkey ─────────────────────────────────────────────────────────────

  const handleAddPasskey = useCallback(async () => {
    setAddError(null);
    setSuccessMsg(null);
    const ok = await registerPasskey("My Device");
    if (ok) {
      setSuccessMsg("Passkey added successfully.");
      await fetchPasskeys();
      setTimeout(() => setSuccessMsg(null), 3500);
    } else {
      setAddError(registerError ?? "Failed to add passkey.");
    }
  }, [registerPasskey, registerError, fetchPasskeys]);

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <section className="glass-panel p-5">
      {/* Header */}
      <h2 className="text-sm font-heading font-semibold text-[var(--foreground)] mb-1 flex items-center gap-2">
        <KeyRound className="h-4 w-4 text-[var(--gold-500)]" />
        Passkeys
      </h2>
      <p className="text-xs text-[var(--color-muted)] mb-4">
        Use Face ID, Touch ID, or Windows Hello to sign in without a password.
      </p>

      {/* Success */}
      {successMsg && (
        <div className="mb-3 p-3 rounded-xl bg-green-500/10 border border-green-500/20 text-green-400 text-xs flex items-center gap-2 card-enter">
          <CheckCircle className="h-4 w-4 flex-shrink-0" />
          {successMsg}
        </div>
      )}

      {/* Add error */}
      {addError && (
        <div className="mb-3 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-xs flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          {addError}
          <button
            onClick={() => setAddError(null)}
            className="ml-auto text-xs underline"
          >
            dismiss
          </button>
        </div>
      )}

      {/* Fetch error */}
      {fetchError && (
        <div className="mb-3 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-xs flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          {fetchError}
        </div>
      )}

      {/* Passkey list */}
      {isFetching ? (
        <div className="flex items-center justify-center py-6">
          <span className="spinner text-[var(--gold-500)]" aria-label="Loading passkeys" />
        </div>
      ) : passkeys.length === 0 ? (
        <p className="text-xs text-[var(--color-muted)] py-4 text-center">
          No passkeys registered. Add one to enable biometric login.
        </p>
      ) : (
        <ul className="space-y-2 mb-4">
          {passkeys.map((pk) => (
            <li
              key={pk.credential_id}
              className="flex items-center justify-between rounded-xl bg-white/5 border border-[var(--stroke2)] px-4 py-3"
            >
              <div className="flex items-center gap-3">
                <KeyRound className="h-4 w-4 text-[var(--gold-500)] flex-shrink-0" />
                <div>
                  <p className="text-sm font-medium text-[var(--foreground)]">
                    {pk.device_name}
                  </p>
                  <p className="text-xs text-[var(--color-muted)]">
                    Added {formatDate(pk.created_at)}
                    {pk.last_used_at
                      ? ` · Last used ${formatDate(pk.last_used_at)}`
                      : ""}
                  </p>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* Add Passkey button */}
      <button
        type="button"
        onClick={handleAddPasskey}
        disabled={!isSupported || isRegistering}
        aria-label="Add Passkey"
        className={[
          "flex items-center gap-2 mt-2",
          "bg-[var(--gold-500)] text-[var(--ink-950)]",
          "rounded-xl px-4 py-2.5",
          "text-sm font-semibold",
          "transition-colors hover:bg-[var(--gold-600)]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)]",
          "disabled:opacity-50 disabled:pointer-events-none",
          "w-full justify-center",
        ].join(" ")}
      >
        {isRegistering ? (
          <span className="spinner" aria-hidden="true" />
        ) : (
          <>
            <Plus className="h-4 w-4" />
            Add Passkey
          </>
        )}
      </button>

      {!isSupported && (
        <p className="mt-2 text-xs text-[var(--color-muted)] text-center">
          Passkeys are not supported in this browser.
        </p>
      )}
    </section>
  );
}
