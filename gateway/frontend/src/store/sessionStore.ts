/**
 * Session store — Zustand state for agent sessions.
 */

"use client";

import { create } from "zustand";
import {
  createSession as apiCreateSession,
  listSessions as apiListSessions,
  deleteSession as apiDeleteSession,
  type Session,
} from "@/services/api/agentService";

interface SessionState {
  sessions: Session[];
  activeSessionId: string | null;
  isLoading: boolean;
  error: string | null;

  loadSessions: () => Promise<void>;
  createSession: (title?: string) => Promise<Session>;
  switchSession: (sessionId: string) => void;
  deleteSession: (sessionId: string) => Promise<void>;
  clearError: () => void;
}

export const useSessionStore = create<SessionState>((set, get) => ({
  sessions: [],
  activeSessionId: null,
  isLoading: false,
  error: null,

  loadSessions: async () => {
    set({ isLoading: true, error: null });
    try {
      const sessions = await apiListSessions();
      set({ sessions, isLoading: false });
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to load sessions";
      set({ isLoading: false, error: message });
    }
  },

  createSession: async (title?: string) => {
    set({ isLoading: true, error: null });
    try {
      const session = await apiCreateSession(
        title ? { system_prompt: title } : undefined
      );
      set((state) => ({
        sessions: [session, ...state.sessions],
        activeSessionId: session.session_id,
        isLoading: false,
      }));
      return session;
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to create session";
      set({ isLoading: false, error: message });
      throw err;
    }
  },

  switchSession: (sessionId: string) => {
    set({ activeSessionId: sessionId });
  },

  deleteSession: async (sessionId: string) => {
    try {
      await apiDeleteSession(sessionId);
      set((state) => {
        const sessions = state.sessions.filter(
          (s) => s.session_id !== sessionId
        );
        const activeSessionId =
          state.activeSessionId === sessionId
            ? sessions[0]?.session_id ?? null
            : state.activeSessionId;
        return { sessions, activeSessionId };
      });
    } catch (err: unknown) {
      const message =
        err instanceof Error
          ? err.message
          : "Failed to delete session";
      set({ error: message });
    }
  },

  clearError: () => set({ error: null }),
}));
