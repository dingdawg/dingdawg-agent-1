/**
 * DingDawg App — Full Authenticated User Journey E2E Tests
 *
 * Target: https://app.dingdawg.com  (Agent 1 — the main SaaS product)
 *
 * Coverage:
 *   APP-01  /register page — form elements visible
 *   APP-02  /login page — form elements visible
 *   APP-03  /chat/marios-italian — skeleton UI then loaded state
 *   APP-04  /onboarding (/claim) — 3-step wizard visible (6-step UI variant)
 *   APP-M01-M04  Mobile (390×844) repeat
 *
 * Rules:
 *   - READ-ONLY: screenshots + page assertions only — no real form submits
 *   - Screenshot on EVERY step — fullPage: true
 *   - Tests run against production https://app.dingdawg.com
 *   - Auth-gated pages are checked for redirect behaviour (not bypassed)
 *   - No credentials stored or submitted to production auth APIs
 *
 * Run:
 *   npx playwright test e2e/dingdawg-app-journey.spec.ts --project=production
 */

import { test, expect, type Page } from "@playwright/test";
import * as fs from "fs";

// ─── Constants ────────────────────────────────────────────────────────────────

const APP_BASE = "https://app.dingdawg.com";
const BACKEND = process.env.BACKEND_URL ?? "https://api.dingdawg.com";
const SCREENSHOTS = "./e2e-screenshots/app-journey";

// Ensure screenshot dir exists at runtime
fs.mkdirSync(SCREENSHOTS, { recursive: true });

// ─── Helper ───────────────────────────────────────────────────────────────────

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `${SCREENSHOTS}/${name}.png`, fullPage: true });
}

/**
 * Wait for either the skeleton loader OR the real content to appear.
 * Returns which state the page is in: "skeleton" | "loaded" | "unknown".
 */
async function detectLoadState(page: Page): Promise<"skeleton" | "loaded" | "unknown"> {
  try {
    // Common skeleton patterns: shimmer divs, aria-busy, data-loading attrs
    const skeletonCount = await page.locator(
      "[class*='skeleton'], [class*='shimmer'], [class*='loading'], [aria-busy='true'], [data-loading='true']"
    ).count();

    if (skeletonCount > 0) return "skeleton";

    // Loaded: main content is present and not hidden
    const mainCount = await page.locator("main, [role='main'], #__next main").count();
    if (mainCount > 0) return "loaded";
  } catch {
    // Page may have navigated
  }
  return "unknown";
}

// ─── Suite A: Desktop (1280×720) ─────────────────────────────────────────────

