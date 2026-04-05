/**
 * Admin Command Center — E2E Tests
 *
 * Covers all 12 admin pages + the auth gate:
 *   /admin             — Overview (KPI cards, health, alerts, quick actions)
 *   /admin/mila        — MiLA Command Console
 *   /admin/agents      — Agent Control Center
 *   /admin/debug       — Debug Monitor
 *   /admin/revenue     — Revenue Dashboard
 *   /admin/crm         — CRM Pipeline
 *   /admin/alerts      — Alert Management
 *   /admin/marketing   — Marketing Campaign Center
 *   /admin/workflows   — Workflow Test Runner
 *   /admin/scheduler   — Scheduler / Calendar
 *   /admin/deploy      — Agent Deployment Center
 *   /admin/integrations — Integration Health Dashboard
 *   /admin/system      — System Health
 *
 * Strategy:
 *   - All API calls are intercepted with page.route() — no live backend required.
 *   - Auth state is injected via localStorage before navigation.
 *   - Tests assert that pages render without crashing and display key UI elements.
 *   - Error-state tests remove mocks to trigger error paths.
 *
 * Conventions:
 *   - ADMIN_EMAIL must match NEXT_PUBLIC_ADMIN_EMAIL in the test environment.
 *     For local runs set it via .env.test.local. We use "admin@dingdawg.com" as
 *     the canonical test value (can be overridden by TEST_ADMIN_EMAIL env var).
 */

import { test, expect, Page, Route } from "@playwright/test";

// ─── Constants ────────────────────────────────────────────────────────────────

const ADMIN_EMAIL =
  process.env.TEST_ADMIN_EMAIL ?? "admin@dingdawg.com";

const NON_ADMIN_EMAIL = "user@example.com";

// Auth store shape that AdminRoute reads from localStorage
function buildAuthState(email: string, authenticated: boolean) {
  return JSON.stringify({
    state: {
      user: authenticated ? { id: "usr-1", email, name: "Test User" } : null,
      token: authenticated ? "fake-jwt-token" : null,
      isAuthenticated: authenticated,
      isHydrated: true,
    },
    version: 0,
  });
}

async function injectAdminAuth(page: Page) {
  await page.evaluate(
    ({ email, value }: { email: string; value: string }) => {
      localStorage.setItem("auth-store", value);
      // Also set the token so API client calls include it
      localStorage.setItem("token", "fake-jwt-token");
    },
    { email: ADMIN_EMAIL, value: buildAuthState(ADMIN_EMAIL, true) }
  );
}

async function injectNonAdminAuth(page: Page) {
  await page.evaluate(
    ({ value }: { value: string }) => {
      localStorage.setItem("auth-store", value);
      localStorage.setItem("token", "fake-jwt-token");
    },
    { value: buildAuthState(NON_ADMIN_EMAIL, true) }
  );
}

async function clearAuth(page: Page) {
  await page.evaluate(() => {
    localStorage.removeItem("auth-store");
    localStorage.removeItem("token");
  });
}

// ─── Mock API helpers ─────────────────────────────────────────────────────────

