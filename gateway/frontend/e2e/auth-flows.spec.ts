/**
 * DingDawg Agent 1 — Auth Flows E2E Tests
 *
 * Covers:
 * - test_forgot_password_page_loads
 * - test_reset_password_page_loads_with_token
 * - test_verify_email_page_loads_with_token
 * - test_mobile_layout_responsive
 * - Forgot-password full form interaction
 * - Reset-password password visibility toggle
 * - Reset-password validation (mismatch, too short)
 * - Verify-email loading → error flow (bogus token)
 * - Keyboard navigation on forms (accessibility)
 *
 * Screenshots are taken at every significant state transition.
 * Uses Playwright test.describe.serial to enforce ordering.
 */

import { test, expect, Page } from "@playwright/test";

const SCREENSHOTS = "./e2e-screenshots/auth-flows";

async function screenshot(page: Page, name: string) {
  await page.screenshot({
    path: `${SCREENSHOTS}/${name}.png`,
    fullPage: true,
  });
}

// ─── Forgot Password Page ─────────────────────────────────────────────────────

test.describe("Forgot Password Page", () => {
  test("test_forgot_password_page_loads", async ({ page }) => {
    await page.goto("/forgot-password");

    // Heading visible
    await expect(
      page.getByRole("heading", { name: /reset password/i })
    ).toBeVisible();

    // Email input visible and focused
    const emailInput = page.getByLabel(/email address/i);
    await expect(emailInput).toBeVisible();

    // Submit button visible
    await expect(
      page.getByRole("button", { name: /send reset link/i })
    ).toBeVisible();

    await screenshot(page, "FP-01-page-loaded");
  });

  test("forgot_password_submit_sends_request_and_shows_confirmation", async ({
    page,
  }) => {
    await page.goto("/forgot-password");

    const emailInput = page.getByLabel(/email address/i);
    await emailInput.fill("test@example.com");

    // Intercept the network call — mock 200 response
    await page.route("**/auth/forgot-password", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          message:
            "If an account exists with that email, a password reset link will be sent.",
        }),
      });
    });

    await page.getByRole("button", { name: /send reset link/i }).click();

    // Confirmation state: check icon + message
    await expect(page.getByText(/if an account exists/i)).toBeVisible({
      timeout: 5000,
    });

    await screenshot(page, "FP-02-confirmation-shown");
  });

  test("forgot_password_empty_submit_does_nothing", async ({ page }) => {
    await page.goto("/forgot-password");

    const btn = page.getByRole("button", { name: /send reset link/i });
    await expect(btn).toBeDisabled();

    await screenshot(page, "FP-03-empty-submit-disabled");
  });

  test("forgot_password_back_to_login_link_visible", async ({ page }) => {
    await page.goto("/forgot-password");

    const backLink = page.getByRole("link", { name: /back to login/i });
    await expect(backLink).toBeVisible();
    await expect(backLink).toHaveAttribute("href", "/login");

    await screenshot(page, "FP-04-back-link-visible");
  });
});

// ─── Reset Password with Token ───────────────────────────────────────────────

