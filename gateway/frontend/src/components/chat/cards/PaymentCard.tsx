"use client";

/**
 * PaymentCard — Stripe payment display within chat.
 *
 * Does NOT embed Stripe Elements — that requires Stripe.js SDK integration
 * by the parent. This card shows the formatted amount, description, and
 * a Pay button that triggers the parent's onPay callback.
 *
 * Status states:
 *   pending   → blue accent, active Pay button
 *   processing → spinner, Pay button disabled
 *   completed  → green check, no Pay button
 *   failed     → red X, no Pay button
 */

import { CheckCircle, XCircle, Loader2, CreditCard } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type PaymentStatus = "pending" | "processing" | "completed" | "failed";

interface PaymentCardProps {
  /** Amount in the smallest currency unit (cents for USD). */
  amount: number;
  currency: string;
  description: string;
  onPay: () => void;
  status: PaymentStatus;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatAmount(amount: number, currency: string): string {
  const major = amount / 100;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency.toUpperCase(),
    minimumFractionDigits: 2,
  }).format(major);
}

const statusConfig: Record<
  PaymentStatus,
  { label: string; labelColor: string; dotColor: string }
> = {
  pending: {
    label: "Pending",
    labelColor: "text-blue-400",
    dotColor: "bg-blue-400",
  },
  processing: {
    label: "Processing…",
    labelColor: "text-yellow-400",
    dotColor: "bg-yellow-400",
  },
  completed: {
    label: "Paid",
    labelColor: "text-green-400",
    dotColor: "bg-green-400",
  },
  failed: {
    label: "Payment Failed",
    labelColor: "text-red-400",
    dotColor: "bg-red-400",
  },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function PaymentCard({
  amount,
  currency,
  description,
  onPay,
  status,
}: PaymentCardProps) {
  const config = statusConfig[status];
  const formattedAmount = formatAmount(amount, currency);

  return (
    <div className="glass-panel-gold p-4 card-enter">
      {/* Header row */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <div className="h-9 w-9 rounded-xl bg-[var(--gold-500)]/15 flex items-center justify-center flex-shrink-0">
            <CreditCard className="h-4 w-4 text-[var(--gold-500)]" />
          </div>
          <div>
            <p className="text-xs text-[var(--color-muted)] font-body">Payment</p>
            <p className="text-base font-heading font-bold text-[var(--foreground)]">
              {formattedAmount}
            </p>
          </div>
        </div>

        {/* Status indicator */}
        <div
          className={`flex items-center gap-1.5 ${config.labelColor}`}
          data-status={status}
        >
          {status === "processing" && (
            <Loader2
              role="status"
              aria-label="processing payment"
              className="h-4 w-4 animate-spin"
            />
          )}
          {status === "completed" && <CheckCircle className="h-4 w-4" />}
          {status === "failed" && <XCircle className="h-4 w-4" />}
          {status === "pending" && (
            <span className={`h-2 w-2 rounded-full ${config.dotColor}`} />
          )}
          <span className="text-xs font-medium">{config.label}</span>
        </div>
      </div>

      {/* Description */}
      <p className="text-sm text-[var(--color-muted)] mb-4">{description}</p>

      {/* Divider */}
      <div className="border-t border-[var(--color-gold-stroke)] mb-4" />

      {/* Pay button — only shown for pending/processing */}
      {(status === "pending" || status === "processing") && (
        <button
          onClick={status === "pending" ? onPay : undefined}
          disabled={status === "processing"}
          className={
            "w-full min-h-12 py-3 px-4 rounded-xl text-sm font-semibold font-heading " +
            "transition-all active:scale-[0.98] " +
            (status === "pending"
              ? "bg-[var(--gold-500)] text-[#07111c] hover:bg-[var(--gold-600)]"
              : "bg-white/10 text-[var(--color-muted)] cursor-not-allowed opacity-60")
          }
        >
          {status === "processing" ? "Processing…" : `Pay ${formattedAmount}`}
        </button>
      )}

      {/* Completed state */}
      {status === "completed" && (
        <div className="flex items-center gap-2 justify-center py-2">
          <CheckCircle className="h-5 w-5 text-green-400" />
          <span className="text-sm font-medium text-green-400">Payment Successful</span>
        </div>
      )}

      {/* Failed state */}
      {status === "failed" && (
        <div className="flex items-center gap-2 justify-center py-2">
          <XCircle className="h-5 w-5 text-red-400" />
          <span className="text-sm font-medium text-red-400">Payment Declined</span>
        </div>
      )}
    </div>
  );
}
