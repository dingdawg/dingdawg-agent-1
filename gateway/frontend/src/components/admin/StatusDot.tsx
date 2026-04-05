"use client";

/**
 * StatusDot — color-coded status indicator with optional label and pulse animation.
 *
 * Colors: green (ok/live), yellow (warning/test), red (critical/down), gray (unknown)
 */

import { cn } from "@/lib/utils";

type StatusColor = "green" | "yellow" | "red" | "gray";

interface StatusDotProps {
  color: StatusColor;
  label?: string;
  pulse?: boolean;
  className?: string;
}

const COLOR_CLASSES: Record<StatusColor, string> = {
  green: "bg-emerald-500",
  yellow: "bg-yellow-400",
  red: "bg-red-500",
  gray: "bg-gray-500",
};

export default function StatusDot({ color, label, pulse = false, className }: StatusDotProps) {
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span className="relative flex h-2.5 w-2.5">
        {pulse && (
          <span
            className={cn(
              "animate-ping absolute inline-flex h-full w-full rounded-full opacity-75",
              COLOR_CLASSES[color]
            )}
          />
        )}
        <span
          className={cn(
            "relative inline-flex rounded-full h-2.5 w-2.5",
            COLOR_CLASSES[color]
          )}
        />
      </span>
      {label && (
        <span className="text-xs text-gray-400 font-medium">{label}</span>
      )}
    </span>
  );
}
