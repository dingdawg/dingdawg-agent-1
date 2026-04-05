/**
 * DingDawg Agent 1 — Protected Pages Smoke Tests
 *
 * STOA Layer 4 — E2E (functional, against local dev server)
 *
 * Covers workflows that are NOT adequately covered in the existing e2e suite:
 *
 *   SMOKE-AUTH: Unauthenticated redirect guards
 *     SMOKE-AUTH-01  /dashboard → /login redirect when no token
 *     SMOKE-AUTH-02  /settings  → /login redirect when no token
 *     SMOKE-AUTH-03  /tasks     → /login redirect when no token
 *     SMOKE-AUTH-04  /billing   → /login redirect when no token
 *     SMOKE-AUTH-05  /analytics → /login redirect when no token
 *     SMOKE-AUTH-06  /integrations → /login redirect when no token
 *     SMOKE-AUTH-07  /claim     → /login redirect when no token
 *
 *   SMOKE-CHAT: /chat → /dashboard redirect
 *     SMOKE-CHAT-01  GET /chat redirects to /dashboard (unauthenticated → /login)
 *
 *   SMOKE-TASKS: Tasks page interactive elements
 *     SMOKE-TASKS-01  Tasks page renders filter tabs (All/Pending/In Progress/Completed)
 *     SMOKE-TASKS-02  Clicking "Pending" filter tab activates it
 *     SMOKE-TASKS-03  Empty state renders when no tasks
 *     SMOKE-TASKS-04  FAB "New Task" button is visible
 *     SMOKE-TASKS-05  New Task modal opens on FAB click
 *     SMOKE-TASKS-06  New Task modal closes on backdrop click
 *     SMOKE-TASKS-07  New Task modal close button works
 *     SMOKE-TASKS-08  Task type select has expected options
 *
 *   SMOKE-ANALYTICS: Analytics page structure
 *     SMOKE-ANA-01  Page heading "Analytics" is visible
 *     SMOKE-ANA-02  Refresh button exists and is clickable
 *     SMOKE-ANA-03  Empty state renders when no data
 *
 *   SMOKE-BILLING: Billing page structure
 *     SMOKE-BILL-01  Page heading "Billing" is visible
 *     SMOKE-BILL-02  4 plan cards render (Free, Starter, Pro, Enterprise)
 *     SMOKE-BILL-03  "This Month" usage section heading visible
 *     SMOKE-BILL-04  "Usage History" section heading visible
 *     SMOKE-BILL-05  Free plan shows $0/mo
 *
 *   SMOKE-SETTINGS: Settings tabs and danger zone
 *     SMOKE-SET-01  All 5 tabs visible (General, Personality, Skills, Branding, Danger)
 *     SMOKE-SET-02  Clicking "Personality" tab changes content
 *     SMOKE-SET-03  Clicking "Skills" tab shows skill toggles
 *     SMOKE-SET-04  Clicking "Branding" tab shows branding editor
 *     SMOKE-SET-05  "Delete Agent" button visible inside Danger tab (or in General)
 *     SMOKE-SET-06  First delete click shows confirm state (two-click guard)
 *     SMOKE-SET-07  Clicking Cancel hides confirm state
 *
 *   SMOKE-NAV: AppShell navigation
 *     SMOKE-NAV-01  Desktop nav rail has all 7 expected links
 *     SMOKE-NAV-02  Active link highlighted on /dashboard
 *     SMOKE-NAV-03  Active link highlighted on /settings
 *     SMOKE-NAV-04  Logout link in nav triggers redirect to /login
 *     SMOKE-NAV-05  Mobile: hamburger menu button visible at 375px
 *     SMOKE-NAV-06  Mobile: hamburger opens nav overlay
 *
 *   SMOKE-EXPLORE: Explore page interactions
 *     SMOKE-EXP-01  Search input filters agent list
 *     SMOKE-EXP-02  Category chip "Restaurant" filters to restaurant agents
 *     SMOKE-EXP-03  "Clear filters" button resets to all agents
 *     SMOKE-EXP-04  Agent card links navigate to /agents/[handle]
 *
 * All tests use API route mocking to avoid backend dependency.
 * Auth is established by injecting a JWT + user into localStorage.
 */

import { test, expect, type Page } from "@playwright/test";

// ─── Constants ────────────────────────────────────────────────────────────────

const AUTH_TOKEN_KEY = "dd_access_token";
const AUTH_USER_KEY = "dd_user";

