"use client";

/**
 * Agent status card — avatar, name, handle, type, template info.
 */

import { User, Store, Zap } from "lucide-react";

export interface AgentInfo {
  name: string;
  handle: string;
  agent_type: "personal" | "business";
  template_name?: string;
  is_active: boolean;
}

interface AgentStatusCardProps {
  agent: AgentInfo;
  className?: string;
}

export function AgentStatusCard({ agent, className = "" }: AgentStatusCardProps) {
  return (
    <div className={`glass-panel-gold p-4 card-enter ${className}`}>
      <div className="flex items-center gap-3">
        {/* Avatar */}
        <div className="h-12 w-12 rounded-2xl bg-[var(--gold-500)]/15 flex items-center justify-center flex-shrink-0">
          {agent.agent_type === "business" ? (
            <Store className="h-6 w-6 text-[var(--gold-500)]" />
          ) : (
            <User className="h-6 w-6 text-[var(--gold-500)]" />
          )}
        </div>

        <div className="flex-1 min-w-0">
          <p className="text-base font-heading font-semibold text-[var(--foreground)] truncate">
            {agent.name}
          </p>
          <p className="text-sm text-[var(--gold-500)] font-medium">
            @{agent.handle}
          </p>
        </div>

        {/* Status dot */}
        <div className="flex items-center gap-1.5">
          <span
            className={`h-2 w-2 rounded-full ${
              agent.is_active ? "bg-green-400 thinking-pulse" : "bg-gray-500"
            }`}
          />
          <span className="text-xs text-[var(--color-muted)]">
            {agent.is_active ? "Online" : "Offline"}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-3 mt-3 pt-3 border-t border-[var(--color-gold-stroke)]">
        <span className="inline-flex items-center gap-1 text-xs text-[var(--color-muted)] capitalize">
          <Zap className="h-3 w-3" />
          {agent.agent_type}
        </span>
        {agent.template_name && (
          <span className="text-xs text-[var(--color-muted)]">
            {agent.template_name}
          </span>
        )}
      </div>
    </div>
  );
}
