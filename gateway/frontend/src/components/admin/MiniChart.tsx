"use client";

/**
 * MiniChart — sparkline chart using Recharts.
 *
 * Minimal visual trend indicator: no axes, no labels, no grid.
 * Accepts a data array of objects with a numeric value field.
 * Used in overview KPI cards and inline metric displays.
 *
 * Safari / SSR safety:
 *   ResponsiveContainer internally calls window.getComputedStyle() and
 *   ResizeObserver during the first render. On older Safari versions (< 16)
 *   and on any SSR pass this throws, crashing the entire admin shell.
 *   The `mounted` guard defers the chart to after the first client paint so
 *   the DOM element exists and has dimensions before Recharts measures it.
 */

import { useEffect, useState } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  Tooltip,
} from "recharts";

export type ChartType = "line" | "bar";

interface DataPoint {
  [key: string]: string | number;
}

interface MiniChartProps {
  data: DataPoint[];
  dataKey: string;
  color?: string;
  type?: ChartType;
  height?: number;
  showTooltip?: boolean;
}

export default function MiniChart({
  data,
  dataKey,
  color = "#F6B400",
  type = "line",
  height = 48,
  showTooltip = false,
}: MiniChartProps) {
  // Defer Recharts rendering until after first client paint.
  // This prevents window/ResizeObserver access during SSR and on Safari's
  // first synchronous render pass where the container has no dimensions yet.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);

  const placeholder = (
    <div
      className="w-full flex items-center justify-center text-gray-600 text-xs"
      style={{ height }}
    >
      {(!data || data.length === 0) ? "No data" : ""}
    </div>
  );

  if (!mounted || !data || data.length === 0) {
    return placeholder;
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      {type === "bar" ? (
        <BarChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 2 }}>
          {showTooltip && (
            <Tooltip
              contentStyle={{
                background: "#0d1926",
                border: "1px solid #1a2a3d",
                borderRadius: "8px",
                fontSize: "12px",
                color: "#fff",
              }}
              cursor={{ fill: "rgba(246,180,0,0.08)" }}
            />
          )}
          <Bar dataKey={dataKey} fill={color} radius={[2, 2, 0, 0]} />
        </BarChart>
      ) : (
        <LineChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 2 }}>
          {showTooltip && (
            <Tooltip
              contentStyle={{
                background: "#0d1926",
                border: "1px solid #1a2a3d",
                borderRadius: "8px",
                fontSize: "12px",
                color: "#fff",
              }}
              cursor={{ stroke: color, strokeWidth: 1 }}
            />
          )}
          <Line
            type="monotone"
            dataKey={dataKey}
            stroke={color}
            strokeWidth={2}
            dot={false}
            activeDot={showTooltip ? { r: 3, fill: color } : false}
          />
        </LineChart>
      )}
    </ResponsiveContainer>
  );
}
