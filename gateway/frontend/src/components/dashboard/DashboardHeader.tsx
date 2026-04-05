"use client";

/**
 * DashboardHeader — compact agent command bar above the chat area.
 *
 * Shows:
 *   - Agent name + @handle + live status dot
 *   - Quick stats: conversations, active tasks, active skills
 *   - Integration status badges (colored dots)
 *   - Settings + Integrations icon links
 *
 * Design: max 80px height, responsive (stats collapse on mobile),
 * dark theme with gold accents matching the existing design system.
 */

import Link from "next/link";
import { Settings, Plug } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface DashboardStats {
  conversations: number;
  activeTasks: number;
  activeSkills: number;
  integrations: { name: string; connected: boolean }[];
}

interface DashboardHeaderProps {
  agentName: string;
  handle: string;
  /** "active" | "configuring" | "error" */
  status: "active" | "configuring" | "error";
  stats: DashboardStats;
  className?: string;
}

// ─── Status dot color map ─────────────────────────────────────────────────────

const STATUS_COLOR: Record<DashboardHeaderProps["status"], string> = {
  active: "bg-[var(--color-success,#22c55e)]",
  configuring: "bg-yellow-400",
  error: "bg-red-500",
};

const STATUS_LABEL: Record<DashboardHeaderProps["status"], string> = {
  active: "Active",
  configuring: "Configuring",
  error: "Error",
};

// ─── Integration dot color ────────────────────────────────────────────────────

function integrationColor(connected: boolean): string {
  return connected ? "bg-[var(--color-success,#22c55e)]" : "bg-white/20";
}

// ─── Component ────────────────────────────────────────────────────────────────

export function DashboardHeader({
  agentName,
  handle,
  status,
  stats,
  className,
}: DashboardHeaderProps) {
  return (
    <div
      className={cn(
        // Container: dark glass panel, max 80px tall
        "flex items-center justify-between gap-3 px-4 py-2.5",
        "border-b border-[var(--stroke)] bg-[var(--ink-950)]",
        "flex-shrink-0 min-h-[52px] max-h-[80px]",
        className
      )}
    >
      {/* ── Left: agent identity ─────────────────────────────────── */}
      <div className="flex items-center gap-2.5 min-w-0">
        {/* Status dot */}
        <span
          className={cn(
            "flex-shrink-0 h-2 w-2 rounded-full",
            STATUS_COLOR[status]
          )}
          title={STATUS_LABEL[status]}
          aria-label={`Agent status: ${STATUS_LABEL[status]}`}
        />

        {/* Agent name + handle */}
        <div className="min-w-0">
          <p className="text-sm font-semibold text-[var(--foreground)] leading-tight truncate">
            {agentName}
          </p>
          <p className="text-xs text-[var(--gold-500)] leading-tight truncate">
            @{handle}
          </p>
        </div>

        {/* Divider */}
        <span className="hidden sm:block h-6 w-px bg-[var(--stroke)] flex-shrink-0 mx-1" />

        {/* Quick stats — hidden on small mobile */}
        <div className="hidden sm:flex items-center gap-3 text-xs text-[var(--color-muted)]">
          <span>
            <span className="font-semibold text-[var(--foreground)]">
              {stats.conversations}
            </span>{" "}
            <span className="hidden md:inline">Conversations</span>
            <span className="md:hidden">Chats</span>
          </span>

          <span className="h-3.5 w-px bg-[var(--stroke)]" />

          <span>
            <span className="font-semibold text-[var(--foreground)]">
              {stats.activeTasks}
            </span>{" "}
            Tasks
          </span>

          <span className="h-3.5 w-px bg-[var(--stroke)]" />

          <span>
            <span className="font-semibold text-[var(--foreground)]">
              {stats.activeSkills}
            </span>{" "}
            <span className="hidden md:inline">Skills active</span>
            <span className="md:hidden">Skills</span>
          </span>
        </div>
      </div>

      {/* ── Right: integrations + action icons ───────────────────── */}
      <div className="flex items-center gap-2 flex-shrink-0">
        {/* Integration dots — show up to 5 */}
        {stats.integrations.length > 0 && (
          <div
            className="hidden sm:flex items-center gap-1.5 mr-1"
            aria-label="Integration status"
          >
            {stats.integrations.slice(0, 5).map((integration) => (
              <span
                key={integration.name}
                className={cn(
                  "h-2 w-2 rounded-full transition-colors",
                  integrationColor(integration.connected)
                )}
                title={`${integration.name}: ${integration.connected ? "Connected" : "Disconnected"}`}
              />
            ))}
            {stats.integrations.length > 5 && (
              <span className="text-[10px] text-[var(--color-muted)]">
                +{stats.integrations.length - 5}
              </span>
            )}
          </div>
        )}

        {/* Integrations icon link */}
        <Link
          href="/integrations"
          className={cn(
            "flex items-center justify-center h-10 w-10 min-h-[44px] min-w-[44px] rounded-lg",
            "text-[var(--color-muted)] hover:text-[var(--foreground)]",
            "hover:bg-white/5 transition-colors"
          )}
          title="Integrations"
          aria-label="Open integrations"
        >
          <Plug className="h-4 w-4" />
        </Link>

        {/* Settings icon link */}
        <Link
          href="/settings"
          className={cn(
            "flex items-center justify-center h-10 w-10 min-h-[44px] min-w-[44px] rounded-lg",
            "text-[var(--color-muted)] hover:text-[var(--gold-500)]",
            "hover:bg-white/5 transition-colors"
          )}
          title="Settings"
          aria-label="Open settings"
        >
          <Settings className="h-4 w-4" />
        </Link>
      </div>
    </div>
  );
}
