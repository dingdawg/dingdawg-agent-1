"use client";

/**
 * Reset Password — Set new password phase.
 *
 * The user lands here from the email link:
 *   /reset-password/{token}
 *
 * Shows a form to enter and confirm a new password.
 * On success, redirects to /login with a success toast.
 * On error (expired/used/invalid), shows a clear message with a link
 * to request a new reset.
 *
 * Mobile-first, dark theme, 44px touch targets throughout.
 */

import { useState, useEffect, useRef } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import { Zap, Eye, EyeOff, CheckCircle, AlertCircle, Lock } from "lucide-react";
import { resetPassword } from "@/services/api/authService";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type PageState = "idle" | "loading" | "success" | "error";

export default function ResetPasswordTokenPage() {
  const params = useParams();
  const router = useRouter();
  const token = typeof params.token === "string" ? params.token : Array.isArray(params.token) ? params.token[0] : "";

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [pageState, setPageState] = useState<PageState>("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const firstInputRef = useRef<HTMLInputElement>(null);

  // Auto-focus first input on mount
  useEffect(() => {
    firstInputRef.current?.focus();
  }, []);

  // Redirect to login after success
  useEffect(() => {
    if (pageState === "success") {
      const timer = setTimeout(() => {
        router.push("/login?reset=1");
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [pageState, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLocalError(null);

    // Match backend complexity rules: 8+ chars, 1 uppercase, 1 digit, 1 special char
    if (newPassword.length < 8) {
      setLocalError("Password must be at least 8 characters.");
      return;
    }
    if (!/[A-Z]/.test(newPassword)) {
      setLocalError("Password must contain at least 1 uppercase letter.");
      return;
    }
    if (!/[0-9]/.test(newPassword)) {
      setLocalError("Password must contain at least 1 digit.");
      return;
    }
    if (!/[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?`~]/.test(newPassword)) {
      setLocalError("Password must contain at least 1 special character (!@#$%^&* etc.).");
      return;
    }
    if (newPassword !== confirmPassword) {
      setLocalError("Passwords do not match.");
      return;
    }

    setPageState("loading");
    try {
      await resetPassword(token, newPassword);
      setPageState("success");
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : "Invalid or expired reset link. Please request a new one.";
      setErrorMsg(msg);
      setPageState("error");
    }
  };

  // ── Success state ─────────────────────────────────────────────────────────

  if (pageState === "success") {
    return (
      <div className="flex items-start justify-center min-h-screen px-4 pt-16">
        <div className="w-full max-w-sm">
          <div className="glass-panel p-8 text-center space-y-4">
            <CheckCircle className="h-12 w-12 text-green-400 mx-auto" />
            <h2 className="text-xl font-bold text-[var(--foreground)]">
              Password Updated!
            </h2>
            <p className="text-sm text-[var(--color-muted)]">
              Your password has been changed. Redirecting you to login&hellip;
            </p>
            <Link
              href="/login"
              className="inline-flex items-center gap-1.5 text-sm text-[var(--gold-500)] hover:underline mt-2"
            >
              Go to login now
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // ── Error state ───────────────────────────────────────────────────────────

  if (pageState === "error") {
    return (
      <div className="flex items-start justify-center min-h-screen px-4 pt-16">
        <div className="w-full max-w-sm">
          <div className="glass-panel p-8 text-center space-y-4">
            <AlertCircle className="h-12 w-12 text-red-400 mx-auto" />
            <h2 className="text-xl font-bold text-[var(--foreground)]">
              Link Invalid or Expired
            </h2>
            <p className="text-sm text-[var(--color-muted)]">
              {errorMsg || "This reset link is no longer valid."}
            </p>
            <Link
              href="/forgot-password"
              className="inline-flex items-center gap-1.5 text-sm text-[var(--gold-500)] hover:underline mt-2"
            >
              Request a new reset link
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // ── Form state ────────────────────────────────────────────────────────────

  return (
    <div className="flex items-start justify-center min-h-screen px-4 pt-16">
      <div className="w-full max-w-sm">
        {/* Header */}
        <div className="flex flex-col items-center gap-2 mb-8">
          <Zap className="h-9 w-9 text-[var(--gold-500)]" />
          <h1 className="text-2xl font-bold text-[var(--foreground)]">
            Set New Password
          </h1>
          <p className="text-sm text-[var(--color-muted)] text-center">
            Choose a strong password for your account.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="glass-panel p-6 space-y-4">
          {/* Validation error */}
          {localError && (
            <div
              role="alert"
              className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2"
            >
              <AlertCircle className="h-4 w-4 flex-shrink-0" />
              {localError}
            </div>
          )}

          {/* New Password */}
          <div>
            <label
              htmlFor="new-password"
              className="block text-sm font-medium text-[var(--foreground)] mb-1.5"
            >
              New Password
            </label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--color-muted)]" />
              <Input
                id="new-password"
                ref={firstInputRef}
                type={showNew ? "text" : "password"}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="At least 8 characters"
                className="pl-9 pr-10"
                required
                minLength={8}
                autoComplete="new-password"
                style={{ minHeight: "44px" }}
              />
              <button
                type="button"
                onClick={() => setShowNew((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors p-1"
                aria-label={showNew ? "Hide password" : "Show password"}
                style={{ minHeight: "44px", minWidth: "44px" }}
              >
                {showNew ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
          </div>

          {/* Confirm Password */}
          <div>
            <label
              htmlFor="confirm-password"
              className="block text-sm font-medium text-[var(--foreground)] mb-1.5"
            >
              Confirm Password
            </label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--color-muted)]" />
              <Input
                id="confirm-password"
                type={showConfirm ? "text" : "password"}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Repeat your password"
                className="pl-9 pr-10"
                required
                minLength={8}
                autoComplete="new-password"
                style={{ minHeight: "44px" }}
              />
              <button
                type="button"
                onClick={() => setShowConfirm((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors p-1"
                aria-label={showConfirm ? "Hide password" : "Show password"}
                style={{ minHeight: "44px", minWidth: "44px" }}
              >
                {showConfirm ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
          </div>

          {/* Strength hint */}
          {newPassword.length > 0 && newPassword.length < 8 && (
            <p className="text-xs text-amber-400">
              Password too short — need at least 8 characters.
            </p>
          )}
          {newPassword.length >= 8 && !/[A-Z]/.test(newPassword) && (
            <p className="text-xs text-amber-400">
              Add at least 1 uppercase letter.
            </p>
          )}
          {newPassword.length >= 8 && /[A-Z]/.test(newPassword) && !/[0-9]/.test(newPassword) && (
            <p className="text-xs text-amber-400">
              Add at least 1 digit.
            </p>
          )}
          {newPassword.length >= 8 && /[A-Z]/.test(newPassword) && /[0-9]/.test(newPassword) && !/[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?`~]/.test(newPassword) && (
            <p className="text-xs text-amber-400">
              Add at least 1 special character (!@#$%^&* etc.).
            </p>
          )}
          {newPassword.length >= 8 && confirmPassword.length > 0 && newPassword !== confirmPassword && (
            <p className="text-xs text-amber-400">Passwords don&apos;t match.</p>
          )}

          <Button
            type="submit"
            variant="gold"
            isLoading={pageState === "loading"}
            disabled={pageState === "loading" || !newPassword || !confirmPassword}
            className="w-full"
            style={{ minHeight: "44px" }}
          >
            Update Password
          </Button>

          <div className="text-center">
            <Link
              href="/login"
              className="text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors"
            >
              Back to login
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
}
