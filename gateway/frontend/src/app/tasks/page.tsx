"use client";

/**
 * Tasks page — personal agent task management.
 *
 * - Protected route (redirects to /login if not authenticated)
 * - Filter tabs: All / Pending / In Progress / Completed
 * - Task list with description, type badge, status badge, created date
 * - Floating "New Task" button
 * - Task creation modal (agent selector + type + description)
 * - Calls real API endpoints via platformService
 */

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Plus,
  X,
  AlertCircle,
  ClipboardList,
  ChevronDown,
} from "lucide-react";
import { useAgentStore } from "@/store/agentStore";
import {
  listTasks,
  createTask,
  cancelTask,
} from "@/services/api/platformService";
import type { TaskResponse } from "@/services/api/platformService";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { formatRelativeTime } from "@/lib/utils";

// ─── Types / constants ────────────────────────────────────────────────────────

type FilterTab = "all" | "pending" | "in_progress" | "completed";

const FILTER_TABS: { label: string; value: FilterTab }[] = [
  { label: "All", value: "all" },
  { label: "Pending", value: "pending" },
  { label: "In Progress", value: "in_progress" },
  { label: "Completed", value: "completed" },
];

const TASK_TYPES = [
  "research",
  "booking",
  "reminder",
  "errand",
  "purchase",
  "email",
] as const;

type TaskType = (typeof TASK_TYPES)[number];

