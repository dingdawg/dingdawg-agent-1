"use client";

/**
 * TurnstileWidget — Cloudflare Turnstile invisible CAPTCHA integration.
 *
 * Loads the Turnstile script dynamically and executes an invisible challenge.
 * Real users see nothing. Bots fail silently.
 *
 * Pricing: $0 for up to 1M verifications/month (Cloudflare Free tier).
 * Docs: https://developers.cloudflare.com/turnstile/get-started/
 *
 * Environment variables required:
 *   NEXT_PUBLIC_TURNSTILE_SITE_KEY — your Turnstile site key
 *
 * If the site key is not configured, the widget renders nothing and calls
 * onSuccess with an empty token (dev/test mode — backend also skips verification).
 *
 * Usage:
 * ```tsx
 * import { TurnstileWidget } from "@/components/security/TurnstileWidget";
 *
 * function RegisterForm() {
 *   const [turnstileToken, setTurnstileToken] = useState("");
 *
 *   return (
 *     <form>
 *       <TurnstileWidget
 *         siteKey={process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || ""}
 *         onSuccess={setTurnstileToken}
 *       />
 *       ... submit uses turnstileToken ...
 *     </form>
 *   );
 * }
 * ```
 */

import { useEffect, useRef, useState, useCallback } from "react";

interface TurnstileWidgetProps {
  /** The Cloudflare Turnstile site key (from NEXT_PUBLIC_TURNSTILE_SITE_KEY). */
  siteKey: string;
  /** Called when the challenge completes successfully with the token. */
  onSuccess: (token: string) => void;
  /** Called when the challenge fails (optional — widget auto-retries). */
  onError?: () => void;
  /** Called when the token expires (widget will re-execute). */
  onExpired?: () => void;
  /** Theme override. Defaults to "auto" (matches system preference). */
  theme?: "light" | "dark" | "auto";
}

// Cloudflare Turnstile script URL
const TURNSTILE_SCRIPT_URL =
  "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

/*
 * SRI (Subresource Integrity) — deliberate decision NOT to pin a hash here.
 *
 * Reason: Cloudflare continuously updates the Turnstile script at this URL
 * without version-bumping the path. Pinning a SHA-384 hash would cause the
 * script to silently fail (browser blocks mismatched SRI), breaking bot
 * protection for all users the moment Cloudflare pushes an update — which
 * can happen without notice.
 *
 * Defense-in-depth is achieved via the Content-Security-Policy header
 * (see next.config.ts) which restricts script-src to only allow scripts
 * from 'self' and https://challenges.cloudflare.com. This prevents any
 * other origin from injecting scripts, while still allowing Cloudflare to
 * maintain their CDN without breaking our integration.
 *
 * If Cloudflare ever provides a stable versioned URL or a published SRI hash
 * in their official docs, we should adopt it at that point.
 */

// Global script loaded flag (avoid double-loading)
let _scriptLoaded = false;
let _scriptLoading = false;
const _scriptCallbacks: Array<() => void> = [];

function loadTurnstileScript(onLoad: () => void): void {
  if (_scriptLoaded) {
    onLoad();
    return;
  }

  if (_scriptLoading) {
    _scriptCallbacks.push(onLoad);
    return;
  }

  _scriptLoading = true;
  _scriptCallbacks.push(onLoad);

  const script = document.createElement("script");
  script.src = TURNSTILE_SCRIPT_URL;
  script.async = true;
  script.defer = true;
  script.onload = () => {
    _scriptLoaded = true;
    _scriptLoading = false;
    _scriptCallbacks.forEach((cb) => cb());
    _scriptCallbacks.length = 0;
  };
  script.onerror = () => {
    _scriptLoading = false;
    // Callbacks are not called on error — the widget falls back to dev mode
  };

  document.head.appendChild(script);
}

