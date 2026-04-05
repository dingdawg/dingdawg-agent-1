/**
 * adminService.test.ts — Unit tests for adminService API functions.
 *
 * Strategy: mock the client module (get/post helpers) so we can assert
 * each service function calls the correct endpoint with the correct method
 * and returns/transforms data as specified.
 *
 * Tests:
 *   - getWhoami calls GET /api/v1/admin/whoami
 *   - getPlatformStats calls GET /api/v1/admin/platform-stats
 *   - getStripeStatus calls GET /api/v1/admin/stripe-status
 *   - getFunnel calls GET /api/v1/admin/funnel
 *   - getContacts builds correct query string (page, per_page, optional search)
 *   - getAlerts returns array when backend returns array
 *   - getAlerts returns alerts array when backend returns {alerts:[...]}
 *   - acknowledgeAlert calls POST /api/v1/admin/alerts/{id}/acknowledge
 *   - getAgentsList builds query string correctly (no "all" status sent)
 *   - getAgentsList omits status param when status is "all"
 *   - suspendAdminAgent calls POST /api/v1/admin/agents/{id}/suspend
 *   - activateAdminAgent calls POST /api/v1/admin/agents/{id}/activate
 *   - getSystemHealth calls GET /api/v1/admin/system/health
 *   - sendCommand calls POST /api/v1/admin/command with command payload
 *   - getCampaigns returns array when backend returns array
 *   - getCampaigns returns campaigns array when backend returns {campaigns:[...]}
 *   - getEvents returns array when backend returns array
 *   - getEvents returns events array when backend returns {events:[...]}
 *   - getAdminTemplates unwraps {templates:[...]} shape
 *   - getDeploymentHistory unwraps {history:[...]} shape
 *   - getWorkflowTests unwraps {tests:[...]} shape
 *   - runWorkflowTest calls POST with correct test ID in URL
 *   - runAllWorkflowTests unwraps {results:[...]} shape
 *   - getSystemErrors builds query string with limit param
 *   - getSystemMetrics builds query string with hours param
 *   - runSystemSelfTest calls POST /api/v1/admin/system/self-test
 *
 * Run: npx vitest run src/__tests__/admin/adminService.test.ts
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// ─── Mock client ──────────────────────────────────────────────────────────────
// Must be declared before importing adminService.

const mockGet = vi.fn();
const mockPost = vi.fn();

vi.mock("@/services/api/client", () => ({
  // Only forward args that the service actually passes so toHaveBeenCalledWith
  // assertions don't see spurious `undefined` trailing arguments.
  get: (url: string, config?: unknown) =>
    config !== undefined ? mockGet(url, config) : mockGet(url),
  post: (url: string, data?: unknown, config?: unknown) =>
    config !== undefined ? mockPost(url, data, config) : mockPost(url, data),
}));

// ─── Import service AFTER mocks ───────────────────────────────────────────────

import {
  getWhoami,
  getPlatformStats,
  getStripeStatus,
  getFunnel,
  getContacts,
  getAlerts,
  acknowledgeAlert,
  getAgentsList,
  suspendAdminAgent,
  activateAdminAgent,
  getSystemHealth,
  getSystemErrors,
  getSystemMetrics,
  runSystemSelfTest,
  sendCommand,
  getCampaigns,
  getEvents,
  createEvent,
  getAdminTemplates,
  deployAgent,
  getDeploymentHistory,
  getWorkflowTests,
  runWorkflowTest,
  runAllWorkflowTests,
} from "@/services/api/adminService";

import type {
  AdminWhoami,
  PlatformStats,
  StripeStatus,
  FunnelData,
  PaginatedContacts,
  Alert,
  AdminAgent,
  AgentsListResponse,
  Campaign,
  AdminEvent,
  AdminTemplate,
  DeploymentRecord,
  WorkflowTest,
  RunTestResponse,
  SystemHealthReport,
} from "@/services/api/adminService";

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const whoamiFixture: AdminWhoami = {
  user_id: "usr-001",
  email: "admin@dingdawg.com",
  is_admin: true,
  role: "superadmin",
};

const statsFixture: PlatformStats = {
  total_users: 400,
  total_agents: 80,
  sessions_24h: 50,
  errors_24h: 2,
  active_sessions: 10,
  revenue_mtd_cents: 100000,
};

const stripeFixture: StripeStatus = {
  mode: "test",
  webhook_configured: true,
  last_event: null,
  customer_count: 3,
};

const funnelFixture: FunnelData = {
  registered_users: 100,
  claimed_handles: 70,
  active_subscribers: 20,
  active_7d: 35,
  churned_30d: 1,
};

const contactsFixture: PaginatedContacts = {
  items: [],
  total: 0,
  page: 1,
  per_page: 20,
};

const alertFixture: Alert = {
  id: "a1",
  severity: "critical",
  title: "Test alert",
  description: "desc",
  source: "system",
  timestamp: "2026-03-13T12:00:00",
  acknowledged: false,
};

const agentFixture: AdminAgent = {
  id: "agent-001",
  handle: "bot",
  owner_email: "owner@example.com",
  status: "active",
  template_name: "Sales Bot",
  created_at: "2026-01-01T00:00:00",
  last_active: null,
  message_count: 10,
};

const agentsResponseFixture: AgentsListResponse = {
  agents: [agentFixture],
  total: 1,
  page: 1,
  per_page: 20,
};

const campaignFixture: Campaign = {
  id: "c1",
  name: "March Push",
  channel: "email",
  status: "active",
  reach: 500,
  opens: 120,
  clicks: 30,
  created_at: "2026-03-01T00:00:00",
};

const eventFixture: AdminEvent = {
  id: "ev-1",
  title: "Q1 Review",
  date: "2026-03-31",
  type: "deadline",
};

const templateFixture: AdminTemplate = {
  id: "tmpl-1",
  name: "Sales Bot",
  sector: "retail",
  description: "Handles sales queries",
  agent_count: 5,
};

const deploymentFixture: DeploymentRecord = {
  id: "dep-1",
  handle: "@testbot",
  template_name: "Sales Bot",
  status: "success",
  deployed_at: "2026-03-13T10:00:00",
};

const workflowTestFixture: WorkflowTest = {
  id: "wt-1",
  name: "DB health",
  description: "Checks DB connectivity",
  last_result: "pass",
};

const runTestFixture: RunTestResponse = {
  test_id: "wt-1",
  result: "pass",
  duration_ms: 42,
  steps: [],
  ran_at: "2026-03-13T12:00:00",
};

const systemHealthFixture: SystemHealthReport = {
  status: "healthy",
  uptime_seconds: 3600,
  timestamp: "2026-03-13T12:00:00",
  components: {
    database: { status: "ok", latency_ms: 5 },
    llm_providers: {},
    integrations: {},
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
    total_agents: 10,
    total_sessions: 200,
    total_messages: 1500,
    active_sessions_24h: 5,
    error_rate_1h: 0,
    avg_response_time_ms: 300,
  },
  recent_errors: [],
  self_healing: {
    circuit_breakers: {},
    auto_recovered: [],
  },
};

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("adminService", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Admin identity ────────────────────────────────────────────────────────────

  it("getWhoami calls GET /api/v1/admin/whoami and returns data", async () => {
    mockGet.mockResolvedValueOnce(whoamiFixture);

    const result = await getWhoami();

    expect(mockGet).toHaveBeenCalledWith("/api/v1/admin/whoami");
    expect(result).toEqual(whoamiFixture);
    expect(result.is_admin).toBe(true);
    expect(result.role).toBe("superadmin");
  });

  it("getPlatformStats calls GET /api/v1/admin/platform-stats", async () => {
    mockGet.mockResolvedValueOnce(statsFixture);

    const result = await getPlatformStats();

    expect(mockGet).toHaveBeenCalledWith("/api/v1/admin/platform-stats");
    expect(result.total_users).toBe(400);
    expect(result.revenue_mtd_cents).toBe(100000);
  });

  // ── Revenue / Stripe ──────────────────────────────────────────────────────────

  it("getStripeStatus calls GET /api/v1/admin/stripe-status", async () => {
    mockGet.mockResolvedValueOnce(stripeFixture);

    const result = await getStripeStatus();

    expect(mockGet).toHaveBeenCalledWith("/api/v1/admin/stripe-status");
    expect(result.mode).toBe("test");
  });

  it("getFunnel calls GET /api/v1/admin/funnel", async () => {
    mockGet.mockResolvedValueOnce(funnelFixture);

    const result = await getFunnel();

    expect(mockGet).toHaveBeenCalledWith("/api/v1/admin/funnel");
    expect(result.registered_users).toBe(100);
  });

  it("getContacts calls GET with page and per_page query params", async () => {
    mockGet.mockResolvedValueOnce(contactsFixture);

    await getContacts({ page: 2, per_page: 10 });

    const [url] = mockGet.mock.calls[0] as [string];
    expect(url).toContain("/api/v1/admin/contacts");
    expect(url).toContain("page=2");
    expect(url).toContain("per_page=10");
  });

  it("getContacts appends search param when provided", async () => {
    mockGet.mockResolvedValueOnce(contactsFixture);

    await getContacts({ page: 1, per_page: 20, search: "alice" });

    const [url] = mockGet.mock.calls[0] as [string];
    expect(url).toContain("search=alice");
  });

  it("getContacts omits search param when search is undefined", async () => {
    mockGet.mockResolvedValueOnce(contactsFixture);

    await getContacts({ page: 1, per_page: 20 });

    const [url] = mockGet.mock.calls[0] as [string];
    expect(url).not.toContain("search=");
  });

  // ── Alerts ────────────────────────────────────────────────────────────────────

  it("getAlerts returns array when backend returns raw array", async () => {
    mockGet.mockResolvedValueOnce([alertFixture]);

    const result = await getAlerts();

    expect(mockGet).toHaveBeenCalledWith("/api/v1/admin/alerts");
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("a1");
  });

  it("getAlerts unwraps {alerts:[...]} shape", async () => {
    mockGet.mockResolvedValueOnce({ alerts: [alertFixture] });

    const result = await getAlerts();

    expect(result).toHaveLength(1);
    expect(result[0].severity).toBe("critical");
  });

  it("getAlerts returns [] when backend returns {alerts: null}", async () => {
    mockGet.mockResolvedValueOnce({ alerts: null });

    const result = await getAlerts();

    expect(result).toEqual([]);
  });

  it("acknowledgeAlert calls POST /api/v1/admin/alerts/{id}/acknowledge", async () => {
    mockPost.mockResolvedValueOnce(undefined);

    await acknowledgeAlert("alert-007");

    expect(mockPost).toHaveBeenCalledWith(
      "/api/v1/admin/alerts/alert-007/acknowledge",
      {}
    );
  });

  // ── Agent control ─────────────────────────────────────────────────────────────

  it("getAgentsList calls GET /api/v1/admin/agents with page and per_page", async () => {
    mockGet.mockResolvedValueOnce(agentsResponseFixture);

    const result = await getAgentsList({ page: 1, per_page: 20 });

    const [url] = mockGet.mock.calls[0] as [string];
    expect(url).toContain("/api/v1/admin/agents");
    expect(url).toContain("page=1");
    expect(url).toContain("per_page=20");
    expect(result.agents).toHaveLength(1);
  });

  it("getAgentsList omits status param when status is 'all'", async () => {
    mockGet.mockResolvedValueOnce(agentsResponseFixture);

    await getAgentsList({ page: 1, per_page: 20, status: "all" });

    const [url] = mockGet.mock.calls[0] as [string];
    expect(url).not.toContain("status=");
  });

  it("getAgentsList includes status param when status is not 'all'", async () => {
    mockGet.mockResolvedValueOnce(agentsResponseFixture);

    await getAgentsList({ page: 1, per_page: 20, status: "suspended" });

    const [url] = mockGet.mock.calls[0] as [string];
    expect(url).toContain("status=suspended");
  });

  it("getAgentsList includes search param when provided", async () => {
    mockGet.mockResolvedValueOnce(agentsResponseFixture);

    await getAgentsList({ page: 1, per_page: 20, search: "bot" });

    const [url] = mockGet.mock.calls[0] as [string];
    expect(url).toContain("search=bot");
  });

  it("suspendAdminAgent calls POST /api/v1/admin/agents/{id}/suspend", async () => {
    mockPost.mockResolvedValueOnce(undefined);

    await suspendAdminAgent("agent-001");

    expect(mockPost).toHaveBeenCalledWith(
      "/api/v1/admin/agents/agent-001/suspend",
      {}
    );
  });

  it("activateAdminAgent calls POST /api/v1/admin/agents/{id}/activate", async () => {
    mockPost.mockResolvedValueOnce(undefined);

    await activateAdminAgent("agent-002");

    expect(mockPost).toHaveBeenCalledWith(
      "/api/v1/admin/agents/agent-002/activate",
      {}
    );
  });

  // ── System health ─────────────────────────────────────────────────────────────

  it("getSystemHealth calls GET /api/v1/admin/system/health", async () => {
    mockGet.mockResolvedValueOnce(systemHealthFixture);

    const result = await getSystemHealth();

    expect(mockGet).toHaveBeenCalledWith("/api/v1/admin/system/health");
    expect(result.status).toBe("healthy");
  });

  it("getSystemErrors calls GET /api/v1/admin/system/errors without limit by default", async () => {
    mockGet.mockResolvedValueOnce({ errors: [], total: 0, retrieved_at: "" });

    await getSystemErrors();

    const [url] = mockGet.mock.calls[0] as [string];
    expect(url).toBe("/api/v1/admin/system/errors");
  });

  it("getSystemErrors appends limit query param when provided", async () => {
    mockGet.mockResolvedValueOnce({ errors: [], total: 0, retrieved_at: "" });

    await getSystemErrors(50);

    const [url] = mockGet.mock.calls[0] as [string];
    expect(url).toBe("/api/v1/admin/system/errors?limit=50");
  });

  it("getSystemMetrics calls GET /api/v1/admin/system/metrics without hours by default", async () => {
    mockGet.mockResolvedValueOnce({
      buckets: [],
      totals: {
        total_events: 0,
        total_errors: 0,
        total_skill_executions: 0,
        total_auth_events: 0,
      },
      period_hours: 24,
      generated_at: "",
    });

    await getSystemMetrics();

    const [url] = mockGet.mock.calls[0] as [string];
    expect(url).toBe("/api/v1/admin/system/metrics");
  });

  it("getSystemMetrics appends hours query param when provided", async () => {
    mockGet.mockResolvedValueOnce({
      buckets: [],
      totals: {
        total_events: 0,
        total_errors: 0,
        total_skill_executions: 0,
        total_auth_events: 0,
      },
      period_hours: 12,
      generated_at: "",
    });

    await getSystemMetrics(12);

    const [url] = mockGet.mock.calls[0] as [string];
    expect(url).toBe("/api/v1/admin/system/metrics?hours=12");
  });

  it("runSystemSelfTest calls POST /api/v1/admin/system/self-test", async () => {
    mockPost.mockResolvedValueOnce({
      overall: "pass",
      passed: 1,
      total: 1,
      results: [],
      ran_at: "",
    });

    const result = await runSystemSelfTest();

    expect(mockPost).toHaveBeenCalledWith(
      "/api/v1/admin/system/self-test",
      {}
    );
    expect(result.overall).toBe("pass");
  });

  // ── MiLA command ──────────────────────────────────────────────────────────────

  it("sendCommand calls POST /api/v1/admin/command with command payload", async () => {
    mockPost.mockResolvedValueOnce({
      command: "status",
      response: "All systems operational",
      executed_at: "2026-03-13T12:00:00",
    });

    const result = await sendCommand("status");

    expect(mockPost).toHaveBeenCalledWith("/api/v1/admin/command", {
      command: "status",
    });
    expect(result.command).toBe("status");
  });

  // ── Campaigns ─────────────────────────────────────────────────────────────────

  it("getCampaigns returns array when backend returns raw array", async () => {
    mockGet.mockResolvedValueOnce([campaignFixture]);

    const result = await getCampaigns();

    expect(mockGet).toHaveBeenCalledWith("/api/v1/admin/campaigns");
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe("March Push");
  });

  it("getCampaigns unwraps {campaigns:[...]} shape", async () => {
    mockGet.mockResolvedValueOnce({ campaigns: [campaignFixture] });

    const result = await getCampaigns();

    expect(result).toHaveLength(1);
    expect(result[0].channel).toBe("email");
  });

  // ── Calendar events ───────────────────────────────────────────────────────────

  it("getEvents returns array when backend returns raw array", async () => {
    mockGet.mockResolvedValueOnce([eventFixture]);

    const result = await getEvents();

    expect(mockGet).toHaveBeenCalledWith("/api/v1/admin/events");
    expect(result).toHaveLength(1);
    expect(result[0].title).toBe("Q1 Review");
  });

  it("getEvents unwraps {events:[...]} shape", async () => {
    mockGet.mockResolvedValueOnce({ events: [eventFixture] });

    const result = await getEvents();

    expect(result).toHaveLength(1);
    expect(result[0].type).toBe("deadline");
  });

  it("createEvent calls POST /api/v1/admin/events with payload", async () => {
    mockPost.mockResolvedValueOnce(eventFixture);

    const payload = { title: "Q1 Review", date: "2026-03-31", type: "deadline" as const };
    const result = await createEvent(payload);

    expect(mockPost).toHaveBeenCalledWith("/api/v1/admin/events", payload);
    expect(result.id).toBe("ev-1");
  });

  // ── Templates / Deploy ────────────────────────────────────────────────────────

  it("getAdminTemplates unwraps {templates:[...]} shape", async () => {
    mockGet.mockResolvedValueOnce({ templates: [templateFixture] });

    const result = await getAdminTemplates();

    expect(mockGet).toHaveBeenCalledWith("/api/v1/admin/templates");
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe("Sales Bot");
  });

  it("deployAgent calls POST /api/v1/admin/deploy with payload", async () => {
    mockPost.mockResolvedValueOnce(deploymentFixture);

    const result = await deployAgent({
      template_id: "tmpl-1",
      handle: "@testbot",
    });

    expect(mockPost).toHaveBeenCalledWith("/api/v1/admin/deploy", {
      template_id: "tmpl-1",
      handle: "@testbot",
    });
    expect(result.status).toBe("success");
  });

  it("getDeploymentHistory unwraps {history:[...]} shape", async () => {
    mockGet.mockResolvedValueOnce({ history: [deploymentFixture] });

    const result = await getDeploymentHistory();

    expect(mockGet).toHaveBeenCalledWith("/api/v1/admin/deploy/history");
    expect(result).toHaveLength(1);
    expect(result[0].handle).toBe("@testbot");
  });

  // ── Workflow tests ────────────────────────────────────────────────────────────

  it("getWorkflowTests unwraps {tests:[...]} shape", async () => {
    mockGet.mockResolvedValueOnce({ tests: [workflowTestFixture] });

    const result = await getWorkflowTests();

    expect(mockGet).toHaveBeenCalledWith("/api/v1/admin/workflow-tests");
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe("DB health");
  });

  it("runWorkflowTest calls POST with correct test ID in URL", async () => {
    mockPost.mockResolvedValueOnce(runTestFixture);

    const result = await runWorkflowTest("wt-1");

    expect(mockPost).toHaveBeenCalledWith(
      "/api/v1/admin/workflow-tests/wt-1/run",
      {}
    );
    expect(result.result).toBe("pass");
  });

  it("runAllWorkflowTests unwraps {results:[...]} shape", async () => {
    mockPost.mockResolvedValueOnce({ results: [runTestFixture] });

    const result = await runAllWorkflowTests();

    expect(mockPost).toHaveBeenCalledWith(
      "/api/v1/admin/workflow-tests/run-all",
      {}
    );
    expect(result).toHaveLength(1);
    expect(result[0].test_id).toBe("wt-1");
  });
});