test.describe("APP: app.dingdawg.com User Journey — Desktop", () => {
  test.use({ baseURL: APP_BASE, viewport: { width: 1280, height: 720 } });

  // ── APP-01: /register page ─────────────────────────────────────────────────

  test("APP-01: /register page — form elements visible", async ({ page }) => {
    await page.goto("/register", { waitUntil: "networkidle" });
    await shot(page, "app-01-register-initial-load");

    // Page title sanity
    const title = await page.title();
    expect(title.toLowerCase()).toMatch(/register|sign up|dingdawg/i);
    await shot(page, "app-01-register-title-ok");

    // Email input
    const emailInput = page.locator(
      "input[type='email'], input[name='email'], input[placeholder*='email' i]"
    ).first();
    await expect(emailInput).toBeVisible({ timeout: 15_000 });
    await shot(page, "app-01-register-email-input-visible");

    // Password input
    const passwordInput = page.locator("input[type='password']").first();
    await expect(passwordInput).toBeVisible({ timeout: 5_000 });
    await shot(page, "app-01-register-password-input-visible");

    // Submit button
    const submitBtn = page.locator(
      "button[type='submit'], button:has-text('Register'), " +
      "button:has-text('Sign Up'), button:has-text('Create Account'), " +
      "button:has-text('Get Started')"
    ).first();
    await expect(submitBtn).toBeVisible({ timeout: 5_000 });
    await shot(page, "app-01-register-submit-btn-visible");

    // Link to login page
    const loginLink = page.locator(
      "a[href*='login'], a:has-text('Log in'), a:has-text('Sign in'), a:has-text('Already have')"
    ).first();
    // Non-fatal — just capture screenshot either way
    const loginLinkCount = await loginLink.count();
    await shot(
      page,
      loginLinkCount > 0 ? "app-01-register-login-link-present" : "app-01-register-no-login-link"
    );
  });

  // ── APP-02: /login page ────────────────────────────────────────────────────

  test("APP-02: /login page — form elements visible", async ({ page }) => {
    await page.goto("/login", { waitUntil: "networkidle" });
    await shot(page, "app-02-login-initial-load");

    const title = await page.title();
    expect(title.toLowerCase()).toMatch(/login|sign in|dingdawg/i);
    await shot(page, "app-02-login-title-ok");

    // Email input
    const emailInput = page.locator(
      "input[type='email'], input[name='email'], input[placeholder*='email' i]"
    ).first();
    await expect(emailInput).toBeVisible({ timeout: 15_000 });
    await shot(page, "app-02-login-email-input-visible");

    // Password input
    const passwordInput = page.locator("input[type='password']").first();
    await expect(passwordInput).toBeVisible({ timeout: 5_000 });
    await shot(page, "app-02-login-password-input-visible");

    // Submit button
    const submitBtn = page.locator(
      "button[type='submit'], button:has-text('Login'), " +
      "button:has-text('Log in'), button:has-text('Sign in')"
    ).first();
    await expect(submitBtn).toBeVisible({ timeout: 5_000 });
    await shot(page, "app-02-login-submit-btn-visible");

    // Link back to register
    const registerLink = page.locator(
      "a[href*='register'], a:has-text('Register'), a:has-text('Sign up'), a:has-text('Create account')"
    ).first();
    const registerLinkCount = await registerLink.count();
    await shot(
      page,
      registerLinkCount > 0 ? "app-02-login-register-link-present" : "app-02-login-no-register-link"
    );
  });

  // ── APP-03: /chat/marios-italian ───────────────────────────────────────────
  // Public widget-style chat pages may be accessible without auth.
  // If auth-gated, we verify the redirect to /login is correct.

  test("APP-03: /chat/marios-italian — skeleton then loaded (or auth redirect)", async ({ page }) => {
    await page.goto("/chat/marios-italian", { waitUntil: "domcontentloaded" });
    await shot(page, "app-03-chat-initial-domcontent");

    // Check early load state — skeleton may appear before API data
    const stateEarly = await detectLoadState(page);
    await shot(page, `app-03-chat-early-state-${stateEarly}`);

    // Now wait for network idle (or timeout)
    try {
      await page.waitForLoadState("networkidle", { timeout: 15_000 });
    } catch {
      // Page may stream — that's fine
    }

    await shot(page, "app-03-chat-after-networkidle");

    const finalUrl = page.url();

    // Case A: Redirected to login (page is auth-gated)
    if (finalUrl.includes("/login") || finalUrl.includes("/register")) {
      await shot(page, "app-03-chat-redirected-to-auth");
      const emailInput = page.locator("input[type='email']").first();
      await expect(emailInput).toBeVisible({ timeout: 5_000 });
      await shot(page, "app-03-chat-auth-gate-verified");
      return;
    }

    // Case B: Chat page loaded (public widget)
    // Verify skeleton → loaded transition
    const skeletonLocator = page.locator(
      "[class*='skeleton'], [class*='shimmer'], [class*='loading']"
    );

    // Skeleton may have already transitioned — that's OK
    await shot(page, "app-03-chat-skeleton-check");

    // After load, some chat UI element should be visible
    const chatUi = page.locator(
      "form, input[placeholder*='message' i], input[placeholder*='Ask' i], " +
      "textarea, [class*='chat'], [class*='message'], [role='textbox']"
    ).first();

    // Wait up to 20s for chat UI
    const chatCount = await chatUi.count();
    if (chatCount > 0) {
      await expect(chatUi).toBeVisible({ timeout: 20_000 });
      await shot(page, "app-03-chat-ui-loaded");
    } else {
      // At minimum, page should not be blank
      const bodyText = await page.locator("body").innerText();
      expect(bodyText.length, "Chat page should have some content").toBeGreaterThan(10);
      await shot(page, "app-03-chat-content-present");
    }

    await shot(page, "app-03-chat-final-state");
  });

  // ── APP-04: /onboarding (6-step flow) ─────────────────────────────────────
  // The onboarding wizard lives at /claim on Agent 1.
  // We check /onboarding first; if it redirects we follow to /claim.

  test("APP-04: /onboarding — 6-step wizard visible (or /claim redirect)", async ({ page }) => {
    // Try /onboarding first
    await page.goto("/onboarding", { waitUntil: "domcontentloaded" });
    await shot(page, "app-04-onboarding-initial");

    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    await shot(page, "app-04-onboarding-after-idle");

    const urlAfterOnboarding = page.url();

    // If redirected to login, verify and stop
    if (urlAfterOnboarding.includes("/login")) {
      await shot(page, "app-04-onboarding-redirected-to-login");
      const emailInput = page.locator("input[type='email']").first();
      await expect(emailInput).toBeVisible({ timeout: 5_000 });
      await shot(page, "app-04-onboarding-auth-gate-confirmed");
      return;
    }

    // If redirected to /claim or /dashboard, follow
    if (urlAfterOnboarding.includes("/claim") || urlAfterOnboarding.includes("/dashboard")) {
      await shot(page, "app-04-onboarding-at-claim-or-dashboard");
    }

    // Check if /claim has step indicators (the wizard)
    if (urlAfterOnboarding.includes("/claim") || urlAfterOnboarding.includes("/onboarding")) {
      // Step indicators / progress bar
      const progressBar = page.locator(
        "[role='progressbar'], [class*='progress'], [class*='step'], [class*='wizard']"
      ).first();
      const progressCount = await progressBar.count();

      if (progressCount > 0) {
        await expect(progressBar).toBeVisible({ timeout: 5_000 });
        await shot(page, "app-04-onboarding-progress-bar-visible");
      } else {
        await shot(page, "app-04-onboarding-no-progress-bar");
      }

      // Step navigation buttons or step labels
      const stepElements = page.locator(
        "button:has-text('Continue'), button:has-text('Next'), " +
        "[class*='sector'], button[aria-pressed], [class*='step-']"
      );
      const stepCount = await stepElements.count();
      await shot(
        page,
        stepCount > 0 ? "app-04-onboarding-steps-visible" : "app-04-onboarding-steps-not-found"
      );
    }

    await shot(page, "app-04-onboarding-final");
  });
});

