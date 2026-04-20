/**
 * Agent store — Zustand state for platform agents, templates, and selection.
 *
 * Follows the same pattern as authStore.ts:
 *  - Memory only (no localStorage persistence)
 *  - Async actions set isLoading/error around API calls
 *  - Error messages extracted from axios response detail
 */

"use client";

import { create } from "zustand";
import {
  listAgents,
  createAgent,
  listTemplates,
  type AgentResponse,
  type TemplateResponse,
  type CreateAgentPayload,
} from "@/services/api/platformService";

// ─── Types ────────────────────────────────────────────────────────────────────

export type Agent = AgentResponse;
export type Template = TemplateResponse;

interface AgentState {
  agents: Agent[];
  currentAgent: Agent | null;
  templates: Template[];
  isLoading: boolean;
  error: string | null;

  fetchAgents: () => Promise<void>;
  fetchTemplates: () => Promise<void>;
  createAgent: (data: CreateAgentPayload) => Promise<Agent>;
  selectAgent: (id: string) => void;
  clearError: () => void;
  reset: () => void;
}

// ─── Helper: extract axios error detail ──────────────────────────────────────

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

export const useAgentStore = create<AgentState>((set, get) => ({
  agents: [],
  currentAgent: null,
  templates: [],
  // Start as true — pages check `!isLoading && agents.length === 0` to redirect
  // to /claim.  If this starts false, the redirect fires before fetchAgents()
  // even begins, causing a flash of /claim for users who already have an agent.
  isLoading: true,
  error: null,

  fetchAgents: async () => {
    // Dev-only bypass: synthesize a local mock agent so protected routes
    // (dashboard, billing, analytics, etc.) render without a live backend
    // session. Mirrors the auth bypass in middleware.ts + authStore.ts.
    // NEVER fires in production — NODE_ENV !== "development" short-circuits.
    if (
      process.env.NODE_ENV === "development" &&
      process.env.NEXT_PUBLIC_DEV_BYPASS_AUTH === "1"
    ) {
      const mockAgent = {
        id: "dev-agent-local",
        name: "JC",
        handle: "yjh",
        industry: "service",
        description: "Dev mock agent for UI layout work.",
        agent_type: "personal",
        avatar_url: "",
        primary_color: "#f5b800",
        greeting: "Hi! I'm JC. How can I help?",
        goal: "",
        personality: "",
        voice_enabled: false,
        is_public: true,
        skills: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      } as unknown as Agent;
      set({ agents: [mockAgent], currentAgent: mockAgent, isLoading: false });
      return;
    }

    set({ isLoading: true, error: null });
    try {
      const agents = await listAgents();
      // Auto-select first agent if none selected
      const current = get().currentAgent;
      const selected =
        current && agents.find((a) => a.id === current.id)
          ? current
          : agents[0] ?? null;
      set({ agents, currentAgent: selected, isLoading: false });
    } catch (err: unknown) {
      set({
        isLoading: false,
        error: extractError(err, "Failed to load agents"),
      });
    }
  },

  fetchTemplates: async () => {
    set({ isLoading: true, error: null });
    try {
      const templates = await listTemplates();
      set({ templates, isLoading: false });
    } catch (err: unknown) {
      set({
        isLoading: false,
        error: extractError(err, "Failed to load templates"),
      });
    }
  },

  createAgent: async (data: CreateAgentPayload): Promise<Agent> => {
    set({ isLoading: true, error: null });
    try {
      const agent = await createAgent(data);
      set((state) => ({
        agents: [...state.agents, agent],
        currentAgent: agent,
        isLoading: false,
      }));
      return agent;
    } catch (err: unknown) {
      const msg = extractError(err, "Failed to create agent");
      set({ isLoading: false, error: msg });
      throw err;
    }
  },

  selectAgent: (id: string) => {
    const agent = get().agents.find((a) => a.id === id) ?? null;
    set({ currentAgent: agent });
  },

  clearError: () => set({ error: null }),

  reset: () =>
    set({ agents: [], currentAgent: null, templates: [], isLoading: false, error: null }),
}));
