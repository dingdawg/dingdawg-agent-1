"use client";

/**
 * Login page — glass panel form with email/password.
 *
 * Honors a `returnTo` query parameter so that protected routes (e.g. /admin)
 * can bounce the user here and have them land back at the right page after login.
 * Only relative paths starting with "/" are accepted — all others fall back to
 * /dashboard to prevent open-redirect attacks.
 *
 * useSearchParams() requires a Suspense boundary in Next.js App Router.
 * Pattern: LoginForm (uses the hook) is wrapped in <Suspense> by the default export.
 */

import { Suspense, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { ChevronLeft } from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import { setAccessToken } from "@/services/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
// PasskeyButton removed from login page — causes hydration errors that break the form
import { MfaChallengeModal } from "@/components/auth/MfaChallengeModal";

/** Validate that returnTo is a safe relative path (no protocol, no double-slash). */
function safeReturnTo(raw: string | null): string {
  if (!raw) return "/dashboard";
  // Must start with exactly one "/" and not be a protocol-relative URL (//)
  if (raw.startsWith("/") && !raw.startsWith("//")) return raw;
  return "/dashboard";
}

/** Inner component — isolated here so useSearchParams() has a Suspense ancestor. */
function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passkeyError, setPasskeyError] = useState<string | null>(null);
  const { login, isLoading, error, clearError, mfaChallenge, clearMfaChallenge } = useAuthStore();
  const router = useRouter();
  const searchParams = useSearchParams();
  const returnTo = safeReturnTo(searchParams.get("returnTo"));

  const handlePasskeySuccess = (result: { access_token: string; user_id: string }) => {
    setAccessToken(result.access_token);
    const user = { id: result.user_id, email: email.trim() };
    if (typeof window !== "undefined") {
      localStorage.setItem("auth_user", JSON.stringify(user));
    }
    useAuthStore.setState({ user, isAuthenticated: true, error: null });
    const adminEmail = (process.env.NEXT_PUBLIC_ADMIN_EMAIL ?? "").trim().toLowerCase();
    const isAdmin = email.trim().toLowerCase() === adminEmail;
    router.push(isAdmin && returnTo === "/dashboard" ? "/admin" : returnTo);
  };

  useEffect(() => {
    // Clear any stale in-memory token if localStorage has none
    const storedToken = localStorage.getItem("access_token");
    if (!storedToken) {
      setAccessToken(null);
    }
  }, []);

  // Dev-bypass: skip the whole login flow so Tauri webview never navigates
  // to Google OAuth (which redirects to live app.dingdawg.com and drops the
  // LayoutEditor overlay). Only fires when NEXT_PUBLIC_DEV_BYPASS_AUTH=1 AND
  // NODE_ENV=development.
  useEffect(() => {
    if (
      process.env.NODE_ENV === "development" &&
      process.env.NEXT_PUBLIC_DEV_BYPASS_AUTH === "1"
    ) {
      const devUser = { id: "dev-local", email: "dev@localhost" };
      localStorage.setItem("auth_user", JSON.stringify(devUser));
      localStorage.setItem("access_token", "dev-local-bypass-token");
      setAccessToken("dev-local-bypass-token");
      useAuthStore.setState({
        user: devUser,
        isAuthenticated: true,
        isHydrated: true,
        error: null,
      });
      router.replace(returnTo);
    }
  }, [returnTo, router]);

  const handleMfaSuccess = (accessToken: string, userId: string, mfaEmail: string) => {
    // Use setFromResponse to set token + auth state atomically
    useAuthStore.getState().setFromResponse({
      access_token: accessToken,
      token_type: "bearer",
      user_id: userId,
      email: mfaEmail,
    });
    clearMfaChallenge();
    const adminEmail = (process.env.NEXT_PUBLIC_ADMIN_EMAIL ?? "").trim().toLowerCase();
    const isAdmin = mfaEmail.trim().toLowerCase() === adminEmail;
    router.push(isAdmin && returnTo === "/dashboard" ? "/admin" : returnTo);
  };

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (isLoading) return;              // guard against double-submit
    if (!email.trim() || !password) return; // guard — mirrors HTML required
    try {
      const result = await login(email, password);
      if (result.mfaRequired) {
        // MfaChallengeModal will appear — wait for user to complete 2FA
        return;
      }
      const adminEmail = (process.env.NEXT_PUBLIC_ADMIN_EMAIL ?? "").trim().toLowerCase();
      const isAdmin = email.trim().toLowerCase() === adminEmail;
      router.push(isAdmin && returnTo === "/dashboard" ? "/admin" : returnTo);
    } catch {
      // Error is captured in the auth store and displayed below
    }
  };

  return (
    <>
    {mfaChallenge && (
      <MfaChallengeModal
        challengeToken={mfaChallenge.challengeToken}
        userId={mfaChallenge.userId}
        email={mfaChallenge.email}
        onSuccess={handleMfaSuccess}
        onCancel={() => { clearMfaChallenge(); }}
      />
    )}
    <Card className="w-full max-w-lg">
      {/* Logo */}
      <div className="flex flex-col items-center gap-2 mb-10">
        <Image src="/icons/logo.png" alt="DingDawg mascot" width={108} height={86} priority />
        <h1 className="text-2xl font-bold text-[var(--foreground)] font-heading heading-depth">
          DingDawg
        </h1>
        <p className="text-xs font-semibold text-[var(--gold-500)] tracking-widest uppercase">
          Book. Invoice. Follow Up. Automatically.
        </p>
        <p className="text-sm text-[var(--color-muted)] mt-1">Sign in to your AI agent dashboard</p>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-5 p-3.5 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-start justify-between gap-3">
          <span>{error}</span>
          <button
            onClick={clearError}
            className="shrink-0 text-xs opacity-70 hover:opacity-100 transition-opacity underline"
          >
            dismiss
          </button>
        </div>
      )}

      {/* SSO buttons — above form (STOA: Google/Apple first reduces friction) */}
      <div className="flex flex-col gap-3 mb-5">
        <a
          href="/auth/google"
          className="flex items-center justify-center gap-3 w-full h-12 rounded-xl bg-white border border-gray-200 text-gray-700 font-medium text-sm hover:bg-gray-50 transition-colors shadow-sm"
          aria-label="Continue with Google"
        >
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615Z" fill="#4285F4" />
            <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18Z" fill="#34A853" />
            <path d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332Z" fill="#FBBC05" />
            <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58Z" fill="#EA4335" />
          </svg>
          Continue with Google
        </a>

        <a
          href="/auth/apple"
          className="flex items-center justify-center gap-3 w-full h-12 rounded-xl bg-black text-white font-medium text-sm hover:bg-gray-900 transition-colors shadow-sm"
          aria-label="Continue with Apple"
        >
          <svg width="17" height="20" viewBox="0 0 17 20" aria-hidden="true" fill="white">
            <path d="M13.876 10.26c-.02-2.047 1.673-3.037 1.749-3.085-1.153-1.688-2.943-2.044-3.575-2.07-1.623-.169-3.17.97-3.99.97-.824 0-2.084-.944-3.426-.918C2.898 5.185 1.335 6.13.506 7.61c-1.699 2.96-.436 7.353 1.223 9.757.814 1.177 1.779 2.495 3.051 2.447 1.227-.05 1.687-.79 3.168-.79 1.48 0 1.893.79 3.178.764 1.32-.025 2.15-1.194 2.957-2.378a13.27 13.27 0 0 0 1.342-2.74c-2.056-.787-2.547-3.36-2.549-3.41ZM11.21 3.35c.672-.822 1.13-1.962.998-3.1-1.03.044-2.24.685-2.93 1.495-.646.74-1.2 1.91-1.052 3.04 1.142.09 2.308-.574 2.984-1.435Z" />
          </svg>
          Continue with Apple
        </a>
      </div>

      {/* Or continue with divider */}
      <div className="flex items-center gap-3 mb-5">
        <div className="flex-1 h-px bg-[var(--stroke)]" />
        <span className="text-[11px] font-medium text-[var(--color-muted-dark)] uppercase tracking-widest">
          or sign in with email
        </span>
        <div className="flex-1 h-px bg-[var(--stroke)]" />
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} className="flex flex-col gap-5">
        <div>
          <label
            htmlFor="email"
            className="block text-xs font-semibold text-[var(--color-muted)] uppercase tracking-wider mb-2"
          >
            Email
          </label>
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            required
            autoComplete="email"
            autoFocus
          />
        </div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <label
              htmlFor="password"
              className="block text-xs font-semibold text-[var(--color-muted)] uppercase tracking-wider"
            >
              Password
            </label>
            <Link
              href="/forgot-password"
              className="text-xs text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors"
            >
              Forgot password?
            </Link>
          </div>
          <Input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Enter your password"
            required
            autoComplete="current-password"
          />
        </div>

        <Button
          type="submit"
          variant="gold"
          size="lg"
          isLoading={isLoading}
          className="mt-1"
          onClick={(e) => {
            // Redundant click handler — ensures login fires even if onSubmit
            // event delegation fails (observed in Next.js 16 + React 19
            // with Suspense bailout-to-CSR).
            e.preventDefault();
            void handleSubmit();
          }}
        >
          Sign In
        </Button>

        {/* Trust micro-copy */}
        <p className="text-center text-[11px] text-[var(--color-muted-dark)]">
          Secured with 256-bit encryption
        </p>
      </form>

      {/* Passkey error */}
      {passkeyError && (
        <div className="mt-4 p-3.5 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-start justify-between gap-3">
          <span>{passkeyError}</span>
          <button
            onClick={() => setPasskeyError(null)}
            className="shrink-0 text-xs opacity-70 hover:opacity-100 transition-opacity underline"
          >
            dismiss
          </button>
        </div>
      )}

      {/* Passkey login — disabled on login page to prevent hydration errors */}

      {/* Register link */}
      <p className="mt-8 text-center text-sm text-[var(--color-muted)]">
        Don&apos;t have an account?{" "}
        <Link href="/register" className="text-[var(--gold-500)] hover:underline font-semibold">
          Sign up free
        </Link>
      </p>
    </Card>
    </>
  );
}

/**
 * Page shell — wraps LoginForm in Suspense as required by Next.js App Router
 * when useSearchParams() is used inside a client component.
 */
export default function LoginPage() {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen px-4" style={{ paddingTop: "env(safe-area-inset-top, 0px)", paddingBottom: "env(safe-area-inset-bottom, 0px)" }}>
      <div className="w-full max-w-lg">
        <Link href="/" className="flex items-center gap-1 text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] mb-4"><ChevronLeft className="h-4 w-4" />Home</Link>
      </div>
      <Suspense
        fallback={
          <div className="flex items-center justify-center w-full max-w-lg h-64">
            <div className="w-8 h-8 border-2 border-[var(--gold-400)] border-t-transparent rounded-full animate-spin" />
          </div>
        }
      >
        <LoginForm />
      </Suspense>
    </div>
  );
}
