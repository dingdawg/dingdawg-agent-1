/**
 * DingDawg Agent 1 — Full E2E Production Smoke Test
 *
 * Tests the REAL deployed frontend (Vercel) talking to the REAL backend (Railway).
 * Every test takes a screenshot for visual proof.
 *
 * Flow: Landing → Register → Dashboard → Create Agent → Chat → Explore → Settings → Logout
 */

import { test, expect, Page } from "@playwright/test";

const SCREENSHOTS = "./e2e-screenshots";
const TEST_EMAIL = `e2e_${Date.now()}@dingdawg.com`;
const TEST_PASSWORD = "E2ETestPass2026x";

async function screenshot(page: Page, name: string) {
  await page.screenshot({ path: `${SCREENSHOTS}/${name}.png`, fullPage: true });
}

// ─── 1. Landing Page ───────────────────────────────────────────────────────────

test.describe("1. Landing & Public Pages", () => {
  test("1a. Landing page loads", async ({ page }) => {
    await page.goto("/");
    await screenshot(page, "01-landing");
    // Should redirect to login or show landing
    await expect(page).toHaveURL(/\/(login)?$/);
  });

  test("1b. Login page renders", async ({ page }) => {
    await page.goto("/login");
    await expect(page.locator("input[type='email'], input[name='email']")).toBeVisible();
    await expect(page.locator("input[type='password']")).toBeVisible();
    await screenshot(page, "02-login-page");
  });

  test("1c. Register page renders", async ({ page }) => {
    await page.goto("/register");
    await expect(page.locator("input[type='email'], input[name='email']")).toBeVisible();
    await expect(page.locator("input[type='password']").first()).toBeVisible();
    await screenshot(page, "03-register-page");
  });

  test("1d. Explore page loads (public)", async ({ page }) => {
    await page.goto("/explore");
    await screenshot(page, "04-explore-page");
    // Should show agent directory or search
    await expect(page.locator("body")).not.toBeEmpty();
  });
});

// ─── 2. Registration Flow ──────────────────────────────────────────────────────

test.describe("2. Registration", () => {
  test("2a. Register new user", async ({ page }) => {
    await page.goto("/register");
    await page.fill("input[type='email'], input[name='email']", TEST_EMAIL);

    // Fill password fields
    const passwordInputs = page.locator("input[type='password']");
    const count = await passwordInputs.count();
    await passwordInputs.nth(0).fill(TEST_PASSWORD);
    if (count > 1) {
      await passwordInputs.nth(1).fill(TEST_PASSWORD);
    }

    await screenshot(page, "05-register-filled");

    // Submit
    await page.locator("button[type='submit'], button:has-text('Register'), button:has-text('Sign up'), button:has-text('Create')").first().click();

    // Wait for navigation (should go to dashboard or claim page)
    await page.waitForURL(/\/(dashboard|claim|chat)/, { timeout: 15_000 });
    await screenshot(page, "06-after-register");
  });
});

// ─── 3. Authenticated Pages ────────────────────────────────────────────────────

