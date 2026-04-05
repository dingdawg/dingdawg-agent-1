/**
 * k6 Load Test — DingDawg Agent 1 Checkout Path
 *
 * Target: POST /api/v1/payments/create-checkout-session
 * Auth:   JWT obtained via POST /auth/login at test start (per-VU)
 * Load:   Ramp 0 → 100 VUs over 30s, hold 60s, ramp down 10s
 *
 * Thresholds (hard gates — test FAILS if breached):
 *   - http_req_duration p(95) < 500ms
 *   - http_req_failed   rate < 1%
 *
 * Endpoints exercised (in order per iteration):
 *   1. GET  /api/v1/live                           — liveness baseline
 *   2. POST /auth/login                            — obtain JWT token
 *   3. POST /api/v1/payments/create-checkout-session — primary checkout path
 *   4. GET  /api/v1/payments/status                — subscription status (read-only)
 *
 * DO NOT point BASE_URL at production. Use a staging or local instance.
 * Set BASE_URL via env: k6 run -e BASE_URL=http://localhost:8000 checkout_load_test.js
 */

import http from "k6/http";
import { check, group, sleep } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

// Override via: k6 run -e BASE_URL=http://staging.example.com checkout_load_test.js
const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";

// Test credentials — must exist in the target DB.
// Override via env vars so secrets never live in source control.
const TEST_EMAIL = __ENV.TEST_EMAIL || "loadtest@example.com";
const TEST_PASSWORD = __ENV.TEST_PASSWORD || "LoadTest_SecurePassword_123!";

// Agent ID used in checkout requests — must exist in target DB.
const TEST_AGENT_ID = __ENV.TEST_AGENT_ID || "test-agent-load-001";

// Plan to request a checkout session for (starter | pro | enterprise).
// Stripe will 503 in non-Stripe-configured env — that is expected and handled.
const CHECKOUT_PLAN = __ENV.CHECKOUT_PLAN || "starter";

// ---------------------------------------------------------------------------
// Load shape
// ---------------------------------------------------------------------------

export const options = {
  scenarios: {
    checkout_ramp: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        // Phase 1: ramp up to 100 concurrent users over 30 seconds
        { duration: "30s", target: 100 },
        // Phase 2: hold at 100 concurrent users for 60 seconds
        { duration: "60s", target: 100 },
        // Phase 3: ramp down to 0 over 10 seconds
        { duration: "10s", target: 0 },
      ],
      gracefulRampDown: "15s",
    },
  },

  // Hard thresholds — CI will mark the test as FAILED if these are breached.
  thresholds: {
    // 95th-percentile response time must stay under 500 ms across ALL requests.
    http_req_duration: ["p(95)<500"],
    // Less than 1% of requests may fail (non-2xx or network error).
    http_req_failed: ["rate<0.01"],
    // Checkout-specific trend must also be under 500 ms at p95.
    checkout_duration: ["p(95)<500"],
    // Auth (login) must be fast — 95th percentile under 800 ms.
    auth_duration: ["p(95)<800"],
  },
};

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------

// Tracks latency specifically for the checkout session creation endpoint.
const checkoutDuration = new Trend("checkout_duration", true);

// Tracks latency specifically for the auth/login endpoint.
const authDuration = new Trend("auth_duration", true);

// Count how often Stripe returns 503 (not configured) vs real errors.
const stripeUnconfiguredCount = new Counter("stripe_unconfigured_503");

// Count checkout 201 successes.
const checkoutSuccessCount = new Counter("checkout_success_201");

// Error rate broken out by endpoint group.
const checkoutErrorRate = new Rate("checkout_error_rate");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Build standard JSON POST headers.
 * Optionally include a Bearer token.
 */