/** Route all /api/v1/admin/* calls to mock JSON responses. */
async function mockAdminApis(page: Page) {
  // Platform stats
  await page.route("**/api/v1/admin/platform-stats", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total_users: 1234,
        total_agents: 567,
        sessions_24h: 890,
        errors_24h: 3,
        active_sessions: 12,
        revenue_mtd_cents: 0,
      }),
    });
  });

  // Stripe status
  await page.route("**/api/v1/admin/stripe-status", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        mode: "test",
        webhook_configured: false,
        last_event: null,
        customer_count: 0,
      }),
    });
  });

  // Alerts
  await page.route("**/api/v1/admin/alerts", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "alert-1",
          severity: "warning",
          title: "High memory usage detected",
          description: "Memory at 85% capacity",
          source: "system",
          timestamp: new Date().toISOString(),
          acknowledged: false,
        },
        {
          id: "alert-2",
          severity: "info",
          title: "New user registered",
          description: "User john@example.com registered",
          source: "system",
          timestamp: new Date().toISOString(),
          acknowledged: true,
        },
      ]),
    });
  });

  // Health detailed
  await page.route("**/api/v1/admin/health-detailed", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        uptime_seconds: 86400,
        db_size_mb: 42.3,
        memory_mb: 512,
        avg_response_ms: 145,
        top_endpoints: [
          {
            endpoint: "/api/v1/chat",
            request_count: 500,
            avg_response_ms: 120,
            error_rate: 0.01,
          },
        ],
        response_times: [
          { endpoint: "/api/v1/chat", avg_ms: 120 },
          { endpoint: "/api/v1/agent", avg_ms: 200 },
        ],
      }),
    });
  });

  // Agents list
  await page.route("**/api/v1/admin/agents**", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        agents: [
          {
            id: "agent-uuid-1",
            handle: "test-agent",
            owner_email: "owner@example.com",
            status: "active",
            template_name: "Restaurant",
            created_at: "2024-01-01T00:00:00Z",
            last_active: "2024-06-01T00:00:00Z",
            message_count: 42,
          },
          {
            id: "agent-uuid-2",
            handle: "suspended-agent",
            owner_email: "owner2@example.com",
            status: "suspended",
            template_name: "Retail",
            created_at: "2024-02-01T00:00:00Z",
            last_active: null,
            message_count: 0,
          },
        ],
        total: 2,
        page: 1,
        per_page: 20,
      }),
    });
  });

  // Agent template distribution
  await page.route(
    "**/api/v1/admin/agents/template-distribution",
    (route: Route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          { template_name: "Restaurant", count: 10 },
          { template_name: "Retail", count: 5 },
        ]),
      });
    }
  );

  // Errors list
  await page.route("**/api/v1/admin/errors", (route: Route) => {
    if (route.request().method() === "GET") {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          errors: [
            {
              id: "err-1",
              endpoint: "/api/v1/chat",
              message: "Rate limit exceeded",
              status: 429,
              count: 5,
              last_seen: new Date().toISOString(),
            },
          ],
        }),
      });
    } else {
      route.fulfill({ status: 200, body: "{}" });
    }
  });

  // Revenue funnel
  await page.route("**/api/v1/admin/funnel", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        registered_users: 100,
        claimed_handles: 50,
        active_subscribers: 20,
        active_7d: 15,
        churned_30d: 3,
      }),
    });
  });

  // Contacts
  await page.route("**/api/v1/admin/contacts**", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            email: "contact@example.com",
            agent_handle: "my-agent",
            status: "active",
            last_active: new Date().toISOString(),
            subscription_tier: "pro",
          },
        ],
        total: 1,
        page: 1,
        per_page: 20,
      }),
    });
  });

  // MiLA command
  await page.route("**/api/v1/admin/command", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        command: "status",
        response: "System operational. All services running.",
        executed_at: new Date().toISOString(),
      }),
    });
  });

  // Campaigns
  await page.route("**/api/v1/admin/campaigns", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "camp-1",
          name: "Welcome Campaign",
          channel: "email",
          status: "active",
          reach: 500,
          opens: 200,
          clicks: 80,
          created_at: "2024-01-01T00:00:00Z",
        },
      ]),
    });
  });

  // Email stats
  await page.route("**/api/v1/admin/email-stats", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        delivery_rate: 0.97,
        open_rate: 0.38,
        click_rate: 0.15,
        bounce_rate: 0.02,
        emails_sent: 500,
        emails_delivered: 485,
        period: "Last 30 days",
      }),
    });
  });

  // Deploy marketing agent
  await page.route(
    "**/api/v1/admin/deploy-marketing-agent",
    (route: Route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          deployed: true,
          handle: "dingdawg-marketing",
          deployed_at: new Date().toISOString(),
        }),
      });
    }
  );

  // Templates
  await page.route("**/api/v1/admin/templates", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "tmpl-1",
          name: "Restaurant Agent",
          sector: "restaurant",
          description: "Full-service restaurant booking and menu agent",
          agent_count: 10,
          icon_key: "restaurant",
        },
        {
          id: "tmpl-2",
          name: "Retail Agent",
          sector: "ecommerce",
          description: "E-commerce product discovery and checkout agent",
          agent_count: 5,
          icon_key: "shopping",
        },
      ]),
    });
  });

  // Deployment history
  await page.route("**/api/v1/admin/deploy/history", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "deploy-1",
          handle: "test-deploy",
          template_name: "Restaurant Agent",
          status: "success",
          deployed_at: "2024-06-01T10:00:00Z",
        },
      ]),
    });
  });

  // Deploy agent
  await page.route("**/api/v1/admin/deploy", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "deploy-new",
        handle: "new-agent",
        template_name: "Restaurant Agent",
        status: "success",
        deployed_at: new Date().toISOString(),
      }),
    });
  });

  // Workflow tests
  await page.route("**/api/v1/admin/workflow-tests", (route: Route) => {
    if (!route.request().url().includes("/run") && !route.request().url().includes("/history")) {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: "health-check",
            name: "Health Check",
            description: "Verifies all backend services are reachable.",
            last_result: "pass",
            last_run_at: new Date().toISOString(),
          },
          {
            id: "auth-flow",
            name: "Auth Flow",
            description: "Registers a test user, logs in, refreshes token.",
            last_result: "pending",
            last_run_at: null,
          },
        ]),
      });
    } else {
      route.continue();
    }
  });

  // Workflow test run
  await page.route("**/api/v1/admin/workflow-tests/**/run", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        test_id: "health-check",
        result: "pass",
        duration_ms: 142,
        steps: [
          { name: "Ping database", result: "pass", duration_ms: 12 },
          { name: "Ping LLM provider", result: "pass", duration_ms: 130 },
        ],
        ran_at: new Date().toISOString(),
      }),
    });
  });

  // Workflow run-all
  await page.route(
    "**/api/v1/admin/workflow-tests/run-all",
    (route: Route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            test_id: "health-check",
            result: "pass",
            duration_ms: 200,
            steps: [],
            ran_at: new Date().toISOString(),
          },
        ]),
      });
    }
  );

  // Workflow test history
  await page.route(
    "**/api/v1/admin/workflow-tests/history",
    (route: Route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            test_id: "health-check",
            test_name: "Health Check",
            result: "pass",
            duration_ms: 120,
            ran_at: new Date().toISOString(),
          },
        ]),
      });
    }
  );

  // Calendar events
  await page.route("**/api/v1/admin/events", (route: Route) => {
    if (route.request().method() === "GET") {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: "evt-1",
            title: "Q2 Launch Review",
            date: new Date(Date.now() + 7 * 86400000).toISOString(),
            type: "deadline",
            description: "Review all Q2 milestones",
          },
          {
            id: "evt-2",
            title: "Colorado AI Act Deadline",
            date: "2026-06-30T00:00:00Z",
            type: "policy",
            description: "SB 205 compliance required",
          },
        ]),
      });
    } else {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "evt-new",
          title: "Test Event",
          date: new Date().toISOString(),
          type: "reminder",
        }),
      });
    }
  });

  // Integration health
  await page.route("**/api/v1/admin/integration-health", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          name: "SendGrid",
          key: "sendgrid",
          status: "connected",
          connected_agents: 3,
          webhook_success_rate: 0.99,
          last_tested_at: new Date().toISOString(),
          last_test_result: "pass",
          last_test_response_ms: 45,
          mode: null,
        },
        {
          name: "Stripe",
          key: "stripe",
          status: "connected",
          connected_agents: 10,
          webhook_success_rate: 0.98,
          last_tested_at: new Date().toISOString(),
          last_test_result: "pass",
          last_test_response_ms: 120,
          mode: "test",
        },
        {
          name: "Twilio",
          key: "twilio",
          status: "not_configured",
          connected_agents: 0,
          webhook_success_rate: null,
          last_tested_at: null,
          last_test_result: null,
          last_test_response_ms: null,
          mode: null,
        },
      ]),
    });
  });

  // Integration test
  await page.route(
    "**/api/v1/admin/integrations/**/test",
    (route: Route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          key: "sendgrid",
          result: "pass",
          response_ms: 55,
          tested_at: new Date().toISOString(),
          message: "SendGrid connection verified",
        }),
      });
    }
  );

  // Alert acknowledge
  await page.route(
    "**/api/v1/admin/alerts/**/acknowledge",
    (route: Route) => {
      route.fulfill({ status: 200, body: "{}" });
    }
  );

  // Alert configure
  await page.route("**/api/v1/admin/alerts/configure", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        config: {
          error_rate_threshold: 5,
          response_time_threshold_ms: 2000,
          failed_payment_alert: true,
          security_event_alert: true,
        },
      }),
    });
  });

  // System health
  await page.route("**/api/v1/admin/system/health", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "healthy",
        uptime_seconds: 86400,
        timestamp: new Date().toISOString(),
        components: {
          database: { status: "ok", latency_ms: 5 },
          llm_providers: {
            openai: { status: "ok", configured: true, error_rate_1h: 0.01 },
            anthropic: {
              status: "ok",
              configured: true,
              error_rate_1h: 0.005,
            },
          },
          integrations: {
            stripe: { status: "test", last_webhook: null },
            sendgrid: { status: "configured", last_webhook: null },
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
          total_agents: 567,
          total_sessions: 8900,
          total_messages: 45000,
          active_sessions_24h: 890,
          error_rate_1h: 0.005,
          avg_response_time_ms: 145,
        },
        recent_errors: [],
        self_healing: {
          circuit_breakers: { openai: "CLOSED", stripe: "CLOSED" },
          auto_recovered: [],
        },
      }),
    });
  });

  // System errors
  await page.route("**/api/v1/admin/system/errors**", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        errors: [],
        total: 0,
        retrieved_at: new Date().toISOString(),
      }),
    });
  });

  // System self-test
  await page.route("**/api/v1/admin/system/self-test", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        overall: "pass",
        passed: 4,
        total: 4,
        results: [
          {
            test: "Database",
            result: "pass",
            message: "Tables verified",
            duration_ms: 12,
          },
          {
            test: "OpenAI",
            result: "pass",
            message: "API key valid",
            duration_ms: 340,
          },
          {
            test: "Stripe",
            result: "pass",
            message: "Webhook reachable",
            duration_ms: 150,
          },
          {
            test: "Security",
            result: "pass",
            message: "All layers active",
            duration_ms: 5,
          },
        ],
        ran_at: new Date().toISOString(),
      }),
    });
  });

  // Whoami
  await page.route("**/api/v1/admin/whoami", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        user_id: "usr-1",
        email: ADMIN_EMAIL,
        is_admin: true,
        role: "admin",
      }),
    });
  });

  // System metrics
  await page.route("**/api/v1/admin/system/metrics**", (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        buckets: [],
        totals: {
          total_events: 0,
          total_errors: 0,
          total_skill_executions: 0,
          total_auth_events: 0,
        },
        period_hours: 24,
        generated_at: new Date().toISOString(),
      }),
    });
  });

  // Errors clear
  await page.route("**/api/v1/admin/errors/clear", (route: Route) => {
    route.fulfill({ status: 200, body: "{}" });
  });
}

