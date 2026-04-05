"use client";

/**
 * PricingPlans — displays the 4 subscription tiers with upgrade buttons.
 *
 * Uses StripeCheckout for paid plans (Stripe Checkout hosted redirect).
 * Free plan downgrade handled locally via existing /subscribe endpoint.
 *
 * Tiers (must match backend PRICING_TIERS and usage_meter.py):
 *   free       — $0/mo     — 50 actions
 *   starter    — $49.99/mo — 500 actions
 *   pro        — $79.99/mo — 2000 actions
 *   enterprise — $499/mo   — unlimited
 *
 * NOTE: The prices shown here are the DISPLAY prices.
 * The actual charge is determined by the Stripe Price object in your
 * Stripe dashboard, configured via STRIPE_PRICE_* env vars.
 */

import { useCallback, useEffect, useState } from "react";
import { CheckCircle, Zap, TrendingUp, Shield } from "lucide-react";
import { StripeCheckout } from "./StripeCheckout";
import { post } from "@/services/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PricingTier {
  id: "free" | "starter" | "pro" | "enterprise";
  label: string;
  /** Monthly price in dollars (0 = free) */
  price: number;
  /** Included actions per month (-1 = unlimited, null = unlimited display) */
  actionsIncluded: number | null;
  /** Short feature bullets */
  features: string[];
  /** Lucide icon */
  Icon: React.ElementType;
  /** Highlight colour token for text */
  color: string;
  /** Highlight colour token for border/bg */
  highlight: string;
  /** Whether this is the recommended (most popular) plan */
  recommended?: boolean;
}

export interface PricingPlansProps {
  /** The current plan ID for this agent */
  currentPlan: string;
  /** Agent ID to associate subscriptions with */
  agentId: string;
  /** Called when the plan is successfully changed (free plan only) */
  onPlanChanged?: () => void;
  /** Called on any error */
  onError?: (message: string) => void;
}

// ---------------------------------------------------------------------------
// Plan definitions
// ---------------------------------------------------------------------------

