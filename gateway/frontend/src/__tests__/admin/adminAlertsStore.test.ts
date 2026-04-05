/**
 * adminAlertsStore.test.ts — Unit tests for useAdminAlertsStore (Zustand).
 *
 * Tests:
 *   - Initial state is correct
 *   - fetchAlerts success populates alerts sorted newest-first
 *   - fetchAlerts computes unreadCount correctly (only unacknowledged)
 *   - fetchAlerts failure sets error, alerts stays []
 *   - fetchAlerts does NOT throw
 *   - setFilter updates filter field
 *   - acknowledgeAlert optimistic update marks alert acknowledged
 *   - acknowledgeAlert recomputes unreadCount after optimistic update
 *   - acknowledgeAlert restores state when API call fails
 *   - acknowledgeAlert restores unreadCount on failure
 *   - clearError resets error to null
 *
 * Run: npx vitest run src/__tests__/admin/adminAlertsStore.test.ts
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// ─── Mock adminService ────────────────────────────────────────────────────────

const mockGetAlerts = vi.fn();
const mockAcknowledgeAlert = vi.fn();

vi.mock("@/services/api/adminService", () => ({
  getAlerts: () => mockGetAlerts(),
  acknowledgeAlert: (id: string) => mockAcknowledgeAlert(id),
}));

// ─── Import store AFTER mocks ─────────────────────────────────────────────────

import { useAdminAlertsStore } from "@/store/adminAlertsStore";
import type { Alert } from "@/services/api/adminService";

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const alertCritical: Alert = {
  id: "alert-001",
  severity: "critical",
  title: "Database connection lost",
  description: "Primary DB unreachable for 30s",
  source: "system",
  timestamp: "2026-03-13T12:00:00",
  acknowledged: false,
};

const alertWarning: Alert = {
  id: "alert-002",
  severity: "warning",
  title: "High error rate",
  description: "Error rate above threshold",
  source: "system",
  timestamp: "2026-03-13T11:30:00",
  acknowledged: false,
};

const alertInfoAcknowledged: Alert = {
  id: "alert-003",
  severity: "info",
  title: "Deploy completed",
  description: "Marketing agent deployed",
  source: "integration",
  timestamp: "2026-03-13T10:00:00",
  acknowledged: true,
};

// ─── Helper — reset store between tests ──────────────────────────────────────

function resetStore() {
  useAdminAlertsStore.setState({
    alerts: [],
    unreadCount: 0,
    filter: "all",
    isLoading: false,
    error: null,
  });
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("useAdminAlertsStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStore();
  });

  // ── Initial state ─────────────────────────────────────────────────────────────

  it("has correct initial state", () => {
    const state = useAdminAlertsStore.getState();
    expect(state.alerts).toEqual([]);
    expect(state.unreadCount).toBe(0);
    expect(state.filter).toBe("all");
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  // ── fetchAlerts — success ─────────────────────────────────────────────────────

  it("fetchAlerts success populates alerts array", async () => {
    mockGetAlerts.mockResolvedValueOnce([
      alertWarning,
      alertCritical,
      alertInfoAcknowledged,
    ]);

    await useAdminAlertsStore.getState().fetchAlerts();

    const state = useAdminAlertsStore.getState();
    expect(state.alerts).toHaveLength(3);
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  it("fetchAlerts sorts alerts newest-first by timestamp", async () => {
    // Feed in oldest-first order
    mockGetAlerts.mockResolvedValueOnce([
      alertInfoAcknowledged, // 10:00
      alertWarning,          // 11:30
      alertCritical,         // 12:00
    ]);

    await useAdminAlertsStore.getState().fetchAlerts();

    const alerts = useAdminAlertsStore.getState().alerts;
    // Newest (12:00) should be first
    expect(alerts[0].id).toBe("alert-001");
    expect(alerts[1].id).toBe("alert-002");
    expect(alerts[2].id).toBe("alert-003");
  });

  it("fetchAlerts computes unreadCount as count of unacknowledged alerts", async () => {
    // Two unacknowledged, one acknowledged
    mockGetAlerts.mockResolvedValueOnce([
      alertCritical,
      alertWarning,
      alertInfoAcknowledged,
    ]);

    await useAdminAlertsStore.getState().fetchAlerts();

    expect(useAdminAlertsStore.getState().unreadCount).toBe(2);
  });

  it("fetchAlerts unreadCount is 0 when all alerts are acknowledged", async () => {
    const acked: Alert = { ...alertCritical, acknowledged: true };
    mockGetAlerts.mockResolvedValueOnce([acked, alertInfoAcknowledged]);

    await useAdminAlertsStore.getState().fetchAlerts();

    expect(useAdminAlertsStore.getState().unreadCount).toBe(0);
  });

  it("fetchAlerts sets isLoading=true during fetch, false after", async () => {
    let resolveFn!: (v: Alert[]) => void;
    mockGetAlerts.mockReturnValueOnce(
      new Promise<Alert[]>((resolve) => {
        resolveFn = resolve;
      })
    );

    const promise = useAdminAlertsStore.getState().fetchAlerts();
    expect(useAdminAlertsStore.getState().isLoading).toBe(true);

    resolveFn([alertCritical]);
    await promise;
    expect(useAdminAlertsStore.getState().isLoading).toBe(false);
  });

  // ── fetchAlerts — failure ─────────────────────────────────────────────────────

  it("fetchAlerts failure sets error and alerts stays []", async () => {
    mockGetAlerts.mockRejectedValueOnce(new Error("Alerts API down"));

    await useAdminAlertsStore.getState().fetchAlerts();

    const state = useAdminAlertsStore.getState();
    expect(state.alerts).toEqual([]);
    expect(state.error).toBe("Alerts API down");
    expect(state.isLoading).toBe(false);
  });

  it("fetchAlerts failure extracts axios response.data.detail", async () => {
    const axiosError = Object.assign(new Error("Request failed"), {
      response: { data: { detail: "Not authorized" } },
    });
    mockGetAlerts.mockRejectedValueOnce(axiosError);

    await useAdminAlertsStore.getState().fetchAlerts();

    expect(useAdminAlertsStore.getState().error).toBe("Not authorized");
  });

  it("fetchAlerts does NOT throw on failure", async () => {
    mockGetAlerts.mockRejectedValueOnce(new Error("boom"));

    await expect(
      useAdminAlertsStore.getState().fetchAlerts()
    ).resolves.toBeUndefined();
  });

  // ── setFilter ─────────────────────────────────────────────────────────────────

  it("setFilter updates the filter field", () => {
    useAdminAlertsStore.getState().setFilter("critical");
    expect(useAdminAlertsStore.getState().filter).toBe("critical");

    useAdminAlertsStore.getState().setFilter("warning");
    expect(useAdminAlertsStore.getState().filter).toBe("warning");

    useAdminAlertsStore.getState().setFilter("all");
    expect(useAdminAlertsStore.getState().filter).toBe("all");
  });

  // ── acknowledgeAlert — optimistic update ──────────────────────────────────────

  it("acknowledgeAlert immediately marks the alert as acknowledged (optimistic)", async () => {
    useAdminAlertsStore.setState({
      alerts: [alertCritical, alertWarning],
      unreadCount: 2,
    });
    mockAcknowledgeAlert.mockResolvedValueOnce(undefined);

    useAdminAlertsStore.getState().acknowledgeAlert("alert-001");

    // Optimistic update is synchronous — check immediately without await
    const updated = useAdminAlertsStore
      .getState()
      .alerts.find((a) => a.id === "alert-001");
    expect(updated?.acknowledged).toBe(true);
  });

  it("acknowledgeAlert recomputes unreadCount after optimistic update", async () => {
    useAdminAlertsStore.setState({
      alerts: [alertCritical, alertWarning],
      unreadCount: 2,
    });
    mockAcknowledgeAlert.mockResolvedValueOnce(undefined);

    useAdminAlertsStore.getState().acknowledgeAlert("alert-001");

    // One of the two unread is now acknowledged → count should drop to 1
    expect(useAdminAlertsStore.getState().unreadCount).toBe(1);
  });

  it("acknowledgeAlert calls acknowledgeAlert API with correct alertId", async () => {
    useAdminAlertsStore.setState({ alerts: [alertCritical], unreadCount: 1 });
    mockAcknowledgeAlert.mockResolvedValueOnce(undefined);

    useAdminAlertsStore.getState().acknowledgeAlert("alert-001");

    // Allow the micro-task queue to drain for the API call
    await vi.waitFor(() => {
      expect(mockAcknowledgeAlert).toHaveBeenCalledWith("alert-001");
    });
  });

  it("acknowledgeAlert restores previous alerts when API call fails", async () => {
    useAdminAlertsStore.setState({
      alerts: [alertCritical, alertWarning],
      unreadCount: 2,
    });
    mockAcknowledgeAlert.mockRejectedValueOnce(new Error("Network failure"));

    useAdminAlertsStore.getState().acknowledgeAlert("alert-001");

    // Wait for the catch block to restore state
    await vi.waitFor(() => {
      const state = useAdminAlertsStore.getState();
      // The restored alert should be unacknowledged again
      const restored = state.alerts.find((a) => a.id === "alert-001");
      expect(restored?.acknowledged).toBe(false);
    });
  });

  it("acknowledgeAlert restores unreadCount when API call fails", async () => {
    useAdminAlertsStore.setState({
      alerts: [alertCritical, alertWarning],
      unreadCount: 2,
    });
    mockAcknowledgeAlert.mockRejectedValueOnce(new Error("Network failure"));

    useAdminAlertsStore.getState().acknowledgeAlert("alert-001");

    await vi.waitFor(() => {
      expect(useAdminAlertsStore.getState().unreadCount).toBe(2);
    });
  });

  it("acknowledgeAlert sets error message when API call fails", async () => {
    useAdminAlertsStore.setState({ alerts: [alertCritical], unreadCount: 1 });
    mockAcknowledgeAlert.mockRejectedValueOnce(
      new Error("Failed to acknowledge")
    );

    useAdminAlertsStore.getState().acknowledgeAlert("alert-001");

    await vi.waitFor(() => {
      expect(useAdminAlertsStore.getState().error).toBe(
        "Failed to acknowledge"
      );
    });
  });

  // ── clearError ────────────────────────────────────────────────────────────────

  it("clearError resets error to null", async () => {
    mockGetAlerts.mockRejectedValueOnce(new Error("some error"));
    await useAdminAlertsStore.getState().fetchAlerts();
    expect(useAdminAlertsStore.getState().error).toBeTruthy();

    useAdminAlertsStore.getState().clearError();
    expect(useAdminAlertsStore.getState().error).toBeNull();
  });
});
