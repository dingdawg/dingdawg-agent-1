"use client";

/**
 * Revenue admin page — Command Center revenue dashboard.
 *
 * Sections:
 *   1. 4 KPI stat cards (MRR, subscriptions, ARPU, gross margin)
 *   2. Stripe mode badge (TEST / LIVE) + webhook status
 *   3. MRR area chart (30-day)
 *   4. Recent transactions DataTable
 *   5. Cost breakdown panel
 *
 * Data: adminService.getStripeStatus(), adminService.getFunnel()
 * Polling: 120 seconds via usePolling
 * Auth gate: AdminRoute
 */

import { useCallback, useEffect, useState } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import {
  DollarSign,
  Users,
  TrendingUp,
  BarChart3,
  AlertCircle,
  RefreshCw,
  Zap,
  Webhook,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAdminRevenueStore } from "@/store/adminRevenueStore";
import { usePolling } from "@/hooks/usePolling";
import StatCard from "@/components/admin/StatCard";
import StatusDot from "@/components/admin/StatusDot";
import AlertBadge from "@/components/admin/AlertBadge";
import DataTable, { type ColumnDef } from "@/components/admin/DataTable";
import type { StripeStatus } from "@/store/adminRevenueStore";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDollars(cents: number): string {
  return "$" + (cents / 100).toFixed(2);
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return "Never";
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60_000);
    if (mins < 1) return "Just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  } catch {
    return iso;
  }
}

// ─── Mock MRR data — replaces with real data when backend provides it ─────────

function buildMockMrrData(): Array<{ date: string; value: number }> {
  const points: Array<{ date: string; value: number }> = [];
  const now = new Date();
  for (let i = 29; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    points.push({
      date: d.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
      value: 0,
    });
  }
  return points;
}

// ─── Mock transaction row shape ───────────────────────────────────────────────

interface TransactionRow {
  date: string;
  customer: string;
  amount: string;
  status: string;
  type: string;
}

const TRANSACTION_COLUMNS: ColumnDef<TransactionRow>[] = [
  { header: "Date", accessor: "date", sortable: true },
  { header: "Customer", accessor: "customer", sortable: true },
  {
    header: "Amount",
    accessor: "amount",
    sortable: true,
    render: (v) => (
      <span className="text-[var(--gold-400)] font-medium">{String(v)}</span>
    ),
  },
  {
    header: "Status",
    accessor: "status",
    render: (v) => {
      const val = String(v);
      const color =
        val === "succeeded"
          ? "text-emerald-400"
          : val === "pending"
          ? "text-yellow-400"
          : "text-red-400";
      return <span className={cn("text-xs font-semibold capitalize", color)}>{val}</span>;
    },
  },
  { header: "Type", accessor: "type", sortable: true },
];

// ─── Stripe Mode Badge ────────────────────────────────────────────────────────

function StripeBadge({ status }: { status: StripeStatus | null }) {
  if (!status) {
    return (
      <div className="h-6 w-32 bg-[#1a2a3d] rounded animate-pulse" />
    );
  }

  if (status.mode === "not_configured") {
    return (
      <AlertBadge severity="CRITICAL" label="NOT CONFIGURED" />
    );
  }

  if (status.mode === "test") {
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-yellow-500/20 text-yellow-400 border border-yellow-500/30">
        <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />
        TEST MODE
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
      LIVE
    </span>
  );
}

// ─── Page export ──────────────────────────────────────────────────────────────

export default function RevenuePage() {
  return <RevenueContent />;
}

// ─── Revenue Content ──────────────────────────────────────────────────────────

