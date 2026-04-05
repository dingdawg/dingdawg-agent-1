"use client";

/**
 * System Health page — /admin/system
 *
 * Shows:
 *   - Overall system status banner (healthy/degraded/critical)
 *   - Uptime + key metrics row
 *   - Component status cards: DB, LLM providers, integrations, security
 *   - Self-healing panel: circuit breakers + auto-recovery log
 *   - Recent errors expandable list
 *   - "Run Self-Test" button with live results
 *
 * Polls every 30s. Pauses when tab is hidden.
 * Glass-panel-gold styling matches existing Command Center design.
 * Mobile responsive.
 */

import { useCallback, useEffect, useState } from "react";
import { usePolling } from "@/hooks/usePolling";
import StatusDot from "@/components/admin/StatusDot";
import {
  getSystemHealth,
  getSystemErrors,
  runSystemSelfTest,
} from "@/services/api/adminService";
import type {
  SystemHealthReport,
  SystemErrorEntry,
  SelfTestResponse,
  SelfTestResult,
  SystemStatus,
} from "@/services/api/adminService";
import { cn } from "@/lib/utils";

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

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso + "Z").toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function statusColor(s: string): "green" | "yellow" | "red" | "gray" {
  const lower = s.toLowerCase();
  if (lower === "ok" || lower === "healthy" || lower === "closed" || lower === "active" || lower === "pass") return "green";
  if (lower === "degraded" || lower === "warning" || lower === "test" || lower === "configured" || lower === "dev-mode") return "yellow";
  if (lower === "critical" || lower === "error" || lower === "open" || lower === "fail") return "red";
  return "gray";
}

function overallBannerClass(status: SystemStatus): string {
  if (status === "healthy") return "bg-emerald-500/10 border-emerald-500/30 text-emerald-400";
  if (status === "degraded") return "bg-yellow-500/10 border-yellow-500/30 text-yellow-400";
  return "bg-red-500/10 border-red-500/30 text-red-400";
}

// ─── Skeletons ────────────────────────────────────────────────────────────────

function SkeletonBlock({ h = "h-24" }: { h?: string }) {
  return (
    <div className={`${h} bg-[#0d1926] border border-[#1a2a3d] rounded-xl animate-pulse`} />
  );
}

// ─── Section wrapper ──────────────────────────────────────────────────────────

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
        {title}
      </h2>
      {children}
    </section>
  );
}

// ─── Component card ───────────────────────────────────────────────────────────

function ComponentCard({
  title,
  status,
  children,
}: {
  title: string;
  status: string;
  children?: React.ReactNode;
}) {
  const color = statusColor(status);
  return (
    <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-medium text-white">{title}</span>
        <StatusDot color={color} label={status.toUpperCase()} />
      </div>
      {children}
    </div>
  );
}

// ─── Metric row ───────────────────────────────────────────────────────────────

function MetricRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between text-sm py-1">
      <span className="text-gray-400">{label}</span>
      <span className="text-white text-xs font-medium tabular-nums">{value}</span>
    </div>
  );
}

// ─── Self-test result row ─────────────────────────────────────────────────────

function SelfTestRow({ result }: { result: SelfTestResult }) {
  const isPassed = result.result === "pass";
  return (
    <div className="flex items-start gap-3 py-2 border-b border-[#1a2a3d] last:border-0">
      <span
        className={cn(
          "mt-0.5 flex-shrink-0 w-2 h-2 rounded-full",
          isPassed ? "bg-emerald-500" : "bg-red-500"
        )}
      />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-white">{result.test}</p>
        <p className="text-xs text-gray-400 mt-0.5">{result.message}</p>
      </div>
      <span className="text-xs text-gray-500 whitespace-nowrap flex-shrink-0">
        {result.duration_ms.toFixed(0)}ms
      </span>
    </div>
  );
}

// ─── Error row ────────────────────────────────────────────────────────────────

