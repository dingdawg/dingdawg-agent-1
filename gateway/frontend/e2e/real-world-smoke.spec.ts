/**
 * DingDawg Agent 1 — Real-World Production Smoke Tests
 *
 * Verifies production health before running heavy test suites.
 * Hits the REAL Railway backend and Vercel frontend directly.
 * Every test takes a screenshot for visual proof.
 *
 * Run order matters: S2 creates the credentials that S3 uses.
 * Use test.describe.serial to enforce sequential execution.
 */

import { test, expect, Page } from "@playwright/test";

const SCREENSHOTS = "./e2e-screenshots/real-world";
const BACKEND_URL = process.env.BACKEND_URL ?? "https://api.dingdawg.com";

// Unique credentials per test run — avoids collision with parallel CI runs
const TEST_EMAIL = `smoke_${Date.now()}@dingdawg.com`;
const TEST_PASSWORD = "SmokePass2026x!";

async function screenshot(page: Page, name: string) {
  await page.screenshot({ path: `${SCREENSHOTS}/${name}.png`, fullPage: true });
}

test.describe.serial("Production Smoke Tests", () => {
  // ─── S1: Backend Health ──────────────────────────────────────────────────────

  test("S1: Backend health check returns healthy + database connected", async ({ page }) => {
    const response = await page.request.get(`${BACKEND_URL}/health`);

    expect(response.status()).toBe(200);

    const body = await response.json();
    expect(body.status).toMatch(/healthy|degraded/);
    expect(body.database).toBe("connected");

    // Screenshot the raw JSON response rendered on a blank page
    await page.goto(`${BACKEND_URL}/health`);
    await screenshot(page, "S1-health-check");
  });

  // ─── S2: Auth Register ───────────────────────────────────────────────────────

  test("S2: Register new user returns token", async ({ page }) => {
    const response = await page.request.post("/auth/register", {
      data: {
        email: TEST_EMAIL,
        password: TEST_PASSWORD,
      },
    });

    // Accept 200 or 201 — Railway returns 200, spec says 201 is also valid
    expect([200, 201]).toContain(response.status());

    const body = await response.json();
    expect(body.token ?? body.access_token).toBeTruthy();

    // Navigate to register page and screenshot for visual record
    await page.goto("/register");
    await screenshot(page, "S2-auth-register");
  });

  // ─── S3: Auth Login (uses S2 credentials) ───────────────────────────────────

  test("S3: Login with S2 credentials returns token", async ({ page }) => {
    const response = await page.request.post("/auth/login", {
      data: {
        email: TEST_EMAIL,
        password: TEST_PASSWORD,
      },
    });

    expect(response.status()).toBe(200);

    const body = await response.json();
    expect(body.token ?? body.access_token).toBeTruthy();

    // Navigate to login page and screenshot for visual record
    await page.goto("/login");
    await screenshot(page, "S3-auth-login");
  });

  // ─── S4: OpenAPI spec is security-gated in production ───────────────────────

  test("S4: OpenAPI spec is security-gated (returns 404 in production)", async ({ page }) => {
    // The OpenAPI spec (/openapi.json and /docs) is intentionally disabled in
    // production to prevent API enumeration attacks. This test verifies that
    // the security gate is working — a 404 is the CORRECT response.
    const response = await page.request.get(`${BACKEND_URL}/openapi.json`);

    // 404 = security gate active (correct production behaviour)
    // 200 = gate accidentally disabled (test should fail to alert us)
    expect(response.status()).toBe(404);

    // Screenshot for visual record
    await page.goto("/");
    await screenshot(page, "S4-openapi-gated-404");
  });

  // ─── S5: CORS Headers ────────────────────────────────────────────────────────

  test("S5: Backend returns CORS headers on preflight", async ({ page }) => {
    const response = await page.request.fetch(`${BACKEND_URL}/health`, {
      method: "OPTIONS",
      headers: {
        Origin: "https://app.dingdawg.com",
        "Access-Control-Request-Method": "GET",
      },
    });

    // OPTIONS may return 200 or 204 — both are valid preflight responses
    expect([200, 204]).toContain(response.status());

    const headers = response.headers();
    const hasCors =
      "access-control-allow-origin" in headers ||
      "access-control-allow-methods" in headers ||
      "access-control-allow-headers" in headers;

    expect(hasCors).toBe(true);

    // Screenshot the frontend homepage as the visual anchor for this check
    await page.goto("/");
    await screenshot(page, "S5-cors-headers");
  });
});
