"use client";

/**
 * IntegrationCard — a single integration tile in the Integration Hub grid.
 *
 * Shows icon, name, category tag, connection status badge, and a configure
 * button. Supports a "coming soon" locked state for upcoming integrations.
 */

import { cn } from "@/lib/utils";

export type TierName = "starter" | "pro" | "enterprise";

export interface IntegrationCardProps {
  /** Display name of the integration */
  name: string;
  /** Short description shown below the name */
  description: string;
  /** Emoji or short string icon */
  icon: string;
  /** Category label e.g. "Communication", "Scheduling" */
  category: string;
  /** Whether the integration is currently connected */
  connected: boolean;
  /** Called when the user clicks "Configure" */
  onConfigure: () => void;
  /** Optional active item count (e.g. webhooks) — overrides connected boolean */
  activeCount?: number;
  /** If true, renders the card in a grayed-out "Coming Soon" state */
  comingSoon?: boolean;
  /** If true, shows a loading spinner instead of the status badge */
  loading?: boolean;
  /** Custom label for the action button (default: "Configure") */
  actionLabel?: string;
  /**
   * When set, the card is locked — faded, non-interactive, with an upgrade
   * badge showing which tier unlocks it. The onConfigure callback fires with
   * a "locked" signal so the parent can show an upgrade prompt.
   */
  lockedTier?: TierName;
}

// Category → accent color mapping
const CATEGORY_COLORS: Record<string, string> = {
  Communication: "text-blue-400 bg-blue-400/10 border-blue-400/20",
  Scheduling: "text-green-400 bg-green-400/10 border-green-400/20",
  Automation: "text-purple-400 bg-purple-400/10 border-purple-400/20",
  "Voice & Phone": "text-orange-400 bg-orange-400/10 border-orange-400/20",
  DingDawg: "text-[var(--gold-500)] bg-[var(--gold-500)]/10 border-[var(--gold-500)]/20",
};

function categoryClass(category: string): string {
  return (
    CATEGORY_COLORS[category] ??
    "text-[var(--color-muted)] bg-white/5 border-white/10"
  );
}

const TIER_LABEL: Record<TierName, string> = {
  starter: "STARTER",
  pro: "PRO",
  enterprise: "ENTERPRISE",
};

export function IntegrationCard({
  name,
  description,
  icon,
  category,
  connected,
  onConfigure,
  activeCount,
  comingSoon = false,
  loading = false,
  actionLabel,
  lockedTier,
}: IntegrationCardProps) {
  const isLocked = Boolean(lockedTier) && !comingSoon;
  const hasActiveCount = typeof activeCount === "number";

  const statusLabel = (() => {
    if (loading) return null;
    if (hasActiveCount) return `${activeCount} active`;
    return connected ? "Connected" : "Not Connected";
  })();

  const statusClass = (() => {
    if (hasActiveCount && activeCount! > 0)
      return "text-green-400 bg-green-400/10 border border-green-400/20";
    if (connected) return "text-green-400 bg-green-400/10 border border-green-400/20";
    return "text-[var(--color-muted)] bg-white/5 border border-white/10";
  })();

  return (
    <div
      className={cn(
        "glass-panel p-5 flex flex-col gap-4 transition-all duration-200 relative",
        comingSoon || isLocked
          ? "opacity-50"
          : "hover:border-[var(--stroke2)] hover:shadow-[0_0_0_1px_rgba(246,180,0,0.08)]",
        isLocked && "cursor-pointer"
      )}
      onClick={isLocked ? onConfigure : undefined}
    >
      {/* Tier upgrade badge — top-right corner for locked cards */}
      {isLocked && lockedTier && (
        <div className="absolute top-2 right-2 px-2 py-0.5 rounded-full bg-[var(--gold-500)]/20 text-[var(--gold-500)] text-[10px] font-semibold tracking-wide border border-[var(--gold-500)]/30 z-10">
          {TIER_LABEL[lockedTier]}
        </div>
      )}

      {/* Top row: icon + category */}
      <div className="flex items-start justify-between">
        {/* Icon */}
        <div className="h-11 w-11 rounded-xl bg-white/5 border border-[var(--stroke)] flex items-center justify-center text-2xl flex-shrink-0 select-none">
          {icon}
        </div>

        {/* Category tag — hide when locked tier badge occupies top-right */}
        {!isLocked && (
          <span
            className={cn(
              "text-[10px] font-semibold px-2 py-1 rounded-full border",
              categoryClass(category)
            )}
          >
            {category}
          </span>
        )}
      </div>

      {/* Name + description */}
      <div className="flex-1">
        <h3 className="text-sm font-semibold font-heading text-[var(--foreground)] mb-1">
          {name}
        </h3>
        <p className="text-xs text-[var(--color-muted)] leading-relaxed line-clamp-2">
          {description}
        </p>
      </div>

      {/* Status + action row */}
      <div className="flex items-center justify-between gap-3">
        {/* Status badge */}
        {loading && !isLocked ? (
          <span className="spinner text-[var(--gold-500)] h-3.5 w-3.5" />
        ) : (
          <span
            className={cn(
              "text-xs font-medium px-2.5 py-1 rounded-full",
              isLocked ? "text-[var(--color-muted)] bg-white/5 border border-white/10" : statusClass
            )}
          >
            {isLocked ? "Locked" : statusLabel}
          </span>
        )}

        {/* Action button */}
        {comingSoon ? (
          <span className="text-xs font-medium px-3 py-1.5 rounded-lg bg-white/5 text-[var(--color-muted)] border border-white/10 cursor-not-allowed">
            Coming Soon
          </span>
        ) : isLocked ? (
          <span className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-[var(--gold-500)]/10 text-[var(--gold-500)] border border-[var(--gold-500)]/20 pointer-events-none">
            Upgrade to {lockedTier ? TIER_LABEL[lockedTier] : ""}
          </span>
        ) : (
          <button
            onClick={onConfigure}
            disabled={loading}
            className={cn(
              "text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors",
              "bg-[var(--gold-500)]/10 text-[var(--gold-500)] border border-[var(--gold-500)]/20",
              "hover:bg-[var(--gold-500)]/20 hover:border-[var(--gold-500)]/40",
              "disabled:opacity-50 disabled:cursor-not-allowed"
            )}
          >
            {actionLabel || (connected ? "Settings" : "Connect")}
          </button>
        )}
      </div>
    </div>
  );
}
