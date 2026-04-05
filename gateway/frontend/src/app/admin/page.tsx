"use client";

/**
 * Command Center overview page — /admin
 *
 * Shows:
 *   - 4 KPI StatCards: Users, Agents, Sessions (24h), Errors (24h)
 *   - Stripe mode indicator (prominent)
 *   - Recent alerts feed
 *   - System health summary
 *   - Quick action buttons
 *
 * Polls every 30s using usePolling. Pauses when tab is hidden.
 * Shows loading skeleton on first load.
 */

import { useCallback, useEffect } from "react";
import { useAdminStore } from "@/store/adminStore";
import { usePolling } from "@/hooks/usePolling";
import StatCard from "@/components/admin/StatCard";
import AlertBadge from "@/components/admin/AlertBadge";
import StatusDot from "@/components/admin/StatusDot";
import { getAlerts, getHealthDetailed } from "@/services/api/adminService";
import { useState } from "react";
import type { Alert, HealthDetailed } from "@/services/api/adminService";
import { cn } from "@/lib/utils";

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function SkeletonCard() {
  return (
    <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4 flex flex-col gap-3 animate-pulse">
      <div className="h-3 w-20 bg-[#1a2a3d] rounded" />
      <div className="h-8 w-16 bg-[#1a2a3d] rounded" />
    </div>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const parts: string[] = [];
  if (d > 0) parts.push(`${d}d`);
  if (h > 0) parts.push(`${h}h`);
  parts.push(`${m}m`);
  return parts.join(" ");
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AdminOverviewPage() {
  const { platformStats, stripeMode, isLoading, fetchPlatformStats, fetchStripeStatus } =
    useAdminStore();

  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [health, setHealth] = useState<HealthDetailed | null>(null);
  const [alertsLoading, setAlertsLoading] = useState(true);

  const refresh = useCallback(async () => {
    await Promise.allSettled([
      fetchPlatformStats(),
      fetchStripeStatus(),
      getAlerts()
        .then((a) => setAlerts(a.slice(0, 5)))
        .finally(() => setAlertsLoading(false)),
      getHealthDetailed()
        .then(setHealth)
        .catch(() => setHealth(null)),
    ]);
  }, [fetchPlatformStats, fetchStripeStatus]);

  // Initial load
  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Poll every 30s, pause when hidden
  usePolling(refresh, 30_000);

  const stripeBadgeClass =
    stripeMode === "live"
      ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
      : stripeMode === "test"
      ? "bg-yellow-500/20 text-yellow-400 border-yellow-500/30"
      : "bg-gray-700/40 text-gray-400 border-gray-600/30";

  const stripeLabel =
    stripeMode === "live"
      ? "Stripe LIVE — real payments active"
      : stripeMode === "test"
      ? "Stripe TEST mode — no real charges"
      : "Stripe status unknown";

  return (
    <div className="p-4 space-y-6 max-w-3xl mx-auto">
      {/* ── Stripe mode banner ────────────────────────────────────────── */}
      <div
        className={cn(
          "flex items-center gap-3 px-4 py-3 rounded-xl border text-sm font-medium",
          stripeBadgeClass
        )}
      >
        <StatusDot
          color={stripeMode === "live" ? "green" : stripeMode === "test" ? "yellow" : "gray"}
          pulse={stripeMode === "live"}
        />
        {stripeLabel}
      </div>

      {/* ── KPI cards ─────────────────────────────────────────────────── */}
      <section aria-label="Platform KPIs">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
          Platform
        </h2>
        <div className="grid grid-cols-2 gap-3">
          {isLoading && !platformStats ? (
            <>
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
            </>
          ) : (
            <>
              <StatCard
                label="Total Users"
                value={platformStats?.total_users?.toLocaleString() ?? "--"}
                isLoading={isLoading && !platformStats}
              />
              <StatCard
                label="Total Agents"
                value={platformStats?.total_agents?.toLocaleString() ?? "--"}
                isLoading={isLoading && !platformStats}
              />
              <StatCard
                label="Sessions (24h)"
                value={platformStats?.sessions_24h?.toLocaleString() ?? "--"}
                isLoading={isLoading && !platformStats}
              />
              <StatCard
                label="Errors (24h)"
                value={platformStats?.errors_24h?.toLocaleString() ?? "--"}
                trend={
                  platformStats?.errors_24h
                    ? platformStats.errors_24h > 10
                      ? "down"
                      : "up"
                    : "neutral"
                }
                trendLabel={
                  platformStats?.errors_24h !== undefined
                    ? platformStats.errors_24h > 10
                      ? "High"
                      : "OK"
                    : undefined
                }
                isLoading={isLoading && !platformStats}
              />
            </>
          )}
        </div>
      </section>

      {/* ── System health ─────────────────────────────────────────────── */}
      <section aria-label="System health">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
          System Health
        </h2>
        <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4 space-y-3">
          {health ? (
            <>
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-400">Uptime</span>
                <span className="text-white text-xs">
                  {formatUptime(health.uptime_seconds)}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-400">DB Size</span>
                <span className="text-white text-xs">{health.db_size_mb} MB</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-400">Memory</span>
                <span className="text-white text-xs">{health.memory_mb} MB</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-400">Avg Response</span>
                <StatusDot
                  color={
                    health.avg_response_ms < 200
                      ? "green"
                      : health.avg_response_ms < 500
                      ? "yellow"
                      : "red"
                  }
                  label={`${health.avg_response_ms}ms`}
                />
              </div>
            </>
          ) : (
            <div className="space-y-2 animate-pulse">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="flex justify-between">
                  <div className="h-3 w-20 bg-[#1a2a3d] rounded" />
                  <div className="h-3 w-12 bg-[#1a2a3d] rounded" />
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* ── Recent alerts ─────────────────────────────────────────────── */}
      <section aria-label="Recent alerts">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
          Recent Alerts
        </h2>
        <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl divide-y divide-[#1a2a3d] overflow-hidden">
          {alertsLoading ? (
            <div className="p-4 space-y-3 animate-pulse">
              {[1, 2, 3].map((i) => (
                <div key={i} className="flex gap-3">
                  <div className="h-4 w-16 bg-[#1a2a3d] rounded-full" />
                  <div className="h-4 flex-1 bg-[#1a2a3d] rounded" />
                </div>
              ))}
            </div>
          ) : alerts.length === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-gray-500">
              No active alerts
            </div>
          ) : (
            alerts.map((alert) => (
              <div key={alert.id} className="flex items-start gap-3 px-4 py-3">
                <AlertBadge
                  severity={
                    (alert.severity?.toUpperCase() as "CRITICAL" | "WARNING" | "INFO" | "OK") ??
                    "INFO"
                  }
                />
                <span className="text-sm text-gray-300 leading-snug flex-1 min-w-0">
                  {alert.title ?? alert.description ?? "Alert"}
                </span>
              </div>
            ))
          )}
        </div>
      </section>

      {/* ── Quick actions ─────────────────────────────────────────────── */}
      <section aria-label="Quick actions">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
          Quick Actions
        </h2>
        <div className="grid grid-cols-2 gap-3">
          {[
            { label: "View Agents", href: "/admin/agents" },
            { label: "Revenue", href: "/admin/revenue" },
            { label: "Alerts", href: "/admin/alerts" },
            { label: "MiLA Tests", href: "/admin/mila" },
          ].map((action) => (
            <a
              key={action.href}
              href={action.href}
              className="flex items-center justify-center px-4 py-3 rounded-xl bg-[#0d1926] border border-[#1a2a3d] text-sm font-medium text-gray-300 hover:text-[var(--gold-400)] hover:border-[var(--gold-400)]/40 transition-colors min-h-[48px]"
            >
              {action.label}
            </a>
          ))}
        </div>
      </section>
    </div>
  );
}