function jsonHeaders(token) {
  const headers = {
    "Content-Type": "application/json",
    Accept: "application/json",
    // Identify load test traffic so it can be filtered in server logs.
    "X-Load-Test": "true",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return { headers };
}

// ---------------------------------------------------------------------------
// Setup — runs ONCE before all VUs start (optional, for DB seeding checks)
// ---------------------------------------------------------------------------

export function setup() {
  // Verify the service is reachable before unleashing 100 VUs.
  const liveness = http.get(`${BASE_URL}/api/v1/live`);
  if (liveness.status !== 200) {
    throw new Error(
      `Service not reachable at ${BASE_URL}/api/v1/live — status ${liveness.status}. Aborting load test.`
    );
  }
  console.log(`[setup] Service is live at ${BASE_URL}. Starting load test.`);

  // Return data shared with all VUs via the `data` parameter of default().
  return { baseUrl: BASE_URL };
}

// ---------------------------------------------------------------------------
// Default function — executed by every VU on every iteration
// ---------------------------------------------------------------------------

export default function (data) {
  const base = data.baseUrl;

  // -------------------------------------------------------------------------
  // Group 1: Baseline health check
  // Every VU confirms the service is still alive before hitting checkout.
  // -------------------------------------------------------------------------
  group("health_baseline", function () {
    const res = http.get(`${base}/api/v1/live`, {
      headers: { Accept: "application/json", "X-Load-Test": "true" },
      tags: { endpoint: "liveness" },
    });

    check(res, {
      "liveness 200": (r) => r.status === 200,
      "liveness has status field": (r) => {
        try {
          return JSON.parse(r.body).status === "pass";
        } catch {
          return false;
        }
      },
    });
  });

  // Small think-time between groups (simulate realistic user pacing).
  sleep(0.2);

  // -------------------------------------------------------------------------
  // Group 2: Authentication — obtain JWT token
  // Each VU authenticates independently to avoid shared token state.
  // -------------------------------------------------------------------------
  let token = null;

  group("auth_login", function () {
    const loginPayload = JSON.stringify({
      email: TEST_EMAIL,
      password: TEST_PASSWORD,
    });

    const startTime = Date.now();
    const res = http.post(`${base}/auth/login`, loginPayload, {
      ...jsonHeaders(null),
      tags: { endpoint: "auth_login" },
    });
    authDuration.add(Date.now() - startTime);

    const loginOk = check(res, {
      "login 200": (r) => r.status === 200,
      "login returns token": (r) => {
        try {
          const body = JSON.parse(r.body);
          return typeof body.token === "string" && body.token.length > 0;
        } catch {
          return false;
        }
      },
    });

    if (loginOk && res.status === 200) {
      try {
        token = JSON.parse(res.body).token;
      } catch {
        // token remains null; subsequent groups will skip checkout gracefully.
      }
    }
  });

  // If auth failed, skip the payment path for this iteration.
  // This prevents cascading errors from inflating checkout failure metrics.
  if (!token) {
    console.warn(`[VU ${__VU}] Auth failed — skipping checkout iteration.`);
    sleep(1);
    return;
  }

  sleep(0.3);

  // -------------------------------------------------------------------------
  // Group 3: Checkout session creation — THE PRIMARY LOAD TARGET
  //
  // POST /api/v1/payments/create-checkout-session
  //
  // Expected responses in a non-Stripe-configured staging environment:
  //   - 503 Service Unavailable (Stripe not configured) — acceptable, counted separately
  //   - 201 Created with { checkout_url, session_id }   — full success
  //   - 400 Bad Request (invalid plan)                  — test misconfiguration
  //   - 401 Unauthorized                                — auth token issue
  //
  // In production, 201 is the only acceptable success.
  // -------------------------------------------------------------------------
  group("checkout_create_session", function () {
    const checkoutPayload = JSON.stringify({
      plan: CHECKOUT_PLAN,
      agent_id: TEST_AGENT_ID,
      // Use relative paths — backend resolves domain from request.base_url.
      success_url: "",
      cancel_url: "",
    });

    const startTime = Date.now();
    const res = http.post(
      `${base}/api/v1/payments/create-checkout-session`,
      checkoutPayload,
      {
        ...jsonHeaders(token),
        tags: { endpoint: "checkout_create" },
      }
    );
    const elapsed = Date.now() - startTime;
    checkoutDuration.add(elapsed);

    // Determine pass/fail based on expected response codes.
    const isSuccess = res.status === 201;
    const isStripeUnconfigured = res.status === 503;
    const isClientError = res.status >= 400 && res.status < 500 && res.status !== 401;
    const isUnexpectedError = res.status >= 500 && !isStripeUnconfigured;

    if (isSuccess) {
      checkoutSuccessCount.add(1);
    }
    if (isStripeUnconfigured) {
      // 503 from Stripe-not-configured is expected in staging — do NOT count as error.
      stripeUnconfiguredCount.add(1);
    }

    // Mark as error only for unexpected server failures or auth failures.
    // 503 stripe-unconfigured and 4xx client errors are tracked but not errors.
    checkoutErrorRate.add(isUnexpectedError ? 1 : 0);

    check(res, {
      // Accept 201 (success) or 503 (stripe unconfigured in staging) as valid.
      "checkout acceptable response": (r) =>
        r.status === 201 || r.status === 503 || r.status === 400,
      "checkout not 500": (r) => r.status !== 500,
      "checkout not 502/504": (r) => r.status !== 502 && r.status !== 504,
      "checkout response has body": (r) => r.body && r.body.length > 0,
      "checkout has JSON body": (r) => {
        try {
          JSON.parse(r.body);
          return true;
        } catch {
          return false;
        }
      },
    });

    // On 201 success, also verify the response shape.
    if (isSuccess) {
      check(res, {
        "checkout_url is string": (r) => {
          try {
            const body = JSON.parse(r.body);
            return typeof body.checkout_url === "string";
          } catch {
            return false;
          }
        },
        "session_id is string": (r) => {
          try {
            const body = JSON.parse(r.body);
            return typeof body.session_id === "string";
          } catch {
            return false;
          }
        },
      });
    }
  });

  sleep(0.3);

  // -------------------------------------------------------------------------
  // Group 4: Subscription status read (GET — read-only, no Stripe writes)
  // Simulates the frontend polling subscription state after checkout redirect.
  // -------------------------------------------------------------------------
  group("subscription_status", function () {
    const res = http.get(
      `${base}/api/v1/payments/status?agent_id=${TEST_AGENT_ID}`,
      {
        ...jsonHeaders(token),
        tags: { endpoint: "subscription_status" },
      }
    );

    check(res, {
      // 200 success or 503 stripe-unconfigured are both acceptable.
      "status endpoint responds": (r) =>
        r.status === 200 || r.status === 503 || r.status === 404,
      "status not 500": (r) => r.status !== 500,
    });
  });

  // Think time at end of iteration — simulates user reading the redirect page.
  sleep(Math.random() * 0.5 + 0.5); // 0.5–1.0s random think time
}

// ---------------------------------------------------------------------------
// Teardown — runs ONCE after all VUs finish
// ---------------------------------------------------------------------------

export function teardown(data) {
  console.log(`[teardown] Load test complete. Base URL: ${data.baseUrl}`);
  console.log(
    "[teardown] Review: checkout_duration, auth_duration, stripe_unconfigured_503, checkout_success_201"
  );
}
