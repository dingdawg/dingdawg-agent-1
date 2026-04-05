/**
 * E2E Auth Helpers
 *
 * Consolidates authentication setup patterns that were copy-pasted across
 * multiple spec files.  Import these instead of duplicating inline.
 *
 * Key patterns:
 *   - registerAndGetToken: creates a throwaway user via API, returns token
 *   - injectAuthToken: writes the token to localStorage so ProtectedRoute
 *     treats the page as authenticated without a UI login flow
 *   - loginViaUI: fills the login form and submits — use when testing the
 *     login page itself
 *   - setupAuthenticatedPage: register + inject token + navigate
 *
 * Notes:
 *   - AUTH_HEADER_KEY matches the key used by useAuthStore in authStore.ts
 *     ("dd_access_token").  If that key changes, update this constant.
 *   - All helpers accept an optional baseURL so tests can target either the
 *     local dev server or Vercel without changing the call site.
 */

import type { Page, APIRequestContext } from "@playwright/test";
import { expect } from "@playwright/test";

// ─── Constants ────────────────────────────────────────────────────────────────

/** localStorage key used by useAuthStore to persist the JWT */
const AUTH_TOKEN_KEY = "dd_access_token";
/** localStorage key used by useAuthStore to persist user object */
const AUTH_USER_KEY = "dd_user";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface TestCredentials {
  email: string;
  password: string;
  accessToken: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Register a new throwaway user via the backend API.
 * Returns credentials including the access_token.
 *
 * Uses a timestamp suffix so parallel test runs never collide on email.
 */
export async function registerAndGetToken(
  request: APIRequestContext,
  options: {
    emailPrefix?: string;
    password?: string;
    baseURL?: string;
  } = {}
): Promise<TestCredentials> {
  const ts = Date.now();
  const emailPrefix = options.emailPrefix ?? "e2e_helper";
  const email = `${emailPrefix}_${ts}@dingdawg.test`;
  const password = options.password ?? `E2EHelper${ts}x`;
  const base = options.baseURL ?? "";

  const resp = await request.post(`${base}/auth/register`, {
    data: { email, password },
  });
  expect(resp.status(), `register failed: ${await resp.text()}`).toBe(201);

  const body = (await resp.json()) as { access_token: string };
  expect(body.access_token, "expected access_token in register response").toBeTruthy();

  return { email, password, accessToken: body.access_token };
}

/**
 * Inject an access token directly into localStorage so the React auth
 * store treats the browser session as authenticated.
 *
 * Call this after page.goto() but before any interactions that require auth.
 * The page must have completed its initial navigation so the JS context exists.
 */
export async function injectAuthToken(
  page: Page,
  token: string,
  email = "e2e@dingdawg.test"
): Promise<void> {
  await page.evaluate(
    ([tokenKey, userKey, tok, em]) => {
      localStorage.setItem(tokenKey, tok);
      localStorage.setItem(
        userKey,
        JSON.stringify({ id: "e2e-user-id", email: em, is_active: true })
      );
    },
    [AUTH_TOKEN_KEY, AUTH_USER_KEY, token, email]
  );
}

/**
 * Full helper: register → inject token → navigate to target path.
 * Returns the credentials for further use in the test (e.g. claim flow).
 *
 * Usage:
 *   const creds = await setupAuthenticatedPage(page, request, "/dashboard");
 */
export async function setupAuthenticatedPage(
  page: Page,
  request: APIRequestContext,
  targetPath = "/dashboard",
  options: { emailPrefix?: string; password?: string; baseURL?: string } = {}
): Promise<TestCredentials> {
  const creds = await registerAndGetToken(request, options);

  // Navigate to a minimal page first so localStorage is available on the
  // correct origin, then inject the token.
  await page.goto(targetPath);
  await injectAuthToken(page, creds.accessToken, creds.email);

  // Reload so the React store hydrates from the injected localStorage values.
  await page.reload();

  return creds;
}

/**
 * Login via the UI form.  Use this when the test is specifically about the
 * login page UX, not just needing an authenticated state.
 */
export async function loginViaUI(
  page: Page,
  email: string,
  password: string
): Promise<void> {
  await page.goto("/login");
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"]').fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL(/\/(dashboard|claim|chat)/, { timeout: 15_000 });
}

/**
 * Take a screenshot for visual/debug reference.
 * Not a snapshot assertion — just artifact capture.
 */
export async function debugShot(
  page: Page,
  name: string,
  dir = "e2e-screenshots/debug"
): Promise<void> {
  await page.screenshot({ path: `${dir}/${name}.png`, fullPage: true });
}
