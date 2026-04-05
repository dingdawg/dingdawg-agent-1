/**
 * DingDawg Agent 1 — Visual Regression Baselines
 *
 * STOA Layer 8 — Visual Regression Testing
 *
 * Uses Playwright's built-in toHaveScreenshot() for pixel-diff comparisons.
 * Snapshots are stored under e2e/visual-regression.spec.ts-snapshots/ and
 * committed to source control as baselines.
 *
 * Covered pages and states:
 *
 *   PUBLIC (no auth required):
 *     VR-PUB-01  Homepage — desktop 1280×720
 *     VR-PUB-02  Homepage — mobile 375×812
 *     VR-PUB-03  Login page
 *     VR-PUB-04  Register page
 *     VR-PUB-05  Forgot password page
 *     VR-PUB-06  Explore page (loading skeleton + loaded state)
 *     VR-PUB-07  Public agent profile — 404 (unknown handle)
 *     VR-PUB-08  Privacy page
 *     VR-PUB-09  Terms page
 *
 *   AUTHENTICATED (inject token via localStorage; mocked API responses):
 *     VR-AUTH-01  Claim wizard — step 1 (sector grid)
 *     VR-AUTH-02  Claim wizard — step 2 (template list, after sector click)
 *     VR-AUTH-03  Claim wizard — step 3 (@handle input)
 *     VR-AUTH-04  Dashboard — desktop with mocked welcome KPI cards
 *     VR-AUTH-05  Dashboard — mobile 375×812
 *     VR-AUTH-06  Settings page — General tab
 *     VR-AUTH-07  Settings page — Branding tab
 *     VR-AUTH-08  Integrations page — All tab
 *     VR-AUTH-09  Integrations page — Communication tab
 *     VR-AUTH-10  Billing page — plan cards visible
 *     VR-AUTH-11  Analytics page — empty state
 *     VR-AUTH-12  Tasks page — empty state
 *
 *   RESPONSIVE — all authenticated pages at 375px:
 *     VR-MOB-01  Settings mobile
 *     VR-MOB-02  Integrations mobile
 *     VR-MOB-03  Billing mobile
 *     VR-MOB-04  Tasks mobile
 *     VR-MOB-05  Analytics mobile
 *
 * Running baselines:
 *   npx playwright test e2e/visual-regression.spec.ts --update-snapshots
 *
 * Comparing against baselines:
 *   npx playwright test e2e/visual-regression.spec.ts
 *
 * Notes:
 *   - Dynamic content (timestamps, IDs, shimmer pulses) is masked before
 *     snapshot to prevent false failures.
 *   - All tests use page.waitForLoadState("networkidle") to ensure styles
 *     and fonts are settled before capturing.
 *   - Auth is established by injecting a JWT into localStorage + a mock
 *     of GET /api/v1/agents so every protected page sees an agent.
 *   - Never run these against a live production environment — target local
 *     dev server (baseURL: http://localhost:3000 in playwright.config.ts).
 */

import {
  test,
  expect,
  type Page,
  type PageAssertionsToHaveScreenshotOptions,
} from "@playwright/test";

// ─── Viewports ────────────────────────────────────────────────────────────────

const DESKTOP = { width: 1280, height: 720 };
const MOBILE = { width: 375, height: 812 };

// ─── Snapshot options ─────────────────────────────────────────────────────────

/**
 * Default toHaveScreenshot options.
 * maxDiffPixelRatio: 0.02 allows 2% pixel variance (font hinting, AA).
 */
const SNAP_OPTS: PageAssertionsToHaveScreenshotOptions = {
  maxDiffPixelRatio: 0.02,
  animations: "disabled",
};

// ─── Selectors to mask ────────────────────────────────────────────────────────

/**
 * CSS selectors for elements with dynamic content that should be masked
 * (replaced with a solid rectangle) before snapshot comparison.
 */
