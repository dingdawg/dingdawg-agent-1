"use client";

/**
 * Marketing Command Center — admin page for campaign management.
 *
 * - Campaign summary KPI cards (total, emails sent, open rate)
 * - Email delivery stats (delivery rate, open rate, click rate, bounce rate)
 * - Campaign table with status badges
 * - Deploy Marketing Agent CTA
 * - Polls every 120s (marketing data changes slowly)
 * - Empty states for all zero-data scenarios
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  Mail,
  BarChart2,
  MousePointerClick,
  AlertCircle,
  RefreshCw,
  Megaphone,
  Rocket,
  CheckCircle2,
  Loader2,
  TrendingUp,
  Send,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  getCampaigns,
  getEmailStats,
  deployMarketingAgent,
  type Campaign,
  type CampaignStatus,
  type EmailStats,
} from "@/services/api/adminService";

const POLL_INTERVAL_MS = 120_000; // 2 minutes

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatPct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

// ─── Status badge ─────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<CampaignStatus, string> = {
  draft: "bg-gray-500/15 text-gray-400 border-gray-500/20",
  active: "bg-green-500/15 text-green-400 border-green-500/20",
  completed: "bg-blue-500/15 text-blue-400 border-blue-500/20",
  failed: "bg-red-500/15 text-red-400 border-red-500/20",
};

function StatusBadge({ status }: { status: CampaignStatus }) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium border",
        STATUS_STYLES[status]
      )}
    >
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cn("animate-pulse rounded-lg bg-white/5", className)} />
  );
}

// ─── KPI Card ─────────────────────────────────────────────────────────────────

interface KpiProps {
  label: string;
  value: string | number;
  sub?: string;
  icon: React.ComponentType<{ className?: string }>;
  accent?: boolean;
}

function KpiCard({ label, value, sub, icon: Icon, accent }: KpiProps) {
  return (
    <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-5 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-400 font-medium">{label}</span>
        <div
          className={cn(
            "h-8 w-8 rounded-lg flex items-center justify-center",
            accent ? "bg-[var(--gold-500)]/15" : "bg-white/5"
          )}
        >
          <Icon
            className={cn(
              "h-4 w-4",
              accent ? "text-[var(--gold-500)]" : "text-gray-400"
            )}
          />
        </div>
      </div>
      <p className="text-2xl font-bold text-white leading-none">{value}</p>
      {sub && <p className="text-xs text-gray-500">{sub}</p>}
    </div>
  );
}

// ─── Stat bar ─────────────────────────────────────────────────────────────────

interface StatBarProps {
  label: string;
  value: number;
  color: string;
}

function StatBar({ label, value, color }: StatBarProps) {
  const pct = Math.min(Math.round(value * 100), 100);
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-400">{label}</span>
        <span className="font-semibold text-white">{pct}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-white/8 overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all duration-500", color)}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ─── Campaign table ───────────────────────────────────────────────────────────

function CampaignTable({ campaigns }: { campaigns: Campaign[] }) {
  if (campaigns.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-10 gap-3">
        <Megaphone className="h-10 w-10 text-gray-600" />
        <p className="text-sm text-gray-400 font-medium">No campaigns yet</p>
        <p className="text-xs text-gray-600 text-center max-w-xs">
          Use the marketing agent to launch your first campaign
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto -mx-1">
      <table className="w-full text-sm min-w-[580px]">
        <thead>
          <tr className="border-b border-[#1a2a3d]">
            {["Name", "Channel", "Status", "Reach", "Opens", "Clicks", "Date"].map(
              (h) => (
                <th
                  key={h}
                  className="text-left text-xs text-gray-500 font-medium py-2 px-2 first:pl-0 last:pr-0"
                >
                  {h}
                </th>
              )
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-[#1a2a3d]">
          {campaigns.map((c) => (
            <tr key={c.id} className="hover:bg-white/2 transition-colors">
              <td className="py-3 px-2 pl-0 font-medium text-white truncate max-w-[160px]">
                {c.name}
              </td>
              <td className="py-3 px-2 text-gray-400 capitalize">{c.channel}</td>
              <td className="py-3 px-2">
                <StatusBadge status={c.status} />
              </td>
              <td className="py-3 px-2 text-gray-300">{formatNumber(c.reach)}</td>
              <td className="py-3 px-2 text-gray-300">{formatNumber(c.opens)}</td>
              <td className="py-3 px-2 text-gray-300">{formatNumber(c.clicks)}</td>
              <td className="py-3 px-2 pr-0 text-gray-500 text-xs">
                {formatDate(c.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Main page content ────────────────────────────────────────────────────────

function MarketingContent() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [emailStats, setEmailStats] = useState<EmailStats | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isDeploying, setIsDeploying] = useState(false);
  const [deployResult, setDeployResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [camps, stats] = await Promise.allSettled([
        getCampaigns(),
        getEmailStats(),
      ]);
      if (camps.status === "fulfilled") setCampaigns(camps.value);
      if (stats.status === "fulfilled") setEmailStats(stats.value);
      if (camps.status === "rejected" && stats.status === "rejected") {
        const err = camps.reason as { response?: { data?: { detail?: string } } };
        setError(err?.response?.data?.detail ?? "Failed to load marketing data");
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Initial load + polling
  useEffect(() => {
    void loadData();
    intervalRef.current = setInterval(() => void loadData(), POLL_INTERVAL_MS);
    return () => {
      if (intervalRef.current !== null) clearInterval(intervalRef.current);
    };
  }, [loadData]);

  const handleDeploy = useCallback(async () => {
    setIsDeploying(true);
    setDeployResult(null);
    try {
      const result = await deployMarketingAgent();
      // deployMarketingAgent returns MarketingAgentStatus shape from existing service
      setDeployResult({
        success: true,
        message: result.deployed
          ? `Marketing agent deployed${result.handle ? ` as @${result.handle}` : ""}`
          : "Deploy request submitted",
      });
      void loadData(); // refresh data after deploy
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "Deploy failed — try again";
      setDeployResult({ success: false, message: msg });
    } finally {
      setIsDeploying(false);
    }
  }, [loadData]);

  // Derived summary stats
  const totalCampaigns = campaigns.length;
  const emailsSent = emailStats?.emails_sent ?? 0;
  const openRate = emailStats?.open_rate ?? 0;

  return (
    <div className="h-full overflow-y-auto scrollbar-thin px-4 pt-5 pb-20 lg:pb-8 max-w-4xl mx-auto">
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-lg font-bold text-white">Marketing</h1>
          <p className="text-xs text-gray-400 mt-0.5">Campaign management and email stats</p>
        </div>
        <button
          onClick={() => void loadData()}
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
            onClick={() => void loadData()}
            className="ml-auto text-xs underline"
          >
            retry
          </button>
        </div>
      )}

      {/* ── Campaign summary KPI cards ─────────────────────────────── */}
      {isLoading && !emailStats ? (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-5">
          {[0, 1, 2].map((i) => (
            <div key={i} className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-5 flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-8 w-8 rounded-lg" />
              </div>
              <Skeleton className="h-7 w-16" />
              <Skeleton className="h-3 w-12" />
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-5">
          <KpiCard
            label="Total Campaigns"
            value={totalCampaigns}
            sub="All time"
            icon={Megaphone}
            accent
          />
          <KpiCard
            label="Emails Sent"
            value={formatNumber(emailsSent)}
            sub={emailStats?.period ?? "This period"}
            icon={Send}
          />
          <KpiCard
            label="Open Rate"
            value={formatPct(openRate)}
            sub="Average across campaigns"
            icon={TrendingUp}
            accent
          />
        </div>
      )}

      {/* ── Email delivery stats ────────────────────────────────────── */}
      <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-5 mb-4">
        <div className="flex items-center gap-2 mb-4">
          <Mail className="h-4 w-4 text-[var(--gold-500)]" />
          <h2 className="text-sm font-semibold text-white">Email Delivery Stats</h2>
        </div>

        {isLoading && !emailStats ? (
          <div className="flex flex-col gap-3">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex flex-col gap-1.5">
                <div className="flex justify-between">
                  <Skeleton className="h-3 w-20" />
                  <Skeleton className="h-3 w-8" />
                </div>
                <Skeleton className="h-1.5 w-full" />
              </div>
            ))}
          </div>
        ) : emailStats ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4">
            <StatBar
              label="Delivery Rate"
              value={emailStats.delivery_rate}
              color="bg-green-500"
            />
            <StatBar
              label="Open Rate"
              value={emailStats.open_rate}
              color="bg-[var(--gold-500)]"
            />
            <StatBar
              label="Click Rate"
              value={emailStats.click_rate}
              color="bg-blue-500"
            />
            <StatBar
              label="Bounce Rate"
              value={emailStats.bounce_rate}
              color="bg-red-500"
            />
          </div>
        ) : (
          <div className="flex items-center gap-2 py-4 text-sm text-gray-500">
            <BarChart2 className="h-4 w-4" />
            No email stats available yet
          </div>
        )}
      </div>

      {/* ── Campaign table ──────────────────────────────────────────── */}
      <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-5 mb-4">
        <div className="flex items-center gap-2 mb-4">
          <MousePointerClick className="h-4 w-4 text-[var(--gold-500)]" />
          <h2 className="text-sm font-semibold text-white">Campaigns</h2>
          {campaigns.length > 0 && (
            <span className="ml-auto text-xs text-gray-500">
              {campaigns.length} total
            </span>
          )}
        </div>
        {isLoading && campaigns.length === 0 ? (
          <div className="flex flex-col gap-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="flex items-center gap-3">
                <Skeleton className="flex-1 h-4" />
                <Skeleton className="w-16 h-4" />
                <Skeleton className="w-16 h-5 rounded-md" />
                <Skeleton className="w-10 h-4" />
              </div>
            ))}
          </div>
        ) : (
          <CampaignTable campaigns={campaigns} />
        )}
      </div>

      {/* ── Deploy Marketing Agent CTA ──────────────────────────────── */}
      <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-5">
        <div className="flex items-start gap-4">
          <div className="h-10 w-10 rounded-xl bg-[var(--gold-500)]/10 flex items-center justify-center flex-shrink-0">
            <Rocket className="h-5 w-5 text-[var(--gold-500)]" />
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-sm font-semibold text-white mb-1">
              Deploy Marketing Agent
            </h2>
            <p className="text-xs text-gray-400 mb-3">
              Launch the @dingdawg-marketing agent to automate campaigns, email sequences, and outreach.
            </p>

            {deployResult && (
              <div
                className={cn(
                  "mb-3 flex items-center gap-2 text-xs p-2.5 rounded-lg",
                  deployResult.success
                    ? "bg-green-500/10 border border-green-500/20 text-green-400"
                    : "bg-red-500/10 border border-red-500/20 text-red-400"
                )}
              >
                {deployResult.success ? (
                  <CheckCircle2 className="h-3.5 w-3.5 flex-shrink-0" />
                ) : (
                  <AlertCircle className="h-3.5 w-3.5 flex-shrink-0" />
                )}
                {deployResult.message}
              </div>
            )}

            <button
              onClick={() => void handleDeploy()}
              disabled={isDeploying}
              className={cn(
                "flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-colors",
                "bg-[var(--gold-500)] text-[#07111c]",
                "hover:bg-[var(--gold-600)]",
                "disabled:opacity-50 disabled:cursor-not-allowed",
                "min-h-[44px]"
              )}
            >
              {isDeploying ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Rocket className="h-4 w-4" />
              )}
              {isDeploying ? "Deploying..." : "Deploy Marketing Agent"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Page export ──────────────────────────────────────────────────────────────

export default function MarketingAdminPage() {
  return <MarketingContent />;
}
