"use client";

/**
 * CRM admin page — Command Center pipeline and contact management.
 *
 * Sections:
 *   1. Funnel visualization (horizontal bars): Registered -> Claimed -> Subscribed -> Active 7d -> Churned 30d
 *   2. Churn indicators (inactive 7d+, failed payments, expiring subs)
 *   3. Session depth bar chart (messages-per-session distribution)
 *   4. Contact DataTable with search and pagination
 *
 * Data: adminService.getFunnel(), adminService.getContacts()
 * Polling: 60 seconds via usePolling
 * Auth gate: AdminRoute
 */

import { useCallback, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import {
  Users,
  AlertCircle,
  RefreshCw,
  TrendingDown,
  Activity,
  Search,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAdminRevenueStore } from "@/store/adminRevenueStore";
import { usePolling } from "@/hooks/usePolling";
import AdminRoute from "@/components/auth/AdminRoute";
import StatusDot from "@/components/admin/StatusDot";
import DataTable, { type ColumnDef } from "@/components/admin/DataTable";
import type { Contact, FunnelData } from "@/store/adminRevenueStore";

// ─── Funnel bar component ─────────────────────────────────────────────────────

interface FunnelBarProps {
  label: string;
  value: number;
  maxValue: number;
  color: string;
  conversionRate?: number;
}

function FunnelBar({ label, value, maxValue, color, conversionRate }: FunnelBarProps) {
  const widthPct = maxValue > 0 ? Math.max((value / maxValue) * 100, 2) : 0;
  return (
    <div className="mb-4">
      <div className="flex justify-between text-sm mb-1.5">
        <span className="text-gray-400 font-medium">{label}</span>
        <div className="flex items-center gap-2">
          {conversionRate !== undefined && (
            <span className="text-xs text-gray-600">
              {conversionRate.toFixed(1)}% conv.
            </span>
          )}
          <span className="text-white font-bold tabular-nums">{value.toLocaleString()}</span>
        </div>
      </div>
      <div className="h-8 bg-[#1a2a3d] rounded-lg overflow-hidden">
        <div
          className="h-full rounded-lg transition-all duration-500"
          style={{ width: `${widthPct}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}

// ─── Churn indicator card ─────────────────────────────────────────────────────

interface ChurnCardProps {
  label: string;
  count: number;
  total: number;
  severity: "warning" | "critical" | "info";
}

function ChurnCard({ label, count, total, severity }: ChurnCardProps) {
  const pct = total > 0 ? ((count / total) * 100).toFixed(1) : "0.0";
  const colorMap = {
    warning: "text-yellow-400 bg-yellow-500/10 border-yellow-500/20",
    critical: "text-red-400 bg-red-500/10 border-red-500/20",
    info: "text-blue-400 bg-blue-500/10 border-blue-500/20",
  };
  return (
    <div className={cn("rounded-xl border p-4 flex items-center justify-between", colorMap[severity])}>
      <div>
        <p className="text-xs font-medium opacity-80 uppercase tracking-wide mb-1">{label}</p>
        <p className="text-2xl font-bold">{count}</p>
      </div>
      <div className="text-right">
        <p className="text-xs opacity-60">of total</p>
        <p className="text-lg font-semibold">{pct}%</p>
      </div>
    </div>
  );
}

// ─── Mock session depth data ──────────────────────────────────────────────────

const SESSION_DEPTH_DATA = [
  { range: "1-2", sessions: 0 },
  { range: "3-5", sessions: 0 },
  { range: "6-10", sessions: 0 },
  { range: "11-20", sessions: 0 },
  { range: "20+", sessions: 0 },
];

// ─── Contact table columns ────────────────────────────────────────────────────

const CONTACT_COLUMNS: ColumnDef<Contact>[] = [
  {
    header: "Email",
    accessor: "email",
    sortable: true,
    render: (v) => (
      <span className="text-white font-medium text-sm">{String(v)}</span>
    ),
  },
  {
    header: "Agent Handle",
    accessor: "agent_handle",
    sortable: true,
    render: (v) =>
      v ? (
        <span className="text-[var(--gold-400)] font-medium">@{String(v)}</span>
      ) : (
        <span className="text-gray-600 text-xs">Not claimed</span>
      ),
  },
  {
    header: "Status",
    accessor: "status",
    sortable: true,
    render: (v) => {
      const val = String(v) as "active" | "inactive" | "churned";
      const colorMap: Record<string, "green" | "yellow" | "red"> = {
        active: "green",
        inactive: "yellow",
        churned: "red",
      };
      return (
        <StatusDot
          color={colorMap[val] ?? "gray"}
          label={val.charAt(0).toUpperCase() + val.slice(1)}
          pulse={val === "active"}
        />
      );
    },
  },
  {
    header: "Last Active",
    accessor: "last_active",
    sortable: true,
    render: (v) => {
      if (!v) return <span className="text-gray-600 text-xs">Never</span>;
      try {
        const d = new Date(String(v));
        const diff = Date.now() - d.getTime();
        const days = Math.floor(diff / 86_400_000);
        const label =
          days === 0
            ? "Today"
            : days === 1
            ? "Yesterday"
            : `${days}d ago`;
        return (
          <span className={cn("text-sm", days >= 7 ? "text-red-400" : "text-gray-300")}>
            {label}
          </span>
        );
      } catch {
        return <span className="text-gray-400 text-sm">{String(v)}</span>;
      }
    },
  },
  {
    header: "Plan",
    accessor: "subscription_tier",
    sortable: true,
    render: (v) =>
      v ? (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-[var(--gold-400)]/10 text-[var(--gold-400)] border border-[var(--gold-400)]/20 capitalize">
          {String(v)}
        </span>
      ) : (
        <span className="text-gray-600 text-xs">Free</span>
      ),
  },
];

// ─── Funnel section ───────────────────────────────────────────────────────────

function FunnelSection({ funnel, isLoading }: { funnel: FunnelData | null; isLoading: boolean }) {
  if (isLoading && !funnel) {
    return (
      <div className="space-y-4">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="space-y-1.5">
            <div className="flex justify-between">
              <div className="h-4 w-28 bg-[#1a2a3d] rounded animate-pulse" />
              <div className="h-4 w-10 bg-[#1a2a3d] rounded animate-pulse" />
            </div>
            <div className="h-8 bg-[#1a2a3d] rounded-lg animate-pulse" />
          </div>
        ))}
      </div>
    );
  }

  const f = funnel ?? {
    registered_users: 0,
    claimed_handles: 0,
    active_subscribers: 0,
    active_7d: 0,
    churned_30d: 0,
  };

  const maxVal = Math.max(f.registered_users, 1);

  function convRate(a: number, b: number): number {
    return b > 0 ? (a / b) * 100 : 0;
  }

  return (
    <div>
      <FunnelBar
        label="Registered Users"
        value={f.registered_users}
        maxValue={maxVal}
        color="#F6B400"
      />
      <FunnelBar
        label="Claimed Handle"
        value={f.claimed_handles}
        maxValue={maxVal}
        color="#22c55e"
        conversionRate={convRate(f.claimed_handles, f.registered_users)}
      />
      <FunnelBar
        label="Subscribed"
        value={f.active_subscribers}
        maxValue={maxVal}
        color="#3b82f6"
        conversionRate={convRate(f.active_subscribers, f.claimed_handles)}
      />
      <FunnelBar
        label="Active (7d)"
        value={f.active_7d}
        maxValue={maxVal}
        color="#8b5cf6"
        conversionRate={convRate(f.active_7d, f.active_subscribers)}
      />
      <FunnelBar
        label="Churned (30d)"
        value={f.churned_30d}
        maxValue={maxVal}
        color="#ef4444"
        conversionRate={convRate(f.churned_30d, f.active_subscribers)}
      />
    </div>
  );
}

// ─── Page export ──────────────────────────────────────────────────────────────

export default function CrmPage() {
  return (
    <AdminRoute>
      <CrmContent />
    </AdminRoute>
  );
}

// ─── CRM Content ──────────────────────────────────────────────────────────────

function CrmContent() {
  const {
    funnel,
    contacts,
    isLoading,
    error,
    fetchFunnel,
    fetchContacts,
  } = useAdminRevenueStore();

  const [refreshing, setRefreshing] = useState(false);
  const [contactSearch, setContactSearch] = useState("");
  const [contactPage, setContactPage] = useState(1);

  const PER_PAGE = 20;

  const poll = useCallback(async () => {
    await Promise.allSettled([
      fetchFunnel(),
      fetchContacts({ page: contactPage, per_page: PER_PAGE, search: contactSearch || undefined }),
    ]);
  }, [fetchFunnel, fetchContacts, contactPage, contactSearch]);

  usePolling(poll, 60_000);

  async function handleRefresh() {
    setRefreshing(true);
    await poll();
    setRefreshing(false);
  }

  function handleSearchChange(value: string) {
    setContactSearch(value);
    setContactPage(1);
    void fetchContacts({ page: 1, per_page: PER_PAGE, search: value || undefined });
  }

  function handlePageChange(next: number) {
    setContactPage(next);
    void fetchContacts({ page: next, per_page: PER_PAGE, search: contactSearch || undefined });
  }

  const totalUsers = funnel?.registered_users ?? 0;
  const inactive7d = funnel ? Math.max(0, funnel.active_subscribers - funnel.active_7d) : 0;
  const churned30d = funnel?.churned_30d ?? 0;

  const contactItems = contacts?.items ?? [];
  const totalContacts = contacts?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalContacts / PER_PAGE));

  return (
    <div className="min-h-screen bg-[var(--ink-950)] overflow-y-auto scrollbar-thin">
      <div className="max-w-5xl mx-auto px-4 pt-6 pb-24 lg:pb-8 space-y-6">

        {/* ── Header ─────────────────────────────────────────────── */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-heading font-bold text-white">CRM Pipeline</h1>
            <p className="text-xs text-gray-400 mt-0.5">Funnel, contacts, and churn indicators</p>
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
            <button onClick={handleRefresh} className="text-xs underline">retry</button>
          </div>
        )}

        {/* ── Two-column: Funnel + Churn ──────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Funnel */}
          <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-5">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2 mb-5">
              <Activity className="h-4 w-4 text-[var(--gold-400)]" />
              Acquisition Funnel
            </h2>
            <FunnelSection funnel={funnel} isLoading={isLoading} />
          </div>

          {/* Churn indicators */}
          <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-5">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2 mb-5">
              <TrendingDown className="h-4 w-4 text-red-400" />
              Churn Indicators
            </h2>
            <div className="space-y-3">
              <ChurnCard
                label="Inactive 7+ days"
                count={inactive7d}
                total={totalUsers}
                severity="warning"
              />
              <ChurnCard
                label="Failed payments"
                count={0}
                total={totalUsers}
                severity="critical"
              />
              <ChurnCard
                label="Churned (30d)"
                count={churned30d}
                total={totalUsers}
                severity="critical"
              />
              <ChurnCard
                label="Expiring subscriptions"
                count={0}
                total={totalUsers}
                severity="info"
              />
            </div>
          </div>
        </div>

        {/* ── Session Depth Chart ─────────────────────────────────── */}
        <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <Activity className="h-4 w-4 text-[var(--gold-400)]" />
              Session Depth Distribution
            </h2>
            <span className="text-xs text-gray-500">Messages per session</span>
          </div>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={SESSION_DEPTH_DATA} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
              <XAxis
                dataKey="range"
                stroke="#1a2a3d"
                tick={{ fill: "#9ca3af", fontSize: 11 }}
                tickLine={false}
              />
              <YAxis
                stroke="#1a2a3d"
                tick={{ fill: "#9ca3af", fontSize: 11 }}
                tickLine={false}
                allowDecimals={false}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#0d1926",
                  border: "1px solid #1a2a3d",
                  borderRadius: "8px",
                  color: "#fff",
                  fontSize: "12px",
                }}
                cursor={{ fill: "rgba(246,180,0,0.06)" }}
              />
              <Bar dataKey="sessions" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <p className="text-xs text-gray-600 text-center mt-1">
            High 6-20 msg sessions indicate strong product-market fit
          </p>
        </div>

        {/* ── Contacts Table ──────────────────────────────────────── */}
        <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-5">
          <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <Users className="h-4 w-4 text-[var(--gold-400)]" />
              Contacts
              {totalContacts > 0 && (
                <span className="text-xs text-gray-500 font-normal">
                  ({totalContacts.toLocaleString()} total)
                </span>
              )}
            </h2>

            {/* Search */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500 pointer-events-none" />
              <input
                type="search"
                value={contactSearch}
                onChange={(e) => handleSearchChange(e.target.value)}
                placeholder="Search email or handle..."
                className="pl-8 pr-3 py-2 min-h-[44px] w-56 bg-[var(--ink-950)] border border-[#1a2a3d] rounded-xl text-sm text-white placeholder-gray-600 focus:outline-none focus:border-[var(--gold-400)] transition-colors"
              />
            </div>
          </div>

          <DataTable<Contact>
            columns={CONTACT_COLUMNS}
            data={contactItems}
            pageSize={PER_PAGE}
            searchable={false}
            emptyMessage={
              contactSearch
                ? `No contacts matching "${contactSearch}"`
                : "No contacts yet — users will appear here once they register"
            }
            isLoading={isLoading && !contacts}
          />

          {/* Server-side pagination controls */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-3 text-xs text-gray-400">
              <span>{totalContacts} contacts</span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handlePageChange(contactPage - 1)}
                  disabled={contactPage === 1 || isLoading}
                  className="px-3 py-1.5 min-h-[36px] rounded-lg bg-[var(--ink-950)] border border-[#1a2a3d] disabled:opacity-40 disabled:cursor-not-allowed hover:border-[var(--gold-400)] transition-colors"
                >
                  Prev
                </button>
                <span className="px-2">
                  {contactPage} / {totalPages}
                </span>
                <button
                  onClick={() => handlePageChange(contactPage + 1)}
                  disabled={contactPage === totalPages || isLoading}
                  className="px-3 py-1.5 min-h-[36px] rounded-lg bg-[var(--ink-950)] border border-[#1a2a3d] disabled:opacity-40 disabled:cursor-not-allowed hover:border-[var(--gold-400)] transition-colors"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>

        {/* ── Link back to revenue ────────────────────────────────── */}
        <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-[var(--gold-400)]/10 flex items-center justify-center">
              <Activity className="h-4 w-4 text-[var(--gold-400)]" />
            </div>
            <div>
              <p className="text-sm font-semibold text-white">Revenue Dashboard</p>
              <p className="text-xs text-gray-400">MRR, Stripe status, transactions</p>
            </div>
          </div>
          <a
            href="/admin/revenue"
            className="px-4 py-2 min-h-[44px] flex items-center rounded-xl bg-[var(--gold-400)]/10 border border-[var(--gold-400)]/20 text-[var(--gold-400)] text-xs font-semibold hover:bg-[var(--gold-400)]/20 transition-colors"
          >
            View Revenue
          </a>
        </div>

      </div>
    </div>
  );
}
