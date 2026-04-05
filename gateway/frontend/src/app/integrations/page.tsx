"use client";

/**
 * Integration Hub — connect the agent to external services.
 *
 * Grid of integration cards (2 cols desktop, 1 col mobile):
 *   - Google Calendar, SendGrid, Twilio, Vapi, Webhooks, DD Main Bridge
 *   - Coming soon: Stripe, Slack, Zapier, Google Sheets, HubSpot
 *
 * Tab filter: All | Communication | Scheduling | Automation | Voice & Phone | Coming Soon
 * Modal: per-integration configuration form
 * State: integration status fetched on mount, refreshed after each configure action.
 *
 * Route: /integrations
 */

import { useEffect, useState, useCallback } from "react";
import { useNangoConnect } from "@/hooks/useNangoConnect";
import { useRouter } from "next/navigation";
import { RefreshCw, AlertCircle, Plug, Lock } from "lucide-react";
import { cn } from "@/lib/utils";
import type { TierName } from "@/components/integrations/IntegrationCard";
import { useAgentStore } from "@/store/agentStore";
import { useAuthStore } from "@/store/authStore";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { PageHeader } from "@/components/layout/PageHeader";

const ADMIN_EMAIL = (process.env.NEXT_PUBLIC_ADMIN_EMAIL ?? "").trim().toLowerCase();
import { AppShell } from "@/components/layout/AppShell";
import { IntegrationCard } from "@/components/integrations/IntegrationCard";
import type { ModalIntegration } from "@/components/integrations/IntegrationConfigModal";
import dynamic from "next/dynamic";

const IntegrationConfigModal = dynamic(
  () =>
    import("@/components/integrations/IntegrationConfigModal").then(
      (m) => m.IntegrationConfigModal
    ),
  { ssr: false }
);
import {
  getIntegrationStatus,
  connectGoogleCalendar,
  configureSendGrid,
  configureTwilio,
  configureVapi,
  disconnectIntegration,
  testIntegration,
  listWebhooks,
  createWebhook,
  deleteWebhook,
  type IntegrationStatus,
  type WebhookEntry,
  type SendGridConfig,
  type TwilioConfig,
  type VapiConfig,
  type WebhookConfig,
  type IntegrationKey,
} from "@/services/api/integrationService";

// ─── Static integration definitions ──────────────────────────────────────────

// ─── Tier ordering ────────────────────────────────────────────────────────────

const TIER_ORDER: Record<TierName | "free", number> = {
  free: 0,
  starter: 1,
  pro: 2,
  enterprise: 3,
};

interface IntegrationDef {
  id: ModalIntegration;
  name: string;
  description: string;
  icon: string;
  category: string;
  /** Minimum plan tier required to use this integration */
  requiredTier: TierName;
}

const LIVE_INTEGRATIONS: IntegrationDef[] = [
  // ── Starter tier ────────────────────────────────────────────────────────────
  {
    id: "google_calendar",
    name: "Google Calendar",
    description:
      "Your agent books straight into your real Google Calendar — customers see your actual availability and get automatic reminders. No double-booking.",
    icon: "📅",
    category: "Scheduling",
    requiredTier: "starter",
  },
  {
    id: "sendgrid",
    name: "Email Alerts",
    description:
      "Stay in the loop without babysitting your agent — get a daily summary of bookings, messages, and anything that needs your attention, straight to your inbox.",
    icon: "✉️",
    category: "Communication",
    requiredTier: "starter",
  },
  {
    id: "twilio",
    name: "Text Message Alerts",
    description:
      "Get a text the moment something needs your attention — new bookings, customer questions, appointment reminders, all straight to your phone.",
    icon: "💬",
    category: "Communication",
    requiredTier: "starter",
  },
  {
    id: "webhooks",
    name: "Connect Any App",
    description:
      "Automatically sync your agent's data with any tool you already use — QuickBooks, Google Sheets, your CRM, anything. Set it once, runs forever.",
    icon: "🔗",
    category: "Automation",
    requiredTier: "starter",
  },
  // ── Pro tier ─────────────────────────────────────────────────────────────────
  {
    id: "vapi",
    name: "AI Phone Answering",
    description:
      "Never miss a call. Your agent answers the phone, books appointments by voice, takes messages, and only rings you when it's urgent.",
    icon: "📞",
    category: "Voice & Phone",
    requiredTier: "pro",
  },
  {
    id: "zapier" as ModalIntegration,
    name: "Zapier — 8,000+ Apps",
    description:
      "Connect your agent to basically every app on the planet — QuickBooks, Mailchimp, Square, Google Sheets, HubSpot, and 8,000 more. No tech skills needed.",
    icon: "⚡",
    category: "Automation",
    requiredTier: "pro",
  },
  {
    id: "cronofy" as ModalIntegration,
    name: "All Calendars — One Click",
    description:
      "Use Google, Outlook, or Apple Calendar? Connect any of them in one click. Your agent checks your real availability before booking — no conflicts, ever.",
    icon: "🗓️",
    category: "Scheduling",
    requiredTier: "pro",
  },
  // ── Enterprise tier ──────────────────────────────────────────────────────────
  {
    id: "stripe" as ModalIntegration,
    name: "Accept Payments in Chat",
    description:
      "Customers pay you right inside the conversation — credit cards, invoices, refunds all handled. You get paid without ever leaving the chat.",
    icon: "💳",
    category: "Automation",
    requiredTier: "enterprise",
  },
  {
    id: "dd_main_bridge",
    name: "Command Center (Multi-Location)",
    description:
      "Own multiple locations? Run all your agents from one dashboard — shared customer data, unified settings, one place to see everything.",
    icon: "🏪",
    category: "DingDawg",
    requiredTier: "enterprise",
  },
];

