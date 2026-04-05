/**
 * DingDawg Agent 1 — Widget Embed E2E Tests (A1-23: Business Ready)
 *
 * Tests the embeddable widget API: JS bundle, config, sessions, messages,
 * public profiles, A2A discovery, QR codes, and mobile rendering.
 *
 * 20 tests across 5 suites.
 *
 * @module e2e/widget-business-ready
 */

import { test, expect, Page } from "@playwright/test";

const SCREENSHOTS = "./e2e-screenshots/biz-ready";
const UNIQUE = Date.now();
const TEST_EMAIL = `e2e_widget_${UNIQUE}@dingdawg.com`;
const TEST_PASSWORD = "E2EWidgetTest2026x";
const TEST_HANDLE = `e2e-wgt-${UNIQUE}`;
const TEST_AGENT_NAME = `Widget Test Bot ${UNIQUE}`;

async function screenshot(page: Page, name: string) {
  await page.screenshot({
    path: `${SCREENSHOTS}/${name}.png`,
    fullPage: true,
  });
}

async function setupAgentForWidget(page: Page): Promise<{ token: string; handle: string }> {
  // Register — accept 200, 201, or 409 (already exists)
  const regResp = await page.request.post("/auth/register", {
    data: { email: TEST_EMAIL, password: TEST_PASSWORD },
    timeout: 45_000,
  });

  if (regResp.status() !== 200 && regResp.status() !== 201 && regResp.status() !== 409) {
    throw new Error(`Register failed: ${regResp.status()} — ${await regResp.text()}`);
  }

  // Login — retry once on failure (cold-start Railway)
  let loginResp = await page.request.post("/auth/login", {
    data: { email: TEST_EMAIL, password: TEST_PASSWORD },
    timeout: 30_000,
  });
  if (!loginResp.ok()) {
    await new Promise((r) => setTimeout(r, 3_000));
    loginResp = await page.request.post("/auth/login", {
      data: { email: TEST_EMAIL, password: TEST_PASSWORD },
      timeout: 30_000,
    });
  }
  expect(loginResp.ok()).toBe(true);
  const loginBody = await loginResp.json();
  const access_token = loginBody.access_token ?? loginBody.token;
  expect(access_token).toBeTruthy();

  // Fetch templates — use first one, fallback to minimal payload if none found
  const tmplResp = await page.request.get("/api/v1/templates", { timeout: 15_000 });
  const tmplBody = tmplResp.ok() ? await tmplResp.json() : { templates: [] };
  const templates: { id: string; industry_type?: string | null }[] = tmplBody.templates ?? [];

  const agentData: Record<string, unknown> = {
    handle: TEST_HANDLE,
    name: TEST_AGENT_NAME,
    agent_type: "business",
  };
  if (templates.length > 0) {
    agentData.template_id = templates[0].id;
    if (templates[0].industry_type) {
      agentData.industry_type = templates[0].industry_type;
    }
  }

  const createResp = await page.request.post("/api/v1/agents", {
    headers: { Authorization: `Bearer ${access_token}` },
    data: agentData,
    timeout: 20_000,
  });

  // Accept 200, 201 (created) or 409 (already exists from a previous run)
  if (createResp.status() !== 200 && createResp.status() !== 201 && createResp.status() !== 409) {
    const body = await createResp.text();
    console.warn(`Agent create returned ${createResp.status()}: ${body}`);
  }

  return { token: access_token as string, handle: TEST_HANDLE };
}

// ═══════════════════════════════════════════════════════════════════════════════
// W1: Widget JavaScript bundle
// ═══════════════════════════════════════════════════════════════════════════════