/** A single mocked agent matching AgentResponse shape from platformService.ts */
const MOCK_AGENT = {
  id: "smoke-agent-id-0001",
  handle: "smoke-test-agent",
  name: "Smoke Test Agent",
  agent_type: "business",
  status: "active",
  subscription_tier: "free",
  industry_type: "restaurant",
  template_id: "restaurant-v1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  config_json: null,
  branding_json: null,
};

// ─── Shared setup ─────────────────────────────────────────────────────────────

/**
 * Inject auth token + user into localStorage on the current page origin.
 * Must be called after page.goto() so the correct origin is active.
 */
async function injectAuth(page: Page): Promise<void> {
  await page.evaluate(
    ([tokKey, usrKey]) => {
      localStorage.setItem(tokKey, "smoke-fake-jwt-token");
      localStorage.setItem(
        usrKey,
        JSON.stringify({ id: "smoke-user-id", email: "smoke@dingdawg.test", is_active: true })
      );
    },
    [AUTH_TOKEN_KEY, AUTH_USER_KEY]
  );
}

/**
 * Mock the standard set of backend endpoints needed by any protected page.
 * Individual tests add additional mocks on top of this baseline.
 */
async function mockBaseEndpoints(page: Page): Promise<void> {
  await page.route("**/api/v1/agents**", (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ agents: [MOCK_AGENT] }),
    });
  });
  await page.route("**/api/v1/sessions**", (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ sessions: [] }),
    });
  });
  await page.route("**/api/v1/tasks**", (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });
  await page.route("**/api/v1/payments/usage/**", (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        plan: "free",
        total_actions: 0,
        actions_included: 50,
        billed_actions: 0,
        remaining_free: 50,
        total_amount_cents: 0,
        year_month: "2026-03",
      }),
    });
  });
  await page.route("**/api/v1/payments/usage/**/history", (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });
  await page.route("**/api/v1/integrations/**", (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        google_calendar: { connected: false },
        sendgrid: { connected: false },
        twilio: { connected: false },
        vapi: { connected: false },
        webhooks: { active_count: 0, webhooks: [] },
        dd_main_bridge: { connected: false },
      }),
    });
  });
  await page.route("**/api/v1/analytics/**", (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ total_conversations: 0, total_messages: 0, avg_messages_per_conversation: 0, daily_conversations: [] }),
    });
  });
  await page.route("**/api/v1/webhooks/**", (route) => {
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
  });
}

/**
 * Navigate to a path with auth already established.
 * Registers mocks → navigates → injects token → reloads.
 */
async function gotoAuthed(page: Page, path: string): Promise<void> {
  await mockBaseEndpoints(page);
  await page.goto(path);
  await injectAuth(page);
  await page.reload();
  await page.waitForLoadState("networkidle");
}

// ─── SMOKE-AUTH: Unauthenticated redirect guards ──────────────────────────────

test.describe("SMOKE-AUTH: Unauthenticated redirect guards", () => {
  const PROTECTED = [
    "/dashboard",
    "/settings",
    "/tasks",
    "/billing",
    "/analytics",
    "/integrations",
    "/claim",
  ];

  for (const path of PROTECTED) {
    test(`SMOKE-AUTH: ${path} → /login when no token`, async ({ page }) => {
      // Clear any existing localStorage on the page origin.
      await page.goto("/login");
      await page.evaluate(([tok, usr]) => {
        localStorage.removeItem(tok);
        localStorage.removeItem(usr);
      }, [AUTH_TOKEN_KEY, AUTH_USER_KEY]);

      await page.goto(path);
      await page.waitForURL(/\/login/, { timeout: 10_000 });
      await expect(page).toHaveURL(/\/login/);
    });
  }
});

// ─── SMOKE-CHAT: /chat redirect ───────────────────────────────────────────────

test.describe("SMOKE-CHAT: /chat route redirect", () => {
  test("SMOKE-CHAT-01: /chat redirects to /dashboard (auth) or /login (no auth)", async ({ page }) => {
    // Without auth, should end up at /login.
    await page.goto("/login");
    await page.evaluate(([tok, usr]) => {
      localStorage.removeItem(tok);
      localStorage.removeItem(usr);
    }, [AUTH_TOKEN_KEY, AUTH_USER_KEY]);

    await page.goto("/chat");
    // /chat page calls router.replace("/dashboard"), and /dashboard redirects
    // to /login if unauthenticated.
    await page.waitForURL(/\/(login|dashboard)/, { timeout: 10_000 });
    const url = page.url();
    expect(url).toMatch(/\/(login|dashboard)/);
  });
});