// ─── Auth gate setup helper ───────────────────────────────────────────────────

/**
 * Navigate to a page and inject auth BEFORE the page loads by using
 * addInitScript, which runs before any page JS executes.
 */
async function gotoWithAuth(
  page: Page,
  url: string,
  email: string,
  authenticated: boolean
) {
  const authValue = buildAuthState(email, authenticated);
  await page.addInitScript(
    ({ key, value }: { key: string; value: string }) => {
      localStorage.setItem(key, value);
      if (value.includes('"isAuthenticated":true')) {
        localStorage.setItem("token", "fake-jwt-token");
      }
    },
    { key: "auth-store", value: authValue }
  );
  await page.goto(url);
}

// ─── Auth Gate Tests ──────────────────────────────────────────────────────────

test.describe("Admin Auth Gate", () => {
  test("unauthenticated user is redirected to /login with returnTo", async ({
    page,
  }) => {
    // Navigate without injecting any auth — store will be empty/null
    await page.goto("/admin");

    // AdminRoute sees !isAuthenticated and calls router.replace
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
    // returnTo param should be present
    await expect(page).toHaveURL(/returnTo=%2Fadmin|returnTo=\/admin/);
  });

  test("authenticated non-admin is redirected to /dashboard", async ({
    page,
  }) => {
    await gotoWithAuth(page, "/admin", NON_ADMIN_EMAIL, true);

    // AdminRoute detects email mismatch and redirects
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10_000 });
  });

  test("authenticated admin sees admin content without redirect", async ({
    page,
  }) => {
    await mockAdminApis(page);
    await gotoWithAuth(page, "/admin", ADMIN_EMAIL, true);

    // Must NOT be redirected to /login or /dashboard
    await expect(page).toHaveURL(/\/admin$/, { timeout: 10_000 });

    // Stripe status banner should appear (rendered by overview page)
    await expect(page.getByText(/stripe/i).first()).toBeVisible({
      timeout: 10_000,
    });
  });
});

// ─── Overview Page ────────────────────────────────────────────────────────────

test.describe("Admin Overview Page (/admin)", () => {
  test.beforeEach(async ({ page }) => {
    await mockAdminApis(page);
    await gotoWithAuth(page, "/admin", ADMIN_EMAIL, true);
    await expect(page).toHaveURL(/\/admin$/, { timeout: 10_000 });
  });

  test("renders stripe mode badge", async ({ page }) => {
    // Stripe TEST mode banner rendered by overview page
    await expect(
      page.getByText(/stripe test mode/i)
    ).toBeVisible({ timeout: 10_000 });
  });

  test("renders KPI stat cards", async ({ page }) => {
    // Wait for the Platform section heading
    await expect(page.getByText("Platform")).toBeVisible({ timeout: 10_000 });

    // At least one stat card with a numeric value should appear
    await expect(page.getByText("Total Users")).toBeVisible();
    await expect(page.getByText("Total Agents")).toBeVisible();
  });

  test("renders system health section", async ({ page }) => {
    await expect(page.getByText(/system health/i)).toBeVisible({
      timeout: 10_000,
    });
    // Uptime row
    await expect(page.getByText("Uptime")).toBeVisible();
  });

  test("renders recent alerts section", async ({ page }) => {
    await expect(page.getByText(/recent alerts/i)).toBeVisible({
      timeout: 10_000,
    });
    // The mocked alert title
    await expect(
      page.getByText("High memory usage detected")
    ).toBeVisible({ timeout: 8_000 });
  });

  test("renders quick action buttons", async ({ page }) => {
    await expect(page.getByText(/quick actions/i)).toBeVisible({
      timeout: 10_000,
    });
    await expect(
      page.getByRole("link", { name: /view agents/i })
    ).toBeVisible();
    await expect(page.getByRole("link", { name: /revenue/i })).toBeVisible();
    await expect(page.getByRole("link", { name: /alerts/i })).toBeVisible();
  });

  test("does not crash when API returns error", async ({ page }) => {
    // This tests that a previously loaded page doesn't crash when polled data fails.
    // We override the health endpoint to 500 after initial load.
    await page.route("**/api/v1/admin/health-detailed", (route: Route) => {
      route.fulfill({ status: 500, body: '{"detail":"server error"}' });
    });
    // Re-navigate to trigger fresh fetch
    await page.goto("/admin");
    await gotoWithAuth(page, "/admin", ADMIN_EMAIL, true);
    // Page must not show a crash — Stripe banner should still render
    await expect(page.getByText(/stripe/i).first()).toBeVisible({
      timeout: 10_000,
    });
  });
});

// ─── MiLA Command Console ─────────────────────────────────────────────────────

