/**
 * SystemHealthPage.test.tsx — Admin system health dashboard tests
 *
 * 10 tests covering: loading skeleton, error state with retry, status banner,
 * platform metrics display, component cards, self-healing panel,
 * recent errors list, empty errors message, self-test button, and
 * self-test result rendering.
 *
 * Run: npx vitest run src/__tests__/admin/SystemHealthPage.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";

// ─── Mock usePolling — prevents real intervals in tests ───────────────────────

vi.mock("@/hooks/usePolling", () => ({
  usePolling: vi.fn(),
}));

// ─── Mock adminService ────────────────────────────────────────────────────────

const mockGetSystemHealth = vi.fn();
const mockGetSystemErrors = vi.fn();
const mockRunSystemSelfTest = vi.fn();

vi.mock("@/services/api/adminService", () => ({
  getSystemHealth: () => mockGetSystemHealth(),
  getSystemErrors: (_limit?: number) => mockGetSystemErrors(),
  runSystemSelfTest: () => mockRunSystemSelfTest(),
}));

// ─── Mock StatusDot — renders a simple span for test assertions ───────────────

vi.mock("@/components/admin/StatusDot", () => ({
  default: ({
    color,
    label,
  }: {
    color: string;
    label?: string;
    pulse?: boolean;
  }) => (
    <span data-testid="status-dot" data-color={color}>
      {label}
    </span>
  ),
}));

// ─── Fixtures ─────────────────────────────────────────────────────────────────

import type {
  SystemHealthReport,
  SystemErrorsResponse,
  SelfTestResponse,
} from "@/services/api/adminService";

const healthyReport: SystemHealthReport = {
  status: "healthy",
  uptime_seconds: 86461, // 1d 0h 1m
  timestamp: "2026-03-13T12:00:00",
  components: {
    database: { status: "ok", latency_ms: 4 },
    llm_providers: {
      openai: { status: "ok", configured: true, error_rate_1h: 0.01 },
      anthropic: { status: "ok", configured: true, error_rate_1h: 0 },
    },
    integrations: {
      stripe: { status: "configured", last_webhook: "2026-03-13T11:55:00" },
      twilio: { status: "test", last_webhook: null },
    },
    security: {
      rate_limiter: "active",
      constitution: "active",
      input_sanitizer: "active",
      bot_prevention: "active",
      token_revocation_guard: "active",
      tier_isolation: "active",
    },
  },
  metrics: {
    total_agents: 42,
    total_sessions: 1200,
    total_messages: 8500,
    active_sessions_24h: 17,
    error_rate_1h: 0.002,
    avg_response_time_ms: 312,
  },
  recent_errors: [],
  self_healing: {
    circuit_breakers: { openai: "CLOSED", stripe: "CLOSED" },
    auto_recovered: [
      {
        timestamp: "2026-03-13T11:00:00",
        issue: "Slow DB queries",
        action: "Connection pool recycled",
      },
    ],
  },
};

const errorsResponse: SystemErrorsResponse = {
  errors: [
    {
      timestamp: "2026-03-13T11:58:00",
      event_type: "api_error",
      actor: "user-abc",
      message: "Rate limit exceeded",
      endpoint: "/api/v1/chat",
      details: { status: 429 },
    },
  ],
  total: 1,
  retrieved_at: "2026-03-13T12:00:00",
};

const emptyErrorsResponse: SystemErrorsResponse = {
  errors: [],
  total: 0,
  retrieved_at: "2026-03-13T12:00:00",
};

const selfTestPassed: SelfTestResponse = {
  overall: "pass",
  passed: 3,
  total: 3,
  ran_at: "2026-03-13T12:00:00",
  results: [
    { test: "DB connectivity", result: "pass", message: "OK", duration_ms: 12 },
    { test: "LLM ping", result: "pass", message: "OK", duration_ms: 80 },
    { test: "Stripe webhook", result: "pass", message: "OK", duration_ms: 45 },
  ],
};

const selfTestFailed: SelfTestResponse = {
  overall: "fail",
  passed: 2,
  total: 3,
  ran_at: "2026-03-13T12:00:00",
  results: [
    { test: "DB connectivity", result: "pass", message: "OK", duration_ms: 12 },
    { test: "LLM ping", result: "pass", message: "OK", duration_ms: 80 },
    {
      test: "Stripe webhook",
      result: "fail",
      message: "Timeout after 5000ms",
      duration_ms: 5001,
    },
  ],
};

// ─── Import component AFTER mocks ─────────────────────────────────────────────

// Dynamic import so mocks are applied first
let SystemHealthPage: React.ComponentType;

beforeEach(async () => {
  vi.resetModules();
  mockGetSystemHealth.mockReset();
  mockGetSystemErrors.mockReset();
  mockRunSystemSelfTest.mockReset();

  const mod = await import("@/app/admin/system/page");
  SystemHealthPage = mod.default;
});

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("SystemHealthPage", () => {
  it("renders loading skeleton while data is fetching", async () => {
    // Never resolve — keep in loading state
    mockGetSystemHealth.mockReturnValue(new Promise(() => {}));
    mockGetSystemErrors.mockReturnValue(new Promise(() => {}));

    render(<SystemHealthPage />);

    // Skeleton blocks animate-pulse should be present
    const pulseEls = document.querySelectorAll(".animate-pulse");
    expect(pulseEls.length).toBeGreaterThan(0);
  });

  it("renders error panel with retry button when health API rejects", async () => {
    // With the allSettled fix, a health rejection sets fetchError and shows the error panel.
    mockGetSystemHealth.mockRejectedValue(new Error("Network error"));
    mockGetSystemErrors.mockRejectedValue(new Error("Network error"));

    render(<SystemHealthPage />);

    await waitFor(() => {
      expect(screen.getByText(/failed to load system health/i)).toBeTruthy();
    });

    // Error message from rejection is displayed
    expect(screen.getByText("Network error")).toBeTruthy();
    // Retry button is present and functional
    expect(screen.getByRole("button", { name: /retry/i })).toBeTruthy();
  });

  it("retry button re-invokes refresh and recovers when health API succeeds", async () => {
    // First call rejects → error panel shown. Second call resolves → health loaded.
    mockGetSystemHealth
      .mockRejectedValueOnce(new Error("Temporary failure"))
      .mockResolvedValue(healthyReport);
    mockGetSystemErrors.mockResolvedValue(emptyErrorsResponse);

    render(<SystemHealthPage />);

    await waitFor(() => {
      expect(screen.getByText(/failed to load system health/i)).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => {
      expect(screen.getByText(/system healthy/i)).toBeTruthy();
    });
  });

  it("still shows 'No recent errors' when errors fetch rejects", async () => {
    mockGetSystemHealth.mockResolvedValue(healthyReport);
    mockGetSystemErrors.mockRejectedValue(new Error("Network error"));

    render(<SystemHealthPage />);

    await waitFor(() => {
      expect(screen.getByText(/no recent errors/i)).toBeTruthy();
    });
  });

  it("renders system healthy status banner after data loads", async () => {
    mockGetSystemHealth.mockResolvedValue(healthyReport);
    mockGetSystemErrors.mockResolvedValue(emptyErrorsResponse);

    render(<SystemHealthPage />);

    await waitFor(() => {
      expect(screen.getByText(/system healthy/i)).toBeTruthy();
    });
  });

  it("renders platform metrics section with correct values", async () => {
    mockGetSystemHealth.mockResolvedValue(healthyReport);
    mockGetSystemErrors.mockResolvedValue(emptyErrorsResponse);

    render(<SystemHealthPage />);

    await waitFor(() => {
      expect(screen.getByText("Total Agents")).toBeTruthy();
    });

    expect(screen.getByText("42")).toBeTruthy();
    expect(screen.getByText("1,200")).toBeTruthy();
    expect(screen.getByText("312ms")).toBeTruthy();
  });

  it("renders self-healing panel with circuit breakers", async () => {
    mockGetSystemHealth.mockResolvedValue(healthyReport);
    mockGetSystemErrors.mockResolvedValue(emptyErrorsResponse);

    render(<SystemHealthPage />);

    await waitFor(() => {
      expect(screen.getByText(/self-healing/i)).toBeTruthy();
    });

    expect(screen.getByText(/circuit breakers/i)).toBeTruthy();
    // "openai" appears once — in the circuit breakers section
    expect(screen.getByText("openai")).toBeTruthy();
    // "stripe" may appear in multiple places (integration status + circuit breaker label)
    const stripeEls = screen.getAllByText("stripe");
    expect(stripeEls.length).toBeGreaterThanOrEqual(1);
  });

  it("renders auto-recovery log entries", async () => {
    mockGetSystemHealth.mockResolvedValue(healthyReport);
    mockGetSystemErrors.mockResolvedValue(emptyErrorsResponse);

    render(<SystemHealthPage />);

    await waitFor(() => {
      expect(screen.getByText("Slow DB queries")).toBeTruthy();
    });

    expect(screen.getByText("Connection pool recycled")).toBeTruthy();
  });

  it("shows 'No recent errors' when error list is empty", async () => {
    mockGetSystemHealth.mockResolvedValue(healthyReport);
    mockGetSystemErrors.mockResolvedValue(emptyErrorsResponse);

    render(<SystemHealthPage />);

    await waitFor(() => {
      expect(screen.getByText(/no recent errors/i)).toBeTruthy();
    });
  });

  it("renders error entries from getSystemErrors response", async () => {
    mockGetSystemHealth.mockResolvedValue(healthyReport);
    mockGetSystemErrors.mockResolvedValue(errorsResponse);

    render(<SystemHealthPage />);

    await waitFor(() => {
      expect(screen.getByText("Rate limit exceeded")).toBeTruthy();
    });

    // Endpoint text is rendered inside a <p> alongside event_type separated by ·
    // Use a matcher function to find the element containing the endpoint substring
    const endpointEl = screen.getByText((content) =>
      content.includes("/api/v1/chat")
    );
    expect(endpointEl).toBeTruthy();
  });

  it("Run Test button triggers self-test and renders passing summary", async () => {
    mockGetSystemHealth.mockResolvedValue(healthyReport);
    mockGetSystemErrors.mockResolvedValue(emptyErrorsResponse);
    mockRunSystemSelfTest.mockResolvedValue(selfTestPassed);

    render(<SystemHealthPage />);

    await waitFor(() => {
      expect(screen.getByText("Run Test")).toBeTruthy();
    });

    fireEvent.click(screen.getByText("Run Test"));

    await waitFor(() => {
      expect(screen.getByText(/all tests passed/i)).toBeTruthy();
    });

    expect(screen.getByText(/3\/3 passed/i)).toBeTruthy();
  });

  it("self-test renders failure summary when overall is fail", async () => {
    mockGetSystemHealth.mockResolvedValue(healthyReport);
    mockGetSystemErrors.mockResolvedValue(emptyErrorsResponse);
    mockRunSystemSelfTest.mockResolvedValue(selfTestFailed);

    render(<SystemHealthPage />);

    await waitFor(() => {
      expect(screen.getByText("Run Test")).toBeTruthy();
    });

    fireEvent.click(screen.getByText("Run Test"));

    await waitFor(() => {
      expect(screen.getByText(/some tests failed/i)).toBeTruthy();
    });

    expect(screen.getByText("Timeout after 5000ms")).toBeTruthy();
  });
});