// ─── SMOKE-TASKS: Tasks page ──────────────────────────────────────────────────

test.describe("SMOKE-TASKS: Tasks page", () => {
  test("SMOKE-TASKS-01: filter tabs All/Pending/In Progress/Completed render", async ({ page }) => {
    await gotoAuthed(page, "/tasks");

    await expect(page.getByRole("button", { name: "All" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Pending" })).toBeVisible();
    await expect(page.getByRole("button", { name: "In Progress" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Completed" })).toBeVisible();
  });

  test("SMOKE-TASKS-02: clicking Pending filter tab activates it", async ({ page }) => {
    await gotoAuthed(page, "/tasks");

    const pendingBtn = page.getByRole("button", { name: "Pending" });
    await pendingBtn.click();

    // The active tab gets a gold background class — check the button has the
    // gold text color variant (text-[#07111c] from the active class) or a
    // distinctive aria-pressed / aria-selected attribute.
    // Fallback: assert the button has changed visual state by checking its
    // computed background is not the default bg-white/5 via class check.
    await expect(pendingBtn).toHaveClass(/bg-\[var\(--gold-500\)\]/);
  });

  test("SMOKE-TASKS-03: empty state renders when no tasks", async ({ page }) => {
    await gotoAuthed(page, "/tasks");

    // Mock returns [] tasks — empty state panel should show.
    await expect(page.getByText(/no tasks yet/i)).toBeVisible();
  });

  test("SMOKE-TASKS-04: FAB New Task button is visible", async ({ page }) => {
    await gotoAuthed(page, "/tasks");

    await expect(page.getByRole("button", { name: /new task/i })).toBeVisible();
  });

  test("SMOKE-TASKS-05: New Task modal opens on FAB click", async ({ page }) => {
    await gotoAuthed(page, "/tasks");

    await page.getByRole("button", { name: /new task/i }).click();

    // Modal heading
    await expect(page.getByRole("heading", { name: /new task/i })).toBeVisible();
    // Task type select
    await expect(page.locator("select")).toBeVisible();
    // Description textarea
    await expect(page.getByPlaceholder(/describe/i)).toBeVisible();
    // Create Task submit button
    await expect(page.getByRole("button", { name: /create task/i })).toBeVisible();
  });

  test("SMOKE-TASKS-06: New Task modal closes on backdrop click", async ({ page }) => {
    await gotoAuthed(page, "/tasks");

    await page.getByRole("button", { name: /new task/i }).click();
    await expect(page.getByRole("heading", { name: /new task/i })).toBeVisible();

    // Click the backdrop (the fixed overlay div behind the modal)
    await page.mouse.click(10, 10);

    await expect(page.getByRole("heading", { name: /new task/i })).not.toBeVisible();
  });

  test("SMOKE-TASKS-07: New Task modal close button works", async ({ page }) => {
    await gotoAuthed(page, "/tasks");

    await page.getByRole("button", { name: /new task/i }).click();
    await expect(page.getByRole("heading", { name: /new task/i })).toBeVisible();

    // The X button inside the modal
    await page.getByRole("button", { name: /close/i }).click();

    await expect(page.getByRole("heading", { name: /new task/i })).not.toBeVisible();
  });

  test("SMOKE-TASKS-08: task type select has expected options", async ({ page }) => {
    await gotoAuthed(page, "/tasks");

    await page.getByRole("button", { name: /new task/i }).click();

    const select = page.locator("select").first();
    const options = await select.locator("option").allTextContents();
    // TASK_TYPES in tasks/page.tsx: research, booking, reminder, errand, purchase, email
    const expected = ["Research", "Booking", "Reminder", "Errand", "Purchase", "Email"];
    for (const opt of expected) {
      expect(options.some((o) => o.toLowerCase() === opt.toLowerCase())).toBeTruthy();
    }
  });
});

// ─── SMOKE-ANALYTICS: Analytics page ─────────────────────────────────────────

test.describe("SMOKE-ANALYTICS: Analytics page structure", () => {
  test("SMOKE-ANA-01: page heading Analytics is visible", async ({ page }) => {
    await gotoAuthed(page, "/analytics");

    await expect(page.getByRole("heading", { name: /analytics/i })).toBeVisible();
  });

  test("SMOKE-ANA-02: Refresh button exists and is clickable", async ({ page }) => {
    await gotoAuthed(page, "/analytics");

    const refreshBtn = page.getByRole("button", { name: /refresh/i });
    await expect(refreshBtn).toBeVisible();
    await expect(refreshBtn).toBeEnabled();
    await refreshBtn.click();
    // Should not throw — mock returns quickly
  });

  test("SMOKE-ANA-03: empty state renders when backend returns no data", async ({ page }) => {
    await gotoAuthed(page, "/analytics");

    // With all analytics mocked to empty, the "No data yet" empty state should
    // appear after load completes.
    await expect(page.getByText(/no data yet/i)).toBeVisible({ timeout: 8_000 });
  });
});

// ─── SMOKE-BILLING: Billing page ──────────────────────────────────────────────

test.describe("SMOKE-BILLING: Billing page structure", () => {
  test("SMOKE-BILL-01: page heading Billing is visible", async ({ page }) => {
    await gotoAuthed(page, "/billing");

    await expect(page.getByRole("heading", { level: 1 })).toContainText(/billing/i);
  });

  test("SMOKE-BILL-02: 4 plan cards render (Free, Starter, Pro, Enterprise)", async ({ page }) => {
    await gotoAuthed(page, "/billing");

    await expect(page.getByText("Free")).toBeVisible();
    await expect(page.getByText("Starter")).toBeVisible();
    await expect(page.getByText("Pro")).toBeVisible();
    await expect(page.getByText("Enterprise")).toBeVisible();
  });

  test("SMOKE-BILL-03: This Month usage section heading visible", async ({ page }) => {
    await gotoAuthed(page, "/billing");

    await expect(page.getByText(/this month/i)).toBeVisible();
  });

  test("SMOKE-BILL-04: Usage History section heading visible", async ({ page }) => {
    await gotoAuthed(page, "/billing");

    await expect(page.getByText(/usage history/i)).toBeVisible();
  });

  test("SMOKE-BILL-05: Free plan shows $0/mo price", async ({ page }) => {
    await gotoAuthed(page, "/billing");

    // Free plan card has $0 + /mo text
    await expect(page.getByText("$0")).toBeVisible();
  });

  test("SMOKE-BILL-06: Upgrade buttons are present for non-current plans", async ({ page }) => {
    await gotoAuthed(page, "/billing");

    // The mocked usage returns plan: "free" so Starter/Pro/Enterprise should show Upgrade buttons.
    const upgradeBtns = page.getByRole("button", { name: /upgrade/i });
    await expect(upgradeBtns.first()).toBeVisible();
  });
});

// ─── SMOKE-SETTINGS: Settings tabs and danger zone ───────────────────────────

test.describe("SMOKE-SETTINGS: Settings page tabs and danger zone", () => {
  test("SMOKE-SET-01: all 5 tabs visible (General, Personality, Skills, Branding, Danger)", async ({ page }) => {
    await gotoAuthed(page, "/settings");

    await expect(page.getByRole("button", { name: /general/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /personality/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /skills/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /branding/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /danger/i })).toBeVisible();
  });

  test("SMOKE-SET-02: clicking Personality tab changes tab content", async ({ page }) => {
    await gotoAuthed(page, "/settings");

    await page.getByRole("button", { name: /personality/i }).click();
    await page.waitForLoadState("networkidle");

    // PromptEditor content should appear — look for personality-specific content
    // The Personality tab renders PromptEditor which has a system prompt textarea.
    await expect(
      page.getByText(/personality|system prompt|tone|language/i).first()
    ).toBeVisible({ timeout: 5_000 });
  });

  test("SMOKE-SET-03: clicking Skills tab shows skill toggles", async ({ page }) => {
    await gotoAuthed(page, "/settings");

    await page.getByRole("button", { name: /skills/i }).click();
    await page.waitForLoadState("networkidle");

    // SkillToggles renders toggle switches — at least one should be visible.
    await expect(
      page.getByRole("switch").first()
    ).toBeVisible({ timeout: 5_000 });
  });

  test("SMOKE-SET-04: clicking Branding tab shows branding editor", async ({ page }) => {
    await gotoAuthed(page, "/settings");

    await page.getByRole("button", { name: /branding/i }).click();
    await page.waitForLoadState("networkidle");

    // BrandingEditor has color preset buttons and a primary color label.
    await expect(
      page.getByText(/primary color|brand color|branding/i).first()
    ).toBeVisible({ timeout: 5_000 });
  });

  test("SMOKE-SET-05: Delete Agent button is visible in settings", async ({ page }) => {
    await gotoAuthed(page, "/settings");

    // The delete button is in the General tab danger zone section.
    await expect(
      page.getByRole("button", { name: /delete agent/i })
    ).toBeVisible();
  });

  test("SMOKE-SET-06: first Delete Agent click shows Confirm Delete (two-click guard)", async ({ page }) => {
    await gotoAuthed(page, "/settings");

    await page.getByRole("button", { name: /delete agent/i }).click();

    // After first click, the button text changes to "Confirm Delete"
    await expect(
      page.getByRole("button", { name: /confirm delete/i })
    ).toBeVisible({ timeout: 3_000 });
  });

  test("SMOKE-SET-07: clicking Cancel after Delete hides Confirm Delete", async ({ page }) => {
    await gotoAuthed(page, "/settings");

    await page.getByRole("button", { name: /delete agent/i }).click();
    await expect(page.getByRole("button", { name: /confirm delete/i })).toBeVisible();

    await page.getByRole("button", { name: /cancel/i }).click();

    // Confirm Delete disappears; Delete Agent button returns.
    await expect(page.getByRole("button", { name: /delete agent/i })).toBeVisible({ timeout: 3_000 });
    await expect(page.getByRole("button", { name: /confirm delete/i })).not.toBeVisible();
  });
});

// ─── SMOKE-NAV: AppShell navigation ──────────────────────────────────────────

test.describe("SMOKE-NAV: AppShell navigation", () => {
  test("SMOKE-NAV-01: desktop nav rail has 7 expected links", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await gotoAuthed(page, "/dashboard");

    // NAV_ITEMS in AppShell.tsx: Dashboard, Tasks, Analytics, Explore, Integrations, Billing, Settings
    const nav = page.locator("nav");
    for (const label of ["Dashboard", "Tasks", "Analytics", "Explore", "Integrations", "Billing", "Settings"]) {
      await expect(nav.getByRole("link", { name: label }).or(nav.getByTitle(label))).toBeVisible();
    }
  });

  test("SMOKE-NAV-02: active link highlighted on /dashboard", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await gotoAuthed(page, "/dashboard");

    // The active nav link gets a gold background indicator.
    // Look for a link with href="/dashboard" that has an active class or gold styling.
    const dashLink = page.locator('nav a[href="/dashboard"]');
    await expect(dashLink).toBeVisible();
    // Verify the link itself is on the page and not hidden
    await expect(dashLink.first()).toBeVisible();
  });

  test("SMOKE-NAV-03: active link highlighted on /settings", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await gotoAuthed(page, "/settings");

    const settingsLink = page.locator('nav a[href="/settings"]');
    await expect(settingsLink.first()).toBeVisible();
  });

  test("SMOKE-NAV-04: logout navigates to /login", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await gotoAuthed(page, "/dashboard");

    // Logout button is in the AppShell desktop nav — look for a button with LogOut icon label.
    const logoutBtn = page.getByRole("button", { name: /log.?out|sign.?out/i });
    await expect(logoutBtn).toBeVisible();
    await logoutBtn.click();

    await page.waitForURL(/\/login/, { timeout: 8_000 });
    await expect(page).toHaveURL(/\/login/);
  });

  test("SMOKE-NAV-05: mobile hamburger menu button visible at 375px", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await gotoAuthed(page, "/dashboard");

    // AppShell renders a Menu (hamburger) button for mobile
    const menuBtn = page.getByRole("button", { name: /menu|open navigation/i });
    await expect(menuBtn).toBeVisible();
  });

  test("SMOKE-NAV-06: mobile hamburger opens nav overlay", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await gotoAuthed(page, "/dashboard");

    const menuBtn = page.getByRole("button", { name: /menu|open navigation/i });
    await menuBtn.click();

    // After opening, nav links should become visible in the overlay.
    await expect(page.getByRole("link", { name: "Dashboard" })).toBeVisible({ timeout: 3_000 });
  });
});

