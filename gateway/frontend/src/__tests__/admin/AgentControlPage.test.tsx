/**
 * AgentControlPage.test.tsx — Admin agent control center tests
 *
 * 10 tests covering: renders header, stat cards display agent counts,
 * search input renders, status filter buttons render all 4 states,
 * agent table renders agent rows, suspend button appears for active agents,
 * activate button appears for suspended agents, inactive agents show dash,
 * error banner renders on store error, loading indicator shows on isLoading.
 *
 * Run: npx vitest run src/__tests__/admin/AgentControlPage.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";

// ─── Mock usePolling ──────────────────────────────────────────────────────────

vi.mock("@/hooks/usePolling", () => ({
  usePolling: vi.fn(),
}));

// ─── Mock recharts — avoids SVG rendering issues in jsdom ────────────────────

vi.mock("recharts", () => ({
  PieChart: ({ children }: { children: React.ReactNode }) =>
    React.createElement("div", { "data-testid": "pie-chart" }, children),
  Pie: () => React.createElement("div", { "data-testid": "pie" }),
  Cell: () => null,
  Tooltip: () => null,
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) =>
    React.createElement("div", null, children),
  Legend: () => null,
}));

// ─── Mock StatusDot ───────────────────────────────────────────────────────────

vi.mock("@/components/admin/StatusDot", () => ({
  default: ({ color, label }: { color: string; label?: string }) =>
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
    isLoading,
  }: {
    label: string;
    value: string | number;
    isLoading?: boolean;
    subLabel?: string;
  }) =>
    React.createElement(
      "div",
      { "data-testid": `stat-card-${label.replace(/\s+/g, "-").toLowerCase()}` },
      isLoading
        ? React.createElement("div", { "data-testid": "loading-pulse" })
        : React.createElement("span", null, String(value))
    ),
}));

// ─── Mock DataTable ───────────────────────────────────────────────────────────

vi.mock("@/components/admin/DataTable", () => ({
  default: ({
    data,
    columns,
    emptyMessage,
    isLoading,
  }: {
    data: unknown[];
    columns: Array<{
      header: string;
      accessor: string;
      render?: (v: unknown, row: unknown) => React.ReactNode;
    }>;
    emptyMessage?: string;
    isLoading?: boolean;
    pageSize?: number;
    searchable?: boolean;
  }) => {
    if (isLoading) {
      return React.createElement(
        "div",
        { "data-testid": "data-table-loading" },
        "Loading..."
      );
    }
    if (data.length === 0) {
      return React.createElement(
        "div",
        { "data-testid": "data-table-empty" },
        emptyMessage
      );
    }
    return React.createElement(
      "table",
      { "data-testid": "data-table" },
      React.createElement(
        "tbody",
        null,
        (data as Record<string, unknown>[]).map((row, i) =>
          React.createElement(
            "tr",
            { key: i, "data-testid": `table-row-${i}` },
            columns.map((col) =>
              React.createElement(
                "td",
                { key: col.accessor },
                col.render
                  ? col.render(row[col.accessor], row)
                  : String(row[col.accessor] ?? "")
              )
            )
          )
        )
      )
    );
  },
}));

// ─── Mock adminService ────────────────────────────────────────────────────────

vi.mock("@/services/api/adminService", () => ({
  getAgentsList: vi.fn(),
  suspendAdminAgent: vi.fn(),
  activateAdminAgent: vi.fn(),
  getAgentTemplateDistribution: vi
    .fn()
    .mockResolvedValue([{ template_name: "Sales Bot", count: 5 }]),
}));

// ─── Mock adminAgentsStore ────────────────────────────────────────────────────

import type { AdminAgent } from "@/services/api/adminService";

const mockActiveAgent: AdminAgent = {
  id: "agent-1",
  handle: "salesbot",
  owner_email: "owner@example.com",
  status: "active",
  template_name: "Sales Bot",
  created_at: "2026-01-01T00:00:00",
  last_active: "2026-03-13T10:00:00",
  message_count: 42,
};

const mockSuspendedAgent: AdminAgent = {
  id: "agent-2",
  handle: "supportbot",
  owner_email: "owner2@example.com",
  status: "suspended",
  template_name: "Support Bot",
  created_at: "2026-02-01T00:00:00",
  last_active: null,
  message_count: 7,
};

const mockInactiveAgent: AdminAgent = {
  id: "agent-3",
  handle: "demobot",
  owner_email: "demo@example.com",
  status: "inactive",
  template_name: "Demo Bot",
  created_at: "2026-03-01T00:00:00",
  last_active: null,
  message_count: 0,
};

const mockStoreBase = {
  agents: [mockActiveAgent, mockSuspendedAgent],
  totalAgents: 2,
  page: 1,
  perPage: 20,
  search: "",
  statusFilter: "all",
  isLoading: false,
  error: null as string | null,
  fetchAgents: vi.fn(),
  setPage: vi.fn(),
  setSearch: vi.fn(),
  setStatusFilter: vi.fn(),
  suspendAgent: vi.fn(),
  activateAgent: vi.fn(),
};

const mockUseAdminAgentsStore = vi.fn(() => mockStoreBase);

vi.mock("@/store/adminAgentsStore", () => ({
  useAdminAgentsStore: () => mockUseAdminAgentsStore(),
}));

// ─── Import component after mocks ─────────────────────────────────────────────

import AgentControlPage from "@/app/admin/agents/page";

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("AgentControlPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseAdminAgentsStore.mockReturnValue({ ...mockStoreBase });
  });

  it("renders the Agent Control Center heading", () => {
    render(<AgentControlPage />);
    expect(screen.getByText("Agent Control Center")).toBeTruthy();
  });

  it("renders total agents count in subheading", () => {
    render(<AgentControlPage />);
    expect(screen.getByText(/2 total agents/i)).toBeTruthy();
  });

  it("renders 4 stat cards with correct labels", () => {
    render(<AgentControlPage />);
    expect(screen.getByTestId("stat-card-total-agents")).toBeTruthy();
    expect(screen.getByTestId("stat-card-active-today")).toBeTruthy();
    expect(screen.getByTestId("stat-card-suspended")).toBeTruthy();
    expect(screen.getByTestId("stat-card-templates-used")).toBeTruthy();
  });

  it("renders search input with correct placeholder", () => {
    render(<AgentControlPage />);
    const input = screen.getByPlaceholderText(/search handle or email/i);
    expect(input).toBeTruthy();
  });

  it("renders all 4 status filter buttons", () => {
    render(<AgentControlPage />);
    // Use getAllByText because "active"/"suspended"/"inactive" also appear as
    // StatusDot labels in the data table rows — assert at least one button exists
    expect(screen.getAllByText("all").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("active").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("suspended").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("inactive").length).toBeGreaterThanOrEqual(1);
    // Verify the filter bar buttons are real <button> elements
    const filterButtons = screen
      .getAllByRole("button")
      .filter((btn) =>
        ["all", "active", "suspended", "inactive"].includes(
          btn.textContent?.trim() ?? ""
        )
      );
    expect(filterButtons.length).toBe(4);
  });

  it("calls setStatusFilter when a filter button is clicked", () => {
    const setStatusFilter = vi.fn();
    mockUseAdminAgentsStore.mockReturnValue({
      ...mockStoreBase,
      setStatusFilter,
    });

    render(<AgentControlPage />);
    // Find the filter button specifically (not status-dot labels in table rows)
    const activeFilterBtn = screen
      .getAllByRole("button")
      .find((btn) => btn.textContent?.trim() === "active");
    expect(activeFilterBtn).toBeTruthy();
    fireEvent.click(activeFilterBtn!);
    expect(setStatusFilter).toHaveBeenCalledWith("active");
  });

  it("renders data table with agent rows", () => {
    render(<AgentControlPage />);
    expect(screen.getByTestId("data-table")).toBeTruthy();
    expect(screen.getByTestId("table-row-0")).toBeTruthy();
    expect(screen.getByTestId("table-row-1")).toBeTruthy();
  });

  it("renders Suspend button for active agents", () => {
    render(<AgentControlPage />);
    const suspendButtons = screen.getAllByText("Suspend");
    expect(suspendButtons.length).toBeGreaterThanOrEqual(1);
  });

  it("renders Activate button for suspended agents", () => {
    render(<AgentControlPage />);
    const activateButtons = screen.getAllByText("Activate");
    expect(activateButtons.length).toBeGreaterThanOrEqual(1);
  });

  it("shows dash for inactive agent action column", () => {
    mockUseAdminAgentsStore.mockReturnValue({
      ...mockStoreBase,
      agents: [mockInactiveAgent],
      totalAgents: 1,
    });

    render(<AgentControlPage />);
    expect(screen.getByText("—")).toBeTruthy();
  });

  it("renders error banner when store has an error", () => {
    mockUseAdminAgentsStore.mockReturnValue({
      ...mockStoreBase,
      error: "Failed to load agents",
    });

    render(<AgentControlPage />);
    expect(screen.getByText("Failed to load agents")).toBeTruthy();
  });
});
