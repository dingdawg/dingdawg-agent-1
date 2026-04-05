/**
 * DingDawg Agent 1 — Onboarding Wizard E2E Tests
 *
 * Tests the 3-step /claim wizard against the REAL deployed frontend + backend.
 *
 * Flow:
 *   /claim → Step 1 (sector grid, 8 sectors) →
 *   Step 2 (template list, filtered by sector) →
 *   Step 3 (@handle input + name + submit) → /dashboard
 *
 * Every step takes a screenshot for visual proof.
 *
 * NOTE: These tests use serial mode so state from earlier tests (e.g. claimed
 * handle) is visible to later tests (e.g. "handle is taken" check).
 */

import { test, expect, Page } from "@playwright/test";

const SCREENSHOTS = "./e2e-screenshots";
const UNIQUE = Date.now();
const TEST_EMAIL = `e2e_ob_${UNIQUE}@dingdawg.com`;
const TEST_PASSWORD = "E2EOnboard2026x";
const TEST_HANDLE = `e2e-ob-${UNIQUE}`.slice(0, 28); // max 30 chars
const TEST_AGENT_NAME = `E2E Onboarding Bot ${UNIQUE}`;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function screenshot(page: Page, name: string) {
  await page.screenshot({
    path: `${SCREENSHOTS}/${name}.png`,
    fullPage: true,
  });
}

/** Register a new user via API, return access token. */
async function registerUser(
  page: Page,
  email = TEST_EMAIL,
  password = TEST_PASSWORD
): Promise<string> {
  const resp = await page.request.post("/auth/register", {
    data: { email, password },
  });
  expect(resp.status()).toBe(201);
  const body = await resp.json();
  expect(body.access_token).toBeTruthy();
  return body.access_token;
}

/** Login via UI — fills email + password and submits. */
async function loginViaUI(
  page: Page,
  email = TEST_EMAIL,
  password = TEST_PASSWORD
) {
  await page.goto("/login");
  await page.fill("input[type='email'], input[name='email']", email);
  await page.fill("input[type='password']", password);
  await page
    .locator(
      "button[type='submit'], button:has-text('Log in'), button:has-text('Sign in'), button:has-text('Login')"
    )
    .first()
    .click();
  await page.waitForURL(/\/(dashboard|claim|chat)/, { timeout: 15_000 });
}

// ---------------------------------------------------------------------------
// Suite: Onboarding wizard — desktop viewport
// ---------------------------------------------------------------------------