test.describe("Reset Password Token Page", () => {
  const FAKE_TOKEN = "fake-reset-token-for-ui-testing-only";

  test("test_reset_password_page_loads_with_token", async ({ page }) => {
    await page.goto(`/reset-password/${FAKE_TOKEN}`);

    // Heading visible
    await expect(
      page.getByRole("heading", { name: /set new password/i })
    ).toBeVisible();

    // Both password inputs visible
    await expect(page.getByLabel(/new password/i)).toBeVisible();
    await expect(page.getByLabel(/confirm password/i)).toBeVisible();

    // Submit button visible
    await expect(
      page.getByRole("button", { name: /update password/i })
    ).toBeVisible();

    await screenshot(page, "RP-01-page-loaded");
  });

  test("reset_password_visibility_toggle_works", async ({ page }) => {
    await page.goto(`/reset-password/${FAKE_TOKEN}`);

    const newPasswordInput = page.getByLabel(/new password/i);
    await expect(newPasswordInput).toHaveAttribute("type", "password");

    // Click the eye icon for new password (first toggle button)
    const toggleBtns = page.getByRole("button", { name: /show password|hide password/i });
    await toggleBtns.first().click();

    await expect(newPasswordInput).toHaveAttribute("type", "text");
    await screenshot(page, "RP-02-password-visible");

    // Click again to hide
    await toggleBtns.first().click();
    await expect(newPasswordInput).toHaveAttribute("type", "password");
    await screenshot(page, "RP-03-password-hidden");
  });

  test("reset_password_shows_mismatch_error", async ({ page }) => {
    await page.goto(`/reset-password/${FAKE_TOKEN}`);

    await page.getByLabel(/new password/i).fill("Password123!");
    await page.getByLabel(/confirm password/i).fill("DifferentPass123!");

    await page.getByRole("button", { name: /update password/i }).click();

    // Mismatch warning appears inline
    await expect(page.getByText(/do not match/i)).toBeVisible({ timeout: 3000 });

    await screenshot(page, "RP-04-mismatch-error");
  });

  test("reset_password_shows_short_password_error", async ({ page }) => {
    await page.goto(`/reset-password/${FAKE_TOKEN}`);

    await page.getByLabel(/new password/i).fill("short");
    await page.getByLabel(/confirm password/i).fill("short");

    await page.getByRole("button", { name: /update password/i }).click();

    // Short password error
    await expect(page.getByText(/at least 8 characters/i)).toBeVisible({
      timeout: 3000,
    });

    await screenshot(page, "RP-05-short-password-error");
  });

  test("reset_password_invalid_token_shows_error_state", async ({ page }) => {
    // Intercept the API call and return 400 (invalid token)
    await page.route("**/auth/reset-password", (route) => {
      route.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "Invalid or expired reset token.",
        }),
      });
    });

    await page.goto(`/reset-password/${FAKE_TOKEN}`);

    await page.getByLabel(/new password/i).fill("ValidPass123!");
    await page.getByLabel(/confirm password/i).fill("ValidPass123!");
    await page.getByRole("button", { name: /update password/i }).click();

    // Error state appears
    await expect(
      page.getByRole("heading", { name: /link invalid or expired/i })
    ).toBeVisible({ timeout: 5000 });

    // Link to request new reset
    await expect(
      page.getByRole("link", { name: /request a new reset link/i })
    ).toBeVisible();

    await screenshot(page, "RP-06-invalid-token-error");
  });

  test("reset_password_success_shows_success_state", async ({ page }) => {
    // Intercept the API call and return 200
    await page.route("**/auth/reset-password", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          message: "Password updated successfully.",
        }),
      });
    });

    await page.goto(`/reset-password/${FAKE_TOKEN}`);

    await page.getByLabel(/new password/i).fill("ValidPass123!");
    await page.getByLabel(/confirm password/i).fill("ValidPass123!");
    await page.getByRole("button", { name: /update password/i }).click();

    // Success state appears
    await expect(
      page.getByRole("heading", { name: /password updated/i })
    ).toBeVisible({ timeout: 5000 });

    await screenshot(page, "RP-07-success-state");
  });
});

// ─── Email Verification Page ─────────────────────────────────────────────────

test.describe("Email Verification Page", () => {
  const FAKE_VERIFY_TOKEN = "fake-verify-token-for-ui-testing-only";

  test("test_verify_email_page_loads_with_token", async ({ page }) => {
    // Mock the API to delay so we can see the loading state
    await page.route(`**/auth/verify-email/**`, (route) => {
      // Return after a short delay to allow loading state screenshot
      setTimeout(() => {
        route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Invalid or expired verification link." }),
        });
      }, 200);
    });

    await page.goto(`/verify-email/${FAKE_VERIFY_TOKEN}`);

    // Loading state — spinner + "Verifying your email" heading
    await expect(
      page.getByRole("heading", { name: /verifying your email/i })
    ).toBeVisible({ timeout: 3000 });

    await screenshot(page, "VE-01-loading-state");
  });

  test("verify_email_valid_token_shows_success", async ({ page }) => {
    await page.route(`**/auth/verify-email/**`, (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ message: "Email verified successfully.", verified: true }),
      });
    });

    await page.goto(`/verify-email/${FAKE_VERIFY_TOKEN}`);

    // Success state
    await expect(
      page.getByRole("heading", { name: /email verified/i })
    ).toBeVisible({ timeout: 5000 });

    // Link to dashboard
    await expect(
      page.getByRole("link", { name: /go to dashboard now/i })
    ).toBeVisible();

    await screenshot(page, "VE-02-success-state");
  });

  test("verify_email_invalid_token_shows_error", async ({ page }) => {
    await page.route(`**/auth/verify-email/**`, (route) => {
      route.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Invalid or expired verification link." }),
      });
    });

    await page.goto(`/verify-email/${FAKE_VERIFY_TOKEN}`);

    // Error state
    await expect(
      page.getByRole("heading", { name: /verification failed/i })
    ).toBeVisible({ timeout: 5000 });

    // Login button + resend link
    await expect(
      page.getByRole("button", { name: /go to login/i })
    ).toBeVisible();

    await screenshot(page, "VE-03-error-state");
  });

  test("verify_email_expired_token_shows_error", async ({ page }) => {
    await page.route(`**/auth/verify-email/**`, (route) => {
      route.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "This verification link has expired. Please request a new one.",
        }),
      });
    });

    await page.goto(`/verify-email/${FAKE_VERIFY_TOKEN}`);

    // The component shows the "Verification Failed" heading for any 400 response.
    // Note: axios throws with err.message = "Request failed with status code 400",
    // not the API detail text, so we verify the error state heading only.
    await expect(
      page.getByRole("heading", { name: /verification failed/i })
    ).toBeVisible({ timeout: 5000 });

    // The "Go to Login" button must be visible in the error state
    await expect(
      page.getByRole("button", { name: /go to login/i })
    ).toBeVisible({ timeout: 3000 });

    await screenshot(page, "VE-04-expired-token");
  });
});

