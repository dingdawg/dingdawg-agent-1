"use client";

/**
 * Analytics page — performance overview for the active agent.
 *
 * - 4 KPI cards: Total Conversations, Total Messages, Avg Msgs/Conversation, Revenue
 * - Daily conversations bar chart (CSS bars, no library)
 * - Skill usage table with colored success-rate bars
 * - Recent conversations list with message count and duration
 * - Loading skeletons, error state, empty state
 * - Mobile responsive (single column on sm, 2-col on md+)
 * - Protected route + agent guard
 */

import { useEffect, useState, useCallback, Component, type ErrorInfo, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  BarChart3,
  MessageSquare,
  Zap,
  DollarSign,
  AlertCircle,
  RefreshCw,
  Clock,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAgentStore } from "@/store/agentStore";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { PageHeader } from "@/components/layout/PageHeader";
import {
  getDashboardAnalytics,
  getConversations,
  getSkillUsage,
  getRevenue,
  type DashboardAnalytics,
  type ConversationEntry,
  type SkillUsageEntry,
  type RevenueData,
} from "@/services/api/analyticsService";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function formatShortDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

// ─── Skeleton components ──────────────────────────────────────────────────────

function SkeletonBlock({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-lg bg-white/5",
        className
      )}
    />
  );
}

function KpiCardSkeleton() {
  return (
    <div className="glass-panel p-5 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <SkeletonBlock className="h-4 w-28" />
        <SkeletonBlock className="h-8 w-8 rounded-lg" />
      </div>
      <SkeletonBlock className="h-8 w-20" />
      <SkeletonBlock className="h-3 w-16" />
    </div>
  );
}

// ─── KPI Card ────────────────────────────────────────────────────────────────

interface KpiCardProps {
  label: string;
  value: string | number;
  sub?: string;
  icon: React.ComponentType<{ className?: string }>;
  accent?: boolean;
}

function KpiCard({ label, value, sub, icon: Icon, accent }: KpiCardProps) {
  return (
    <div className="glass-panel p-5 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-sm text-[var(--color-muted)] font-medium">
          {label}
        </span>
        <div
          className={cn(
            "h-8 w-8 rounded-lg flex items-center justify-center",
            accent
              ? "bg-[var(--gold-500)]/15"
              : "bg-white/5"
          )}
        >
          <Icon
            className={cn(
              "h-4 w-4",
              accent ? "text-[var(--gold-500)]" : "text-[var(--color-muted)]"
            )}
          />
        </div>
      </div>
      <p className="text-2xl font-bold text-[var(--foreground)] leading-none">
        {value}
      </p>
      {sub && (
        <p className="text-xs text-[var(--color-muted)]">{sub}</p>
      )}
    </div>
  );
}

// ─── Daily Conversations Chart ────────────────────────────────────────────────