interface ComingSoonDef {
  name: string;
  description: string;
  icon: string;
  category: string;
  requiredTier?: TierName;
}

const COMING_SOON: ComingSoonDef[] = [
  // Pro coming soon
  {
    name: "Social Media Posting",
    description: "Your agent automatically posts updates, promotions, and replies to Twitter, Facebook, and Instagram — your business stays active 24/7.",
    icon: "📱",
    category: "Automation",
    requiredTier: "pro",
  },
  // Enterprise coming soon
  {
    name: "TikTok & LinkedIn Posting",
    description: "Reach the next generation of customers — your agent handles TikTok video captions and LinkedIn posts without lifting a finger.",
    icon: "🎵",
    category: "Automation",
    requiredTier: "enterprise",
  },
  {
    name: "Custom API Access",
    description: "Build on top of your agent — full REST API access for your devs to create custom workflows, dashboards, and integrations.",
    icon: "🔧",
    category: "Automation",
    requiredTier: "enterprise",
  },
  {
    name: "White Label Options",
    description: "Rebrand the agent as your own product — your logo, your domain, your colors. Resell to your own clients.",
    icon: "🏷️",
    category: "DingDawg",
    requiredTier: "enterprise",
  },
  // General coming soon (no tier gate)
  {
    name: "Slack Alerts",
    description: "If your team runs on Slack, your agent will post there — new bookings, sales, anything urgent — so nothing slips through the cracks.",
    icon: "💼",
    category: "Communication",
  },
  {
    name: "Google Sheets Sync",
    description: "Every booking, lead, and sale logged to a Google Sheet automatically — your data, your spreadsheet, always up to date.",
    icon: "📊",
    category: "Automation",
  },
  {
    name: "CRM Sync",
    description: "Every new customer your agent talks to automatically lands in your HubSpot, Salesforce, or any CRM — your pipeline fills itself.",
    icon: "🤝",
    category: "Communication",
  },
];

// ─── Tab definitions ──────────────────────────────────────────────────────────

const TABS = [
  "All",
  "Communication",
  "Scheduling",
  "Automation",
  "Voice & Phone",
  "Coming Soon",
] as const;

type Tab = (typeof TABS)[number];

// ─── Default status ───────────────────────────────────────────────────────────

const DEFAULT_STATUS: IntegrationStatus = {
  google_calendar: { connected: false },
  sendgrid: { connected: false },
  twilio: { connected: false },
  vapi: { connected: false },
  webhooks: { active_count: 0, webhooks: [] },
  dd_main_bridge: { connected: false },
};

// ─── Page export ──────────────────────────────────────────────────────────────

export default function IntegrationsPage() {
  return (
    <ProtectedRoute>
      <AppShell>
        <IntegrationsContent />
      </AppShell>
    </ProtectedRoute>
  );
}

// ─── Integrations Content ─────────────────────────────────────────────────────

// ─── Tier section header ──────────────────────────────────────────────────────

