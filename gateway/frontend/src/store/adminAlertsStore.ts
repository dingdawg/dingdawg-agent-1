"use client";

/**
 * Admin alerts store — Zustand state for system alert management.
 *
 * Holds alerts array, unread count, active filter, and loading state.
 * Acknowledging an alert updates local state immediately (optimistic) then
 * fires the API call. If the API call fails, the alert is restored.
 */

import { create } from "zustand";
import {
  getAlerts,
  acknowledgeAlert as apiAcknowledgeAlert,
  type Alert,
} from "@/services/api/adminService";

// ─── Types ────────────────────────────────────────────────────────────────────

export type AlertFilter = "all" | "critical" | "warning" | "info";

interface AdminAlertsState {
  alerts: Alert[];
  unreadCount: number;
  filter: AlertFilter;
  isLoading: boolean;
  error: string | null;

  fetchAlerts: () => Promise<void>;
  setFilter: (filter: AlertFilter) => void;
  acknowledgeAlert: (alertId: string) => void;
  clearError: () => void;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function countUnread(alerts: Alert[]): number {
  return alerts.filter((a) => !a.acknowledged).length;
}

function extractError(err: unknown, fallback: string): string {
  if (err instanceof Error) {
    const axiosDetail = (
      err as { response?: { data?: { detail?: string } } }
    )?.response?.data?.detail;
    return axiosDetail ?? err.message;
  }
  return fallback;
}

// ─── Store ────────────────────────────────────────────────────────────────────

export const useAdminAlertsStore = create<AdminAlertsState>((set, get) => ({
  alerts: [],
  unreadCount: 0,
  filter: "all",
  isLoading: false,
  error: null,

  fetchAlerts: async () => {
    set({ isLoading: true, error: null });
    try {
      const alerts = await getAlerts();
      // Sort newest first
      const sorted = [...alerts].sort(
        (a, b) =>
          new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
      );
      set({
        alerts: sorted,
        unreadCount: countUnread(sorted),
        isLoading: false,
      });
    } catch (err: unknown) {
      set({
        isLoading: false,
        error: extractError(err, "Failed to load alerts"),
      });
    }
  },

  setFilter: (filter: AlertFilter) => {
    set({ filter });
  },

  acknowledgeAlert: (alertId: string) => {
    // Optimistic update — mark acknowledged immediately
    const prevAlerts = get().alerts;
    const nextAlerts = prevAlerts.map((a) =>
      a.id === alertId ? { ...a, acknowledged: true } : a
    );
    set({ alerts: nextAlerts, unreadCount: countUnread(nextAlerts) });

    // Fire API — restore on failure
    apiAcknowledgeAlert(alertId).catch((err: unknown) => {
      // Restore previous state on failure
      set({
        alerts: prevAlerts,
        unreadCount: countUnread(prevAlerts),
        error: extractError(err, "Failed to acknowledge alert"),
      });
    });
  },

  clearError: () => set({ error: null }),
}));

// Re-export Alert type for convenience so pages don't need a double import
export type { Alert };
