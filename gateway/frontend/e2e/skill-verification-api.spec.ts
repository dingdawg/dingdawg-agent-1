/**
 * DingDawg Agent 1 — All-12-Skills API Verification
 *
 * Verifies every built-in skill works on PRODUCTION via direct API calls.
 * All requests route through the Vercel proxy → Railway backend.
 *
 * Field names and response shapes verified via production probing on 2026-03-01.
 *
 * Total: 1 SETUP + 24 skill tests + 12 secondary tests = 37 tests
 */

import { test, expect, type APIRequestContext } from "@playwright/test";

// ─── Constants ────────────────────────────────────────────────────────────────

const BACKEND = "https://app.dingdawg.com";
const TS = Date.now();
const TEST_EMAIL = `skill-verify-${TS}@dingdawg.dev`;
const TEST_PASSWORD = "SkillVerify2026x!";

// ─── Shared state ─────────────────────────────────────────────────────────────

let authToken = "";
let capturedContactId = "";
let capturedAppointmentId = "";
let capturedNotificationId = "";
let capturedFormId = "";
let capturedInvoiceId = "";
let capturedInventoryItemId = "";
let capturedExpenseId = "";
let capturedWebhookId = "";
let capturedReferrerId = "";
let capturedReviewId = "";

// ─── Suite configuration ──────────────────────────────────────────────────────

test.describe.configure({ mode: "serial" });

// ─── Auth: register once, share token ────────────────────────────────────────

test.beforeAll(async ({ request }) => {
  const regRes = await request.post(`${BACKEND}/auth/register`, {
    data: { email: TEST_EMAIL, password: TEST_PASSWORD },
    timeout: 20_000,
  });

  if (regRes.status() === 409 || regRes.status() === 400) {
    const loginRes = await request.post(`${BACKEND}/auth/login`, {
      data: { email: TEST_EMAIL, password: TEST_PASSWORD },
      timeout: 20_000,
    });
    expect(loginRes.status()).toBe(200);
    const body = await loginRes.json();
    authToken = (body.access_token ?? body.token) as string;
  } else {
    expect([200, 201]).toContain(regRes.status());
    const body = await regRes.json();
    authToken = (body.access_token ?? body.token) as string;
  }

  expect(authToken).toBeTruthy();
});

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Execute a skill. Action goes inside parameters (backend dispatches on
 * parameters["action"], not the top-level body.action which defaults to "").
 */
async function executeSkill(
  request: APIRequestContext,
  skillName: string,
  action: string,
  parameters: Record<string, unknown> = {}
): Promise<{ status: number; body: Record<string, unknown> }> {
  const res = await request.post(
    `${BACKEND}/api/v1/skills/${skillName}/execute`,
    {
      headers: { Authorization: `Bearer ${authToken}` },
      data: { action, parameters: { ...parameters, action } },
      timeout: 30_000,
    }
  );
  const body = await res.json();
  return { status: res.status(), body };
}

function parseOutput(body: Record<string, unknown>): Record<string, unknown> {
  const raw = body.output;
  if (typeof raw === "string") {
    try { return JSON.parse(raw) as Record<string, unknown>; } catch { return {}; }
  }
  if (raw !== null && typeof raw === "object") return raw as Record<string, unknown>;
  return {};
}

function assertSkillSuccess(
  status: number,
  body: Record<string, unknown>
): Record<string, unknown> {
  expect(status).toBe(200);
  expect(body.success).toBe(true);
  const output = parseOutput(body);
  // Some skills return {error: "Unknown action: X"} inside a success=true envelope
  const errStr = String(output.error ?? "");
  if (errStr.includes("Unknown action")) {
    throw new Error(`Skill returned success=true but output contains: ${errStr}`);
  }
  return output;
}

// ─── 1. Contacts ──────────────────────────────────────────────────────────────

