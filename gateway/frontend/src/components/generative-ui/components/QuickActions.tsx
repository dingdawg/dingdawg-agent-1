"use client";

import { Zap } from "lucide-react";
import type { QuickActionsProps } from "../catalog";

interface QuickActionsComponentProps extends QuickActionsProps {
  onAction?: (action: string) => void;
}

export function QuickActions({
  actions,
  title = "Quick Actions",
  onAction,
}: QuickActionsComponentProps) {
  return (
    <div className="glass-panel-gold rounded-xl p-4 space-y-3 card-enter">
      <div className="flex items-center gap-2">
        <Zap className="h-4 w-4 text-[var(--gold-500)]" />
        <span className="text-sm font-heading font-semibold text-[var(--foreground)]">
          {title}
        </span>
      </div>

      <div className="flex flex-wrap gap-2">
        {actions.map((action, i) => (
          <button
            key={i}
            onClick={() => onAction?.(action)}
            className="px-3 py-2 rounded-lg text-sm font-body bg-white/5 hover:bg-[var(--gold-500)]/10 hover:text-[var(--gold-500)] text-[var(--foreground)] border border-white/10 hover:border-[var(--gold-500)]/30 transition-colors min-h-[44px]"
          >
            {action}
          </button>
        ))}
      </div>
    </div>
  );
}