const DYNAMIC_SELECTORS = [
  // Relative timestamps: "2 minutes ago", "just now"
  "[data-testid='relative-time']",
  // Session IDs shown in session list
  ".session-id",
  // Spinner / loading animations
  ".spinner",
  "[class*='animate-pulse']",
  // Any element with a data-dynamic attribute set by the app
  "[data-dynamic='true']",
];

// ─── Auth mock helpers ────────────────────────────────────────────────────────

const AUTH_TOKEN_KEY = "dd_access_token";
const AUTH_USER_KEY = "dd_user";

/**
 * Inject a fake auth token + user into localStorage and mock the agents
 * endpoint so every ProtectedRoute renders its content without a real backend.
 *
 * The mocked agent shape matches AgentResponse in platformService.ts.
 */
async function injectMockedAuth(page: Page, handle = "e2e-test-agent"): Promise<void> {
  // Mock agents API before navigating so the store hydrates immediately.
  await page.route("**/api/v1/agents**", (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        agents: [
          {
            id: "vr-agent-id-0001",
            handle,
            name: "E2E Test Agent",
            agent_type: "business",
            status: "active",
            subscription_tier: "free",
            industry_type: "restaurant",
            template_id: "restaurant-v1",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
            config_json: null,
            branding_json: null,
          },
        ],
      }),
    });
  });

  // Mock sessions so the session panel doesn't hang.
  await page.route("**/api/v1/sessions**", (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ sessions: [] }),
    });
  });

  // Mock tasks endpoint so the welcome flow resolves.
  await page.route("**/api/v1/tasks**", (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  // Mock usage endpoint so DashboardHeader doesn't spin.
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

  // Mock integration status so /integrations doesn't error.
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

  // Mock analytics endpoints.
  await page.route("**/api/v1/analytics/**", (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total_conversations: 0,
        total_messages: 0,
        avg_messages_per_conversation: 0,
        daily_conversations: [],
      }),
    });
  });

  // Inject localStorage credentials.
  await page.evaluate(
    ([tokKey, usrKey]) => {
      localStorage.setItem(tokKey, "vr-fake-jwt-token-for-testing");
      localStorage.setItem(
        usrKey,
        JSON.stringify({
          id: "vr-user-id-0001",
          email: "vr@dingdawg.test",
          is_active: true,
        })
      );
    },
    [AUTH_TOKEN_KEY, AUTH_USER_KEY]
  );
}

/**
 * Wait for the page to fully settle (network idle + no spinners visible)
 * before taking a snapshot.
 */
async function waitForPageSettle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  // Give framer-motion animations time to complete (disabled via SNAP_OPTS
  // but the layout still shifts on first paint).
  await page.waitForTimeout(300);
}

/**
 * Build the mask list from DYNAMIC_SELECTORS — only includes locators
 * that actually exist on the page so Playwright does not throw on missing
 * elements.
 */
async function buildMasks(page: Page) {
  const masks = [];
  for (const sel of DYNAMIC_SELECTORS) {
    const count = await page.locator(sel).count();
    if (count > 0) {
      masks.push(page.locator(sel));
    }
  }
  return masks;
}

// ─── PUBLIC PAGES ─────────────────────────────────────────────────────────────

