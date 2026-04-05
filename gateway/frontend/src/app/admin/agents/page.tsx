"use client";

/**
 * Agent Control Center — admin page for viewing, searching, filtering,
 * and managing all platform agents.
 *
 * Features:
 *  - 4 summary StatCards (total, active today, suspended, unique templates)
 *  - Full DataTable with search + status filter + pagination (20/page)
 *  - Agent distribution PieChart (agents per template)
 *  - Suspend / Activate toggle per row
 *  - Polls every 60s via usePolling
 */

import { useCallback, useEffect, useState } from "react";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import StatCard from "@/components/admin/StatCard";
import DataTable from "@/components/admin/DataTable";
import type { ColumnDef } from "@/components/admin/DataTable";
import StatusDot from "@/components/admin/StatusDot";
import { usePolling } from "@/hooks/usePolling";
import * as adminService from "@/services/api/adminService";
import type { AdminAgent, TemplateDistributionItem } from "@/services/api/adminService";
import { useAdminAgentsStore } from "@/store/adminAgentsStore";

const CHART_COLORS = [
  "#F6B400",
  "#22c55e",
  "#3b82f6",
  "#a855f7",
  "#ec4899",
  "#f97316",
];

const STATUS_FILTERS = ["all", "active", "suspended", "inactive"] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

// ─── Status dot helper ────────────────────────────────────────────────────────

function agentStatusColor(
  status: AdminAgent["status"]
): "green" | "yellow" | "red" {
  if (status === "active") return "green";
  if (status === "suspended") return "red";
  return "yellow";
}

// ─── Row action button ────────────────────────────────────────────────────────

