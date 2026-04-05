/**
 * Admin service — wires to admin-only backend endpoints.
 *
 * All endpoints require require_admin gate on the backend.
 *
 * Backend endpoints (expected):
 *   GET  /api/v1/admin/events                    — list calendar events
 *   POST /api/v1/admin/events                    — create calendar event
 *   GET  /api/v1/admin/templates                 — list agent templates with usage counts
 *   POST /api/v1/admin/deploy/marketing          — deploy marketing agent
 *   GET  /api/v1/admin/deploy/history            — deployment history
 *   GET  /api/v1/admin/workflows/tests           — list workflow test definitions
 *   POST /api/v1/admin/workflows/tests/{id}/run  — run a specific test
 *   POST /api/v1/admin/workflows/tests/run-all   — run all tests
 */

import { get, post } from "./client";

// ─── Admin Identity / Platform Stats Types ────────────────────────────────────

export interface AdminWhoami {
  user_id: string;
  email: string;
  is_admin: boolean;
  role: string;
}

export interface PlatformStats {
  total_users: number;
  total_agents: number;
  sessions_24h: number;
  errors_24h: number;
  active_sessions: number;
  revenue_mtd_cents: number;
}

// ─── Admin Identity / Platform Stats API ─────────────────────────────────────

/** Verify admin identity — used by AdminRoute and adminStore.checkAdmin(). */
export async function getWhoami(): Promise<AdminWhoami> {
  return get<AdminWhoami>("/api/v1/admin/whoami");
}

/** Top-level platform KPIs for the Command Center overview page. */
export async function getPlatformStats(): Promise<PlatformStats> {
  return get<PlatformStats>("/api/v1/admin/platform-stats");
}

// ─── Calendar / Scheduler Types ───────────────────────────────────────────────

export type EventType = "deadline" | "appointment" | "policy" | "reminder";

export interface AdminEvent {
  id: string;
  title: string;
  date: string; // ISO 8601
  type: EventType;
  description?: string;
}

export interface CreateEventPayload {
  title: string;
  date: string;
  type: EventType;
  description?: string;
}

// ─── Deploy Types ─────────────────────────────────────────────────────────────

export interface AdminTemplate {
  id: string;
  name: string;
  sector: string;
  description: string;
  agent_count: number;
  icon_key?: string;
}

export interface MarketingAgentStatus {
  deployed: boolean;
  handle?: string;
  deployed_at?: string;
}

export interface DeployPayload {
  template_id: string;
  handle: string;
}

export type DeploymentStatus = "success" | "pending" | "failed";

export interface DeploymentRecord {
  id: string;
  handle: string;
  template_name: string;
  status: DeploymentStatus;
  deployed_at: string;
}

// ─── Workflow / Test Types ────────────────────────────────────────────────────

export type TestResult = "pass" | "fail" | "pending" | "running";

export interface TestStep {
  name: string;
  result: "pass" | "fail";
  duration_ms: number;
  error?: string;
}

export interface WorkflowTest {
  id: string;
  name: string;
  description: string;
  last_result: TestResult;
  last_run_at?: string;
  steps?: TestStep[];
}

export interface RunTestResponse {
  test_id: string;
  result: TestResult;
  duration_ms: number;
  steps: TestStep[];
  ran_at: string;
}

export interface TestHistoryEntry {
  test_id: string;
  test_name: string;
  result: TestResult;
  duration_ms: number;
  ran_at: string;
}

// ─── Calendar API ─────────────────────────────────────────────────────────────

export async function getEvents(): Promise<AdminEvent[]> {
  const data = await get<AdminEvent[] | { events: AdminEvent[] }>(
    "/api/v1/admin/events"
  );
  if (Array.isArray(data)) return data;
  return data.events ?? [];
}

export async function createEvent(
  payload: CreateEventPayload
): Promise<AdminEvent> {
  return post<AdminEvent>("/api/v1/admin/events", payload);
}

// ─── Deploy API ───────────────────────────────────────────────────────────────

export async function getAdminTemplates(): Promise<AdminTemplate[]> {
  const data = await get<AdminTemplate[] | { templates: AdminTemplate[] }>(
    "/api/v1/admin/templates"
  );
  if (Array.isArray(data)) return data;
  return data.templates ?? [];
}