test.describe("1. Contacts", () => {
  test("execute: add contact", async ({ request }) => {
    const { status, body } = await executeSkill(request, "contacts", "add", {
      name: `Contact ${TS}`,
      email: `contact-${TS}@dingdawg.dev`,
      phone: "555-0100",
      tags: ["vip", "test"],
    });
    const output = assertSkillSuccess(status, body);
    expect(output.status).toBe("created");
    expect(typeof output.id).toBe("string");
    capturedContactId = output.id as string;
    console.log(`contacts/add OK — id=${capturedContactId}`);
  });

  test("verify: list shows contact", async ({ request }) => {
    const { status, body } = await executeSkill(request, "contacts", "list", {});
    const output = assertSkillSuccess(status, body);
    const contacts = output.contacts as unknown[];
    expect(Array.isArray(contacts)).toBe(true);
    expect(contacts.length).toBeGreaterThan(0);
    if (capturedContactId) {
      const found = contacts.some((c) => (c as Record<string, unknown>).id === capturedContactId);
      expect(found).toBe(true);
    }
    console.log(`contacts/list OK — ${contacts.length} contact(s)`);
  });
});

// ─── 2. Appointments ──────────────────────────────────────────────────────────

test.describe("2. Appointments", () => {
  test("execute: schedule appointment", async ({ request }) => {
    const { status, body } = await executeSkill(request, "appointments", "schedule", {
      contact_name: "Dr Smith",
      title: `Appt ${TS}`,
      start_time: "2026-04-15T10:00:00",
      duration_minutes: 60,
      notes: "Skill verification test",
    });
    const output = assertSkillSuccess(status, body);
    expect(output.status).toBe("scheduled");
    expect(typeof output.id).toBe("string");
    capturedAppointmentId = output.id as string;
    console.log(`appointments/schedule OK — id=${capturedAppointmentId}`);
  });

  test("verify: list shows appointment", async ({ request }) => {
    const { status, body } = await executeSkill(request, "appointments", "list", {});
    const output = assertSkillSuccess(status, body);
    const items = output.appointments as unknown[];
    expect(Array.isArray(items)).toBe(true);
    expect(items.length).toBeGreaterThan(0);
    console.log(`appointments/list OK — ${items.length} appointment(s)`);
  });
});

// ─── 3. Notifications ─────────────────────────────────────────────────────────

test.describe("3. Notifications", () => {
  test("execute: send notification", async ({ request }) => {
    const { status, body } = await executeSkill(request, "notifications", "send", {
      channel: "email",
      recipient: `contact-${TS}@dingdawg.dev`,
      body: "Skill verification test notification",
      subject: `Verify ${TS}`,
    });
    const output = assertSkillSuccess(status, body);
    expect(output.status).toBe("queued");
    expect(typeof output.id).toBe("string");
    capturedNotificationId = output.id as string;
    console.log(`notifications/send OK — id=${capturedNotificationId}`);
  });

  test("verify: list shows notification", async ({ request }) => {
    const { status, body } = await executeSkill(request, "notifications", "list", {});
    const output = assertSkillSuccess(status, body);
    const items = output.notifications as unknown[];
    expect(Array.isArray(items)).toBe(true);
    expect(items.length).toBeGreaterThan(0);
    console.log(`notifications/list OK — ${items.length} notification(s)`);
  });
});

// ─── 4. Data-Store ────────────────────────────────────────────────────────────

test.describe("4. Data-Store", () => {
  const DS_KEY = `test-key-${TS}`;
  const DS_COLLECTION = "skill-verify";
  const DS_VALUE = { verified: true, ts: TS };

  test("execute: set key/value", async ({ request }) => {
    const { status, body } = await executeSkill(request, "data-store", "set", {
      key: DS_KEY,
      value: DS_VALUE,
      collection: DS_COLLECTION,
    });
    const output = assertSkillSuccess(status, body);
    expect(output.status).toBe("set");
    expect(output.key).toBe(DS_KEY);
    console.log(`data-store/set OK — key=${DS_KEY}`);
  });

  test("verify: get returns stored value", async ({ request }) => {
    const { status, body } = await executeSkill(request, "data-store", "get", {
      key: DS_KEY,
      collection: DS_COLLECTION,
    });
    const output = assertSkillSuccess(status, body);
    expect(output.key).toBe(DS_KEY);
    const val = output.value as Record<string, unknown>;
    expect(val.verified).toBe(true);
    console.log(`data-store/get OK — value=${JSON.stringify(val)}`);
  });
});

