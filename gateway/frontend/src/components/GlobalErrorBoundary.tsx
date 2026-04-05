"use client";

import React from "react";
import Link from "next/link";

interface ErrorBoundaryState {
  hasError: boolean;
  errorMessage: string;
}

interface ErrorBoundaryProps {
  children: React.ReactNode;
}

/**
 * GlobalErrorBoundary catches unexpected React render errors anywhere in the
 * tree and renders a friendly branded fallback instead of exposing stack
 * traces to users.  Wrap {children} in RootLayout with this component.
 */
export class GlobalErrorBoundary extends React.Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, errorMessage: "" };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return {
      hasError: true,
      errorMessage: error?.message ?? "An unexpected error occurred.",
    };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // Log to console in development; swap for a real error-reporting
    // service (e.g. Sentry) in production.
    console.error("[GlobalErrorBoundary] Uncaught error:", error, info);
  }

  private handleReset = (): void => {
    this.setState({ hasError: false, errorMessage: "" });
  };

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div className="min-h-screen bg-[var(--ink-950)] flex items-center justify-center px-4">
        <div className="max-w-md w-full text-center">
          {/* Brand mark */}
          <div className="mb-6">
            <span className="text-5xl" role="img" aria-label="DingDawg lightning bolt">
              &#9889;
            </span>
          </div>

          {/* Heading */}
          <h1 className="text-3xl font-extrabold text-white mb-3 font-heading">
            Something went wrong
          </h1>

          {/* Body copy — no stack trace exposed */}
          <p className="text-[var(--muted)] text-base leading-relaxed mb-8">
            We hit an unexpected error. Our team has been notified. Please
            return to your dashboard and try again.
          </p>

          {/* Actions */}
          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            <Link
              href="/dashboard"
              className="inline-flex items-center justify-center gap-2 px-8 py-3
                         bg-[var(--gold-500)] text-[var(--ink-950)] font-semibold
                         text-base rounded-lg hover:bg-[var(--gold-600)]
                         transition-colors focus-visible:outline-none
                         focus-visible:ring-2 focus-visible:ring-[var(--gold-500)]"
              onClick={this.handleReset}
            >
              Return to Dashboard
            </Link>

            <button
              type="button"
              onClick={this.handleReset}
              className="inline-flex items-center justify-center gap-2 px-8 py-3
                         border border-[var(--stroke2)] bg-transparent
                         text-[var(--foreground)] font-semibold text-base rounded-lg
                         hover:bg-white/5 transition-colors
                         focus-visible:outline-none focus-visible:ring-2
                         focus-visible:ring-[var(--gold-500)]"
            >
              Try Again
            </button>
          </div>

          {/* Footer brand */}
          <p className="mt-10 text-[var(--muted)] text-xs">
            &copy; {new Date().getFullYear()} DingDawg &mdash; Universal AI Agent Platform
          </p>
        </div>
      </div>
    );
  }
}

export default GlobalErrorBoundary;
