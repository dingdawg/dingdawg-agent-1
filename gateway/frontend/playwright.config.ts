import { defineConfig } from "@playwright/test";

/**
 * Playwright configuration for DingDawg Agent 1 frontend E2E tests.
 *
 * Two project targets:
 *
 *   production  — targets the live Vercel deployment.
 *                 Run with: npx playwright test --project=production
 *
 *   local       — targets a locally running Next.js dev server.
 *                 Required for visual-regression.spec.ts (toHaveScreenshot).
 *                 Run with: npx playwright test --project=local
 *
 *   mobile      — local target at 375×812 viewport (iPhone-class).
 *
 * Visual regression snapshots are stored in:
 *   e2e/visual-regression.spec.ts-snapshots/
 *
 * To update all baselines:
 *   npx playwright test e2e/visual-regression.spec.ts --project=local --update-snapshots
 *
 * IMPORTANT: visual-regression.spec.ts MUST run against the local project.
 * Running it against production will fail because snapshot pixel counts differ
 * between network-dependent timing and local rendering.
 */

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: {
    timeout: 12_000,
    // Default threshold for toHaveScreenshot: 2% pixel diff tolerance.
    toHaveScreenshot: { maxDiffPixelRatio: 0.02 },
  },
  fullyParallel: false,
  retries: 1,
  reporter: [["list"], ["html", { open: "never" }]],

  // Snapshot directory for toHaveScreenshot baselines.
  // Snapshots are stored alongside the spec file (default Playwright behavior).
  // snapshotDir is not overridden so Playwright uses its default:
  //   <spec-file-name>-snapshots/<project-name>/<platform>/
  snapshotPathTemplate:
    "{testDir}/{testFilePath}-snapshots/{testName}-{projectName}-{platform}.png",

  projects: [
    // ── Production target (existing tests, smoke checks) ──────────────────
    {
      name: "production",
      use: {
        browserName: "chromium",
        baseURL: "https://app.dingdawg.com",
        screenshot: "on",
        trace: "on-first-retry",
        headless: true,
        viewport: { width: 1280, height: 720 },
      },
    },

    // ── Marketing site target (dingdawg.com — public storefront) ──────────
    // Run: npx playwright test --project=marketing
    {
      name: "marketing",
      use: {
        browserName: "chromium",
        baseURL: "https://dingdawg.com",
        screenshot: "on",
        trace: "on-first-retry",
        headless: true,
        viewport: { width: 1280, height: 720 },
      },
      // Only run the marketing-site spec under this project
      testMatch: "**/dingdawg-marketing-site.spec.ts",
    },

    // ── Marketing site — mobile ────────────────────────────────────────────
    {
      name: "marketing-mobile",
      use: {
        browserName: "chromium",
        baseURL: "https://dingdawg.com",
        screenshot: "on",
        trace: "on-first-retry",
        headless: true,
        viewport: { width: 390, height: 844 },
        hasTouch: true,
        isMobile: true,
        userAgent:
          "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) " +
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
      },
      testMatch: "**/dingdawg-marketing-site.spec.ts",
    },

    // ── Local dev server target (visual regression + new smoke tests) ─────
    {
      name: "local",
      use: {
        browserName: "chromium",
        baseURL: "http://localhost:3000",
        screenshot: "only-on-failure",
        trace: "on-first-retry",
        headless: true,
        viewport: { width: 1280, height: 720 },
      },
    },

    // ── Mobile local (375×812 — iPhone-class) ─────────────────────────────
    {
      name: "mobile-local",
      use: {
        browserName: "chromium",
        baseURL: "http://localhost:3000",
        screenshot: "only-on-failure",
        trace: "on-first-retry",
        headless: true,
        viewport: { width: 375, height: 812 },
        // Simulate mobile touch + UA
        hasTouch: true,
        isMobile: true,
        userAgent:
          "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) " +
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
      },
    },
  ],

  // Keep the original outputDir for artifact screenshots.
  outputDir: "./e2e-screenshots",
});
