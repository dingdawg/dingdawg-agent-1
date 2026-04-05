/**
 * RevenuePage.test.tsx — Admin revenue dashboard tests
 *
 * 10 tests covering: renders Revenue heading, KPI card labels, Stripe
 * TEST MODE badge, LIVE badge, not-configured critical badge, error banner,
 * Refresh button present, customer count displays, webhook status dot,
 * CRM pipeline link, and transactions empty message.
 *
 * NOTE: RevenuePage is wrapped in AdminRoute which checks auth. We mock
 * AdminRoute to render children directly so we can test the content.
 *
 * Run: npx vitest run src/__tests__/admin/RevenuePage.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";

// ─── Mock usePolling ──────────────────────────────────────────────────────────

vi.mock("@/hooks/usePolling", () => ({
  usePolling: vi.fn(),
}));

// ─── Mock AdminRoute — render children directly, bypass auth check ────────────

vi.mock("@/components/auth/AdminRoute", () => ({
  default: ({ children }: { children: React.ReactNode }) =>
    React.createElement(React.Fragment, null, children),
}));

// ─── Mock recharts ────────────────────────────────────────────────────────────

vi.mock("recharts", () => ({
  AreaChart: ({ children }: { children: React.ReactNode }) =>
    React.createElement("div", { "data-testid": "area-chart" }, children),
  Area: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) =>
    React.createElement("div", null, children),
  defs: () => null,
  linearGradient: () => null,
  stop: () => null,
}));

// ─── Mock lucide-react icons ──────────────────────────────────────────────────

vi.mock("lucide-react", () => {
  const icon = (name: string) => {
    const Component = ({ className }: { className?: string }) =>
      React.createElement("span", {
        "data-testid": `icon-${name}`,
        className,
      });
    Component.displayName = name;
    return Component;
  };
  return {
    DollarSign: icon("DollarSign"),
    Users: icon("Users"),
    TrendingUp: icon("TrendingUp"),
    BarChart3: icon("BarChart3"),
    AlertCircle: icon("AlertCircle"),
    RefreshCw: icon("RefreshCw"),
    Zap: icon("Zap"),
    Webhook: icon("Webhook"),
  };
});

// ─── Mock StatusDot ───────────────────────────────────────────────────────────

vi.mock("@/components/admin/StatusDot", () => ({
  default: ({
    color,
    label,
  }: {
    color: string;
    label?: string;
    pulse?: boolean;
  }) =>
    React.createElement(
      "span",
      { "data-testid": "status-dot", "data-color": color },
      label
    ),
}));

// ─── Mock StatCard ────────────────────────────────────────────────────────────

vi.mock("@/components/admin/StatCard", () => ({
  default: ({
    label,
    value,
  }: {
    label: string;
    value: string | number;
    subLabel?: string;
    trend?: string;
    trendLabel?: string;
    isLoading?: boolean;
  }) =>
    React.createElement(
      "div",
      { "data-testid": `stat-card-${label.replace(/\s+/g, "-").toLowerCase()}` },
      React.createElement("span", { "data-testid": "stat-label" }, label),
      React.createElement("span", { "data-testid": "stat-value" }, String(value))
    ),
}));

// ─── Mock AlertBadge ──────────────────────────────────────────────────────────

vi.mock("@/components/admin/AlertBadge", () => ({
  default: ({
    severity,
    label,
  }: {
    severity: string;
    label: string;
  }) =>
    React.createElement(
      "span",
      { "data-testid": `alert-badge-${severity.toLowerCase()}` },
      label
    ),
}));

// ─── Mock DataTable ───────────────────────────────────────────────────────────

vi.mock("@/components/admin/DataTable", () => ({
  default: ({
    data,
    emptyMessage,
  }: {
    data: unknown[];
    emptyMessage?: string;
    columns: unknown[];
    pageSize?: number;
    searchable?: boolean;
    isLoading?: boolean;
  }) => {
    if (data.length === 0) {
      return React.createElement(
        "div",
        { "data-testid": "data-table-empty" },
        emptyMessage
      );
    }
    return React.createElement("div", { "data-testid": "data-table" });
  },
}));

// ─── Mock adminRevenueStore ───────────────────────────────────────────────────

import type { StripeStatus, FunnelData } from "@/store/adminRevenueStore";

const mockFetchStripeStatus = vi.fn().mockResolvedValue(undefined);
const mockFetchFunnel = vi.fn().mockResolvedValue(undefined);

const mockStripeTest: StripeStatus = {
  mode: "test",
  webhook_configured: true,
  last_event: "2026-03-13T11:50:00",
  customer_count: 3,
};

const mockStripeLive: StripeStatus = {
  mode: "live",
  webhook_configured: true,
  last_event: "2026-03-13T11:55:00",
  customer_count: 88,
};

const mockStripeNotConfigured: StripeStatus = {
  mode: "not_configured",
  webhook_configured: false,
  last_event: null,
  customer_count: 0,
};

const mockFunnel: FunnelData = {
  registered_users: 120,
  claimed_handles: 80,
  active_subscribers: 15,
  active_7d: 30,
  churned_30d: 2,
};

const mockStoreBase = {
  stripeStatus: mockStripeTest,
  funnel: mockFunnel,
  contacts: null,
  isLoading: false,
  error: null as string | null,
  fetchStripeStatus: mockFetchStripeStatus,
  fetchFunnel: mockFetchFunnel,
  fetchContacts: vi.fn(),
  clearError: vi.fn(),
};

const mockUseAdminRevenueStore = vi.fn(() => mockStoreBase);

vi.mock("@/store/adminRevenueStore", () => ({
  useAdminRevenueStore: () => mockUseAdminRevenueStore(),
}));

// ─── Import component after mocks ─────────────────────────────────────────────

import RevenuePage from "@/app/admin/revenue/page";

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("RevenuePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseAdminRevenueStore.mockReturnValue({ ...mockStoreBase });
  });

  it("renders the Revenue page heading", () => {
    render(<RevenuePage />);
    expect(screen.getByText("Revenue")).toBeTruthy();
    expect(
      screen.getByText(/financial overview and stripe status/i)
    ).toBeTruthy();
  });

  it("renders all 4 KPI stat cards", () => {
    render(<RevenuePage />);
    expect(screen.getByTestId("stat-card-mrr")).toBeTruthy();
    expect(screen.getByTestId("stat-card-active-subscriptions")).toBeTruthy();
    expect(screen.getByTestId("stat-card-arpu")).toBeTruthy();
    expect(screen.getByTestId("stat-card-gross-margin")).toBeTruthy();
  });

  it("renders Stripe Status panel heading", () => {
    render(<RevenuePage />);
    expect(screen.getByText("Stripe Status")).toBeTruthy();
  });

  it("shows TEST MODE badge when stripe mode is test", () => {
    render(<RevenuePage />);
    expect(screen.getByText("TEST MODE")).toBeTruthy();
  });

  it("shows TEST MODE warning alert when in test mode", () => {
    render(<RevenuePage />);
    expect(
      screen.getByText(/no real charges.*flip stripe to live mode/i)
    ).toBeTruthy();
  });

  it("shows LIVE badge when stripe mode is live", () => {
    mockUseAdminRevenueStore.mockReturnValue({
      ...mockStoreBase,
      stripeStatus: mockStripeLive,
    });

    render(<RevenuePage />);
    expect(screen.getByText("LIVE")).toBeTruthy();
  });

  it("shows NOT CONFIGURED alert badge when stripe not configured", () => {
    mockUseAdminRevenueStore.mockReturnValue({
      ...mockStoreBase,
      stripeStatus: mockStripeNotConfigured,
    });

    render(<RevenuePage />);
    expect(screen.getByTestId("alert-badge-critical")).toBeTruthy();
    expect(screen.getByText("NOT CONFIGURED")).toBeTruthy();
  });

  it("renders error banner when store has an error", () => {
    mockUseAdminRevenueStore.mockReturnValue({
      ...mockStoreBase,
      error: "Failed to load Stripe status",
    });

    render(<RevenuePage />);
    expect(screen.getByText("Failed to load Stripe status")).toBeTruthy();
  });

  it("renders Refresh button", () => {
    render(<RevenuePage />);
    expect(screen.getByText("Refresh")).toBeTruthy();
  });

  it("renders customer count from stripe status", () => {
    render(<RevenuePage />);
    expect(screen.getByText("3")).toBeTruthy();
  });

  it("renders transactions table with empty message when no transactions", () => {
    render(<RevenuePage />);
    const emptyTable = screen.getByTestId("data-table-empty");
    expect(emptyTable).toBeTruthy();
    expect(emptyTable.textContent).toMatch(/no transactions yet/i);
  });

  it("renders CRM Pipeline link pointing to /admin/crm", () => {
    render(<RevenuePage />);
    const crmLink = screen.getByText("View CRM").closest("a");
    expect(crmLink).toBeTruthy();
    expect(crmLink?.getAttribute("href")).toBe("/admin/crm");
  });

  it("shows funnel data in CRM preview when funnel is loaded", () => {
    render(<RevenuePage />);
    expect(
      screen.getByText(/120 registered, 15 subscribed/i)
    ).toBeTruthy();
  });

  it("calls fetchStripeStatus and fetchFunnel on Refresh click", async () => {
    const fetchStripeStatus = vi.fn().mockResolvedValue(undefined);
    const fetchFunnel = vi.fn().mockResolvedValue(undefined);

    mockUseAdminRevenueStore.mockReturnValue({
      ...mockStoreBase,
      fetchStripeStatus,
      fetchFunnel,
    });

    render(<RevenuePage />);
    fireEvent.click(screen.getByText("Refresh"));

    await waitFor(() => {
      expect(fetchStripeStatus).toHaveBeenCalled();
      expect(fetchFunnel).toHaveBeenCalled();
    });
  });
});