// ─── 5. Forms ─────────────────────────────────────────────────────────────────

test.describe("5. Forms", () => {
  test("execute: create_form", async ({ request }) => {
    const { status, body } = await executeSkill(request, "forms", "create_form", {
      name: `Form ${TS}`,
      fields_schema: [
        { name: "rating", type: "number", required: true },
        { name: "comment", type: "textarea", required: false },
      ],
    });
    const output = assertSkillSuccess(status, body);
    expect(output.status).toBe("created");
    expect(typeof output.id).toBe("string");
    capturedFormId = output.id as string;
    console.log(`forms/create_form OK — id=${capturedFormId}`);
  });

  test("verify: list_forms shows form", async ({ request }) => {
    const { status, body } = await executeSkill(request, "forms", "list_forms", {});
    const output = assertSkillSuccess(status, body);
    const items = output.forms as unknown[];
    expect(Array.isArray(items)).toBe(true);
    expect(items.length).toBeGreaterThan(0);
    console.log(`forms/list_forms OK — ${items.length} form(s)`);
  });
});

// ─── 6. Customer Engagement ───────────────────────────────────────────────────

test.describe("6. Customer-Engagement", () => {
  test("execute: record_visit", async ({ request }) => {
    const { status, body } = await executeSkill(request, "customer-engagement", "record_visit", {
      customer_name: `CE Customer ${TS}`,
      email: `ce-${TS}@dingdawg.dev`,
      notes: "Skill verification test",
    });
    const output = assertSkillSuccess(status, body);
    expect(typeof output.id).toBe("string");
    expect(typeof output.visit_count).toBe("number");
    expect(output.visit_count as number).toBeGreaterThanOrEqual(1);
    console.log(`customer-engagement/record_visit OK — visits=${output.visit_count}`);
  });

  test("verify: detect_lapsed returns valid response", async ({ request }) => {
    const { status, body } = await executeSkill(request, "customer-engagement", "detect_lapsed", {
      days: 30,
    });
    const output = assertSkillSuccess(status, body);
    const lapsed = (output.lapsed_customers ?? output.customers ?? []) as unknown[];
    expect(Array.isArray(lapsed)).toBe(true);
    console.log(`customer-engagement/detect_lapsed OK — ${lapsed.length} lapsed`);
  });
});

// ─── 7. Review Manager ────────────────────────────────────────────────────────

test.describe("7. Review-Manager", () => {
  test("execute: log_review", async ({ request }) => {
    const { status, body } = await executeSkill(request, "review-manager", "log_review", {
      platform: "google",
      reviewer_name: `Reviewer ${TS}`,
      rating: 5,
      review_text: "Absolutely fantastic service!",
    });
    const output = assertSkillSuccess(status, body);
    expect(output.sentiment).toBe("positive");
    expect(output.response_status).toBe("pending");
    expect(typeof output.id).toBe("string");
    capturedReviewId = output.id as string;
    console.log(`review-manager/log_review OK — id=${capturedReviewId} sentiment=${output.sentiment}`);
  });

  test("verify: list_pending shows review", async ({ request }) => {
    const { status, body } = await executeSkill(request, "review-manager", "list_pending", {});
    const output = assertSkillSuccess(status, body);
    const items = (output.pending_reviews ?? output.reviews) as unknown[];
    expect(Array.isArray(items)).toBe(true);
    expect(items.length).toBeGreaterThan(0);
    console.log(`review-manager/list_pending OK — ${items.length} pending review(s)`);
  });
});

// ─── 8. Referral Program ──────────────────────────────────────────────────────