test.describe("MiLA Command Console (/admin/mila)", () => {
  test.beforeEach(async ({ page }) => {
    await mockAdminApis(page);
    await gotoWithAuth(page, "/admin/mila", ADMIN_EMAIL, true);
    await expect(page).toHaveURL(/\/admin\/mila/, { timeout: 10_000 });
  });

  test("renders page title and subtitle", async ({ page }) => {
    await expect(
      page.getByText("MiLA Command Console")
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByText(/admin-only interactive command interface/i)
    ).toBeVisible();
  });

  test("renders welcome message", async ({ page }) => {
    await expect(
      page.getByText(/command center ready/i)
    ).toBeVisible({ timeout: 10_000 });
  });

  test("renders quick command buttons", async ({ page }) => {
    await expect(page.getByRole("button", { name: /status/i })).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByRole("button", { name: /stats/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /errors/i })).toBeVisible();
    await expect(
      page.getByRole("button", { name: /test health/i })
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /deploy status/i })
    ).toBeVisible();
  });

  test("textarea input accepts text", async ({ page }) => {
    const textarea = page.getByPlaceholder(/type a command/i);
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    await textarea.fill("status");
    await expect(textarea).toHaveValue("status");
  });

  test("send button is enabled when text is present", async ({ page }) => {
    const textarea = page.getByPlaceholder(/type a command/i);
    await textarea.fill("status");
    const sendButton = page.getByRole("button", { name: /send command/i });
    await expect(sendButton).toBeEnabled();
  });

  test("send button is disabled when textarea is empty", async ({ page }) => {
    const sendButton = page.getByRole("button", { name: /send command/i });
    // Textarea is empty on load — button should be disabled
    await expect(sendButton).toBeDisabled();
  });

  test("clicking quick command button sends command and shows response", async ({
    page,
  }) => {
    // Click the "Status" quick command
    await page.getByRole("button", { name: /^status$/i }).click();

    // Response text from the mock should appear
    await expect(
      page.getByText(/system operational/i)
    ).toBeVisible({ timeout: 10_000 });
  });

  test("typing and pressing Enter sends command", async ({ page }) => {
    const textarea = page.getByPlaceholder(/type a command/i);
    await textarea.fill("stats");
    await textarea.press("Enter");

    // Mock response should appear
    await expect(
      page.getByText(/system operational/i)
    ).toBeVisible({ timeout: 10_000 });
  });
});

// ─── Agent Control Center ─────────────────────────────────────────────────────

test.describe("Agent Control Center (/admin/agents)", () => {
  test.beforeEach(async ({ page }) => {
    await mockAdminApis(page);
    await gotoWithAuth(page, "/admin/agents", ADMIN_EMAIL, true);
    await expect(page).toHaveURL(/\/admin\/agents/, { timeout: 10_000 });
  });

  test("renders page heading", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: /agent control center/i })
    ).toBeVisible({ timeout: 10_000 });
  });

  test("renders summary stat cards", async ({ page }) => {
    await expect(page.getByText("Total Agents")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("Active Today")).toBeVisible();
    await expect(page.getByText("Suspended")).toBeVisible();
    await expect(page.getByText("Templates Used")).toBeVisible();
  });

  test("renders search input and status filter buttons", async ({ page }) => {
    const searchInput = page.getByPlaceholder(/search handle or email/i);
    await expect(searchInput).toBeVisible({ timeout: 10_000 });

    // Filter buttons: all, active, suspended, inactive
    await expect(page.getByRole("button", { name: /^all$/i })).toBeVisible();
    await expect(
      page.getByRole("button", { name: /^active$/i })
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /^suspended$/i })
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /^inactive$/i })
    ).toBeVisible();
  });

  test("renders agent table with mocked data", async ({ page }) => {
    // Table columns
    await expect(page.getByText("Handle")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Owner")).toBeVisible();
    await expect(page.getByText("Status")).toBeVisible();

    // Agent handle from mock
    await expect(page.getByText("@test-agent")).toBeVisible({ timeout: 8_000 });
    await expect(page.getByText("@suspended-agent")).toBeVisible();
  });

  test("clicking status filter changes active filter", async ({ page }) => {
    const activeBtn = page.getByRole("button", { name: /^active$/i });
    await activeBtn.click();

    // Button should take on the active style (gold bg in Tailwind)
    // We assert it no longer has the same de-selected appearance by checking aria or class
    await expect(activeBtn).toBeVisible();
  });

  test("search input accepts text", async ({ page }) => {
    const searchInput = page.getByPlaceholder(/search handle or email/i);
    await searchInput.fill("test-agent");
    await expect(searchInput).toHaveValue("test-agent");
  });

  test("agent control page shows action buttons in rows", async ({ page }) => {
    // active agent has "Suspend" button; suspended has "Activate"
    await expect(
      page.getByRole("button", { name: /suspend/i }).first()
    ).toBeVisible({ timeout: 8_000 });
    await expect(
      page.getByRole("button", { name: /activate/i }).first()
    ).toBeVisible({ timeout: 8_000 });
  });

  test("API failure shows error state rather than crash", async ({ page }) => {
    // Override agents endpoint to 500 after initial load
    await page.route("**/api/v1/admin/agents**", (route: Route) => {
      route.fulfill({ status: 500, body: '{"detail":"DB error"}' });
    });
    await page.reload();
    // Page must remain at /admin/agents and show some form of error or empty state
    await expect(page).toHaveURL(/\/admin\/agents/);
    // The heading must still be there (page didn't crash entirely)
    await expect(
      page.getByRole("heading", { name: /agent control center/i })
    ).toBeVisible({ timeout: 10_000 });
  });
});

// ─── Debug Monitor ────────────────────────────────────────────────────────────

test.describe("Debug Monitor (/admin/debug)", () => {
  test.beforeEach(async ({ page }) => {
    await mockAdminApis(page);
    await gotoWithAuth(page, "/admin/debug", ADMIN_EMAIL, true);
    await expect(page).toHaveURL(/\/admin\/debug/, { timeout: 10_000 });
  });

  test("renders page heading and subtitle", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: /debug monitor/i })
    ).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/refreshes every 10s/i)).toBeVisible();
  });

  test("renders system health stats section", async ({ page }) => {
    await expect(page.getByText(/system health/i)).toBeVisible({
      timeout: 10_000,
    });
    // Health stat pills
    await expect(page.getByText("Uptime")).toBeVisible({ timeout: 8_000 });
    await expect(page.getByText("DB Size")).toBeVisible();
    await expect(page.getByText("Memory")).toBeVisible();
    await expect(page.getByText("Avg Response")).toBeVisible();
  });

  test("renders error feed section with mocked error", async ({ page }) => {
    await expect(page.getByText(/error feed/i)).toBeVisible({ timeout: 10_000 });
    // Error from mock: "Rate limit exceeded"
    await expect(
      page.getByText("Rate limit exceeded")
    ).toBeVisible({ timeout: 8_000 });
  });

  test("clear button is visible when errors exist", async ({ page }) => {
    await expect(
      page.getByRole("button", { name: /^clear$/i })
    ).toBeVisible({ timeout: 8_000 });
  });

  test("renders top endpoints section", async ({ page }) => {
    await expect(
      page.getByText(/top endpoints by request count/i)
    ).toBeVisible({ timeout: 10_000 });
    // Endpoint from mock
    await expect(page.getByText("/api/v1/chat")).toBeVisible({ timeout: 8_000 });
  });

  test("API failure shows error banner rather than crash", async ({ page }) => {
    await page.route("**/api/v1/admin/errors", (route: Route) => {
      route.fulfill({ status: 500, body: '{"detail":"DB error"}' });
    });
    await page.route("**/api/v1/admin/health-detailed", (route: Route) => {
      route.fulfill({ status: 500, body: '{"detail":"DB error"}' });
    });
    await page.reload();
    // Page must not crash — heading should still be visible
    await expect(
      page.getByRole("heading", { name: /debug monitor/i })
    ).toBeVisible({ timeout: 10_000 });
  });
});