export async function getMarketingAgentStatus(): Promise<MarketingAgentStatus> {
  // Backend has no GET endpoint for marketing agent status — return default not-deployed state.
  return Promise.resolve({ deployed: false });
}

export async function deployMarketingAgent(): Promise<MarketingAgentStatus> {
  return post<MarketingAgentStatus>("/api/v1/admin/deploy-marketing-agent", {});
}

export async function deployAgent(payload: DeployPayload): Promise<DeploymentRecord> {
  return post<DeploymentRecord>("/api/v1/admin/deploy", payload);
}

export async function getDeploymentHistory(): Promise<DeploymentRecord[]> {
  const data = await get<DeploymentRecord[] | { history: DeploymentRecord[] }>(
    "/api/v1/admin/deploy/history"
  );
  if (Array.isArray(data)) return data;
  return data.history ?? [];
}

// ─── Workflow Tests API ───────────────────────────────────────────────────────

export async function getWorkflowTests(): Promise<WorkflowTest[]> {
  const data = await get<WorkflowTest[] | { tests: WorkflowTest[] }>(
    "/api/v1/admin/workflow-tests"
  );
  if (Array.isArray(data)) return data;
  return data.tests ?? [];
}

export async function runWorkflowTest(testId: string): Promise<RunTestResponse> {
  return post<RunTestResponse>(
    `/api/v1/admin/workflow-tests/${testId}/run`,
    {}
  );
}

export async function runAllWorkflowTests(): Promise<RunTestResponse[]> {
  const data = await post<RunTestResponse[] | { results: RunTestResponse[] }>(
    "/api/v1/admin/workflow-tests/run-all",
    {}
  );
  if (Array.isArray(data)) return data;
  return data.results ?? [];
}

export async function getTestHistory(): Promise<TestHistoryEntry[]> {
  const data = await get<TestHistoryEntry[] | { history: TestHistoryEntry[] }>(
    "/api/v1/admin/workflow-tests/history"
  );
  if (Array.isArray(data)) return data;
  return data.history ?? [];
}

// ─── Revenue / CRM Types ──────────────────────────────────────────────────────

export interface StripeStatus {
  mode: "test" | "live" | "not_configured";
  webhook_configured: boolean;
  last_event: string | null;
  customer_count: number;
}

export interface FunnelData {
  registered_users: number;
  claimed_handles: number;
  active_subscribers: number;
  active_7d: number;
  churned_30d: number;
}

export interface ContactsParams {
  page: number;
  per_page: number;
  search?: string;
}

export interface Contact {
  email: string;
  agent_handle: string | null;
  status: "active" | "inactive" | "churned";
  last_active: string | null;
  subscription_tier: string | null;
}

export interface PaginatedContacts {
  items: Contact[];
  total: number;
  page: number;
  per_page: number;
}

// ─── Revenue / CRM API ────────────────────────────────────────────────────────

export async function getStripeStatus(): Promise<StripeStatus> {
  return get<StripeStatus>("/api/v1/admin/stripe-status");
}

export async function getFunnel(): Promise<FunnelData> {
  return get<FunnelData>("/api/v1/admin/funnel");
}

export async function getContacts(params: ContactsParams): Promise<PaginatedContacts> {
  const q = new URLSearchParams({
    page: String(params.page),
    per_page: String(params.per_page),
  });
  if (params.search) {
    q.set("search", params.search);
  }
  return get<PaginatedContacts>(`/api/v1/admin/contacts?${q.toString()}`);
}

// ─── MiLA Command Types ───────────────────────────────────────────────────────

export interface CommandResponse {
  command: string;
  /** Backend field name is "response" — matches POST /admin/command return shape. */
  response: string | Record<string, unknown> | null | undefined;
  executed_at?: string;
}

// ─── Marketing Campaign Types ─────────────────────────────────────────────────

export type CampaignStatus = "draft" | "active" | "completed" | "failed";

export interface Campaign {
  id: string;
  name: string;
  channel: "email" | "sms" | "push" | "social";
  status: CampaignStatus;
  reach: number;
  opens: number;
  clicks: number;
  created_at: string;
}