function TierSectionHeader({
  label,
  tier,
  unlocked,
}: {
  label: string;
  tier: TierName | null;
  unlocked: boolean;
}) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <h2
        className={cn(
          "text-xs font-semibold whitespace-nowrap",
          unlocked ? "text-green-400" : "text-[var(--color-muted)]"
        )}
      >
        {label}
      </h2>
      {!unlocked && tier && (
        <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-[var(--gold-500)]/15 text-[var(--gold-500)] border border-[var(--gold-500)]/25">
          {tier.toUpperCase()}
        </span>
      )}
      <div className="flex-1 h-px bg-[var(--stroke)]" />
    </div>
  );
}

// ─── Tier helpers ─────────────────────────────────────────────────────────────

/**
 * Derives the user's current tier from their plan string.
 * Falls back to "free" if nothing is stored — safe default.
 */
function parseTier(plan: string | null | undefined): TierName | "free" {
  switch ((plan ?? "").toLowerCase()) {
    case "starter": return "starter";
    case "pro":     return "pro";
    case "enterprise": return "enterprise";
    default:        return "free";
  }
}

function tierUnlocked(userTier: TierName | "free", required: TierName): boolean {
  return TIER_ORDER[userTier] >= TIER_ORDER[required];
}

const TIER_DISPLAY: Record<TierName, string> = {
  starter: "Starter ($49.99/mo)",
  pro: "Pro ($79.99/mo)",
  enterprise: "Enterprise ($199.99/mo)",
};

// ─── Content ──────────────────────────────────────────────────────────────────