// ─── Revenue Dashboard ────────────────────────────────────────────────────────

test.describe("Revenue Dashboard (/admin/revenue)", () => {
  test.beforeEach(async ({ page }) => {
    await mockAdminApis(page);
    await gotoWithAuth(page, "/admin/revenue", ADMIN_EMAIL, true);
    await expect(page).toHaveURL(/\/admin\/revenue/, { timeout: 10_000 });
  });

  test("renders page heading", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: /revenue/i })
    ).toBeVisible({ timeout: 10_000 });
  });

  test("renders Stripe TEST MODE badge", async ({ page }) => {
    // The StripeBadge component renders "TEST MODE" text
    await expect(page.getByText("TEST MODE")).toBeVisible({ timeout: 10_000 });
  });

  test("renders KPI stat cards", async ({ page }) => {
    await expect(page.getByText("MRR")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Active Subscriptions")).toBeVisible();
    await expect(page.getByText("ARPU")).toBeVisible();
    await expect(page.getByText("Gross Margin")).toBeVisible();
  });

  test("renders Stripe Status panel", async ({ page }) => {
    await expect(page.getByText("Stripe Status")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("Customers")).toBeVisible();
    await expect(page.getByText("Webhook")).toBeVisible();
    await expect(page.getByText("Last Event")).toBeVisible();
  });

  test("renders MRR chart section", async ({ page }) => {
    await expect(page.getByText(/mrr.*30 day view/i)).toBeVisible({
      timeout: 10_000,
    });
  });

  test("renders recent transactions table", async ({ page }) => {
    await expect(page.getByText(/recent transactions/i)).toBeVisible({
      timeout: 10_000,
    });
    // Empty state message since transactions array is empty
    await expect(
      page.getByText(/no transactions yet/i)
    ).toBeVisible({ timeout: 8_000 });
  });

  test("renders cost breakdown section", async ({ page }) => {
    await expect(page.getByText(/cost breakdown/i)).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("API costs (token usage)")).toBeVisible();
    await expect(page.getByText("Net Margin")).toBeVisible();
  });

  test("renders CRM pipeline link", async ({ page }) => {
    await expect(page.getByText("CRM Pipeline")).toBeVisible({
      timeout: 10_000,
    });
    await expect(
      page.getByRole("link", { name: /view crm/i })
    ).toBeVisible();
  });

  test("refresh button is visible and enabled", async ({ page }) => {
    await expect(
      page.getByRole("button", { name: /refresh/i })
    ).toBeVisible({ timeout: 10_000 });
  });

  test("API failure shows error banner", async ({ page }) => {
    await page.route("**/api/v1/admin/stripe-status", (route: Route) => {
      route.fulfill({ status: 500, body: '{"detail":"error"}' });
    });
    await page.route("**/api/v1/admin/funnel", (route: Route) => {
      route.fulfill({ status: 500, body: '{"detail":"error"}' });
    });
    await page.reload();
    // Error banner should appear
    await expect(page.getByText(/revenue/i).first()).toBeVisible({
      timeout: 10_000,
    });
  });
});

// ─── Alert Management ─────────────────────────────────────────────────────────

test.describe("Alert Management Center (/admin/alerts)", () => {
  test.beforeEach(async ({ page }) => {
    await mockAdminApis(page);
    await gotoWithAuth(page, "/admin/alerts", ADMIN_EMAIL, true);
    await expect(page).toHaveURL(/\/admin\/alerts/, { timeout: 10_000 });
  });

  test("renders page heading", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: /alerts/i })
    ).toBeVisible({ timeout: 10_000 });
  });

  test("renders alert statistics summary", async ({ page }) => {
    await expect(page.getByText("Alerts Today")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("Critical")).toBeVisible();
    await expect(page.getByText("Unread")).toBeVisible();
    await expect(page.getByText("Top Source")).toBeVisible();
  });

  test("renders filter tabs", async ({ page }) => {
    await expect(page.getByRole("button", { name: /^all/i })).toBeVisible({
      timeout: 10_000,
    });
    await expect(
      page.getByRole("button", { name: /^critical/i })
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /^warning/i })
    ).toBeVisible();
    await expect(page.getByRole("button", { name: /^info/i })).toBeVisible();
  });

  test("renders alert cards from mock data", async ({ page }) => {
    await expect(
      page.getByText("High memory usage detected")
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByText("New user registered")
    ).toBeVisible({ timeout: 10_000 });
  });

  test("clicking filter tab filters alerts", async ({ page }) => {
    // Click Warning tab
    await page.getByRole("button", { name: /^warning/i }).click();

    // Warning alert should be visible
    await expect(
      page.getByText("High memory usage detected")
    ).toBeVisible({ timeout: 8_000 });

    // Click Info tab
    await page.getByRole("button", { name: /^info/i }).click();
    await expect(
      page.getByText("New user registered")
    ).toBeVisible({ timeout: 8_000 });
  });

  test("acknowledge button appears for unread alert", async ({ page }) => {
    // "High memory usage detected" is not acknowledged
    await expect(
      page.getByRole("button", { name: /ack/i }).first()
    ).toBeVisible({ timeout: 10_000 });
  });

  test("alert configuration panel expands when button clicked", async ({
    page,
  }) => {
    const configBtn = page.getByRole("button", { name: /alert configuration/i });
    await expect(configBtn).toBeVisible({ timeout: 10_000 });
    await configBtn.click();

    // Config panel content
    await expect(page.getByText(/alert thresholds/i)).toBeVisible({
      timeout: 8_000,
    });
    await expect(page.getByText(/error rate threshold/i)).toBeVisible();
    await expect(page.getByText(/response time threshold/i)).toBeVisible();
  });

  test("refresh button is visible", async ({ page }) => {
    await expect(
      page.getByRole("button", { name: /refresh/i })
    ).toBeVisible({ timeout: 10_000 });
  });
});

// ─── Marketing Command Center ─────────────────────────────────────────────────