test.describe("VR — Public Pages", () => {
  test("VR-PUB-01: homepage desktop 1280×720", async ({ page }) => {
    await page.setViewportSize(DESKTOP);
    await page.goto("/");
    await waitForPageSettle(page);
    const mask = await buildMasks(page);
    await expect(page).toHaveScreenshot("VR-PUB-01-homepage-desktop.png", {
      ...SNAP_OPTS,
      mask,
    });
  });

  test("VR-PUB-02: homepage mobile 375×812", async ({ page }) => {
    await page.setViewportSize(MOBILE);
    await page.goto("/");
    await waitForPageSettle(page);
    const mask = await buildMasks(page);
    await expect(page).toHaveScreenshot("VR-PUB-02-homepage-mobile.png", {
      ...SNAP_OPTS,
      mask,
    });
  });

  test("VR-PUB-03: login page desktop", async ({ page }) => {
    await page.setViewportSize(DESKTOP);
    await page.goto("/login");
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-PUB-03-login-desktop.png", SNAP_OPTS);
  });

  test("VR-PUB-04: register page desktop", async ({ page }) => {
    await page.setViewportSize(DESKTOP);
    await page.goto("/register");
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-PUB-04-register-desktop.png", SNAP_OPTS);
  });

  test("VR-PUB-05: forgot-password page desktop", async ({ page }) => {
    await page.setViewportSize(DESKTOP);
    await page.goto("/forgot-password");
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-PUB-05-forgot-password-desktop.png", SNAP_OPTS);
  });

  test("VR-PUB-06: explore page — loaded state desktop", async ({ page }) => {
    await page.setViewportSize(DESKTOP);

    // Mock agents list so the explore grid has stable content.
    await page.route("**/api/v1/public/agents**", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          agents: [
            {
              handle: "demo-restaurant",
              name: "Demo Restaurant",
              industry: "Restaurant",
              description: "Book tables and order online.",
              agent_type: "business",
              avatar_url: "",
              primary_color: "#F0B429",
              greeting: "Welcome to Demo Restaurant!",
              created_at: "2026-01-01T00:00:00Z",
            },
            {
              handle: "demo-salon",
              name: "Demo Salon",
              industry: "Salon",
              description: "Book beauty appointments.",
              agent_type: "business",
              avatar_url: "",
              primary_color: "#A78BFA",
              greeting: "Welcome to Demo Salon!",
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
          total: 2,
          limit: 100,
          offset: 0,
        }),
      });
    });

    await page.goto("/explore");
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-PUB-06-explore-desktop.png", SNAP_OPTS);
  });

  test("VR-PUB-07: public agent profile 404 state", async ({ page }) => {
    await page.setViewportSize(DESKTOP);

    // Mock the agent API to return 404.
    await page.route("**/api/v1/public/agents/nonexistent-handle-vr**", (route) => {
      route.fulfill({ status: 404, contentType: "application/json", body: '{"detail":"Not found"}' });
    });

    await page.goto("/agents/nonexistent-handle-vr");
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-PUB-07-agent-profile-404.png", SNAP_OPTS);
  });

  test("VR-PUB-08: privacy page", async ({ page }) => {
    await page.setViewportSize(DESKTOP);
    await page.goto("/privacy");
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-PUB-08-privacy.png", SNAP_OPTS);
  });

  test("VR-PUB-09: terms page", async ({ page }) => {
    await page.setViewportSize(DESKTOP);
    await page.goto("/terms");
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-PUB-09-terms.png", SNAP_OPTS);
  });
});

// ─── AUTHENTICATED PAGES ──────────────────────────────────────────────────────

