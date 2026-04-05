"use client";

/**
 * ProgressCard — vertical timeline for order/task progress tracking.
 *
 * Step states:
 *   completed → green filled check circle
 *   active    → blue pulsing dot
 *   pending   → gray empty circle
 *
 * Each step can optionally show a description and a formatted timestamp.
 */

import { CheckCircle2, Circle, Loader2 } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ProgressStep {
  label: string;
  description?: string;
  timestamp?: Date;
  status: "completed" | "active" | "pending";
}

interface ProgressCardProps {
  steps: ProgressStep[];
  currentStep: number;
  title?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTimestamp(date: Date): string {
  return date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ProgressCard({ steps, currentStep, title }: ProgressCardProps) {
  return (
    <div className="glass-panel-gold p-4 card-enter">
      {title && (
        <h3 className="text-sm font-heading font-semibold text-[var(--foreground)] mb-4">
          {title}
        </h3>
      )}

      <div className="flex flex-col">
        {steps.map((step, i) => {
          const isLast = i === steps.length - 1;

          return (
            <div key={`${step.label}-${i}`} className="flex gap-3">
              {/* Timeline column: icon + connector line */}
              <div className="flex flex-col items-center flex-shrink-0">
                {/* Status icon */}
                <div
                  data-status={step.status}
                  className="flex items-center justify-center h-6 w-6 rounded-full flex-shrink-0"
                >
                  {step.status === "completed" && (
                    <CheckCircle2 className="h-5 w-5 text-green-400" />
                  )}
                  {step.status === "active" && (
                    <div className="h-3 w-3 rounded-full bg-blue-400 thinking-pulse" />
                  )}
                  {step.status === "pending" && (
                    <Circle className="h-5 w-5 text-[var(--color-muted)] opacity-40" />
                  )}
                </div>

                {/* Connector line (not shown for last item) */}
                {!isLast && (
                  <div
                    className={[
                      "w-0.5 flex-1 my-1 min-h-[16px]",
                      step.status === "completed"
                        ? "bg-green-400/30"
                        : "bg-white/10",
                    ].join(" ")}
                  />
                )}
              </div>

              {/* Content column */}
              <div className={`pb-4 flex-1 min-w-0 ${isLast ? "pb-0" : ""}`}>
                <div className="flex items-center justify-between gap-2 mb-0.5">
                  <p
                    className={[
                      "text-sm font-medium",
                      step.status === "active"
                        ? "text-[var(--foreground)]"
                        : step.status === "completed"
                        ? "text-[var(--foreground)]"
                        : "text-[var(--color-muted)]",
                    ].join(" ")}
                  >
                    {step.label}
                  </p>

                  {step.timestamp && (
                    <span className="text-xs text-[var(--color-muted)] flex-shrink-0">
                      {formatTimestamp(step.timestamp)}
                    </span>
                  )}
                </div>

                {step.description && (
                  <p className="text-xs text-[var(--color-muted)] mt-0.5">
                    {step.description}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