function ToggleStatusButton({
  agent,
  onToggle,
}: {
  agent: AdminAgent;
  onToggle: (id: string, newStatus: "active" | "suspended") => void;
}) {
  const [busy, setBusy] = useState(false);

  async function handleClick() {
    if (busy) return;
    setBusy(true);
    try {
      await onToggle(
        agent.id,
        agent.status === "active" ? "suspended" : "active"
      );
    } finally {
      setBusy(false);
    }
  }

  if (agent.status === "inactive") {
    return <span className="text-xs text-gray-600">—</span>;
  }

  const isSuspended = agent.status === "suspended";

  return (
    <button
      onClick={handleClick}
      disabled={busy}
      className={[
        "px-2.5 py-1 rounded-lg text-xs font-semibold transition-colors min-h-[32px]",
        isSuspended
          ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/20"
          : "bg-red-500/10 text-red-400 border border-red-500/30 hover:bg-red-500/20",
        busy ? "opacity-50 cursor-wait" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {busy ? "..." : isSuspended ? "Activate" : "Suspend"}
    </button>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function AgentControlPage() {
  const {
    agents,
    totalAgents,
    page,
    perPage,
    search,
    statusFilter,
    isLoading,
    error,
    fetchAgents,
    setPage,
    setSearch,
    setStatusFilter,
    suspendAgent,
    activateAgent,
  } = useAdminAgentsStore();

  const [distribution, setDistribution] = useState<TemplateDistributionItem[]>(
    []
  );
  const [distLoading, setDistLoading] = useState(false);

  // Fetch distribution on mount (not polled — template names rarely change)
  useEffect(() => {
    setDistLoading(true);
    adminService
      .getAgentTemplateDistribution()
      .then(setDistribution)
      .catch(() => {
        /* distribution is non-critical — fail silently */
      })
      .finally(() => setDistLoading(false));
  }, []);

  const poll = useCallback(() => {
    void fetchAgents();
  }, [fetchAgents]);

  usePolling(poll, 60_000);

  // Re-fetch whenever filter/page/search changes
  useEffect(() => {
    void fetchAgents();
  }, [page, statusFilter, fetchAgents]);

  // Debounce search to avoid hammering the API on every keystroke
  useEffect(() => {
    const timer = setTimeout(() => {
      void fetchAgents();
    }, 350);
    return () => clearTimeout(timer);
  }, [search, fetchAgents]);

  async function handleToggle(
    id: string,
    newStatus: "active" | "suspended"
  ) {
    if (newStatus === "suspended") {
      await suspendAgent(id);
    } else {
      await activateAgent(id);
    }
  }

  // ─── Derived summary stats ──────────────────────────────────────────────────

  const activeCount = agents.filter((a) => a.status === "active").length;
  const suspendedCount = agents.filter((a) => a.status === "suspended").length;
  const uniqueTemplates = new Set(agents.map((a) => a.template_name)).size;

  const totalPages = Math.max(1, Math.ceil(totalAgents / perPage));

  // ─── Column definitions ─────────────────────────────────────────────────────

  const columns: ColumnDef<AdminAgent>[] = [
    {
      header: "Handle",
      accessor: "handle",
      sortable: true,
      render: (v) => (
        <span className="font-mono text-[var(--gold-400,#F6B400)] text-sm">
          @{String(v)}
        </span>
      ),
    },
    {
      header: "Owner",
      accessor: "owner_email",
      sortable: true,
      render: (v) => (
        <span className="text-gray-300 text-sm truncate max-w-[180px] block">
          {String(v)}
        </span>
      ),
    },
    {
      header: "Status",
      accessor: "status",
      sortable: true,
      render: (v, row) => (
        <StatusDot
          color={agentStatusColor((row as AdminAgent).status)}
          label={String(v)}
        />
      ),
    },
    {
      header: "Template",
      accessor: "template_name",
      sortable: true,
      render: (v) => (
        <span className="text-gray-300 text-sm">{String(v)}</span>
      ),
    },
    {
      header: "Created",
      accessor: "created_at",
      sortable: true,
      render: (v) => (
        <span className="text-gray-400 text-xs">
          {new Date(String(v)).toLocaleDateString()}
        </span>
      ),
    },
    {
      header: "Last Active",
      accessor: "last_active",
      render: (v) => (
        <span className="text-gray-400 text-xs">
          {v ? new Date(String(v)).toLocaleDateString() : "Never"}
        </span>
      ),
    },
    {
      header: "Messages",
      accessor: "message_count",
      sortable: true,
      render: (v) => (
        <span className="text-white font-medium tabular-nums">{String(v)}</span>
      ),
    },
    {
      header: "Action",
      accessor: "id",
      render: (_, row) => (
        <ToggleStatusButton
          agent={row as AdminAgent}
          onToggle={handleToggle}
        />
      ),
    },
  ];

  return (
    <div className="min-h-screen bg-[var(--ink-950,#07111c)] p-4 md:p-6">
      <div className="max-w-3xl mx-auto space-y-6">
      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div>
        <h1 className="text-2xl font-bold font-heading text-white">
          Agent Control Center
        </h1>
        <p className="text-gray-400 text-[15px] mt-1">
          {totalAgents.toLocaleString()} total agents
          {isLoading && (
            <span className="ml-2 text-xs text-[#F6B400]">Refreshing...</span>
          )}
        </p>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* ── Summary cards ────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="Total Agents"
          value={totalAgents.toLocaleString()}
          isLoading={isLoading}
        />
        <StatCard
          label="Active Today"
          value={activeCount.toLocaleString()}
          subLabel="on this page"
          isLoading={isLoading}
        />
        <StatCard
          label="Suspended"
          value={suspendedCount.toLocaleString()}
          isLoading={isLoading}
        />
        <StatCard
          label="Templates Used"
          value={uniqueTemplates.toLocaleString()}
          subLabel="unique"
          isLoading={isLoading}
        />
      </div>

      {/* ── Filter bar ──────────────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row gap-3">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search handle or email..."
          className="flex-1 bg-[#0d1926] border border-[#1a2a3d] rounded-2xl px-4 py-2 text-[15px] text-white placeholder-gray-500 focus:outline-none focus:border-[#F6B400] transition-colors min-h-[44px]"
        />
        <div className="flex gap-1.5 flex-wrap">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              className={[
                "px-3 py-2 rounded-lg text-xs font-semibold capitalize transition-colors min-h-[44px]",
                statusFilter === f
                  ? "bg-[#F6B400] text-[#07111c]"
                  : "bg-[#0d1926] border border-[#1a2a3d] text-gray-400 hover:border-[#F6B400] hover:text-white",
              ].join(" ")}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* ── Agent table ─────────────────────────────────────────────────────── */}
      <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4">
        <DataTable<AdminAgent>
          columns={columns}
          data={agents}
          pageSize={perPage}
          searchable={false}
          emptyMessage="No agents match your search."
          isLoading={isLoading}
        />

        {/* Server-side pagination controls */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between mt-4 text-xs text-gray-400">
            <span>
              Page {page} of {totalPages} ({totalAgents.toLocaleString()} agents)
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage(Math.max(1, page - 1))}
                disabled={page === 1}
                className="px-3 py-1.5 rounded-lg bg-[#0a1520] border border-[#1a2a3d] disabled:opacity-40 hover:border-[#F6B400] transition-colors min-h-[36px]"
              >
                Prev
              </button>
              <button
                onClick={() => setPage(Math.min(totalPages, page + 1))}
                disabled={page === totalPages}
                className="px-3 py-1.5 rounded-lg bg-[#0a1520] border border-[#1a2a3d] disabled:opacity-40 hover:border-[#F6B400] transition-colors min-h-[36px]"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── Template distribution chart ──────────────────────────────────────── */}
      <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">
          Agent Distribution by Template
        </h2>

        {distLoading ? (
          <div className="h-48 flex items-center justify-center text-gray-500 text-sm">
            Loading chart...
          </div>
        ) : distribution.length === 0 ? (
          <div className="h-48 flex items-center justify-center text-gray-500 text-sm">
            No distribution data available.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie
                data={distribution}
                dataKey="count"
                nameKey="template_name"
                cx="50%"
                cy="50%"
                innerRadius={55}
                outerRadius={85}
                paddingAngle={3}
              >
                {distribution.map((_, idx) => (
                  <Cell
                    key={idx}
                    fill={CHART_COLORS[idx % CHART_COLORS.length]}
                  />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  backgroundColor: "#0d1926",
                  border: "1px solid #1a2a3d",
                  borderRadius: "8px",
                  color: "#fff",
                }}
                formatter={(value, name) => [
                  typeof value === "number" ? value.toLocaleString() : String(value ?? ""),
                  String(name ?? ""),
                ]}
              />
              <Legend
                iconType="circle"
                iconSize={8}
                formatter={(value) => (
                  <span className="text-xs text-gray-400">{value}</span>
                )}
              />
            </PieChart>
          </ResponsiveContainer>
        )}
      </div>
      </div>
    </div>
  );
}