/**
 * TurnstileWidget renders an invisible Cloudflare Turnstile challenge.
 *
 * The challenge runs automatically when the component mounts. No user
 * interaction is required for the invisible variant.
 *
 * Handles:
 * - Expired tokens: auto re-executes the challenge
 * - Errors: calls onError if provided, widget shows visible fallback
 * - Loading state: renders nothing (invisible by design)
 * - Dev mode: if siteKey is empty, immediately calls onSuccess("")
 */
export function TurnstileWidget({
  siteKey,
  onSuccess,
  onError,
  onExpired,
  theme = "auto",
}: TurnstileWidgetProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const widgetIdRef = useRef<string | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);

  const renderWidget = useCallback(() => {
    if (!containerRef.current || !window.turnstile || widgetIdRef.current) {
      return;
    }

    widgetIdRef.current = window.turnstile.render(containerRef.current, {
      sitekey: siteKey,
      callback: (token: string) => {
        onSuccess(token);
      },
      "error-callback": () => {
        onError?.();
      },
      "expired-callback": () => {
        onExpired?.();
        // Re-execute the challenge when the token expires
        if (widgetIdRef.current && window.turnstile) {
          window.turnstile.reset(widgetIdRef.current);
        }
      },
      theme,
      // "invisible" execution mode — no user interaction needed
      execution: "render",
      appearance: "interaction-only",
    });
  }, [siteKey, onSuccess, onError, onExpired, theme]);

  useEffect(() => {
    // No site key configured — skip Turnstile challenge entirely.
    // The 3 other bot prevention layers (honeypot, rate limit, disposable email)
    // remain active and still provide meaningful protection.
    if (!siteKey) {
      if (process.env.NODE_ENV === "production") {
        // Visible in browser DevTools Console and any frontend monitoring tool
        // (e.g. Sentry, Datadog RUM, Vercel Analytics).
        // Signals that NEXT_PUBLIC_TURNSTILE_SITE_KEY is missing from Vercel env vars.
        console.warn(
          "[TurnstileWidget] NEXT_PUBLIC_TURNSTILE_SITE_KEY is not set. " +
            "Turnstile challenge is disabled in production. " +
            "Bot prevention layers 2-4 (honeypot, rate limit, disposable email) remain active. " +
            "Add the site key in Vercel → Settings → Environment Variables to re-enable layer 1."
        );
      }
      onSuccess("");
      return;
    }

    loadTurnstileScript(() => {
      setIsLoaded(true);
    });
  }, [siteKey, onSuccess]);

  useEffect(() => {
    if (isLoaded && siteKey) {
      renderWidget();
    }

    return () => {
      // Cleanup widget on unmount
      if (widgetIdRef.current && window.turnstile) {
        try {
          window.turnstile.remove(widgetIdRef.current);
        } catch {
          // Ignore cleanup errors
        }
        widgetIdRef.current = null;
      }
    };
  }, [isLoaded, siteKey, renderWidget]);

  if (!siteKey) {
    // Dev mode: render a visible warning only during local development so
    // engineers know Turnstile is inactive. Hidden in production via the
    // NODE_ENV guard — the console.warn above handles production visibility.
    if (process.env.NODE_ENV === "development") {
      return (
        <p
          style={{
            fontSize: "11px",
            color: "#f59e0b",
            margin: "4px 0 0",
            opacity: 0.7,
          }}
        >
          Turnstile: dev mode (NEXT_PUBLIC_TURNSTILE_SITE_KEY not set)
        </p>
      );
    }
    return null;
  }

  return (
    <div
      ref={containerRef}
      aria-hidden="true"
      style={{
        // The invisible variant renders with minimal visual footprint
        // When needed (challenge fails), Turnstile shows its own UI
        width: "0px",
        height: "0px",
        overflow: "hidden",
        position: "absolute",
        left: "-9999px",
      }}
    />
  );
}

// Augment Window type for Turnstile global
declare global {
  interface Window {
    turnstile?: {
      render: (
        container: HTMLElement,
        options: Record<string, unknown>
      ) => string;
      reset: (widgetId: string) => void;
      remove: (widgetId: string) => void;
      getResponse: (widgetId: string) => string;
    };
  }
}
