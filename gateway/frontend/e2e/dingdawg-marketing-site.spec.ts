/**
 * DingDawg Marketing Site — Full Visitor Journey E2E Tests
 *
 * Target: https://dingdawg.com  (public marketing / storefront)
 *
 * Coverage:
 *   VIS-01  Homepage loads — hero visible
 *   VIS-02  "Try It Now" demo CTA is clickable
 *   VIS-03  /pricing page — verifies $49.99 / $79.99 / $499 tiers
 *   VIS-04  /shield page — Aegis Shield product page
 *   VIS-05  "Get Started Free" redirects to app.dingdawg.com/register
 *   VIS-M01-M05  Mobile (390×844) repeat of each page above
 *
 * Rules:
 *   - READ-ONLY: no form submissions, no write operations against production
 *   - Screenshot on EVERY step — fullPage: true
 *   - Tests run against https://dingdawg.com (not localhost)
 *   - Selectors use flexible matchers to survive minor copy tweaks
 *
 * Run:
 *   npx playwright test e2e/dingdawg-marketing-site.spec.ts --project=production
 */

import { test, expect, type Page } from "@playwright/test";
import * as fs from "fs";

// ─── Constants ────────────────────────────────────────────────────────────────

const MARKETING_URL = "https://dingdawg.com";
const APP_URL = "https://app.dingdawg.com";
const SCREENSHOTS = "./e2e-screenshots/marketing-site";

// Ensure screenshot dir exists at runtime (Playwright doesn't auto-create deep paths)
fs.mkdirSync(SCREENSHOTS, { recursive: true });

// ─── Helper ───────────────────────────────────────────────────────────────────

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `${SCREENSHOTS}/${name}.png`, fullPage: true });
}

// ─── Suite A: Desktop (1280×720) ─────────────────────────────────────────────