function IntegrationsContent() {
  const router = useRouter();
  const { agents, currentAgent, isLoading: agentsLoading, fetchAgents } =
    useAgentStore();
  const { user } = useAuthStore();
  const isAdmin = user?.email?.toLowerCase() === ADMIN_EMAIL;

  // Derive user tier from auth user — extend User type when billing lands.
  // For now read from localStorage plan key set by billing flow, or default free.
  const userTier: TierName | "free" = parseTier(
    typeof window !== "undefined" ? localStorage.getItem("user_plan") : null
  );

  const [status, setStatus] = useState<IntegrationStatus>(DEFAULT_STATUS);
  const [webhooks, setWebhooks] = useState<WebhookEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<Tab>("All");
  const [openModal, setOpenModal] = useState<ModalIntegration | null>(null);

  // Upgrade prompt state — shown when a locked card is clicked
  const [upgradePrompt, setUpgradePrompt] = useState<{
    name: string;
    tier: TierName;
  } | null>(null);

  // Fetch agents on mount
  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  // Redirect if no agents
  useEffect(() => {
    if (!agentsLoading && agents.length === 0) {
      router.replace("/claim");
    }
  }, [agentsLoading, agents.length, router]);

  // Load integration status + webhooks for the current agent
  const loadStatus = useCallback(async () => {
    if (!currentAgent) return;
    setLoading(true);
    setError(null);
    try {
      const [s, wh] = await Promise.allSettled([
        getIntegrationStatus(currentAgent.id),
        listWebhooks(currentAgent.id),
      ]);
      if (s.status === "fulfilled") setStatus(s.value);
      if (wh.status === "fulfilled") setWebhooks(wh.value);
      if (s.status === "rejected") {
        setError((s.reason as Error).message ?? "Failed to load integrations");
      }
    } finally {
      setLoading(false);
    }
  }, [currentAgent]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  // ── Nango Connect for OAuth integrations ──────────────────────────────────

  const { connect: nangoConnect } = useNangoConnect({
    onSuccess: () => {
      loadStatus(); // Refresh status after connecting
    },
    onError: (id, err) => {
      console.error(`Failed to connect ${id}:`, err);
    },
    agentId: currentAgent?.id,
  });

  const handleNangoConnect = useCallback((integrationId: string) => {
    nangoConnect(integrationId);
  }, [nangoConnect]);

  // ── Action handlers ────────────────────────────────────────────────────────

  const handleConnectGoogle = useCallback(async () => {
    if (!currentAgent) return;
    const result = await connectGoogleCalendar(currentAgent.id);
    if (result.oauth_url) {
      // Mobile browsers block window.open popups — redirect in same tab instead.
      // Desktop can use new tab, but same-tab works universally.
      window.location.href = result.oauth_url;
      return; // Don't refresh status — page is navigating away
    }
    // Refresh status after connect attempt
    await loadStatus();
  }, [currentAgent, loadStatus]);

  const handleConfigureSendGrid = useCallback(
    async (config: SendGridConfig) => {
      if (!currentAgent) return;
      await configureSendGrid(currentAgent.id, config);
      await loadStatus();
    },
    [currentAgent, loadStatus]
  );

  const handleConfigureTwilio = useCallback(
    async (config: TwilioConfig) => {
      if (!currentAgent) return;
      await configureTwilio(currentAgent.id, config);
      await loadStatus();
    },
    [currentAgent, loadStatus]
  );

  const handleConfigureVapi = useCallback(
    async (config: VapiConfig) => {
      if (!currentAgent) return;
      await configureVapi(currentAgent.id, config);
      await loadStatus();
    },
    [currentAgent, loadStatus]
  );

  const handleDisconnect = useCallback(
    async (integration: ModalIntegration) => {
      if (!currentAgent) return;
      await disconnectIntegration(currentAgent.id, integration as IntegrationKey);
      await loadStatus();
    },
    [currentAgent, loadStatus]
  );

  const handleTest = useCallback(
    async (integration: "sendgrid" | "twilio") => {
      if (!currentAgent) return;
      await testIntegration(currentAgent.id, integration);
    },
    [currentAgent]
  );

  const handleAddWebhook = useCallback(
    async (config: WebhookConfig) => {
      if (!currentAgent) return;
      await createWebhook(currentAgent.id, config);
      const updated = await listWebhooks(currentAgent.id);
      setWebhooks(updated);
      await loadStatus();
    },
    [currentAgent, loadStatus]
  );

  const handleDeleteWebhook = useCallback(
    async (webhookId: string) => {
      if (!currentAgent) return;
      await deleteWebhook(currentAgent.id, webhookId);
      const updated = await listWebhooks(currentAgent.id);
      setWebhooks(updated);
      await loadStatus();
    },
    [currentAgent, loadStatus]
  );

  // ── Helper: derive per-card status ────────────────────────────────────────

  function isConnected(id: ModalIntegration): boolean {
    switch (id) {
      case "google_calendar":
        return status.google_calendar.connected;
      case "sendgrid":
        return status.sendgrid.connected;
      case "twilio":
        return status.twilio.connected;
      case "vapi":
        return status.vapi.connected;
      case "webhooks":
        return status.webhooks.active_count > 0;
      case "dd_main_bridge":
        return status.dd_main_bridge.connected;
      default:
        return false;
    }
  }

  function activeCount(id: ModalIntegration): number | undefined {
    if (id === "webhooks") return status.webhooks.active_count;
    return undefined;
  }

  // ── Render a single live integration card ─────────────────────────────────

  const NANGO_IDS = ["cronofy", "zapier", "stripe"];

  function renderCard(def: IntegrationDef, unlocked: boolean) {
    const locked = !unlocked;
    return (
      <IntegrationCard
        key={def.id}
        name={def.name}
        description={def.description}
        icon={def.icon}
        category={def.category}
        connected={isConnected(def.id)}
        activeCount={activeCount(def.id)}
        lockedTier={locked ? def.requiredTier : undefined}
        onConfigure={() => {
          if (locked) {
            handleLockedClick(def.name, def.requiredTier);
            return;
          }
          if (NANGO_IDS.includes(def.id)) {
            handleNangoConnect(def.id);
          } else {
            setOpenModal(def.id);
          }
        }}
        loading={loading && !locked}
        actionLabel={
          def.id === "google_calendar" ? "Sign in with Google" :
          def.id === "cronofy" ? "Connect Your Calendar" :
          def.id === "zapier" ? "Connect with Zapier" :
          def.id === "stripe" ? "Connect Stripe" :
          def.id === "twilio" ? "Add Your Phone Number" :
          def.id === "vapi" ? "Get a Business Phone Number" :
          def.id === "sendgrid" ? "Add Your Email" :
          undefined
        }
      />
    );
  }

  // ── Locked card click handler ──────────────────────────────────────────────

  const handleLockedClick = useCallback((name: string, tier: TierName) => {
    setUpgradePrompt({ name, tier });
    // Auto-dismiss after 4 s
    setTimeout(() => setUpgradePrompt(null), 4000);
  }, []);

  // ── Filter by tab ──────────────────────────────────────────────────────────

  const visibleLive = LIVE_INTEGRATIONS.filter((i) => {
    // Command Center bridge is owner-only — hide from non-admin users
    if (i.id === "dd_main_bridge" && !isAdmin) return false;
    if (activeTab === "All") return true;
    if (activeTab === "Coming Soon") return false;
    return i.category === activeTab;
  });

  // ── Group live integrations by tier section for "All" tab ──────────────────

  const starterIntegrations = visibleLive.filter(
    (i) => i.requiredTier === "starter"
  );
  const proIntegrations = visibleLive.filter(
    (i) => i.requiredTier === "pro"
  );
  const enterpriseIntegrations = visibleLive.filter(
    (i) => i.requiredTier === "enterprise"
  );

  const visibleComingSoon =
    activeTab === "All" || activeTab === "Coming Soon"
      ? COMING_SOON.filter(
          (i) =>
            activeTab === "All" ||
            activeTab === "Coming Soon"
        )
      : [];

  // ── Early loading state ───────────────────────────────────────────────────

  if (agentsLoading && agents.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="spinner text-[var(--gold-500)]" />
      </div>
    );
  }

  if (!currentAgent) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 px-6 text-center">
        <div className="h-14 w-14 rounded-2xl bg-[var(--gold-500)]/10 flex items-center justify-center">
          <Plug className="h-7 w-7 text-[var(--gold-500)]" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-[var(--foreground)] mb-1">
            No agent yet
          </h2>
          <p className="text-sm text-[var(--color-muted)]">
            Claim an agent to start connecting integrations.
          </p>
        </div>
        <button
          onClick={() => router.replace("/claim")}
          className="px-5 py-2.5 rounded-xl bg-[var(--gold-500)] text-[#07111c] text-sm font-semibold hover:bg-[var(--gold-600)] transition-colors"
        >
          Claim your agent
        </button>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto scrollbar-thin">
      <div className="max-w-3xl mx-auto px-4 pt-6 pb-24 lg:pb-8">
        {/* ── Back navigation ──────────────────────────────────────── */}
        <PageHeader title="Integrations" />

        {/* ── Page header ──────────────────────────────────────────── */}
        <div className="flex items-start justify-between mb-6">
          <div>
            <h1 className="text-xl font-heading font-bold text-[var(--foreground)] mb-1">
              Give Your Agent Superpowers
            </h1>
            <p className="text-[15px] text-[var(--color-muted)]">
              Connect the tools you already use — your agent works all of them automatically
            </p>
          </div>
          <button
            onClick={loadStatus}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-[var(--color-muted)] hover:text-[var(--foreground)] hover:bg-white/5 transition-colors disabled:opacity-50 flex-shrink-0 mt-1"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            Refresh
          </button>
        </div>

        {/* ── Error banner ─────────────────────────────────────────── */}
        {error && (
          <div className="mb-5 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            {error}
            <button onClick={loadStatus} className="ml-auto text-xs underline">
              retry
            </button>
          </div>
        )}

        {/* ── Tab bar ──────────────────────────────────────────────── */}
        <div className="flex items-center gap-1 overflow-x-auto scrollbar-none mb-6 pb-1">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                "text-xs font-medium px-3 py-1.5 rounded-full whitespace-nowrap transition-colors flex-shrink-0",
                activeTab === tab
                  ? "bg-[var(--gold-500)]/15 text-[var(--gold-500)] border border-[var(--gold-500)]/25"
                  : "text-[var(--color-muted)] hover:text-[var(--foreground)] hover:bg-white/5"
              )}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* ── Upgrade prompt toast ─────────────────────────────────── */}
        {upgradePrompt && (
          <div className="mb-5 p-3.5 rounded-xl bg-[var(--gold-500)]/10 border border-[var(--gold-500)]/25 flex items-center gap-3 animate-in fade-in slide-in-from-top-2 duration-200">
            <Lock className="h-4 w-4 text-[var(--gold-500)] flex-shrink-0" />
            <p className="text-sm text-[var(--foreground)] flex-1">
              <span className="font-semibold">{upgradePrompt.name}</span> requires the{" "}
              <span className="text-[var(--gold-500)] font-semibold">
                {TIER_DISPLAY[upgradePrompt.tier]}
              </span>{" "}
              plan.
            </p>
            <button
              onClick={() => router.push("/settings/billing")}
              className="text-xs font-semibold text-[var(--gold-500)] hover:text-[var(--gold-400)] whitespace-nowrap flex-shrink-0 underline underline-offset-2"
            >
              See Plans
            </button>
            <button
              onClick={() => setUpgradePrompt(null)}
              className="text-[var(--color-muted)] hover:text-[var(--foreground)] text-xs ml-1 flex-shrink-0"
            >
              x
            </button>
          </div>
        )}

        {/* ── Live integrations — grouped by tier ──────────────────── */}
        {visibleLive.length > 0 && (
          <>
            {/* When "All" tab: render tier sections. Other tabs: flat grid */}
            {activeTab === "All" ? (
              <>
                {/* Starter section */}
                {starterIntegrations.length > 0 && (
                  <div className="mb-6">
                    <TierSectionHeader
                      label={tierUnlocked(userTier, "starter") ? "Included in your plan" : "Available with Starter"}
                      tier={tierUnlocked(userTier, "starter") ? null : "starter"}
                      unlocked={tierUnlocked(userTier, "starter")}
                    />
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {starterIntegrations.map((def) =>
                        renderCard(def, tierUnlocked(userTier, def.requiredTier))
                      )}
                    </div>
                  </div>
                )}

                {/* Pro section */}
                {proIntegrations.length > 0 && (
                  <div className="mb-6">
                    <TierSectionHeader
                      label={tierUnlocked(userTier, "pro") ? "Included in your plan" : 'Available with Pro — "Most Popular"'}
                      tier={tierUnlocked(userTier, "pro") ? null : "pro"}
                      unlocked={tierUnlocked(userTier, "pro")}
                    />
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {proIntegrations.map((def) =>
                        renderCard(def, tierUnlocked(userTier, def.requiredTier))
                      )}
                    </div>
                  </div>
                )}

                {/* Enterprise section */}
                {enterpriseIntegrations.length > 0 && (
                  <div className="mb-6">
                    <TierSectionHeader
                      label={tierUnlocked(userTier, "enterprise") ? "Included in your plan" : "Available with Enterprise"}
                      tier={tierUnlocked(userTier, "enterprise") ? null : "enterprise"}
                      unlocked={tierUnlocked(userTier, "enterprise")}
                    />
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {enterpriseIntegrations.map((def) =>
                        renderCard(def, tierUnlocked(userTier, def.requiredTier))
                      )}
                    </div>
                  </div>
                )}
              </>
            ) : (
              /* Filtered tab: flat grid, still apply tier locking */
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-6">
                {visibleLive.map((def) =>
                  renderCard(def, tierUnlocked(userTier, def.requiredTier))
                )}
              </div>
            )}
          </>
        )}

        {/* ── Empty state for filtered tabs ────────────────────────── */}
        {visibleLive.length === 0 && activeTab !== "Coming Soon" && activeTab !== "All" && (
          <div className="glass-panel p-10 text-center flex flex-col items-center gap-3 mb-6">
            <Plug className="h-8 w-8 text-[var(--color-muted)]" />
            <p className="text-sm text-[var(--color-muted)]">
              No {activeTab} integrations available yet.
            </p>
          </div>
        )}

        {/* ── Coming Soon section ──────────────────────────────────── */}
        {visibleComingSoon.length > 0 && (
          <>
            {activeTab === "All" && (
              <div className="flex items-center gap-3 mb-4">
                <h2 className="text-sm font-semibold text-[var(--color-muted)]">
                  Coming Soon
                </h2>
                <div className="flex-1 h-px bg-[var(--stroke)]" />
              </div>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {visibleComingSoon.map((def) => (
                <IntegrationCard
                  key={def.name}
                  name={def.name}
                  description={def.description}
                  icon={def.icon}
                  category={def.category}
                  connected={false}
                  onConfigure={() => {}}
                  comingSoon
                />
              ))}
            </div>
          </>
        )}
      </div>

      {/* ── Config modal ─────────────────────────────────────────────── */}
      {openModal && (
        <IntegrationConfigModal
          integration={openModal}
          status={status}
          webhooks={webhooks}
          onClose={() => setOpenModal(null)}
          onConnectGoogle={handleConnectGoogle}
          onConfigureSendGrid={handleConfigureSendGrid}
          onConfigureTwilio={handleConfigureTwilio}
          onConfigureVapi={handleConfigureVapi}
          onDisconnect={handleDisconnect}
          onTestIntegration={handleTest}
          onAddWebhook={handleAddWebhook}
          onDeleteWebhook={handleDeleteWebhook}
        />
      )}
    </div>
  );
}
