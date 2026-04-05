"use client";

/**
 * Email Verification — Landing page.
 *
 * The user lands here from the verification email:
 *   /verify-email/{token}
 *
 * On mount, immediately calls GET /auth/verify-email/{token}.
 * Shows a loading spinner, then success or error state.
 * On success, a toast message and redirect to dashboard after 3 seconds.
 *
 * Mobile-first, dark theme, 44px touch targets throughout.
 */

import { useState, useEffect } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import { Zap, CheckCircle, AlertCircle, Loader2 } from "lucide-react";
import { verifyEmail } from "@/services/api/authService";
import { Button } from "@/components/ui/button";

type PageState = "loading" | "success" | "error";

export default function VerifyEmailPage() {
  const params = useParams();
  const router = useRouter();
  const token =
    typeof params.token === "string"
      ? params.token
      : Array.isArray(params.token)
      ? params.token[0]
      : "";

  const [pageState, setPageState] = useState<PageState>("loading");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Fire verification request on mount
  useEffect(() => {
    if (!token) {
      setErrorMsg("Verification link is missing a token.");
      setPageState("error");
      return;
    }

    let cancelled = false;
    verifyEmail(token)
      .then((data) => {
        if (!cancelled) {
          if (data?.verified) {
            setPageState("success");
          } else {
            setErrorMsg("Verification did not complete. Please try again.");
            setPageState("error");
          }
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const msg =
            err instanceof Error
              ? err.message
              : "Invalid or expired verification link.";
          setErrorMsg(msg);
          setPageState("error");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [token]);

  // Auto-redirect on success
  useEffect(() => {
    if (pageState === "success") {
      const timer = setTimeout(() => {
        router.push("/dashboard?verified=1");
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [pageState, router]);

  // ── Loading ───────────────────────────────────────────────────────────────

  if (pageState === "loading") {
    return (
      <div className="flex items-center justify-center min-h-screen px-4">
        <div className="w-full max-w-sm">
          <div className="glass-panel p-10 text-center space-y-4">
            <Zap className="h-9 w-9 text-[var(--gold-500)] mx-auto" />
            <Loader2 className="h-8 w-8 text-[var(--gold-500)] mx-auto animate-spin" />
            <h2 className="text-xl font-bold text-[var(--foreground)]">
              Verifying your email&hellip;
            </h2>
            <p className="text-sm text-[var(--color-muted)]">
              Please wait a moment.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // ── Success ───────────────────────────────────────────────────────────────

  if (pageState === "success") {
    return (
      <div className="flex items-start justify-center min-h-screen px-4 pt-16">
        <div className="w-full max-w-sm">
          <div className="glass-panel p-8 text-center space-y-4">
            <Zap className="h-9 w-9 text-[var(--gold-500)] mx-auto" />
            <CheckCircle className="h-12 w-12 text-green-400 mx-auto" />
            <h2 className="text-xl font-bold text-[var(--foreground)]">
              Email Verified!
            </h2>
            <p className="text-sm text-[var(--color-muted)]">
              Your email address has been confirmed. You can now create AI agents
              and access all platform features.
            </p>
            <p className="text-xs text-[var(--color-muted)]">
              Redirecting to dashboard&hellip;
            </p>
            <Link
              href="/dashboard"
              className="inline-flex items-center gap-1.5 text-sm text-[var(--gold-500)] hover:underline"
            >
              Go to dashboard now
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // ── Error ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex items-start justify-center min-h-screen px-4 pt-16">
      <div className="w-full max-w-sm">
        <div className="glass-panel p-8 text-center space-y-4">
          <Zap className="h-9 w-9 text-[var(--gold-500)] mx-auto" />
          <AlertCircle className="h-12 w-12 text-red-400 mx-auto" />
          <h2 className="text-xl font-bold text-[var(--foreground)]">
            Verification Failed
          </h2>
          <p className="text-sm text-[var(--color-muted)]">
            {errorMsg ||
              "This verification link is invalid or has expired."}
          </p>

          <div className="flex flex-col gap-3 pt-2">
            <Button
              variant="gold"
              onClick={() => router.push("/login")}
              className="w-full"
              style={{ minHeight: "44px" }}
            >
              Go to Login
            </Button>

            <Link
              href="/settings"
              className="text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors underline-offset-2 hover:underline"
            >
              Resend verification email from account settings
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
