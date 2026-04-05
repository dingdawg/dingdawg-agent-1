# Agent 1 Checkout Load Test

## What it tests

| Step | Endpoint | Method | Notes |
|------|----------|--------|-------|
| 1 | `/api/v1/live` | GET | Liveness baseline per VU |
| 2 | `/auth/login` | POST | Per-VU JWT token acquisition |
| 3 | `/api/v1/payments/create-checkout-session` | POST | Primary load target |
| 4 | `/api/v1/payments/status` | GET | Read-only subscription status |

## Load shape

| Phase | Duration | VUs |
|-------|----------|-----|
| Ramp up | 30s | 0 → 100 |
| Hold | 60s | 100 |
| Ramp down | 10s | 100 → 0 |

Total test duration: ~100 seconds.

## Thresholds (hard gates)

| Metric | Threshold |
|--------|-----------|
| `http_req_duration` p95 | < 500ms |
| `http_req_failed` rate | < 1% |
| `checkout_duration` p95 | < 500ms |
| `auth_duration` p95 | < 800ms |

## Prerequisites

1. Install k6: https://k6.io/docs/get-started/installation/
   ```bash
   # Ubuntu/Debian
   sudo gpg -k
   sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg \
       --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
   echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" \
       | sudo tee /etc/apt/sources.list.d/k6.list
   sudo apt-get update && sudo apt-get install k6

   # macOS
   brew install k6
   ```

2. A running Agent 1 instance (local or staging — NEVER production for load tests):
   ```bash
   cd ~/Desktop/DingDawg-Agent-1/gateway
   uvicorn isg_agent.main:app --host 0.0.0.0 --port 8000
   ```

3. A test user account in the target DB with known credentials.

## Running the test

### Local instance (default)
```bash
k6 run tests/load/checkout_load_test.js
```

### Staging instance with overrides
```bash
k6 run \
  -e BASE_URL=https://staging.your-domain.com \
  -e TEST_EMAIL=loadtest@your-domain.com \
  -e TEST_PASSWORD=YourSecurePassword \
  -e TEST_AGENT_ID=your-staging-agent-id \
  -e CHECKOUT_PLAN=starter \
  tests/load/checkout_load_test.js
```

### With JSON output (for CI or dashboards)
```bash
k6 run --out json=results.json tests/load/checkout_load_test.js
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BASE_URL` | `http://localhost:8000` | Target service base URL |
| `TEST_EMAIL` | `loadtest@example.com` | Test account email |
| `TEST_PASSWORD` | `LoadTest_SecurePassword_123!` | Test account password |
| `TEST_AGENT_ID` | `test-agent-load-001` | Agent ID for checkout/status requests |
| `CHECKOUT_PLAN` | `starter` | Plan to checkout (`starter`, `pro`, `enterprise`) |

## Interpreting results

**503 on checkout** — Expected in staging if Stripe is not configured. The script counts these separately via `stripe_unconfigured_503` metric and does NOT count them as errors.

**401 on checkout** — Auth token issue. Check `TEST_EMAIL`/`TEST_PASSWORD` are correct and the test user exists.

**checkout_duration p95 > 500ms** — Backend is slow under load. Investigate DB query performance on the `users` and `subscriptions` tables.

**auth_duration p95 > 800ms** — SQLite is contending under 100 concurrent writers. Consider WAL mode or connection pooling.

## IMPORTANT

- Never run this against the production Railway deployment.
- Never commit real credentials in place of the default env var placeholders.
- The test does NOT complete a real Stripe payment — it only calls `create-checkout-session`, which returns a URL. No charges occur.
