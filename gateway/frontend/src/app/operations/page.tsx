"use client";

/**
 * Business Operations Hub (Cap 1 — Proactive Ops).
 *
 * - Morning Pulse summary (appointments, revenue, alerts)
 * - Active triggers / alerts list
 * - Quick actions: create payment link, view missed conversations
 * - Links to sub-pages
 */

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Activity,
  AlertCircle,
  Bell,
  CreditCard,
  MessageSquare,
  RefreshCw,
  Users,
  CalendarDays,
  TrendingUp,
  Megaphone,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAgentStore } from "@/store/agentStore";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import {
  getMorningPulse,
  checkTriggers,
  type OpsResult,
} from "@/services/api/businessOpsService";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

function severityColor(s: string) {
  if (s === "high") return "text-red-400 bg-red-500/10 border-red-500/20";
  if (s === "medium") return "text-yellow-400 bg-yellow-500/10 border-yellow-500/20";
  return "text-blue-400 bg-blue-500/10 border-blue-500/20";
}

// ─── Sub-nav links ────────────────────────────────────────────────────────────

const SUB_PAGES = [
  { href: "/operations/payments", label: "Payments", icon: CreditCard, color: "text-green-400" },
  { href: "/operations/conversations", label: "Conversations", icon: MessageSquare, color: "text-blue-400" },
  { href: "/operations/clients", label: "Clients", icon: Users, color: "text-purple-400" },
  { href: "/operations/staff", label: "Staff", icon: CalendarDays, color: "text-orange-400" },
  { href: "/operations/marketing", label: "Marketing", icon: Megaphone, color: "text-pink-400" },
];

// ─── Page shell ───────────────────────────────────────────────────────────────

export default function OperationsPage() {
  return (
    <ProtectedRoute>
      <AppShell>
        <OperationsContent />
      </AppShell>
    </ProtectedRoute>
  );
}

// ─── Content ──────────────────────────────────────────────────────────────────