function RevenueContent() {
  const { stripeStatus, funnel, isLoading, error, fetchStripeStatus, fetchFunnel } =
    useAdminRevenueStore();

  const [refreshing, setRefreshing] = useState(false);
  // Defer Recharts until after first client paint — prevents window/ResizeObserver
  // crash on Safari where the container has no dimensions on the SSR/hydration pass.
  const [chartMounted, setChartMounted] = useState(false);
  useEffect(() => { setChartMounted(true); }, []);

  const poll = useCallback(async () => {
    await Promise.allSettled([fetchStripeStatus(), fetchFunnel()]);
  }, [fetchStripeStatus, fetchFunnel]);

  usePolling(poll, 120_000);

  async function handleRefresh() {
    setRefreshing(true);
    await poll();
    setRefreshing(false);
  }

  const mrrData = buildMockMrrData();
  const transactions: TransactionRow[] = [];

  // Derived KPIs from available data
  const customerCount = stripeStatus?.customer_count ?? 0;
  const activeSubscribers = funnel?.active_subscribers ?? 0;

  return (
    <div className="min-h-screen bg-[var(--ink-950)] overflow-y-auto scrollbar-thin">
      <div className="max-w-5xl mx-auto px-4 pt-6 pb-24 lg:pb-8 space-y-6">

        {/* ── Header ─────────────────────────────────────────────── */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-heading font-bold text-white">Revenue</h1>
            <p className="text-[15px] text-gray-400 mt-0.5">Financial overview and Stripe status</p>
          </div>
          <button
            onClick={handleRefresh}
            disabled={refreshing || isLoading}
            className="flex items-center gap-1.5 px-3 py-2 min-h-[44px] rounded-xl bg-[#0d1926] border border-[#1a2a3d] text-xs text-gray-400 hover:text-white hover:border-[var(--gold-400)] transition-colors disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", (refreshing || isLoading) && "animate-spin")} />
            Refresh
          </button>
        </div>

        {/* ── Error banner ────────────────────────────────────────── */}
        {error && (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            <span className="flex-1">{error}</span>
            <button onClick={handleRefresh} className="text-xs underline">
              retry
            </button>
          </div>
        )}

        {/* ── KPI Cards ───────────────────────────────────────────── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatCard
            label="MRR"
            value={formatDollars(0)}
            subLabel="Monthly recurring"
            trend="neutral"
            trendLabel="Stripe LIVE needed"
            isLoading={isLoading && !stripeStatus}
          />
          <StatCard
            label="Active Subscriptions"
            value={activeSubscribers}
            subLabel="Current period"
            trend={activeSubscribers > 0 ? "up" : "neutral"}
            trendLabel={activeSubscribers > 0 ? "Growing" : "No subs yet"}
            isLoading={isLoading && !funnel}
          />
          <StatCard
            label="ARPU"
            value="$0.00"
            subLabel="Avg revenue/user"
            trend="neutral"
            trendLabel="No billing data"
            isLoading={isLoading && !stripeStatus}
          />
          <StatCard
            label="Gross Margin"
            value="0%"
            subLabel="After API costs"
            trend="neutral"
            trendLabel="No revenue yet"
            isLoading={isLoading && !stripeStatus}
          />
        </div>

        {/* ── Stripe Status Panel ─────────────────────────────────── */}
        <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <Zap className="h-4 w-4 text-[var(--gold-400)]" />
              Stripe Status
            </h2>
            <StripeBadge status={stripeStatus} />
          </div>

          {stripeStatus?.mode === "test" && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/20">
              <AlertCircle className="h-4 w-4 text-yellow-400 flex-shrink-0 mt-0.5" />
              <p className="text-xs text-yellow-300">
                TEST MODE — No real charges. Flip Stripe to LIVE mode in your backend
                environment variables before accepting real payments.
              </p>
            </div>
          )}

          {stripeStatus?.mode === "live" && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
              <TrendingUp className="h-4 w-4 text-emerald-400 flex-shrink-0 mt-0.5" />
              <p className="text-xs text-emerald-300">
                LIVE — Real payments are active. All charges will be billed to customers.
              </p>
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-1">
            <div className="space-y-1">
              <p className="text-xs text-gray-500 uppercase tracking-wide">Customers</p>
              {isLoading && !stripeStatus ? (
                <div className="h-5 w-12 bg-[#1a2a3d] rounded animate-pulse" />
              ) : (
                <p className="text-lg font-bold text-white">{customerCount}</p>
              )}
            </div>

            <div className="space-y-1">
              <p className="text-xs text-gray-500 uppercase tracking-wide flex items-center gap-1">
                <Webhook className="h-3 w-3" />
                Webhook
              </p>
              {isLoading && !stripeStatus ? (
                <div className="h-5 w-20 bg-[#1a2a3d] rounded animate-pulse" />
              ) : (
                <StatusDot
                  color={stripeStatus?.webhook_configured ? "green" : "red"}
                  label={stripeStatus?.webhook_configured ? "Configured" : "Not configured"}
                  pulse={stripeStatus?.webhook_configured}
                />
              )}
            </div>

            <div className="space-y-1">
              <p className="text-xs text-gray-500 uppercase tracking-wide">Last Event</p>
              {isLoading && !stripeStatus ? (
                <div className="h-5 w-24 bg-[#1a2a3d] rounded animate-pulse" />
              ) : (
                <p className="text-sm text-gray-300">
                  {formatRelativeTime(stripeStatus?.last_event ?? null)}
                </p>
              )}
            </div>
          </div>
        </div>

        {/* ── MRR Chart ───────────────────────────────────────────── */}
        <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-[var(--gold-400)]" />
              MRR — 30 Day View
            </h2>
            <span className="text-xs text-gray-500">USD</span>
          </div>
          {chartMounted ? (
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={mrrData}>
                <defs>
                  <linearGradient id="goldGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#F6B400" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#F6B400" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="date"
                  stroke="#1a2a3d"
                  tick={{ fill: "#9ca3af", fontSize: 11 }}
                  tickLine={false}
                  interval={6}
                />
                <YAxis
                  stroke="#1a2a3d"
                  tick={{ fill: "#9ca3af", fontSize: 11 }}
                  tickLine={false}
                  tickFormatter={(v: number) => "$" + v}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0d1926",
                    border: "1px solid #1a2a3d",
                    borderRadius: "8px",
                    color: "#fff",
                    fontSize: "12px",
                  }}
                  formatter={(v: unknown) => ["$" + Number(v).toFixed(2), "MRR"]}
                />
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke="#F6B400"
                  fill="url(#goldGrad)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div
              className="w-full flex items-center justify-center text-gray-600 text-xs animate-pulse bg-[#080f18] rounded-lg"
              style={{ height: 200 }}
            />
          )}
          {stripeStatus?.mode === "test" && (
            <p className="text-xs text-gray-600 text-center mt-2">
              No revenue in test mode — flip to LIVE to see real data
            </p>
          )}
        </div>

        {/* ── Recent Transactions ─────────────────────────────────── */}
        <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-5">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2 mb-4">
            <DollarSign className="h-4 w-4 text-[var(--gold-400)]" />
            Recent Transactions
          </h2>
          <DataTable<TransactionRow>
            columns={TRANSACTION_COLUMNS}
            data={transactions}
            pageSize={10}
            searchable={false}
            emptyMessage="No transactions yet — flip Stripe to LIVE mode to start accepting payments"
            isLoading={isLoading && !stripeStatus}
          />
        </div>

        {/* ── Cost Breakdown ──────────────────────────────────────── */}
        <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-5">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2 mb-4">
            <TrendingUp className="h-4 w-4 text-[var(--gold-400)]" />
            Cost Breakdown
          </h2>
          <div className="space-y-3">
            {[
              { label: "API costs (token usage)", value: "$0.00", sub: "LLM inference" },
              { label: "Hosting costs", value: "$0.00", sub: "Server + infra" },
              { label: "Stripe fees", value: "$0.00", sub: "2.9% + $0.30 / charge" },
            ].map(({ label, value, sub }) => (
              <div
                key={label}
                className="flex items-center justify-between py-2 border-b border-[#1a2a3d] last:border-0"
              >
                <div>
                  <p className="text-sm text-gray-300">{label}</p>
                  <p className="text-xs text-gray-600">{sub}</p>
                </div>
                <span className="text-sm font-semibold text-white">{value}</span>
              </div>
            ))}
            <div className="flex items-center justify-between pt-2">
              <div>
                <p className="text-sm font-semibold text-white">Net Margin</p>
                <p className="text-xs text-gray-500">Revenue minus all costs</p>
              </div>
              <span className="text-lg font-bold text-[var(--gold-400)]">$0.00</span>
            </div>
          </div>
        </div>

        {/* ── CRM preview link ────────────────────────────────────── */}
        <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-blue-500/10 flex items-center justify-center">
              <Users className="h-4 w-4 text-blue-400" />
            </div>
            <div>
              <p className="text-sm font-semibold text-white">CRM Pipeline</p>
              <p className="text-xs text-gray-400">
                {funnel
                  ? `${funnel.registered_users} registered, ${funnel.active_subscribers} subscribed`
                  : "View funnel and contacts"}
              </p>
            </div>
          </div>
          <a
            href="/admin/crm"
            className="px-4 py-2 min-h-[44px] flex items-center rounded-xl bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-semibold hover:bg-blue-500/20 transition-colors"
          >
            View CRM
          </a>
        </div>

      </div>
    </div>
  );
}