function DailyConversationsChart({
  data,
}: {
  data: DashboardAnalytics["daily_conversations"];
}) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-sm text-[var(--color-muted)]">
        No conversation data yet
      </div>
    );
  }

  const maxCount = Math.max(...data.map((d) => d.count), 1);
  // Show last 14 entries at most to keep chart readable
  const visible = data.slice(-14);

  return (
    <div className="flex items-end gap-1.5 h-32 w-full">
      {visible.map((entry) => {
        const heightPct = Math.max((entry.count / maxCount) * 100, 4);
        return (
          <div
            key={entry.date}
            className="flex-1 flex flex-col items-center justify-end gap-1 group"
          >
            {/* Bar */}
            <div
              className="w-full rounded-t-sm bg-[var(--gold-500)]/40 hover:bg-[var(--gold-500)]/70 transition-colors cursor-default relative"
              style={{ height: `${heightPct}%` }}
            >
              {/* Tooltip */}
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-2 py-1 rounded-md bg-[var(--ink-800)] text-xs text-[var(--foreground)] whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-10 border border-[var(--stroke)] shadow-lg">
                {entry.count} conversation{entry.count !== 1 ? "s" : ""}
                <br />
                <span className="text-[var(--color-muted)]">
                  {formatShortDate(entry.date)}
                </span>
              </div>
            </div>
            {/* Label */}
            <span className="text-[9px] text-[var(--color-muted)] truncate w-full text-center">
              {formatShortDate(entry.date)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ─── Skill Usage Table ────────────────────────────────────────────────────────

function SkillUsageTable({ skills }: { skills: SkillUsageEntry[] }) {
  if (skills.length === 0) {
    return (
      <p className="text-sm text-[var(--color-muted)] py-4 text-center">
        No skill executions yet
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-0 divide-y divide-[var(--stroke)]">
      {skills.map((skill) => {
        const pct = Math.round(skill.success_rate * 100);
        const barColor =
          pct >= 80
            ? "bg-green-500"
            : pct >= 50
            ? "bg-yellow-500"
            : "bg-red-500";

        return (
          <div
            key={skill.skill_name}
            className="flex items-center gap-4 py-3 first:pt-0 last:pb-0"
          >
            {/* Skill name */}
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-[var(--foreground)] capitalize truncate">
                {skill.skill_name.replace(/_/g, " ")}
              </p>
              <p className="text-xs text-[var(--color-muted)]">
                {skill.total_executions} exec
                {skill.total_executions !== 1 ? "s" : ""} &middot;{" "}
                {skill.success_count} ok / {skill.failure_count} fail
              </p>
            </div>

            {/* Success rate bar + label */}
            <div className="flex items-center gap-2 flex-shrink-0 w-28">
              <div className="flex-1 h-1.5 rounded-full bg-white/10 overflow-hidden">
                <div
                  className={cn("h-full rounded-full", barColor)}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span
                className={cn(
                  "text-xs font-semibold w-8 text-right",
                  pct >= 80
                    ? "text-green-400"
                    : pct >= 50
                    ? "text-yellow-400"
                    : "text-red-400"
                )}
              >
                {pct}%
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Recent Conversations List ────────────────────────────────────────────────

function ConversationList({ conversations }: { conversations: ConversationEntry[] }) {
  if (conversations.length === 0) {
    return (
      <p className="text-sm text-[var(--color-muted)] py-4 text-center">
        No conversations yet
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-0 divide-y divide-[var(--stroke)]">
      {conversations.slice(0, 10).map((conv) => (
        <div
          key={conv.session_id}
          className="flex items-center gap-3 py-3 first:pt-0 last:pb-0"
        >
          <div className="h-7 w-7 rounded-lg bg-[var(--gold-500)]/10 flex items-center justify-center flex-shrink-0">
            <MessageSquare className="h-3.5 w-3.5 text-[var(--gold-500)]" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-[var(--foreground)] font-medium">
              {conv.message_count} message{conv.message_count !== 1 ? "s" : ""}
            </p>
            <p className="text-xs text-[var(--color-muted)]">
              {formatDate(conv.started_at)}
            </p>
          </div>
          <div className="flex items-center gap-1 text-xs text-[var(--color-muted)] flex-shrink-0">
            <Clock className="h-3 w-3" />
            {formatDuration(conv.duration_seconds)}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Error Boundary ───────────────────────────────────────────────────────────

class AnalyticsErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean; error: Error | null }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Analytics page error:", error, info);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-full gap-4 px-6 text-center">
          <p className="text-sm text-red-400">Failed to load analytics.</p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="text-xs underline text-[var(--color-muted)]"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// ─── Main page export ─────────────────────────────────────────────────────────

export default function AnalyticsPage() {
  return (
    <ProtectedRoute>
      <AppShell>
        <AnalyticsErrorBoundary>
          <AnalyticsContent />
        </AnalyticsErrorBoundary>
      </AppShell>
    </ProtectedRoute>
  );
}

// ─── Analytics Content ────────────────────────────────────────────────────────

function AnalyticsContent() {
  const router = useRouter();
  const { agents, currentAgent, isLoading: agentsLoading, fetchAgents } =
    useAgentStore();

  const [dashboard, setDashboard] = useState<DashboardAnalytics | null>(null);
  const [conversations, setConversations] = useState<ConversationEntry[]>([]);
  const [skills, setSkills] = useState<SkillUsageEntry[]>([]);
  const [revenue, setRevenue] = useState<RevenueData | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch agents on mount
  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  // Redirect to /claim if authenticated but no agents
  useEffect(() => {
    if (!agentsLoading && agents.length === 0) {
      router.replace("/claim");
    }
  }, [agentsLoading, agents.length, router]);

  // Load all analytics data for the active agent
  const loadAnalytics = useCallback(async () => {
    if (!currentAgent) return;
    setLoading(true);
    setError(null);

    try {
      const [dash, convs, skillData, rev] = await Promise.allSettled([
        getDashboardAnalytics(currentAgent.id),
        getConversations(currentAgent.id),
        getSkillUsage(currentAgent.id),
        getRevenue(currentAgent.id),
      ]);

      if (dash.status === "fulfilled") setDashboard(dash.value);
      if (convs.status === "fulfilled") setConversations(convs.value);
      if (skillData.status === "fulfilled") setSkills(skillData.value);
      if (rev.status === "fulfilled") setRevenue(rev.value);

      // Surface error only if the primary dashboard call failed
      if (dash.status === "rejected") {
        const detail =
          (dash.reason as { response?: { data?: { detail?: string } } })
            ?.response?.data?.detail ?? "Failed to load analytics";
        setError(detail);
      }
    } finally {
      setLoading(false);
    }
  }, [currentAgent]);

  useEffect(() => {
    loadAnalytics();
  }, [loadAnalytics]);

  // ── Loading state: agents still fetching ───────────────────────
  if (agentsLoading && agents.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="spinner text-[var(--gold-500)]" />
      </div>
    );
  }

  // ── No agent claimed yet ───────────────────────────────────────
  if (!currentAgent) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 px-6 text-center">
        <div className="h-14 w-14 rounded-2xl bg-[var(--gold-500)]/10 flex items-center justify-center">
          <BarChart3 className="h-7 w-7 text-[var(--gold-500)]" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-[var(--foreground)] mb-1">
            No agent yet
          </h2>
          <p className="text-sm text-[var(--color-muted)]">
            Claim an agent to start tracking analytics.
          </p>
        </div>
        <Link
          href="/claim"
          className="px-5 py-2.5 rounded-xl bg-[var(--gold-500)] text-[#07111c] text-sm font-semibold hover:bg-[var(--gold-600)] transition-colors"
        >
          Claim your agent
        </Link>
      </div>
    );
  }

  const hasAnyData =
    dashboard !== null ||
    conversations.length > 0 ||
    skills.length > 0 ||
    revenue !== null;

  // ── Empty state: agent exists but zero data ────────────────────
  const showEmpty = !loading && !error && !hasAnyData;

  return (
    <div className="h-full overflow-y-auto scrollbar-thin px-4 pt-6 pb-20 lg:pb-8 max-w-3xl mx-auto">
      {/* ── Back navigation ────────────────────────────────────── */}
      <PageHeader title="Analytics" />

      {/* ── Page header ────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-[var(--foreground)]">
            Analytics
          </h1>
          <p className="text-xs text-[var(--color-muted)] mt-0.5">
            @{currentAgent.handle}
          </p>
        </div>
        <button
          onClick={loadAnalytics}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-[var(--color-muted)] hover:text-[var(--foreground)] hover:bg-white/5 transition-colors disabled:opacity-50"
        >
          <RefreshCw
            className={cn("h-3.5 w-3.5", loading && "animate-spin")}
          />
          Refresh
        </button>
      </div>

      {/* ── Error banner ───────────────────────────────────────── */}
      {error && (
        <div className="mb-5 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2">
          <AlertCircle className="h-4 w-4 flex-shrink-0" />
          {error}
          <button
            onClick={loadAnalytics}
            className="ml-auto text-xs underline"
          >
            retry
          </button>
        </div>
      )}

      {/* ── Empty state ────────────────────────────────────────── */}
      {showEmpty && (
        <div className="glass-panel p-10 text-center flex flex-col items-center gap-3">
          <TrendingUp className="h-10 w-10 text-[var(--color-muted)]" />
          <p className="text-sm font-medium text-[var(--foreground)]">
            No analytics yet
          </p>
          <p className="text-xs text-[var(--color-muted)] max-w-xs">
            Start chatting with customers to see data here.
          </p>
          <Link
            href="/dashboard"
            className="mt-2 px-5 py-2.5 rounded-xl bg-[var(--gold-500)] text-[#07111c] text-sm font-semibold hover:bg-[var(--gold-600)] transition-colors inline-block"
          >
            Go to Dashboard
          </Link>
        </div>
      )}

      {/* ── KPI cards (2-col on md+) ──────────────────────────── */}
      {loading && !hasAnyData ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-6">
          <KpiCardSkeleton />
          <KpiCardSkeleton />
          <KpiCardSkeleton />
          <KpiCardSkeleton />
        </div>
      ) : hasAnyData ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-6">
          <KpiCard
            label="Total Conversations"
            value={dashboard?.total_conversations ?? 0}
            sub="All time"
            icon={MessageSquare}
            accent
          />
          <KpiCard
            label="Total Messages"
            value={dashboard?.total_messages ?? 0}
            sub="Across all sessions"
            icon={BarChart3}
          />
          <KpiCard
            label="Avg Messages / Chat"
            value={
              dashboard
                ? dashboard.avg_messages_per_conversation.toFixed(1)
                : "0"
            }
            sub="Per conversation"
            icon={Zap}
          />
          <KpiCard
            label="Total Revenue"
            value={revenue ? formatCents(revenue.total_revenue_cents) : "$0.00"}
            sub="All-time billed"
            icon={DollarSign}
            accent
          />
        </div>
      ) : null}

      {/* ── Daily conversations chart ──────────────────────────── */}
      {(loading || (dashboard && dashboard.daily_conversations.length > 0)) && (
        <div className="glass-panel p-5 mb-4">
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4">
            Daily Conversations
          </h2>
          {loading && !dashboard ? (
            <div className="h-32 flex items-end gap-1.5">
              {[40, 70, 55, 90, 30, 80, 60, 45, 75, 50].map((h, i) => (
                <div
                  key={i}
                  className="flex-1 animate-pulse rounded-t-sm bg-white/5"
                  style={{ height: `${h}%` }}
                />
              ))}
            </div>
          ) : (
            <DailyConversationsChart
              data={dashboard?.daily_conversations ?? []}
            />
          )}
        </div>
      )}

      {/* ── Two-column section: skills + conversations ─────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Skill usage */}
        <div className="glass-panel p-5">
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4">
            Skill Usage
          </h2>
          {loading && skills.length === 0 ? (
            <div className="flex flex-col gap-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="flex items-center gap-3">
                  <SkeletonBlock className="flex-1 h-4" />
                  <SkeletonBlock className="w-24 h-2" />
                </div>
              ))}
            </div>
          ) : (
            <SkillUsageTable skills={skills} />
          )}
        </div>

        {/* Recent conversations */}
        <div className="glass-panel p-5">
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4">
            Recent Conversations
          </h2>
          {loading && conversations.length === 0 ? (
            <div className="flex flex-col gap-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="flex items-center gap-3">
                  <SkeletonBlock className="h-7 w-7 rounded-lg flex-shrink-0" />
                  <div className="flex-1 flex flex-col gap-1.5">
                    <SkeletonBlock className="h-3.5 w-24" />
                    <SkeletonBlock className="h-3 w-16" />
                  </div>
                  <SkeletonBlock className="h-3 w-10 flex-shrink-0" />
                </div>
              ))}
            </div>
          ) : (
            <ConversationList conversations={conversations} />
          )}
        </div>
      </div>
    </div>
  );
}
