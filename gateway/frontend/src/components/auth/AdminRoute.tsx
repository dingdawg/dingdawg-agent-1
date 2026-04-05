"use client";

/**
 * AdminRoute — gate for Command Center pages.
 *
 * Checks:
 *   1. Auth hydration (wait for localStorage read)
 *   2. isAuthenticated (valid JWT)
 *   3. user.email === NEXT_PUBLIC_ADMIN_EMAIL
 *
 * Redirect logic:
 *   - Not authenticated  → /login?returnTo=/admin  (so post-login the user lands on /admin)
 *   - Authenticated, not admin → /dashboard  (regular users never see the admin login prompt)
 *
 * NOTE: `router` is intentionally excluded from the redirect effect's dependency
 * array. In Next.js App Router the router object reference changes on every
 * render/navigation event, which would re-run the redirect check mid-navigation
 * and cause the "jumping" symptom. We only need to re-evaluate when auth state
 * actually changes (isHydrated, isAuthenticated, user).
 */

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/authStore";

const ADMIN_EMAIL = (process.env.NEXT_PUBLIC_ADMIN_EMAIL ?? "").trim().toLowerCase();

interface AdminRouteProps {
  children: React.ReactNode;
}

export default function AdminRoute({ children }: AdminRouteProps) {
  const { user, isAuthenticated, isHydrated, hydrate } = useAuthStore();
  const router = useRouter();
  // Keep a stable ref to router so the redirect effect doesn't re-fire every
  // time Next.js creates a new router object reference during navigation.
  const routerRef = useRef(router);
  routerRef.current = router;

  // Ensure auth is hydrated from localStorage on first mount
  useEffect(() => {
    if (!isHydrated) {
      hydrate();
    }
  }, [isHydrated, hydrate]);

  // Redirect as soon as we have a definitive answer.
  // Depends only on auth state — NOT on `router` — to avoid spurious re-runs
  // mid-navigation that would bounce the admin between /admin and /dashboard.
  useEffect(() => {
    if (!isHydrated) return;

    const userEmail = user?.email?.trim().toLowerCase() ?? "";
    const isAdmin = isAuthenticated && userEmail === ADMIN_EMAIL;

    if (!isAuthenticated) {
      // Not logged in — send to login with return URL so the user lands back here
      routerRef.current.replace("/login?returnTo=/admin");
    } else if (!isAdmin) {
      // Logged in but not the admin — send to their own dashboard
      routerRef.current.replace("/dashboard");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isHydrated, isAuthenticated, user]);

  // Show spinner while hydrating
  if (!isHydrated) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-[var(--ink-950)]">
        <div className="w-8 h-8 border-2 border-[var(--gold-400)] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const userEmail = user?.email?.trim().toLowerCase() ?? "";
  const isAdmin = isAuthenticated && userEmail === ADMIN_EMAIL;

  // Gate: render nothing while redirect fires (or if auth check fails)
  if (!isAdmin) {
    return null;
  }

  return <>{children}</>;
}
