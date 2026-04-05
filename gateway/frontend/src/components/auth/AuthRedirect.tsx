"use client";

/**
 * AuthRedirect — client-only component that redirects authenticated users
 * away from the public landing page to /dashboard.
 *
 * Intentionally thin: all page content lives in the server component (page.tsx)
 * so SSR/SEO works correctly. This is the only client-side piece on that page.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/authStore";

interface AuthRedirectProps {
  /** Route to navigate to when the user is authenticated. */
  to: string;
}

export function AuthRedirect({ to }: AuthRedirectProps) {
  const { isAuthenticated, isHydrated, hydrate } = useAuthStore();
  const router = useRouter();

  // Hydrate auth from localStorage on first mount (mirrors ProtectedRoute)
  useEffect(() => {
    if (!isHydrated) {
      hydrate();
    }
  }, [isHydrated, hydrate]);

  // Only redirect after hydration is confirmed so we don't flash-redirect
  // unauthenticated users who happen to load before localStorage is read.
  useEffect(() => {
    if (isHydrated && isAuthenticated) {
      router.replace(to);
    }
  }, [isAuthenticated, isHydrated, router, to]);

  return null;
}
