"use client";

/**
 * StatCard — KPI metric card for the Command Center overview.
 *
 * Shows: label, value, optional trend direction with color coding.
 * Trend: up (green), down (red), neutral (gray).
 */

import { cn } from "@/lib/utils";

export type TrendDirection = "up" | "down" | "neutral";

interface StatCardProps {
  label: string;
  value: string | number;
  subLabel?: string;
  trend?: TrendDirection;
  trendLabel?: string;
  isLoading?: boolean;
  className?: string;
}

const TREND_STYLES: Record<TrendDirection, { arrow: string; color: string }> = {
  up: { arrow: "\u2191", color: "text-emerald-400" },
  down: { arrow: "\u2193", color: "text-red-400" },
  neutral: { arrow: "\u2192", color: "text-gray-400" },
};

export default function StatCard({
  label,
  value,
  subLabel,
  trend,
  trendLabel,
  isLoading = false,
  className,
}: StatCardProps) {
  return (
    <div
      className={cn(
        "bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4 flex flex-col gap-2",
        className
      )}
    >
      <p className="text-xs font-medium text-gray-400 uppercase tracking-wide">{label}</p>

      {isLoading ? (
        <div className="h-8 w-24 bg-[#1a2a3d] rounded animate-pulse" />
      ) : (
        <p className="text-2xl font-bold font-heading text-white leading-none">
          {value}
        </p>
      )}

      {(subLabel || (trend && trendLabel)) && (
        <div className="flex items-center gap-2 mt-0.5">
          {subLabel && (
            <span className="text-xs text-gray-500">{subLabel}</span>
          )}
          {trend && trendLabel && (
            <span
              className={cn(
                "text-xs font-medium flex items-center gap-0.5",
                TREND_STYLES[trend].color
              )}
            >
              <span aria-hidden="true">{TREND_STYLES[trend].arrow}</span>
              {trendLabel}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