export interface EmailStats {
  delivery_rate: number;
  open_rate: number;
  click_rate: number;
  bounce_rate: number;
  emails_sent: number;
  emails_delivered: number;
  period: string;
}

// ─── Alert Types ──────────────────────────────────────────────────────────────

export type AlertSeverity = "critical" | "warning" | "info";
export type AlertSource = "system" | "payment" | "security" | "integration";

export interface Alert {
  id: string;
  severity: AlertSeverity;
  title: string;
  description: string;
  source: AlertSource;
  timestamp: string;
  acknowledged: boolean;
}

export interface AlertConfig {
  error_rate_threshold: number;
  response_time_threshold_ms: number;
  failed_payment_alert: boolean;
  security_event_alert: boolean;
}

export interface AlertConfigResponse {
  success: boolean;
  config: AlertConfig;
}

// ─── MiLA Command API ─────────────────────────────────────────────────────────

/**
 * Send a command to the MiLA admin console.
 */
export async function sendCommand(command: string): Promise<CommandResponse> {
  return post<CommandResponse>("/api/v1/admin/command", { command });
}

// ─── Marketing Campaign API ───────────────────────────────────────────────────

/**
 * List all marketing campaigns.
 */
export async function getCampaigns(): Promise<Campaign[]> {
  const data = await get<Campaign[] | { campaigns: Campaign[] }>(
    "/api/v1/admin/campaigns"
  );
  if (Array.isArray(data)) return data;
  return data.campaigns ?? [];
}

/**
 * Get email delivery statistics.
 */
export async function getEmailStats(): Promise<EmailStats> {
  return get<EmailStats>("/api/v1/admin/email-stats");
}

// ─── Alerts API ───────────────────────────────────────────────────────────────

/**
 * List system alerts, newest first.
 */
export async function getAlerts(): Promise<Alert[]> {
  const data = await get<Alert[] | { alerts: Alert[] }>(
    "/api/v1/admin/alerts"
  );
  if (Array.isArray(data)) return data;
  return data.alerts ?? [];
}

/**
 * Acknowledge an alert by ID.
 */
export async function acknowledgeAlert(alertId: string): Promise<void> {
  await post(`/api/v1/admin/alerts/${alertId}/acknowledge`, {});
}

/**
 * Save alert configuration thresholds.
 */
export async function configureAlerts(
  config: AlertConfig
): Promise<AlertConfigResponse> {
  return post<AlertConfigResponse>("/api/v1/admin/alerts/configure", config);
}

// ─── Ops: Agent Control Types ─────────────────────────────────────────────────

export interface AdminAgent {
  id: string;
  handle: string;
  owner_email: string;
  status: "active" | "suspended" | "inactive";
  template_name: string;
  created_at: string;
  last_active: string | null;
  message_count: number;
}

export interface AgentsListResponse {
  agents: AdminAgent[];
  total: number;
  page: number;
  per_page: number;
}

export interface AgentsListParams {
  page?: number;
  per_page?: number;
  search?: string;
  status?: string;
}

export interface TemplateDistributionItem {
  template_name: string;
  count: number;
}

// ─── Ops: Debug Monitor Types ─────────────────────────────────────────────────

export interface ErrorEntry {
  id: string;
  endpoint: string;
  message: string;
  status: number;
  count: number;
  last_seen: string;
}

export interface HealthDetailed {
  uptime_seconds: number;
  db_size_mb: number;
  memory_mb: number;
  avg_response_ms: number;
  top_endpoints: EndpointStat[];
  response_times: EndpointResponseTime[];
}

export interface EndpointStat {
  endpoint: string;
  request_count: number;
  avg_response_ms: number;
  error_rate: number;
}

export interface EndpointResponseTime {
  endpoint: string;
  avg_ms: number;
}

// ─── Ops: Integration Health Types ───────────────────────────────────────────

export type IntegrationStatus = "connected" | "disconnected" | "not_configured";

