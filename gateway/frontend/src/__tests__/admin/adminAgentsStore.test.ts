/**
 * adminAgentsStore.test.ts — Unit tests for useAdminAgentsStore (Zustand).
 *
 * Tests:
 *   - Initial state is correct
 *   - fetchAgents success populates agents and totalAgents
 *   - fetchAgents null guard — res.agents null falls back to []
 *   - fetchAgents null guard — res.total null falls back to 0
 *   - fetchAgents passes current page/perPage/search/statusFilter to API
 *   - fetchAgents failure sets error, agents stays []
 *   - setPage updates page (does NOT auto-fetch)
 *   - setSearch updates search and resets page to 1
 *   - setStatusFilter updates statusFilter and resets page to 1
 *   - suspendAgent optimistic update flips status to "suspended"
 *   - suspendAgent failure sets error and re-throws
 *   - activateAgent optimistic update flips status to "active"
 *   - activateAgent failure sets error and re-throws
 *
 * Run: npx vitest run src/__tests__/admin/adminAgentsStore.test.ts
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// ─── Mock adminService ────────────────────────────────────────────────────────

const mockGetAgentsList = vi.fn();
const mockSuspendAdminAgent = vi.fn();
const mockActivateAdminAgent = vi.fn();

vi.mock("@/services/api/adminService", () => ({
  getAgentsList: (params: unknown) => mockGetAgentsList(params),
  suspendAdminAgent: (id: string) => mockSuspendAdminAgent(id),
  activateAdminAgent: (id: string) => mockActivateAdminAgent(id),
}));

// ─── Import store AFTER mocks ─────────────────────────────────────────────────

import { useAdminAgentsStore } from "@/store/adminAgentsStore";
import type { AdminAgent } from "@/services/api/adminService";

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const agentActive: AdminAgent = {
  id: "agent-001",
  handle: "salesbot",
  owner_email: "owner@example.com",
  status: "active",
  template_name: "Sales Bot",
  created_at: "2026-01-01T00:00:00",
  last_active: "2026-03-13T10:00:00",
  message_count: 42,
};

const agentSuspended: AdminAgent = {
  id: "agent-002",
  handle: "supportbot",
  owner_email: "support@example.com",
  status: "suspended",
  template_name: "Support Bot",
  created_at: "2026-02-01T00:00:00",
  last_active: null,
  message_count: 5,
};

const mockAgentsResponse = {
  agents: [agentActive, agentSuspended],
  total: 2,
  page: 1,
  per_page: 20,
};

// ─── Helper — reset store between tests ──────────────────────────────────────

function resetStore() {
  useAdminAgentsStore.setState({
    agents: [],
    totalAgents: 0,
    page: 1,
    perPage: 20,
    search: "",
    statusFilter: "all",
    isLoading: false,
    error: null,
  });
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("useAdminAgentsStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStore();
  });

  // ── Initial state ─────────────────────────────────────────────────────────────

  it("has correct initial state", () => {
    const state = useAdminAgentsStore.getState();
    expect(state.agents).toEqual([]);
    expect(state.totalAgents).toBe(0);
    expect(state.page).toBe(1);
    expect(state.perPage).toBe(20);
    expect(state.search).toBe("");
    expect(state.statusFilter).toBe("all");
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  // ── fetchAgents — success ─────────────────────────────────────────────────────

  it("fetchAgents success populates agents array and totalAgents", async () => {
    mockGetAgentsList.mockResolvedValueOnce(mockAgentsResponse);

    await useAdminAgentsStore.getState().fetchAgents();

    const state = useAdminAgentsStore.getState();
    expect(state.agents).toHaveLength(2);
    expect(state.agents[0]).toEqual(agentActive);
    expect(state.agents[1]).toEqual(agentSuspended);
    expect(state.totalAgents).toBe(2);
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  it("fetchAgents sets isLoading=true during fetch, false after", async () => {
    let resolveFn!: (v: typeof mockAgentsResponse) => void;
    mockGetAgentsList.mockReturnValueOnce(
      new Promise<typeof mockAgentsResponse>((resolve) => {
        resolveFn = resolve;
      })
    );

    const promise = useAdminAgentsStore.getState().fetchAgents();
    expect(useAdminAgentsStore.getState().isLoading).toBe(true);

    resolveFn(mockAgentsResponse);
    await promise;
    expect(useAdminAgentsStore.getState().isLoading).toBe(false);
  });

  // ── fetchAgents — null guards ─────────────────────────────────────────────────

  it("fetchAgents guards against null agents in response (falls back to [])", async () => {
    mockGetAgentsList.mockResolvedValueOnce({
      agents: null,
      total: 0,
      page: 1,
      per_page: 20,
    });

    await useAdminAgentsStore.getState().fetchAgents();

    expect(useAdminAgentsStore.getState().agents).toEqual([]);
  });

  it("fetchAgents guards against null total in response (falls back to 0)", async () => {
    mockGetAgentsList.mockResolvedValueOnce({
      agents: [agentActive],
      total: null,
      page: 1,
      per_page: 20,
    });

    await useAdminAgentsStore.getState().fetchAgents();

    expect(useAdminAgentsStore.getState().totalAgents).toBe(0);
  });

  // ── fetchAgents — params forwarding ──────────────────────────────────────────

  it("fetchAgents forwards page, perPage, search, statusFilter to API", async () => {
    useAdminAgentsStore.setState({
      page: 3,
      perPage: 10,
      search: "  bob  ",
      statusFilter: "active",
    });
    mockGetAgentsList.mockResolvedValueOnce(mockAgentsResponse);

    await useAdminAgentsStore.getState().fetchAgents();

    expect(mockGetAgentsList).toHaveBeenCalledWith({
      page: 3,
      per_page: 10,
      search: "bob", // trimmed
      status: "active",
    });
  });

  it("fetchAgents omits search param when search is empty/whitespace", async () => {
    useAdminAgentsStore.setState({ search: "   " });
    mockGetAgentsList.mockResolvedValueOnce(mockAgentsResponse);

    await useAdminAgentsStore.getState().fetchAgents();

    const call = mockGetAgentsList.mock.calls[0][0] as Record<string, unknown>;
    expect(call.search).toBeUndefined();
  });

  // ── fetchAgents — failure ─────────────────────────────────────────────────────

  it("fetchAgents failure sets error and agents stays []", async () => {
    mockGetAgentsList.mockRejectedValueOnce(new Error("Agents API down"));

    await useAdminAgentsStore.getState().fetchAgents();

    const state = useAdminAgentsStore.getState();
    expect(state.agents).toEqual([]);
    expect(state.error).toBe("Agents API down");
    expect(state.isLoading).toBe(false);
  });

  it("fetchAgents does NOT throw on failure", async () => {
    mockGetAgentsList.mockRejectedValueOnce(new Error("boom"));

    await expect(
      useAdminAgentsStore.getState().fetchAgents()
    ).resolves.toBeUndefined();
  });

  // ── setPage ───────────────────────────────────────────────────────────────────

  it("setPage updates page without triggering fetchAgents", () => {
    useAdminAgentsStore.getState().setPage(4);

    expect(useAdminAgentsStore.getState().page).toBe(4);
    expect(mockGetAgentsList).not.toHaveBeenCalled();
  });

  // ── setSearch ─────────────────────────────────────────────────────────────────

  it("setSearch updates search and resets page to 1", () => {
    useAdminAgentsStore.setState({ page: 5 });
    useAdminAgentsStore.getState().setSearch("charlie");

    const state = useAdminAgentsStore.getState();
    expect(state.search).toBe("charlie");
    expect(state.page).toBe(1);
  });

  // ── setStatusFilter ───────────────────────────────────────────────────────────

  it("setStatusFilter updates statusFilter and resets page to 1", () => {
    useAdminAgentsStore.setState({ page: 3 });
    useAdminAgentsStore.getState().setStatusFilter("suspended");

    const state = useAdminAgentsStore.getState();
    expect(state.statusFilter).toBe("suspended");
    expect(state.page).toBe(1);
  });

  // ── suspendAgent ──────────────────────────────────────────────────────────────

  it("suspendAgent optimistic update flips agent status to 'suspended'", async () => {
    useAdminAgentsStore.setState({ agents: [agentActive, agentSuspended] });
    mockSuspendAdminAgent.mockResolvedValueOnce(undefined);

    await useAdminAgentsStore.getState().suspendAgent("agent-001");

    const updated = useAdminAgentsStore
      .getState()
      .agents.find((a) => a.id === "agent-001");
    expect(updated?.status).toBe("suspended");
    // The other agent is unchanged
    const other = useAdminAgentsStore
      .getState()
      .agents.find((a) => a.id === "agent-002");
    expect(other?.status).toBe("suspended");
  });

  it("suspendAgent calls suspendAdminAgent with correct agentId", async () => {
    useAdminAgentsStore.setState({ agents: [agentActive] });
    mockSuspendAdminAgent.mockResolvedValueOnce(undefined);

    await useAdminAgentsStore.getState().suspendAgent("agent-001");

    expect(mockSuspendAdminAgent).toHaveBeenCalledWith("agent-001");
  });

  it("suspendAgent failure sets error and re-throws", async () => {
    useAdminAgentsStore.setState({ agents: [agentActive] });
    mockSuspendAdminAgent.mockRejectedValueOnce(new Error("Suspend failed"));

    await expect(
      useAdminAgentsStore.getState().suspendAgent("agent-001")
    ).rejects.toThrow("Suspend failed");

    expect(useAdminAgentsStore.getState().error).toBe("Suspend failed");
  });

  // ── activateAgent ─────────────────────────────────────────────────────────────

  it("activateAgent optimistic update flips agent status to 'active'", async () => {
    useAdminAgentsStore.setState({ agents: [agentActive, agentSuspended] });
    mockActivateAdminAgent.mockResolvedValueOnce(undefined);

    await useAdminAgentsStore.getState().activateAgent("agent-002");

    const updated = useAdminAgentsStore
      .getState()
      .agents.find((a) => a.id === "agent-002");
    expect(updated?.status).toBe("active");
    // Other agent is unchanged
    const other = useAdminAgentsStore
      .getState()
      .agents.find((a) => a.id === "agent-001");
    expect(other?.status).toBe("active");
  });

  it("activateAgent calls activateAdminAgent with correct agentId", async () => {
    useAdminAgentsStore.setState({ agents: [agentSuspended] });
    mockActivateAdminAgent.mockResolvedValueOnce(undefined);

    await useAdminAgentsStore.getState().activateAgent("agent-002");

    expect(mockActivateAdminAgent).toHaveBeenCalledWith("agent-002");
  });

  it("activateAgent failure sets error and re-throws", async () => {
    useAdminAgentsStore.setState({ agents: [agentSuspended] });
    mockActivateAdminAgent.mockRejectedValueOnce(new Error("Activate failed"));

    await expect(
      useAdminAgentsStore.getState().activateAgent("agent-002")
    ).rejects.toThrow("Activate failed");

    expect(useAdminAgentsStore.getState().error).toBe("Activate failed");
  });
});