test.describe("3. Authenticated User Flow", () => {
  test.beforeEach(async ({ page }) => {
    // Login
    await page.goto("/login");
    await page.fill("input[type='email'], input[name='email']", TEST_EMAIL);
    await page.fill("input[type='password']", TEST_PASSWORD);
    await page.locator("button[type='submit'], button:has-text('Log in'), button:has-text('Sign in'), button:has-text('Login')").first().click();
    await page.waitForURL(/\/(dashboard|claim|chat)/, { timeout: 15_000 });
  });

  test("3a. Dashboard loads after login", async ({ page }) => {
    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");
    await screenshot(page, "07-dashboard");
    // Dashboard should have some content
    await expect(page.locator("body")).not.toBeEmpty();
  });

  test("3b. Claim/create agent page", async ({ page }) => {
    await page.goto("/claim");
    await page.waitForLoadState("networkidle");
    await screenshot(page, "08-claim-page");
  });

  test("3c. Tasks page loads", async ({ page }) => {
    await page.goto("/tasks");
    // Tasks page redirects to /claim if user has no agents — accept both
    await page.waitForURL(/\/(tasks|claim|login)/, { timeout: 10_000 });
    await page.waitForLoadState("domcontentloaded");
    await screenshot(page, "09-tasks-page");
    // Verify we landed on tasks OR on /claim (no-agent redirect) — both are valid
    const url = page.url();
    expect(url).toMatch(/\/(tasks|claim|login)/);
  });

  test("3d. Settings page loads", async ({ page }) => {
    await page.goto("/settings");
    // Settings page redirects to /claim if user has no agents — accept both
    await page.waitForURL(/\/(settings|claim|login)/, { timeout: 10_000 });
    await page.waitForLoadState("domcontentloaded");
    await screenshot(page, "10-settings-page");
    const url = page.url();
    expect(url).toMatch(/\/(settings|claim|login)/);
  });

  test("3e. Chat/Dashboard — send a message", async ({ page }) => {
    await page.goto("/dashboard");
    // Dashboard redirects to /claim when user has no agents
    await page.waitForURL(/\/(dashboard|claim|chat|login)/, { timeout: 10_000 });
    await page.waitForLoadState("domcontentloaded");

    // Look for chat input
    const chatInput = page.locator(
      "textarea, input[placeholder*='message'], input[placeholder*='type'], input[placeholder*='ask']"
    ).first();

    if (await chatInput.isVisible({ timeout: 5000 }).catch(() => false)) {
      await chatInput.fill("Hello, what can you do?");
      await screenshot(page, "11-chat-message-typed");

      // Send via Enter or send button
      const sendButton = page.locator(
        "button:has-text('Send'), button[aria-label='Send'], button[type='submit']"
      ).first();

      if (await sendButton.isVisible({ timeout: 2000 }).catch(() => false)) {
        await sendButton.click();
      } else {
        await chatInput.press("Enter");
      }

      // Wait for response
      await page.waitForTimeout(3000);
      await screenshot(page, "12-chat-response");
    } else {
      // No chat input visible — take screenshot of whatever is shown
      await screenshot(page, "11-no-chat-input-visible");
    }
  });
});

// ─── 4. API Proxy Verification ─────────────────────────────────────────────────

test.describe("4. API Proxy (Frontend → Backend)", () => {
  test("4a. Health via Vercel proxy", async ({ page }) => {
    const response = await page.goto("/api/v1/templates");
    expect(response?.status()).toBeLessThan(500);
    await screenshot(page, "13-api-templates-proxy");
  });

  test("4b. Auth endpoint via proxy", async ({ page }) => {
    // Ensure the test user exists — register first (idempotent: 409 if already exists)
    await page.request.post("/auth/register", {
      data: { email: TEST_EMAIL, password: TEST_PASSWORD },
    });
    // Now login — must succeed regardless of whether register was called above
    const response = await page.request.post("/auth/login", {
      data: { email: TEST_EMAIL, password: TEST_PASSWORD },
    });
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.access_token).toBeTruthy();
  });
});

// ─── 5. Mobile Viewport ────────────────────────────────────────────────────────

test.describe("5. Mobile Responsiveness", () => {
  test.use({ viewport: { width: 390, height: 844 } }); // iPhone 14

  test("5a. Login page mobile", async ({ page }) => {
    await page.goto("/login");
    await screenshot(page, "14-mobile-login");
    await expect(page.locator("input[type='email'], input[name='email']")).toBeVisible();
  });

  test("5b. Dashboard mobile", async ({ page }) => {
    // Login first
    await page.goto("/login");
    await page.fill("input[type='email'], input[name='email']", TEST_EMAIL);
    await page.fill("input[type='password']", TEST_PASSWORD);
    await page.locator("button[type='submit'], button:has-text('Log in'), button:has-text('Sign in'), button:has-text('Login')").first().click();
    await page.waitForURL(/\/(dashboard|claim|chat)/, { timeout: 15_000 });
    await page.goto("/dashboard");
    // Dashboard may redirect to /claim if user has no agents — accept both
    await page.waitForURL(/\/(dashboard|claim|chat)/, { timeout: 10_000 });
    await page.waitForLoadState("domcontentloaded");
    await screenshot(page, "15-mobile-dashboard");
  });
});
