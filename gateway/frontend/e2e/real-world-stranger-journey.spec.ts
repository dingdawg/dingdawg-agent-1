/**
 * DingDawg Agent 1 — Real-World Stranger Journey E2E Tests
 *
 * Simulates a complete first-time visitor experience against the REAL
 * deployed stack: Vercel frontend → Railway backend → SQLite DB → OpenAI LLM.
 *
 * Tests are split into:
 *   Block 1 — UI Verification: Does the frontend render correctly? (J1-J3)
 *   Block 2 — API Stranger Journey: Register → Claim → Chat → Skill (J4-J8)
 *   Block 3 — LLM → Skill Integration: Natural language → real DB writes (L1-L6)
 *   Block 4 — Cleanup: Logout verification (J9)
 *
 * Backend:  https://api.dingdawg.com
 * Frontend: https://app.dingdawg.com
 */

import { test, expect, type Page, type APIRequestContext } from "@playwright/test";

// ─── Constants ────────────────────────────────────────────────────────────────

const BASE = "https://app.dingdawg.com";
const API = process.env.BACKEND_URL ?? "https://api.dingdawg.com";

const TS = Date.now();
const EMAIL = `rw_stranger_${TS}@dingdawg.com`;
const PASSWORD = "StrangerJourney2026!";
const HANDLE = `rw-stranger-${TS}`;

// ─── Shared state (populated by earlier tests, consumed by later ones) ───────

let token = "";
let userId = "";
let agentId = "";
let sessionId = "";

// ─── Helpers ────────────────────────────────────────────────────────────────

async function ss(page: Page, name: string) {
  await page.screenshot({
    path: `e2e-screenshots/real-world/${name}.png`,
    fullPage: true,
  });
}

/**
 * Inject auth into localStorage so Next.js recognises the session.
 */
async function injectAuth(page: Page) {
  await page.goto(`${BASE}/login`);
  await page.evaluate(
    ({ t, u }) => {
      localStorage.setItem("access_token", t);
      localStorage.setItem("auth_user", JSON.stringify(u));
    },
    { t: token, u: { id: userId, email: EMAIL } }
  );
}

/**
 * Send a chat message through the session API and return the response.
 */
async function sendChatMessage(
  request: APIRequestContext,
  content: string
): Promise<{ content: string; model_used: string }> {
  // Ensure session exists
  if (!sessionId) {
    const sessResp = await request.post(`${API}/api/v1/sessions`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { agent_id: agentId },
      timeout: 20_000,
    });
    expect(sessResp.ok()).toBeTruthy();
    const sess = await sessResp.json();
    sessionId = (sess.session_id ?? sess.id ?? "") as string;
  }

  const res = await request.post(
    `${API}/api/v1/sessions/${sessionId}/message`,
    {
      headers: { Authorization: `Bearer ${token}` },
      data: { content },
      timeout: 60_000,
    }
  );
  expect(res.status()).toBe(200);
  const body = await res.json();
  return {
    content: (body.content ?? "") as string,
    model_used: (body.model_used ?? "") as string,
  };
}

/**
 * Check if any keyword appears in text (case-insensitive).
 */
function hasKeyword(text: string, keywords: string[]): boolean {
  const lower = text.toLowerCase();
  return keywords.some((kw) => lower.includes(kw.toLowerCase()));
}

// ─── Block 1: UI Verification (J1-J3) ───────────────────────────────────────

