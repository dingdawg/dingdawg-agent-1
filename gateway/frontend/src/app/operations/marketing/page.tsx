"use client";

/**
 * Marketing & Campaigns (Cap 6).
 *
 * - Campaign analytics overview (last 30 days)
 * - Create campaign form (name, segment, channel, message template)
 * - Draft campaigns list with send action
 * - Sent campaigns history
 * - Back link to /operations
 *
 * Backend endpoints:
 *   GET  /api/v1/business-ops/campaigns/analytics?business_id&days
 *   POST /api/v1/business-ops/campaigns
 *   POST /api/v1/business-ops/campaigns/{campaign_id}/send
 */

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Megaphone,
  AlertCircle,
  RefreshCw,
  ChevronLeft,
  CheckCircle,
  Plus,
  Send,
  BarChart3,
} from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { useAgentStore } from "@/store/agentStore";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import {
  getCampaignAnalytics,
  createCampaign,
  sendCampaign,
  type CampaignAnalyticsResponse,
  type CreateCampaignResponse,
  type SendCampaignResponse,
} from "@/services/api/businessOpsService";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Campaign {
  id: string;
  name: string;
  channel: string;
  status: string;
  sent_count?: number;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function channelBadge(channel: string): string {
  const map: Record<string, string> = {
    sms: "bg-green-500/10 text-green-400 border-green-500/20",
    email: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    push: "bg-purple-500/10 text-purple-400 border-purple-500/20",
  };
  return map[channel] ?? "bg-white/5 text-[var(--color-muted)] border-[var(--stroke)]";
}

function statusBadge(status: string): string {
  if (status === "sent") return "bg-green-500/10 text-green-400 border-green-500/20";
  if (status === "draft") return "bg-yellow-500/10 text-yellow-400 border-yellow-500/20";
  return "bg-white/5 text-[var(--color-muted)] border-[var(--stroke)]";
}

// ─── Page shell ───────────────────────────────────────────────────────────────

export default function MarketingPage() {
  return (
    <ProtectedRoute>
      <AppShell>
        <MarketingContent />
      </AppShell>
    </ProtectedRoute>
  );
}

// ─── Content ──────────────────────────────────────────────────────────────────

function MarketingContent() {
  const router = useRouter();
  const { currentAgent, agents, isLoading: agentsLoading, fetchAgents } = useAgentStore();

  const [analytics, setAnalytics] = useState<CampaignAnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Create form state
  const [showForm, setShowForm] = useState(false);
  const [formName, setFormName] = useState("");
  const [formChannel, setFormChannel] = useState("sms");
  const [formSegment, setFormSegment] = useState("{}");
  const [formTemplate, setFormTemplate] = useState("");
  const [creating, setCreating] = useState(false);
  const [createResult, setCreateResult] = useState<CreateCampaignResponse | null>(null);

  // Send state
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [sendResults, setSendResults] = useState<Record<string, SendCampaignResponse>>({});

  // Guard: redirect if no agents
  useEffect(() => {
    if (!agentsLoading && agents.length === 0) {
      router.push("/claim");
    }
  }, [agentsLoading, agents, router]);

  const agentId = currentAgent?.id ?? agents[0]?.id ?? "";

  const load = useCallback(async () => {
    if (!agentId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getCampaignAnalytics(agentId, 30);
      setAnalytics(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    if (agentId) load();
  }, [agentId, load]);

  const handleCreate = useCallback(async () => {
    if (!formName.trim() || !formTemplate.trim()) return;
    setCreating(true);
    setCreateResult(null);
    try {
      const result = await createCampaign(agentId, {
        name: formName.trim(),
        channel: formChannel,
        segment_filter_json: formSegment || "{}",
        template: formTemplate.trim(),
      });
      setCreateResult(result);
      if (result.ok || result.campaign_id) {
        setFormName("");
        setFormTemplate("");
        setFormSegment("{}");
        setShowForm(false);
        load();
      }
    } catch (err: unknown) {
      setCreateResult({
        ok: false,
        err: err instanceof Error ? err.message : "Failed to create campaign",
      });
    } finally {
      setCreating(false);
    }
  }, [agentId, formName, formChannel, formSegment, formTemplate, load]);

  const handleSend = useCallback(
    async (campaignId: string) => {
      setSendingId(campaignId);
      try {
        const result = await sendCampaign(agentId, campaignId);
        setSendResults((prev) => ({ ...prev, [campaignId]: result }));
        load();
      } catch (err: unknown) {
        setSendResults((prev) => ({
          ...prev,
          [campaignId]: {
            ok: false,
            err: err instanceof Error ? err.message : "Send failed",
          },
        }));
      } finally {
        setSendingId(null);
      }
    },
    [agentId, load]
  );

  const campaigns: Campaign[] = Array.isArray(analytics?.campaigns)
    ? (analytics.campaigns as Campaign[])
    : [];

  const drafts = campaigns.filter((c) => c.status === "draft");
  const sent = campaigns.filter((c) => c.status === "sent");

  // ─── Render ──────────────────────────────────────────────────────────────────

  return (
    <div
      className="h-full overflow-y-auto overflow-x-hidden scrollbar-thin px-4 pb-6 max-w-2xl mx-auto w-full"
      style={{ paddingTop: "calc(env(safe-area-inset-top, 0px) + 24px)" }}
    >
      {/* Back navigation */}
      <div className="flex items-center gap-2 mb-5">
        <Link
          href="/operations"
          className="flex items-center gap-1 text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors"
        >
          <ChevronLeft size={16} />
          Operations
        </Link>
      </div>

      {/* Page header */}
      <div className="flex items-center justify-between gap-3 mb-6">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-pink-500/10">
            <Megaphone size={22} className="text-pink-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-[var(--foreground)]">Marketing</h1>
            <p className="text-sm text-[var(--color-muted)]">Campaigns, segments, and reach</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-[var(--color-muted)] hover:bg-white/5 transition-colors disabled:opacity-50"
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
          <button
            onClick={() => setShowForm((v) => !v)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[var(--gold-500)] text-[#07111c] text-xs font-semibold hover:bg-[var(--gold-600)] transition-colors"
          >
            <Plus size={14} />
            New Campaign
          </button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex items-center gap-2 text-sm text-red-400 rounded-xl border border-red-500/20 bg-red-500/5 p-3 mb-4">
          <AlertCircle size={16} className="shrink-0" />
          <span>{error}</span>
          <button onClick={load} className="ml-auto hover:underline text-xs">
            Retry
          </button>
        </div>
      )}

      {/* Create campaign form */}
      {showForm && (
        <div className="glass-panel p-5 mb-6">
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4">New Campaign</h2>

          <div className="space-y-3">
            <div>
              <label className="block text-xs text-[var(--color-muted)] mb-1">
                Campaign name
              </label>
              <input
                type="text"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="e.g. Summer Re-engagement"
                className="w-full rounded-lg border border-[var(--stroke)] bg-[var(--ink-900)] px-3 py-2 text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:border-[var(--gold-500)]/50 focus:outline-none transition-colors"
              />
            </div>

            <div>
              <label className="block text-xs text-[var(--color-muted)] mb-1">Channel</label>
              <select
                value={formChannel}
                onChange={(e) => setFormChannel(e.target.value)}
                className="w-full rounded-lg border border-[var(--stroke)] bg-[var(--ink-900)] px-3 py-2 text-sm text-[var(--foreground)] focus:border-[var(--gold-500)]/50 focus:outline-none transition-colors"
              >
                <option value="sms">SMS</option>
                <option value="email">Email</option>
                <option value="push">Push notification</option>
              </select>
            </div>

            <div>
              <label className="block text-xs text-[var(--color-muted)] mb-1">
                Message template
              </label>
              <textarea
                value={formTemplate}
                onChange={(e) => setFormTemplate(e.target.value)}
                placeholder="Hi {name}, we miss you! Book your next appointment and get 10% off…"
                rows={3}
                className="w-full rounded-lg border border-[var(--stroke)] bg-[var(--ink-900)] px-3 py-2 text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:border-[var(--gold-500)]/50 focus:outline-none transition-colors resize-none"
              />
              <p className="text-xs text-[var(--color-muted)] mt-1">
                Use {"{name}"} for personalization.
              </p>
            </div>
          </div>

          {createResult && (
            <div
              className={cn(
                "flex items-center gap-2 rounded-lg px-3 py-2 text-xs mt-3 border",
                createResult.ok || createResult.campaign_id
                  ? "bg-green-500/10 text-green-400 border-green-500/20"
                  : "bg-red-500/10 text-red-400 border-red-500/20"
              )}
            >
              {createResult.ok || createResult.campaign_id ? (
                <CheckCircle size={13} />
              ) : (
                <AlertCircle size={13} />
              )}
              {createResult.ok || createResult.campaign_id
                ? `Campaign created${
                    createResult.campaign_id ? ` — ID: ${createResult.campaign_id}` : ""
                  }`
                : (createResult.err as string | undefined) ?? "Failed to create campaign"}
            </div>
          )}

          <div className="flex gap-2 mt-4">
            <button
              onClick={handleCreate}
              disabled={creating || !formName.trim() || !formTemplate.trim()}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--gold-500)] text-[#07111c] text-sm font-semibold hover:bg-[var(--gold-600)] disabled:opacity-50 transition-colors"
            >
              {creating ? (
                <RefreshCw size={14} className="animate-spin" />
              ) : (
                <Plus size={14} />
              )}
              {creating ? "Creating…" : "Create Draft"}
            </button>
            <button
              onClick={() => setShowForm(false)}
              className="px-4 py-2 rounded-lg text-sm text-[var(--color-muted)] hover:bg-white/5 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Analytics summary */}
      {analytics && campaigns.length > 0 && (
        <div className="glass-panel p-4 mb-6">
          <div className="flex items-center gap-2 mb-3">
            <BarChart3 size={16} className="text-pink-400" />
            <span className="text-sm font-semibold text-[var(--foreground)]">Last 30 days</span>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg bg-white/[0.03] border border-[var(--stroke)] p-3">
              <p className="text-xs text-[var(--color-muted)] mb-1">Total campaigns</p>
              <p className="text-xl font-bold text-[var(--foreground)]">{campaigns.length}</p>
            </div>
            <div className="rounded-lg bg-white/[0.03] border border-[var(--stroke)] p-3">
              <p className="text-xs text-[var(--color-muted)] mb-1">Sent</p>
              <p className="text-xl font-bold text-green-400">{sent.length}</p>
            </div>
          </div>
        </div>
      )}

      {/* Loading skeleton */}
      {loading && !analytics && (
        <div className="space-y-3 mb-6">
          <div className="glass-panel p-4 h-16 animate-pulse" />
          <div className="glass-panel p-4 h-16 animate-pulse" />
        </div>
      )}

      {/* Draft campaigns — ready to send */}
      {drafts.length > 0 && (
        <section className="mb-6">
          <h2 className="text-xs font-semibold text-[var(--color-muted)] uppercase tracking-wider mb-3">
            Ready to send ({drafts.length})
          </h2>
          <div className="space-y-2">
            {drafts.map((campaign) => {
              const sendResult = sendResults[campaign.id];
              return (
                <div
                  key={campaign.id}
                  className="glass-panel p-4 flex items-center justify-between gap-3"
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-[var(--foreground)] truncate">
                      {campaign.name}
                    </p>
                    <div className="flex items-center gap-2 mt-1">
                      <span
                        className={cn(
                          "text-xs px-2 py-0.5 rounded-full border",
                          channelBadge(campaign.channel)
                        )}
                      >
                        {campaign.channel}
                      </span>
                      <span
                        className={cn(
                          "text-xs px-2 py-0.5 rounded-full border",
                          statusBadge(campaign.status)
                        )}
                      >
                        {campaign.status}
                      </span>
                    </div>
                    {sendResult && (
                      <p
                        className={cn(
                          "text-xs mt-1",
                          sendResult.ok ? "text-green-400" : "text-red-400"
                        )}
                      >
                        {sendResult.ok
                          ? `Sent to ${sendResult.sent_count ?? "?"} recipients`
                          : ((sendResult.err as string | undefined) ?? "Send failed")}
                      </p>
                    )}
                  </div>
                  <button
                    onClick={() => handleSend(campaign.id)}
                    disabled={sendingId === campaign.id}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-green-500/10 text-green-400 border border-green-500/20 text-xs font-medium hover:bg-green-500/20 disabled:opacity-50 transition-colors shrink-0"
                  >
                    {sendingId === campaign.id ? (
                      <RefreshCw size={12} className="animate-spin" />
                    ) : (
                      <Send size={12} />
                    )}
                    {sendingId === campaign.id ? "Sending…" : "Send"}
                  </button>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Sent campaigns history */}
      {sent.length > 0 && (
        <section className="mb-6">
          <h2 className="text-xs font-semibold text-[var(--color-muted)] uppercase tracking-wider mb-3">
            Sent ({sent.length})
          </h2>
          <div className="space-y-2">
            {sent.map((campaign) => (
              <div
                key={campaign.id}
                className="glass-panel p-4 flex items-center justify-between gap-3"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-[var(--foreground)] truncate">
                    {campaign.name}
                  </p>
                  <div className="flex items-center gap-2 mt-1">
                    <span
                      className={cn(
                        "text-xs px-2 py-0.5 rounded-full border",
                        channelBadge(campaign.channel)
                      )}
                    >
                      {campaign.channel}
                    </span>
                    <span className="text-xs px-2 py-0.5 rounded-full border bg-green-500/10 text-green-400 border-green-500/20">
                      sent
                    </span>
                  </div>
                </div>
                {campaign.sent_count !== undefined && (
                  <p className="text-sm font-semibold text-[var(--foreground)] shrink-0">
                    {campaign.sent_count} sent
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Empty state */}
      {!loading && !error && campaigns.length === 0 && (
        <div className="glass-panel p-10 text-center">
          <Megaphone size={36} className="text-pink-400/50 mx-auto mb-3" />
          <p className="text-sm font-medium text-[var(--foreground)] mb-1">No campaigns yet</p>
          <p className="text-xs text-[var(--color-muted)] mb-4">
            Create your first campaign to start reaching customers.
          </p>
          <button
            onClick={() => setShowForm(true)}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--gold-500)] text-[#07111c] text-sm font-semibold hover:bg-[var(--gold-600)] transition-colors"
          >
            <Plus size={14} />
            Create Campaign
          </button>
        </div>
      )}
    </div>
  );
}