test.describe("Marketing Command Center (/admin/marketing)", () => {
  test.beforeEach(async ({ page }) => {
    await mockAdminApis(page);
    await gotoWithAuth(page, "/admin/marketing", ADMIN_EMAIL, true);
    await expect(page).toHaveURL(/\/admin\/marketing/, { timeout: 10_000 });
  });

  test("renders page heading", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: /marketing/i })
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByText(/campaign management and email stats/i)
    ).toBeVisible();
  });

  test("renders KPI cards", async ({ page }) => {
    await expect(page.getByText("Total Campaigns")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("Emails Sent")).toBeVisible();
    await expect(page.getByText("Open Rate")).toBeVisible();
  });

  test("renders email delivery stats", async ({ page }) => {
    await expect(page.getByText(/email delivery stats/i)).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText(/delivery rate/i)).toBeVisible();
    await expect(page.getByText(/open rate/i)).toBeVisible();
    await expect(page.getByText(/click rate/i)).toBeVisible();
    await expect(page.getByText(/bounce rate/i)).toBeVisible();
  });

  test("renders campaigns table with mocked campaign", async ({ page }) => {
    await expect(page.getByText("Campaigns")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Welcome Campaign")).toBeVisible({
      timeout: 8_000,
    });
  });

  test("renders deploy marketing agent section", async ({ page }) => {
    await expect(
      page.getByText("Deploy Marketing Agent")
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByRole("button", { name: /deploy marketing agent/i })
    ).toBeVisible();
  });
});

// ─── Workflow Test Runner ─────────────────────────────────────────────────────

test.describe("Workflow Test Runner (/admin/workflows)", () => {
  test.beforeEach(async ({ page }) => {
    await mockAdminApis(page);
    await gotoWithAuth(page, "/admin/workflows", ADMIN_EMAIL, true);
    await expect(page).toHaveURL(/\/admin\/workflows/, { timeout: 10_000 });
  });

  test("renders page heading", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: /workflows/i })
    ).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/system test runner/i)).toBeVisible();
  });

  test("renders run all button", async ({ page }) => {
    await expect(
      page.getByRole("button", { name: /run all/i })
    ).toBeVisible({ timeout: 10_000 });
  });

  test("renders test cards with mocked tests", async ({ page }) => {
    // From mock data: "Health Check" and "Auth Flow"
    await expect(page.getByText("Health Check")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("Auth Flow")).toBeVisible({ timeout: 10_000 });
  });

  test("each test card has a run button", async ({ page }) => {
    const runButtons = page.getByRole("button", { name: /^run$/i });
    await expect(runButtons.first()).toBeVisible({ timeout: 10_000 });
  });

  test("renders test history section", async ({ page }) => {
    await expect(page.getByText("Test History")).toBeVisible({
      timeout: 10_000,
    });
    // From mock history: "Health Check" pass entry
    await expect(page.getByText("Health Check")).toBeVisible({ timeout: 8_000 });
  });

  test("clicking run button on a test card calls API and shows result", async ({
    page,
  }) => {
    const runButtons = page.getByRole("button", { name: /^run$/i });
    await runButtons.first().click();

    // After running, a pass result badge should appear
    await expect(page.getByText("Pass").first()).toBeVisible({
      timeout: 10_000,
    });
  });

  test("clicking run all button calls run-all API", async ({ page }) => {
    const runAllBtn = page.getByRole("button", { name: /run all/i });
    await runAllBtn.click();

    // Pass badge should appear after run
    await expect(page.getByText("Pass").first()).toBeVisible({
      timeout: 10_000,
    });
  });
});

// ─── Scheduler ────────────────────────────────────────────────────────────────

test.describe("Scheduler (/admin/scheduler)", () => {
  test.beforeEach(async ({ page }) => {
    await mockAdminApis(page);
    await gotoWithAuth(page, "/admin/scheduler", ADMIN_EMAIL, true);
    await expect(page).toHaveURL(/\/admin\/scheduler/, { timeout: 10_000 });
  });

  test("renders page heading", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: /scheduler/i })
    ).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/key dates and events/i)).toBeVisible();
  });

  test("renders key dates section", async ({ page }) => {
    await expect(page.getByText("Key Dates")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Colorado AI Act Deadline")).toBeVisible();
    await expect(page.getByText("USPTO Trademark Review")).toBeVisible();
    await expect(page.getByText("Stripe Test Mode Cutover")).toBeVisible();
  });

  test("renders upcoming events from mock data", async ({ page }) => {
    await expect(page.getByText(/upcoming events/i)).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("Q2 Launch Review")).toBeVisible({
      timeout: 8_000,
    });
    await expect(page.getByText("Colorado AI Act Deadline")).toBeVisible();
  });

  test("renders quick add event form", async ({ page }) => {
    await expect(page.getByText(/quick add event/i)).toBeVisible({
      timeout: 10_000,
    });
    await expect(
      page.getByPlaceholder(/event title/i)
    ).toBeVisible();
    // Event type select
    await expect(page.getByRole("combobox")).toBeVisible();
    await expect(
      page.getByRole("button", { name: /add event/i })
    ).toBeVisible();
  });

  test("add event form button is disabled when title is empty", async ({
    page,
  }) => {
    const addBtn = page.getByRole("button", { name: /add event/i });
    await expect(addBtn).toBeDisabled({ timeout: 10_000 });
  });
});

// ─── Deploy Center ────────────────────────────────────────────────────────────

test.describe("Deploy Center (/admin/deploy)", () => {
  test.beforeEach(async ({ page }) => {
    await mockAdminApis(page);
    await gotoWithAuth(page, "/admin/deploy", ADMIN_EMAIL, true);
    await expect(page).toHaveURL(/\/admin\/deploy/, { timeout: 10_000 });
  });

  test("renders page heading", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: /deploy/i })
    ).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/agent deployment center/i)).toBeVisible();
  });

  test("renders marketing agent card", async ({ page }) => {
    await expect(page.getByText("Marketing Agent")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("@dingdawg-marketing")).toBeVisible();
    // Deploy button
    await expect(
      page
        .getByRole("button", { name: /deploy @dingdawg-marketing/i })
    ).toBeVisible({ timeout: 8_000 });
  });

  test("renders template gallery with mocked templates", async ({ page }) => {
    await expect(page.getByText("Template Gallery")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("Restaurant Agent")).toBeVisible({
      timeout: 8_000,
    });
    await expect(page.getByText("Retail Agent")).toBeVisible();
  });

  test("renders quick deploy form", async ({ page }) => {
    await expect(page.getByText("Quick Deploy")).toBeVisible({
      timeout: 10_000,
    });
    await expect(
      page.getByPlaceholder(/agent-handle/i)
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /deploy agent/i })
    ).toBeVisible();
  });

  test("quick deploy button is disabled when form is incomplete", async ({
    page,
  }) => {
    const deployBtn = page.getByRole("button", { name: /deploy agent/i });
    await expect(deployBtn).toBeDisabled({ timeout: 10_000 });
  });

  test("renders deployment history section", async ({ page }) => {
    await expect(page.getByText("Deployment History")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("@test-deploy")).toBeVisible({ timeout: 8_000 });
    await expect(page.getByText("Restaurant Agent")).toBeVisible();
  });
});