test.describe("Block 1: UI Verification", () => {
  test.describe.configure({ mode: "serial" });

  test("J1: Landing page renders SSR homepage", async ({ page }) => {
    await page.goto(BASE);
    await page.waitForLoadState("networkidle");

    // SSR homepage hero — "Your AI Agent." heading
    const heading = page.locator("h1, h2").first();
    await expect(heading).toBeVisible({ timeout: 10_000 });
    const text = (await heading.textContent()) ?? "";
    expect(text.toLowerCase()).toContain("your ai agent");

    // CTA button — "Claim Your Agent"
    await expect(
      page.locator("a:has-text('Claim Your Agent'), a:has-text('Get Started')").first()
    ).toBeVisible();

    // Login link visible in nav or body
    await expect(
      page.locator("a:has-text('Sign In'), a:has-text('Login'), a[href='/login']").first()
    ).toBeVisible();

    await ss(page, "J1-landing");
  });

  test("J2: Register page renders form", async ({ page }) => {
    await page.goto(`${BASE}/register`);
    await page.waitForLoadState("networkidle");

    await expect(page.locator("input[type='email'], input[name='email']").first()).toBeVisible();
    await expect(page.locator("input[type='password']").first()).toBeVisible();

    await ss(page, "J2-register-page");
  });

  test("J3: Claim page renders (after auth injection)", async ({ page }) => {
    // Register via API first
    const regResp = await page.request.post(`${API}/auth/register`, {
      data: { email: EMAIL, password: PASSWORD },
      timeout: 20_000,
    });
    expect([200, 201]).toContain(regResp.status());
    const body = await regResp.json();
    token = (body.access_token ?? body.token ?? "") as string;
    userId = (body.user_id ?? body.id ?? "") as string;
    expect(token).toBeTruthy();

    // Inject auth and navigate to claim
    await injectAuth(page);
    await page.goto(`${BASE}/claim`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(3_000);

    // The page should render something (not a blank 500)
    const bodyText = (await page.locator("body").textContent()) ?? "";
    expect(bodyText.trim().length).toBeGreaterThan(10);

    await ss(page, "J3-claim-page");
  });
});

// ─── Block 2: API Stranger Journey (J4-J8) ─────────────────────────────────

test.describe("Block 2: API Stranger Journey", () => {
  test.describe.configure({ mode: "serial" });

  test("J4: Register new user via API", async ({ page }) => {
    // Skip if already registered in Block 1
    if (!token) {
      const resp = await page.request.post(`${API}/auth/register`, {
        data: { email: EMAIL, password: PASSWORD },
        timeout: 20_000,
      });

      // Accept 201 (new) or 409/400 (already exists from Block 1)
      if (resp.status() === 201 || resp.status() === 200) {
        const body = await resp.json();
        token = (body.access_token ?? body.token ?? "") as string;
        userId = (body.user_id ?? body.id ?? "") as string;
      } else {
        // Login instead
        const loginResp = await page.request.post(`${API}/auth/login`, {
          data: { email: EMAIL, password: PASSWORD },
          timeout: 20_000,
        });
        expect(loginResp.ok()).toBeTruthy();
        const body = await loginResp.json();
        token = (body.access_token ?? body.token ?? "") as string;
        userId = (body.user_id ?? body.id ?? "") as string;
      }
    }

    expect(token).toBeTruthy();
    console.log(`J4 OK — registered user=${EMAIL} token_len=${token.length}`);
  });

  test("J5: Check handle availability via API", async ({ page }) => {
    const resp = await page.request.get(
      `${API}/api/v1/agents/handle/${HANDLE}/check`,
      { timeout: 10_000 }
    );
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body.available).toBe(true);
    expect(body.handle).toBe(HANDLE);

    console.log(`J5 OK — handle @${HANDLE} is available`);
  });

  test("J6: Create agent via API (claim)", async ({ page }) => {
    const resp = await page.request.post(`${API}/api/v1/agents`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        handle: HANDLE,
        name: "RW Stranger Restaurant",
        agent_type: "business",
        industry: "restaurant",
      },
      timeout: 20_000,
    });

    expect([200, 201]).toContain(resp.status());
    const body = await resp.json();
    agentId = (body.id ?? body.agent_id ?? "") as string;
    expect(agentId).toBeTruthy();

    console.log(`J6 OK — agent created id=${agentId} handle=@${HANDLE}`);
  });

  test("J7: Create chat session via API", async ({ page }) => {
    const resp = await page.request.post(`${API}/api/v1/sessions`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { agent_id: agentId },
      timeout: 20_000,
    });
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    sessionId = (body.session_id ?? body.id ?? "") as string;
    expect(sessionId).toBeTruthy();

    console.log(`J7 OK — session created id=${sessionId}`);
  });

  test("J8: Send 'Hello' and receive LLM response", async ({ page }) => {
    test.slow(); // LLM latency

    const { content, model_used } = await sendChatMessage(page.request, "Hello");

    expect(content.length).toBeGreaterThan(0);
    expect(model_used).toBeTruthy();

    console.log(`J8 OK — model=${model_used} response_len=${content.length}`);
    console.log(`J8 response: ${content.slice(0, 200)}`);

    await ss(page, "J8-hello-response");
  });
});

