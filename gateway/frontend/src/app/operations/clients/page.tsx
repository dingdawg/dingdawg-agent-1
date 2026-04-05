"use client";

/**
 * Client Intelligence Dashboard (Cap 4).
 *
 * - Segment cards: VIP / Regular / At-Risk / Lapsed / New
 * - Client search
 * - CLV and churn scores per client
 * - Rebook suggestions
 */

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Users,
  Search,
  AlertCircle,
  RefreshCw,
  Star,
  TrendingDown,
  UserPlus,
  Clock,
  ChevronLeft,
} from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { useAgentStore } from "@/store/agentStore";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import {
  getClientSegments,
  getClientDashboard,
  triggerRebook,
  type ClientSegmentsResponse,
  type ClientDashboardResponse,
  type RebookResponse,
} from "@/services/api/businessOpsService";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

function segmentStyle(seg: string) {
  switch (seg) {
    case "VIP": return "text-[var(--gold-500)] bg-[var(--gold-500)]/10 border-[var(--gold-500)]/30";
    case "At-Risk": return "text-red-400 bg-red-500/10 border-red-500/20";
    case "Lapsed": return "text-orange-400 bg-orange-500/10 border-orange-500/20";
    case "New": return "text-green-400 bg-green-500/10 border-green-500/20";
    default: return "text-blue-400 bg-blue-500/10 border-blue-500/20";
  }
}

function churnColor(score: number) {
  if (score >= 0.7) return "text-red-400";
  if (score >= 0.4) return "text-yellow-400";
  return "text-green-400";
}

function segmentIcon(seg: string) {
  switch (seg) {
    case "VIP": return Star;
    case "At-Risk": return TrendingDown;
    case "New": return UserPlus;
    case "Lapsed": return Clock;
    default: return Users;
  }
}

// ─── Page shell ───────────────────────────────────────────────────────────────

export default function ClientsPage() {
  return (
    <ProtectedRoute>
      <AppShell>
        <ClientsContent />
      </AppShell>
    </ProtectedRoute>
  );
}

// ─── Content ──────────────────────────────────────────────────────────────────

