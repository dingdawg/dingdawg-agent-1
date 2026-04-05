"use client";

/**
 * StripeCheckout — redirect-to-Stripe-hosted-checkout component.
 *
 * Pattern: NO Stripe.js, NO Elements, NO @stripe/stripe-js import.
 * The backend creates the Checkout Session and returns a URL.
 * We redirect window.location.href to that URL.
 *
 * Stripe handles PCI compliance, card input, 3D Secure, retries.
 *
 * Backend endpoint:
 *   POST /api/v1/payments/create-checkout-session
 *   Body: { plan: string, agent_id: string }
 *   Response: { checkout_url: string, session_id: string }
 *
 * On success: Stripe redirects to /billing?success=true&session_id=...
 * On cancel:  Stripe redirects to /billing?canceled=true
 *
 * Usage:
 *   <StripeCheckout plan="starter" agentId={agent.id} />
 *   <StripeCheckout plan="pro" agentId={agent.id} label="Go Pro" />
 */

import { useState } from "react";
import { post } from "@/services/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CheckoutSessionResponse {
  checkout_url: string;
  session_id: string;
}

interface StripeCheckoutProps {
  /** The plan to purchase: "starter" | "pro" | "enterprise" */
  plan: string;
  /** The agent ID to associate this subscription with */
  agentId: string;
  /** Button label (default: "Upgrade") */
  label?: string;
  /** Additional Tailwind classes for the button */
  className?: string;
  /** Called after successful redirect initiation */
  onRedirecting?: () => void;
  /** Called if the checkout session request fails */
  onError?: (error: string) => void;
  /** Disable the button (e.g. when this is the current plan) */
  disabled?: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function StripeCheckout({
  plan,
  agentId,
  label = "Upgrade",
  className = "",
  onRedirecting,
  onError,
  disabled = false,
}: StripeCheckoutProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    if (isLoading || disabled) return;
    setIsLoading(true);
    setError(null);

    try {
      const data = await post<CheckoutSessionResponse>(
        "/api/v1/payments/create-checkout-session",
        { plan, agent_id: agentId }
      );

      if (!data.checkout_url) {
        throw new Error("No checkout URL returned from server.");
      }

      onRedirecting?.();

      // Hard redirect — Stripe Checkout requires a full page navigation.
      // Do NOT use router.push — Stripe needs the actual browser URL change.
      window.location.href = data.checkout_url;
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ??
        (err as Error)?.message ??
        "Payment error. Please try again.";

      setError(message);
      onError?.(message);
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-1">
      <button
        onClick={handleClick}
        disabled={disabled || isLoading}
        aria-busy={isLoading}
        className={[
          "w-full py-2 px-4 rounded-lg font-semibold text-sm transition-all",
          "bg-[var(--gold-500)] text-[#07111c]",
          "hover:opacity-90 active:scale-[0.98]",
          "disabled:opacity-50 disabled:cursor-not-allowed",
          "flex items-center justify-center gap-2",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {isLoading ? (
          <>
            <span
              className="inline-block h-3.5 w-3.5 rounded-full border-2 border-[#07111c]/30 border-t-[#07111c] animate-spin"
              aria-hidden="true"
            />
            Redirecting to Stripe…
          </>
        ) : (
          label
        )}
      </button>

      {error && (
        <p className="text-xs text-red-400 mt-1" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// BillingPortalButton — redirects to Stripe Customer Portal
// ---------------------------------------------------------------------------

interface BillingPortalButtonProps {
  agentId?: string;
  label?: string;
  className?: string;
}

interface BillingPortalResponse {
  portal_url: string;
}

export function BillingPortalButton({
  agentId = "",
  label = "Manage Subscription",
  className = "",
}: BillingPortalButtonProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    if (isLoading) return;
    setIsLoading(true);
    setError(null);

    try {
      const params = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
      const { get } = await import("@/services/api/client");
      const data = await get<BillingPortalResponse>(
        `/api/v1/payments/billing-portal${params}`
      );

      if (!data.portal_url) {
        throw new Error("No portal URL returned from server.");
      }

      window.location.href = data.portal_url;
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ??
        (err as Error)?.message ??
        "Could not open billing portal.";
      setError(message);
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-1">
      <button
        onClick={handleClick}
        disabled={isLoading}
        aria-busy={isLoading}
        className={[
          "w-full py-2 px-4 rounded-lg font-semibold text-sm transition-all",
          "border border-[var(--stroke)] text-[var(--foreground)]",
          "hover:bg-white/5 active:scale-[0.98]",
          "disabled:opacity-50 disabled:cursor-not-allowed",
          "flex items-center justify-center gap-2",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {isLoading ? (
          <>
            <span
              className="inline-block h-3.5 w-3.5 rounded-full border-2 border-[var(--foreground)]/30 border-t-[var(--foreground)] animate-spin"
              aria-hidden="true"
            />
            Opening portal…
          </>
        ) : (
          label
        )}
      </button>

      {error && (
        <p className="text-xs text-red-400 mt-1" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
