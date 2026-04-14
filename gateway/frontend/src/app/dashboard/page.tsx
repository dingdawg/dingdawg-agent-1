"use client";

/**
 * Dashboard page — chat-first agent interface with AppShell layout.
 *
 * The conversation IS the dashboard. Modules render as interactive cards
 * in the chat stream. Layout: AppShell (nav + header) → session panel + chat.
 */

import { Suspense, useEffect, useState, useCallback, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { MessageSquare, Calendar, Mail, BarChart2, Search } from "lucide-react";
import { useNotificationStore } from "@/store/notificationStore";
import { useAuthStore } from "@/store/authStore";
import { useAgentStore } from "@/store/agentStore";
import { useChatStore } from "@/store/chatStore";
import { useSessionStore } from "@/store/sessionStore";
import {
  createSession,
  listSessions,
  sendMessage,
  sendMessageStream,
} from "@/services/api/agentService";
import { listTasks, getUsage } from "@/services/api/platformService";
import type {
  TaskResponse,
  TaskUsageResponse,
} from "@/services/api/platformService";
import { getIntegrationStatus } from "@/services/api/integrationService";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { ChatStream } from "@/components/chat/ChatStream";
import type { CardPayload } from "@/components/chat/ChatStream";
import type { TaskCardData } from "@/components/chat/cards/TaskCard";
import { ChatInput } from "@/components/chat/ChatInput";
import { VoiceButton } from "@/components/chat/VoiceButton";
import { DashboardHeader } from "@/components/dashboard/DashboardHeader";
import type { DashboardStats } from "@/components/dashboard/DashboardHeader";
import { GettingStarted } from "@/components/dashboard/GettingStarted";
import { AIDisclosureBanner } from "@/components/chat/AIDisclosureBanner";
import { generateId } from "@/lib/utils";

export default function DashboardPage() {
  return (
    <ProtectedRoute>
      <AppShell>
        <Suspense
          fallback={
            <div className="flex items-center justify-center h-full">
              <span className="spinner text-[var(--gold-500)]" />
            </div>
          }
        >
          <ChatDashboard />
        </Suspense>
      </AppShell>
    </ProtectedRoute>
  );
}

// ─── Skill result → card mapper ───────────────────────────────────────────────

/**
 * Maps an action payload returned by the LLM skill dispatcher to a CardPayload
 * that can be rendered inline in the chat stream.
 *
 * Covers all business-ops skills documented in the task spec.
 */
function mapSkillResultToCard(action: {
  skill: string;
  action: string;
  result: unknown;
}): CardPayload | null {
  const { skill, result } = action;
  const data = result as Record<string, unknown> | null | undefined;

  // ── KPI-style skills ──────────────────────────────────────────
  if (
    skill === "morning_pulse" ||
    skill === "weekly_intelligence" ||
    skill === "client_dashboard" ||
    skill === "campaign_analytics"
  ) {
    const metrics: CardPayload["kpiMetrics"] = [];
    if (data && typeof data === "object") {
      for (const [key, val] of Object.entries(data)) {
        if (typeof val === "number" || typeof val === "string") {
          metrics.push({
            label: key
              .replace(/_/g, " ")
              .replace(/\b\w/g, (c) => c.toUpperCase()),
            value: val as string | number,
            trend: "flat",
          });
        }
      }
    }
    if (metrics.length === 0) return null;
    return { type: "kpi-cards", kpiMetrics: metrics };
  }

  // ── Revenue forecast ──────────────────────────────────────────
  if (skill === "revenue_forecast") {
    const metrics: CardPayload["kpiMetrics"] = [];
    if (data && typeof data === "object") {
      const fieldMap: Record<string, string> = {
        current: "Current Revenue",
        forecast: "Forecast",
        growth: "Growth",
        target: "Target",
        mrr: "MRR",
        arr: "ARR",
      };
      for (const [key, label] of Object.entries(fieldMap)) {
        if (data[key] !== undefined) {
          metrics.push({
            label,
            value: data[key] as string | number,
            trend:
              key === "growth"
                ? ((data[key] as number) >= 0 ? "up" : "down")
                : "flat",
          });
        }
      }
      // Fallback: any numeric fields
      if (metrics.length === 0) {
        for (const [k, v] of Object.entries(data)) {
          if (typeof v === "number" || typeof v === "string") {
            metrics.push({
              label: k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
              value: v as string | number,
              trend: "flat",
            });
          }
        }
      }
    }
    if (metrics.length === 0) return null;
    return { type: "kpi-cards", kpiMetrics: metrics };
  }

  // ── Task-list skills ──────────────────────────────────────────
  if (skill === "check_triggers" || skill === "missed_conversations") {
    const items = Array.isArray(data?.items ?? data)
      ? (data?.items ?? data) as unknown[]
      : [];
    const tasks = (items as Record<string, unknown>[]).map((item, idx) => ({
      id: (item.id as string | undefined) ?? `item-${idx}`,
      description:
        (item.description as string | undefined) ??
        (item.message as string | undefined) ??
        (item.title as string | undefined) ??
        JSON.stringify(item),
      status: ((item.status as string | undefined) ?? "pending") as TaskCardData["status"],
      task_type: skill,
    }));
    if (tasks.length === 0) return null;
    return {
      type: "task-list",
      taskListTitle:
        skill === "missed_conversations" ? "Missed Conversations" : "Triggers",
      tasks,
    };
  }

  if (skill === "segment_clients") {
    const segments = Array.isArray(data?.segments ?? data)
      ? (data?.segments ?? data) as unknown[]
      : [];
    const tasks = (segments as Record<string, unknown>[]).map((seg, idx) => ({
      id: `seg-${idx}`,
      description:
        (seg.name as string | undefined) ??
        (seg.label as string | undefined) ??
        JSON.stringify(seg),
      status: "pending" as TaskCardData["status"],
      task_type: "segment",
    }));
    if (tasks.length === 0) return null;
    return { type: "task-list", taskListTitle: "Client Segments", tasks };
  }

  if (skill === "assign_staff" || skill === "staff_schedule") {
    const entries = Array.isArray(data?.assignments ?? data?.schedule ?? data)
      ? (data?.assignments ?? data?.schedule ?? data) as unknown[]
      : [];
    const tasks = (entries as Record<string, unknown>[]).map((entry, idx) => ({
      id: (entry.id as string | undefined) ?? `staff-${idx}`,
      description:
        (entry.description as string | undefined) ??
        (entry.name as string | undefined) ??
        (entry.staff as string | undefined) ??
        JSON.stringify(entry),
      status: ((entry.status as string | undefined) ?? "pending") as TaskCardData["status"],
      task_type: "staff",
    }));
    if (tasks.length === 0) return null;
    return {
      type: "task-list",
      taskListTitle: skill === "assign_staff" ? "Staff Assignments" : "Staff Schedule",
      tasks,
    };
  }

  // ── Confirmation skills ───────────────────────────────────────
  if (skill === "create_payment_link") {
    return {
      type: "confirmation",
      confirmTitle: "Payment Link Created",
      confirmDescription:
        (data?.url as string | undefined) ??
        (data?.link as string | undefined) ??
        (data?.message as string | undefined) ??
        "Your payment link is ready.",
      confirmVariant: "default",
    };
  }

  if (skill === "process_refund") {
    return {
      type: "confirmation",
      confirmTitle: "Refund Processed",
      confirmDescription:
        (data?.message as string | undefined) ??
        (data?.status as string | undefined) ??
        "The refund has been submitted for approval.",
      confirmVariant: "default",
    };
  }

  // ── Integration skills → connect cards ──────────────────────────
  if (skill === "connect_integration" || skill === "setup_integration") {
    return {
      type: "integration-connect" as const,
      integrationData: {
        integrationId: (data?.integration_id as string) || "google_calendar",
        name: (data?.name as string) || "Google Calendar",
        description: (data?.description as string) || "Connect your calendar",
        actionLabel: (data?.action_label as string) || "Connect",
        type: ((data?.input_type as string) || "oauth") as "oauth" | "phone" | "email" | "api_key",
        icon: data?.icon as string | undefined,
      },
    };
  }

  // ── Onboarding skills → interactive cards ───────────────────────
  if (skill === "onboard_selection" || skill === "industry_picker") {
    const options = (data?.options as Array<{id: string; label: string; emoji: string}>) || [];
    if (options.length > 0) {
      return {
        type: "selection" as const,
        selectionData: {
          title: (data?.title as string) || "Choose one",
          subtitle: data?.subtitle as string | undefined,
          options,
          onSelect: () => {},
        },
      };
    }
  }

  if (skill === "onboard_input" || skill === "collect_info") {
    return {
      type: "input-field" as const,
      inputData: {
        title: (data?.title as string) || "Enter your info",
        placeholder: (data?.placeholder as string) || "Type here...",
        type: ((data?.input_type as string) || "text") as "text" | "tel" | "email" | "url",
        submitLabel: (data?.submit_label as string) || "Continue",
        onSubmit: () => {},
        icon: data?.icon as string | undefined,
      },
    };
  }

  if (skill === "onboard_confirm" || skill === "review_setup") {
    const items = (data?.items as Array<{label: string; value: string; emoji?: string}>) || [];
    if (items.length > 0) {
      return {
        type: "confirm-summary" as const,
        confirmData: {
          title: (data?.title as string) || "Here's what I have:",
          items,
          onConfirm: () => {},
          onChange: () => {},
        },
      };
    }
  }

  if (skill === "onboard_complete" || skill === "setup_complete") {
    return {
      type: "success" as const,
      successData: {
        title: (data?.title as string) || "You're all set!",
        message: (data?.message as string) || "Your agent is ready to work.",
        nextAction: (data?.next_action as string) || "Start chatting",
      },
    };
  }

  if (skill === "setup_checklist" || skill === "getting_started") {
    const items = (data?.items as Array<{id: string; label: string; done: boolean; emoji?: string}>) || [];
    if (items.length > 0) {
      return {
        type: "checklist" as const,
        checklistData: {
          title: (data?.title as string) || "Get your agent ready",
          items,
          onItemClick: () => {},
        },
      };
    }
  }

  if (skill === "oauth_connect" || skill === "social_login") {
    return {
      type: "oauth" as const,
      oauthData: {
        title: (data?.title as string) || "Connect your account",
        onSelect: () => {},
        showEmailOption: (data?.show_email as boolean) || false,
      },
    };
  }

  // ── Health / status skills ────────────────────────────────────
  if (
    data &&
    typeof data === "object" &&
    ("health" in data || "status" in data || "system_status" in data)
  ) {
    const statusVal =
      (data.health as string | undefined) ??
      (data.system_status as string | undefined) ??
      (data.status as string | undefined) ??
      "unknown";
    const resolvedStatus: "healthy" | "degraded" | "unhealthy" =
      statusVal === "healthy" || statusVal === "ok" || statusVal === "green"
        ? "healthy"
        : statusVal === "degraded" || statusVal === "warning"
        ? "degraded"
        : "unhealthy";
    const score =
      typeof data.score === "number"
        ? (data.score as number)
        : resolvedStatus === "healthy"
        ? 90
        : resolvedStatus === "degraded"
        ? 55
        : 20;
    return {
      type: "health-status",
      healthData: {
        score,
        status: resolvedStatus,
        incidents: Array.isArray(data.incidents)
          ? (data.incidents as import("@/components/chat/cards/HealthStatusCard").HealthIncident[])
          : [],
        circuits: Array.isArray(data.circuits)
          ? (data.circuits as import("@/components/chat/cards/HealthStatusCard").CircuitStatus[])
          : [],
        driftLevel:
          (data.driftLevel as "NORMAL" | "ELEVATED" | "HIGH" | "CRITICAL" | undefined) ??
          "NORMAL",
        performanceGrade:
          (data.performanceGrade as string | undefined) ??
          (resolvedStatus === "healthy" ? "A" : resolvedStatus === "degraded" ? "C" : "F"),
        trend:
          (data.trend as "improving" | "stable" | "declining" | undefined) ?? "stable",
      },
    };
  }

  return null;
}

// ─── Contextual quick-reply generator ─────────────────────────────────────────

/**
 * Generates 2-4 contextual quick reply options based on the assistant's response.
 * Scans response text for topic keywords and returns relevant follow-up prompts.
 */
function generateQuickReplies(responseText: string): string[] {
  const lower = responseText.toLowerCase();

  // Appointment / scheduling context
  if (
    lower.includes("appointment") ||
    lower.includes("schedule") ||
    lower.includes("booking") ||
    lower.includes("calendar")
  ) {
    return ["Book now", "View schedule", "Cancel appointment"];
  }

  // Payment / billing context
  if (
    lower.includes("payment") ||
    lower.includes("invoice") ||
    lower.includes("billing") ||
    lower.includes("refund") ||
    lower.includes("balance")
  ) {
    return ["Send invoice", "Check balance", "Payment history"];
  }

  // Task context
  if (
    lower.includes("task") ||
    lower.includes("to-do") ||
    lower.includes("todo") ||
    lower.includes("assigned")
  ) {
    return ["Create task", "View tasks", "Mark complete"];
  }

  // Client / customer context
  if (
    lower.includes("client") ||
    lower.includes("customer") ||
    lower.includes("lead") ||
    lower.includes("contact")
  ) {
    return ["View clients", "Add new client", "Send follow-up"];
  }

  // Analytics / report context
  if (
    lower.includes("analytics") ||
    lower.includes("report") ||
    lower.includes("metric") ||
    lower.includes("revenue") ||
    lower.includes("forecast")
  ) {
    return ["Show full report", "Compare periods", "Export data"];
  }

  // Staff context
  if (
    lower.includes("staff") ||
    lower.includes("team") ||
    lower.includes("employee")
  ) {
    return ["Staff schedule", "Assign staff", "Team overview"];
  }

  // Default quick replies
  return ["What can you do?", "Book appointment", "Check status", "Help"];
}

// ─── Quick Action Chips ───────────────────────────────────────────────────────────────

const QUICK_CHIPS = [
  { label: "Morning pulse", prompt: "Give me my morning business pulse" },
  { label: "Book appointment", prompt: "Book a demo appointment for a new client this week" },
  { label: "Check tasks", prompt: "Show me my active tasks" },
  { label: "Send invoice", prompt: "Help me send an invoice to a client" },
] as const;

function QuickActionChips({ onSend }: { onSend: (prompt: string) => void }) {
  return (
    <div className="flex items-center gap-2 px-4 pb-2 pt-1 overflow-x-auto scrollbar-none flex-shrink-0">
      {QUICK_CHIPS.map((chip) => (
        <button
          key={chip.label}
          type="button"
          onClick={() => onSend(chip.prompt)}
          className="flex-shrink-0 px-3 py-1.5 rounded-full text-[13px] font-medium border border-[var(--stroke2)] bg-white/[0.04] text-[var(--foreground)] hover:bg-[var(--gold-500)]/10 hover:border-[var(--gold-500)]/30 hover:text-[var(--gold-500)] transition-colors duration-150 whitespace-nowrap min-h-[44px]"
        >
          {chip.label}
        </button>
      ))}
    </div>
  );
}

// ─── Chat Dashboard ────────────────────────────────────────────────────────────

function ChatDashboard() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user } = useAuthStore();
  const { agents, currentAgent, isLoading, fetchAgents, selectAgent } = useAgentStore();
  const {
    messages,
    isStreaming,
    appendUserMessage,
    appendAssistantMessage,
    appendStreamingAssistantMessage,
    finalizeLastAssistant,
    updateLastAssistant,
    setLastAssistantError,
    reset: resetChat,
  } = useChatStore();
  const {
    sessions,
    activeSessionId: storeActiveSessionId,
    loadSessions,
    createSession: storeCreateSession,
    switchSession,
    deleteSession: storeDeleteSession,
  } = useSessionStore();

  const [cardMap, setCardMap] = useState<Map<string, CardPayload[]>>(new Map());
  // isLoading: true between user send and first streaming token (drives skeleton)
  const [isSendingMessage, setIsSendingMessage] = useState(false);
  const [welcomeSent, setWelcomeSent] = useState(false);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const sessionInitRef = useRef(false);
  // Holds the active stream AbortController so we can cancel on navigation/unmount
  const abortControllerRef = useRef<AbortController | null>(null);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(
    null
  );

  // Dashboard stats (populated from welcome flow data)
  // Default activeSkills to 16 (all skills) — matches backend behavior where
  // null/empty enabled_skills means ALL skills are available.
  const [dashStats, setDashStats] = useState<DashboardStats>({
    conversations: 0,
    activeTasks: 0,
    activeSkills: 16,
    integrations: [],
  });

  // Ref to the chat textarea for focus-from-GettingStarted
  const chatInputAreaRef = useRef<HTMLDivElement>(null);

  const handleFocusChat = useCallback(() => {
    const textarea = chatInputAreaRef.current?.querySelector("textarea");
    textarea?.focus();
  }, []);

  // Cancel any in-flight stream on unmount (e.g. navigating away)
  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  // Boot: fetch agents + sessions
  useEffect(() => {
    fetchAgents();
    loadSessions();
  }, [fetchAgents, loadSessions]);

  // Select agent from ?agent=handle query parameter (e.g. /dashboard?agent=tgj)
  useEffect(() => {
    const handle = searchParams.get("agent");
    if (!handle || isLoading || agents.length === 0) return;
    // Skip if the correct agent is already selected
    if (currentAgent?.handle === handle) return;
    const match = agents.find((a) => a.handle === handle);
    if (match) {
      selectAgent(match.id);
    }
  }, [searchParams, isLoading, agents, currentAgent?.handle, selectAgent]);

  // Redirect to /claim if no agents
  useEffect(() => {
    if (!isLoading && agents.length === 0) {
      router.replace("/claim");
    }
  }, [isLoading, agents.length, router]);

  // ── Welcome flow ────────────────────────────────────────────────

  const sendWelcome = useCallback(async () => {
    if (!currentAgent || welcomeSent) return;
    setWelcomeSent(true);

    const agentId = currentAgent.id;
    const firstName = user?.email?.split("@")[0] ?? "there";

    let tasks: TaskResponse[] = [];
    let usage: TaskUsageResponse | null = null;
    let integrationNames: { name: string; connected: boolean }[] = [];
    try {
      const [tasksResult, usageResult, integrationStatus] = await Promise.all([
        listTasks({ agent_id: agentId }),
        getUsage(agentId),
        getIntegrationStatus(agentId),
      ]);
      tasks = tasksResult;
      usage = usageResult;
      integrationNames = [
        { name: "Google Calendar", connected: integrationStatus.google_calendar.connected },
        { name: "SendGrid", connected: integrationStatus.sendgrid.connected },
        { name: "Twilio", connected: integrationStatus.twilio.connected },
        { name: "Vapi", connected: integrationStatus.vapi.connected },
        { name: "DD Main Bridge", connected: integrationStatus.dd_main_bridge.connected },
      ];
    } catch {
      // Graceful fallback — integrationNames stays empty, stats degrade gracefully
    }

    const activeTasks = tasks.filter((t) =>
      ["pending", "in_progress"].includes(t.status)
    );
    const completedCount = tasks.filter(
      (t) => t.status === "completed"
    ).length;

    // Read sessions from store directly at call time to avoid stale closure.
    // Including `sessions` in the dependency array would cause sendWelcome to
    // re-create every time a session is added, which triggers the guard
    // `welcomeSent` to fire multiple times.
    const currentSessions = useSessionStore.getState().sessions;

    // Update header stats from live data
    setDashStats({
      conversations: currentSessions.length,
      activeTasks: activeTasks.length,
      activeSkills: 16,  // All skills enabled by default (backend injects all)
      integrations: integrationNames,
    });

    // Greeting with KPI cards
    const greeting = `Good ${getTimeOfDay()}, ${firstName}. Here's your overview.`;
    appendAssistantMessage(greeting);

    const msgs1 = useChatStore.getState().messages;
    const greetMsgId = msgs1[msgs1.length - 1]?.id;
    if (greetMsgId) {
      setCardMap((prev) => {
        const next = new Map(prev);
        next.set(greetMsgId, [
          {
            type: "kpi-cards",
            kpiMetrics: [
              {
                label: "Active Tasks",
                value: activeTasks.length,
                trend: activeTasks.length > 0 ? "up" : "flat",
              },
              {
                label: "Completed",
                value: completedCount,
                trend: completedCount > 0 ? "up" : "flat",
              },
              {
                label: "This Month",
                value: usage?.tasks_total ?? 0,
                trend: "flat",
              },
            ],
          },
        ]);
        return next;
      });
    }

    // Task list or quick replies
    if (activeTasks.length > 0) {
      const taskMsg = `You have ${activeTasks.length} active task${activeTasks.length !== 1 ? "s" : ""}:`;
      appendAssistantMessage(taskMsg);

      const msgs2 = useChatStore.getState().messages;
      const taskMsgId = msgs2[msgs2.length - 1]?.id;
      if (taskMsgId) {
        setCardMap((prev) => {
          const next = new Map(prev);
          next.set(taskMsgId, [
            {
              type: "task-list",
              taskListTitle: "Active Tasks",
              tasks: activeTasks.slice(0, 10).map((t) => ({
                id: t.id,
                description: t.description,
                status: t.status,
                task_type: t.task_type,
              })),
            },
            {
              type: "quick-replies",
              quickReplies: [
                "New task",
                "Show all tasks",
                "Check usage",
                "Agent settings",
              ],
            },
          ]);
          return next;
        });
      }
    } else {
      const noTaskMsg =
        "No active tasks right now. What would you like to do?";
      appendAssistantMessage(noTaskMsg);

      const msgs3 = useChatStore.getState().messages;
      const noTaskMsgId = msgs3[msgs3.length - 1]?.id;
      if (noTaskMsgId) {
        setCardMap((prev) => {
          const next = new Map(prev);
          next.set(noTaskMsgId, [
            {
              type: "quick-replies",
              quickReplies: [
                "New task",
                "Check usage",
                "Agent settings",
                "What can you do?",
              ],
            },
          ]);
          return next;
        });
      }
    }
  }, [currentAgent, welcomeSent, user, appendAssistantMessage]);

  useEffect(() => {
    if (currentAgent && !welcomeSent && messages.length === 0) {
      sendWelcome();
    }
  }, [currentAgent, welcomeSent, messages.length, sendWelcome]);

  // ── Session management ──────────────────────────────────────────

  useEffect(() => {
    if (!currentAgent || sessionInitRef.current || activeSessionId) return;
    sessionInitRef.current = true;

    (async () => {
      try {
        const allSessions = await listSessions();
        const active = allSessions.find((s) => s.status === "active");
        if (active) {
          setActiveSessionId(active.session_id);
        } else {
          const created = await createSession({ agent_id: currentAgent.id });
          setActiveSessionId(created.session_id);
        }
      } catch {
        sessionInitRef.current = false;
      }
    })();
  }, [currentAgent, activeSessionId]);

  const ensureSession = useCallback(async (): Promise<string> => {
    if (activeSessionId) return activeSessionId;
    const created = await createSession({ agent_id: currentAgent?.id });
    setActiveSessionId(created.session_id);
    // Wire Dexie persistence to this session
    useChatStore.getState().setActiveSession(created.session_id);
    return created.session_id;
  }, [activeSessionId, currentAgent]);

  // ── Message handlers ────────────────────────────────────────────

  // Ref tracking accumulated token content during a stream so RAF callbacks
  // always see the latest value without stale closures.
  const streamContentRef = useRef<string>("");

  // Stable ref to handleSend so card callbacks created inside onDone can
  // call the latest version without stale-closure issues.
  const handleSendRef = useRef<(content: string) => void>(() => {});

  const handleSend = useCallback(
    async (content: string) => {
      // Abort any previous in-flight stream before starting a new one
      abortControllerRef.current?.abort();

      appendUserMessage(content);
      appendStreamingAssistantMessage();
      setIsSendingMessage(true);

      let sessionId: string;
      try {
        sessionId = await ensureSession();
      } catch (err: unknown) {
        const msg =
          err instanceof Error ? err.message : "Failed to start session";
        setLastAssistantError(`Error: ${msg}`);
        return;
      }

      const agentHandle = currentAgent?.handle;
      if (!agentHandle) {
        setLastAssistantError("Error: No agent selected — cannot send message");
        return;
      }

      // Reset accumulated content for this stream
      streamContentRef.current = "";

      const controller = sendMessageStream(agentHandle, sessionId, content, {
        onToken: (token: string) => {
          // Accumulate tokens and update the store with the running content
          setIsSendingMessage(false);
          streamContentRef.current += token;
          updateLastAssistant(streamContentRef.current);
        },
        onDone: (payload) => {
          setIsSendingMessage(false);
          // Use the server's authoritative full_response (handles any race
          // between RAF batching and the done event)
          finalizeLastAssistant({
            content: payload.full_response || streamContentRef.current,
            governance_decision: payload.halted ? "HALT" : "PROCEED",
          });
          streamContentRef.current = "";

          // Render a rich card if the skill returned structured data
          const msgs = useChatStore.getState().messages;
          const lastMsgId = msgs[msgs.length - 1]?.id;

          if (payload.action) {
            const card = mapSkillResultToCard(payload.action);
            if (card && lastMsgId) {
              // Patch placeholder callbacks with real handlers that send
              // user interactions as chat messages through handleSendRef
              // (ref avoids stale closure since callbacks fire later)
              if (card.selectionData) {
                card.selectionData.onSelect = (optionId: string) => void handleSendRef.current(optionId);
              }
              if (card.inputData) {
                card.inputData.onSubmit = (value: string) => void handleSendRef.current(value);
              }
              if (card.oauthData) {
                card.oauthData.onSelect = (providerId: string) => {
                  const id = providerId === "google" ? "google_calendar" : providerId === "microsoft" ? "microsoft_calendar" : "apple_calendar";
                  void handleSendRef.current(`Connect ${id}`);
                };
              }
              if (card.confirmData) {
                card.confirmData.onConfirm = () => void handleSendRef.current("Looks good, let's go!");
                card.confirmData.onChange = () => void handleSendRef.current("I want to change something");
              }
              if (card.checklistData) {
                card.checklistData.onItemClick = (itemId: string) => void handleSendRef.current(`Set up ${itemId}`);
              }

              setCardMap((prev) => {
                const next = new Map(prev);
                next.set(lastMsgId, [...(next.get(lastMsgId) ?? []), card]);
                return next;
              });

              // Fire notification for completed agent actions
              const { skill, action: actionName } = payload.action;
              const addNotification = useNotificationStore.getState().addNotification;
              if (skill && actionName) {
                const notifType =
                  skill.includes("book") || skill.includes("schedule") ? "booking" as const :
                  skill.includes("payment") || skill.includes("invoice") ? "payment" as const :
                  skill.includes("task") ? "task" as const :
                  skill.includes("message") || skill.includes("chat") ? "message" as const :
                  "system" as const;

                addNotification({
                  type: notifType,
                  title: `Agent completed: ${actionName}`,
                  body: payload.full_response?.slice(0, 120) || `${skill} → ${actionName}`,
                  agentHandle: currentAgent?.handle,
                  actionUrl: "/dashboard",
                });
              }
            }
          }

          // Always append contextual quick replies after every assistant message
          if (lastMsgId) {
            const responseText =
              payload.full_response || streamContentRef.current;
            const quickReplies = generateQuickReplies(responseText);
            setCardMap((prev) => {
              const next = new Map(prev);
              const existing = next.get(lastMsgId) ?? [];
              // Don't add if quick-replies already present (e.g. from skill mapping)
              const hasQR = existing.some((c) => c.type === "quick-replies");
              if (!hasQR) {
                next.set(lastMsgId, [
                  ...existing,
                  { type: "quick-replies", quickReplies },
                ]);
              }
              return next;
            });
          }
        },
        onError: (errorMessage: string) => {
          setIsSendingMessage(false);
          // If we have partial content, finalize what arrived so far;
          // otherwise fall back to the non-streaming endpoint.
          if (streamContentRef.current) {
            finalizeLastAssistant({
              content: streamContentRef.current,
            });
            streamContentRef.current = "";
          } else {
            // Fall back to the non-streaming endpoint
            void sendMessage(sessionId, content)
              .then((res) => {
                finalizeLastAssistant({
                  content: res.content,
                  model: res.model_used,
                  tokens_used: res.input_tokens + res.output_tokens,
                  governance_decision: res.governance_decision as
                    | "PROCEED"
                    | "REVIEW"
                    | "HALT",
                });
                // Wire action cards from REST fallback response
                if (res.actions && res.actions.length > 0) {
                  const msgs = useChatStore.getState().messages;
                  const lastId = msgs[msgs.length - 1]?.id;
                  if (lastId) {
                    const newCards: CardPayload[] = [];
                    for (const ac of res.actions) {
                      const card = mapSkillResultToCard({
                        skill: ac.skill,
                        action: ac.action,
                        result: ac.data,
                      });
                      if (card) newCards.push(card);
                    }
                    if (newCards.length > 0) {
                      setCardMap((prev) => {
                        const next = new Map(prev);
                        next.set(lastId, [...(next.get(lastId) ?? []), ...newCards]);
                        return next;
                      });
                    }
                  }
                }
              })
              .catch((fbErr: unknown) => {
                const fbMsg =
                  fbErr instanceof Error
                    ? fbErr.message
                    : "Failed to get response";
                setLastAssistantError(`Error: ${fbMsg}`);
              });
          }
        },
      });

      abortControllerRef.current = controller;
    },
    [
      appendUserMessage,
      appendStreamingAssistantMessage,
      finalizeLastAssistant,
      updateLastAssistant,
      setLastAssistantError,
      ensureSession,
      currentAgent,
      setIsSendingMessage,
    ]
  );

  // Keep ref in sync so card callbacks always use the latest handleSend
  handleSendRef.current = handleSend;

  const handleQuickReply = useCallback(
    (reply: string) => handleSend(reply),
    [handleSend]
  );

  const handleTaskAction = useCallback(
    (action: "start" | "edit" | "cancel", taskId: string) =>
      handleSend(`${action} task ${taskId}`),
    [handleSend]
  );

  // Integration connect from chat stream cards
  const handleIntegrationConnect = useCallback(
    async (integrationId: string, inputValue?: string) => {
      try {
        // For OAuth integrations, use Nango Connect UI
        const oauthIntegrations = [
          "google_calendar", "microsoft_calendar", "apple_calendar",
          "cronofy", "zapier", "stripe", "hubspot", "slack",
        ];
        if (oauthIntegrations.includes(integrationId)) {
          // Dynamic import to avoid loading Nango until needed
          const { post: apiPost } = await import("@/services/api/client");
          const result = await apiPost<{ token?: string; public_key?: string; error?: string }>(
            "/api/v1/integrations/nango/connect",
            { integration_id: integrationId, agent_id: currentAgent?.id },
          );
          if (result.token) {
            const { ConnectUI } = await import("@nangohq/frontend");
            const connectUI = new ConnectUI({ sessionToken: result.token });
            connectUI.open();
          }
        }

        // For phone/email, the card already collected input — send to backend
        if (inputValue) {
          handleSend(`Connect ${integrationId} with ${inputValue}`);
        }

        // Notify success
        const addNotification = useNotificationStore.getState().addNotification;
        addNotification({
          type: "integration",
          title: `${integrationId.replace(/_/g, " ")} connected`,
          body: "Your agent can now use this service.",
          agentHandle: currentAgent?.handle,
        });
      } catch (err) {
        console.error("Integration connect failed:", err);
      }
    },
    [currentAgent, handleSend]
  );

  // Selection card callback — user picked an option
  const handleSelectionSelect = useCallback(
    (optionId: string) => handleSend(optionId),
    [handleSend]
  );

  // Input card callback — user submitted a value
  const handleInputSubmit = useCallback(
    (value: string) => handleSend(value),
    [handleSend]
  );

  // OAuth card callback — user selected a provider
  const handleOAuthSelect = useCallback(
    (providerId: string) => handleIntegrationConnect(providerId === "google" ? "google_calendar" : providerId === "microsoft" ? "microsoft_calendar" : "apple_calendar"),
    [handleIntegrationConnect]
  );

  // Confirm card callbacks
  const handleConfirmApprove = useCallback(
    () => handleSend("Looks good, let's go!"),
    [handleSend]
  );

  const handleConfirmChange = useCallback(
    () => handleSend("I want to change something"),
    [handleSend]
  );

  // Checklist item click
  const handleChecklistClick = useCallback(
    (itemId: string) => handleSend(`Set up ${itemId}`),
    [handleSend]
  );

  // Success next action
  const handleSuccessNext = useCallback(
    () => handleSend("Let's get started!"),
    [handleSend]
  );

  // Retry a failed message — find the last user message before the error bubble
  const handleRetry = useCallback(
    (_messageId: string) => {
      const allMessages = useChatStore.getState().messages;
      // Walk back from the error message to find the preceding user message
      for (let i = allMessages.length - 1; i >= 0; i--) {
        if (allMessages[i]?.role === "user") {
          const userContent = allMessages[i]?.content;
          if (userContent) {
            // Remove the error assistant bubble then re-send
            void handleSend(userContent);
          }
          break;
        }
      }
    },
    [handleSend]
  );

  // ── Session panel actions ───────────────────────────────────────

  const handleNewSession = useCallback(async () => {
    try {
      const session = await storeCreateSession();
      setActiveSessionId(session.session_id);
      useChatStore.getState().setActiveSession(session.session_id);
      resetChat();
      setWelcomeSent(false);
      setCardMap(new Map());
    } catch {
      // handled in store
    }
  }, [storeCreateSession, resetChat]);

  const handleSwitchSession = useCallback(
    async (sessionId: string) => {
      switchSession(sessionId);
      setActiveSessionId(sessionId);
      // Load persisted messages from Dexie IndexedDB
      await useChatStore.getState().loadSession(sessionId);
      setWelcomeSent(true); // Don't re-send welcome for existing sessions
      setCardMap(new Map());
    },
    [switchSession]
  );

  const handleDeleteSession = useCallback(
    async (sessionId: string) => {
      if (deletingSessionId === sessionId) {
        await storeDeleteSession(sessionId);
        setDeletingSessionId(null);
        if (activeSessionId === sessionId) {
          const remaining = sessions.filter(
            (s) => s.session_id !== sessionId
          );
          if (remaining.length > 0) {
            handleSwitchSession(remaining[0].session_id);
          }
        }
      } else {
        setDeletingSessionId(sessionId);
        setTimeout(() => setDeletingSessionId(null), 3000);
      }
    },
    [
      deletingSessionId,
      activeSessionId,
      sessions,
      storeDeleteSession,
      handleSwitchSession,
    ]
  );

  // ── Render ──────────────────────────────────────────────────────

  if (isLoading && agents.length === 0) {
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
          <MessageSquare className="h-7 w-7 text-[var(--gold-500)]" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-[var(--foreground)] mb-1">
            Create your first agent
          </h2>
          <p className="text-sm text-[var(--color-muted)]">
            Claim an agent to start chatting and managing your business.
          </p>
        </div>
        <button
          onClick={() => router.replace("/claim")}
          className="px-5 py-2.5 rounded-xl bg-[var(--gold-500)] text-[#07111c] text-sm font-semibold hover:bg-[var(--gold-600)] transition-colors"
        >
          Create your agent
        </button>
      </div>
    );
  }

  return (
    <div className="h-full flex overflow-hidden">
      {/* ── Chat-first fullscreen area ────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Agent command bar — stats, status, notifications, settings */}
        <DashboardHeader
          agentName={currentAgent.name}
          handle={currentAgent.handle}
          status="active"
          stats={dashStats}
        />

        {/* AI Disclosure — Oregon SB 1546 / FTC compliance */}
        <AIDisclosureBanner sessionId={activeSessionId} />

        {/* Getting started guide — shows for new agents (< 5 conversations) */}
        <GettingStarted
          handle={currentAgent.handle}
          conversationCount={sessions.length}
          onFocusChat={handleFocusChat}
          hasCustomizedSettings={
            !!(currentAgent.industry_type || currentAgent.template_id)
          }
          hasIntegrations={dashStats.integrations.some((i) => i.connected)}
        />

        {/* ── Welcome state vs Active chat ──────────────────────── */}
        {(() => {
          // Welcome state: only system-generated messages, no user input yet
          const hasUserMessage = messages.some((m) => m.role === "user");
          const isWelcomeState = !hasUserMessage && !isStreaming;

          if (isWelcomeState) {
            // ── Centered layout like Grok/Gemini empty state ──
            // Mobile: brand at top, pills above input, input at bottom
            // Desktop: everything centered vertically
            return (
              <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
                {/* Spacer — pushes content to center on desktop, top on mobile */}
                <div className="flex-1" />

                {/* Brand / Agent identity */}
                <div className="flex flex-col items-center gap-3 px-4 mb-6 lg:mb-8">
                  <div className="h-14 w-14 lg:h-16 lg:w-16 rounded-2xl bg-[var(--gold-500)]/10 border border-[var(--gold-500)]/20 flex items-center justify-center">
                    <span className="text-xl lg:text-2xl font-heading font-bold text-[var(--gold-500)]">
                      {currentAgent.name.charAt(0).toUpperCase()}
                    </span>
                  </div>
                  <div className="text-center">
                    <h2 className="text-lg lg:text-xl font-heading font-bold text-[var(--foreground)]">
                      {currentAgent.name}
                    </h2>
                    <p className="text-sm text-[var(--color-muted)] mt-1">
                      Your AI agent is ready
                    </p>
                    <p className="text-xs text-[var(--color-muted)] mt-2 px-3 py-1.5 rounded-full bg-white/5 border border-[var(--stroke)]/50 inline-flex items-center gap-1.5">
                      <span className="text-[var(--gold-500)] font-medium">@{currentAgent.handle}</span>
                      <span>&mdash; shareable link</span>
                    </p>
                  </div>
                </div>

                {/* Spacer — pushes input down on desktop */}
                <div className="flex-1" />

                {/* Try This First — guided prompt cards for new users */}
                <div className="px-4 mb-4 max-w-2xl mx-auto w-full">
                  <p className="text-xs text-[var(--color-muted)] text-center mb-3 font-medium tracking-wide uppercase opacity-70">
                    Try asking your agent to&hellip;
                  </p>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-2">
                    {[
                      {
                        icon: <Calendar className="h-4 w-4 text-[var(--gold-500)]" aria-hidden="true" />,
                        title: "Book a demo appointment",
                        subtitle: "Schedule and confirm with a client",
                        prompt: "Book a demo appointment for a new client this week",
                      },
                      {
                        icon: <Mail className="h-4 w-4 text-[var(--gold-500)]" aria-hidden="true" />,
                        title: "Draft a follow-up email",
                        subtitle: "Write and send a professional follow-up",
                        prompt: "Draft a follow-up email to a lead I met yesterday",
                      },
                      {
                        icon: <BarChart2 className="h-4 w-4 text-[var(--gold-500)]" aria-hidden="true" />,
                        title: "Create a sales report",
                        subtitle: "Summarize revenue and top opportunities",
                        prompt: "Create a sales report summarizing this month's performance",
                      },
                      {
                        icon: <Search className="h-4 w-4 text-[var(--gold-500)]" aria-hidden="true" />,
                        title: "Research a competitor",
                        subtitle: "Find key insights about a rival company",
                        prompt: "Research my top competitor and summarize their strengths",
                      },
                    ].map((card) => (
                      <button
                        key={card.title}
                        type="button"
                        onClick={() => handleSend(card.prompt)}
                        className="group flex flex-col gap-1.5 rounded-xl border border-[var(--stroke2)] bg-white/3 hover:bg-white/6 hover:border-[var(--gold-500)]/30 transition-all duration-150 text-left px-3.5 py-3 min-h-[44px]"
                      >
                        <span className="flex items-center gap-2">
                          {card.icon}
                          <span className="text-sm font-medium text-[var(--foreground)] leading-snug line-clamp-1">
                            {card.title}
                          </span>
                        </span>
                        <span className="text-[11px] text-[var(--color-muted)] leading-snug pl-6 line-clamp-1">
                          {card.subtitle}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Quick action chips */}
                <QuickActionChips onSend={handleSend} />

                {/* Input bar — bottom anchored, full width like Gemini/Grok */}
                <div className="bg-[var(--ink-950)] flex-shrink-0" ref={chatInputAreaRef}>
                  <div className="flex items-end max-w-2xl mx-auto w-full px-4">
                    <div className="flex-1 min-w-0 [&>div]:border-t-0 [&>div]:bg-transparent [&>div]:backdrop-blur-none">
                      <ChatInput
                        onSend={handleSend}
                        disabled={isStreaming}
                        placeholder={`Message ${currentAgent.name}...`}
                      />
                    </div>
                    <div className="flex-shrink-0 flex items-end pb-2 pl-1">
                      <VoiceButton
                        onTranscript={handleSend}
                        disabled={isStreaming}
                        size={44}
                      />
                    </div>
                  </div>
                  <p className="text-center text-[11px] text-[var(--color-muted)] opacity-60 pb-1.5 px-4">
                    Responses may be inaccurate. Verify important information.
                  </p>
                </div>
              </div>
            );
          }

          // ── Active chat: standard bottom-anchored stream like Claude ──
          // Wrapped in a flex column that fills remaining height (min-h-0
          // prevents the flex child from overflowing on mobile browsers).
          return (
            <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
              <ChatStream
                messages={messages}
                cards={cardMap}
                isStreaming={isStreaming}
                isLoading={isSendingMessage}
                onQuickReply={handleQuickReply}
                onTaskAction={handleTaskAction}
                onRetry={handleRetry}
                onIntegrationConnect={handleIntegrationConnect}
              />

              {/* Quick action chips */}
              <QuickActionChips onSend={handleSend} />

              {/* Input bar — bottom-anchored */}
              <div className="bg-[var(--ink-950)] flex-shrink-0" ref={chatInputAreaRef}>
                <div className="flex items-end max-w-3xl mx-auto w-full px-4">
                  <div className="flex-1 min-w-0 [&>div]:border-t-0 [&>div]:bg-transparent [&>div]:backdrop-blur-none">
                    <ChatInput
                      onSend={handleSend}
                      disabled={isStreaming}
                      placeholder={`Message ${currentAgent.name}...`}
                    />
                  </div>
                  <div className="flex-shrink-0 flex items-end pb-2 pl-1">
                    <VoiceButton
                      onTranscript={handleSend}
                      disabled={isStreaming}
                      size={44}
                    />
                  </div>
                </div>
                <p className="text-center text-[11px] text-[var(--color-muted)] opacity-60 pb-1.5 px-4">
                  Responses may be inaccurate. Verify important information.
                </p>
              </div>
            </div>
          );
        })()}
      </div>
    </div>
  );
}

function getTimeOfDay(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "morning";
  if (hour < 17) return "afternoon";
  return "evening";
}