test.describe("ONB: Onboarding Wizard", () => {
  test.describe.configure({ mode: "serial" });

  // ── 1. /claim page loads with 8 sector cards ──────────────────────────────

  test("ONB-01: /claim page loads with 8 sector cards", async ({ page }) => {
    await registerUser(page);
    await loginViaUI(page);

    await page.goto("/claim");
    await page.waitForLoadState("networkidle");
    await screenshot(page, "onb-01-claim-page-loaded");

    // Header — the h1 text in claim/page.tsx is "Claim Your Agent"
    await expect(
      page.locator("h1:has-text('Claim Your Agent')")
    ).toBeVisible({ timeout: 10_000 });

    // Step 1 heading
    await expect(
      page.locator("h2:has-text('Choose your sector')")
    ).toBeVisible({ timeout: 5_000 });

    // Progress bar visible
    await expect(
      page.locator("[role='progressbar']")
    ).toBeVisible();

    // Wait for sector buttons to appear — loading skeleton uses <div> not <button>.
    // Poll until at least 8 aria-pressed buttons are visible (API load or fallback).
    await page.waitForSelector("button[aria-pressed]", { timeout: 10_000 });
    const sectorButtons = page.locator("button[aria-pressed]");
    const count = await sectorButtons.count();
    expect(count).toBeGreaterThanOrEqual(8);

    await screenshot(page, "onb-02-sector-grid-rendered");
  });

  // ── 2. All 8 sectors are visible ─────────────────────────────────────────

  test("ONB-02: All 8 sector names are visible", async ({ page }) => {
    await loginViaUI(page);
    await page.goto("/claim");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);

    const expectedSectors = [
      "Personal",
      "Business",
      "B2B",
      "A2A",
      "Compliance",
      "Enterprise",
      "Health",
      "Gaming",
    ];

    for (const name of expectedSectors) {
      await expect(
        page.locator(`button:has-text('${name}')`)
      ).toBeVisible({ timeout: 5_000 });
    }

    await screenshot(page, "onb-03-all-8-sectors-visible");
  });

  // ── 3. Continue disabled before sector selection ──────────────────────────

  test("ONB-03: Continue is disabled before sector selection", async ({
    page,
  }) => {
    await loginViaUI(page);
    await page.goto("/claim");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("button:has-text('Continue')")).toBeDisabled();
    await screenshot(page, "onb-04-continue-disabled-no-sector");
  });

  // ── 4. Sector selection highlights card + enables Continue ────────────────

  test("ONB-04: Selecting a sector highlights card and enables Continue", async ({
    page,
  }) => {
    await loginViaUI(page);
    await page.goto("/claim");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);

    // Click the "Business" sector
    await page.locator("button:has-text('Business')").first().click();
    await screenshot(page, "onb-05-business-sector-selected");

    // Continue should now be enabled
    await expect(page.locator("button:has-text('Continue')")).toBeEnabled();

    // The Business button should have aria-pressed=true
    const businessBtn = page.locator("button:has-text('Business')").first();
    await expect(businessBtn).toHaveAttribute("aria-pressed", "true");
  });

  // ── 5. Step 2 shows templates filtered by sector ──────────────────────────

  test("ONB-05: Step 2 shows templates filtered by sector", async ({
    page,
  }) => {
    await loginViaUI(page);
    await page.goto("/claim");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);

    // Select Business sector
    await page.locator("button:has-text('Business')").first().click();
    await page.locator("button:has-text('Continue')").click();

    // Step 2 heading
    await expect(
      page.locator("h2:has-text('Pick a starting template')")
    ).toBeVisible({ timeout: 5_000 });

    // Templates should load
    await page.waitForSelector("button[aria-pressed]", { timeout: 10_000 });

    const templateButtons = page.locator("button[aria-pressed]");
    const templateCount = await templateButtons.count();
    expect(templateCount).toBeGreaterThan(0);

    // Continue disabled until a template is selected
    await expect(page.locator("button:has-text('Continue')")).toBeDisabled();

    await screenshot(page, "onb-06-step2-templates-loaded");
  });

  // ── 6. Template selection enables Continue ────────────────────────────────

  test("ONB-06: Selecting a template enables Continue", async ({ page }) => {
    await loginViaUI(page);
    await page.goto("/claim");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);

    // Navigate to step 2
    await page.locator("button:has-text('Business')").first().click();
    await page.locator("button:has-text('Continue')").click();
    await page.waitForSelector("button[aria-pressed]", { timeout: 10_000 });

    // Select first template
    await page.locator("button[aria-pressed]").first().click();
    await screenshot(page, "onb-07-template-selected");

    await expect(page.locator("button:has-text('Continue')")).toBeEnabled();

    // Template button should have aria-pressed=true
    const firstTemplate = page.locator("button[aria-pressed='true']").first();
    expect(await firstTemplate.count()).toBeGreaterThan(0);
  });

  // ── 7. Step 3 shows @handle input ────────────────────────────────────────

  test("ONB-07: Step 3 shows handle input and name input", async ({
    page,
  }) => {
    await loginViaUI(page);
    await page.goto("/claim");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);

    // Navigate to step 3 (step 0 → sector, step 1 → template, step 2 → handle)
    await page.locator("button:has-text('Business')").first().click();
    await page.locator("button:has-text('Continue')").click();

    // Wait for step 1 (template selection) to be visible.
    // Template buttons have aria-pressed attribute; wait up to 20s for API to respond.
    await page.waitForSelector("h2:has-text('Pick a starting template')", { timeout: 20_000 });
    // Wait for template buttons to appear (may take time for API call to complete)
    await page.waitForSelector("button[aria-pressed]", { timeout: 20_000 });
    await page.locator("button[aria-pressed]").first().click();
    // After selecting a template, Continue button becomes enabled (React state update)
    const continueBtn = page.locator("button:has-text('Continue')");
    await continueBtn.waitFor({ state: "visible", timeout: 5_000 });
    await expect(continueBtn).toBeEnabled({ timeout: 5_000 });
    await continueBtn.click();

    // Step 2 (handle) heading — matches claim/page.tsx line 306: "Claim your @handle"
    await expect(
      page.locator("h2:has-text('Claim your @handle')")
    ).toBeVisible({ timeout: 10_000 });

    // Handle input
    await expect(page.locator("input#handle")).toBeVisible();

    // Agent name input
    await expect(page.locator("input#agent-name")).toBeVisible();

    // Claim Agent button disabled (no handle, no name)
    await expect(page.locator("button:has-text('Claim Agent')")).toBeDisabled();

    await screenshot(page, "onb-08-step3-handle-input");
  });

  // ── 8. Handle availability check — available ──────────────────────────────

  test("ONB-08: Handle availability check shows green when available", async ({
    page,
  }) => {
    await loginViaUI(page);
    await page.goto("/claim");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);

    // Navigate to step 3
    await page.locator("button:has-text('Business')").first().click();
    await page.locator("button:has-text('Continue')").click();
    await page.waitForSelector("button[aria-pressed]", { timeout: 10_000 });
    await page.locator("button[aria-pressed]").first().click();
    await page.locator("button:has-text('Continue')").click();

    await page.waitForSelector("input#handle", { timeout: 5_000 });

    // Type a unique handle
    await page.locator("input#handle").fill(TEST_HANDLE);
    await screenshot(page, "onb-09-handle-typed");

    // Wait for debounce (300ms) + API response
    await page.waitForTimeout(800);

    // Should show availability text
    const availableText = page.locator(`text=is available`);
    await expect(availableText).toBeVisible({ timeout: 5_000 });
    await screenshot(page, "onb-10-handle-available");
  });

  // ── 9. Claim Agent enabled after valid handle + name ─────────────────────

  test("ONB-09: Claim Agent enabled after valid handle + name", async ({
    page,
  }) => {
    await loginViaUI(page);
    await page.goto("/claim");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);

    // Navigate to step 3
    await page.locator("button:has-text('Business')").first().click();
    await page.locator("button:has-text('Continue')").click();
    await page.waitForSelector("button[aria-pressed]", { timeout: 10_000 });
    await page.locator("button[aria-pressed]").first().click();
    await page.locator("button:has-text('Continue')").click();

    await page.waitForSelector("input#handle", { timeout: 5_000 });

    // Enter valid handle
    await page.locator("input#handle").fill(TEST_HANDLE);
    await page.waitForTimeout(800);
    await expect(page.locator("text=is available")).toBeVisible({
      timeout: 5_000,
    });

    // Claim Agent still disabled — no agent name yet
    await expect(page.locator("button:has-text('Claim Agent')")).toBeDisabled();

    // Fill agent name
    await page.locator("input#agent-name").fill(TEST_AGENT_NAME);

    // Now Claim Agent should be enabled
    await expect(page.locator("button:has-text('Claim Agent')")).toBeEnabled();
    await screenshot(page, "onb-11-claim-ready");
  });

  // ── 10. Full flow → submit → redirect to /dashboard ──────────────────────

  test("ONB-10: Full onboarding flow creates agent and redirects to /dashboard", async ({
    page,
  }) => {
    await loginViaUI(page);
    await page.goto("/claim");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);

    // Step 1: Personal sector (avoid Business — might conflict with other tests)
    await page.locator("button:has-text('Personal')").first().click();
    await page.locator("button:has-text('Continue')").click();

    // Step 2: First template
    await page.waitForSelector("button[aria-pressed]", { timeout: 10_000 });
    await page.locator("button[aria-pressed]").first().click();
    await page.locator("button:has-text('Continue')").click();

    // Step 3: Handle + name
    await page.waitForSelector("input#handle", { timeout: 5_000 });
    const fullFlowHandle = `e2e-full-${UNIQUE}`.slice(0, 28);
    await page.locator("input#handle").fill(fullFlowHandle);
    await page.waitForTimeout(800);
    await expect(page.locator("text=is available")).toBeVisible({
      timeout: 5_000,
    });
    await page.locator("input#agent-name").fill(`E2E Full Flow Bot ${UNIQUE}`);

    await screenshot(page, "onb-12-full-flow-ready-to-submit");

    // Submit
    await page.locator("button:has-text('Claim Agent')").click();

    // Should redirect to /dashboard
    await page.waitForURL(/\/dashboard/, { timeout: 20_000 });
    await screenshot(page, "onb-13-redirected-to-dashboard");

    expect(page.url()).toContain("/dashboard");
  });

  // ── 11. Back navigation preserves sector selection ────────────────────────

  test("ONB-11: Back navigation preserves sector selection", async ({
    page,
  }) => {
    await loginViaUI(page);
    await page.goto("/claim");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);

    // Select Health sector
    await page.locator("button:has-text('Health')").first().click();
    await page.locator("button:has-text('Continue')").click();

    // We're on step 2 — go back
    await page.waitForSelector("button:has-text('Back')", { timeout: 5_000 });
    await page.locator("button:has-text('Back')").click();

    // Step 1 should show with Health selected
    await expect(
      page.locator("h2:has-text('Choose your sector')")
    ).toBeVisible();

    // Health button should still be aria-pressed=true
    const healthBtn = page.locator("button:has-text('Health')").first();
    await expect(healthBtn).toHaveAttribute("aria-pressed", "true");

    await screenshot(page, "onb-14-back-preserves-sector");
  });

  // ── 12. Short handle keeps Claim Agent disabled ───────────────────────────

  test("ONB-12: Short handle keeps Claim Agent disabled", async ({ page }) => {
    await loginViaUI(page);
    await page.goto("/claim");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);

    // Navigate to step 3
    await page.locator("button:has-text('Business')").first().click();
    await page.locator("button:has-text('Continue')").click();
    await page.waitForSelector("button[aria-pressed]", { timeout: 10_000 });
    await page.locator("button[aria-pressed]").first().click();
    await page.locator("button:has-text('Continue')").click();

    await page.waitForSelector("input#handle", { timeout: 5_000 });

    // Type too-short handle (2 chars — below 3 minimum)
    await page.locator("input#handle").fill("ab");

    // Helper text should show char requirement
    await expect(
      page.locator("text=3–30 characters, letters, numbers, hyphens")
    ).toBeVisible();

    // Claim Agent should be disabled
    await expect(page.locator("button:has-text('Claim Agent')")).toBeDisabled();

    await screenshot(page, "onb-15-short-handle-disabled");
  });

  // ── 13. API: GET /api/v1/onboarding/sectors ───────────────────────────────

  test("ONB-13: API sectors endpoint returns 8 sectors", async ({ page }) => {
    const resp = await page.request.get("/api/v1/onboarding/sectors");
    expect(resp.status()).toBe(200);
    const data = await resp.json();
    expect(data.count).toBe(8);
    expect(data.sectors.length).toBe(8);

    const names = data.sectors.map((s: { name: string }) => s.name);
    expect(names).toContain("Personal");
    expect(names).toContain("Business");
    expect(names).toContain("Gaming");
    expect(names).toContain("Health");
  });

  // ── 14. API: GET /api/v1/onboarding/check-handle ─────────────────────────

  test("ONB-14: API check-handle returns correct availability", async ({
    page,
  }) => {
    // Fresh handle → available
    const freshHandle = `e2e-check-${Date.now()}`;
    const freshResp = await page.request.get(
      `/api/v1/onboarding/check-handle/${freshHandle}`
    );
    expect(freshResp.status()).toBe(200);
    const fresh = await freshResp.json();
    expect(fresh.available).toBe(true);
    expect(fresh.handle).toBe(freshHandle);

    // Invalid handle → not available + reason
    const invalidResp = await page.request.get(
      "/api/v1/onboarding/check-handle/INVALID_HANDLE"
    );
    expect(invalidResp.status()).toBe(200);
    const invalid = await invalidResp.json();
    expect(invalid.available).toBe(false);
    expect(invalid.reason).toBeTruthy();
  });

  // ── 15. Progress bar updates as user advances ─────────────────────────────

  test("ONB-15: Progress bar reflects current step", async ({ page }) => {
    await loginViaUI(page);
    await page.goto("/claim");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);

    // Step 1: progress bar at ~33%
    const progressBar = page.locator("[role='progressbar']");
    await expect(progressBar).toBeVisible();
    const step1Value = await progressBar.getAttribute("aria-valuenow");
    expect(Number(step1Value)).toBeCloseTo(33, -1); // ~33%

    // Advance to step 2
    await page.locator("button:has-text('Business')").first().click();
    await page.locator("button:has-text('Continue')").click();
    await page.waitForSelector("button[aria-pressed]", { timeout: 10_000 });

    // Progress should be ~67%
    const step2Value = await progressBar.getAttribute("aria-valuenow");
    expect(Number(step2Value)).toBeCloseTo(67, -1); // ~67%

    await screenshot(page, "onb-16-progress-bar-step2");
  });
});

