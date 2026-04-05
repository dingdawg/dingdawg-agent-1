"use client";

/**
 * Billing page — subscription plans, skill-action usage meter, and history.
 *
 * Backend endpoints used:
 *   GET  /api/v1/payments/usage/{agent_id}          — current month usage
 *   GET  /api/v1/payments/usage/{agent_id}/history  — monthly history
 *   POST /api/v1/payments/subscribe                 — change plan
 *
 * Pricing tiers match backend PRICING_TIERS:
 *   Free      —  50 actions/mo  — $0/mo
 *   Starter   — 500 actions/mo  — $49.99/mo
 *   Pro       — 2 000 actions/mo — $79.99/mo
 *   Enterprise — unlimited      — $199.99/mo
 */

import { Suspense, useEffect, useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  CreditCard,
  Zap,
  TrendingUp,
  AlertCircle,
  CheckCircle,
  ChevronUp,
} from "lucide-react";
import { useAgentStore } from "@/store/agentStore";
import {
  getSkillUsage,
  getSkillUsageHistory,
  subscribeToPlan,
  createCheckoutSession,
  getSubscriptionStatus,
  type SkillUsageSummary,
  type SubscriptionStatusResponse,
} from "@/services/api/paymentService";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { BillingPortalButton } from "@/components/billing/StripeCheckout";

// ─── Pricing tiers (must match backend PRICING_TIERS) ────────────────────────

interface PricingTier {
  id: string;
  label: string;
  price: number;
  actionsIncluded: number | null; // null = unlimited
  color: string;
  highlight: string;
  features: string[];
}

const PRICING_TIERS: PricingTier[] = [
  {
    id: "free",
    label: "Free",
    price: 0,
    actionsIncluded: 50,
    color: "text-slate-400",
    highlight: "bg-slate-500/10 border-slate-500/20",
    features: ["50 AI actions/month", "1 agent", "Basic chat widget"],
  },
  {
    id: "starter",
    label: "Starter",
    price: 49.99,
    actionsIncluded: 500,
    color: "text-blue-400",
    highlight: "bg-blue-500/10 border-blue-500/20",
    features: ["500 AI actions/month", "Google Calendar integration", "Voice replies (Vapi)"],
  },
  {
    id: "pro",
    label: "Pro",
    price: 79.99,
    actionsIncluded: 2000,
    color: "text-purple-400",
    highlight: "bg-purple-500/10 border-purple-500/20",
    features: ["2,000 AI actions/month", "All integrations", "Analytics dashboard"],
  },
  {
    id: "enterprise",
    label: "Enterprise",
    price: 199.99,
    actionsIncluded: null,
    color: "text-[var(--gold-500)]",
    highlight: "bg-[var(--gold-500)]/10 border-[var(--gold-500)]/30",
    features: ["Unlimited AI actions", "Custom AI personality", "Priority support"],
  },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

function formatMonth(yearMonth: string): string {
  // yearMonth = "2026-03"
  try {
    const parts = yearMonth.split("-");
    const year = Number(parts[0]);
    const month = Number(parts[1]);
    if (!year || !month || month < 1 || month > 12) return yearMonth;
    const date = new Date(year, month - 1, 1);
    return date.toLocaleString("en-US", { month: "long", year: "numeric" });
  } catch {
    return yearMonth;
  }
}

function planLabel(planId: string): string {
  return PRICING_TIERS.find((t) => t.id === planId)?.label ?? planId;
}

// ─── Plan badge ───────────────────────────────────────────────────────────────

function PlanBadge({ plan }: { plan: string }) {
  const tier = PRICING_TIERS.find((t) => t.id === plan);
  if (!tier) return null;
  return (
    <span
      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold border ${tier.highlight} ${tier.color}`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          plan === "free"
            ? "bg-slate-400"
            : plan === "starter"
            ? "bg-blue-400"
            : plan === "pro"
            ? "bg-purple-400"
            : "bg-[var(--gold-500)]"
        }`}
      />
      {tier.label}
    </span>
  );
}

