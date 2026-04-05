"use client";

import { useState } from "react";
import Link from "next/link";
import { Zap, ArrowLeft, Mail, CheckCircle, AlertCircle } from "lucide-react";
import { forgotPassword } from "@/services/api/authService";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;

    setIsLoading(true);
    setError(null);
    try {
      await forgotPassword(email.trim());
      setSubmitted(true);
    } catch {
      setError("Something went wrong. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex items-start justify-center min-h-screen px-4 pt-16">
      <div className="w-full max-w-sm">
        {/* Header */}
        <div className="flex flex-col items-center gap-2 mb-8">
          <Zap className="h-9 w-9 text-[var(--gold-500)]" />
          <h1 className="text-2xl font-bold text-[var(--foreground)]">
            Reset Password
          </h1>
          <p className="text-sm text-[var(--color-muted)] text-center">
            Enter your email and we&apos;ll send you a reset link.
          </p>
        </div>

        {submitted ? (
          <div className="glass-panel p-6 text-center space-y-3">
            <CheckCircle className="h-10 w-10 text-green-400 mx-auto" />
            <p className="text-sm text-[var(--foreground)]">
              If an account exists with <strong>{email}</strong>, a password
              reset link will be sent.
            </p>
            <Link
              href="/login"
              className="inline-flex items-center gap-1.5 text-sm text-[var(--gold-500)] hover:underline mt-4"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to login
            </Link>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="glass-panel p-6 space-y-4">
            {error && (
              <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2">
                <AlertCircle className="h-4 w-4 flex-shrink-0" />
                {error}
              </div>
            )}

            <div>
              <label
                htmlFor="email"
                className="block text-sm font-medium text-[var(--foreground)] mb-1.5"
              >
                Email address
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--color-muted)]" />
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  className="pl-9"
                  required
                  autoFocus
                />
              </div>
            </div>

            <Button
              type="submit"
              variant="gold"
              disabled={!email.trim() || isLoading}
              isLoading={isLoading}
              className="w-full"
            >
              Send Reset Link
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
        )}
      </div>
    </div>
  );
}
