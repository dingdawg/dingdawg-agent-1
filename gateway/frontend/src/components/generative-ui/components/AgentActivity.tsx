"use client";

import {
  CheckCircle2,
  Clock,
  XCircle,
  Zap,
  MessageSquare,
  Calendar,
  CreditCard,
  AlertTriangle,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { AgentActivityProps } from "../catalog";

const typeConfig = {
  task: { icon: Zap, color: "text-blue-400" },
  message: { icon: MessageSquare, color: "text-purple-400" },
  booking: { icon: Calendar, color: "text-[var(--gold-500)]" },
  payment: { icon: CreditCard, color: "text-green-400" },
  alert: { icon: AlertTriangle, color: "text-yellow-400" },
  system: { icon: Settings, color: "text-[var(--color-muted)]" },
};

const statusConfig = {
  success: { icon: CheckCircle2, color: "text-green-400" },
  pending: { icon: Clock, color: "text-yellow-400" },
  failed: { icon: XCircle, color: "text-red-400" },
};

export function AgentActivity({ actions, title = "Agent Activity" }: AgentActivityProps) {
  return (
    <div className="glass-panel-gold rounded-xl p-4 space-y-3 card-enter">
      <div className="flex items-center gap-2">
        <Zap className="h-4 w-4 text-[var(--gold-500)]" />
        <span className="text-sm font-heading font-semibold text-[var(--foreground)]">
          {title}
        </span>
      </div>

      <div className="space-y-2">
        {actions.slice(0, 8).map((action, i) => {
          const type = typeConfig[action.type];
          const TypeIcon = type.icon;
          const status = action.status ? statusConfig[action.status] : null;
          const StatusIcon = status?.icon;

          return (
            <div key={i} className="flex items-start gap-3 bg-white/5 rounded-lg px-3 py-2">
              <div className={cn("mt-0.5 shrink-0", type.color)}>
                <TypeIcon className="h-3.5 w-3.5" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-body text-[var(--foreground)] leading-snug">
                  {action.description}
                </p>
                <p className="text-xs text-[var(--color-muted)] mt-0.5">{action.timestamp}</p>
              </div>
              {StatusIcon && status && (
                <div className={cn("shrink-0 mt-0.5", status.color)}>
                  <StatusIcon className="h-3.5 w-3.5" />
                </div>
              )}
            </div>
          );
        })}
        {actions.length > 8 && (
          <p className="text-xs text-center text-[var(--color-muted)] py-1">
            +{actions.length - 8} more actions
          </p>
        )}
      </div>
    </div>
  );
}
