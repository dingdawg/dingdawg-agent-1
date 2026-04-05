"use client";

/**
 * Integration Health Dashboard — admin page for monitoring all platform integrations.
 *
 * Features:
 *  - 6 integration cards: Google Calendar, SendGrid, Twilio, Stripe, Vapi, Slack
 *  - Each card: status dot, connected agents, webhook success rate bar, "Test" button
 *  - Webhook delivery bar chart (success/failure per integration)
 *  - Recent test results log
 *  - Polls every 60s
 */

import { useCallback, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import StatusDot from "@/components/admin/StatusDot";
import { usePolling } from "@/hooks/usePolling";
import * as adminService from "@/services/api/adminService";
import type {
  IntegrationHealth,
  IntegrationStatus,
  IntegrationTestResult,
} from "@/services/api/adminService";

// ─── Integration metadata (display names, icons) ──────────────────────────────

interface IntegrationMeta {
  key: string;
  name: string;
  icon: string;
  hasWebhook: boolean;
}

const INTEGRATION_META: IntegrationMeta[] = [
  { key: "google_calendar", name: "Google Calendar", icon: "📅", hasWebhook: false },
  { key: "sendgrid", name: "SendGrid", icon: "📧", hasWebhook: true },
  { key: "twilio", name: "Twilio", icon: "📱", hasWebhook: true },
  { key: "stripe", name: "Stripe", icon: "💳", hasWebhook: true },
  { key: "vapi", name: "Vapi (Voice)", icon: "🎙", hasWebhook: false },
  { key: "slack", name: "Slack", icon: "💬", hasWebhook: true },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function statusColor(s: IntegrationStatus): "green" | "red" | "gray" {
  if (s === "connected") return "green";
  if (s === "disconnected") return "red";
  return "gray";
}

function statusLabel(s: IntegrationStatus): string {
  if (s === "connected") return "Connected";
  if (s === "disconnected") return "Disconnected";
  return "Not Configured";
}

function formatTime(isoString: string | null): string {
  if (!isoString) return "Never";
  try {
    const d = new Date(isoString);
    return d.toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return isoString;
  }
}

// ─── Webhook success rate bar ─────────────────────────────────────────────────

function RateBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100);
  const color =
    pct >= 95 ? "bg-emerald-500" : pct >= 80 ? "bg-yellow-400" : "bg-red-500";
  return (
    <div className="mt-2">
      <div className="flex justify-between items-center mb-1">
        <span className="text-xs text-gray-500">Webhook success</span>
        <span
          className={`text-xs font-semibold ${
            pct >= 95
              ? "text-emerald-400"
              : pct >= 80
              ? "text-yellow-400"
              : "text-red-400"
          }`}
        >
          {pct}%
        </span>
      </div>
      <div className="h-1.5 bg-[#1a2a3d] rounded-full overflow-hidden">
        <div
          className={`h-full ${color} rounded-full transition-all duration-500`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ─── Integration card ─────────────────────────────────────────────────────────

function IntegrationCard({
  meta,
  health,
  onTest,
  testBusy,
}: {
  meta: IntegrationMeta;
  health: IntegrationHealth | undefined;
  onTest: (key: string) => void;
  testBusy: boolean;
}) {
  const status: IntegrationStatus = health?.status ?? "not_configured";

  return (
    <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xl leading-none" role="img" aria-label={meta.name}>
            {meta.icon}
          </span>
          <div>
            <p className="text-sm font-semibold text-white">{meta.name}</p>
            {health?.mode && (
              <span className="text-xs text-gray-500 capitalize">
                {health.mode} mode
              </span>
            )}
          </div>
        </div>
        <StatusDot color={statusColor(status)} label={statusLabel(status)} />
      </div>

      {/* Stats */}
      <div className="flex items-center gap-4 text-xs text-gray-400">
        <span>
          <span className="text-white font-semibold">
            {health?.connected_agents ?? 0}
          </span>{" "}
          agents
        </span>
        {health?.last_test_result && (
          <span>
            Last test:{" "}
            <span
              className={
                health.last_test_result === "pass"
                  ? "text-emerald-400"
                  : "text-red-400"
              }
            >
              {health.last_test_result}
            </span>
            {health.last_test_response_ms !== null && (
              <span className="text-gray-600 ml-1">
                ({health.last_test_response_ms}ms)
              </span>
            )}
          </span>
        )}
      </div>

      {/* Webhook rate bar */}
      {meta.hasWebhook && health?.webhook_success_rate !== null && health?.webhook_success_rate !== undefined && (
        <RateBar rate={health.webhook_success_rate} />
      )}

      {/* Footer */}
      <div className="flex items-center justify-between pt-1">
        <span className="text-xs text-gray-600">
          {health?.last_tested_at
            ? `Tested ${formatTime(health.last_tested_at)}`
            : "Not yet tested"}
        </span>
        <button
          onClick={() => onTest(meta.key)}
          disabled={testBusy || status === "not_configured"}
          className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#0a1520] border border-[#1a2a3d] text-gray-300 hover:border-[#F6B400] hover:text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed min-h-[32px]"
        >
          {testBusy ? "Testing..." : "Test"}
        </button>
      </div>
    </div>
  );
}

// ─── Test result row ──────────────────────────────────────────────────────────

function TestResultRow({ result }: { result: IntegrationTestResult }) {
  const meta = INTEGRATION_META.find((m) => m.key === result.key);
  return (
    <div className="flex items-center gap-3 py-2 border-b border-[#1a2a3d] last:border-0">
      <span className="text-base leading-none" role="img" aria-label={meta?.name ?? result.key}>
        {meta?.icon ?? "?"}
      </span>
      <span className="flex-1 text-sm text-gray-300">
        {meta?.name ?? result.key}
      </span>
      <span
        className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
          result.result === "pass"
            ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
            : "bg-red-500/10 text-red-400 border border-red-500/30"
        }`}
      >
        {result.result}
      </span>
      <span className="text-xs text-gray-600 tabular-nums w-14 text-right">
        {result.response_ms}ms
      </span>
      <span className="text-xs text-gray-500 whitespace-nowrap">
        {formatTime(result.tested_at)}
      </span>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function IntegrationsHealthPage() {
  const [integrations, setIntegrations] = useState<IntegrationHealth[]>([]);
  const [testResults, setTestResults] = useState<IntegrationTestResult[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [testBusy, setTestBusy] = useState<Record<string, boolean>>({});

  async function fetchHealth() {
    setFetchError(null);
    try {
      const data = await adminService.getIntegrationHealth();
      setIntegrations(data);
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "Failed to load integration health";
      setFetchError(msg);
    } finally {
      setIsLoading(false);
    }
  }

  const poll = useCallback(() => {
    void fetchHealth();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  usePolling(poll, 60_000);

  async function handleTest(key: string) {
    if (testBusy[key]) return;
    setTestBusy((prev) => ({ ...prev, [key]: true }));
    try {
      const result = await adminService.testIntegration(key);
      setTestResults((prev) => [result, ...prev].slice(0, 20));
      // Refresh integration list to pick up updated last_tested_at
      await fetchHealth();
    } catch {
      /* non-critical — test failure is shown in the log if we get a result */
    } finally {
      setTestBusy((prev) => ({ ...prev, [key]: false }));
    }
  }

  // ─── Webhook delivery chart data ────────────────────────────────────────────

  const chartData = INTEGRATION_META.filter((m) => m.hasWebhook).map((m) => {
    const h = integrations.find((i) => i.key === m.key);
    const rate = h?.webhook_success_rate ?? null;
    const success = rate !== null ? Math.round(rate * 100) : 0;
    const failure = rate !== null ? 100 - success : 0;
    return { name: m.name.split(" ")[0], success, failure };
  });

  return (
    <div className="min-h-screen bg-[var(--ink-950,#07111c)] p-4 md:p-6 space-y-6">
      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div>
        <h1 className="text-2xl font-bold font-heading text-white">
          Integration Health
        </h1>
        <p className="text-gray-400 text-sm mt-1">
          6 integrations monitored &mdash; refreshes every 60s
          {isLoading && (
            <span className="ml-2 text-xs text-[#F6B400]">Loading...</span>
          )}
        </p>
      </div>

      {fetchError && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3 text-red-400 text-sm">
          {fetchError}
        </div>
      )}

      {/* ── Integration cards ────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {INTEGRATION_META.map((meta) => {
          const health = integrations.find((i) => i.key === meta.key);
          return (
            <IntegrationCard
              key={meta.key}
              meta={meta}
              health={health}
              onTest={handleTest}
              testBusy={!!testBusy[meta.key]}
            />
          );
        })}

        {/* Loading skeletons */}
        {isLoading &&
          integrations.length === 0 &&
          INTEGRATION_META.map((m) => (
            <div
              key={m.key + "-skel"}
              className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4 h-40 animate-pulse"
            />
          ))}
      </div>

      {/* ── Webhook delivery chart ───────────────────────────────────────────── */}
      <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4">
        <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-4">
          Webhook Delivery Rates
        </h2>

        {chartData.every((d) => d.success === 0 && d.failure === 0) ? (
          <div className="h-48 flex items-center justify-center text-gray-500 text-sm">
            No webhook data available.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chartData} margin={{ top: 0, right: 8, bottom: 0, left: 0 }}>
              <XAxis
                dataKey="name"
                tickLine={false}
                axisLine={false}
                tick={{ fill: "#6b7280", fontSize: 11 }}
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                tick={{ fill: "#6b7280", fontSize: 11 }}
                tickFormatter={(v) => `${v}%`}
                domain={[0, 100]}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#0d1926",
                  border: "1px solid #1a2a3d",
                  borderRadius: "8px",
                  color: "#fff",
                }}
                formatter={(value, name) => [
                  `${typeof value === "number" ? value : 0}%`,
                  String(name ?? "") === "success" ? "Success" : "Failure",
                ]}
              />
              <Legend
                formatter={(value) => (
                  <span className="text-xs text-gray-400 capitalize">
                    {value}
                  </span>
                )}
              />
              <Bar dataKey="success" stackId="a" fill="#22c55e" radius={[0, 0, 0, 0]} />
              <Bar dataKey="failure" stackId="a" fill="#ef4444" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* ── Test results log ─────────────────────────────────────────────────── */}
      <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4">
        <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
          Recent Test Results
        </h2>

        {testResults.length === 0 ? (
          <div className="py-8 text-center text-gray-500 text-sm">
            No tests run yet. Click "Test" on any integration card above.
          </div>
        ) : (
          <div className="space-y-0">
            <div className="flex items-center gap-3 pb-2 border-b border-[#1a2a3d] text-xs text-gray-500">
              <span className="w-6" />
              <span className="flex-1">Integration</span>
              <span className="text-right">Result</span>
              <span className="w-14 text-right">Time</span>
              <span className="whitespace-nowrap">Tested At</span>
            </div>
            {testResults.map((result, idx) => (
              <TestResultRow key={`${result.key}-${idx}`} result={result} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
