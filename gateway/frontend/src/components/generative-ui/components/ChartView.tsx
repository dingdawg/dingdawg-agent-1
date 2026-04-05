"use client";

import {
  BarChart,
  Bar,
  LineChart,
  Line,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { BarChart2 } from "lucide-react";
import type { ChartViewProps } from "../catalog";

const DEFAULT_COLOR = "var(--gold-500, #f59e0b)";

export function ChartView({ type, data, labels, title, color = DEFAULT_COLOR }: ChartViewProps) {
  const chartData = data.map((value, i) => ({
    name: labels[i] ?? `${i}`,
    value,
  }));

  const commonTooltipStyle = {
    backgroundColor: "rgba(0,0,0,0.8)",
    border: "1px solid rgba(255,255,255,0.1)",
    borderRadius: "8px",
    color: "#fff",
    fontSize: "12px",
  };

  const renderChart = () => {
    switch (type) {
      case "bar":
        return (
          <BarChart data={chartData}>
            <XAxis
              dataKey="name"
              tick={{ fontSize: 10, fill: "var(--color-muted, #9ca3af)" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "var(--color-muted, #9ca3af)" }}
              axisLine={false}
              tickLine={false}
              width={36}
            />
            <Tooltip contentStyle={commonTooltipStyle} cursor={{ fill: "rgba(255,255,255,0.05)" }} />
            <Bar dataKey="value" fill={color} radius={[4, 4, 0, 0]} />
          </BarChart>
        );

      case "line":
        return (
          <LineChart data={chartData}>
            <XAxis
              dataKey="name"
              tick={{ fontSize: 10, fill: "var(--color-muted, #9ca3af)" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "var(--color-muted, #9ca3af)" }}
              axisLine={false}
              tickLine={false}
              width={36}
            />
            <Tooltip contentStyle={commonTooltipStyle} />
            <Line
              type="monotone"
              dataKey="value"
              stroke={color}
              strokeWidth={2}
              dot={{ fill: color, r: 3 }}
              activeDot={{ r: 5 }}
            />
          </LineChart>
        );

      case "area":
        return (
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={color} stopOpacity={0.3} />
                <stop offset="95%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="name"
              tick={{ fontSize: 10, fill: "var(--color-muted, #9ca3af)" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "var(--color-muted, #9ca3af)" }}
              axisLine={false}
              tickLine={false}
              width={36}
            />
            <Tooltip contentStyle={commonTooltipStyle} />
            <Area
              type="monotone"
              dataKey="value"
              stroke={color}
              strokeWidth={2}
              fill="url(#areaGrad)"
            />
          </AreaChart>
        );

      case "pie":
        return (
          <PieChart>
            <Pie
              data={chartData}
              cx="50%"
              cy="50%"
              outerRadius={80}
              dataKey="value"
              label={({ name, percent }) =>
                `${name} ${((percent ?? 0) * 100).toFixed(0)}%`
              }
              labelLine={false}
            >
              {chartData.map((_, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={`hsl(${(index * 47 + 40) % 360}, 65%, 55%)`}
                />
              ))}
            </Pie>
            <Tooltip contentStyle={commonTooltipStyle} />
          </PieChart>
        );

      default:
        return null;
    }
  };

  return (
    <div className="glass-panel-gold rounded-xl p-4 space-y-3 card-enter">
      {title && (
        <div className="flex items-center gap-2">
          <BarChart2 className="h-4 w-4 text-[var(--gold-500)]" />
          <span className="text-sm font-heading font-semibold text-[var(--foreground)]">
            {title}
          </span>
        </div>
      )}
      <div className="w-full" style={{ height: 200 }}>
        <ResponsiveContainer width="100%" height="100%">
          {renderChart() ?? <div />}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
