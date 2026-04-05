"use client";

/**
 * Single task card with status badge + inline action buttons.
 */

import { Clock, Play, Pencil, X, CheckCircle } from "lucide-react";

export interface TaskCardData {
  id: string;
  description: string;
  status: "pending" | "in_progress" | "completed" | "cancelled" | "failed";
  task_type?: string;
  due_date?: string;
}

interface TaskCardProps {
  task: TaskCardData;
  onAction?: (action: "start" | "edit" | "cancel", taskId: string) => void;
  className?: string;
}

const statusStyles: Record<string, { bg: string; text: string; label: string }> = {
  pending: { bg: "bg-yellow-500/15", text: "text-yellow-400", label: "Pending" },
  in_progress: { bg: "bg-blue-500/15", text: "text-blue-400", label: "In Progress" },
  completed: { bg: "bg-green-500/15", text: "text-green-400", label: "Completed" },
  cancelled: { bg: "bg-white/10", text: "text-[var(--color-muted)]", label: "Cancelled" },
  failed: { bg: "bg-red-500/15", text: "text-red-400", label: "Failed" },
};

export function TaskCard({ task, onAction, className = "" }: TaskCardProps) {
  const style = statusStyles[task.status] ?? statusStyles.pending;
  const isActive = task.status === "pending" || task.status === "in_progress";

  return (
    <div className={`glass-panel-gold p-4 card-enter ${className}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-heading font-semibold text-[var(--foreground)] truncate">
            {task.description}
          </p>
          <div className="flex items-center gap-2 mt-1.5">
            <span
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${style.bg} ${style.text} border-current/20`}
            >
              {task.status === "completed" ? (
                <CheckCircle className="h-3 w-3" />
              ) : (
                <Clock className="h-3 w-3" />
              )}
              {style.label}
            </span>
            {task.task_type && (
              <span className="text-xs text-[var(--color-muted)]">
                {task.task_type}
              </span>
            )}
            {task.due_date && (
              <span className="text-xs text-[var(--color-muted)]">
                Due {task.due_date}
              </span>
            )}
          </div>
        </div>
      </div>

      {isActive && onAction && (
        <div className="flex items-center gap-2 mt-3 pt-3 border-t border-[var(--color-gold-stroke)]">
          {task.status === "pending" && (
            <button
              onClick={() => onAction("start", task.id)}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-[var(--gold-500)] text-[#07111c] hover:bg-[var(--gold-600)] transition-colors"
            >
              <Play className="h-3 w-3" />
              Start
            </button>
          )}
          <button
            onClick={() => onAction("edit", task.id)}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-white/5 text-[var(--foreground)] hover:bg-white/10 transition-colors"
          >
            <Pencil className="h-3 w-3" />
            Edit
          </button>
          <button
            onClick={() => onAction("cancel", task.id)}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-white/5 text-[var(--color-muted)] hover:bg-red-500/10 hover:text-red-400 transition-colors"
          >
            <X className="h-3 w-3" />
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
