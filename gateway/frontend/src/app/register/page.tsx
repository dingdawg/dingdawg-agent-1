"use client";

/**
 * Register page — glass panel form with email/password/confirm.
 *
 * Bot Prevention Layer 0 integration:
 *   - HoneypotField: invisible trap input (CSS hidden, aria-hidden)
 *   - TurnstileWidget: Cloudflare invisible CAPTCHA (loads on mount)
 *   - isDisposableEmail: client-side pre-check before API call
 *   - Page load timing: submitted with form for server-side timing analysis
 *
 * Real users see NO friction — zero visible CAPTCHAs, zero extra clicks.
 */

import { useState, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Zap, ChevronLeft } from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { HoneypotField } from "@/components/security/HoneypotField";
import { TurnstileWidget } from "@/components/security/TurnstileWidget";
import { isDisposableEmail, getPageLoadTimestamp } from "@/lib/security";

export default function RegisterPage() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [termsAccepted, setTermsAccepted] = useState(false);

  // Bot prevention state — invisible to real users
  const [honeypot, setHoneypot] = useState("");
  const [turnstileToken, setTurnstileToken] = useState("");

  const { register, isLoading, error, clearError } = useAuthStore();
  const router = useRouter();

  const handleTurnstileSuccess = useCallback((token: string) => {
    setTurnstileToken(token);
  }, []);

  // Password strength: 0=empty, 1=weak, 2=fair, 3=good, 4=strong
  const passwordStrength = useMemo((): 0 | 1 | 2 | 3 | 4 => {
    if (!password) return 0;
    let score = 0;
    if (password.length >= 8) score++;
    if (password.length >= 12) score++;
    if (/[A-Z]/.test(password) && /[a-z]/.test(password)) score++;
    if (/[0-9]/.test(password) && /[^A-Za-z0-9]/.test(password)) score++;
    return Math.max(1, score) as 1 | 2 | 3 | 4;
  }, [password]);

  const strengthLabel = ["", "Weak", "Fair", "Good", "Strong"][passwordStrength];
  const strengthColor = ["", "bg-red-500", "bg-yellow-400", "bg-blue-400", "bg-green-400"][passwordStrength];
  const strengthTextColor = ["", "text-red-400", "text-yellow-400", "text-blue-400", "text-green-400"][passwordStrength];

  const validatePasswordField = (val: string) => {
    if (val.length > 0 && val.length < 8) {
      setFieldErrors((prev) => ({ ...prev, password: "At least 8 characters required" }));
    } else {
      setFieldErrors((prev) => {
        const n = { ...prev };
        delete n.password;
        return n;
      });
    }
  };

  const validateConfirmField = (val: string) => {
    if (val.length > 0 && val !== password) {
      setFieldErrors((prev) => ({ ...prev, confirmPassword: "Passwords do not match" }));
    } else {
      setFieldErrors((prev) => {
        const n = { ...prev };
        delete n.confirmPassword;
        return n;
      });
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLocalError(null);

    if (password !== confirmPassword) {
      setLocalError("Passwords do not match");
      return;
    }

    if (password.length < 8) {
      setLocalError("Password must be at least 8 characters");
      return;
    }

    if (!termsAccepted) {
      setLocalError(
        "You must agree to the Terms of Service and Privacy Policy to create an account",
      );
      return;
    }

    if (isDisposableEmail(email)) {
      setLocalError("Please use a permanent email address");
      return;
    }

    try {
      await register(email, password, {
        website: honeypot,
        turnstile_token: turnstileToken,
        page_load_at: getPageLoadTimestamp() ?? undefined,
        terms_accepted: true,
        terms_accepted_at: new Date().toISOString(),
      });
      router.push("/onboarding");
    } catch {
      // Error is in store
    }
  };

  const displayError = localError ?? error;

  return (
    <div className="flex flex-col items-center justify-center min-h-screen px-4 py-10" style={{ paddingTop: "calc(env(safe-area-inset-top, 0px) + 40px)", paddingBottom: "env(safe-area-inset-bottom, 0px)" }}>
      <div className="w-full max-w-lg">
        <Link href="/" className="flex items-center gap-1 text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] mb-4"><ChevronLeft className="h-4 w-4" />Home</Link>
      </div>
      <Card className="w-full max-w-lg">
        {/* Logo */}
        <div className="flex flex-col items-center gap-2 mb-10">
          <div className="flex items-center justify-center w-14 h-14 rounded-2xl bg-[var(--gold-500)]/10 border border-[var(--gold-500)]/20">
            <Zap className="h-7 w-7 text-[var(--gold-500)]" />
          </div>
          <h1 className="text-2xl font-bold text-[var(--foreground)] font-heading heading-depth mt-1">
            Create Account
          </h1>
          <p className="text-xs font-semibold text-[var(--gold-500)] tracking-widest uppercase">
            Your AI Agent Platform
          </p>
          <p className="text-sm text-[var(--color-muted)] mt-1">
            Get started with DingDawg Agent
          </p>
        </div>

        {/* Error */}
        {displayError && (
          <div className="mb-5 p-3.5 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-start justify-between gap-3">
            <span>{displayError}</span>
            <button
              onClick={() => {
                setLocalError(null);
                clearError();
              }}
              className="shrink-0 text-xs opacity-70 hover:opacity-100 transition-opacity underline"
            >
              dismiss
            </button>
          </div>
        )}

        {/* Social sign-up section */}
        <div className="flex items-center gap-3 mb-4">
          <div className="flex-1 h-px bg-[var(--stroke)]" />
          <span className="text-[11px] font-medium text-[var(--color-muted-dark)] uppercase tracking-widest whitespace-nowrap">
            sign up with
          </span>
          <div className="flex-1 h-px bg-[var(--stroke)]" />
        </div>

        <a
          href="/auth/google"
          className="flex items-center justify-center gap-3 w-full h-12 rounded-xl bg-white border border-gray-200 text-gray-700 font-medium text-sm hover:bg-gray-50 transition-colors shadow-sm mb-3"
          aria-label="Sign up with Google"
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
          aria-label="Sign up with Apple"
        >
          <svg width="17" height="20" viewBox="0 0 17 20" aria-hidden="true" fill="white">
            <path d="M13.876 10.26c-.02-2.047 1.673-3.037 1.749-3.085-1.153-1.688-2.943-2.044-3.575-2.07-1.623-.169-3.17.97-3.99.97-.824 0-2.084-.944-3.426-.918C2.898 5.185 1.335 6.13.506 7.61c-1.699 2.96-.436 7.353 1.223 9.757.814 1.177 1.779 2.495 3.051 2.447 1.227-.05 1.687-.79 3.168-.79 1.48 0 1.893.79 3.178.764 1.32-.025 2.15-1.194 2.957-2.378a13.27 13.27 0 0 0 1.342-2.74c-2.056-.787-2.547-3.36-2.549-3.41ZM11.21 3.35c.672-.822 1.13-1.962.998-3.1-1.03.044-2.24.685-2.93 1.495-.646.74-1.2 1.91-1.052 3.04 1.142.09 2.308-.574 2.984-1.435Z" />
          </svg>
          Continue with Apple
        </a>

        <div className="flex items-center gap-3 my-5">
          <div className="flex-1 h-px bg-[var(--stroke)]" />
          <span className="text-[11px] font-medium text-[var(--color-muted-dark)] uppercase tracking-widest whitespace-nowrap">
            or create account with email
          </span>
          <div className="flex-1 h-px bg-[var(--stroke)]" />
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="flex flex-col gap-5">
          {/*
           * HoneypotField — invisible bot trap.
           * Must be inside form so it submits with the form data.
           * Position: absolute, left -9999px — completely invisible to humans.
           */}
          <HoneypotField value={honeypot} onChange={setHoneypot} />

          <div>
            <label
              htmlFor="fullName"
              className="block text-xs font-semibold text-[var(--color-muted)] uppercase tracking-wider mb-2"
            >
              Full Name
            </label>
            <Input
              id="fullName"
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Your name"
              autoComplete="name"
              autoFocus
            />
          </div>

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
            />
          </div>

          <div>
            <label
              htmlFor="password"
              className="block text-xs font-semibold text-[var(--color-muted)] uppercase tracking-wider mb-2"
            >
              Password
            </label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                validatePasswordField(e.target.value);
              }}
              placeholder="At least 8 characters"
              required
              autoComplete="new-password"
              minLength={8}
            />
            {fieldErrors.password ? (
              <p className="mt-1.5 text-xs text-red-400">{fieldErrors.password}</p>
            ) : password.length > 0 ? (
              <div className="mt-2 space-y-1.5">
                {/* 4-segment strength bar */}
                <div className="flex gap-1">
                  {[1, 2, 3, 4].map((seg) => (
                    <div
                      key={seg}
                      className={`h-1 flex-1 rounded-full transition-all duration-300 ${
                        passwordStrength >= seg ? strengthColor : "bg-white/10"
                      }`}
                    />
                  ))}
                </div>
                <p className={`text-xs font-medium ${strengthTextColor}`}>
                  {strengthLabel} password
                  {passwordStrength < 3 && " — add uppercase, numbers, and symbols"}
                </p>
              </div>
            ) : (
              <p className="mt-1.5 text-xs text-[var(--color-muted-dark)]">
                Min 8 characters — mix letters, numbers, and symbols for best security.
              </p>
            )}
          </div>

          <div>
            <label
              htmlFor="confirmPassword"
              className="block text-xs font-semibold text-[var(--color-muted)] uppercase tracking-wider mb-2"
            >
              Confirm Password
            </label>
            <Input
              id="confirmPassword"
              type="password"
              value={confirmPassword}
              onChange={(e) => {
                setConfirmPassword(e.target.value);
                validateConfirmField(e.target.value);
              }}
              placeholder="Repeat your password"
              required
              autoComplete="new-password"
              minLength={8}
            />
            {fieldErrors.confirmPassword && (
              <p className="mt-1.5 text-xs text-red-400">{fieldErrors.confirmPassword}</p>
            )}
          </div>

          {/* Terms and Privacy Policy acceptance */}
          <div className="flex items-start gap-3 pt-1">
            <input
              id="termsAccepted"
              type="checkbox"
              checked={termsAccepted}
              onChange={(e) => setTermsAccepted(e.target.checked)}
              className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer accent-[var(--gold-500)] rounded"
            />
            <label
              htmlFor="termsAccepted"
              className="text-sm text-[var(--color-muted)] leading-snug cursor-pointer"
            >
              I agree to the{" "}
              <Link
                href="/terms"
                className="text-[var(--gold-500)] hover:underline font-semibold"
                target="_blank"
                rel="noopener noreferrer"
              >
                Terms of Service
              </Link>{" "}
              and{" "}
              <Link
                href="/privacy"
                className="text-[var(--gold-500)] hover:underline font-semibold"
                target="_blank"
                rel="noopener noreferrer"
              >
                Privacy Policy
              </Link>
            </label>
          </div>

          <Button
            type="submit"
            variant="gold"
            size="lg"
            isLoading={isLoading}
            disabled={!termsAccepted}
            className="mt-1"
          >
            Create Account
          </Button>

          {/* Trust micro-copy */}
          <p className="text-center text-[11px] text-[var(--color-muted-dark)]">
            No credit card required · Free plan available · Cancel anytime
          </p>
        </form>

        {/*
         * TurnstileWidget — runs invisible Cloudflare challenge on page load.
         * Placed outside the form so it does not affect form layout.
         * Calls handleTurnstileSuccess with the verification token.
         */}
        <TurnstileWidget
          siteKey={process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? ""}
          onSuccess={handleTurnstileSuccess}
        />

        {/* Login link */}
        <p className="mt-6 text-center text-sm text-[var(--color-muted)]">
          Already have an account?{" "}
          <Link href="/login" className="text-[var(--gold-500)] hover:underline font-medium">
            Sign in
          </Link>
        </p>
      </Card>
    </div>
  );
}
