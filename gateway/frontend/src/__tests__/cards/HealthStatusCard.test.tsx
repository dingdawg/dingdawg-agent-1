/**
 * HealthStatusCard.test.tsx — Agent self-healing status card tests
 *
 * 10 tests covering score display, status bands, incident list,
 * circuit breaker dots, trend arrows, performance grade, and drift level.
 *
 * Run: npx vitest run src/__tests__/cards/HealthStatusCard.test.tsx
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { HealthStatusCard } from "../../components/chat/cards/HealthStatusCard";
import type { HealthStatusData } from "../../components/chat/cards/HealthStatusCard";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const healthyData: HealthStatusData = {
  score: 95,
  status: "healthy",
  incidents: [],
  circuits: [
    { service: "stripe_api", state: "CLOSED" },
    { service: "email_api", state: "CLOSED" },
  ],
  driftLevel: "NORMAL",
  performanceGrade: "A",
  trend: "improving",
};

const degradedData: HealthStatusData = {
  score: 62,
  status: "degraded",
  incidents: [
    {
      id: "inc-1",
      severity: "HIGH",
      description: "Email delivery failing",
      category: "integration_down",
    },
    {
      id: "inc-2",
      severity: "MEDIUM",
      description: "Slow response times",
      category: "timeout",
    },
  ],
  circuits: [
    { service: "stripe_api", state: "CLOSED" },
    { service: "email_api", state: "OPEN" },
    { service: "sms_gateway", state: "HALF_OPEN" },
  ],
  driftLevel: "HIGH",
  performanceGrade: "C",
  trend: "declining",
};

const unhealthyData: HealthStatusData = {
  score: 28,
  status: "unhealthy",
  incidents: [
    {
      id: "inc-3",
      severity: "CRITICAL",
      description: "Database unreachable",
      category: "outage",
    },
  ],
  circuits: [{ service: "db_primary", state: "OPEN" }],
  driftLevel: "CRITICAL",
  performanceGrade: "F",
  trend: "declining",
};

const stableData: HealthStatusData = {
  score: 75,
  status: "degraded",
  incidents: [],
  circuits: [],
  driftLevel: "ELEVATED",
  performanceGrade: "B",
  trend: "stable",
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("HealthStatusCard", () => {
  it("renders the health score number", () => {
    render(<HealthStatusCard data={healthyData} />);
    expect(screen.getByTestId("score-value").textContent).toBe("95");
  });

  it("shows 'healthy' status badge for score >= 80", () => {
    render(<HealthStatusCard data={healthyData} />);
    const badge = screen.getByTestId("status-badge");
    expect(badge.textContent?.toLowerCase()).toContain("healthy");
    // Green color class should be applied
    expect(badge.className).toContain("green");
  });

  it("shows 'degraded' status badge for score 50-79", () => {
    render(<HealthStatusCard data={degradedData} />);
    const badge = screen.getByTestId("status-badge");
    expect(badge.textContent?.toLowerCase()).toContain("degraded");
    expect(badge.className).toContain("yellow");
  });

  it("shows 'unhealthy' status badge for score < 50", () => {
    render(<HealthStatusCard data={unhealthyData} />);
    const badge = screen.getByTestId("status-badge");
    expect(badge.textContent?.toLowerCase()).toContain("unhealthy");
    expect(badge.className).toContain("red");
  });

  it("renders incident list with severity badges when incidents are present", () => {
    render(<HealthStatusCard data={degradedData} />);
    expect(screen.getByTestId("incidents-list")).toBeTruthy();
    expect(screen.getByText("Email delivery failing")).toBeTruthy();
    expect(screen.getByText("Slow response times")).toBeTruthy();
    // Severity badge for HIGH
    const highBadge = screen.getByTestId("severity-high");
    expect(highBadge).toBeTruthy();
    expect(highBadge.className).toContain("orange");
  });

  it("shows 'No active incidents' message when incidents list is empty", () => {
    render(<HealthStatusCard data={healthyData} />);
    expect(screen.getByTestId("no-incidents-message")).toBeTruthy();
    expect(screen.getByText("No active incidents")).toBeTruthy();
  });

  it("renders circuit breaker status dot for each service", () => {
    render(<HealthStatusCard data={degradedData} />);
    const breakers = screen.getByTestId("circuit-breakers");
    expect(breakers).toBeTruthy();

    // All three services rendered
    expect(screen.getByTestId("circuit-stripe_api")).toBeTruthy();
    expect(screen.getByTestId("circuit-email_api")).toBeTruthy();
    expect(screen.getByTestId("circuit-sms_gateway")).toBeTruthy();

    // Service names visible
    expect(screen.getByText("stripe_api")).toBeTruthy();
    expect(screen.getByText("email_api")).toBeTruthy();
    expect(screen.getByText("sms_gateway")).toBeTruthy();
  });

  it("shows TrendingUp icon for improving trend", () => {
    render(<HealthStatusCard data={healthyData} />);
    expect(screen.getByTestId("trend-improving")).toBeTruthy();
  });

  it("shows TrendingDown icon for declining trend", () => {
    render(<HealthStatusCard data={degradedData} />);
    expect(screen.getByTestId("trend-declining")).toBeTruthy();
  });

  it("shows Minus icon for stable trend", () => {
    render(<HealthStatusCard data={stableData} />);
    expect(screen.getByTestId("trend-stable")).toBeTruthy();
  });

  it("displays the performance grade", () => {
    render(<HealthStatusCard data={healthyData} />);
    expect(screen.getByTestId("performance-grade").textContent).toBe("A");
  });

  it("shows drift level indicator with correct label", () => {
    render(<HealthStatusCard data={degradedData} />);
    const driftEl = screen.getByTestId("drift-level");
    expect(driftEl.textContent).toBe("HIGH");
  });
});