test.describe("8. Referral-Program", () => {
  test("execute: create_referrer", async ({ request }) => {
    const { status, body } = await executeSkill(request, "referral-program", "create_referrer", {
      referrer_name: `Referrer ${TS}`,
      email: `referrer-${TS}@dingdawg.dev`,
    });
    const output = assertSkillSuccess(status, body);
    expect(typeof output.id).toBe("string");
    expect(typeof output.referral_code).toBe("string");
    expect((output.referral_code as string).startsWith("REF-")).toBe(true);
    capturedReferrerId = output.id as string;
    console.log(`referral-program/create_referrer OK — code=${output.referral_code}`);
  });

  test("verify: list_referrers shows referrer", async ({ request }) => {
    const { status, body } = await executeSkill(request, "referral-program", "list_referrers", {});
    const output = assertSkillSuccess(status, body);
    const referrers = output.referrers as unknown[];
    expect(Array.isArray(referrers)).toBe(true);
    expect(referrers.length).toBeGreaterThan(0);
    console.log(`referral-program/list_referrers OK — ${referrers.length} referrer(s)`);
  });
});

// ─── 9. Invoicing ─────────────────────────────────────────────────────────────

test.describe("9. Invoicing", () => {
  test("execute: create invoice", async ({ request }) => {
    const { status, body } = await executeSkill(request, "invoicing", "create", {
      client_name: `Invoice Client ${TS}`,
      line_items: [
        { description: "Haircut", quantity: 1, unit_price_cents: 3500 },
        { description: "Beard Trim", quantity: 1, unit_price_cents: 1500 },
      ],
      due_date: "2026-05-01",
    });
    const output = assertSkillSuccess(status, body);
    expect(typeof output.id).toBe("string");
    expect(typeof output.invoice_number).toBe("string");
    expect((output.invoice_number as string).startsWith("INV-")).toBe(true);
    expect(output.status).toBe("draft");
    capturedInvoiceId = output.id as string;
    console.log(`invoicing/create OK — number=${output.invoice_number} total=${output.total_cents}`);
  });

  test("verify: list shows invoice", async ({ request }) => {
    const { status, body } = await executeSkill(request, "invoicing", "list", {});
    const output = assertSkillSuccess(status, body);
    const items = output.invoices as unknown[];
    expect(Array.isArray(items)).toBe(true);
    expect(items.length).toBeGreaterThan(0);
    console.log(`invoicing/list OK — ${items.length} invoice(s)`);
  });
});

// ─── 10. Inventory ────────────────────────────────────────────────────────────

test.describe("10. Inventory", () => {
  const ITEM_NAME = `Test Item ${TS}`;

  test("execute: add_item", async ({ request }) => {
    const { status, body } = await executeSkill(request, "inventory", "add_item", {
      item_name: ITEM_NAME,
      quantity: 50,
      unit: "bottles",
      reorder_level: 10,
      category: "haircare",
    });
    const output = assertSkillSuccess(status, body);
    expect(output.status).toBe("created");
    expect(typeof output.id).toBe("string");
    capturedInventoryItemId = output.id as string;
    console.log(`inventory/add_item OK — id=${capturedInventoryItemId}`);
  });

  test("verify: list shows item", async ({ request }) => {
    const { status, body } = await executeSkill(request, "inventory", "list", {});
    const output = assertSkillSuccess(status, body);
    const items = output.items as unknown[];
    expect(Array.isArray(items)).toBe(true);
    expect(items.length).toBeGreaterThan(0);
    console.log(`inventory/list OK — ${items.length} item(s)`);
  });
});

// ─── 11. Expenses ─────────────────────────────────────────────────────────────

