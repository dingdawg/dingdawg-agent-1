"use client";

/**
 * HealthStatusCard — agent self-healing status display in chat stream.
 *
 * Shows:
 *   - Overall health score (0-100) with color band (green/yellow/red)
 *   - Active incidents list with severity badges
 *   - Circuit breaker status for key integrations
 *   - Drift indicator (stable/declining)
 *   - Performance grade (A+ to F) with trend arrow
 *
 * Data comes from the MiLA capability distillation engine via API.
 * glass-panel-gold styling matches existing card components.
 */

import { Activity, AlertTriangle, Shield, TrendingUp, TrendingDown, Minus } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface HealthIncident {
  id: string;
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  description: string;
  category: string;
}

export interface CircuitStatus {
  service: string;
  state: "CLOSED" | "OPEN" | "HALF_OPEN";
}

export interface HealthStatusData {
  score: number;                    // 0-100
  status: "healthy" | "degraded" | "unhealthy";
  incidents: HealthIncident[];
  circuits: CircuitStatus[];
  driftLevel: "NORMAL" | "ELEVATED" | "HIGH" | "CRITICAL";
  performanceGrade: string;         // "A+" to "F"
  trend: "improving" | "stable" | "declining";
}

interface HealthStatusCardProps {
  data: HealthStatusData;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getScoreColor(score: number): string {
  if (score >= 80) return "#22c55e";
  if (score >= 50) return "#eab308";
  return "#ef4444";
}

function getScoreLabel(score: number): string {
  if (score >= 80) return "text-green-400";
  if (score >= 50) return "text-yellow-400";
  return "text-red-400";
}

function getStatusBadgeClass(status: HealthStatusData["status"]): string {
  switch (status) {
    case "healthy":
      return "bg-green-500/20 text-green-400";
    case "degraded":
      return "bg-yellow-500/20 text-yellow-400";
    case "unhealthy":
      return "bg-red-500/20 text-red-400";
  }
}

function getSeverityBadgeClass(severity: HealthIncident["severity"]): string {
  switch (severity) {
    case "CRITICAL":
      return "bg-red-500/20 text-red-400";
    case "HIGH":
      return "bg-orange-500/20 text-orange-400";
    case "MEDIUM":
      return "bg-yellow-500/20 text-yellow-400";
    case "LOW":
      return "bg-blue-500/20 text-blue-400";
  }
}

function getCircuitDotClass(state: CircuitStatus["state"]): string {
  switch (state) {
    case "CLOSED":
      return "bg-green-400";
    case "HALF_OPEN":
      return "bg-yellow-400";
    case "OPEN":
      return "bg-red-400";
  }
}

function getDriftBadgeClass(drift: HealthStatusData["driftLevel"]): string {
  switch (drift) {
    case "NORMAL":
      return "bg-green-500/20 text-green-400";
    case "ELEVATED":
      return "bg-yellow-500/20 text-yellow-400";
    case "HIGH":
      return "bg-orange-500/20 text-orange-400";
    case "CRITICAL":
      return "bg-red-500/20 text-red-400";
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function HealthStatusCard({ data }: HealthStatusCardProps) {
  const scoreColor = getScoreColor(data.score);
  const scoreLabelClass = getScoreLabel(data.score);

  // conic-gradient ring: fills clockwise proportional to score
  const fillPercent = Math.min(100, Math.max(0, data.score));
  const ringStyle: React.CSSProperties = {
    background: `conic-gradient(${scoreColor} ${fillPercent}%, rgba(255,255,255,0.08) ${fillPercent}%)`,
  };

  return (
    <div className="glass-panel-gold p-4 card-enter" data-testid="health-status-card">
      {/* Header row */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-[var(--gold-500)]" />
          <h3 className="text-sm font-heading font-semibold text-[var(--foreground)]">
            Agent Health
          </h3>
        </div>
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium capitalize ${getStatusBadgeClass(data.status)}`}
          data-testid="status-badge"
        >
          {data.status}
        </span>
      </div>

      {/* Score + grade row */}
      <div className="flex items-center gap-4 mb-4">
        {/* Circular progress ring */}
        <div
          className="relative h-16 w-16 rounded-full flex-shrink-0 flex items-center justify-center"
          style={ringStyle}
          aria-label={`Health score ${data.score}`}
          data-testid="score-ring"
        >
          {/* Inner cutout */}
          <div className="h-12 w-12 rounded-full bg-[var(--glass)] flex items-center justify-center">
            <span
              className={`text-lg font-heading font-bold leading-none ${scoreLabelClass}`}
              data-testid="score-value"
            >
              {data.score}
            </span>
          </div>
        </div>

        {/* Grade + trend */}
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-[var(--color-muted)]">Grade</span>
            <span
              className="text-xl font-heading font-bold text-[var(--foreground)]"
              data-testid="performance-grade"
            >
              {data.performanceGrade}
            </span>
            {/* Trend arrow */}
            {data.trend === "improving" && (
              <TrendingUp
                className="h-4 w-4 text-green-400"
                data-testid="trend-improving"
                aria-label="Trend: improving"
              />
            )}
            {data.trend === "stable" && (
              <Minus
                className="h-4 w-4 text-[var(--color-muted)]"
                data-testid="trend-stable"
                aria-label="Trend: stable"
              />
            )}
            {data.trend === "declining" && (
              <TrendingDown
                className="h-4 w-4 text-red-400"
                data-testid="trend-declining"
                aria-label="Trend: declining"
              />
            )}
          </div>

          {/* Drift level */}
          <div className="flex items-center gap-1.5">
            <Shield className="h-3 w-3 text-[var(--color-muted)]" />
            <span className="text-xs text-[var(--color-muted)]">Drift</span>
            <span
              className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium ${getDriftBadgeClass(data.driftLevel)}`}
              data-testid="drift-level"
            >
              {data.driftLevel}
            </span>
          </div>
        </div>
      </div>

      {/* Circuit breakers */}
      {data.circuits.length > 0 && (
        <div className="mb-3">
          <p className="text-xs text-[var(--color-muted)] mb-1.5 font-medium uppercase tracking-wide">
            Circuit Breakers
          </p>
          <div className="flex flex-wrap gap-2" data-testid="circuit-breakers">
            {data.circuits.map((circuit) => (
              <div
                key={circuit.service}
                className="flex items-center gap-1.5 text-xs text-[var(--foreground)]"
                data-testid={`circuit-${circuit.service}`}
              >
                <span
                  className={`h-2 w-2 rounded-full flex-shrink-0 ${getCircuitDotClass(circuit.state)}`}
                  aria-label={`${circuit.service} ${circuit.state}`}
                />
                <span className="text-[var(--color-muted)]">{circuit.service}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Divider */}
      <div className="border-t border-[var(--color-gold-stroke)] mb-3" />

      {/* Incidents */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <AlertTriangle className="h-3 w-3 text-[var(--color-muted)]" />
          <p className="text-xs text-[var(--color-muted)] font-medium uppercase tracking-wide">
            Active Incidents
          </p>
          {data.incidents.length > 0 && (
            <span className="ml-auto text-xs text-[var(--color-muted)]">
              {data.incidents.length}
            </span>
          )}
        </div>

        {data.incidents.length === 0 ? (
          <p
            className="text-xs text-green-400"
            data-testid="no-incidents-message"
          >
            No active incidents
          </p>
        ) : (
          <ul className="flex flex-col gap-2" data-testid="incidents-list">
            {data.incidents.map((incident) => (
              <li
                key={incident.id}
                className="flex items-start gap-2"
                data-testid={`incident-${incident.id}`}
              >
                <span
                  className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium flex-shrink-0 ${getSeverityBadgeClass(incident.severity)}`}
                  data-testid={`severity-${incident.severity.toLowerCase()}`}
                >
                  {incident.severity}
                </span>
                <span className="text-xs text-[var(--foreground)] leading-relaxed">
                  {incident.description}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