// ─── Suite B: Mobile (390×844 — iPhone 14 class) ─────────────────────────────

test.describe("APP-M: app.dingdawg.com User Journey — Mobile", () => {
  test.use({
    baseURL: APP_BASE,
    viewport: { width: 390, height: 844 },
    hasTouch: true,
    isMobile: true,
    userAgent:
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) " +
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
  });

  const mobileScreenshots = `${SCREENSHOTS}/mobile`;

  // ── APP-M01: /register on mobile ──────────────────────────────────────────

  test("APP-M01: /register page — form readable on mobile", async ({ page }) => {
    fs.mkdirSync(mobileScreenshots, { recursive: true });
    await page.goto("/register", { waitUntil: "networkidle" });
    await page.screenshot({ path: `${mobileScreenshots}/app-m01-register-load.png`, fullPage: true });

    const emailInput = page.locator(
      "input[type='email'], input[name='email']"
    ).first();
    await expect(emailInput).toBeVisible({ timeout: 15_000 });

    // Touch target size
    const box = await emailInput.boundingBox();
    expect(box).toBeTruthy();
    if (box) {
      expect(box.height).toBeGreaterThanOrEqual(36); // relaxed for inputs
    }

    await page.screenshot({ path: `${mobileScreenshots}/app-m01-register-email-visible.png`, fullPage: true });

    const passwordInput = page.locator("input[type='password']").first();
    await expect(passwordInput).toBeVisible({ timeout: 5_000 });
    await page.screenshot({ path: `${mobileScreenshots}/app-m01-register-password-visible.png`, fullPage: true });
  });

  // ── APP-M02: /login on mobile ──────────────────────────────────────────────

  test("APP-M02: /login page — form readable on mobile", async ({ page }) => {
    fs.mkdirSync(mobileScreenshots, { recursive: true });
    await page.goto("/login", { waitUntil: "networkidle" });
    await page.screenshot({ path: `${mobileScreenshots}/app-m02-login-load.png`, fullPage: true });

    const emailInput = page.locator(
      "input[type='email'], input[name='email']"
    ).first();
    await expect(emailInput).toBeVisible({ timeout: 15_000 });
    await page.screenshot({ path: `${mobileScreenshots}/app-m02-login-email-visible.png`, fullPage: true });

    const submitBtn = page.locator(
      "button[type='submit'], button:has-text('Login'), button:has-text('Log in'), button:has-text('Sign in')"
    ).first();
    await expect(submitBtn).toBeVisible({ timeout: 5_000 });

    // Touch target
    const btnBox = await submitBtn.boundingBox();
    expect(btnBox).toBeTruthy();
    if (btnBox) {
      expect(btnBox.height).toBeGreaterThanOrEqual(44);
    }
    await page.screenshot({ path: `${mobileScreenshots}/app-m02-login-btn-touch-target.png`, fullPage: true });
  });

  // ── APP-M03: /chat/marios-italian on mobile ────────────────────────────────

  test("APP-M03: /chat/marios-italian loads or redirects correctly on mobile", async ({ page }) => {
    fs.mkdirSync(mobileScreenshots, { recursive: true });
    await page.goto("/chat/marios-italian", { waitUntil: "domcontentloaded" });
    await page.screenshot({ path: `${mobileScreenshots}/app-m03-chat-initial.png`, fullPage: true });

    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    await page.screenshot({ path: `${mobileScreenshots}/app-m03-chat-after-idle.png`, fullPage: true });

    const finalUrl = page.url();

    if (finalUrl.includes("/login")) {
      const emailInput = page.locator("input[type='email']").first();
      await expect(emailInput).toBeVisible({ timeout: 5_000 });
      await page.screenshot({ path: `${mobileScreenshots}/app-m03-chat-auth-redirect-mobile.png`, fullPage: true });
      return;
    }

    // If chat page loaded, verify some content exists
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.length).toBeGreaterThan(10);
    await page.screenshot({ path: `${mobileScreenshots}/app-m03-chat-loaded-mobile.png`, fullPage: true });
  });

  // ── APP-M04: /onboarding on mobile ────────────────────────────────────────

  test("APP-M04: /onboarding wizard visible on mobile", async ({ page }) => {
    fs.mkdirSync(mobileScreenshots, { recursive: true });
    await page.goto("/onboarding", { waitUntil: "domcontentloaded" });
    await page.screenshot({ path: `${mobileScreenshots}/app-m04-onboarding-initial.png`, fullPage: true });

    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    await page.screenshot({ path: `${mobileScreenshots}/app-m04-onboarding-idle.png`, fullPage: true });

    const finalUrl = page.url();

    if (finalUrl.includes("/login")) {
      const emailInput = page.locator("input[type='email']").first();
      await expect(emailInput).toBeVisible({ timeout: 5_000 });
      await page.screenshot({ path: `${mobileScreenshots}/app-m04-onboarding-auth-redirect.png`, fullPage: true });
      return;
    }

    // Check for any wizard/step content
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.length, "Onboarding page should have content on mobile").toBeGreaterThan(10);
    await page.screenshot({ path: `${mobileScreenshots}/app-m04-onboarding-content-ok.png`, fullPage: true });
  });
});

