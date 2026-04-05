"use client";

/**
 * ProtectedRoute — redirects to /login if not authenticated.
 *
 * Hydrates auth from localStorage before making the redirect decision,
 * so page reloads don't bounce authenticated users to login.
 *
 * NOTE: `router` is intentionally excluded from the redirect effect's dependency
 * array. In Next.js App Router the router object reference changes on every
 * render/navigation event. Including it causes the redirect check to re-fire
 * mid-navigation, which can bounce users to /login unexpectedly. We only need
 * to re-evaluate when auth state actually changes (isHydrated, isAuthenticated).
 */

import { useEffect, useRef, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/authStore";

interface ProtectedRouteProps {
  children: ReactNode;
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const router = useRouter();
  const { isAuthenticated, isHydrated, hydrate } = useAuthStore();
  // Stable ref so the redirect effect doesn't re-run on every router reference
  // change that Next.js App Router emits during navigation.
  const routerRef = useRef(router);
  routerRef.current = router;

  // Hydrate auth from localStorage on first mount
  useEffect(() => {
    if (!isHydrated) {
      hydrate();
    }
  }, [isHydrated, hydrate]);

  // Redirect only after hydration is complete.
  // Depends only on auth state — NOT on `router` — to avoid spurious re-runs.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (isHydrated && !isAuthenticated) {
      routerRef.current.replace("/login");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, isHydrated]);

  // Show spinner while hydrating or if not authenticated yet
  if (!isHydrated || !isAuthenticated) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <span className="spinner text-[var(--gold-500)]" />
      </div>
    );
  }

  return <>{children}</>;
}
