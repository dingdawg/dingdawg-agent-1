"use client";

import { Info, AlertTriangle, XCircle, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AlertCardProps } from "../catalog";

const severityConfig = {
  info: {
    icon: Info,
    bg: "bg-blue-500/10",
    border: "border-blue-500/30",
    iconColor: "text-blue-400",
    titleColor: "text-blue-300",
  },
  warning: {
    icon: AlertTriangle,
    bg: "bg-yellow-500/10",
    border: "border-yellow-500/30",
    iconColor: "text-yellow-400",
    titleColor: "text-yellow-300",
  },
  error: {
    icon: XCircle,
    bg: "bg-red-500/10",
    border: "border-red-500/30",
    iconColor: "text-red-400",
    titleColor: "text-red-300",
  },
  success: {
    icon: CheckCircle2,
    bg: "bg-green-500/10",
    border: "border-green-500/30",
    iconColor: "text-green-400",
    titleColor: "text-green-300",
  },
};

interface AlertCardComponentProps extends AlertCardProps {
  onAction?: (payload: string) => void;
}

export function AlertCard({ severity, title, message, action, onAction }: AlertCardComponentProps) {
  const config = severityConfig[severity];
  const Icon = config.icon;

  return (
    <div
      className={cn(
        "rounded-xl p-4 border space-y-2 card-enter",
        config.bg,
        config.border
      )}
    >
      <div className="flex items-start gap-3">
        <Icon className={cn("h-4 w-4 shrink-0 mt-0.5", config.iconColor)} />
        <div className="flex-1 min-w-0 space-y-1">
          <p className={cn("text-sm font-heading font-semibold", config.titleColor)}>
            {title}
          </p>
          <p className="text-sm font-body text-[var(--foreground)] leading-snug">{message}</p>
        </div>
      </div>

      {action && (
        <button
          onClick={() => onAction?.(action.payload)}
          className={cn(
            "ml-7 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors min-h-[36px]",
            "bg-white/10 hover:bg-white/20 text-[var(--foreground)]"
          )}
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
