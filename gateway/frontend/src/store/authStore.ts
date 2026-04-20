/**
 * Auth store — Zustand state for authentication.
 *
 * Tokens persisted to localStorage for survival across page reloads.
 */

"use client";

import { create } from "zustand";
import {
  login as apiLogin,
  register as apiRegister,
  type LoginResponse,
  type RegisterBotFields,
  type RegisterResponse,
} from "@/services/api/authService";
import { setAccessToken } from "@/services/api/client";

/** MFA challenge state stored in the auth store while waiting for 2FA. */
export interface MfaChallenge {
  challengeToken: string;
  userId: string;
  email: string;
}

interface User {
  id: string;
  email: string;
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  isHydrated: boolean;
  error: string | null;
  /** Non-null when login returned mfa_required=true and we are waiting for 2FA. */
  mfaChallenge: MfaChallenge | null;

  hydrate: () => void;
  login: (email: string, password: string) => Promise<{ mfaRequired: boolean }>;
  register: (email: string, password: string, botFields?: RegisterBotFields) => Promise<void>;
  logout: () => void;
  setFromResponse: (res: LoginResponse) => void;
  clearError: () => void;
  clearMfaChallenge: () => void;
}

function loadStoredUser(): User | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem("auth_user");
    if (raw) return JSON.parse(raw) as User;
  } catch { /* ignore */ }
  return null;
}

function loadStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: false,
  isHydrated: false,
  error: null,
  mfaChallenge: null,

  hydrate: () => {
    // Dev-only bypass: if NODE_ENV=development AND the dev flag is set,
    // inject a fake user so protected routes render without a real session.
    // Mirrors middleware.ts — both need to pass to reach /dashboard.
    // NEVER fires in production builds (NODE_ENV !== "development").
    if (
      process.env.NODE_ENV === "development" &&
      process.env.NEXT_PUBLIC_DEV_BYPASS_AUTH === "1"
    ) {
      const devUser: User = { id: "dev-local", email: "dev@localhost" };
      setAccessToken("dev-local-bypass-token");
      set({ user: devUser, isAuthenticated: true, isHydrated: true });
      return;
    }

    const token = loadStoredToken();
    const user = loadStoredUser();
    if (token && user) {
      setAccessToken(token);
      set({ user, isAuthenticated: true, isHydrated: true });
    } else {
      set({ isHydrated: true });
    }
  },

  login: async (email: string, password: string) => {
    set({ isLoading: true, error: null, mfaChallenge: null });
    try {
      const res = await apiLogin(email, password);

      // MFA required — store challenge state and return indicator
      if ((res as unknown as { mfa_required?: boolean }).mfa_required) {
        const challengeToken = (res as unknown as { mfa_challenge_token?: string }).mfa_challenge_token ?? "";
        set({
          isLoading: false,
          mfaChallenge: {
            challengeToken,
            userId: res.user_id,
            email: res.email,
          },
        });
        return { mfaRequired: true };
      }

      const user = { id: res.user_id, email: res.email };
      setAccessToken(res.access_token);
      if (typeof window !== "undefined") {
        localStorage.setItem("auth_user", JSON.stringify(user));
      }
      set({
        user,
        isAuthenticated: true,
        isLoading: false,
        error: null,
        mfaChallenge: null,
      });
      return { mfaRequired: false };
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Login failed";
      const axiosDetail =
        (err as { response?: { data?: { detail?: string } } })?.response
          ?.data?.detail ?? message;
      set({ isLoading: false, error: axiosDetail });
      throw err;
    }
  },

  register: async (email: string, password: string, botFields?: RegisterBotFields) => {
    set({ isLoading: true, error: null });
    try {
      // Use the token returned directly from registration — no redundant login call
      const res: RegisterResponse = await apiRegister(email, password, botFields);
      const user = { id: res.user_id, email: res.email };
      setAccessToken(res.access_token);
      if (typeof window !== "undefined") {
        localStorage.setItem("auth_user", JSON.stringify(user));
      }
      set({
        user,
        isAuthenticated: true,
        isLoading: false,
        error: null,
      });
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Registration failed";
      const axiosDetail =
        (err as { response?: { data?: { detail?: string } } })?.response
          ?.data?.detail ?? message;
      set({ isLoading: false, error: axiosDetail });
      throw err;
    }
  },

  logout: () => {
    // Fire-and-forget server-side token invalidation
    import("@/services/api/authService").then(({ serverLogout }) => {
      serverLogout();
    });
    setAccessToken(null);
    set({
      user: null,
      isAuthenticated: false,
      error: null,
    });
  },

  setFromResponse: (res: LoginResponse) => {
    const user = { id: res.user_id, email: res.email };
    setAccessToken(res.access_token);
    if (typeof window !== "undefined") {
      localStorage.setItem("auth_user", JSON.stringify(user));
    }
    set({
      user,
      isAuthenticated: true,
      error: null,
    });
  },

  clearError: () => set({ error: null }),
  clearMfaChallenge: () => set({ mfaChallenge: null }),
}));