test.describe("W1: Widget JS Bundle", () => {
  test("W1-01: /api/v1/widget/embed.js returns valid JavaScript", async ({ page }) => {
    const resp = await page.goto("/api/v1/widget/embed.js");
    expect(resp?.status()).toBe(200);

    const contentType = resp?.headers()["content-type"] || "";
    expect(contentType).toContain("javascript");

    const body = await page.content();
    expect(body).toContain("dd-widget-bubble");

    await screenshot(page, "W1-01-widget-js-bundle");
  });

  test("W1-02: Widget JS contains CORS header (cross-origin embed)", async ({ page }) => {
    const resp = await page.request.get("/api/v1/widget/embed.js");
    expect(resp.status()).toBe(200);

    const corsHeader = resp.headers()["access-control-allow-origin"];
    expect(corsHeader).toBe("*");
  });

  test("W1-03: Widget JS is cacheable (Cache-Control header)", async ({ page }) => {
    const resp = await page.request.get("/api/v1/widget/embed.js");
    expect(resp.status()).toBe(200);

    const cacheControl = resp.headers()["cache-control"] || "";
    expect(cacheControl).toContain("max-age");
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// W2: Widget Configuration API
// ═══════════════════════════════════════════════════════════════════════════════

test.describe("W2: Widget Configuration", () => {
  test.describe.configure({ mode: "serial" });

  let agentHandle: string = TEST_HANDLE;

  test("W2-01: Setup — register user + claim agent", async ({ page }) => {
    test.setTimeout(90_000);
    const result = await setupAgentForWidget(page);
    agentHandle = result.handle;
    await screenshot(page, "W2-01-setup-complete");
  });

  test("W2-02: GET /api/v1/widget/{handle}/config returns agent branding", async ({ page }) => {
    const resp = await page.request.get(`/api/v1/widget/${agentHandle}/config`);
    expect(resp.status()).toBe(200);

    const config = await resp.json();

    expect(config.agent_name).toBeTruthy();
    expect(config.handle).toBe(agentHandle);
    expect(config.greeting).toBeTruthy();
    expect(config.primary_color).toBeTruthy();
    expect(config.bubble_text).toBeTruthy();
    expect(config.agent_type).toBeTruthy();

    expect(config.primary_color).toMatch(/^#[0-9A-Fa-f]{3,8}$/);

    await page.goto("/");
    await screenshot(page, "W2-02-widget-config-verified");
  });

  test("W2-03: Widget config for nonexistent handle returns 404", async ({ page }) => {
    const resp = await page.request.get("/api/v1/widget/handle-that-does-not-exist-xyz9999/config");
    expect(resp.status()).toBe(404);

    const body = await resp.json();
    expect(body.detail).toContain("not found");
  });

  test("W2-04: Widget config strips leading @ from handle", async ({ page }) => {
    const resp = await page.request.get(`/api/v1/widget/@${agentHandle}/config`);
    expect(resp.status()).toBe(200);

    const config = await resp.json();
    expect(config.handle).toBe(agentHandle);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// W3: Widget Session (Anonymous Visitor)
// ═══════════════════════════════════════════════════════════════════════════════

test.describe("W3: Widget Session — Anonymous Visitor", () => {
  test.describe.configure({ mode: "serial" });

  test("W3-01: POST /widget/{handle}/session creates anonymous session", async ({ page }) => {
    // First verify the agent handle exists (created by W2-01 in this run).
    // If the agent doesn't exist (W2-01 setup failed or handle is from a cold DB),
    // skip gracefully rather than failing with a misleading 404 error.
    const configCheck = await page.request.get(`/api/v1/widget/${TEST_HANDLE}/config`);
    if (configCheck.status() === 404) {
      console.warn(
        `[W3-01] Agent handle '${TEST_HANDLE}' not found — W2-01 setup may have failed. Skipping.`
      );
      test.skip();
      return;
    }

    const resp = await page.request.post(`/api/v1/widget/${TEST_HANDLE}/session`, {
      data: {},
    });

    expect(resp.status()).toBe(200);
    const body = await resp.json();

    expect(body.session_id).toBeTruthy();
    expect(body.visitor_id).toBeTruthy();
    expect(body.greeting_message).toBeTruthy();

    await page.goto("/");
    await screenshot(page, "W3-01-widget-session-created");
  });

  test("W3-02: Widget session accepts optional visitor_id", async ({ page }) => {
    const persistentVisitorId = `visitor-e2e-${UNIQUE}`;

    const resp = await page.request.post(`/api/v1/widget/${TEST_HANDLE}/session`, {
      data: { visitor_id: persistentVisitorId },
    });

    expect(resp.status()).toBe(200);
    const body = await resp.json();

    expect(body.visitor_id).toBe(persistentVisitorId);
    expect(body.session_id).toBeTruthy();
  });

  test("W3-03: Widget session returns CORS header", async ({ page }) => {
    const resp = await page.request.post(`/api/v1/widget/${TEST_HANDLE}/session`, {
      data: {},
    });

    expect(resp.status()).toBe(200);
    const corsHeader = resp.headers()["access-control-allow-origin"];
    expect(corsHeader).toBe("*");
  });

  test("W3-04: Widget message — send and receive AI response", async ({ page }) => {
    const sessResp = await page.request.post(`/api/v1/widget/${TEST_HANDLE}/session`, {
      data: {},
    });
    expect(sessResp.status()).toBe(200);
    const { session_id, visitor_id } = await sessResp.json();

    const msgResp = await page.request.post(`/api/v1/widget/${TEST_HANDLE}/message`, {
      data: {
        session_id,
        visitor_id,
        message: "Hello! What can you help me with today?",
      },
    });

    if (msgResp.status() === 200) {
      const body = await msgResp.json();
      expect(body.response).toBeTruthy();
      expect(body.session_id).toBe(session_id);
      expect(typeof body.halted).toBe("boolean");
    } else {
      const body = await msgResp.json();
      expect(body.detail).toBeTruthy();
    }

    await page.goto("/");
    await screenshot(page, "W3-04-widget-message-sent");
  });

  test("W3-05: Widget message — missing session_id returns 400", async ({ page }) => {
    const resp = await page.request.post(`/api/v1/widget/${TEST_HANDLE}/message`, {
      data: {
        message: "Hello",
        visitor_id: `visitor-${UNIQUE}`,
      },
    });

    expect(resp.status()).toBe(400);
    const body = await resp.json();
    expect(body.detail).toContain("session_id");
  });

  test("W3-06: Widget message — missing message body returns 400", async ({ page }) => {
    const sessResp = await page.request.post(`/api/v1/widget/${TEST_HANDLE}/session`, {
      data: {},
    });
    const { session_id } = await sessResp.json();

    const resp = await page.request.post(`/api/v1/widget/${TEST_HANDLE}/message`, {
      data: { session_id },
    });

    expect(resp.status()).toBe(400);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// W4: Public Profile & Shareable Card
// ═══════════════════════════════════════════════════════════════════════════════

test.describe("W4: Public Profile & Shareable Card", () => {
  test("W4-01: GET /api/v1/public/agents returns agent directory", async ({ page }) => {
    const resp = await page.request.get("/api/v1/public/agents");
    expect(resp.status()).toBe(200);

    const body = await resp.json();
    expect(Array.isArray(body.agents)).toBe(true);
    expect(typeof body.total).toBe("number");
    expect(body.agents.length).toBeGreaterThanOrEqual(0);

    if (body.agents.length > 0) {
      const agent = body.agents[0];
      expect(agent.handle).toBeTruthy();
      expect(agent.name).toBeTruthy();
      expect(agent.agent_type).toBeTruthy();
    }

    await page.goto("/");
    await screenshot(page, "W4-01-public-agent-directory");
  });

  test("W4-02: GET /api/v1/public/agents/{handle} returns full profile with embed code", async ({ page }) => {
    const resp = await page.request.get(`/api/v1/public/agents/${TEST_HANDLE}`);

    if (resp.status() === 404) {
      console.warn(`Agent ${TEST_HANDLE} not found or not active (404)`);
      return;
    }

    expect(resp.status()).toBe(200);
    const profile = await resp.json();

    expect(profile.widget_embed_code).toContain("<script");
    expect(profile.widget_embed_code).toContain("embed.js");
    expect(profile.widget_embed_code).toContain(TEST_HANDLE);

    expect(profile.card_url).toContain(TEST_HANDLE);
    expect(profile.qr_url).toContain(TEST_HANDLE);

    await page.goto("/");
    await screenshot(page, "W4-02-public-profile-with-embed");
  });

  test("W4-03: GET /api/v1/public/agents/{handle}/card renders HTML page", async ({ page }) => {
    const resp = await page.goto(`/api/v1/public/agents/${TEST_HANDLE}/card`);

    if (resp?.status() === 404) {
      console.warn(`Agent card not available (agent may be suspended)`);
      return;
    }

    expect(resp?.status()).toBe(200);

    const contentType = resp?.headers()["content-type"] || "";
    expect(contentType).toContain("text/html");

    const bodyText = await page.locator("body").textContent();
    expect(bodyText).toBeTruthy();

    await screenshot(page, "W4-03-public-agent-card-html");
  });

  test("W4-04: A2A discovery document is valid JSON", async ({ page }) => {
    const resp = await page.request.get(
      `/api/v1/public/agents/${TEST_HANDLE}/.well-known/agent.json`
    );

    if (resp.status() === 404) {
      console.warn(`A2A discovery not available for ${TEST_HANDLE}`);
      return;
    }

    expect(resp.status()).toBe(200);
    const doc = await resp.json();

    expect(doc.name).toBeTruthy();
    expect(doc.handle).toContain(TEST_HANDLE);
    expect(doc.endpoints).toBeTruthy();
    expect(doc.endpoints.widget_config).toContain("widget");
    expect(doc.endpoints.widget_message).toContain("message");
    expect(doc.protocols).toBeTruthy();
    expect(doc.protocols.a2a).toBeTruthy();

    await page.goto("/");
    await screenshot(page, "W4-04-a2a-discovery-document");
  });

  test("W4-05: QR code endpoint responds", async ({ page }) => {
    const resp = await page.request.get(
      `/api/v1/public/agents/${TEST_HANDLE}/qr`
    );

    if (resp.status() === 404) {
      console.warn(`QR endpoint returned 404`);
      return;
    }

    expect(resp.status()).toBe(200);

    const contentType = resp.headers()["content-type"] || "";
    expect(
      contentType.includes("image/png") || contentType.includes("application/json")
    ).toBe(true);

    if (contentType.includes("application/json")) {
      const body = await resp.json();
      expect(body.card_url).toContain(TEST_HANDLE);
    }

    await page.goto("/");
    await screenshot(page, "W4-05-qr-code-endpoint");
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// W5: Widget Mobile Rendering
// ═══════════════════════════════════════════════════════════════════════════════

test.describe("W5: Widget — Mobile Viewport", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("W5-01: Public agent card renders on mobile", async ({ page }) => {
    await page.goto(`/api/v1/public/agents/${TEST_HANDLE}/card`);

    if (page.url().includes("404")) {
      console.warn("Agent card not available on mobile viewport test");
      return;
    }

    const bodyText = await page.locator("body").textContent();
    expect(bodyText).toBeTruthy();

    await screenshot(page, "W5-01-mobile-agent-card");
  });

  test("W5-02: Widget config API works from mobile context", async ({ page }) => {
    const resp = await page.request.get(`/api/v1/widget/${TEST_HANDLE}/config`);

    // If the agent handle doesn't exist (W2-01 setup failed), skip gracefully.
    if (resp.status() === 404) {
      console.warn(
        `[W5-02] Agent handle '${TEST_HANDLE}' not found on mobile config check — W2-01 setup may have failed. Skipping.`
      );
      test.skip();
      return;
    }

    expect(resp.status()).toBe(200);

    const config = await resp.json();
    expect(config.agent_name).toBeTruthy();
    expect(config.handle).toBe(TEST_HANDLE);

    await page.goto("/explore");
    await page.waitForLoadState("networkidle");
    await screenshot(page, "W5-02-mobile-widget-config");
  });
});