// ─── Usage meter ──────────────────────────────────────────────────────────────

function UsageMeter({ usage }: { usage: SkillUsageSummary }) {
  const unlimited = usage.actions_included === 0;
  const pct = unlimited
    ? 0
    : Math.min(100, Math.round((usage.total_actions / usage.actions_included) * 100));
  const warn = pct >= 80;
  const critical = pct >= 100;

  return (
    <div className="space-y-2">
      <div className="flex items-end justify-between">
        <div>
          <p className="text-2xl font-bold text-[var(--foreground)]">
            {usage.total_actions.toLocaleString()}
            {!unlimited && (
              <span className="text-sm font-normal text-[var(--color-muted)] ml-1">
                / {usage.actions_included.toLocaleString()} actions
              </span>
            )}
          </p>
          {unlimited && (
            <p className="text-sm text-[var(--color-muted)]">
              Unlimited actions
            </p>
          )}
        </div>
        {!unlimited && (
          <p
            className={`text-lg font-semibold tabular-nums ${
              critical
                ? "text-red-400"
                : warn
                ? "text-yellow-400"
                : "text-[var(--gold-500)]"
            }`}
          >
            {pct}%
          </p>
        )}
      </div>

      {!unlimited && (
        <div className="w-full h-2.5 rounded-full bg-white/8 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${
              critical
                ? "bg-red-400"
                : warn
                ? "bg-yellow-400"
                : "bg-[var(--gold-500)]"
            }`}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}

      <div className="flex items-center justify-between text-xs text-[var(--color-muted)]">
        <span>
          <span className="font-semibold text-[var(--foreground)]">
            {usage.remaining_free.toLocaleString()}
          </span>{" "}
          free actions remaining
        </span>
        <span>{formatMonth(usage.year_month)}</span>
      </div>
    </div>
  );
}

// ─── Plan card ────────────────────────────────────────────────────────────────

interface PlanCardProps {
  tier: PricingTier;
  isCurrent: boolean;
  onUpgrade: (planId: string) => void;
  isLoading: boolean;
}

function PlanCard({ tier, isCurrent, onUpgrade, isLoading }: PlanCardProps) {
  return (
    <div
      className={`glass-panel p-4 flex flex-col gap-3 transition-all ${
        isCurrent
          ? "border-[var(--gold-500)] ring-1 ring-[var(--gold-500)]/30"
          : "border-[var(--stroke)]"
      }`}
    >
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <p className={`font-heading font-bold text-base ${tier.color}`}>
            {tier.label}
          </p>
          <p className="text-xl font-bold text-[var(--foreground)] mt-0.5">
            ${tier.price}
            <span className="text-xs font-normal text-[var(--color-muted)]">
              /mo
            </span>
          </p>
        </div>
        {isCurrent && (
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-[var(--gold-500)]/15 text-[var(--gold-500)] border border-[var(--gold-500)]/30 uppercase tracking-wide">
            Current
          </span>
        )}
      </div>

      {/* Actions */}
      <p className="text-sm text-[var(--color-muted)]">
        {tier.actionsIncluded === null
          ? "Unlimited actions"
          : `${tier.actionsIncluded.toLocaleString()} actions/mo`}
      </p>

      {/* Feature bullets */}
      <ul className="flex flex-col gap-1.5">
        {tier.features.map((feature) => (
          <li key={feature} className="flex items-center gap-2 text-xs text-[var(--color-muted)]">
            <span className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${
              tier.id === "free" ? "bg-slate-400" :
              tier.id === "starter" ? "bg-blue-400" :
              tier.id === "pro" ? "bg-purple-400" :
              "bg-[var(--gold-500)]"
            }`} />
            {feature}
          </li>
        ))}
      </ul>

      {/* CTA */}
      {!isCurrent && (
        <button
          onClick={() => onUpgrade(tier.id)}
          disabled={isLoading}
          className="w-full py-2 px-4 rounded-lg bg-[var(--gold-500)] text-[#07111c] font-semibold text-sm transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {isLoading ? (
            <span className="flex items-center justify-center gap-2">
              <span className="spinner h-3.5 w-3.5" />
              Upgrading…
            </span>
          ) : tier.price === 0 ? (
            "Downgrade"
          ) : (
            "Upgrade"
          )}
        </button>
      )}
    </div>
  );
}