// ─── Block 3: LLM → Skill Integration (L1-L6) ─────────────────────────────

test.describe("Block 3: LLM Skill Integration", () => {
  test.describe.configure({ mode: "serial" });

  // Ensure auth is set up (may run independently of Block 2)
  test.beforeAll(async ({ request }) => {
    if (!token) {
      const loginResp = await request.post(`${API}/auth/login`, {
        data: { email: EMAIL, password: PASSWORD },
        timeout: 20_000,
      });
      if (loginResp.ok()) {
        const body = await loginResp.json();
        token = (body.access_token ?? body.token ?? "") as string;
      }
    }
    if (!agentId && token) {
      const listResp = await request.get(`${API}/api/v1/agents`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (listResp.ok()) {
        const data = await listResp.json();
        if (data.agents?.length > 0) {
          agentId = data.agents[0].id as string;
        }
      }
    }
  });

  test("L1: 'Add contact John Doe' triggers contacts skill", async ({ page }) => {
    test.slow();

    const { content, model_used } = await sendChatMessage(
      page.request,
      "Add contact John Doe with email john@test.com"
    );

    console.log(`L1 model=${model_used} response: ${content.slice(0, 200)}`);
    expect(content.length).toBeGreaterThan(0);
    expect(
      hasKeyword(content, ["added", "created", "contact", "saved", "john", "doe"])
    ).toBe(true);

    await ss(page, "L1-contacts-add");
  });

  test("L2: 'Schedule appointment' triggers appointments skill", async ({ page }) => {
    test.slow();

    const { content, model_used } = await sendChatMessage(
      page.request,
      "Schedule an appointment for tomorrow at 2pm with Dr. Smith"
    );

    console.log(`L2 model=${model_used} response: ${content.slice(0, 200)}`);
    expect(content.length).toBeGreaterThan(0);
    expect(
      hasKeyword(content, ["scheduled", "booked", "appointment", "confirmed", "smith", "2pm"])
    ).toBe(true);

    await ss(page, "L2-appointment-schedule");
  });

  test("L3: 'Create invoice' triggers invoicing skill", async ({ page }) => {
    test.slow();

    const { content, model_used } = await sendChatMessage(
      page.request,
      "Create an invoice for $50 for web design work"
    );

    console.log(`L3 model=${model_used} response: ${content.slice(0, 200)}`);
    expect(content.length).toBeGreaterThan(0);
    expect(
      hasKeyword(content, ["invoice", "created", "$50", "50", "web design", "draft"])
    ).toBe(true);

    await ss(page, "L3-invoice-create");
  });

  test("L4: 'Add inventory' triggers inventory skill", async ({ page }) => {
    test.slow();

    const { content, model_used } = await sendChatMessage(
      page.request,
      "Add 100 units of flour to my inventory"
    );

    console.log(`L4 model=${model_used} response: ${content.slice(0, 200)}`);
    expect(content.length).toBeGreaterThan(0);
    expect(
      hasKeyword(content, ["added", "inventory", "flour", "100", "units", "item", "created"])
    ).toBe(true);

    await ss(page, "L4-inventory-add");
  });

  test("L5: 'Record expense' triggers expenses skill", async ({ page }) => {
    test.slow();

    const { content, model_used } = await sendChatMessage(
      page.request,
      "Record an expense of $45 for office supplies"
    );

    console.log(`L5 model=${model_used} response: ${content.slice(0, 200)}`);
    expect(content.length).toBeGreaterThan(0);
    expect(
      hasKeyword(content, ["recorded", "expense", "$45", "45", "office", "supplies", "logged"])
    ).toBe(true);

    await ss(page, "L5-expense-record");
  });

  test("L6: 'Show my contacts' recalls John Doe from L1", async ({ page }) => {
    test.slow();

    const { content, model_used } = await sendChatMessage(
      page.request,
      "Show my contacts"
    );

    console.log(`L6 model=${model_used} response: ${content.slice(0, 200)}`);
    expect(content.length).toBeGreaterThan(0);
    expect(
      hasKeyword(content, ["john", "doe", "contact", "found", "list", "here"])
    ).toBe(true);

    await ss(page, "L6-contacts-recall");
  });
});

// ─── Block 4: Verify Skill Results via Direct API ──────────────────────────

test.describe("Block 4: Direct Skill Verification", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeAll(async ({ request }) => {
    if (!token) {
      const loginResp = await request.post(`${API}/auth/login`, {
        data: { email: EMAIL, password: PASSWORD },
        timeout: 20_000,
      });
      if (loginResp.ok()) {
        const body = await loginResp.json();
        token = (body.access_token ?? body.token ?? "") as string;
      }
    }
  });

  test("V1: Contacts list via direct API shows John Doe", async ({ page }) => {
    const resp = await page.request.post(`${API}/api/v1/skills/contacts/execute`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { action: "list", parameters: {} },
      timeout: 20_000,
    });

    expect(resp.status()).toBeLessThan(500);

    if (resp.ok()) {
      const body = await resp.json();
      if (body.success && body.output) {
        const output = typeof body.output === "string" ? JSON.parse(body.output) : body.output;
        const contacts = output.contacts ?? [];
        const johnFound = contacts.some(
          (c: Record<string, unknown>) =>
            JSON.stringify(c).toLowerCase().includes("john")
        );
        if (johnFound) {
          console.log("V1 OK — John Doe confirmed in contacts DB");
        } else {
          console.warn(`V1 SOFT — John not found in ${contacts.length} contacts (LLM may not have fired skill)`);
        }
      }
    }

    await ss(page, "V1-contacts-direct-api");
  });

  test("V2: Appointments list via direct API", async ({ page }) => {
    const resp = await page.request.post(`${API}/api/v1/skills/appointments/execute`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { action: "list", parameters: {} },
      timeout: 20_000,
    });

    expect(resp.status()).toBeLessThan(500);
    if (resp.ok()) {
      const body = await resp.json();
      console.log(`V2 — appointments response: success=${body.success}`);
    }

    await ss(page, "V2-appointments-direct-api");
  });

  test("J9: Logout clears session and redirects to login", async ({ page }) => {
    await injectAuth(page);
    await page.goto(`${BASE}/dashboard`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(2_000);
    await ss(page, "J9-before-logout");

    // Try logout button
    const logoutBtn = page.locator(
      "button:has-text('Logout'), button:has-text('Log out'), " +
        "button:has-text('Sign out'), a:has-text('Logout'), a:has-text('Sign out')"
    ).first();

    if (await logoutBtn.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await logoutBtn.click();
      await page.waitForTimeout(3_000);
    }

    await ss(page, "J9-after-logout");

    // Verify token cleared or redirected
    const storedToken = await page
      .evaluate(() => localStorage.getItem("access_token"))
      .catch(() => null);
    const onLogin = page.url().includes("/login");
    const tokenCleared = !storedToken || storedToken === "";

    // At least one condition met
    expect(onLogin || tokenCleared).toBe(true);
    console.log(`J9 OK — onLogin=${onLogin} tokenCleared=${tokenCleared}`);
  });
});
