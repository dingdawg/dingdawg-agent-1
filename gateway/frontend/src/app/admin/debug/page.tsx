"use client";

/**
 * Debug Monitor — near-real-time error feed and system health dashboard.
 *
 * Features:
 *  - Compact health stat pills (uptime, DB size, memory, avg response time)
 *  - Live scrolling error feed with color-coded severity, auto-scroll to newest
 *  - "Clear" button to dismiss acknowledged errors
 *  - Bar chart: avg response time per endpoint (red if > 500ms)
 *  - Top-10 endpoints table: request count, avg response time, error rate
 *  - Polls every 10s for near-real-time updates
 */

import { useCallback, useRef, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { usePolling } from "@/hooks/usePolling";
import * as adminService from "@/services/api/adminService";
import type {
  ErrorEntry,
  HealthDetailed,
  EndpointStat,
  ClientErrorEntry,
} from "@/services/api/adminService";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h >= 24) {
    const d = Math.floor(h / 24);
    return `${d}d ${h % 24}h`;
  }
  return `${h}h ${m}m`;
}

function formatTime(isoString: string): string {
  try {
    const d = new Date(isoString);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return isoString;
  }
}

// ─── Error card ───────────────────────────────────────────────────────────────

function ErrorCard({ error }: { error: ErrorEntry }) {
  const severityColor =
    error.status >= 500
      ? "border-red-500"
      : error.status >= 400
      ? "border-yellow-500"
      : "border-blue-500";

  const severityBg =
    error.status >= 500
      ? "bg-red-500/5"
      : error.status >= 400
      ? "bg-yellow-500/5"
      : "bg-blue-500/5";

  return (
    <div
      className={`p-3 ${severityBg} bg-[#0d1926] border-l-2 ${severityColor} rounded-r-lg mb-2`}
    >
      <div className="flex justify-between items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm text-white font-medium truncate">
            {error.message}
          </p>
          <p className="text-xs text-gray-500 mt-1">
            {error.endpoint} &middot; {error.count}x
            {error.status > 0 && (
              <span
                className={
                  error.status >= 500
                    ? " text-red-400"
                    : " text-yellow-400"
                }
              >
                {" "}
                HTTP {error.status}
              </span>
            )}
          </p>
        </div>
        <span className="text-xs text-gray-500 whitespace-nowrap flex-shrink-0">
          {formatTime(error.last_seen)}
        </span>
      </div>
    </div>
  );
}

// ─── Health stat pill ─────────────────────────────────────────────────────────

function StatPill({
  label,
  value,
  warn,
}: {
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div className="flex flex-col items-center bg-[#0d1926] border border-[#1a2a3d] rounded-xl px-3 py-2 min-w-[90px]">
      <span className="text-xs text-gray-500 mb-1">{label}</span>
      <span
        className={`text-sm font-bold tabular-nums ${
          warn ? "text-red-400" : "text-white"
        }`}
      >
        {value}
      </span>
    </div>
  );
}

// ─── Endpoint row ─────────────────────────────────────────────────────────────

function EndpointRow({ stat, rank }: { stat: EndpointStat; rank: number }) {
  const isSlow = stat.avg_response_ms > 500;
  return (
    <div className="flex items-center gap-3 py-2 border-b border-[#1a2a3d] last:border-0">
      <span className="text-xs text-gray-600 w-5 text-right">{rank}</span>
      <span className="flex-1 text-sm text-gray-300 font-mono truncate">
        {stat.endpoint}
      </span>
      <span className="text-xs tabular-nums text-gray-400 w-16 text-right">
        {stat.request_count.toLocaleString()}
      </span>
      <span
        className={`text-xs tabular-nums w-16 text-right ${
          isSlow ? "text-red-400" : "text-white"
        }`}
      >
        {stat.avg_response_ms}ms
      </span>
      <span
        className={`text-xs tabular-nums w-14 text-right ${
          stat.error_rate > 0.05 ? "text-red-400" : "text-gray-400"
        }`}
      >
        {(stat.error_rate * 100).toFixed(1)}%
      </span>
    </div>
  );
}

// ─── Client Error Card ────────────────────────────────────────────────────────

const ERROR_TYPE_LABELS: Record<string, string> = {
  js_error: "JS Error",
  unhandled_rejection: "Promise Rejection",
  api_error: "API Error",
  render_error: "Render Error",
};

