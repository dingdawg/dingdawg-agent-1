/**
 * adminRevenueStore.test.ts — Unit tests for useAdminRevenueStore (Zustand).
 *
 * Tests:
 *   - Initial state shape is correct
 *   - fetchStripeStatus success sets stripeStatus, clears isLoading/error
 *   - fetchStripeStatus failure sets error, keeps stripeStatus null
 *   - fetchFunnel success sets funnel data correctly
 *   - fetchFunnel failure sets error message
 *   - fetchContacts success sets paginated contacts
 *   - fetchContacts forwards page/per_page params to API
 *   - fetchContacts failure sets error
 *   - clearError resets error to null
 *   - axios response.data.detail is extracted for errors
 *   - isLoading set true during fetch, false after
 *
 * Run: npx vitest run src/__tests__/admin/adminRevenueStore.test.ts
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// ─── Mock adminService ────────────────────────────────────────────────────────

const mockGetStripeStatus = vi.fn();
const mockGetFunnel = vi.fn();
const mockGetContacts = vi.fn();

vi.mock("@/services/api/adminService", () => ({
  getStripeStatus: () => mockGetStripeStatus(),
  getFunnel: () => mockGetFunnel(),
  getContacts: (params: unknown) => mockGetContacts(params),
}));

// ─── Import store AFTER mocks ─────────────────────────────────────────────────

import { useAdminRevenueStore } from "@/store/adminRevenueStore";
import type {
  StripeStatus,
  FunnelData,
  PaginatedContacts,
  ContactsParams,
} from "@/services/api/adminService";

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const mockStripeStatus: StripeStatus = {
  mode: "test",
  webhook_configured: true,
  last_event: "2026-03-13T10:00:00",
  customer_count: 7,
};

const mockFunnel: FunnelData = {
  registered_users: 200,
  claimed_handles: 150,
  active_subscribers: 30,
  active_7d: 60,
  churned_30d: 4,
};

const mockContacts: PaginatedContacts = {
  items: [
    {
      email: "user@example.com",
      agent_handle: "@mybot",
      status: "active",
      last_active: "2026-03-12T18:00:00",
      subscription_tier: "pro",
    },
    {
      email: "churned@example.com",
      agent_handle: null,
      status: "churned",
      last_active: null,
      subscription_tier: null,
    },
  ],
  total: 2,
  page: 1,
  per_page: 20,
};

// ─── Helper — reset store state between tests ─────────────────────────────────

function resetStore() {
  useAdminRevenueStore.setState({
    stripeStatus: null,
    funnel: null,
    contacts: null,
    isLoading: false,
    error: null,
  });
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("useAdminRevenueStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStore();
  });

  // ── Initial state ─────────────────────────────────────────────────────────────

  it("has correct initial state", () => {
    const state = useAdminRevenueStore.getState();
    expect(state.stripeStatus).toBeNull();
    expect(state.funnel).toBeNull();
    expect(state.contacts).toBeNull();
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  // ── fetchStripeStatus — success ───────────────────────────────────────────────

  it("fetchStripeStatus success sets stripeStatus and clears loading/error", async () => {
    mockGetStripeStatus.mockResolvedValueOnce(mockStripeStatus);

    await useAdminRevenueStore.getState().fetchStripeStatus();

    const state = useAdminRevenueStore.getState();
    expect(state.stripeStatus).toEqual(mockStripeStatus);
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  it("fetchStripeStatus sets isLoading=true during fetch, false after", async () => {
    let resolveFn!: (v: StripeStatus) => void;
    mockGetStripeStatus.mockReturnValueOnce(
      new Promise<StripeStatus>((resolve) => {
        resolveFn = resolve;
      })
    );

    const promise = useAdminRevenueStore.getState().fetchStripeStatus();
    expect(useAdminRevenueStore.getState().isLoading).toBe(true);

    resolveFn(mockStripeStatus);
    await promise;
    expect(useAdminRevenueStore.getState().isLoading).toBe(false);
  });

  // ── fetchStripeStatus — failure ───────────────────────────────────────────────

  it("fetchStripeStatus failure sets error and keeps stripeStatus null", async () => {
    mockGetStripeStatus.mockRejectedValueOnce(new Error("Connection refused"));

    await useAdminRevenueStore.getState().fetchStripeStatus();

    const state = useAdminRevenueStore.getState();
    expect(state.stripeStatus).toBeNull();
    expect(state.error).toBe("Connection refused");
    expect(state.isLoading).toBe(false);
  });

  it("fetchStripeStatus extracts axios response.data.detail for error", async () => {
    const axiosError = Object.assign(new Error("Request failed"), {
      response: { data: { detail: "Admin gate rejected" } },
    });
    mockGetStripeStatus.mockRejectedValueOnce(axiosError);

    await useAdminRevenueStore.getState().fetchStripeStatus();

    expect(useAdminRevenueStore.getState().error).toBe("Admin gate rejected");
  });

  it("fetchStripeStatus does NOT throw on failure", async () => {
    mockGetStripeStatus.mockRejectedValueOnce(new Error("boom"));

    await expect(
      useAdminRevenueStore.getState().fetchStripeStatus()
    ).resolves.toBeUndefined();
  });

  // ── fetchFunnel — success ─────────────────────────────────────────────────────

  it("fetchFunnel success sets funnel data correctly", async () => {
    mockGetFunnel.mockResolvedValueOnce(mockFunnel);

    await useAdminRevenueStore.getState().fetchFunnel();

    const state = useAdminRevenueStore.getState();
    expect(state.funnel).toEqual(mockFunnel);
    expect(state.funnel?.registered_users).toBe(200);
    expect(state.funnel?.active_subscribers).toBe(30);
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  // ── fetchFunnel — failure ─────────────────────────────────────────────────────

  it("fetchFunnel failure sets error string and funnel stays null", async () => {
    mockGetFunnel.mockRejectedValueOnce(new Error("Funnel API timeout"));

    await useAdminRevenueStore.getState().fetchFunnel();

    const state = useAdminRevenueStore.getState();
    expect(state.funnel).toBeNull();
    expect(state.error).toBe("Funnel API timeout");
  });

  it("fetchFunnel falls back to generic message for non-Error throws", async () => {
    mockGetFunnel.mockRejectedValueOnce("string error");

    await useAdminRevenueStore.getState().fetchFunnel();

    expect(useAdminRevenueStore.getState().error).toBe(
      "Failed to load funnel data"
    );
  });

  // ── fetchContacts — success ───────────────────────────────────────────────────

  it("fetchContacts success sets paginated contacts", async () => {
    mockGetContacts.mockResolvedValueOnce(mockContacts);

    const params: ContactsParams = { page: 1, per_page: 20 };
    await useAdminRevenueStore.getState().fetchContacts(params);

    const state = useAdminRevenueStore.getState();
    expect(state.contacts).toEqual(mockContacts);
    expect(state.contacts?.items).toHaveLength(2);
    expect(state.contacts?.total).toBe(2);
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  it("fetchContacts forwards params to getContacts", async () => {
    mockGetContacts.mockResolvedValueOnce(mockContacts);

    const params: ContactsParams = { page: 2, per_page: 10, search: "test" };
    await useAdminRevenueStore.getState().fetchContacts(params);

    expect(mockGetContacts).toHaveBeenCalledWith(params);
  });

  // ── fetchContacts — failure ───────────────────────────────────────────────────

  it("fetchContacts failure sets error and contacts stays null", async () => {
    mockGetContacts.mockRejectedValueOnce(new Error("Contacts API error"));

    await useAdminRevenueStore.getState().fetchContacts({ page: 1, per_page: 20 });

    const state = useAdminRevenueStore.getState();
    expect(state.contacts).toBeNull();
    expect(state.error).toBe("Contacts API error");
  });

  // ── clearError ────────────────────────────────────────────────────────────────

  it("clearError resets error to null", async () => {
    mockGetFunnel.mockRejectedValueOnce(new Error("some error"));
    await useAdminRevenueStore.getState().fetchFunnel();
    expect(useAdminRevenueStore.getState().error).toBeTruthy();

    useAdminRevenueStore.getState().clearError();
    expect(useAdminRevenueStore.getState().error).toBeNull();
  });
});
