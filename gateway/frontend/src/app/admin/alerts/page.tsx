"use client";

/**
 * Alert Management Center — admin page for system alert monitoring.
 *
 * - Scrollable alert feed sorted newest-first
 * - Filter tabs: All / Critical / Warning / Info with unread counts
 * - Each alert: severity badge, title, description, source, timestamp, acknowledge button
 * - Collapsible alert configuration panel with threshold controls
 * - Alert statistics summary
 * - Polls every 15s (alerts need near-real-time)
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  Bell,
  BellOff,
  AlertTriangle,
  Info,
  XCircle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  AlertCircle,
  Shield,
  CreditCard,
  Settings2,
  Plug,
  Activity,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  configureAlerts,
  type Alert,
  type AlertSeverity,
  type AlertSource,
  type AlertConfig,
} from "@/services/api/adminService";
import { useAdminAlertsStore, type AlertFilter } from "@/store/adminAlertsStore";

const POLL_INTERVAL_MS = 15_000;

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatRelativeTime(timestamp: string): string {
  const now = Date.now();
  const then = new Date(timestamp).getTime();
  const diff = now - then;
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// ─── Severity badge ───────────────────────────────────────────────────────────

const SEVERITY_CONFIG: Record<
  AlertSeverity,
  { label: string; classes: string; icon: React.ComponentType<{ className?: string }> }
> = {
  critical: {
    label: "CRITICAL",
    classes: "bg-red-500/15 text-red-400 border-red-500/25",
    icon: XCircle,
  },
  warning: {
    label: "WARNING",
    classes: "bg-yellow-500/15 text-yellow-400 border-yellow-500/25",
    icon: AlertTriangle,
  },
  info: {
    label: "INFO",
    classes: "bg-blue-500/15 text-blue-400 border-blue-500/25",
    icon: Info,
  },
};

function AlertBadge({ severity }: { severity: AlertSeverity }) {
  const config = SEVERITY_CONFIG[severity];
  const Icon = config.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold border tracking-wide",
        config.classes
      )}
    >
      <Icon className="h-2.5 w-2.5" />
      {config.label}
    </span>
  );
}

// ─── Source icon ──────────────────────────────────────────────────────────────

const SOURCE_ICONS: Record<AlertSource, React.ComponentType<{ className?: string }>> = {
  system: Activity,
  payment: CreditCard,
  security: Shield,
  integration: Plug,
};

function SourceIcon({ source }: { source: AlertSource }) {
  const Icon = SOURCE_ICONS[source];
  return <Icon className="h-3.5 w-3.5 text-gray-500" />;
}

// ─── Alert card ───────────────────────────────────────────────────────────────

interface AlertCardProps {
  alert: Alert;
  onAcknowledge: (id: string) => void;
}

function AlertCard({ alert, onAcknowledge }: AlertCardProps) {
  return (
    <div
      className={cn(
        "bg-[#0d1926] border rounded-xl p-4 flex gap-3 transition-opacity",
        alert.acknowledged
          ? "border-[#1a2a3d] opacity-50"
          : "border-[#1a2a3d]",
        alert.severity === "critical" && !alert.acknowledged
          ? "border-l-2 border-l-red-500"
          : ""
      )}
    >
      {/* Left: badge column */}
      <div className="flex-shrink-0 pt-0.5">
        <AlertBadge severity={alert.severity} />
      </div>

      {/* Center: content */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-white leading-tight truncate">
          {alert.title}
        </p>
        <p className="text-xs text-gray-400 mt-0.5 line-clamp-2">
          {alert.description}
        </p>
        <div className="flex items-center gap-2 mt-2">
          <SourceIcon source={alert.source} />
          <span className="text-[10px] text-gray-500 capitalize">{alert.source}</span>
          <span className="text-[10px] text-gray-600">
            {formatRelativeTime(alert.timestamp)}
          </span>
        </div>
      </div>

      {/* Right: acknowledge button */}
      <div className="flex-shrink-0 self-start pt-0.5">
        {alert.acknowledged ? (
          <span className="flex items-center gap-1 text-[10px] text-gray-600">
            <CheckCircle2 className="h-3 w-3" />
            Ack
          </span>
        ) : (
          <button
            onClick={() => onAcknowledge(alert.id)}
            className={cn(
              "flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium",
              "bg-white/5 text-gray-400 hover:bg-white/10 hover:text-white",
              "transition-colors min-h-[28px]"
            )}
            aria-label="Acknowledge alert"
          >
            <CheckCircle2 className="h-3 w-3" />
            Ack
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Alert config panel ───────────────────────────────────────────────────────

const DEFAULT_CONFIG: AlertConfig = {
  error_rate_threshold: 5,
  response_time_threshold_ms: 2000,
  failed_payment_alert: true,
  security_event_alert: true,
};

interface AlertConfigPanelProps {
  onSave: (config: AlertConfig) => Promise<void>;
}

function AlertConfigPanel({ onSave }: AlertConfigPanelProps) {
  const [config, setConfig] = useState<AlertConfig>(DEFAULT_CONFIG);
  const [isSaving, setIsSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);

  const handleSave = async () => {
    setIsSaving(true);
    setSaveResult(null);
    try {
      await onSave(config);
      setSaveResult({ success: true, message: "Configuration saved" });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Save failed";
      setSaveResult({ success: false, message: msg });
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <Settings2 className="h-4 w-4 text-[var(--gold-500)]" />
        <h2 className="text-sm font-semibold text-white">Alert Thresholds</h2>
      </div>

      <div className="flex flex-col gap-4">
        {/* Error rate threshold */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs text-gray-400">Error Rate Threshold</label>
            <span className="text-xs font-semibold text-white">
              {config.error_rate_threshold}%
            </span>
          </div>
          <input
            type="range"
            min={1}
            max={25}
            step={1}
            value={config.error_rate_threshold}
            onChange={(e) =>
              setConfig((prev) => ({
                ...prev,
                error_rate_threshold: Number(e.target.value),
              }))
            }
            className="w-full h-1.5 rounded-full appearance-none bg-white/10 accent-[var(--gold-500)] cursor-pointer"
          />
          <div className="flex justify-between text-[10px] text-gray-600 mt-0.5">
            <span>1%</span>
            <span>25%</span>
          </div>
        </div>

        {/* Response time threshold */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs text-gray-400">Response Time Threshold</label>
            <span className="text-xs font-semibold text-white">
              {config.response_time_threshold_ms}ms
            </span>
          </div>
          <input
            type="range"
            min={200}
            max={10000}
            step={100}
            value={config.response_time_threshold_ms}
            onChange={(e) =>
              setConfig((prev) => ({
                ...prev,
                response_time_threshold_ms: Number(e.target.value),
              }))
            }
            className="w-full h-1.5 rounded-full appearance-none bg-white/10 accent-[var(--gold-500)] cursor-pointer"
          />
          <div className="flex justify-between text-[10px] text-gray-600 mt-0.5">
            <span>200ms</span>
            <span>10s</span>
          </div>
        </div>

        {/* Toggle: failed payment alert */}
        <div className="flex items-center justify-between">
          <label className="text-xs text-gray-400">Failed Payment Alert</label>
          <button
            onClick={() =>
              setConfig((prev) => ({
                ...prev,
                failed_payment_alert: !prev.failed_payment_alert,
              }))
            }
            className={cn(
              "relative inline-flex h-5 w-9 items-center rounded-full transition-colors",
              config.failed_payment_alert ? "bg-[var(--gold-500)]" : "bg-white/15"
            )}
            role="switch"
            aria-checked={config.failed_payment_alert}
          >
            <span
              className={cn(
                "inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform",
                config.failed_payment_alert ? "translate-x-4" : "translate-x-0.5"
              )}
            />
          </button>
        </div>

        {/* Toggle: security event alert */}
        <div className="flex items-center justify-between">
          <label className="text-xs text-gray-400">Security Event Alert</label>
          <button
            onClick={() =>
              setConfig((prev) => ({
                ...prev,
                security_event_alert: !prev.security_event_alert,
              }))
            }
            className={cn(
              "relative inline-flex h-5 w-9 items-center rounded-full transition-colors",
              config.security_event_alert ? "bg-[var(--gold-500)]" : "bg-white/15"
            )}
            role="switch"
            aria-checked={config.security_event_alert}
          >
            <span
              className={cn(
                "inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform",
                config.security_event_alert ? "translate-x-4" : "translate-x-0.5"
              )}
            />
          </button>
        </div>
      </div>

      {saveResult && (
        <div
          className={cn(
            "mt-3 flex items-center gap-2 text-xs p-2.5 rounded-lg",
            saveResult.success
              ? "bg-green-500/10 border border-green-500/20 text-green-400"
              : "bg-red-500/10 border border-red-500/20 text-red-400"
          )}
        >
          {saveResult.success ? (
            <CheckCircle2 className="h-3.5 w-3.5 flex-shrink-0" />
          ) : (
            <AlertCircle className="h-3.5 w-3.5 flex-shrink-0" />
          )}
          {saveResult.message}
        </div>
      )}

      <button
        onClick={() => void handleSave()}
        disabled={isSaving}
        className={cn(
          "mt-4 w-full flex items-center justify-center gap-2",
          "px-4 py-2.5 rounded-xl text-sm font-semibold transition-colors",
          "bg-[var(--gold-500)] text-[#07111c] hover:bg-[var(--gold-600)]",
          "disabled:opacity-50 disabled:cursor-not-allowed min-h-[44px]"
        )}
      >
        {isSaving ? (
          <>
            <RefreshCw className="h-4 w-4 animate-spin" />
            Saving...
          </>
        ) : (
          "Save Configuration"
        )}
      </button>
    </div>
  );
}

// ─── Filter tabs ──────────────────────────────────────────────────────────────

const FILTER_TABS: Array<{ key: AlertFilter; label: string }> = [
  { key: "all", label: "All" },
  { key: "critical", label: "Critical" },
  { key: "warning", label: "Warning" },
  { key: "info", label: "Info" },
];

interface FilterTabsProps {
  activeFilter: AlertFilter;
  alerts: Alert[];
  onFilterChange: (filter: AlertFilter) => void;
}

function FilterTabs({ activeFilter, alerts, onFilterChange }: FilterTabsProps) {
  function countUnread(severity?: AlertSeverity): number {
    return alerts.filter(
      (a) =>
        !a.acknowledged &&
        (severity === undefined || a.severity === severity)
    ).length;
  }

  return (
    <div className="flex gap-1 overflow-x-auto pb-1 scrollbar-none">
      {FILTER_TABS.map(({ key, label }) => {
        const unread =
          key === "all" ? countUnread() : countUnread(key as AlertSeverity);
        const isActive = activeFilter === key;
        return (
          <button
            key={key}
            onClick={() => onFilterChange(key)}
            className={cn(
              "flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors min-h-[36px]",
              isActive
                ? "bg-[var(--gold-500)]/15 text-[var(--gold-500)] border border-[var(--gold-500)]/25"
                : "text-gray-400 hover:text-white hover:bg-white/5"
            )}
          >
            {label}
            {unread > 0 && (
              <span
                className={cn(
                  "inline-flex items-center justify-center h-4 min-w-[16px] px-1 rounded-full text-[9px] font-bold",
                  isActive
                    ? "bg-[var(--gold-500)] text-[#07111c]"
                    : "bg-white/10 text-gray-300"
                )}
              >
                {unread}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

// ─── Alert statistics ─────────────────────────────────────────────────────────

function AlertStats({ alerts }: { alerts: Alert[] }) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const todayAlerts = alerts.filter(
    (a) => new Date(a.timestamp) >= today
  );
  const criticalCount = todayAlerts.filter((a) => a.severity === "critical").length;

  // Most common source
  const sourceCounts = alerts.reduce<Record<string, number>>((acc, a) => {
    acc[a.source] = (acc[a.source] ?? 0) + 1;
    return acc;
  }, {});
  const topSource =
    Object.entries(sourceCounts).sort(([, a], [, b]) => b - a)[0]?.[0] ?? "—";

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
      {[
        { label: "Alerts Today", value: todayAlerts.length },
        { label: "Critical", value: criticalCount },
        { label: "Unread", value: alerts.filter((a) => !a.acknowledged).length },
        { label: "Top Source", value: topSource },
      ].map(({ label, value }) => (
        <div
          key={label}
          className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-3 flex flex-col gap-1"
        >
          <p className="text-xs text-gray-500">{label}</p>
          <p className="text-lg font-bold text-white capitalize">{value}</p>
        </div>
      ))}
    </div>
  );
}

// ─── Main page content ────────────────────────────────────────────────────────

function AlertsContent() {
  const { alerts, filter, unreadCount, isLoading, error, fetchAlerts, setFilter, acknowledgeAlert } =
    useAdminAlertsStore();
  const [configOpen, setConfigOpen] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Initial load + polling
  useEffect(() => {
    void fetchAlerts();
    intervalRef.current = setInterval(() => void fetchAlerts(), POLL_INTERVAL_MS);
    return () => {
      if (intervalRef.current !== null) clearInterval(intervalRef.current);
    };
  }, [fetchAlerts]);

  const handleSaveConfig = useCallback(async (config: AlertConfig) => {
    await configureAlerts(config);
  }, []);

  // Filtered alerts
  const filteredAlerts =
    filter === "all"
      ? alerts
      : alerts.filter((a) => a.severity === filter);

  return (
    <div className="h-full overflow-y-auto scrollbar-thin px-4 pt-5 pb-20 lg:pb-8 max-w-3xl mx-auto">
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2.5">
          <div className="relative">
            <Bell className="h-5 w-5 text-[var(--gold-500)]" />
            {unreadCount > 0 && (
              <span className="absolute -top-1 -right-1 h-3.5 w-3.5 rounded-full bg-red-500 text-[8px] font-bold text-white flex items-center justify-center">
                {unreadCount > 9 ? "9+" : unreadCount}
              </span>
            )}
          </div>
          <div>
            <h1 className="text-lg font-bold text-white">Alerts</h1>
            <p className="text-xs text-gray-400">System event monitoring</p>
          </div>
        </div>
        <button
          onClick={() => void fetchAlerts()}
          disabled={isLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-white hover:bg-white/5 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", isLoading && "animate-spin")} />
          Refresh
        </button>
      </div>

      {/* ── Error ──────────────────────────────────────────────────── */}
      {error && (
        <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2">
          <AlertCircle className="h-4 w-4 flex-shrink-0" />
          {error}
          <button
            onClick={() => void fetchAlerts()}
            className="ml-auto text-xs underline"
          >
            retry
          </button>
        </div>
      )}

      {/* ── Alert statistics ────────────────────────────────────────── */}
      <AlertStats alerts={alerts} />

      {/* ── Filter tabs ─────────────────────────────────────────────── */}
      <div className="mb-3">
        <FilterTabs
          activeFilter={filter}
          alerts={alerts}
          onFilterChange={setFilter}
        />
      </div>

      {/* ── Alert feed ──────────────────────────────────────────────── */}
      <div className="flex flex-col gap-2 mb-4">
        {isLoading && alerts.length === 0 ? (
          <>
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4 flex gap-3 animate-pulse"
              >
                <div className="flex-shrink-0 h-5 w-16 rounded-md bg-white/5" />
                <div className="flex-1 flex flex-col gap-2">
                  <div className="h-4 w-48 rounded bg-white/5" />
                  <div className="h-3 w-full rounded bg-white/5" />
                  <div className="h-3 w-24 rounded bg-white/5" />
                </div>
              </div>
            ))}
          </>
        ) : filteredAlerts.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 gap-3">
            <BellOff className="h-10 w-10 text-gray-600" />
            <p className="text-sm text-gray-400 font-medium">
              {filter === "all" ? "No alerts" : `No ${filter} alerts`}
            </p>
            <p className="text-xs text-gray-600">
              {filter === "all"
                ? "All systems are running normally"
                : "Try switching to a different filter"}
            </p>
          </div>
        ) : (
          filteredAlerts.map((alert) => (
            <AlertCard
              key={alert.id}
              alert={alert}
              onAcknowledge={acknowledgeAlert}
            />
          ))
        )}
      </div>

      {/* ── Alert config panel (collapsible) ────────────────────────── */}
      <div>
        <button
          onClick={() => setConfigOpen((prev) => !prev)}
          className="w-full flex items-center justify-between px-4 py-3 rounded-xl bg-[#0d1926] border border-[#1a2a3d] text-sm text-gray-300 hover:text-white transition-colors mb-2"
        >
          <div className="flex items-center gap-2">
            <Settings2 className="h-4 w-4 text-[var(--gold-500)]" />
            Alert Configuration
          </div>
          {configOpen ? (
            <ChevronUp className="h-4 w-4 text-gray-500" />
          ) : (
            <ChevronDown className="h-4 w-4 text-gray-500" />
          )}
        </button>

        {configOpen && <AlertConfigPanel onSave={handleSaveConfig} />}
      </div>
    </div>
  );
}

// ─── Page export ──────────────────────────────────────────────────────────────

export default function AlertsAdminPage() {
  return <AlertsContent />;
}