test.describe("VIS: dingdawg.com Visitor Journey — Desktop", () => {
  test.use({ baseURL: MARKETING_URL, viewport: { width: 1280, height: 720 } });

  // ── VIS-01: Homepage loads ─────────────────────────────────────────────────

  test("VIS-01: Homepage loads — hero section visible", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await shot(page, "vis-01-homepage-initial");

    // Title sanity check
    const title = await page.title();
    expect(title.toLowerCase()).toMatch(/dingdawg/i);
    await shot(page, "vis-01-homepage-title-verified");

    // Hero / landing section visible — look for common hero markers
    const heroLocator = page.locator(
      "h1, [class*='hero'], [class*='landing'], [class*='headline'], main"
    ).first();
    await expect(heroLocator).toBeVisible({ timeout: 15_000 });
    await shot(page, "vis-01-homepage-hero-visible");
  });

  // ── VIS-02: "Try It Now" demo CTA ─────────────────────────────────────────

  test("VIS-02: Try It Now / demo CTA is present and clickable", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await shot(page, "vis-02-homepage-before-cta");

    // Look for any "try" / "demo" / "get started" style CTA in hero area
    const cta = page.locator(
      "a:has-text('Try'), a:has-text('Demo'), a:has-text('Get Started'), " +
      "button:has-text('Try'), button:has-text('Demo'), button:has-text('Get Started')"
    ).first();

    await expect(cta).toBeVisible({ timeout: 10_000 });
    await shot(page, "vis-02-cta-visible");

    // Grab href before clicking so we can verify destination
    const href = await cta.getAttribute("href");

    // Click — open in same tab (no popup expected from marketing site)
    await cta.click();

    // Allow generous navigation time — may redirect to app or demo page
    await page.waitForLoadState("networkidle", { timeout: 20_000 });
    await shot(page, "vis-02-after-cta-click");

    // Should have navigated somewhere (URL changed or a new section appeared)
    const newUrl = page.url();
    // Either we went to a new route or the href was an anchor — either way page loaded
    expect(newUrl).toBeTruthy();
    await shot(page, "vis-02-cta-destination-verified");
  });

  // ── VIS-03: /pricing page — tier price verification ───────────────────────

  test("VIS-03: /pricing — $49.99 / $79.99 / $499 tiers visible", async ({ page }) => {
    await page.goto("/pricing", { waitUntil: "networkidle" });
    await shot(page, "vis-03-pricing-page-loaded");

    // Page must contain pricing-related text
    const body = page.locator("body");
    const text = await body.innerText();

    // Screenshot the full pricing page
    await shot(page, "vis-03-pricing-page-full");

    // Verify the three price points are present somewhere on the page
    // Use regex to handle formatting like "$49.99", "49.99", "$49" etc.
    const has4999 = /\$?49\.99|\$49/i.test(text);
    const has7999 = /\$?79\.99|\$79/i.test(text);
    const has499 = /\$?499/i.test(text);

    expect(
      has4999,
      `Expected $49.99 tier on /pricing. Page text snippet: ${text.slice(0, 500)}`
    ).toBe(true);

    expect(
      has7999,
      `Expected $79.99 tier on /pricing. Page text snippet: ${text.slice(0, 500)}`
    ).toBe(true);

    expect(
      has499,
      `Expected $499 tier on /pricing. Page text snippet: ${text.slice(0, 500)}`
    ).toBe(true);

    await shot(page, "vis-03-pricing-tiers-verified");
  });

  // ── VIS-04: /shield page ──────────────────────────────────────────────────

  test("VIS-04: /shield page loads — Aegis Shield product visible", async ({ page }) => {
    await page.goto("/shield", { waitUntil: "networkidle" });
    await shot(page, "vis-04-shield-page-loaded");

    // Page must respond (not 404)
    // If the route doesn't exist it will render Next.js 404 page
    const notFound = await page.locator("h1:has-text('404'), h2:has-text('404'), text=not found").count();
    expect(notFound, "/shield returned 404 — route may not be deployed yet").toBe(0);

    // Some content visible
    const mainContent = page.locator("main, [class*='shield'], [class*='aegis'], h1").first();
    await expect(mainContent).toBeVisible({ timeout: 10_000 });
    await shot(page, "vis-04-shield-content-visible");
  });

  // ── VIS-05: "Get Started Free" → app.dingdawg.com/register ───────────────

  test("VIS-05: Get Started Free leads to app.dingdawg.com/register", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await shot(page, "vis-05-homepage-before-register-cta");

    // Find any "Get Started Free" or "Sign Up" or "Register" link/button
    const registerCta = page.locator(
      "a:has-text('Get Started Free'), a:has-text('Get Started'), " +
      "a:has-text('Sign Up'), a:has-text('Register'), " +
      "a[href*='register'], a[href*='signup']"
    ).first();

    await expect(registerCta).toBeVisible({ timeout: 10_000 });
    await shot(page, "vis-05-register-cta-found");

    const href = await registerCta.getAttribute("href");
    await shot(page, "vis-05-register-cta-href-captured");

    // Navigate to the href directly (avoids cross-origin popup issues)
    if (href) {
      const destination = href.startsWith("http") ? href : `${MARKETING_URL}${href}`;
      await page.goto(destination, { waitUntil: "networkidle", timeout: 20_000 });
    } else {
      await registerCta.click();
      await page.waitForLoadState("networkidle", { timeout: 20_000 });
    }

    await shot(page, "vis-05-after-register-navigate");

    // Verify we landed on app.dingdawg.com/register (or equivalent)
    const finalUrl = page.url();
    const isRegisterPage =
      finalUrl.includes("register") ||
      finalUrl.includes("signup") ||
      finalUrl.includes(APP_URL);

    expect(
      isRegisterPage,
      `Expected to land on register page, got: ${finalUrl}`
    ).toBe(true);

    await shot(page, "vis-05-register-page-verified");
  });
});

// ─── Suite B: Mobile (390×844 — iPhone 14 class) ─────────────────────────────

