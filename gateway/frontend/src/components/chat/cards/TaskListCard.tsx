"use client";

/**
 * Scrollable task list card — shows active tasks in chat stream.
 */

import { useState } from "react";
import { CheckCircle, Circle, ChevronDown } from "lucide-react";
import type { TaskCardData } from "./TaskCard";

interface TaskListCardProps {
  tasks: TaskCardData[];
  title?: string;
  maxVisible?: number;
  onTaskClick?: (taskId: string) => void;
}

const statusIcon: Record<string, { icon: typeof Circle; color: string }> = {
  pending: { icon: Circle, color: "text-yellow-400" },
  in_progress: { icon: Circle, color: "text-blue-400" },
  completed: { icon: CheckCircle, color: "text-green-400" },
  cancelled: { icon: Circle, color: "text-[var(--color-muted)]" },
  failed: { icon: Circle, color: "text-red-400" },
};

export function TaskListCard({
  tasks,
  title = "Active Tasks",
  maxVisible = 5,
  onTaskClick,
}: TaskListCardProps) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? tasks : tasks.slice(0, maxVisible);
  const hasMore = tasks.length > maxVisible;

  return (
    <div className="glass-panel-gold p-4 card-enter">
      <h3 className="text-sm font-heading font-semibold text-[var(--foreground)] mb-3">
        {title}
      </h3>

      <div className="flex flex-col gap-1">
        {visible.map((task, i) => {
          const si = statusIcon[task.status] ?? statusIcon.pending;
          const Icon = si.icon;

          return (
            <button
              key={task.id}
              onClick={() => onTaskClick?.(task.id)}
              className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-left hover:bg-white/5 transition-colors group"
              style={{ animationDelay: `${i * 60}ms` }}
            >
              <Icon className={`h-4 w-4 flex-shrink-0 ${si.color}`} />
              <span className="flex-1 text-sm text-[var(--foreground)] truncate group-hover:text-white">
                {task.description}
              </span>
              {task.task_type && (
                <span className="text-xs text-[var(--color-muted)] flex-shrink-0">
                  {task.task_type}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {hasMore && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-1 mt-2 px-3 py-1.5 text-xs text-[var(--gold-500)] hover:text-[var(--gold-600)] transition-colors"
        >
          <ChevronDown
            className={`h-3 w-3 transition-transform ${expanded ? "rotate-180" : ""}`}
          />
          {expanded ? "Show less" : `Show all ${tasks.length}`}
        </button>
      )}

      {tasks.length === 0 && (
        <p className="text-sm text-[var(--color-muted)] py-4 text-center">
          No active tasks
        </p>
      )}
    </div>
  );
}
