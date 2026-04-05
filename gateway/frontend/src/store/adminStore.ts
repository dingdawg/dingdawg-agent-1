"use client";

/**
 * adminStore — Zustand store for Command Center admin state.
 *
 * Follows the same pattern as authStore.ts and agentStore.ts:
 *   - Memory only (no localStorage persistence — admin data is ephemeral)
 *   - Async actions set isLoading/error around API calls
 *   - Error messages extracted from axios response detail
 */

import { create } from "zustand";
import {
  getWhoami,
  getPlatformStats,
  getStripeStatus,
  type AdminWhoami,
  type PlatformStats,
  type StripeStatus,
} from "@/services/api/adminService";

// ─── Types ────────────────────────────────────────────────────────────────────

interface AdminState {
  isAdmin: boolean;
  platformStats: PlatformStats | null;
  stripeMode: "test" | "live" | "not_configured" | "unknown";
  isLoading: boolean;
  error: string | null;
  whoami: AdminWhoami | null;

  checkAdmin: () => Promise<void>;
  fetchPlatformStats: () => Promise<void>;
  fetchStripeStatus: () => Promise<void>;
  clearError: () => void;
  reset: () => void;
}

// ─── Helper ───────────────────────────────────────────────────────────────────

function extractError(err: unknown, fallback: string): string {
  if (err instanceof Error) {
    const detail = (err as { response?: { data?: { detail?: string } } })
      ?.response?.data?.detail;
    return detail ?? err.message;
  }
  return fallback;
}

// ─── Store ────────────────────────────────────────────────────────────────────

export const useAdminStore = create<AdminState>((set) => ({
  isAdmin: false,
  platformStats: null,
  stripeMode: "unknown",
  isLoading: false,
  error: null,
  whoami: null,

  checkAdmin: async () => {
    set({ isLoading: true, error: null });
    try {
      const whoami = await getWhoami();
      set({ whoami, isAdmin: true, isLoading: false });
    } catch (err: unknown) {
      set({
        isAdmin: false,
        whoami: null,
        isLoading: false,
        error: extractError(err, "Admin check failed"),
      });
    }
  },

  fetchPlatformStats: async () => {
    set({ isLoading: true, error: null });
    try {
      const stats = await getPlatformStats();
      set({ platformStats: stats, isLoading: false });
    } catch (err: unknown) {
      set({
        isLoading: false,
        error: extractError(err, "Failed to load platform stats"),
      });
    }
  },

  fetchStripeStatus: async () => {
    try {
      const status = await getStripeStatus();
      set({ stripeMode: status.mode });
    } catch {
      set({ stripeMode: "unknown" });
    }
  },

  clearError: () => set({ error: null }),

  reset: () =>
    set({
      isAdmin: false,
      platformStats: null,
      stripeMode: "unknown",
      isLoading: false,
      error: null,
      whoami: null,
    }),
}));
