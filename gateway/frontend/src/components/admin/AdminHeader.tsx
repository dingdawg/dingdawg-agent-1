"use client";

/**
 * AdminHeader — compact Command Center top bar.
 *
 * Shows:
 *   - "Command Center" title
 *   - STOA security badge (green dot)
 *   - Stripe mode badge: TEST (yellow) or LIVE (green) or unknown (gray)
 *   - User avatar initial circle
 *
 * Stripe mode is read from adminStore (already fetched by layout).
 */

import { useAuthStore } from "@/store/authStore";
import { useAdminStore } from "@/store/adminStore";
import StatusDot from "@/components/admin/StatusDot";
import { cn } from "@/lib/utils";

interface AdminHeaderProps {
  onRefresh?: () => void;
}

export default function AdminHeader({ onRefresh }: AdminHeaderProps) {
  const { user } = useAuthStore();
  const { stripeMode } = useAdminStore();

  const initial = user?.email?.charAt(0).toUpperCase() ?? "A";

  const stripeBadgeClass =
    stripeMode === "live"
      ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
      : stripeMode === "test"
      ? "bg-yellow-500/20 text-yellow-400 border-yellow-500/30"
      : "bg-gray-500/20 text-gray-400 border-gray-500/30";

  const stripeBadgeLabel =
    stripeMode === "live" ? "LIVE" : stripeMode === "test" ? "TEST" : "---";

  return (
    <header className="flex items-center justify-between min-h-14 px-4 border-b border-[#1a2a3d] bg-[var(--ink-950)] flex-shrink-0 z-20" style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}>
      {/* Left: title */}
      <div className="flex items-center gap-3">
        <button
          onClick={onRefresh}
          className="font-heading font-bold text-base text-white tracking-tight hover:text-[var(--gold-400)] transition-colors active:scale-95"
          aria-label="Command Center — tap to refresh"
        >
          Command Center
        </button>

        {/* STOA badge */}
        <span className="hidden sm:inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-xs font-semibold text-emerald-400">
          <StatusDot color="green" pulse />
          STOA
        </span>
      </div>

      {/* Right: Stripe mode + avatar */}
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold border",
            stripeBadgeClass
          )}
          title={`Stripe mode: ${stripeMode}`}
        >
          {stripeBadgeLabel}
        </span>

        <div
          className="h-8 w-8 rounded-full bg-[var(--gold-400)]/20 border border-[var(--gold-400)]/30 flex items-center justify-center flex-shrink-0"
          title={user?.email ?? "Admin"}
        >
          <span className="text-sm font-bold text-[var(--gold-400)]">
            {initial}
          </span>
        </div>
      </div>
    </header>
  );
}