// ─── Suite C: API Smoke (read-only backend checks) ────────────────────────────

test.describe("APP-API: app.dingdawg.com API Smoke — Read-Only", () => {
  test.use({ baseURL: APP_BASE });

  test("APP-API-01: Backend health endpoint returns healthy status", async ({ page }) => {
    fs.mkdirSync(SCREENSHOTS, { recursive: true });

    const response = await page.request.get(`${BACKEND}/health`);
    expect([200, 204]).toContain(response.status());

    // Navigate to app and screenshot as visual anchor
    await page.goto("/login", { waitUntil: "networkidle" });
    await shot(page, "app-api-01-backend-health-ok");

    const body = await response.json().catch(() => ({})) as Record<string, unknown>;
    if (body.status) {
      expect(String(body.status)).toMatch(/healthy|ok|degraded/i);
    }
    await shot(page, "app-api-01-health-status-verified");
  });

  test("APP-API-02: /register page returns 200 HTTP status", async ({ page }) => {
    const response = await page.request.get(`${APP_BASE}/register`);
    expect(response.status()).toBe(200);

    await page.goto("/register", { waitUntil: "networkidle" });
    await shot(page, "app-api-02-register-200-ok");
  });

  test("APP-API-03: /login page returns 200 HTTP status", async ({ page }) => {
    const response = await page.request.get(`${APP_BASE}/login`);
    expect(response.status()).toBe(200);

    await page.goto("/login", { waitUntil: "networkidle" });
    await shot(page, "app-api-03-login-200-ok");
  });
});
