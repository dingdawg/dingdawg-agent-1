"use client";

/**
 * PasskeyButton — Login button that triggers WebAuthn passkey authentication.
 *
 * Renders a fingerprint/biometric icon button for the login page.
 * Disabled when email is empty or WebAuthn is not supported.
 * Gold accent styling matching the existing design system.
 */

import { usePasskey } from "@/hooks/usePasskey";

// ─── Props ─────────────────────────────────────────────────────────────────────

export interface PasskeyButtonProps {
  email: string;
  onSuccess: (result: { access_token: string; user_id: string }) => void;
  onError?: (error: string) => void;
  className?: string;
}

// ─── Fingerprint SVG icon (inline — no emoji, no external dependency) ─────────

function FingerprintIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M2 12C2 6.5 6.5 2 12 2a10 10 0 0 1 8 4" />
      <path d="M5 19.5C5.5 18 6 15 6 12c0-1.6.6-3.1 1.6-4.3" />
      <path d="M17.5 21c-.2-1.1-.4-2.3-.5-3.5" />
      <path d="M22 12c0 4-2.5 7.4-6 8.9" />
      <path d="M12 12c0 2-1 4-2 5" />
      <path d="M8 12c0-2.2 1.8-4 4-4s4 1.8 4 4c0 1-.3 1.9-.7 2.7" />
      <path d="M12 8c1.1 0 2 .9 2 2" />
    </svg>
  );
}

// ─── Component ─────────────────────────────────────────────────────────────────

export function PasskeyButton({
  email,
  onSuccess,
  onError,
  className,
}: PasskeyButtonProps) {
  const { authenticateWithPasskey, isSupported, isLoading, error } =
    usePasskey();

  const isDisabled = !isSupported || !email || isLoading;

  const handleClick = async () => {
    if (isDisabled) return;

    const result = await authenticateWithPasskey(email);

    if (result) {
      onSuccess(result);
    } else {
      const errorMsg = error ?? "Passkey authentication failed.";
      onError?.(errorMsg);
    }
  };

  return (
    <div>
      <button
        type="button"
        onClick={handleClick}
        disabled={isDisabled}
        aria-label="Sign in with Passkey"
        className={[
          "flex items-center gap-2",
          "bg-[var(--gold-500)] text-[var(--ink-950)]",
          "rounded-xl px-4 py-3",
          "text-sm font-semibold",
          "transition-colors hover:bg-[var(--gold-600)]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)]",
          "disabled:opacity-50 disabled:pointer-events-none",
          "w-full justify-center",
          className ?? "",
        ]
          .join(" ")
          .trim()}
      >
        <FingerprintIcon className="h-5 w-5 flex-shrink-0" />
        {isLoading ? "Verifying..." : "Sign in with Passkey"}
      </button>

      {!isSupported && (
        <p
          role="alert"
          className="mt-2 text-xs text-[var(--color-muted)] text-center"
        >
          Passkeys are not supported in this browser.
        </p>
      )}

      {error && isSupported && (
        <p
          role="alert"
          className="mt-2 text-xs text-red-400 text-center"
        >
          {error}
        </p>
      )}
    </div>
  );
}
