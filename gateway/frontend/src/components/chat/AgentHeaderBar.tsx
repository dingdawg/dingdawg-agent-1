"use client";

/**
 * AgentHeaderBar — top bar with agent name, online status, settings gear.
 */

import { Settings, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface AgentHeaderBarProps {
  agentName: string;
  handle: string;
  isOnline: boolean;
  onSettingsClick?: () => void;
  onAgentSwitch?: () => void;
  showSwitch?: boolean;
  className?: string;
}

export function AgentHeaderBar({
  agentName,
  handle,
  isOnline,
  onSettingsClick,
  onAgentSwitch,
  showSwitch = false,
  className,
}: AgentHeaderBarProps) {
  return (
    <header
      className={cn(
        "flex items-center justify-between gap-3 px-5 py-3",
        "border-b border-[var(--color-gold-stroke)]",
        "bg-[var(--ink-950)] lg:bg-[var(--glass)] lg:backdrop-blur-xl",
        className
      )}
    >
      {/* Left: agent identity */}
      <div className="flex items-center gap-3 min-w-0">
        {/* Avatar circle */}
        <div className="h-9 w-9 rounded-xl bg-[var(--gold-500)]/15 flex items-center justify-center flex-shrink-0">
          <span className="text-sm font-heading font-bold text-[var(--gold-500)]">
            {agentName.charAt(0).toUpperCase()}
          </span>
        </div>

        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="text-sm font-heading font-semibold text-[var(--foreground)] truncate">
              {agentName}
            </h1>
            <span
              className={cn(
                "h-2 w-2 rounded-full flex-shrink-0",
                isOnline ? "bg-green-400 thinking-pulse" : "bg-gray-500"
              )}
            />
          </div>
          <p className="text-xs text-[var(--gold-500)] font-medium truncate">
            @{handle}
          </p>
        </div>
      </div>

      {/* Right: actions */}
      <div className="flex items-center gap-1.5">
        {showSwitch && (
          <button
            onClick={onAgentSwitch}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs text-[var(--color-muted)] hover:bg-white/5 border border-[var(--stroke)] transition-colors"
          >
            Switch
            <ChevronDown className="h-3 w-3" />
          </button>
        )}
        <button
          onClick={onSettingsClick}
          className="p-2 rounded-lg text-[var(--color-muted)] hover:bg-white/5 hover:text-[var(--foreground)] transition-colors"
          aria-label="Agent settings"
        >
          <Settings className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}
