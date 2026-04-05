"use client";

import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import type { StatsGridProps } from "../catalog";

const trendConfig = {
  up: { icon: TrendingUp, color: "text-green-400" },
  down: { icon: TrendingDown, color: "text-red-400" },
  flat: { icon: Minus, color: "text-[var(--color-muted)]" },
};

export function StatsGrid({ metrics }: StatsGridProps) {
  return (
    <div className="grid grid-cols-2 gap-3 w-full">
      {metrics.map((metric, i) => {
        const trend = metric.trend ? trendConfig[metric.trend] : null;
        const TrendIcon = trend?.icon;

        return (
          <div
            key={`${metric.label}-${i}`}
            className="glass-panel-gold rounded-xl p-4 flex flex-col gap-1.5 card-enter"
            style={{ animationDelay: `${i * 60}ms` }}
          >
            <p className="text-xs text-[var(--color-muted)] font-body uppercase tracking-wider truncate">
              {metric.label}
            </p>
            <p className="text-2xl font-heading font-bold text-[var(--foreground)]">
              {metric.value}
              {metric.unit && (
                <span className="text-sm font-normal text-[var(--color-muted)] ml-1">
                  {metric.unit}
                </span>
              )}
            </p>
            {trend && TrendIcon && (
              <div className={`flex items-center gap-1 text-xs ${trend.color}`}>
                <TrendIcon className="h-3 w-3" />
                {metric.trendValue && <span>{metric.trendValue}</span>}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