export interface IntegrationHealth {
  name: string;
  key: string;
  status: IntegrationStatus;
  connected_agents: number;
  webhook_success_rate: number | null;
  last_tested_at: string | null;
  last_test_result: "pass" | "fail" | null;
  last_test_response_ms: number | null;
  mode?: string;
}

export interface IntegrationTestResult {
  key: string;
  result: "pass" | "fail";
  response_ms: number;
  tested_at: string;
  message: string;
}

// ─── Ops: Agent Control API ───────────────────────────────────────────────────

export async function getAgentsList(
  params?: AgentsListParams
): Promise<AgentsListResponse> {
  const query = new URLSearchParams();
  if (params?.page !== undefined) query.set("page", String(params.page));
  if (params?.per_page !== undefined)
    query.set("per_page", String(params.per_page));
  if (params?.search) query.set("search", params.search);
  if (params?.status && params.status !== "all")
    query.set("status", params.status);
  const qs = query.toString() ? `?${query.toString()}` : "";
  return get<AgentsListResponse>(`/api/v1/admin/agents${qs}`);
}

export async function suspendAdminAgent(agentId: string): Promise<void> {
  await post(`/api/v1/admin/agents/${agentId}/suspend`, {});
}

export async function activateAdminAgent(agentId: string): Promise<void> {
  await post(`/api/v1/admin/agents/${agentId}/activate`, {});
}

export async function getAgentTemplateDistribution(): Promise<
  TemplateDistributionItem[]
> {
  const data = await get<
    TemplateDistributionItem[] | { distribution: TemplateDistributionItem[] }
  >("/api/v1/admin/agents/template-distribution");
  if (Array.isArray(data)) return data;
  return data.distribution ?? [];
}

// ─── Client Error Types ───────────────────────────────────────────────────────

export type ClientErrorType =
  | "js_error"
  | "unhandled_rejection"
  | "api_error"
  | "render_error";

export interface ClientErrorEntry {
  id: string;
  source: "client";
  message: string;
  stack?: string;
  /** The page URL where the error occurred. */
  endpoint: string;
  error_type: ClientErrorType;
  component?: string;
  count: 1;
  first_seen: string;
  last_seen: string;
  status: 0;
  extra?: Record<string, unknown>;
}

// ─── Ops: Debug Monitor API ───────────────────────────────────────────────────

export async function getErrors(): Promise<ErrorEntry[]> {
  const data = await get<{ errors: ErrorEntry[] } | ErrorEntry[]>(
    "/api/v1/admin/errors"
  );
  if (Array.isArray(data)) return data;
  return data.errors ?? [];
}

/** Report a single client-side error batch directly (used by errorReporter internally via fetch). */
export async function getClientErrors(): Promise<ClientErrorEntry[]> {
  const data = await get<{ errors: ClientErrorEntry[] } | ClientErrorEntry[]>(
    "/api/v1/admin/errors"
  );
  // The merged /errors endpoint returns both server + client; filter to source=client
  const all = Array.isArray(data) ? data : (data.errors ?? []);
  return (all as Array<ErrorEntry & Partial<ClientErrorEntry>>).filter(
    (e): e is ClientErrorEntry => e.source === "client"
  );
}

/** Clear all client-side errors from the database. */
export async function clearClientErrors(): Promise<void> {
  await post("/api/v1/admin/client-errors/clear", {});
}

export async function clearErrors(): Promise<void> {
  await post("/api/v1/admin/errors/clear", {});
}

export async function getHealthDetailed(): Promise<HealthDetailed> {
  return get<HealthDetailed>("/api/v1/admin/health-detailed");
}

// ─── Ops: Integration Health API ──────────────────────────────────────────────

export async function getIntegrationHealth(): Promise<IntegrationHealth[]> {
  const data = await get<
    { integrations: IntegrationHealth[] } | IntegrationHealth[]
  >("/api/v1/admin/integration-health");
  if (Array.isArray(data)) return data;
  return data.integrations ?? [];
}

export async function testIntegration(
  key: string
): Promise<IntegrationTestResult> {
  return post<IntegrationTestResult>(
    `/api/v1/admin/integrations/${key}/test`,
    {}
  );
}

// ─── System Health Types ───────────────────────────────────────────────────────

