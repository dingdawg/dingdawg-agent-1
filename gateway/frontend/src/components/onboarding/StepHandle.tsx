"use client";

/**
 * StepHandle — Step 3 of the onboarding wizard.
 *
 * The "money shot" step.  Renders a large, prominent @handle input with:
 *  - Real-time availability feedback (green check / red X)
 *  - Inline error messaging (format validation, taken, loading)
 *  - Auto-focus on mount for keyboard users
 *  - Mobile keyboard-aware layout (the input stays above the keyboard)
 *
 * The parent passes the debounced check state so this component is purely
 * presentational — no async logic lives here.
 */

import { useEffect, useRef } from "react";

export type HandleStatus = "idle" | "checking" | "available" | "taken" | "invalid";

interface StepHandleProps {
  value: string;
  onChange: (value: string) => void;
  status: HandleStatus;
  reason?: string | null;
  /** Whether the user has interacted with the input at all. */
  touched: boolean;
}

const STATUS_MESSAGES: Record<HandleStatus, string | null> = {
  idle: null,
  checking: null,
  available: null,  // set dynamically with handle value
  taken: null,      // set dynamically
  invalid: null,    // set via reason prop
};

export function StepHandle({
  value,
  onChange,
  status,
  reason,
  touched,
}: StepHandleProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-focus on mount — mobile users expect the keyboard to appear
  useEffect(() => {
    const t = setTimeout(() => inputRef.current?.focus(), 100);
    return () => clearTimeout(t);
  }, []);

  const showAvailable = touched && status === "available" && value.length >= 3;
  const showTaken = touched && status === "taken" && value.length >= 3;
  const showInvalid = touched && status === "invalid" && value.length > 0;
  const showChecking = touched && status === "checking" && value.length >= 3;

  const statusColor = showAvailable
    ? "text-emerald-400"
    : showTaken || showInvalid
    ? "text-red-400"
    : "text-[var(--color-muted)]";

  const borderColor = showAvailable
    ? "border-emerald-400/60 focus-within:border-emerald-400"
    : showTaken || showInvalid
    ? "border-red-400/60 focus-within:border-red-400"
    : "border-[var(--stroke)] focus-within:border-[var(--gold-500)]/70";

  const helperText = (() => {
    if (showAvailable) return `@${value} is available`;
    if (showTaken) return `@${value} is already taken`;
    if (showInvalid) return reason ?? "Invalid handle format";
    if (!touched || value.length === 0) return "3–30 characters, letters, numbers, hyphens";
    if (value.length < 3) return "3–30 characters, letters, numbers, hyphens";
    return "3–30 characters, letters, numbers, hyphens";
  })();

  return (
    <div>
      {/* Large @handle input */}
      <div
        className={`
          relative flex items-center rounded-2xl border transition-all duration-150
          bg-white/4 px-4 py-0
          ${borderColor}
        `}
      >
        {/* @ prefix */}
        <span
          className="text-[var(--gold-500)] font-bold text-2xl select-none flex-shrink-0 mr-1"
          aria-hidden="true"
        >
          @
        </span>

        {/* Handle input */}
        <input
          ref={inputRef}
          id="handle"
          type="text"
          value={value}
          onChange={(e) => {
            // Strip invalid chars on input — only allow a-z, 0-9, hyphens
            const v = e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "");
            onChange(v);
          }}
          placeholder="your-handle"
          maxLength={30}
          autoComplete="off"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          inputMode="text"
          className={`
            flex-1 bg-transparent text-2xl font-medium py-4 outline-none
            placeholder:text-white/20 transition-colors
            ${showAvailable ? "text-emerald-400" : "text-[var(--foreground)]"}
          `}
          aria-label="Choose your @handle"
          aria-describedby="handle-helper"
          aria-invalid={showTaken || showInvalid ? "true" : "false"}
        />

        {/* Right-side status icon */}
        <div className="flex-shrink-0 ml-2 w-6 flex justify-center">
          {showChecking && (
            <span className="inline-block h-5 w-5 rounded-full border-2 border-white/20 border-t-[var(--gold-500)] animate-spin" />
          )}
          {showAvailable && (
            <svg
              className="h-5 w-5 text-emerald-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2.5}
              aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          )}
          {(showTaken || showInvalid) && (
            <svg
              className="h-5 w-5 text-red-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2.5}
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          )}
        </div>
      </div>

      {/* Helper / status text */}
      <p
        id="handle-helper"
        className={`mt-2 text-xs transition-colors ${statusColor}`}
      >
        {helperText}
      </p>
    </div>
  );
}