test.describe("VR — Authenticated Pages (desktop 1280×720)", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize(DESKTOP);
  });

  test("VR-AUTH-01: claim wizard step 1 — sector grid", async ({ page }) => {
    await page.route("**/api/v1/onboarding/sectors**", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          sectors: [
            { id: "personal", name: "Personal", agent_type: "personal", icon: "👤", description: "Your private AI assistant.", popular: false },
            { id: "business", name: "Business", agent_type: "business", icon: "🏪", description: "AI agent for your business.", popular: true },
            { id: "b2b", name: "B2B", agent_type: "b2b", icon: "🤝", description: "Business-to-business.", popular: false },
            { id: "a2a", name: "A2A", agent_type: "a2a", icon: "🔗", description: "Agent-to-agent.", popular: false },
            { id: "compliance", name: "Compliance", agent_type: "compliance", icon: "🛡️", description: "Governance-first.", popular: false },
            { id: "enterprise", name: "Enterprise", agent_type: "enterprise", icon: "🏢", description: "Enterprise ops.", popular: false },
            { id: "health", name: "Health", agent_type: "health", icon: "🏥", description: "Patient scheduling.", popular: false },
            { id: "gaming", name: "Gaming", agent_type: "business", icon: "🎮", description: "Game coaching.", popular: true },
          ],
          count: 8,
        }),
      });
    });
    // Agents endpoint returns empty so ProtectedRoute doesn't redirect to /dashboard.
    await page.route("**/api/v1/agents**", (route) => {
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ agents: [] }) });
    });

    await page.goto("/claim");
    await injectMockedAuth(page, "");
    // Re-navigate so the injected auth takes effect.
    await page.goto("/claim");
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-AUTH-01-claim-step1-sector.png", SNAP_OPTS);
  });

  test("VR-AUTH-02: claim wizard step 2 — template list (after selecting Business sector)", async ({ page }) => {
    await page.route("**/api/v1/onboarding/sectors**", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          sectors: [
            { id: "personal", name: "Personal", agent_type: "personal", icon: "👤", description: "Personal assistant.", popular: false },
            { id: "business", name: "Business", agent_type: "business", icon: "🏪", description: "Business agent.", popular: true },
          ],
          count: 2,
        }),
      });
    });
    await page.route("**/api/v1/templates**", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          templates: [
            { id: "restaurant-v1", name: "Restaurant", agent_type: "business", industry_type: "restaurant", description: "Tables, menus, orders." },
            { id: "salon-v1", name: "Salon & Beauty", agent_type: "business", industry_type: "salon", description: "Bookings, reminders." },
            { id: "retail-v1", name: "Retail Store", agent_type: "business", industry_type: "retail", description: "Inventory, orders." },
          ],
          count: 3,
        }),
      });
    });
    await page.route("**/api/v1/agents**", (route) => {
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ agents: [] }) });
    });

    await page.goto("/claim");
    await injectMockedAuth(page, "");
    await page.goto("/claim");
    await waitForPageSettle(page);

    // Click the Business sector card to advance to step 2.
    await page.getByText("Business").first().click();
    await page.getByRole("button", { name: /continue/i }).click();
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-AUTH-02-claim-step2-templates.png", SNAP_OPTS);
  });

  test("VR-AUTH-03: claim wizard step 3 — @handle input", async ({ page }) => {
    await page.route("**/api/v1/onboarding/sectors**", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          sectors: [
            { id: "business", name: "Business", agent_type: "business", icon: "🏪", description: "Business agent.", popular: true },
          ],
          count: 1,
        }),
      });
    });
    await page.route("**/api/v1/templates**", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          templates: [
            { id: "restaurant-v1", name: "Restaurant", agent_type: "business", industry_type: "restaurant", description: "Tables, menus, orders." },
          ],
          count: 1,
        }),
      });
    });
    await page.route("**/api/v1/onboarding/check-handle/**", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ handle: "my-vr-agent", available: true, reason: null }),
      });
    });
    await page.route("**/api/v1/agents**", (route) => {
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ agents: [] }) });
    });

    await page.goto("/claim");
    await injectMockedAuth(page, "");
    await page.goto("/claim");
    await waitForPageSettle(page);

    // Step 1 → select Business → Continue
    await page.getByText("Business").first().click();
    await page.getByRole("button", { name: /continue/i }).click();
    await waitForPageSettle(page);

    // Step 2 → select Restaurant → Continue
    await page.getByText("Restaurant").first().click();
    await page.getByRole("button", { name: /continue/i }).click();
    await waitForPageSettle(page);

    // Type a handle so the page is in "available" state
    await page.locator('input[placeholder*="handle"], input[placeholder*="your-handle"], input[name="handle"], input[id*="handle"]').first().fill("my-vr-agent");
    await page.waitForTimeout(500); // debounce
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-AUTH-03-claim-step3-handle.png", SNAP_OPTS);
  });

  test("VR-AUTH-04: dashboard — desktop with mocked agent and empty chat", async ({ page }) => {
    await injectMockedAuth(page);
    await page.goto("/dashboard");
    await waitForPageSettle(page);
    const mask = await buildMasks(page);
    await expect(page).toHaveScreenshot("VR-AUTH-04-dashboard-desktop.png", {
      ...SNAP_OPTS,
      mask,
    });
  });

  test("VR-AUTH-05: settings — General tab desktop", async ({ page }) => {
    await injectMockedAuth(page);
    await page.goto("/settings");
    await waitForPageSettle(page);
    const mask = await buildMasks(page);
    await expect(page).toHaveScreenshot("VR-AUTH-05-settings-general-desktop.png", {
      ...SNAP_OPTS,
      mask,
    });
  });

  test("VR-AUTH-06: settings — Branding tab desktop", async ({ page }) => {
    await injectMockedAuth(page);
    await page.goto("/settings");
    await waitForPageSettle(page);

    // Click the Branding tab
    await page.getByRole("button", { name: /branding/i }).click();
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-AUTH-06-settings-branding-desktop.png", SNAP_OPTS);
  });

  test("VR-AUTH-07: integrations — All tab desktop", async ({ page }) => {
    await injectMockedAuth(page);
    await page.goto("/integrations");
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-AUTH-07-integrations-all-desktop.png", SNAP_OPTS);
  });

  test("VR-AUTH-08: integrations — Communication tab desktop", async ({ page }) => {
    await injectMockedAuth(page);
    await page.goto("/integrations");
    await waitForPageSettle(page);

    await page.getByRole("button", { name: "Communication" }).click();
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-AUTH-08-integrations-communication-desktop.png", SNAP_OPTS);
  });

  test("VR-AUTH-09: billing — plan cards visible desktop", async ({ page }) => {
    await injectMockedAuth(page);
    await page.goto("/billing");
    await waitForPageSettle(page);
    const mask = await buildMasks(page);
    await expect(page).toHaveScreenshot("VR-AUTH-09-billing-desktop.png", {
      ...SNAP_OPTS,
      mask,
    });
  });

  test("VR-AUTH-10: analytics — empty state desktop", async ({ page }) => {
    await injectMockedAuth(page);
    await page.goto("/analytics");
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-AUTH-10-analytics-empty-desktop.png", SNAP_OPTS);
  });

  test("VR-AUTH-11: tasks — empty state desktop", async ({ page }) => {
    await injectMockedAuth(page);
    await page.goto("/tasks");
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-AUTH-11-tasks-empty-desktop.png", SNAP_OPTS);
  });
});