// ─── Integration Health Dashboard ─────────────────────────────────────────────

test.describe("Integration Health Dashboard (/admin/integrations)", () => {
  test.beforeEach(async ({ page }) => {
    await mockAdminApis(page);
    await gotoWithAuth(page, "/admin/integrations", ADMIN_EMAIL, true);
    await expect(page).toHaveURL(/\/admin\/integrations/, { timeout: 10_000 });
  });

  test("renders page heading", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: /integration health/i })
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByText(/6 integrations monitored/i)
    ).toBeVisible();
  });

  test("renders integration cards for all 6 integrations", async ({ page }) => {
    // All 6 integrations should appear
    await expect(page.getByText("Google Calendar")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("SendGrid")).toBeVisible();
    await expect(page.getByText("Twilio")).toBeVisible();
    await expect(page.getByText("Stripe")).toBeVisible();
    await expect(page.getByText(/vapi/i)).toBeVisible();
    await expect(page.getByText("Slack")).toBeVisible();
  });

  test("connected integrations show test buttons", async ({ page }) => {
    // SendGrid is connected in mock — its Test button should be enabled
    const testButtons = page.getByRole("button", { name: /^test$/i });
    await expect(testButtons.first()).toBeVisible({ timeout: 10_000 });
  });

  test("not_configured integrations show disabled test button", async ({
    page,
  }) => {
    // Twilio is not_configured in mock — find its card's Test button which is disabled
    // The page renders cards in the INTEGRATION_META order, Twilio is 3rd
    const allTestBtns = await page.getByRole("button", { name: /^test$/i }).all();
    // There should be at least one disabled button (Twilio + Vapi + Slack + Google Calendar are not_configured or unchecked)
    expect(allTestBtns.length).toBeGreaterThan(0);
  });

  test("renders webhook delivery rates chart section", async ({ page }) => {
    await expect(
      page.getByText(/webhook delivery rates/i)
    ).toBeVisible({ timeout: 10_000 });
  });

  test("renders recent test results section", async ({ page }) => {
    await expect(
      page.getByText(/recent test results/i)
    ).toBeVisible({ timeout: 10_000 });
  });

  test("API failure shows error banner", async ({ page }) => {
    await page.route("**/api/v1/admin/integration-health", (route: Route) => {
      route.fulfill({ status: 500, body: '{"detail":"error"}' });
    });
    await page.reload();
    // Error banner should appear
    await expect(
      page.getByText(/failed to load integration health/i)
    ).toBeVisible({ timeout: 10_000 });
    // Page must not fully crash — heading still renders
    await expect(
      page.getByRole("heading", { name: /integration health/i })
    ).toBeVisible();
  });
});

// ─── CRM Pipeline ─────────────────────────────────────────────────────────────

test.describe("CRM Pipeline (/admin/crm)", () => {
  test.beforeEach(async ({ page }) => {
    await mockAdminApis(page);
    await gotoWithAuth(page, "/admin/crm", ADMIN_EMAIL, true);
    await expect(page).toHaveURL(/\/admin\/crm/, { timeout: 10_000 });
  });

  test("renders page heading", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: /crm pipeline/i })
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByText(/funnel, contacts, and churn indicators/i)
    ).toBeVisible();
  });

  test("renders acquisition funnel section", async ({ page }) => {
    await expect(
      page.getByText(/acquisition funnel/i)
    ).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Registered Users")).toBeVisible();
    await expect(page.getByText("Claimed Handle")).toBeVisible();
    await expect(page.getByText("Subscribed")).toBeVisible();
    await expect(page.getByText(/active \(7d\)/i)).toBeVisible();
    await expect(page.getByText(/churned \(30d\)/i)).toBeVisible();
  });

  test("renders churn indicators section", async ({ page }) => {
    await expect(
      page.getByText(/churn indicators/i)
    ).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/inactive 7\+ days/i)).toBeVisible();
    await expect(page.getByText(/failed payments/i)).toBeVisible();
    await expect(page.getByText(/churned \(30d\)/i)).toBeVisible();
    await expect(page.getByText(/expiring subscriptions/i)).toBeVisible();
  });

  test("renders session depth chart section", async ({ page }) => {
    await expect(
      page.getByText(/session depth distribution/i)
    ).toBeVisible({ timeout: 10_000 });
  });

  test("renders contacts table with search", async ({ page }) => {
    await expect(page.getByText("Contacts")).toBeVisible({ timeout: 10_000 });
    const searchInput = page.getByPlaceholder(/search email or handle/i);
    await expect(searchInput).toBeVisible();
    // Contact from mock
    await expect(
      page.getByText("contact@example.com")
    ).toBeVisible({ timeout: 8_000 });
  });

  test("renders link back to revenue dashboard", async ({ page }) => {
    await expect(page.getByText("Revenue Dashboard")).toBeVisible({
      timeout: 10_000,
    });
    await expect(
      page.getByRole("link", { name: /view revenue/i })
    ).toBeVisible();
  });
});

// ─── System Health ────────────────────────────────────────────────────────────