// ─── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: TaskResponse["status"] }) {
  const styles: Record<TaskResponse["status"], string> = {
    pending: "bg-yellow-500/15 text-yellow-400 border-yellow-500/20",
    in_progress: "bg-blue-500/15 text-blue-400 border-blue-500/20",
    completed: "bg-green-500/15 text-green-400 border-green-500/20",
    cancelled: "bg-white/8 text-[var(--color-muted)] border-white/10",
    failed: "bg-red-500/15 text-red-400 border-red-500/20",
  };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs border font-medium whitespace-nowrap ${styles[status]}`}
    >
      {status.replace("_", " ")}
    </span>
  );
}

// ─── Type badge ───────────────────────────────────────────────────────────────

function TypeBadge({ type }: { type: string }) {
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs bg-white/8 border border-[var(--stroke)] text-[var(--color-muted)] capitalize">
      {type}
    </span>
  );
}

// ─── New Task Modal ───────────────────────────────────────────────────────────

interface NewTaskModalProps {
  onClose: () => void;
  onCreated: (task: TaskResponse) => void;
}

function NewTaskModal({ onClose, onCreated }: NewTaskModalProps) {
  const { agents, currentAgent } = useAgentStore();
  const [agentId, setAgentId] = useState(currentAgent?.id ?? agents[0]?.id ?? "");
  const [taskType, setTaskType] = useState<TaskType>("research");
  const [description, setDescription] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!agentId || !description.trim()) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const task = await createTask({
        agent_id: agentId,
        task_type: taskType,
        description: description.trim(),
      });
      onCreated(task);
      onClose();
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to create task";
      setError(detail);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

      {/* Sheet */}
      <div className="glass-panel w-full max-w-md z-10 p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-base font-semibold text-[var(--foreground)]">
            New Task
          </h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-[var(--color-muted)] hover:text-[var(--foreground)] hover:bg-white/5"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {/* Agent selector (only if multiple agents) */}
          {agents.length > 1 && (
            <div>
              <label className="block text-sm font-medium text-[var(--foreground)] mb-1.5">
                Agent
              </label>
              <div className="relative">
                <select
                  value={agentId}
                  onChange={(e) => setAgentId(e.target.value)}
                  className="w-full appearance-none px-3 py-2.5 rounded-lg bg-white/5 border border-[var(--stroke)] text-[var(--foreground)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--gold-500)]"
                  required
                >
                  {agents.map((a) => (
                    <option key={a.id} value={a.id} className="bg-[#0a1624]">
                      @{a.handle} — {a.name}
                    </option>
                  ))}
                </select>
                <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--color-muted)] pointer-events-none" />
              </div>
            </div>
          )}

          {/* Task type */}
          <div>
            <label className="block text-sm font-medium text-[var(--foreground)] mb-1.5">
              Task type
            </label>
            <div className="relative">
              <select
                value={taskType}
                onChange={(e) => setTaskType(e.target.value as TaskType)}
                className="w-full appearance-none px-3 py-2.5 rounded-lg bg-white/5 border border-[var(--stroke)] text-[var(--foreground)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--gold-500)] capitalize"
              >
                {TASK_TYPES.map((t) => (
                  <option key={t} value={t} className="bg-[#0a1624] capitalize">
                    {t.charAt(0).toUpperCase() + t.slice(1)}
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--color-muted)] pointer-events-none" />
            </div>
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-[var(--foreground)] mb-1.5">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe what you need the agent to do…"
              rows={3}
              maxLength={500}
              required
              className="w-full px-3 py-2.5 rounded-lg bg-white/5 border border-[var(--stroke)] text-[var(--foreground)] text-sm placeholder:text-[var(--color-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--gold-500)] resize-none"
            />
            <p className="text-xs text-[var(--color-muted)] mt-1 text-right">
              {description.length}/500
            </p>
          </div>

          <Button
            type="submit"
            variant="gold"
            isLoading={isSubmitting}
            disabled={!description.trim() || !agentId}
          >
            Create Task
          </Button>
        </form>
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function TasksPage() {
  return (
    <ProtectedRoute>
      <AppShell>
        <TasksContent />
      </AppShell>
    </ProtectedRoute>
  );
}

function TasksContent() {
  const router = useRouter();
  const { agents, currentAgent, isLoading: agentsLoading, fetchAgents } =
    useAgentStore();

  const [tasks, setTasks] = useState<TaskResponse[]>([]);
  const [activeFilter, setActiveFilter] = useState<FilterTab>("all");
  const [loadingTasks, setLoadingTasks] = useState(false);
  const [taskError, setTaskError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [cancellingId, setCancellingId] = useState<string | null>(null);

  // Fetch agents on mount
  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  // Redirect to /claim if no agents
  useEffect(() => {
    if (!agentsLoading && agents.length === 0) {
      router.replace("/claim");
    }
  }, [agentsLoading, agents.length, router]);

  // Load tasks for current agent
  const loadTasks = useCallback(async () => {
    if (!currentAgent) return;
    setLoadingTasks(true);
    setTaskError(null);
    try {
      const data = await listTasks({ agent_id: currentAgent.id });
      setTasks(data);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to load tasks";
      setTaskError(detail);
    } finally {
      setLoadingTasks(false);
    }
  }, [currentAgent]);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  const handleCancel = async (id: string) => {
    setCancellingId(id);
    try {
      await cancelTask(id);
      setTasks((prev) =>
        prev.map((t) => (t.id === id ? { ...t, status: "cancelled" as const } : t))
      );
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to cancel task. Please try again.";
      setTaskError(detail);
    } finally {
      setCancellingId(null);
    }
  };

  const handleTaskCreated = (task: TaskResponse) => {
    setTasks((prev) => [task, ...prev]);
  };

  // Filtered view
  const visibleTasks =
    activeFilter === "all"
      ? tasks
      : tasks.filter((t) => t.status === activeFilter);

  if (agentsLoading && agents.length === 0) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <span className="spinner text-[var(--gold-500)]" />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto scrollbar-thin px-4 pt-6 pb-6 max-w-3xl mx-auto">
      {/* Back navigation */}
      <PageHeader title="Tasks" />

      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-xl font-bold text-[var(--foreground)]">Tasks</h1>
          {currentAgent && (
            <p className="text-xs text-[var(--color-muted)] mt-0.5">
              @{currentAgent.handle}
            </p>
          )}
        </div>
        <Button variant="outline" size="sm" onClick={loadTasks} disabled={loadingTasks}>
          {loadingTasks ? (
            <span className="spinner h-3.5 w-3.5" />
          ) : (
            "Refresh"
          )}
        </Button>
      </div>

      {/* Error */}
      {taskError && (
        <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2">
          <AlertCircle className="h-4 w-4 flex-shrink-0" />
          {taskError}
          <button onClick={loadTasks} className="ml-auto text-xs underline">
            retry
          </button>
        </div>
      )}

      {/* Filter tabs */}
      <div className="flex gap-1 mb-5 overflow-x-auto pb-1 scrollbar-thin">
        {FILTER_TABS.map((tab) => {
          const count =
            tab.value === "all"
              ? tasks.length
              : tasks.filter((t) => t.status === tab.value).length;
          return (
            <button
              key={tab.value}
              onClick={() => setActiveFilter(tab.value)}
              className={`flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-150 ${
                activeFilter === tab.value
                  ? "bg-[var(--gold-500)] text-[#07111c]"
                  : "bg-white/5 text-[var(--color-muted)] hover:bg-white/8"
              }`}
            >
              {tab.label}
              {count > 0 && (
                <span
                  className={`text-xs px-1.5 py-0.5 rounded-full ${
                    activeFilter === tab.value
                      ? "bg-[#07111c]/20"
                      : "bg-white/10"
                  }`}
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Task list */}
      {loadingTasks ? (
        <div className="flex items-center justify-center py-12">
          <span className="spinner text-[var(--color-muted)]" />
        </div>
      ) : visibleTasks.length === 0 ? (
        <div className="glass-panel p-8 text-center">
          <ClipboardList className="h-10 w-10 text-[var(--color-muted)] mx-auto mb-3" />
          <p className="text-sm text-[var(--foreground)] font-medium">
            {activeFilter === "all" ? "No tasks yet" : `No ${activeFilter.replace("_", " ")} tasks`}
          </p>
          <p className="text-xs text-[var(--color-muted)] mt-1 max-w-xs mx-auto">
            {activeFilter === "all"
              ? "Your agent will create tasks as it handles customer requests. You can also tap the + button below to create one manually."
              : "Try a different filter or create a new task."}
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {visibleTasks.map((task) => (
            <div
              key={task.id}
              className="glass-panel p-4 flex flex-col gap-2"
            >
              {/* Top row: type + status */}
              <div className="flex items-center gap-2">
                <TypeBadge type={task.task_type} />
                <StatusBadge status={task.status} />
              </div>

              {/* Description */}
              <p className="text-[15px] text-[var(--foreground)] leading-relaxed">
                {task.description}
              </p>

              {/* Result (if any) */}
              {task.result_json && (
                <p className="text-xs text-[var(--color-muted)] italic border-l-2 border-[var(--gold-500)]/40 pl-2">
                  {task.result_json}
                </p>
              )}

              {/* Footer: time + cancel */}
              <div className="flex items-center justify-between">
                <span className="text-xs text-[var(--color-muted)]">
                  {formatRelativeTime(new Date(task.created_at))}
                </span>
                {["pending", "in_progress"].includes(task.status) && (
                  <button
                    onClick={() => handleCancel(task.id)}
                    disabled={cancellingId === task.id}
                    className="text-xs text-[var(--color-muted)] hover:text-red-400 transition-colors disabled:opacity-50"
                  >
                    {cancellingId === task.id ? "Cancelling…" : "Cancel"}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* FAB — New Task */}
      {/* bottom-20 clears the mobile bottom nav bar (h-14 = 56px + safe area) */}
      <button
        onClick={() => setShowModal(true)}
        className="fixed bottom-20 right-4 lg:bottom-6 lg:right-6 h-14 w-14 rounded-full bg-[var(--gold-500)] text-[#07111c] shadow-lg flex items-center justify-center gold-glow hover:bg-[var(--gold-600)] transition-colors z-40"
        aria-label="New task"
      >
        <Plus className="h-6 w-6" />
      </button>

      {/* Modal */}
      {showModal && (
        <NewTaskModal
          onClose={() => setShowModal(false)}
          onCreated={handleTaskCreated}
        />
      )}
    </div>
  );
}
