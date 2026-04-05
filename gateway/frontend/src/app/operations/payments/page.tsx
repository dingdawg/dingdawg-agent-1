"use client";

/**
 * Payments & Revenue (Cap 2).
 *
 * - Revenue forecast chart (CSS bars)
 * - Create payment link form
 * - Recent payment links list
 * - Refund action
 */

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  CreditCard,
  AlertCircle,
  RefreshCw,
  TrendingUp,
  CheckCircle,
  ChevronLeft,
  Plus,
  ExternalLink,
} from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { useAgentStore } from "@/store/agentStore";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import {
  getRevenueForecast,
  createPaymentLink,
  processRefund,
  type RevenueForecastResponse,
  type CreatePaymentLinkResponse,
} from "@/services/api/businessOpsService";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch { return iso; }
}

// ─── Revenue chart ────────────────────────────────────────────────────────────

function RevenueChart({ data }: { data: Array<{ date: string; amount_cents?: number; amount?: number }> }) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-28 text-sm text-[var(--color-muted)]">
        No revenue data yet
      </div>
    );
  }
  const max = Math.max(...data.map((d) => Number(d.amount_cents ?? d.amount ?? 0)), 1);
  const visible = data.slice(-14);
  return (
    <div className="flex items-end gap-1.5 h-28 w-full">
      {visible.map((entry, i) => {
        const val = Number(entry.amount_cents ?? entry.amount ?? 0);
        const heightPct = Math.max((val / max) * 100, 4);
        return (
          <div key={entry.date ?? i} className="flex-1 flex flex-col items-center justify-end gap-1 group">
            <div
              className="w-full rounded-t-sm bg-green-500/40 hover:bg-green-500/70 transition-colors cursor-default relative"
              style={{ height: `${heightPct}%` }}
            >
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-2 py-1 rounded-md bg-[var(--ink-800)] text-xs text-[var(--foreground)] whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-10 border border-[var(--stroke)] shadow-lg">
                {formatCents(val)}
                <br />
                <span className="text-[var(--color-muted)]">{formatDate(entry.date ?? "")}</span>
              </div>
            </div>
            <span className="text-[9px] text-[var(--color-muted)] truncate w-full text-center">
              {formatDate(entry.date ?? "")}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ─── Page shell ───────────────────────────────────────────────────────────────

export default function PaymentsPage() {
  return (
    <ProtectedRoute>
      <AppShell>
        <PaymentsContent />
      </AppShell>
    </ProtectedRoute>
  );
}

// ─── Content ──────────────────────────────────────────────────────────────────

function PaymentsContent() {
  const router = useRouter();
  const { currentAgent, agents, isLoading: agentsLoading, fetchAgents } = useAgentStore();

  const [forecast, setForecast] = useState<RevenueForecastResponse | null>(null);
  const [links, setLinks] = useState<CreatePaymentLinkResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);

  // Create link form
  const [form, setForm] = useState({ client_id: "", appointment_id: "", amount_cents: "" });
  const [creating, setCreating] = useState(false);

  // Refund form
  const [refundForm, setRefundForm] = useState({ payment_id: "", amount_cents: "", reason: "" });
  const [refunding, setRefunding] = useState(false);

  useEffect(() => { fetchAgents(); }, [fetchAgents]);

  useEffect(() => {
    if (!agentsLoading && agents.length === 0) router.replace("/claim");
  }, [agentsLoading, agents.length, router]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  const load = useCallback(async () => {
    if (!currentAgent) return;
    setLoading(true);
    setError(null);
    try {
      const fc = await getRevenueForecast(currentAgent.id, 14);
      setForecast(fc);
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail ?? "Failed to load revenue data";
      setError(detail);
    } finally {
      setLoading(false);
    }
  }, [currentAgent]);

  useEffect(() => { load(); }, [load]);

  const handleCreateLink = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentAgent) return;
    const amountCents = parseInt(form.amount_cents, 10);
    if (!form.client_id || !form.appointment_id || isNaN(amountCents) || amountCents <= 0) {
      setToast({ type: "error", message: "Please fill all fields with valid values." });
      return;
    }
    setCreating(true);
    try {
      const res = await createPaymentLink(currentAgent.id, {
        client_id: form.client_id,
        appointment_id: form.appointment_id,
        amount_cents: amountCents,
      });
      setLinks((prev) => [res, ...prev]);
      setForm({ client_id: "", appointment_id: "", amount_cents: "" });
      setToast({ type: "success", message: "Payment link created!" });
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail ?? "Failed to create payment link";
      setToast({ type: "error", message: detail });
    } finally {
      setCreating(false);
    }
  };

  const handleRefund = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentAgent) return;
    const amountCents = parseInt(refundForm.amount_cents, 10);
    if (!refundForm.payment_id || isNaN(amountCents) || amountCents <= 0) {
      setToast({ type: "error", message: "Payment ID and valid amount required." });
      return;
    }
    setRefunding(true);
    try {
      await processRefund(currentAgent.id, {
        payment_id: refundForm.payment_id,
        amount_cents: amountCents,
        reason: refundForm.reason || "customer_request",
      });
      setRefundForm({ payment_id: "", amount_cents: "", reason: "" });
      setToast({ type: "success", message: "Refund issued." });
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail ?? "Failed to issue refund";
      setToast({ type: "error", message: detail });
    } finally {
      setRefunding(false);
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

  const forecastData = (forecast as Record<string, unknown> | null);
  const dailyData = (forecastData?.daily as Array<{ date: string; amount_cents?: number; amount?: number }>) ?? [];

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
                <CreditCard className="h-5 w-5 text-[var(--gold-500)]" />
                Payments &amp; Revenue
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

        {/* Toast */}
        {toast && (
          <div className={cn("p-3 rounded-xl text-sm flex items-center gap-2 border", toast.type === "success" ? "bg-green-500/10 border-green-500/20 text-green-400" : "bg-red-500/10 border-red-500/20 text-red-400")}>
            {toast.type === "success" ? <CheckCircle className="h-4 w-4 flex-shrink-0" /> : <AlertCircle className="h-4 w-4 flex-shrink-0" />}
            {toast.message}
            <button onClick={() => setToast(null)} className="ml-auto text-xs underline opacity-70">dismiss</button>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            {error}
            <button onClick={load} className="ml-auto text-xs underline">retry</button>
          </div>
        )}

        {/* Revenue forecast chart */}
        <section className="glass-panel p-5">
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-2 flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-[var(--gold-500)]" />
            Revenue Forecast (14 days)
          </h2>
          {forecastData?.actual_cents != null && (
            <p className="text-2xl font-bold text-[var(--foreground)] mb-4">
              {formatCents(Number(forecastData.actual_cents))}
              <span className="text-sm font-normal text-[var(--color-muted)] ml-1">actual</span>
              {forecastData.forecast_cents != null && (
                <span className="ml-3 text-lg text-green-400">
                  → {formatCents(Number(forecastData.forecast_cents))}
                  <span className="text-sm font-normal text-[var(--color-muted)] ml-1">forecast</span>
                </span>
              )}
            </p>
          )}
          {loading && !forecast ? (
            <div className="flex items-end gap-1.5 h-28">
              {[40, 70, 55, 90, 30, 80, 60, 45, 75, 50, 65, 85, 40, 70].map((h, i) => (
                <div key={i} className="flex-1 animate-pulse rounded-t-sm bg-white/5" style={{ height: `${h}%` }} />
              ))}
            </div>
          ) : (
            <RevenueChart data={dailyData} />
          )}
        </section>

        {/* Create payment link form */}
        <section className="glass-panel p-5">
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4 flex items-center gap-2">
            <Plus className="h-4 w-4 text-[var(--gold-500)]" />
            Create Payment Link
          </h2>
          <form onSubmit={handleCreateLink} className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-[var(--color-muted)] mb-1 block">Client ID</label>
                <input
                  type="text"
                  value={form.client_id}
                  onChange={(e) => setForm((f) => ({ ...f, client_id: e.target.value }))}
                  placeholder="client_abc123"
                  className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
                />
              </div>
              <div>
                <label className="text-xs text-[var(--color-muted)] mb-1 block">Appointment ID</label>
                <input
                  type="text"
                  value={form.appointment_id}
                  onChange={(e) => setForm((f) => ({ ...f, appointment_id: e.target.value }))}
                  placeholder="appt_xyz789"
                  className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
                />
              </div>
            </div>
            <div>
              <label className="text-xs text-[var(--color-muted)] mb-1 block">Amount (cents)</label>
              <input
                type="number"
                min="1"
                value={form.amount_cents}
                onChange={(e) => setForm((f) => ({ ...f, amount_cents: e.target.value }))}
                placeholder="5000 = $50.00"
                className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
              />
            </div>
            <button
              type="submit"
              disabled={creating}
              className="w-full py-2.5 rounded-xl bg-[var(--gold-500)] text-[#07111c] font-semibold text-sm hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {creating ? <span className="flex items-center justify-center gap-2"><span className="spinner h-3.5 w-3.5" />Creating…</span> : "Create Payment Link"}
            </button>
          </form>
        </section>

        {/* Recent payment links */}
        {links.length > 0 && (
          <section className="glass-panel p-5">
            <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4">Recent Links</h2>
            <div className="divide-y divide-[var(--stroke)]">
              {links.map((link, i) => (
                <div key={String(link.link_id ?? i)} className="py-3 first:pt-0 last:pb-0 flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-[var(--foreground)] truncate">
                      Link #{String(link.link_id ?? i + 1).slice(0, 12)}
                    </p>
                    {link.url && (
                      <p className="text-xs text-[var(--color-muted)] truncate">{String(link.url)}</p>
                    )}
                  </div>
                  {link.url && (
                    <a
                      href={String(link.url)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex-shrink-0 p-1.5 rounded-lg hover:bg-white/5 text-[var(--color-muted)] hover:text-[var(--gold-500)] transition-colors"
                    >
                      <ExternalLink className="h-4 w-4" />
                    </a>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Refund form */}
        <section className="glass-panel p-5">
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4">Issue Refund</h2>
          <form onSubmit={handleRefund} className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-[var(--color-muted)] mb-1 block">Payment ID</label>
                <input
                  type="text"
                  value={refundForm.payment_id}
                  onChange={(e) => setRefundForm((f) => ({ ...f, payment_id: e.target.value }))}
                  placeholder="pay_abc123"
                  className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
                />
              </div>
              <div>
                <label className="text-xs text-[var(--color-muted)] mb-1 block">Amount (cents)</label>
                <input
                  type="number"
                  min="1"
                  value={refundForm.amount_cents}
                  onChange={(e) => setRefundForm((f) => ({ ...f, amount_cents: e.target.value }))}
                  placeholder="5000 = $50.00"
                  className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
                />
              </div>
            </div>
            <div>
              <label className="text-xs text-[var(--color-muted)] mb-1 block">Reason (optional)</label>
              <input
                type="text"
                value={refundForm.reason}
                onChange={(e) => setRefundForm((f) => ({ ...f, reason: e.target.value }))}
                placeholder="customer_request"
                className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
              />
            </div>
            <button
              type="submit"
              disabled={refunding}
              className="w-full py-2.5 rounded-xl bg-red-500/15 border border-red-500/30 text-red-400 font-semibold text-sm hover:bg-red-500/20 transition-colors disabled:opacity-50"
            >
              {refunding ? <span className="flex items-center justify-center gap-2"><span className="spinner h-3.5 w-3.5" />Processing…</span> : "Issue Refund"}
            </button>
          </form>
        </section>

      </div>
    </div>
  );
}