export type SystemStatus = "healthy" | "degraded" | "critical";
export type ComponentStatus = "ok" | "error" | "warning" | "unavailable";
export type CircuitBreakerState = "CLOSED" | "OPEN" | "HALF_OPEN";
export type IntegrationConfigStatus = "configured" | "unconfigured" | "live" | "test";

export interface DatabaseComponent {
  status: ComponentStatus;
  latency_ms: number | null;
}

export interface LLMProviderInfo {
  status: ComponentStatus | "unavailable";
  configured: boolean;
  error_rate_1h?: number | null;
  reason?: string;
}

export interface IntegrationInfo {
  status: IntegrationConfigStatus;
  last_webhook?: string | null;
}

export interface SecurityLayers {
  rate_limiter: string;
  constitution: string;
  input_sanitizer: string;
  bot_prevention: string;
  token_revocation_guard: string;
  tier_isolation: string;
}

export interface SystemComponents {
  database: DatabaseComponent;
  llm_providers: Record<string, LLMProviderInfo>;
  integrations: Record<string, IntegrationInfo>;
  security: SecurityLayers;
}

export interface SystemMetricsSummary {
  total_agents: number;
  total_sessions: number;
  total_messages: number;
  active_sessions_24h: number;
  error_rate_1h: number;
  avg_response_time_ms: number | null;
}

export interface RecentErrorEntry {
  timestamp: string;
  type: string;
  message: string;
  count: number;
  first_seen: string;
}

export interface AutoRecoveryRecord {
  timestamp: string;
  issue: string;
  action: string;
}

export interface SelfHealingInfo {
  circuit_breakers: Record<string, CircuitBreakerState>;
  auto_recovered: AutoRecoveryRecord[];
}

export interface SystemHealthReport {
  status: SystemStatus;
  uptime_seconds: number;
  timestamp: string;
  components: SystemComponents;
  metrics: SystemMetricsSummary;
  recent_errors: RecentErrorEntry[];
  self_healing: SelfHealingInfo;
}

export interface SystemErrorEntry {
  timestamp: string;
  event_type: string;
  actor: string;
  message: string;
  endpoint: string;
  details: Record<string, unknown>;
  /** Present when errors are embedded in the health report (recent_errors array). */
  count?: number;
}

export interface SystemErrorsResponse {
  errors: SystemErrorEntry[];
  total: number;
  retrieved_at: string;
}

export interface MetricsBucket {
  hour: string;
  event_count: number;
  error_count: number;
  skill_count: number;
  auth_count: number;
}

export interface MetricsTotals {
  total_events: number;
  total_errors: number;
  total_skill_executions: number;
  total_auth_events: number;
}

export interface SystemMetricsResponse {
  buckets: MetricsBucket[];
  totals: MetricsTotals;
  period_hours: number;
  generated_at: string;
}

export interface SelfTestResult {
  test: string;
  result: "pass" | "fail";
  message: string;
  duration_ms: number;
}

export interface SelfTestResponse {
  overall: "pass" | "fail";
  passed: number;
  total: number;
  results: SelfTestResult[];
  ran_at: string;
}

// ─── System Health API ────────────────────────────────────────────────────────

/** Full system health report — the main dashboard data source. */
export async function getSystemHealth(): Promise<SystemHealthReport> {
  return get<SystemHealthReport>("/api/v1/admin/system/health");
}

/** Raw recent error entries from the audit chain. */
export async function getSystemErrors(
  limit?: number
): Promise<SystemErrorsResponse> {
  const qs = limit !== undefined ? `?limit=${limit}` : "";
  return get<SystemErrorsResponse>(`/api/v1/admin/system/errors${qs}`);
}

/** Time-series metrics bucketed by hour. */
export async function getSystemMetrics(
  hours?: number
): Promise<SystemMetricsResponse> {
  const qs = hours !== undefined ? `?hours=${hours}` : "";
  return get<SystemMetricsResponse>(`/api/v1/admin/system/metrics${qs}`);
}

/** Trigger integration self-tests — returns per-test results. */
export async function runSystemSelfTest(): Promise<SelfTestResponse> {
  return post<SelfTestResponse>("/api/v1/admin/system/self-test", {});
}