// ─── MOBILE VISUAL REGRESSION ─────────────────────────────────────────────────

test.describe("VR — Authenticated Pages (mobile 375×812)", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize(MOBILE);
  });

  test("VR-MOB-01: dashboard — mobile 375×812", async ({ page }) => {
    await injectMockedAuth(page);
    await page.goto("/dashboard");
    await waitForPageSettle(page);
    const mask = await buildMasks(page);
    await expect(page).toHaveScreenshot("VR-MOB-01-dashboard-mobile.png", {
      ...SNAP_OPTS,
      mask,
    });
  });

  test("VR-MOB-02: settings — mobile 375×812", async ({ page }) => {
    await injectMockedAuth(page);
    await page.goto("/settings");
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-MOB-02-settings-mobile.png", SNAP_OPTS);
  });

  test("VR-MOB-03: integrations — mobile 375×812", async ({ page }) => {
    await injectMockedAuth(page);
    await page.goto("/integrations");
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-MOB-03-integrations-mobile.png", SNAP_OPTS);
  });

  test("VR-MOB-04: billing — mobile 375×812", async ({ page }) => {
    await injectMockedAuth(page);
    await page.goto("/billing");
    await waitForPageSettle(page);
    const mask = await buildMasks(page);
    await expect(page).toHaveScreenshot("VR-MOB-04-billing-mobile.png", {
      ...SNAP_OPTS,
      mask,
    });
  });

  test("VR-MOB-05: tasks — mobile 375×812", async ({ page }) => {
    await injectMockedAuth(page);
    await page.goto("/tasks");
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-MOB-05-tasks-mobile.png", SNAP_OPTS);
  });

  test("VR-MOB-06: analytics — mobile 375×812", async ({ page }) => {
    await injectMockedAuth(page);
    await page.goto("/analytics");
    await waitForPageSettle(page);
    await expect(page).toHaveScreenshot("VR-MOB-06-analytics-mobile.png", SNAP_OPTS);
  });
});
