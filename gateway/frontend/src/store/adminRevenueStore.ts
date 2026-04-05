"use client";

/**
 * adminRevenueStore — Zustand state for Revenue and CRM admin pages.
 *
 * Holds Stripe status, funnel data, and paginated contacts.
 * All actions follow the same error-extraction pattern as agentStore.ts.
 */

import { create } from "zustand";
import {
  getStripeStatus,
  getFunnel,
  getContacts,
  type StripeStatus,
  type FunnelData,
  type Contact,
  type ContactsParams,
  type PaginatedContacts,
} from "@/services/api/adminService";

// ─── Re-export types for page imports ────────────────────────────────────────

export type { StripeStatus, FunnelData, Contact, ContactsParams, PaginatedContacts };

// ─── Store interface ──────────────────────────────────────────────────────────

interface RevenueState {
  stripeStatus: StripeStatus | null;
  funnel: FunnelData | null;
  contacts: PaginatedContacts | null;
  isLoading: boolean;
  error: string | null;

  fetchStripeStatus: () => Promise<void>;
  fetchFunnel: () => Promise<void>;
  fetchContacts: (params: ContactsParams) => Promise<void>;
  clearError: () => void;
}

// ─── Helper ───────────────────────────────────────────────────────────────────

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

export const useAdminRevenueStore = create<RevenueState>((set) => ({
  stripeStatus: null,
  funnel: null,
  contacts: null,
  isLoading: false,
  error: null,

  fetchStripeStatus: async () => {
    set({ isLoading: true, error: null });
    try {
      const stripeStatus = await getStripeStatus();
      set({ stripeStatus, isLoading: false });
    } catch (err: unknown) {
      set({
        isLoading: false,
        error: extractError(err, "Failed to load Stripe status"),
      });
    }
  },

  fetchFunnel: async () => {
    set({ isLoading: true, error: null });
    try {
      const funnel = await getFunnel();
      set({ funnel, isLoading: false });
    } catch (err: unknown) {
      set({
        isLoading: false,
        error: extractError(err, "Failed to load funnel data"),
      });
    }
  },

  fetchContacts: async (params: ContactsParams) => {
    set({ isLoading: true, error: null });
    try {
      const contacts = await getContacts(params);
      set({ contacts, isLoading: false });
    } catch (err: unknown) {
      set({
        isLoading: false,
        error: extractError(err, "Failed to load contacts"),
      });
    }
  },

  clearError: () => set({ error: null }),
}));