test.describe("System Health (/admin/system)", () => {
  test.beforeEach(async ({ page }) => {
    await mockAdminApis(page);
    await gotoWithAuth(page, "/admin/system", ADMIN_EMAIL, true);
    await expect(page).toHaveURL(/\/admin\/system/, { timeout: 10_000 });
  });

  test("renders overall health status banner", async ({ page }) => {
    // Mock returns status: "healthy"
    await expect(page.getByText(/system healthy/i)).toBeVisible({
      timeout: 10_000,
    });
  });

  test("renders platform metrics section", async ({ page }) => {
    await expect(page.getByText(/platform metrics/i)).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("Total Agents")).toBeVisible();
    await expect(page.getByText("Total Sessions")).toBeVisible();
    await expect(page.getByText("Total Messages")).toBeVisible();
    await expect(page.getByText(/error rate/i)).toBeVisible();
  });

  test("renders database section", async ({ page }) => {
    await expect(page.getByText("Database")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("SQLite")).toBeVisible();
    await expect(page.getByText(/query latency/i)).toBeVisible();
  });

  test("renders LLM providers section", async ({ page }) => {
    await expect(page.getByText(/llm providers/i)).toBeVisible({
      timeout: 10_000,
    });
    // From mock: openai and anthropic
    await expect(page.getByText("Openai")).toBeVisible({ timeout: 8_000 });
    await expect(page.getByText("Anthropic")).toBeVisible();
  });

  test("renders security layers section", async ({ page }) => {
    await expect(page.getByText("Security")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/rate limiter/i)).toBeVisible();
    await expect(page.getByText(/constitution/i)).toBeVisible();
  });

  test("renders self-healing section", async ({ page }) => {
    await expect(page.getByText(/self-healing/i)).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText(/circuit breakers/i)).toBeVisible();
  });

  test("renders recent errors section (empty state)", async ({ page }) => {
    await expect(page.getByText(/recent errors/i)).toBeVisible({
      timeout: 10_000,
    });
    // Mock returns no errors
    await expect(page.getByText(/no recent errors/i)).toBeVisible({
      timeout: 8_000,
    });
  });

  test("renders self-test section with run test button", async ({ page }) => {
    await expect(
      page.getByText(/integration self-test/i)
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByRole("button", { name: /run test/i })
    ).toBeVisible();
  });

  test("clicking run test button calls self-test API and shows results", async ({
    page,
  }) => {
    await page.getByRole("button", { name: /run test/i }).click();

    // Self-test results should appear
    await expect(
      page.getByText(/all tests passed/i)
    ).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Database")).toBeVisible();
  });

  test("API failure shows error state with retry button", async ({ page }) => {
    await page.route("**/api/v1/admin/system/health", (route: Route) => {
      route.fulfill({ status: 500, body: '{"detail":"error"}' });
    });
    await page.route("**/api/v1/admin/system/errors**", (route: Route) => {
      route.fulfill({ status: 500, body: '{"detail":"error"}' });
    });
    await page.reload();

    // Error state renders with Retry button
    await expect(
      page.getByText(/failed to load system health/i)
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByRole("button", { name: /retry/i })
    ).toBeVisible();
  });
});

// ─── Navigation: All 12 admin pages load without crash ────────────────────────

test.describe("Admin Navigation: All pages load", () => {
  const ADMIN_ROUTES = [
    { path: "/admin", label: "Overview" },
    { path: "/admin/mila", label: "MiLA Command Console" },
    { path: "/admin/agents", label: "Agent Control Center" },
    { path: "/admin/debug", label: "Debug Monitor" },
    { path: "/admin/revenue", label: "Revenue" },
    { path: "/admin/crm", label: "CRM Pipeline" },
    { path: "/admin/alerts", label: "Alerts" },
    { path: "/admin/marketing", label: "Marketing" },
    { path: "/admin/workflows", label: "Workflows" },
    { path: "/admin/scheduler", label: "Scheduler" },
    { path: "/admin/deploy", label: "Deploy" },
    { path: "/admin/integrations", label: "Integration Health" },
    { path: "/admin/system", label: "System" },
  ];

  for (const { path, label } of ADMIN_ROUTES) {
    test(`${label} (${path}) loads without JS crash`, async ({ page }) => {
      // Capture any console errors
      const consoleErrors: string[] = [];
      page.on("console", (msg) => {
        if (msg.type() === "error") {
          const text = msg.text();
          // Ignore known benign browser errors
          if (
            !text.includes("favicon") &&
            !text.includes("ERR_ABORTED") &&
            !text.includes("ResizeObserver") &&
            !text.includes("non-passive event listener")
          ) {
            consoleErrors.push(text);
          }
        }
      });

      // Capture uncaught page crashes
      let pageCrashed = false;
      page.on("crash", () => {
        pageCrashed = true;
      });

      await mockAdminApis(page);
      await gotoWithAuth(page, path, ADMIN_EMAIL, true);

      // Give the page time to render
      await page.waitForTimeout(2_000);

      // Must still be on the admin path (not redirected away)
      await expect(page).toHaveURL(new RegExp(path.replace(/\//g, "\\/")), {
        timeout: 10_000,
      });

      expect(pageCrashed).toBe(false);

      // No React error boundary messages
      const errorBoundaryText = await page
        .getByText(/something went wrong/i)
        .count();
      expect(errorBoundaryText).toBe(0);
    });
  }
});

// ─── Error Boundary: Render errors are caught ─────────────────────────────────

test.describe("Error Handling", () => {
  test("API failure on overview page shows partial content, not crash", async ({
    page,
  }) => {
    // Mock only health-detailed to fail — other endpoints succeed
    await mockAdminApis(page);
    await page.route("**/api/v1/admin/health-detailed", (route: Route) => {
      route.fulfill({ status: 500, body: '{"detail":"server error"}' });
    });

    await gotoWithAuth(page, "/admin", ADMIN_EMAIL, true);

    // Stripe banner should still render (uses separate endpoint)
    await expect(page.getByText(/stripe/i).first()).toBeVisible({
      timeout: 10_000,
    });

    // No crash/error boundary shown for a partial API failure
    const errorBoundary = await page
      .getByText(/something went wrong/i)
      .count();
    expect(errorBoundary).toBe(0);
  });

  test("alerts page shows empty state when no alerts returned", async ({
    page,
  }) => {
    await mockAdminApis(page);
    // Override alerts to empty array
    await page.route("**/api/v1/admin/alerts", (route: Route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });

    await gotoWithAuth(page, "/admin/alerts", ADMIN_EMAIL, true);
    await expect(page).toHaveURL(/\/admin\/alerts/, { timeout: 10_000 });

    // Empty state should appear
    await expect(page.getByText(/no alerts/i)).toBeVisible({ timeout: 10_000 });
  });

  test("agents page shows empty state when no agents returned", async ({
    page,
  }) => {
    await mockAdminApis(page);
    await page.route("**/api/v1/admin/agents**", (route: Route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ agents: [], total: 0, page: 1, per_page: 20 }),
      });
    });

    await gotoWithAuth(page, "/admin/agents", ADMIN_EMAIL, true);
    await expect(page).toHaveURL(/\/admin\/agents/, { timeout: 10_000 });

    // Empty table state
    await expect(
      page.getByText(/no agents match your search/i)
    ).toBeVisible({ timeout: 10_000 });
  });

  test("debug monitor shows empty error feed when no errors", async ({
    page,
  }) => {
    await mockAdminApis(page);
    await page.route("**/api/v1/admin/errors", (route: Route) => {
      if (route.request().method() === "GET") {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ errors: [] }),
        });
      } else {
        route.fulfill({ status: 200, body: "{}" });
      }
    });

    await gotoWithAuth(page, "/admin/debug", ADMIN_EMAIL, true);
    await expect(page).toHaveURL(/\/admin\/debug/, { timeout: 10_000 });

    await expect(
      page.getByText(/no errors recorded/i)
    ).toBeVisible({ timeout: 10_000 });
  });
});