function ClientsContent() {
  const router = useRouter();
  const { currentAgent, agents, isLoading: agentsLoading, fetchAgents } = useAgentStore();

  const [segments, setSegments] = useState<ClientSegmentsResponse | null>(null);
  const [dashboard, setDashboard] = useState<ClientDashboardResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [rebookingId, setRebookingId] = useState<string | null>(null);
  const [rebookResult, setRebookResult] = useState<Record<string, RebookResponse>>({});

  useEffect(() => { fetchAgents(); }, [fetchAgents]);

  useEffect(() => {
    if (!agentsLoading && agents.length === 0) router.replace("/claim");
  }, [agentsLoading, agents.length, router]);

  const load = useCallback(async () => {
    if (!currentAgent) return;
    setLoading(true);
    setError(null);
    try {
      const [seg, dash] = await Promise.allSettled([
        getClientSegments(currentAgent.id),
        getClientDashboard(currentAgent.id),
      ]);
      if (seg.status === "fulfilled") setSegments(seg.value);
      if (dash.status === "fulfilled") setDashboard(dash.value);
      if (seg.status === "rejected") {
        const detail =
          (seg.reason as { response?: { data?: { detail?: string } } })
            ?.response?.data?.detail ?? "Failed to load clients";
        setError(detail);
      }
    } finally {
      setLoading(false);
    }
  }, [currentAgent]);

  useEffect(() => { load(); }, [load]);

  const handleRebook = async (clientId: string) => {
    if (!currentAgent) return;
    setRebookingId(clientId);
    try {
      const res = await triggerRebook(currentAgent.id, clientId);
      setRebookResult((prev) => ({ ...prev, [clientId]: res }));
    } catch {
      // non-fatal
    } finally {
      setRebookingId(null);
    }
  };

  if (agentsLoading && agents.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="spinner text-[var(--gold-500)]" />
      </div>
    );
  }
  if (!currentAgent) return null;

  const rawSegments = (segments?.segments as unknown[] ?? []) as Array<Record<string, unknown>>;
  const rawClients = (
    (dashboard as Record<string, unknown> | null)?.clients as unknown[] ??
    (segments as Record<string, unknown> | null)?.clients as unknown[] ??
    []
  ) as Array<Record<string, unknown>>;

  const filtered = rawClients.filter((c) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      String(c.name ?? "").toLowerCase().includes(q) ||
      String(c.email ?? "").toLowerCase().includes(q)
    );
  });

  return (
    <div className="h-full overflow-y-auto scrollbar-thin">
      <div className="max-w-3xl mx-auto px-4 py-6 pb-6 space-y-5">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Link href="/operations" className="text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors">
              <ChevronLeft className="h-5 w-5" />
            </Link>
            <div>
              <h1 className="text-xl font-bold text-[var(--foreground)] flex items-center gap-2">
                <Users className="h-5 w-5 text-[var(--gold-500)]" />
                Client Intelligence
              </h1>
              <p className="text-xs text-[var(--color-muted)] mt-0.5">@{currentAgent.handle}</p>
            </div>
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

        {/* Segment cards */}
        {loading && !segments ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="glass-panel p-4 animate-pulse">
                <div className="h-4 w-20 bg-white/5 rounded mb-2" />
                <div className="h-8 w-10 bg-white/5 rounded" />
              </div>
            ))}
          </div>
        ) : rawSegments.length > 0 ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {rawSegments.map((seg) => {
              const label = String(seg.segment ?? seg.name ?? "Unknown");
              const count = Number(seg.count ?? seg.client_count ?? 0);
              const Icon = segmentIcon(label);
              return (
                <div key={label} className={cn("glass-panel p-4 border", segmentStyle(label))}>
                  <div className="flex items-center gap-2 mb-1">
                    <Icon className="h-4 w-4" />
                    <span className="text-xs font-semibold">{label}</span>
                  </div>
                  <p className="text-2xl font-bold text-[var(--foreground)]">{count}</p>
                </div>
              );
            })}
          </div>
        ) : null}

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--color-muted)]" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search clients by name or email…"
            className="w-full pl-9 pr-4 py-2.5 rounded-xl bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
          />
        </div>

        {/* Client list */}
        <section className="glass-panel p-5">
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4">Clients</h2>
          {loading && rawClients.length === 0 ? (
            <div className="flex items-center justify-center py-6">
              <span className="spinner text-[var(--color-muted)]" />
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-8 text-sm text-[var(--color-muted)]">
              {search ? "No clients match your search." : "No client data yet."}
            </div>
          ) : (
            <div className="divide-y divide-[var(--stroke)]">
              {filtered.slice(0, 50).map((client, i) => {
                const cid = String(client.id ?? i);
                const seg = String(client.segment ?? "Regular");
                const churn = Number(client.churn_score ?? 0);
                const clv = Number(client.clv_cents ?? client.lifetime_value_cents ?? 0);
                const rebook = rebookResult[cid];
                return (
                  <div key={cid} className="py-3 first:pt-0 last:pb-0">
                    <div className="flex items-center gap-3">
                      <div className="h-8 w-8 rounded-lg bg-[var(--gold-500)]/10 flex items-center justify-center flex-shrink-0">
                        <Users className="h-3.5 w-3.5 text-[var(--gold-500)]" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-[var(--foreground)] truncate">
                          {String(client.name ?? "Unknown Client")}
                        </p>
                        <p className="text-xs text-[var(--color-muted)] truncate">
                          {String(client.email ?? client.phone ?? "")}
                        </p>
                      </div>
                      <div className="flex flex-col items-end gap-1 flex-shrink-0">
                        <span className={cn("text-[10px] font-semibold px-2 py-0.5 rounded-full border", segmentStyle(seg))}>
                          {seg}
                        </span>
                        {clv > 0 && (
                          <span className="text-xs text-[var(--color-muted)]">
                            CLV {formatCents(clv)}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Churn bar */}
                    {churn > 0 && (
                      <div className="mt-2 flex items-center gap-2">
                        <span className="text-xs text-[var(--color-muted)] w-16 flex-shrink-0">Churn risk</span>
                        <div className="flex-1 h-1.5 rounded-full bg-white/10 overflow-hidden">
                          <div
                            className={cn("h-full rounded-full", churn >= 0.7 ? "bg-red-400" : churn >= 0.4 ? "bg-yellow-400" : "bg-green-400")}
                            style={{ width: `${Math.round(churn * 100)}%` }}
                          />
                        </div>
                        <span className={cn("text-xs font-semibold w-8 text-right", churnColor(churn))}>
                          {Math.round(churn * 100)}%
                        </span>
                      </div>
                    )}

                    {/* Rebook suggestion */}
                    {rebook?.suggestion && (
                      <p className="mt-1.5 text-xs text-[var(--gold-500)] bg-[var(--gold-500)]/5 rounded-lg px-3 py-1.5 border border-[var(--gold-500)]/20">
                        {String(rebook.suggestion)}
                      </p>
                    )}
                    <div className="mt-2">
                      <button
                        onClick={() => handleRebook(cid)}
                        disabled={rebookingId === cid}
                        className="text-xs text-[var(--color-muted)] hover:text-[var(--gold-500)] transition-colors disabled:opacity-50"
                      >
                        {rebookingId === cid ? "Loading…" : "Get rebook suggestion"}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

      </div>
    </div>
  );
}
