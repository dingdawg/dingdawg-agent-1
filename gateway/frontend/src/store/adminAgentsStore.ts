/**
 * adminAgentsStore — Zustand state for the Agent Control Center admin page.
 *
 * Handles paginated agent list, search/filter, and agent status mutations.
 * Follows the same pattern as agentStore.ts:
 *  - Memory only (no localStorage persistence)
 *  - Async actions set isLoading/error around API calls
 *  - extractError helper strips axios response detail
 */

"use client";

import { create } from "zustand";
import {
  getAgentsList,
  suspendAdminAgent,
  activateAdminAgent,
  type AdminAgent,
} from "@/services/api/adminService";

// ─── Types ────────────────────────────────────────────────────────────────────

export type { AdminAgent };

interface AdminAgentsState {
  agents: AdminAgent[];
  totalAgents: number;
  page: number;
  perPage: number;
  search: string;
  statusFilter: string;
  isLoading: boolean;
  error: string | null;

  fetchAgents: () => Promise<void>;
  setPage: (page: number) => void;
  setSearch: (search: string) => void;
  setStatusFilter: (status: string) => void;
  suspendAgent: (agentId: string) => Promise<void>;
  activateAgent: (agentId: string) => Promise<void>;
}

// ─── Helper ───────────────────────────────────────────────────────────────────

function extractError(err: unknown, fallback: string): string {
  if (err instanceof Error) {
    const detail = (
      err as { response?: { data?: { detail?: string } } }
    )?.response?.data?.detail;
    return detail ?? err.message;
  }
  return fallback;
}

// ─── Store ────────────────────────────────────────────────────────────────────

export const useAdminAgentsStore = create<AdminAgentsState>((set, get) => ({
  agents: [],
  totalAgents: 0,
  page: 1,
  perPage: 20,
  search: "",
  statusFilter: "all",
  isLoading: false,
  error: null,

  fetchAgents: async () => {
    const { page, perPage, search, statusFilter } = get();
    set({ isLoading: true, error: null });
    try {
      const res = await getAgentsList({
        page,
        per_page: perPage,
        search: search.trim() || undefined,
        status: statusFilter,
      });
      set({
        agents: res.agents ?? [],
        totalAgents: res.total ?? 0,
        isLoading: false,
      });
    } catch (err: unknown) {
      set({
        isLoading: false,
        error: extractError(err, "Failed to load agents"),
      });
    }
  },

  setPage: (page: number) => {
    set({ page });
    // Caller is responsible for triggering fetchAgents after setPage
  },

  setSearch: (search: string) => {
    set({ search, page: 1 });
  },

  setStatusFilter: (status: string) => {
    set({ statusFilter: status, page: 1 });
  },

  suspendAgent: async (agentId: string) => {
    set({ error: null });
    try {
      await suspendAdminAgent(agentId);
      // Optimistic update: flip status in local list
      set((state) => ({
        agents: state.agents.map((a) =>
          a.id === agentId ? { ...a, status: "suspended" as const } : a
        ),
      }));
    } catch (err: unknown) {
      set({ error: extractError(err, "Failed to suspend agent") });
      throw err;
    }
  },

  activateAgent: async (agentId: string) => {
    set({ error: null });
    try {
      await activateAdminAgent(agentId);
      set((state) => ({
        agents: state.agents.map((a) =>
          a.id === agentId ? { ...a, status: "active" as const } : a
        ),
      }));
    } catch (err: unknown) {
      set({ error: extractError(err, "Failed to activate agent") });
      throw err;
    }
  },
}));