function ErrorRow({
  error,
  expanded,
  onToggle,
}: {
  error: SystemErrorEntry;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="border-b border-[#1a2a3d] last:border-0">
      <button
        onClick={onToggle}
        className="w-full flex items-start gap-3 px-4 py-3 text-left hover:bg-white/5 transition-colors"
        aria-expanded={expanded}
      >
        <span className="mt-1 flex-shrink-0 w-2 h-2 rounded-full bg-red-500" />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-white truncate">{error.message}</p>
          <p className="text-xs text-gray-500 mt-0.5">
            {error.endpoint} &middot; {error.event_type}
          </p>
        </div>
        <span className="text-xs text-gray-500 whitespace-nowrap flex-shrink-0">
          {formatTimestamp(error.timestamp)}
        </span>
      </button>
      {expanded && (
        <div className="px-4 pb-3">
          <pre className="text-xs text-gray-400 bg-[#080f18] rounded-lg p-3 overflow-x-auto whitespace-pre-wrap break-all">
            {JSON.stringify(error.details, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function SystemHealthPage() {
  const [health, setHealth] = useState<SystemHealthReport | null>(null);
  const [errors, setErrors] = useState<SystemErrorEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [expandedErrors, setExpandedErrors] = useState<Set<number>>(new Set());
  const [selfTestResult, setSelfTestResult] = useState<SelfTestResponse | null>(null);
  const [selfTestRunning, setSelfTestRunning] = useState(false);
  const [selfTestError, setSelfTestError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    setFetchError(null);
    const [healthResult, errorsResult] = await Promise.allSettled([
      getSystemHealth(),
      getSystemErrors(20),
    ]);

    if (healthResult.status === "fulfilled") {
      setHealth(healthResult.value);
    } else {
      // Health fetch failed — surface the error so the error panel renders.
      const reason = healthResult.reason;
      const msg =
        reason instanceof Error
          ? reason.message
          : "Failed to fetch system health";
      setFetchError(msg);
    }

    if (errorsResult.status === "fulfilled") {
      // errors field may be absent on some backend versions — default to [].
      setErrors(errorsResult.value.errors ?? []);
    }
    // Silently ignore errors fetch failure — the health panel is more critical.

    setLastRefreshed(new Date());
    setIsLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  usePolling(refresh, 30_000);

  async function handleSelfTest() {
    setSelfTestRunning(true);
    setSelfTestError(null);
    setSelfTestResult(null);
    try {
      const result = await runSystemSelfTest();
      setSelfTestResult(result);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Self-test failed";
      setSelfTestError(msg);
    } finally {
      setSelfTestRunning(false);
    }
  }

  function toggleError(idx: number) {
    setExpandedErrors((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) {
        next.delete(idx);
      } else {
        next.add(idx);
      }
      return next;
    });
  }

  // ── Loading skeleton ───────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="p-4 space-y-6 max-w-3xl mx-auto">
        <SkeletonBlock h="h-14" />
        <div className="grid grid-cols-2 gap-3">
          <SkeletonBlock />
          <SkeletonBlock />
          <SkeletonBlock />
          <SkeletonBlock />
        </div>
        <SkeletonBlock h="h-48" />
        <SkeletonBlock h="h-32" />
      </div>
    );
  }

  // ── Fetch error state ──────────────────────────────────────────────────
  if (fetchError && !health) {
    return (
      <div className="p-4 max-w-3xl mx-auto">
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-6 text-center">
          <p className="text-red-400 font-medium text-sm">Failed to load system health</p>
          <p className="text-gray-500 text-xs mt-2">{fetchError}</p>
          <button
            onClick={() => void refresh()}
            className="mt-4 px-4 py-2 bg-[#1a2a3d] text-white text-sm rounded-lg hover:bg-[#243548] transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const overallStatus: SystemStatus = health?.status ?? "critical";
  const components = health?.components;
  const metrics = health?.metrics;
  const selfHealing = health?.self_healing;

  return (
    <div className="p-4 space-y-6 max-w-3xl mx-auto">

      {/* ── Overall status banner ────────────────────────────────────── */}
      <div
        className={cn(
          "flex items-center justify-between gap-3 px-4 py-3 rounded-xl border text-sm font-medium",
          overallBannerClass(overallStatus)
        )}
      >
        <div className="flex items-center gap-3">
          <StatusDot
            color={statusColor(overallStatus)}
            pulse={overallStatus === "healthy"}
          />
          <span className="capitalize">System {overallStatus}</span>
          {health && (
            <span className="text-xs opacity-70 font-normal">
              &mdash; up {formatUptime(health.uptime_seconds)}
            </span>
          )}
        </div>
        {lastRefreshed && (
          <span className="text-xs opacity-60 hidden sm:block">
            Refreshed {lastRefreshed.toLocaleTimeString()}
          </span>
        )}
      </div>

      {/* ── Platform metrics row ─────────────────────────────────────── */}
      {metrics && (
        <Section title="Platform Metrics">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {[
              { label: "Total Agents", value: metrics.total_agents.toLocaleString() },
              { label: "Total Sessions", value: metrics.total_sessions.toLocaleString() },
              { label: "Total Messages", value: metrics.total_messages.toLocaleString() },
              { label: "Active (24h)", value: metrics.active_sessions_24h.toLocaleString() },
              {
                label: "Error Rate (1h)",
                value: `${(metrics.error_rate_1h * 100).toFixed(2)}%`,
              },
              {
                label: "Avg Response",
                value: metrics.avg_response_time_ms !== null
                  ? `${metrics.avg_response_time_ms}ms`
                  : "N/A",
              },
            ].map(({ label, value }) => (
              <div
                key={label}
                className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl px-3 py-2.5 flex flex-col gap-1"
              >
                <span className="text-xs text-gray-500">{label}</span>
                <span className="text-sm font-bold text-white tabular-nums">{value}</span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* ── Database ─────────────────────────────────────────────────── */}
      {components?.database && (
        <Section title="Database">
          <ComponentCard title="SQLite" status={components.database.status}>
            {components.database.latency_ms !== null && (
              <MetricRow
                label="Query latency"
                value={`${components.database.latency_ms}ms`}
              />
            )}
          </ComponentCard>
        </Section>
      )}

      {/* ── LLM Providers ────────────────────────────────────────────── */}
      {components?.llm_providers && (
        <Section title="LLM Providers">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {Object.entries(components.llm_providers).map(([name, info]) => (
              <ComponentCard
                key={name}
                title={name.charAt(0).toUpperCase() + name.slice(1)}
                status={info.configured ? info.status : "unavailable"}
              >
                {info.reason && (
                  <p className="text-xs text-gray-500 mt-1">{info.reason}</p>
                )}
                {info.error_rate_1h !== null && info.error_rate_1h !== undefined && (
                  <MetricRow
                    label="Error rate (1h)"
                    value={`${(info.error_rate_1h * 100).toFixed(2)}%`}
                  />
                )}
              </ComponentCard>
            ))}
          </div>
        </Section>
      )}

      {/* ── Integrations ─────────────────────────────────────────────── */}
      {components?.integrations && (
        <Section title="Integrations">
          <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl divide-y divide-[#1a2a3d]">
            {Object.entries(components.integrations).map(([name, info]) => (
              <div key={name} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-sm text-white capitalize">{name}</p>
                  {info.last_webhook && (
                    <p className="text-xs text-gray-500 mt-0.5">
                      Last webhook: {formatTimestamp(info.last_webhook)}
                    </p>
                  )}
                </div>
                <StatusDot
                  color={statusColor(info.status)}
                  label={info.status.toUpperCase()}
                />
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* ── Security layers ───────────────────────────────────────────── */}
      {components?.security && (
        <Section title="Security">
          <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl divide-y divide-[#1a2a3d]">
            {Object.entries(components.security).map(([key, value]) => (
              <div key={key} className="flex items-center justify-between px-4 py-2.5">
                <span className="text-sm text-gray-300 capitalize">
                  {key.replace(/_/g, " ")}
                </span>
                <StatusDot color={statusColor(value)} label={value.toUpperCase()} />
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* ── Self-healing ──────────────────────────────────────────────── */}
      {selfHealing && (
        <Section title="Self-Healing">
          <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4 space-y-4">
            {/* Circuit breakers */}
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">
                Circuit Breakers
              </p>
              <div className="grid grid-cols-2 gap-2">
                {Object.entries(selfHealing.circuit_breakers ?? {}).map(([name, state]) => (
                  <div
                    key={name}
                    className="flex items-center justify-between bg-[#080f18] rounded-lg px-3 py-2"
                  >
                    <span className="text-xs text-gray-400 capitalize">{name}</span>
                    <StatusDot color={statusColor(state)} label={state} />
                  </div>
                ))}
              </div>
            </div>

            {/* Auto-recovery log */}
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">
                Auto-Recovery Log
              </p>
              {(selfHealing.auto_recovered ?? []).length === 0 ? (
                <p className="text-xs text-gray-600 italic">No auto-recovery events.</p>
              ) : (
                <div className="space-y-2">
                  {(selfHealing.auto_recovered ?? []).map((rec, idx) => (
                    <div key={idx} className="bg-[#080f18] rounded-lg px-3 py-2">
                      <p className="text-xs text-emerald-400 font-medium">{rec.issue}</p>
                      <p className="text-xs text-gray-400 mt-0.5">{rec.action}</p>
                      <p className="text-xs text-gray-600 mt-0.5">
                        {formatTimestamp(rec.timestamp)}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </Section>
      )}

      {/* ── Recent errors ─────────────────────────────────────────────── */}
      <Section title="Recent Errors">
        <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl overflow-hidden">
          {errors.length === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-gray-500">
              No recent errors
            </div>
          ) : (
            errors.map((error, idx) => (
              <ErrorRow
                key={idx}
                error={error}
                expanded={expandedErrors.has(idx)}
                onToggle={() => toggleError(idx)}
              />
            ))
          )}
        </div>
      </Section>

      {/* ── Self-test ─────────────────────────────────────────────────── */}
      <Section title="Integration Self-Test">
        <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4">
          <div className="flex items-center justify-between mb-4">
            <div>
              <p className="text-sm text-white font-medium">Run Self-Test</p>
              <p className="text-xs text-gray-500 mt-0.5">
                Verifies DB, tables, LLM providers, Stripe, routes, and security layers.
              </p>
            </div>
            <button
              onClick={() => void handleSelfTest()}
              disabled={selfTestRunning}
              className={cn(
                "px-4 py-2 rounded-lg text-sm font-medium transition-colors min-w-[100px]",
                selfTestRunning
                  ? "bg-[#1a2a3d] text-gray-500 cursor-not-allowed"
                  : "bg-[var(--gold-400)]/20 text-[var(--gold-400)] border border-[var(--gold-400)]/30 hover:bg-[var(--gold-400)]/30"
              )}
            >
              {selfTestRunning ? "Running..." : "Run Test"}
            </button>
          </div>

          {selfTestError && (
            <div className="mb-4 px-3 py-2 bg-red-500/10 border border-red-500/20 rounded-lg text-xs text-red-400">
              {selfTestError}
            </div>
          )}

          {selfTestResult && (
            <div>
              {/* Summary banner */}
              <div
                className={cn(
                  "flex items-center justify-between px-3 py-2 rounded-lg mb-3 text-sm font-medium",
                  selfTestResult.overall === "pass"
                    ? "bg-emerald-500/10 text-emerald-400"
                    : "bg-red-500/10 text-red-400"
                )}
              >
                <span>
                  {selfTestResult.overall === "pass" ? "All tests passed" : "Some tests failed"}
                </span>
                <span className="text-xs opacity-80">
                  {selfTestResult.passed}/{selfTestResult.total} passed &mdash;{" "}
                  {formatTimestamp(selfTestResult.ran_at)}
                </span>
              </div>

              {/* Per-test results */}
              <div className="divide-y divide-[#1a2a3d]">
                {(selfTestResult.results ?? []).map((r) => (
                  <SelfTestRow key={r.test} result={r} />
                ))}
              </div>
            </div>
          )}
        </div>
      </Section>

    </div>
  );
}
