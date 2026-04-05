/**
 * adminStore.test.ts — Unit tests for useAdminStore (Zustand).
 *
 * Tests:
 *   - Initial state shape is correct
 *   - fetchPlatformStats success — sets platformStats, clears isLoading
 *   - fetchPlatformStats failure — sets error, clears isLoading, stats remain null
 *   - fetchPlatformStats API error with axios detail — uses detail string
 *   - fetchStripeStatus sets stripeMode from response
 *   - fetchStripeStatus failure sets stripeMode to "unknown" (does NOT throw)
 *   - checkAdmin success — sets isAdmin and whoami
 *   - checkAdmin failure — sets isAdmin=false, error set, does NOT throw
 *   - clearError resets error to null
 *   - reset returns store to initial values
 *
 * Run: npx vitest run src/__tests__/admin/adminStore.test.ts
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// ─── Mock adminService ────────────────────────────────────────────────────────
// Must be declared before any import that transitively uses the module.

const mockGetWhoami = vi.fn();
const mockGetPlatformStats = vi.fn();
const mockGetStripeStatus = vi.fn();

vi.mock("@/services/api/adminService", () => ({
  getWhoami: () => mockGetWhoami(),
  getPlatformStats: () => mockGetPlatformStats(),
  getStripeStatus: () => mockGetStripeStatus(),
}));

// ─── Import store AFTER mocks ─────────────────────────────────────────────────

import { useAdminStore } from "@/store/adminStore";
import type {
  AdminWhoami,
  PlatformStats,
  StripeStatus,
} from "@/services/api/adminService";

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const mockWhoami: AdminWhoami = {
  user_id: "usr-001",
  email: "admin@dingdawg.com",
  is_admin: true,
  role: "superadmin",
};

const mockStats: PlatformStats = {
  total_users: 500,
  total_agents: 120,
  sessions_24h: 88,
  errors_24h: 3,
  active_sessions: 14,
  revenue_mtd_cents: 250000,
};

const mockStripeTest: StripeStatus = {
  mode: "test",
  webhook_configured: true,
  last_event: "2026-03-13T10:00:00",
  customer_count: 5,
};

const mockStripeLive: StripeStatus = {
  mode: "live",
  webhook_configured: true,
  last_event: "2026-03-13T11:00:00",
  customer_count: 99,
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Reset the Zustand store to its initial state between tests. */
function resetStore() {
  useAdminStore.getState().reset();
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("useAdminStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStore();
  });

  // ── Initial state ────────────────────────────────────────────────────────────

  it("initial state is correct", () => {
    const state = useAdminStore.getState();
    expect(state.isAdmin).toBe(false);
    expect(state.platformStats).toBeNull();
    expect(state.stripeMode).toBe("unknown");
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
    expect(state.whoami).toBeNull();
  });

  // ── fetchPlatformStats — success ──────────────────────────────────────────────

  it("fetchPlatformStats success sets platformStats and clears isLoading", async () => {
    mockGetPlatformStats.mockResolvedValueOnce(mockStats);

    await useAdminStore.getState().fetchPlatformStats();

    const state = useAdminStore.getState();
    expect(state.platformStats).toEqual(mockStats);
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  it("fetchPlatformStats sets isLoading to true during fetch", async () => {
    let resolveFn!: (v: PlatformStats) => void;
    mockGetPlatformStats.mockReturnValueOnce(
      new Promise<PlatformStats>((resolve) => {
        resolveFn = resolve;
      })
    );

    const promise = useAdminStore.getState().fetchPlatformStats();
    // While in-flight, isLoading should be true
    expect(useAdminStore.getState().isLoading).toBe(true);

    resolveFn(mockStats);
    await promise;
    expect(useAdminStore.getState().isLoading).toBe(false);
  });

  // ── fetchPlatformStats — failure ──────────────────────────────────────────────

  it("fetchPlatformStats failure sets error message and clears isLoading", async () => {
    mockGetPlatformStats.mockRejectedValueOnce(new Error("Network timeout"));

    await useAdminStore.getState().fetchPlatformStats();

    const state = useAdminStore.getState();
    expect(state.platformStats).toBeNull();
    expect(state.isLoading).toBe(false);
    expect(state.error).toBe("Network timeout");
  });

  it("fetchPlatformStats uses axios response detail when present", async () => {
    const axiosError = Object.assign(new Error("Request failed"), {
      response: { data: { detail: "Forbidden — admin only" } },
    });
    mockGetPlatformStats.mockRejectedValueOnce(axiosError);

    await useAdminStore.getState().fetchPlatformStats();

    expect(useAdminStore.getState().error).toBe("Forbidden — admin only");
  });

  it("fetchPlatformStats does NOT throw — error is captured in state", async () => {
    mockGetPlatformStats.mockRejectedValueOnce(new Error("boom"));

    await expect(
      useAdminStore.getState().fetchPlatformStats()
    ).resolves.toBeUndefined();
  });

  // ── fetchStripeStatus ─────────────────────────────────────────────────────────

  it("fetchStripeStatus sets stripeMode to 'test' when mode is test", async () => {
    mockGetStripeStatus.mockResolvedValueOnce(mockStripeTest);

    await useAdminStore.getState().fetchStripeStatus();

    expect(useAdminStore.getState().stripeMode).toBe("test");
  });

  it("fetchStripeStatus sets stripeMode to 'live' when mode is live", async () => {
    mockGetStripeStatus.mockResolvedValueOnce(mockStripeLive);

    await useAdminStore.getState().fetchStripeStatus();

    expect(useAdminStore.getState().stripeMode).toBe("live");
  });

  it("fetchStripeStatus failure sets stripeMode to 'unknown' and does NOT throw", async () => {
    mockGetStripeStatus.mockRejectedValueOnce(new Error("API down"));

    await expect(
      useAdminStore.getState().fetchStripeStatus()
    ).resolves.toBeUndefined();

    expect(useAdminStore.getState().stripeMode).toBe("unknown");
  });

  // ── checkAdmin ────────────────────────────────────────────────────────────────

  it("checkAdmin success sets isAdmin=true and populates whoami", async () => {
    mockGetWhoami.mockResolvedValueOnce(mockWhoami);

    await useAdminStore.getState().checkAdmin();

    const state = useAdminStore.getState();
    expect(state.isAdmin).toBe(true);
    expect(state.whoami).toEqual(mockWhoami);
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  it("checkAdmin failure sets isAdmin=false and error, does NOT throw", async () => {
    mockGetWhoami.mockRejectedValueOnce(new Error("Unauthorized"));

    await expect(
      useAdminStore.getState().checkAdmin()
    ).resolves.toBeUndefined();

    const state = useAdminStore.getState();
    expect(state.isAdmin).toBe(false);
    expect(state.whoami).toBeNull();
    expect(state.error).toBe("Unauthorized");
    expect(state.isLoading).toBe(false);
  });

  // ── clearError ────────────────────────────────────────────────────────────────

  it("clearError resets error to null", async () => {
    mockGetPlatformStats.mockRejectedValueOnce(new Error("some error"));
    await useAdminStore.getState().fetchPlatformStats();
    expect(useAdminStore.getState().error).toBeTruthy();

    useAdminStore.getState().clearError();
    expect(useAdminStore.getState().error).toBeNull();
  });

  // ── reset ─────────────────────────────────────────────────────────────────────

  it("reset returns all fields to initial values", async () => {
    mockGetPlatformStats.mockResolvedValueOnce(mockStats);
    mockGetWhoami.mockResolvedValueOnce(mockWhoami);
    mockGetStripeStatus.mockResolvedValueOnce(mockStripeTest);

    await useAdminStore.getState().fetchPlatformStats();
    await useAdminStore.getState().checkAdmin();
    await useAdminStore.getState().fetchStripeStatus();

    useAdminStore.getState().reset();

    const state = useAdminStore.getState();
    expect(state.isAdmin).toBe(false);
    expect(state.platformStats).toBeNull();
    expect(state.stripeMode).toBe("unknown");
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
    expect(state.whoami).toBeNull();
  });
});