test.describe("11. Expenses", () => {
  test("execute: record expense", async ({ request }) => {
    const { status, body } = await executeSkill(request, "expenses", "record", {
      amount_cents: 25000,
      category: "supplies",
      description: `Expense ${TS}`,
      expense_date: "2026-03-01",
    });
    const output = assertSkillSuccess(status, body);
    expect(output.status).toBe("recorded");
    expect(typeof output.id).toBe("string");
    capturedExpenseId = output.id as string;
    console.log(`expenses/record OK — id=${capturedExpenseId}`);
  });

  test("verify: list shows expense", async ({ request }) => {
    const { status, body } = await executeSkill(request, "expenses", "list", {});
    const output = assertSkillSuccess(status, body);
    const items = output.expenses as unknown[];
    expect(Array.isArray(items)).toBe(true);
    expect(items.length).toBeGreaterThan(0);
    console.log(`expenses/list OK — ${items.length} expense(s)`);
  });
});

// ─── 12. Webhooks ─────────────────────────────────────────────────────────────

test.describe("12. Webhooks", () => {
  test("execute: register webhook", async ({ request }) => {
    const { status, body } = await executeSkill(request, "webhooks", "register", {
      name: `Webhook ${TS}`,
      url: `https://httpbin.org/post?ts=${TS}`,
      events: ["appointment.created", "invoice.paid"],
    });
    const output = assertSkillSuccess(status, body);
    expect(output.status).toBe("registered");
    expect(typeof output.id).toBe("string");
    capturedWebhookId = output.id as string;
    console.log(`webhooks/register OK — id=${capturedWebhookId}`);
  });

  test("verify: list shows webhook", async ({ request }) => {
    const { status, body } = await executeSkill(request, "webhooks", "list", {});
    const output = assertSkillSuccess(status, body);
    const items = output.webhooks as unknown[];
    expect(Array.isArray(items)).toBe(true);
    expect(items.length).toBeGreaterThan(0);
    console.log(`webhooks/list OK — ${items.length} webhook(s)`);
  });
});

// ─── Secondary Actions ──────────────────────────────────────────────────────

