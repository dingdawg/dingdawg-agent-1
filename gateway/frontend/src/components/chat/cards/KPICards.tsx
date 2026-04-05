"use client";

/**
 * KPI metric cards — row of 3 stats rendered inside chat stream.
 */

import { TrendingUp, TrendingDown, Minus } from "lucide-react";

export interface KPIMetric {
  label: string;
  value: string | number;
  trend?: "up" | "down" | "flat";
  trendLabel?: string;
}

interface KPICardsProps {
  metrics: KPIMetric[];
}

const trendConfig = {
  up: { icon: TrendingUp, color: "text-green-400" },
  down: { icon: TrendingDown, color: "text-red-400" },
  flat: { icon: Minus, color: "text-[var(--color-muted)]" },
};

export function KPICards({ metrics }: KPICardsProps) {
  return (
    <div className="flex gap-3 w-full overflow-x-auto pb-1">
      {metrics.map((m, i) => {
        const trend = m.trend ? trendConfig[m.trend] : null;
        const TrendIcon = trend?.icon;
        const delayClass =
          i === 0
            ? "card-enter"
            : i === 1
              ? "card-enter-delay-1"
              : "card-enter-delay-2";

        return (
          <div
            key={m.label}
            className={`glass-panel-gold flex-1 min-w-[120px] p-4 flex flex-col gap-1.5 ${delayClass}`}
          >
            <p className="text-xs text-[var(--color-muted)] font-body uppercase tracking-wider">
              {m.label}
            </p>
            <p className="text-2xl font-heading font-bold text-[var(--foreground)]">
              {m.value}
            </p>
            {trend && TrendIcon && (
              <div className={`flex items-center gap-1 text-xs ${trend.color}`}>
                <TrendIcon className="h-3 w-3" />
                {m.trendLabel && <span>{m.trendLabel}</span>}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