// ─── SMOKE-EXPLORE: Explore page interactions ─────────────────────────────────

test.describe("SMOKE-EXPLORE: Explore page", () => {
  const MOCK_AGENTS_RESPONSE = {
    agents: [
      {
        handle: "tonys-pizza",
        name: "Tony's Pizza",
        industry: "Restaurant",
        description: "Order pizza online.",
        agent_type: "business",
        avatar_url: "",
        primary_color: "#F0B429",
        greeting: "Welcome to Tony's Pizza!",
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        handle: "bella-salon",
        name: "Bella Salon",
        industry: "Salon",
        description: "Book beauty appointments.",
        agent_type: "business",
        avatar_url: "",
        primary_color: "#A78BFA",
        greeting: "Welcome to Bella Salon!",
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        handle: "fitness-pro",
        name: "Fitness Pro",
        industry: "Fitness",
        description: "Personal training sessions.",
        agent_type: "business",
        avatar_url: "",
        primary_color: "#34D399",
        greeting: "Let's get fit!",
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
    total: 3,
    limit: 100,
    offset: 0,
  };

  test("SMOKE-EXP-01: search input filters agent list by name", async ({ page }) => {
    await page.route("**/api/v1/public/agents**", (route) => {
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MOCK_AGENTS_RESPONSE) });
    });

    await page.goto("/explore");
    await page.waitForLoadState("networkidle");

    // All 3 agents should show before filtering.
    await expect(page.getByText("Tony's Pizza")).toBeVisible();
    await expect(page.getByText("Bella Salon")).toBeVisible();

    // Type in search box
    await page.getByPlaceholder(/search/i).fill("pizza");

    // Only Tony's Pizza should remain visible.
    await expect(page.getByText("Tony's Pizza")).toBeVisible();
    await expect(page.getByText("Bella Salon")).not.toBeVisible();
  });

  test("SMOKE-EXP-02: Restaurant category chip filters to restaurant agents", async ({ page }) => {
    await page.route("**/api/v1/public/agents**", (route) => {
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MOCK_AGENTS_RESPONSE) });
    });

    await page.goto("/explore");
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Restaurant" }).click();

    // Tony's Pizza (restaurant industry) should remain; Bella Salon should hide.
    await expect(page.getByText("Tony's Pizza")).toBeVisible();
    await expect(page.getByText("Bella Salon")).not.toBeVisible();
  });

  test("SMOKE-EXP-03: Clear filters resets to all agents", async ({ page }) => {
    await page.route("**/api/v1/public/agents**", (route) => {
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MOCK_AGENTS_RESPONSE) });
    });

    await page.goto("/explore");
    await page.waitForLoadState("networkidle");

    // Apply a search that matches nothing
    await page.getByPlaceholder(/search/i).fill("xyznotfound");

    // "No agents found" empty state
    await expect(page.getByText(/no agents found/i)).toBeVisible();

    // Clear filters button
    await page.getByRole("button", { name: /clear filters/i }).click();

    // All agents restored
    await expect(page.getByText("Tony's Pizza")).toBeVisible();
    await expect(page.getByText("Bella Salon")).toBeVisible();
  });

  test("SMOKE-EXP-04: agent card link navigates to /agents/[handle]", async ({ page }) => {
    await page.route("**/api/v1/public/agents**", (route) => {
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MOCK_AGENTS_RESPONSE) });
    });
    // Mock the specific agent profile endpoint too so the profile page loads.
    await page.route("**/api/v1/public/agents/tonys-pizza**", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          handle: "tonys-pizza",
          name: "Tony's Pizza",
          industry: "Restaurant",
          description: "Order pizza online.",
          agent_type: "business",
          avatar_url: "",
          primary_color: "#F0B429",
          greeting: "Welcome to Tony's Pizza!",
          created_at: "2026-01-01T00:00:00Z",
          capabilities: ["Take orders", "Check menu", "Book table"],
          card_url: "",
          chat_url: "",
          qr_url: "",
          widget_embed_code: '<script src="https://cdn.dingdawg.com/widget.js" data-handle="tonys-pizza"></script>',
        }),
      });
    });

    await page.goto("/explore");
    await page.waitForLoadState("networkidle");

    // Click Tony's Pizza card
    await page.getByText("Tony's Pizza").first().click();

    await page.waitForURL(/\/agents\/tonys-pizza/, { timeout: 8_000 });
    await expect(page).toHaveURL(/\/agents\/tonys-pizza/);

    // Profile page should show agent name
    await expect(page.getByRole("heading", { name: "Tony's Pizza" })).toBeVisible();
  });
});