const PLANS: PricingTier[] = [
  {
    id: "free",
    label: "Free",
    price: 0,
    actionsIncluded: 50,
    features: ["50 agent actions/mo", "1 agent", "Community support"],
    Icon: Zap,
    color: "text-slate-400",
    highlight: "bg-slate-500/10 border-slate-500/20",
  },
  {
    id: "starter",
    label: "Starter",
    price: 49.99,
    actionsIncluded: 500,
    features: [
      "500 agent actions/mo",
      "Up to 3 agents",
      "Email + chat support",
      "Usage analytics",
    ],
    Icon: TrendingUp,
    color: "text-blue-400",
    highlight: "bg-blue-500/10 border-blue-500/20",
  },
  {
    id: "pro",
    label: "Pro",
    price: 79.99,
    actionsIncluded: 2000,
    features: [
      "2,000 agent actions/mo",
      "Up to 10 agents",
      "Priority support",
      "Advanced analytics",
      "Custom integrations",
    ],
    Icon: Shield,
    color: "text-purple-400",
    highlight: "bg-purple-500/10 border-purple-500/20",
    recommended: true,
  },
  {
    id: "enterprise",
    label: "Enterprise",
    price: 499,
    actionsIncluded: null,
    features: [
      "Unlimited agent actions",
      "Unlimited agents",
      "Dedicated account manager",
      "Custom integrations",
      "SLA guarantee (99.9% uptime)",
      "White-label deployment",
      "SSO / SAML",
      "Priority onboarding & training",
    ],
    Icon: Shield,
    color: "text-[var(--gold-500)]",
    highlight: "bg-[var(--gold-500)]/10 border-[var(--gold-500)]/30",
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatActions(n: number | null): string {
  if (n === null) return "Unlimited actions/mo";
  if (n === -1) return "Unlimited actions/mo";
  return `${n.toLocaleString()} actions/mo`;
}

// ---------------------------------------------------------------------------
// PlanCard
// ---------------------------------------------------------------------------

interface PlanCardProps {
  tier: PricingTier;
  isCurrent: boolean;
  agentId: string;
  onDowngrade: (planId: string) => Promise<void>;
  isDowngrading: boolean;
}

function PlanCard({
  tier,
  isCurrent,
  agentId,
  onDowngrade,
  isDowngrading,
}: PlanCardProps) {
  const { id, label, price, actionsIncluded, features, Icon, color, highlight, recommended } =
    tier;
  const isPaid = price > 0;

  return (
    <div
      className={[
        "glass-panel p-5 flex flex-col gap-4 relative transition-all duration-200",
        isCurrent
          ? "border-[var(--gold-500)] ring-1 ring-[var(--gold-500)]/30"
          : "border-[var(--stroke)] hover:border-[var(--gold-500)]/40",
      ].join(" ")}
    >
      {/* Recommended badge */}
      {recommended && !isCurrent && (
        <div className="absolute -top-2.5 left-1/2 -translate-x-1/2">
          <span className="text-[10px] font-bold px-2.5 py-0.5 rounded-full bg-[var(--gold-500)] text-[#07111c] uppercase tracking-widest shadow">
            Most Popular
          </span>
        </div>
      )}

      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <span
            className={[
              "flex items-center justify-center h-8 w-8 rounded-lg",
              highlight,
            ].join(" ")}
          >
            <Icon className={`h-4 w-4 ${color}`} />
          </span>
          <div>
            <p className={`font-heading font-bold text-sm ${color}`}>{label}</p>
            {isCurrent && (
              <p className="text-[10px] text-[var(--gold-500)] font-semibold uppercase tracking-wide">
                Current plan
              </p>
            )}
          </div>
        </div>
        <div className="text-right">
          <p className="text-2xl font-bold text-[var(--foreground)] tabular-nums">
            ${price}
          </p>
          <p className="text-xs text-[var(--color-muted)]">/month</p>
        </div>
      </div>

      {/* Actions included */}
      <p className={`text-sm font-semibold ${color}`}>
        {formatActions(actionsIncluded)}
      </p>

      {/* Feature list */}
      <ul className="space-y-1.5 flex-1">
        {features.map((f) => (
          <li key={f} className="flex items-center gap-2 text-xs text-[var(--color-muted)]">
            <CheckCircle className={`h-3.5 w-3.5 flex-shrink-0 ${color}`} />
            {f}
          </li>
        ))}
      </ul>

      {/* CTA */}
      <div className="mt-auto pt-2">
        {isCurrent ? (
          <div className="w-full py-2 px-4 rounded-lg bg-white/5 text-center text-sm font-semibold text-[var(--foreground)] border border-[var(--stroke)]">
            Current Plan
          </div>
        ) : isPaid ? (
          <StripeCheckout
            plan={id}
            agentId={agentId}
            label={`Upgrade to ${label}`}
          />
        ) : (
          /* Downgrade to Free */
          <button
            onClick={() => onDowngrade(id)}
            disabled={isDowngrading}
            className="w-full py-2 px-4 rounded-lg font-semibold text-sm transition-all border border-[var(--stroke)] text-[var(--foreground)] hover:bg-white/5 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isDowngrading ? (
              <span className="flex items-center justify-center gap-2">
                <span className="inline-block h-3.5 w-3.5 rounded-full border-2 border-[var(--foreground)]/30 border-t-[var(--foreground)] animate-spin" />
                Downgrading…
              </span>
            ) : (
              "Downgrade to Free"
            )}
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// PricingPlans (main export)
// ---------------------------------------------------------------------------

interface DowngradeResponse {
  plan: string;
  status: string;
  created_at: string;
}

export function PricingPlans({
  currentPlan,
  agentId,
  onPlanChanged,
  onError,
}: PricingPlansProps) {
  const [downgradingTo, setDowngradingTo] = useState<string | null>(null);

  // Handle free plan downgrade (no Stripe needed)
  const handleDowngrade = useCallback(
    async (planId: string) => {
      if (planId !== "free") return; // only free uses this path
      setDowngradingTo(planId);
      try {
        await post<DowngradeResponse>("/api/v1/payments/subscribe", {
          agent_id: agentId,
          plan: planId,
        });
        onPlanChanged?.();
      } catch (err: unknown) {
        const message =
          (err as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail ??
          (err as Error)?.message ??
          "Failed to change plan.";
        onError?.(message);
      } finally {
        setDowngradingTo(null);
      }
    },
    [agentId, onPlanChanged, onError]
  );

  return (
    <div className="space-y-4">
      {/* Grid: 2 cols on sm, 4 on lg */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {PLANS.map((tier) => (
          <PlanCard
            key={tier.id}
            tier={tier}
            isCurrent={currentPlan === tier.id}
            agentId={agentId}
            onDowngrade={handleDowngrade}
            isDowngrading={downgradingTo === tier.id}
          />
        ))}
      </div>

      <p className="text-xs text-[var(--color-muted)] text-center">
        Paid plans are billed monthly. Cancel anytime via the billing portal.
        Actions beyond your plan are billed at $1.00/action.
      </p>
    </div>
  );
}

// Re-export StripeCheckout for convenience
export { StripeCheckout } from "./StripeCheckout";