function OperationsContent() {
  const router = useRouter();
  const { currentAgent, agents, isLoading: agentsLoading, fetchAgents } = useAgentStore();

  const [pulse, setPulse] = useState<OpsResult | null>(null);
  const [triggers, setTriggers] = useState<OpsResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { fetchAgents(); }, [fetchAgents]);

  useEffect(() => {
    if (!agentsLoading && agents.length === 0) router.replace("/claim");
  }, [agentsLoading, agents.length, router]);

  const load = useCallback(async () => {
    if (!currentAgent) return;
    setLoading(true);
    setError(null);
    try {
      const [p, t] = await Promise.allSettled([
        getMorningPulse(currentAgent.id),
        checkTriggers(currentAgent.id),
      ]);
      if (p.status === "fulfilled") setPulse(p.value);
      if (t.status === "fulfilled") setTriggers(t.value);
      if (p.status === "rejected") {
        const detail =
          (p.reason as { response?: { data?: { detail?: string } } })
            ?.response?.data?.detail ?? "Failed to load pulse";
        setError(detail);
      }
    } finally {
      setLoading(false);
    }
  }, [currentAgent]);

  useEffect(() => { load(); }, [load]);

  if (agentsLoading && agents.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="spinner text-[var(--gold-500)]" />
      </div>
    );
  }
  if (!currentAgent) return null;

  const pulseData = pulse as Record<string, unknown> | null;
  const alerts = (pulseData?.alerts as unknown[]) ?? [];
  const triggerAlerts = (triggers as Record<string, unknown> | null)?.alerts as unknown[] ?? [];

  return (
    <div className="h-full overflow-y-auto scrollbar-thin">
      <div className="max-w-3xl mx-auto px-4 py-6 pb-6 space-y-5">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-[var(--foreground)] flex items-center gap-2">
              <Activity className="h-5 w-5 text-[var(--gold-500)]" />
              Business Operations
            </h1>
            <p className="text-xs text-[var(--color-muted)] mt-0.5">
              @{currentAgent.handle} — morning pulse &amp; command center
            </p>
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-[var(--color-muted)] hover:text-[var(--foreground)] hover:bg-white/5 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            Refresh
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            {error}
            <button onClick={load} className="ml-auto text-xs underline">retry</button>
          </div>
        )}

        {/* Morning Pulse KPIs */}
        <section className="glass-panel p-5">
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4 flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-[var(--gold-500)]" />
            Morning Pulse
          </h2>
          {loading && !pulse ? (
            <div className="flex items-center justify-center py-6">
              <span className="spinner text-[var(--color-muted)]" />
            </div>
          ) : pulse ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[
                {
                  label: "Appointments",
                  value: String(pulseData?.appointments_today ?? pulseData?.appointments ?? 0),
                },
                {
                  label: "Revenue Today",
                  value: pulseData?.revenue_today_cents != null
                    ? formatCents(Number(pulseData.revenue_today_cents))
                    : (pulseData?.revenue != null ? `$${pulseData.revenue}` : "—"),
                },
                {
                  label: "Missed Msgs",
                  value: String(pulseData?.missed_conversations ?? pulseData?.missed_messages ?? 0),
                },
                {
                  label: "Pending Payments",
                  value: String(pulseData?.pending_payments ?? 0),
                },
              ].map((kpi) => (
                <div key={kpi.label} className="bg-white/3 rounded-xl p-3 border border-[var(--stroke)]">
                  <p className="text-xs text-[var(--color-muted)]">{kpi.label}</p>
                  <p className="text-xl font-bold text-[var(--foreground)] mt-1">{kpi.value}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-[var(--color-muted)] text-center py-4">
              No pulse data yet. Refresh to load.
            </p>
          )}
        </section>

        {/* Active alerts */}
        {(alerts.length > 0 || triggerAlerts.length > 0) && (
          <section className="glass-panel p-5">
            <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4 flex items-center gap-2">
              <Bell className="h-4 w-4 text-[var(--gold-500)]" />
              Active Alerts
            </h2>
            <div className="flex flex-col gap-2">
              {[...alerts, ...triggerAlerts].slice(0, 8).map((a, i) => {
                const alert = a as Record<string, unknown>;
                const sev = String(alert.severity ?? "low");
                return (
                  <div
                    key={String(alert.id ?? i)}
                    className={cn(
                      "flex items-start gap-2 px-3 py-2.5 rounded-lg border text-sm",
                      severityColor(sev)
                    )}
                  >
                    <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
                    <span className="flex-1">{String(alert.message ?? alert.description ?? "Alert")}</span>
                    <span className="text-xs opacity-70 capitalize">{sev}</span>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* Quick actions */}
        <section className="glass-panel p-5">
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4">Quick Actions</h2>
          <div className="flex flex-wrap gap-3">
            <Link
              href="/operations/payments"
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[var(--gold-500)] text-[#07111c] text-sm font-semibold hover:opacity-90 transition-opacity"
            >
              <CreditCard className="h-4 w-4" />
              Create Payment Link
            </Link>
            <Link
              href="/operations/conversations"
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-white/8 border border-[var(--stroke)] text-[var(--foreground)] text-sm font-medium hover:bg-white/12 transition-colors"
            >
              <MessageSquare className="h-4 w-4" />
              View Missed Conversations
            </Link>
          </div>
        </section>

        {/* Sub-page navigation */}
        <section>
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-3">Modules</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {SUB_PAGES.map(({ href, label, icon: Icon, color }) => (
              <Link
                key={href}
                href={href}
                className="glass-panel p-4 flex items-center gap-3 hover:bg-white/5 transition-colors group"
              >
                <div className="h-9 w-9 rounded-xl bg-white/5 flex items-center justify-center flex-shrink-0">
                  <Icon className={cn("h-4 w-4", color)} />
                </div>
                <span className="flex-1 text-sm font-medium text-[var(--foreground)]">{label}</span>
                <ChevronRight className="h-4 w-4 text-[var(--color-muted)] group-hover:translate-x-0.5 transition-transform" />
              </Link>
            ))}
          </div>
        </section>

      </div>
    </div>
  );
}