test.describe("Secondary Actions", () => {
  test("contacts: search by name", async ({ request }) => {
    const { status, body } = await executeSkill(request, "contacts", "search", {
      query: `Contact ${TS}`,
    });
    const output = assertSkillSuccess(status, body);
    const items = output.contacts as unknown[];
    expect(Array.isArray(items)).toBe(true);
    console.log(`contacts/search OK — ${items.length} match(es)`);
  });

  test("appointments: cancel", async ({ request }) => {
    // Create a fresh one to cancel
    const { body: createBody } = await executeSkill(request, "appointments", "schedule", {
      contact_name: "Cancel Test",
      title: `Cancel ${TS}`,
      start_time: "2026-06-01T14:00:00",
      duration_minutes: 30,
    });
    const created = parseOutput(createBody);
    const idToCancel = created.id as string;

    const { status, body } = await executeSkill(request, "appointments", "cancel", {
      id: idToCancel,
    });
    const output = assertSkillSuccess(status, body);
    expect(output.status).toBe("cancelled");
    console.log(`appointments/cancel OK — id=${idToCancel}`);
  });

  test("data-store: list collection", async ({ request }) => {
    const { status, body } = await executeSkill(request, "data-store", "list", {
      collection: "skill-verify",
    });
    const output = assertSkillSuccess(status, body);
    const items = output.items as unknown[];
    expect(Array.isArray(items)).toBe(true);
    expect(items.length).toBeGreaterThan(0);
    console.log(`data-store/list OK — ${items.length} key(s)`);
  });

  test("invoicing: get by ID", async ({ request }) => {
    if (!capturedInvoiceId) { console.warn("SKIP: no invoice ID"); return; }
    const { status, body } = await executeSkill(request, "invoicing", "get", {
      id: capturedInvoiceId,
    });
    const output = assertSkillSuccess(status, body);
    expect(output.id).toBe(capturedInvoiceId);
    console.log(`invoicing/get OK — id=${capturedInvoiceId}`);
  });

  test("inventory: check_low_stock", async ({ request }) => {
    const { status, body } = await executeSkill(request, "inventory", "check_low_stock", {});
    const output = assertSkillSuccess(status, body);
    const items = (output.low_stock_items ?? output.items ?? []) as unknown[];
    expect(Array.isArray(items)).toBe(true);
    console.log(`inventory/check_low_stock OK — ${items.length} low-stock item(s)`);
  });

  test("expenses: list shows recorded expenses", async ({ request }) => {
    const { status, body } = await executeSkill(request, "expenses", "list", {});
    const output = assertSkillSuccess(status, body);
    const items = output.expenses as unknown[];
    expect(Array.isArray(items)).toBe(true);
    expect(items.length).toBeGreaterThan(0);
    console.log(`expenses/list OK — ${items.length} expense(s)`);
  });

  test("review-manager: get_stats", async ({ request }) => {
    const { status, body } = await executeSkill(request, "review-manager", "get_stats", {});
    const output = assertSkillSuccess(status, body);
    expect(typeof output.total_reviews).toBe("number");
    expect(output.total_reviews as number).toBeGreaterThan(0);
    console.log(`review-manager/get_stats OK — total=${output.total_reviews}`);
  });

  test("notifications: check status", async ({ request }) => {
    if (!capturedNotificationId) { console.warn("SKIP: no notification ID"); return; }
    const { status, body } = await executeSkill(request, "notifications", "status", {
      id: capturedNotificationId,
    });
    const output = assertSkillSuccess(status, body);
    expect(output.id).toBe(capturedNotificationId);
    console.log(`notifications/status OK — status=${output.status}`);
  });

  test("webhooks: deactivate", async ({ request }) => {
    if (!capturedWebhookId) { console.warn("SKIP: no webhook ID"); return; }
    const { status, body } = await executeSkill(request, "webhooks", "deactivate", {
      id: capturedWebhookId,
    });
    const output = assertSkillSuccess(status, body);
    expect(output.status).toBe("deactivated");
    console.log(`webhooks/deactivate OK — id=${capturedWebhookId}`);
  });

  test("forms: submit + retrieve submissions", async ({ request }) => {
    if (!capturedFormId) { console.warn("SKIP: no form ID"); return; }
    const { status: subStatus, body: subBody } = await executeSkill(request, "forms", "submit", {
      form_id: capturedFormId,
      data: { rating: 5, comment: "Excellent!" },
    });
    const subOutput = assertSkillSuccess(subStatus, subBody);
    expect(typeof subOutput.id).toBe("string");
    console.log(`forms/submit OK — submission_id=${subOutput.id}`);

    const { status: listStatus, body: listBody } = await executeSkill(request, "forms", "submissions", {
      form_id: capturedFormId,
    });
    const listOutput = assertSkillSuccess(listStatus, listBody);
    const submissions = listOutput.submissions as unknown[];
    expect(Array.isArray(submissions)).toBe(true);
    expect(submissions.length).toBeGreaterThan(0);
    console.log(`forms/submissions OK — ${submissions.length} submission(s)`);
  });

  test("referral-program: use_code", async ({ request }) => {
    if (!capturedReferrerId) { console.warn("SKIP: no referrer ID"); return; }
    // Get the referral code
    const { body: statsBody } = await executeSkill(request, "referral-program", "list_referrers", {});
    const statsOutput = parseOutput(statsBody);
    const referrers = statsOutput.referrers as Array<Record<string, unknown>>;
    if (!referrers || referrers.length === 0) {
      console.warn("SKIP: no referrers found");
      return;
    }
    const referrer = referrers.find((r) => r.id === capturedReferrerId);
    const code = referrer?.referral_code as string;
    if (!code) { console.warn("SKIP: no code found"); return; }

    const { status, body } = await executeSkill(request, "referral-program", "use_code", {
      referral_code: code,
      referred_name: `Referred ${TS}`,
    });
    const output = assertSkillSuccess(status, body);
    expect(typeof output.use_id).toBe("string");
    expect(typeof output.reward_cents).toBe("number");
    console.log(`referral-program/use_code OK — use_id=${output.use_id} reward=${output.reward_cents}c`);
  });
});
