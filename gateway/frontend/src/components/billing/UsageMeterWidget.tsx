"use client";

/**
 * UsageMeterWidget — shows usage progress bar + plan info.
 *
 * Displays in sidebar / dashboard to surface:
 *   1. "X of Y free actions used" progress bar
 *   2. Current plan name (Free / Starter / Pro / Enterprise)
 *   3. "Upgrade" button linking to /pricing when on free plan
 *
 * GET /api/v1/payments/usage → { actions_used, actions_limit, plan, plan_label }
 *
 * States:
 *   - Loading: skeleton shimmer (glass-panel placeholder)
 *   - Error:   fail-open — returns null (won't crash the page)
 *   - Success: shows bar, plan label, count, upgrade CTA when applicable
 *   - Enterprise: no progress bar, "Unlimited" label
 *
 * Progress bar colors:
 *   - 0-79%:   gold (var(--gold-500))
 *   - 80-94%:  amber (bg-amber-500)
 *   - 95-100%: red   (bg-red-500)
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { get } from "@/services/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface UsageResponse {
  actions_used: number;
  actions_limit: number;
  plan: "free" | "starter" | "pro" | "enterprise";
  plan_label: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Returns the Tailwind background class for the progress bar fill
 * based on usage percentage.
 */
function getProgressColor(pct: number): string {
  if (pct >= 95) return "bg-red-500";
  if (pct >= 80) return "bg-amber-500";
  return "bg-[var(--gold-500)]";
}

/**
 * Returns the Tailwind text class for the usage count label
 * based on usage percentage.
 */
function getTextColor(pct: number): string {
  if (pct >= 95) return "text-red-400";
  if (pct >= 80) return "text-amber-400";
  return "text-[var(--color-muted)]";
}

// ---------------------------------------------------------------------------
// Skeleton (loading state)
// ---------------------------------------------------------------------------

function UsageMeterSkeleton() {
  return (
    <div
      className="glass-panel p-3 flex flex-col gap-2 animate-pulse"
      aria-hidden="true"
    >
      {/* Plan label + count row */}
      <div className="flex items-center justify-between">
        <div className="h-3 w-14 bg-white/[0.06] rounded" />
        <div className="h-3 w-12 bg-white/[0.06] rounded" />
      </div>
      {/* Progress bar */}
      <div className="h-1.5 w-full bg-white/[0.04] rounded-full overflow-hidden">
        <div className="h-full w-1/3 bg-white/[0.06] rounded-full" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// UsageMeterWidget
// ---------------------------------------------------------------------------

export function UsageMeterWidget() {
  const [data, setData] = useState<UsageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function fetchUsage() {
      try {
        const res = await get<UsageResponse>("/api/v1/payments/usage");
        if (!cancelled) {
          setData(res);
          setLoading(false);
        }
      } catch {
        if (!cancelled) {
          setError(true);
          setLoading(false);
        }
      }
    }

    fetchUsage();

    // Refresh every 5 minutes to keep counts current after tool calls
    const interval = setInterval(() => {
      if (!cancelled) fetchUsage();
    }, 300_000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  // Loading
  if (loading) return <UsageMeterSkeleton />;

  // Error or missing data — fail-open (don't crash the page)
  if (error || !data) return null;

  const { actions_used, actions_limit, plan, plan_label } = data;

  // Enterprise / unlimited — no progress bar needed.
  // Guard against actions_limit === 0 to prevent division by zero.
  const isUnlimited =
    plan === "enterprise" || actions_limit === -1 || actions_limit === 0;

  // Clamped percentage (0-100)
  const pct = isUnlimited
    ? 0
    : Math.min(
        100,
        Math.max(0, Math.round((actions_used / actions_limit) * 100))
      );

  // Show upgrade button when free plan reaches 80%+ usage
  const isFree = plan === "free";
  const showUpgrade = pct >= 80 && isFree;

  return (
    <div className="glass-panel p-3 flex flex-col gap-2">
      {/* Row: plan label + count */}
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold text-[var(--foreground)] uppercase tracking-wider">
          {plan_label}
        </span>

        {isUnlimited ? (
          <span className="text-[11px] font-mono text-[var(--color-muted)]">
            Unlimited
          </span>
        ) : (
          <span
            className={[
              "text-[11px] font-mono tabular-nums",
              getTextColor(pct),
            ].join(" ")}
          >
            {actions_used.toLocaleString()}
            <span className="text-[var(--color-muted)]">
              {" / "}
              {actions_limit.toLocaleString()}
            </span>
          </span>
        )}
      </div>

      {/* Progress bar */}
      {!isUnlimited && (
        <div
          className="h-1.5 w-full bg-white/[0.06] rounded-full overflow-hidden"
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${actions_used} of ${actions_limit} actions used`}
        >
          <div
            className={[
              "h-full rounded-full transition-all duration-500 ease-out",
              getProgressColor(pct),
            ].join(" ")}
            style={{ width: `${Math.max(pct, 2)}%` }}
          />
        </div>
      )}

      {/* Upgrade CTA — free plan at 80%+ */}
      {showUpgrade && (
        <Link
          href="/pricing"
          className={[
            "w-full py-1.5 px-3 rounded-lg text-center",
            "text-[11px] font-semibold",
            "bg-[var(--gold-500)] text-[#07111c]",
            "hover:opacity-90 active:scale-[0.98]",
            "transition-all",
          ].join(" ")}
        >
          Upgrade
        </Link>
      )}
    </div>
  );
}

export default UsageMeterWidget;