// ─── Usage history table ──────────────────────────────────────────────────────

function UsageHistoryTable({ history }: { history: SkillUsageSummary[] }) {
  if (history.length === 0) {
    return (
      <div className="text-center py-8 text-sm text-[var(--color-muted)]">
        No usage history yet.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-[var(--color-muted)] border-b border-[var(--stroke)]">
            <th className="text-left pb-2 font-medium">Month</th>
            <th className="text-right pb-2 font-medium">Plan</th>
            <th className="text-right pb-2 font-medium">Total</th>
            <th className="text-right pb-2 font-medium">Billed</th>
            <th className="text-right pb-2 font-medium">Amount</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--stroke)]">
          {history.map((row) => (
            <tr key={row.year_month} className="text-sm">
              <td className="py-2.5 text-[var(--foreground)]">
                {formatMonth(row.year_month)}
              </td>
              <td className="py-2.5 text-right">
                <PlanBadge plan={row.plan} />
              </td>
              <td className="py-2.5 text-right text-[var(--foreground)] tabular-nums">
                {row.total_actions.toLocaleString()}
              </td>
              <td className="py-2.5 text-right tabular-nums text-[var(--color-muted)]">
                {row.billed_actions.toLocaleString()}
              </td>
              <td className="py-2.5 text-right tabular-nums font-medium text-[var(--foreground)]">
                {formatCents(row.total_amount_cents)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function BillingPage() {
  return (
    <ProtectedRoute>
      <AppShell>
        <Suspense
          fallback={
            <div className="flex items-center justify-center h-full">
              <span className="spinner text-[var(--gold-500)]" />
            </div>
          }
        >
          <BillingContent />
        </Suspense>
      </AppShell>
    </ProtectedRoute>
  );
}

function BillingContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { currentAgent, agents, isLoading: agentsLoading, fetchAgents } =
    useAgentStore();

  const [usage, setUsage] = useState<SkillUsageSummary | null>(null);
  const [history, setHistory] = useState<SkillUsageSummary[]>([]);
  const [subStatus, setSubStatus] = useState<SubscriptionStatusResponse | null>(null);
  const [loadingUsage, setLoadingUsage] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [usageError, setUsageError] = useState<string | null>(null);
  const [subscribingTo, setSubscribingTo] = useState<string | null>(null);
  const [downgradeConfirm, setDowngradeConfirm] = useState(false);
  const [toast, setToast] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  // Handle Stripe redirect query params (success/cancel)
  useEffect(() => {
    if (searchParams.get("success") === "true") {
      setToast({
        type: "success",
        message:
          "Payment successful! Your subscription is now active. It may take a moment to update.",
      });
      // Clean the URL without reloading
      router.replace("/billing", { scroll: false });
    } else if (searchParams.get("canceled") === "true") {
      setToast({
        type: "error",
        message: "Checkout was canceled. No charges were made.",
      });
      router.replace("/billing", { scroll: false });
    }
  }, [searchParams, router]);

  // Fetch agents on mount
  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  // Redirect to /claim if no agents
  useEffect(() => {
    if (!agentsLoading && agents.length === 0) {
      router.replace("/claim");
    }
  }, [agentsLoading, agents.length, router]);

  // Fetch usage + history when agent is known
  const loadData = useCallback(async () => {
    if (!currentAgent) return;

    setLoadingUsage(true);
    setLoadingHistory(true);
    setUsageError(null);

    // Fetch current usage
    getSkillUsage(currentAgent.id)
      .then((data) => setUsage(data))
      .catch((err: unknown) => {
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response
            ?.data?.detail ?? "Failed to load usage";
        setUsageError(detail);
      })
      .finally(() => setLoadingUsage(false));

    // Fetch history (non-blocking)
    getSkillUsageHistory(currentAgent.id)
      .then((data) => setHistory(data))
      .catch(() => {
        // History failure is non-fatal — show empty table
      })
      .finally(() => setLoadingHistory(false));

    // Fetch subscription status (non-blocking, only used if on a paid plan)
    getSubscriptionStatus(currentAgent.id)
      .then((data) => setSubStatus(data))
      .catch(() => {
        // Non-fatal — portal button still renders without status detail
        setSubStatus(null);
      });
  }, [currentAgent]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Auto-dismiss toast
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  const handleUpgrade = async (planId: string) => {
    if (!currentAgent) return;

    // Downgrade confirmation gate
    if (planId === "free" && !downgradeConfirm) {
      setDowngradeConfirm(true);
      return;
    }
    setDowngradeConfirm(false);

    setSubscribingTo(planId);
    try {
      if (planId === "free") {
        // Downgrade to free — handled server-side without Stripe
        await subscribeToPlan(currentAgent.id, planId);
        setToast({
          type: "success",
          message: "Switched to Free plan.",
        });
        await loadData();
      } else {
        // Paid plans — redirect to Stripe Checkout hosted page
        const { checkout_url } = await createCheckoutSession(
          currentAgent.id,
          planId
        );
        // Navigate to Stripe — page leaves so no need to reset subscribingTo
        window.location.href = checkout_url;
      }
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to change plan. Please try again.";
      setToast({ type: "error", message: detail });
      setSubscribingTo(null);
    }
  };

  // Loading state — waiting for agents
  if (agentsLoading && agents.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="spinner text-[var(--gold-500)]" />
      </div>
    );
  }

  if (!currentAgent) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 px-6 text-center">
        <div className="h-14 w-14 rounded-2xl bg-[var(--gold-500)]/10 flex items-center justify-center">
          <CreditCard className="h-7 w-7 text-[var(--gold-500)]" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-[var(--foreground)] mb-1">
            No agent yet
          </h2>
          <p className="text-sm text-[var(--color-muted)]">
            Claim an agent to view billing and usage.
          </p>
        </div>
        <button
          onClick={() => router.replace("/claim")}
          className="px-5 py-2.5 rounded-xl bg-[var(--gold-500)] text-[#07111c] text-sm font-semibold hover:bg-[var(--gold-600)] transition-colors"
        >
          Claim your agent
        </button>
      </div>
    );
  }

  const currentPlanId = usage?.plan ?? "free";

  // Usage urgency: warn at >= 80%, critical at >= 100%
  const usagePct = usage && usage.actions_included > 0
    ? Math.min(100, Math.round((usage.total_actions / usage.actions_included) * 100))
    : 0;
  const showUrgencyBanner = usagePct >= 80 && currentPlanId !== "enterprise";

  return (
    <div className="h-full overflow-y-auto scrollbar-thin">
      <div className="max-w-3xl mx-auto px-4 py-6 pb-6 space-y-5">
        {/* Page header */}
        <PageHeader title="Billing" />
        <div>
          <h1 className="text-xl font-heading font-bold text-[var(--foreground)] flex items-center gap-2">
            <CreditCard className="h-5 w-5 text-[var(--gold-500)]" />
            Billing
          </h1>
          <p className="text-[15px] text-[var(--color-muted)] mt-0.5">
            @{currentAgent.handle} — usage and subscription
          </p>
        </div>

        {/* Usage urgency banner — shown when >= 80% consumed (Stripe/Linear pattern) */}
        {showUrgencyBanner && (
          <div
            className={`p-4 rounded-xl border flex items-start gap-3 ${
              usagePct >= 100
                ? "bg-red-500/10 border-red-500/30 text-red-300"
                : "bg-yellow-500/10 border-yellow-500/30 text-yellow-300"
            }`}
          >
            <AlertCircle className="h-5 w-5 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-sm font-semibold">
                {usagePct >= 100
                  ? "You've used all your actions this month"
                  : `You're using ${usagePct}% of your monthly actions`}
              </p>
              <p className="text-xs mt-0.5 opacity-80">
                {usagePct >= 100
                  ? "Upgrade now to continue — your agent is paused until next cycle or you upgrade."
                  : "Upgrade before you run out to keep your agent running uninterrupted."}
              </p>
            </div>
            <button
              onClick={() => handleUpgrade(currentPlanId === "free" ? "starter" : currentPlanId === "starter" ? "pro" : "enterprise")}
              className="flex-shrink-0 px-3 py-1.5 rounded-lg bg-[var(--gold-500)] text-[#07111c] text-xs font-semibold hover:opacity-90 transition-opacity"
            >
              Upgrade
            </button>
          </div>
        )}

        {/* Downgrade confirmation dialog */}
        {downgradeConfirm && (
          <div className="p-4 rounded-xl border border-yellow-500/30 bg-yellow-500/10 flex flex-col gap-3">
            <div className="flex items-start gap-3">
              <AlertCircle className="h-5 w-5 text-yellow-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-yellow-300">Confirm downgrade to Free</p>
                <p className="text-xs text-yellow-200/70 mt-1">
                  You&apos;ll lose access to paid features and your limit resets to 50 actions/month. This takes effect at the end of your current billing period.
                </p>
              </div>
            </div>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setDowngradeConfirm(false)}
                className="px-3 py-1.5 rounded-lg border border-[var(--stroke)] text-xs text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleUpgrade("free")}
                disabled={subscribingTo === "free"}
                className="px-3 py-1.5 rounded-lg bg-red-500/20 border border-red-500/30 text-red-400 text-xs font-semibold hover:bg-red-500/30 transition-colors disabled:opacity-50"
              >
                {subscribingTo === "free" ? "Downgrading…" : "Yes, downgrade"}
              </button>
            </div>
          </div>
        )}

        {/* Toast */}
        {toast && (
          <div
            className={`p-3 rounded-xl text-sm flex items-center gap-2 border card-enter ${
              toast.type === "success"
                ? "bg-green-500/10 border-green-500/20 text-green-400"
                : "bg-red-500/10 border-red-500/20 text-red-400"
            }`}
          >
            {toast.type === "success" ? (
              <CheckCircle className="h-4 w-4 flex-shrink-0" />
            ) : (
              <AlertCircle className="h-4 w-4 flex-shrink-0" />
            )}
            {toast.message}
            <button
              onClick={() => setToast(null)}
              className="ml-auto text-xs underline opacity-70 hover:opacity-100"
            >
              dismiss
            </button>
          </div>
        )}

        {/* ── Current usage card ──────────────────────────────────────── */}
        <section className="glass-panel p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-heading font-semibold text-[var(--foreground)] flex items-center gap-2">
              <Zap className="h-4 w-4 text-[var(--gold-500)]" />
              This Month
            </h2>
            {usage && <PlanBadge plan={usage.plan} />}
          </div>

          {usageError ? (
            <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2">
              <AlertCircle className="h-4 w-4 flex-shrink-0" />
              {usageError}
              <button
                onClick={loadData}
                className="ml-auto text-xs underline"
              >
                retry
              </button>
            </div>
          ) : loadingUsage ? (
            <div className="flex items-center justify-center py-6">
              <span className="spinner text-[var(--color-muted)]" />
            </div>
          ) : usage ? (
            <>
              <UsageMeter usage={usage} />

              {/* Cost summary */}
              <div className="mt-4 pt-4 border-t border-[var(--stroke)] flex items-center justify-between">
                <div>
                  <p className="text-xs text-[var(--color-muted)]">
                    Billed actions
                  </p>
                  <p className="text-sm font-semibold text-[var(--foreground)]">
                    {usage.billed_actions.toLocaleString()} actions
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-xs text-[var(--color-muted)]">
                    Amount this month
                  </p>
                  <p className="text-xl font-bold text-[var(--gold-500)] tabular-nums">
                    {formatCents(usage.total_amount_cents)}
                  </p>
                </div>
              </div>
            </>
          ) : null}
        </section>

        {/* ── Payment & Subscription ──────────────────────────────────── */}
        {currentPlanId !== "free" && (
          <section className="glass-panel p-5">
            <h2 className="text-sm font-heading font-semibold text-[var(--foreground)] mb-4 flex items-center gap-2">
              <CreditCard className="h-4 w-4 text-[var(--gold-500)]" />
              Payment &amp; Subscription
            </h2>

            {/* Subscription status row */}
            {subStatus && (
              <div className="mb-4 grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
                <div className="rounded-lg bg-white/4 border border-[var(--stroke)] px-3 py-2.5">
                  <p className="text-xs text-[var(--color-muted)] mb-0.5">Plan</p>
                  <PlanBadge plan={subStatus.plan} />
                </div>
                <div className="rounded-lg bg-white/4 border border-[var(--stroke)] px-3 py-2.5">
                  <p className="text-xs text-[var(--color-muted)] mb-0.5">
                    {subStatus.cancel_at_period_end ? "Cancels on" : "Renews on"}
                  </p>
                  <p className="font-semibold text-[var(--foreground)]">
                    {subStatus.current_period_end
                      ? new Date(subStatus.current_period_end).toLocaleDateString(
                          "en-US",
                          { month: "short", day: "numeric", year: "numeric" }
                        )
                      : "—"}
                  </p>
                </div>
                <div className="rounded-lg bg-white/4 border border-[var(--stroke)] px-3 py-2.5">
                  <p className="text-xs text-[var(--color-muted)] mb-0.5">Status</p>
                  <p
                    className={`font-semibold capitalize ${
                      subStatus.is_active
                        ? subStatus.cancel_at_period_end
                          ? "text-yellow-400"
                          : "text-green-400"
                        : "text-red-400"
                    }`}
                  >
                    {subStatus.cancel_at_period_end
                      ? "Canceling"
                      : subStatus.stripe_status ?? (subStatus.is_active ? "Active" : "Inactive")}
                  </p>
                </div>
              </div>
            )}

            {/* Portal button */}
            <BillingPortalButton
              agentId={currentAgent.id}
              label="Manage Payment Method"
            />
            <p className="text-xs text-[var(--color-muted)] mt-2">
              Update your card, download invoices, or cancel your subscription
              via the Stripe Customer Portal.
            </p>
          </section>
        )}

        {/* ── Plan cards ──────────────────────────────────────────────── */}
        <section>
          <h2 className="text-sm font-heading font-semibold text-[var(--foreground)] mb-3 flex items-center gap-2">
            <ChevronUp className="h-4 w-4 text-[var(--gold-500)]" />
            Plans
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {PRICING_TIERS.map((tier) => (
              <PlanCard
                key={tier.id}
                tier={tier}
                isCurrent={currentPlanId === tier.id}
                onUpgrade={handleUpgrade}
                isLoading={subscribingTo === tier.id}
              />
            ))}
          </div>
          <p className="text-xs text-[var(--color-muted)] mt-2">
            Actions beyond your plan&apos;s included amount are billed at $1.00
            per action.
          </p>
        </section>

        {/* ── Usage history ───────────────────────────────────────────── */}
        <section className="glass-panel p-5">
          <h2 className="text-sm font-heading font-semibold text-[var(--foreground)] mb-4 flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-[var(--gold-500)]" />
            Usage History
          </h2>
          {loadingHistory ? (
            <div className="flex items-center justify-center py-6">
              <span className="spinner text-[var(--color-muted)]" />
            </div>
          ) : (
            <UsageHistoryTable history={history} />
          )}
        </section>
      </div>
    </div>
  );
}