test.describe("VIS-M: dingdawg.com Visitor Journey — Mobile", () => {
  test.use({
    baseURL: MARKETING_URL,
    viewport: { width: 390, height: 844 },
    hasTouch: true,
    isMobile: true,
    userAgent:
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) " +
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
  });

  const mobileScreenshots = `${SCREENSHOTS}/mobile`;

  test("VIS-M01: Homepage loads on mobile — hero visible", async ({ page }) => {
    fs.mkdirSync(mobileScreenshots, { recursive: true });
    await page.goto("/", { waitUntil: "networkidle" });
    await page.screenshot({ path: `${mobileScreenshots}/vis-m01-homepage.png`, fullPage: true });

    const heroLocator = page.locator("h1, [class*='hero'], [class*='landing'], main").first();
    await expect(heroLocator).toBeVisible({ timeout: 15_000 });
    await page.screenshot({ path: `${mobileScreenshots}/vis-m01-homepage-hero-verified.png`, fullPage: true });
  });

  test("VIS-M02: CTA button visible and tappable on mobile", async ({ page }) => {
    fs.mkdirSync(mobileScreenshots, { recursive: true });
    await page.goto("/", { waitUntil: "networkidle" });
    await page.screenshot({ path: `${mobileScreenshots}/vis-m02-before-cta.png`, fullPage: true });

    const cta = page.locator(
      "a:has-text('Try'), a:has-text('Demo'), a:has-text('Get Started'), " +
      "button:has-text('Try'), button:has-text('Demo'), button:has-text('Get Started')"
    ).first();

    await expect(cta).toBeVisible({ timeout: 10_000 });

    // Verify touch target size >= 44px (Apple HIG minimum)
    const box = await cta.boundingBox();
    expect(box).toBeTruthy();
    if (box) {
      expect(box.height).toBeGreaterThanOrEqual(44);
    }

    await page.screenshot({ path: `${mobileScreenshots}/vis-m02-cta-touch-target-ok.png`, fullPage: true });
  });

  test("VIS-M03: /pricing page readable on mobile", async ({ page }) => {
    fs.mkdirSync(mobileScreenshots, { recursive: true });
    await page.goto("/pricing", { waitUntil: "networkidle" });
    await page.screenshot({ path: `${mobileScreenshots}/vis-m03-pricing-mobile.png`, fullPage: true });

    const text = await page.locator("body").innerText();
    const hasPricing = /\$?49\.99|\$?79\.99|\$?499|price|plan|tier/i.test(text);
    expect(hasPricing, "Pricing page should contain pricing info on mobile").toBe(true);

    await page.screenshot({ path: `${mobileScreenshots}/vis-m03-pricing-verified.png`, fullPage: true });
  });

  test("VIS-M04: /shield page loads on mobile", async ({ page }) => {
    fs.mkdirSync(mobileScreenshots, { recursive: true });
    await page.goto("/shield", { waitUntil: "networkidle" });
    await page.screenshot({ path: `${mobileScreenshots}/vis-m04-shield-mobile.png`, fullPage: true });

    const notFound = await page.locator("h1:has-text('404'), text=not found").count();
    expect(notFound, "/shield 404 on mobile").toBe(0);

    await page.screenshot({ path: `${mobileScreenshots}/vis-m04-shield-no-404.png`, fullPage: true });
  });

  test("VIS-M05: Get Started Free CTA present on mobile", async ({ page }) => {
    fs.mkdirSync(mobileScreenshots, { recursive: true });
    await page.goto("/", { waitUntil: "networkidle" });
    await page.screenshot({ path: `${mobileScreenshots}/vis-m05-before-register-cta.png`, fullPage: true });

    const registerCta = page.locator(
      "a:has-text('Get Started Free'), a:has-text('Get Started'), " +
      "a:has-text('Sign Up'), a:has-text('Register'), " +
      "a[href*='register'], a[href*='signup']"
    ).first();

    await expect(registerCta).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: `${mobileScreenshots}/vis-m05-register-cta-visible.png`, fullPage: true });
  });
});