function ClientErrorCard({ error }: { error: ClientErrorEntry }) {
  const [expanded, setExpanded] = useState(false);
  const typeLabel = ERROR_TYPE_LABELS[error.error_type] ?? error.error_type;
  const typeColor =
    error.error_type === "render_error" || error.error_type === "js_error"
      ? "text-red-400 bg-red-500/10 border-red-500/30"
      : error.error_type === "api_error"
      ? "text-yellow-400 bg-yellow-500/10 border-yellow-500/30"
      : "text-blue-400 bg-blue-500/10 border-blue-500/30";

  return (
    <div className="p-3 bg-[#0d1926] border border-[#1a2a3d] rounded-lg mb-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span
              className={`text-xs px-1.5 py-0.5 rounded border font-mono ${typeColor}`}
            >
              {typeLabel}
            </span>
            {error.component && (
              <span className="text-xs text-gray-500 font-mono">
                {error.component}
              </span>
            )}
          </div>
          <p className="text-sm text-white font-medium break-words">
            {error.message}
          </p>
          <p className="text-xs text-gray-500 mt-1 truncate" title={error.endpoint}>
            {error.endpoint}
          </p>
        </div>
        <span className="text-xs text-gray-500 whitespace-nowrap flex-shrink-0">
          {formatTime(error.last_seen)}
        </span>
      </div>

      {error.stack && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 text-xs text-gray-500 hover:text-gray-300 transition-colors"
        >
          {expanded ? "Hide stack" : "Show stack"}
        </button>
      )}
      {expanded && error.stack && (
        <pre className="mt-2 text-xs text-gray-400 bg-[#07111c] border border-[#1a2a3d] rounded p-2 overflow-x-auto whitespace-pre-wrap break-all">
          {error.stack}
        </pre>
      )}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function DebugMonitorPage() {
  const [errors, setErrors] = useState<ErrorEntry[]>([]);
  const [clientErrors, setClientErrors] = useState<ClientErrorEntry[]>([]);
  const [health, setHealth] = useState<HealthDetailed | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [clearing, setClearing] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const errorFeedRef = useRef<HTMLDivElement>(null);

  async function fetchAll() {
    setFetchError(null);
    try {
      const [errs, h] = await Promise.allSettled([
        adminService.getErrors(),
        adminService.getHealthDetailed(),
      ]);

      if (errs.status === "fulfilled") {
        const all = errs.value;
        // Split merged list into server errors and client errors
        const serverErrs = all.filter(
          (e): e is ErrorEntry =>
            (e as ErrorEntry & { source?: string }).source !== "client"
        );
        const clientErrs = all.filter(
          (e): e is ClientErrorEntry =>
            (e as ClientErrorEntry).source === "client"
        );
        setErrors(serverErrs);
        setClientErrors(clientErrs);
        // Auto-scroll to newest (bottom) after state update
        requestAnimationFrame(() => {
          if (errorFeedRef.current) {
            errorFeedRef.current.scrollTop = errorFeedRef.current.scrollHeight;
          }
        });
      }
      if (h.status === "fulfilled") {
        setHealth(h.value);
      }
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "Failed to fetch debug data";
      setFetchError(msg);
    } finally {
      setIsLoading(false);
    }
  }

  const poll = useCallback(() => {
    void fetchAll();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  usePolling(poll, 10_000);

  async function handleClear() {
    if (clearing) return;
    setClearing(true);
    try {
      await adminService.clearErrors();
      setErrors([]);
    } catch {
      /* non-critical */
    } finally {
      setClearing(false);
    }
  }

  // ─── Chart data ────────────────────────────────────────────────────────────

  const chartData = (health?.response_times ?? []).slice(0, 10).map((rt) => ({
    name: rt.endpoint.length > 22 ? rt.endpoint.slice(-22) : rt.endpoint,
    ms: rt.avg_ms,
    slow: rt.avg_ms > 500,
  }));

  const avgMs = health?.avg_response_ms ?? 0;
  const isSlowOverall = avgMs > 500;

  return (
    <div className="min-h-screen bg-[var(--ink-950,#07111c)] p-4 md:p-6 space-y-6">
      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold font-heading text-white">
            Debug Monitor
          </h1>
          <p className="text-gray-400 text-sm mt-1">
            Live system feed &mdash; refreshes every 10s
            {isLoading && (
              <span className="ml-2 text-xs text-[#F6B400]">Loading...</span>
            )}
          </p>
        </div>
      </div>

      {fetchError && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3 text-red-400 text-sm">
          {fetchError}
        </div>
      )}

      {/* ── Health status bar ────────────────────────────────────────────────── */}
      <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4">
        <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
          System Health
        </h2>
        {health ? (
          <div className="flex flex-wrap gap-2">
            <StatPill
              label="Uptime"
              value={formatUptime(health.uptime_seconds)}
            />
            <StatPill
              label="DB Size"
              value={`${health.db_size_mb.toFixed(1)} MB`}
            />
            <StatPill
              label="Memory"
              value={`${health.memory_mb.toFixed(0)} MB`}
            />
            <StatPill
              label="Avg Response"
              value={`${avgMs}ms`}
              warn={isSlowOverall}
            />
          </div>
        ) : (
          <div className="flex gap-2">
            {[1, 2, 3, 4].map((i) => (
              <div
                key={i}
                className="h-14 w-24 bg-[#1a2a3d] rounded-xl animate-pulse"
              />
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* ── Error feed ────────────────────────────────────────────────────── */}
        <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4 flex flex-col">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
              Error Feed
              {errors.length > 0 && (
                <span className="ml-2 bg-red-500/20 text-red-400 border border-red-500/30 text-xs px-1.5 py-0.5 rounded-full">
                  {errors.length}
                </span>
              )}
            </h2>
            {errors.length > 0 && (
              <button
                onClick={handleClear}
                disabled={clearing}
                className="text-xs text-gray-500 hover:text-white transition-colors px-2 py-1 rounded border border-[#1a2a3d] hover:border-[#F6B400] min-h-[32px]"
              >
                {clearing ? "Clearing..." : "Clear"}
              </button>
            )}
          </div>

          <div
            ref={errorFeedRef}
            className="flex-1 overflow-y-auto max-h-72 space-y-0 scrollbar-thin pr-1"
          >
            {errors.length === 0 ? (
              <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
                No errors recorded.
              </div>
            ) : (
              errors.map((err) => <ErrorCard key={err.id} error={err} />)
            )}
          </div>
        </div>

        {/* ── Response time chart ──────────────────────────────────────────── */}
        <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4">
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Response Time by Endpoint
            <span className="ml-2 text-gray-600 font-normal normal-case">
              (red = &gt;500ms)
            </span>
          </h2>

          {chartData.length === 0 ? (
            <div className="h-48 flex items-center justify-center text-gray-500 text-sm">
              No response time data available.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart
                data={chartData}
                layout="vertical"
                margin={{ left: 8, right: 16 }}
              >
                <XAxis
                  type="number"
                  tickLine={false}
                  axisLine={false}
                  tick={{ fill: "#6b7280", fontSize: 11 }}
                  tickFormatter={(v) => `${v}ms`}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  tickLine={false}
                  axisLine={false}
                  tick={{ fill: "#6b7280", fontSize: 10 }}
                  width={110}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0d1926",
                    border: "1px solid #1a2a3d",
                    borderRadius: "8px",
                    color: "#fff",
                  }}
                  formatter={(value) => [`${typeof value === "number" ? value : 0}ms`, "Avg Response"]}
                />
                <Bar dataKey="ms" radius={[0, 4, 4, 0]}>
                  {chartData.map((entry, idx) => (
                    <Cell
                      key={idx}
                      fill={entry.slow ? "#ef4444" : "#F6B400"}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* ── API request breakdown ────────────────────────────────────────────── */}
      <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4">
        <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
          Top Endpoints by Request Count
        </h2>

        {health === null ? (
          <div className="space-y-2">
            {[1, 2, 3, 4, 5].map((i) => (
              <div
                key={i}
                className="h-8 bg-[#1a2a3d] rounded animate-pulse"
              />
            ))}
          </div>
        ) : (health.top_endpoints ?? []).length === 0 ? (
          <div className="py-8 text-center text-gray-500 text-sm">
            No endpoint data available.
          </div>
        ) : (
          <div>
            <div className="flex items-center gap-3 pb-2 border-b border-[#1a2a3d] text-xs text-gray-500">
              <span className="w-5" />
              <span className="flex-1">Endpoint</span>
              <span className="w-16 text-right">Requests</span>
              <span className="w-16 text-right">Avg</span>
              <span className="w-14 text-right">Errors</span>
            </div>
            {(health.top_endpoints ?? []).slice(0, 10).map((stat, idx) => (
              <EndpointRow key={stat.endpoint} stat={stat} rank={idx + 1} />
            ))}
          </div>
        )}
      </div>

      {/* ── Client Errors ─────────────────────────────────────────────────────── */}
      <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
            Client Errors
            {clientErrors.length > 0 && (
              <span className="ml-2 bg-orange-500/20 text-orange-400 border border-orange-500/30 text-xs px-1.5 py-0.5 rounded-full">
                {clientErrors.length}
              </span>
            )}
            <span className="ml-2 text-gray-600 font-normal normal-case">
              (auto-refreshes every 10s)
            </span>
          </h2>
        </div>

        {isLoading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-16 bg-[#1a2a3d] rounded animate-pulse" />
            ))}
          </div>
        ) : clientErrors.length === 0 ? (
          <div className="flex items-center justify-center h-24 text-gray-500 text-sm">
            No client errors recorded.
          </div>
        ) : (
          <div className="max-h-80 overflow-y-auto scrollbar-thin pr-1">
            {clientErrors.map((err) => (
              <ClientErrorCard key={err.id} error={err} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
