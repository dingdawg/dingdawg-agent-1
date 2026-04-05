"use client";

/**
 * CookieConsent — minimal localStorage-based cookie notice.
 *
 * Appears at the bottom of the screen on first visit.
 * Once dismissed (Accept or Decline), the choice is stored in localStorage
 * under the key "dd_cookie_consent" and the banner never shows again.
 *
 * No tracking or analytics is gated on acceptance in this version —
 * this banner exists purely as a legal disclosure notice.
 */

import { useEffect, useState } from "react";
import Link from "next/link";

const STORAGE_KEY = "dd_cookie_consent";

export default function CookieConsent() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (!stored) setVisible(true);
    } catch {
      // localStorage unavailable (private browsing etc.) — don't show
    }
  }, []);

  const dismiss = (choice: "accepted" | "declined") => {
    try {
      localStorage.setItem(STORAGE_KEY, choice);
    } catch {
      // ignore write failures
    }
    setVisible(false);
  };

  if (!visible) return null;

  return (
    <div
      role="dialog"
      aria-label="Cookie consent"
      aria-live="polite"
      className="fixed bottom-0 left-0 right-0 z-[9999] p-4 sm:p-5 bg-[var(--ink-950)] border-t border-[var(--stroke)] shadow-2xl"
      style={{ paddingBottom: "max(1.25rem, env(safe-area-inset-bottom, 1.25rem))" }}
    >
      <div className="max-w-4xl mx-auto flex flex-col sm:flex-row items-start sm:items-center gap-4">
        {/* Text */}
        <p className="flex-1 text-sm text-[var(--color-muted)] leading-relaxed">
          We use essential cookies to keep you signed in and remember your
          preferences. We do not use advertising or cross-site tracking cookies.{" "}
          <Link
            href="/privacy"
            className="text-[var(--gold-500)] hover:underline whitespace-nowrap"
          >
            Privacy Policy
          </Link>
        </p>

        {/* Actions */}
        <div className="flex items-center gap-3 flex-shrink-0">
          <button
            onClick={() => dismiss("declined")}
            className="px-4 py-2 rounded-lg text-sm text-[var(--color-muted)] border border-[var(--stroke)] hover:border-white/20 hover:text-[var(--foreground)] transition-colors"
          >
            Decline
          </button>
          <button
            onClick={() => dismiss("accepted")}
            className="px-4 py-2 rounded-lg text-sm font-semibold bg-[var(--gold-500)] text-[#07111c] hover:opacity-90 transition-opacity"
          >
            Accept
          </button>
        </div>
      </div>
    </div>
  );
}