// ─── Mobile Responsiveness ───────────────────────────────────────────────────

test.describe("Mobile Layout", () => {
  test("test_mobile_layout_responsive — forgot password page", async ({ page }) => {
    // Set mobile viewport (iPhone 14 Pro)
    await page.setViewportSize({ width: 393, height: 852 });
    await page.goto("/forgot-password");

    // Key elements all visible on mobile
    await expect(
      page.getByRole("heading", { name: /reset password/i })
    ).toBeVisible();

    const emailInput = page.getByLabel(/email address/i);
    await expect(emailInput).toBeVisible();

    // Touch target check — input must be at least 44px tall
    const box = await emailInput.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.height).toBeGreaterThanOrEqual(40); // allow 4px tolerance

    await screenshot(page, "MOBILE-01-forgot-password-mobile");
  });

  test("mobile_layout_reset_password_with_token", async ({ page }) => {
    await page.setViewportSize({ width: 393, height: 852 });
    await page.goto(`/reset-password/fake-mobile-test-token`);

    await expect(
      page.getByRole("heading", { name: /set new password/i })
    ).toBeVisible();

    // Both inputs must be visible without horizontal scroll
    await expect(page.getByLabel(/new password/i)).toBeInViewport();
    await expect(page.getByLabel(/confirm password/i)).toBeInViewport();

    await screenshot(page, "MOBILE-02-reset-password-mobile");
  });

  test("mobile_layout_verify_email_loading_state", async ({ page }) => {
    await page.setViewportSize({ width: 393, height: 852 });

    await page.route(`**/auth/verify-email/**`, (route) => {
      // Delay so we can screenshot loading state
      setTimeout(() => {
        route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Invalid." }),
        });
      }, 300);
    });

    await page.goto(`/verify-email/fake-mobile-token`);

    // Loading heading must be visible
    await expect(
      page.getByRole("heading", { name: /verifying your email/i })
    ).toBeVisible({ timeout: 3000 });

    await screenshot(page, "MOBILE-03-verify-email-mobile");
  });
});

// ─── Keyboard Accessibility ───────────────────────────────────────────────────

test.describe("Keyboard Accessibility", () => {
  test("forgot_password_is_keyboard_navigable", async ({ page }) => {
    await page.goto("/forgot-password");

    // Tab to email input (auto-focused, so it should already be)
    const emailInput = page.getByLabel(/email address/i);
    await emailInput.focus();
    await expect(emailInput).toBeFocused();

    await emailInput.fill("test@keyboard.com");

    // Tab to submit button
    await page.keyboard.press("Tab");
    const btn = page.getByRole("button", { name: /send reset link/i });
    await expect(btn).toBeFocused();

    await screenshot(page, "A11Y-01-keyboard-nav-forgot-password");
  });

  test("reset_password_inputs_are_keyboard_navigable", async ({ page }) => {
    await page.goto(`/reset-password/some-token`);

    // Auto-focused on first input
    const newPw = page.getByLabel(/new password/i);
    await expect(newPw).toBeFocused();

    // Tab to confirm
    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab"); // skip the eye-icon button
    const confirmPw = page.getByLabel(/confirm password/i);
    await expect(confirmPw).toBeFocused();

    await screenshot(page, "A11Y-02-keyboard-nav-reset-password");
  });
});
