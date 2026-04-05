"use client";

/**
 * OAuth callback page — receives token from Google/Apple Sign-In redirect.
 *
 * The backend redirects here after a successful social sign-in:
 *   /auth/callback?token=JWT&user_id=UUID&email=user@example.com&provider=google
 *
 * This page:
 *   1. Reads the query params
 *   2. Stores the token + user in localStorage (matching login/page.tsx pattern)
 *   3. Sets Zustand auth state
 *   4. Redirects to /dashboard
 *
 * On error (backend redirected with ?error=...), shows message + link to /login.
 */

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore } from "@/store/authStore";
import { setAccessToken } from "@/services/api/client";

function OAuthCallbackHandler() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    const token = searchParams.get("token");
    const userId = searchParams.get("user_id");
    const email = searchParams.get("email");
    const errorParam = searchParams.get("error");

    if (errorParam) {
      setErrorMsg(`Sign-in failed (${errorParam}). Please try again.`);
      return;
    }

    if (!token || !userId || !email) {
      setErrorMsg("Invalid OAuth response. Please try signing in again.");
      return;
    }

    // Store token — same pattern as login/page.tsx and PasskeyButton
    setAccessToken(token);
    const user = { id: userId, email: email.trim() };
    if (typeof window !== "undefined") {
      localStorage.setItem("auth_user", JSON.stringify(user));
    }
    useAuthStore.setState({ user, isAuthenticated: true, error: null });

    router.replace("/dashboard");
  }, [router, searchParams]);

  if (errorMsg) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen px-4 gap-4">
        <p className="text-red-400 text-sm text-center max-w-sm">{errorMsg}</p>
        <a href="/login" className="text-[var(--gold-500)] hover:underline text-sm font-medium">
          Back to login
        </a>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="w-8 h-8 border-2 border-[var(--gold-400)] border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

export default function OAuthCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-screen">
          <div className="w-8 h-8 border-2 border-[var(--gold-400)] border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <OAuthCallbackHandler />
    </Suspense>
  );
}
