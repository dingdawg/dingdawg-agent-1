"use client";

/**
 * AlertBadge — color-coded severity pill badge.
 *
 * Severity levels: CRITICAL | WARNING | INFO | OK
 */

import { cn } from "@/lib/utils";

export type AlertSeverity = "CRITICAL" | "WARNING" | "INFO" | "OK";

interface AlertBadgeProps {
  severity: AlertSeverity;
  label?: string;
  className?: string;
}

const SEVERITY_STYLES: Record<AlertSeverity, string> = {
  CRITICAL: "bg-red-500/20 text-red-400 border border-red-500/30",
  WARNING: "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30",
  INFO: "bg-blue-500/20 text-blue-400 border border-blue-500/30",
  OK: "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30",
};

const DEFAULT_LABELS: Record<AlertSeverity, string> = {
  CRITICAL: "Critical",
  WARNING: "Warning",
  INFO: "Info",
  OK: "OK",
};

export default function AlertBadge({ severity, label, className }: AlertBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold",
        SEVERITY_STYLES[severity],
        className
      )}
    >
      {label ?? DEFAULT_LABELS[severity]}
    </span>
  );
}