// ---------------------------------------------------------------------------
// Suite: Mobile viewport
// ---------------------------------------------------------------------------

test.describe("ONB-M: Mobile Viewport (390×844)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("ONB-M01: Claim wizard renders correctly on mobile", async ({
    page,
  }) => {
    // Register mobile user
    const mobileEmail = `e2e_ob_mobile_${UNIQUE}@dingdawg.com`;
    try {
      await page.request.post("/auth/register", {
        data: { email: mobileEmail, password: TEST_PASSWORD },
      });
    } catch {
      // User may already exist from a previous run
    }

    await page.goto("/login");
    await page.fill("input[type='email'], input[name='email']", mobileEmail);
    await page.fill("input[type='password']", TEST_PASSWORD);
    await page
      .locator(
        "button[type='submit'], button:has-text('Log in'), button:has-text('Sign in')"
      )
      .first()
      .click();
    await page.waitForURL(/\/(dashboard|claim|chat)/, { timeout: 15_000 });

    await page.goto("/claim");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);

    // Header visible on mobile
    await expect(
      page.locator("h1:has-text('Claim Your Agent')")
    ).toBeVisible();

    // Sector grid visible (2-column on mobile)
    const sectorButtons = page.locator("button[aria-pressed]");
    const count = await sectorButtons.count();
    expect(count).toBeGreaterThanOrEqual(8);

    // All buttons should be visible (not cut off)
    await expect(
      page.locator("button:has-text('Gaming')")
    ).toBeVisible();

    await screenshot(page, "onb-m01-mobile-sector-grid");
  });

  test("ONB-M02: Touch targets are at least 44px tall on mobile", async ({
    page,
  }) => {
    const mobileEmail = `e2e_ob_mobile_${UNIQUE}@dingdawg.com`;
    await page.goto("/login");
    await page.fill("input[type='email'], input[name='email']", mobileEmail);
    await page.fill("input[type='password']", TEST_PASSWORD);
    await page
      .locator(
        "button[type='submit'], button:has-text('Log in'), button:has-text('Sign in')"
      )
      .first()
      .click();
    await page.waitForURL(/\/(dashboard|claim|chat)/, { timeout: 15_000 });

    await page.goto("/claim");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);

    // Check that the first sector button has at least 44px height
    const firstSector = page.locator("button[aria-pressed]").first();
    await expect(firstSector).toBeVisible();
    const box = await firstSector.boundingBox();
    expect(box).toBeTruthy();
    if (box) {
      expect(box.height).toBeGreaterThanOrEqual(44);
    }

    await screenshot(page, "onb-m02-touch-targets-verified");
  });
});
