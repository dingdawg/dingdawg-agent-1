'use client'

import { useEffect } from "react";
import Link from "next/link";

interface ErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function Error({ error, reset }: ErrorProps) {
  useEffect(() => {
    // Log to error reporting service if available
    console.error("[route-error]", error);
  }, [error]);

  return (
    <div className="min-h-screen bg-[var(--ink-950)] flex items-center justify-center px-4">
      <div className="max-w-md w-full text-center">
        {/* Brand mark */}
        <div className="mb-6">
          <span className="text-5xl" role="img" aria-label="DingDawg lightning bolt">
            &#9889;
          </span>
        </div>

        {/* Error code */}
        <h1 className="text-8xl font-extrabold text-[var(--gold-500)] mb-2 leading-none font-heading">
          500
        </h1>

        {/* Heading */}
        <h2 className="text-2xl font-semibold text-white mb-3 font-heading">
          Something went wrong
        </h2>

        {/* Body copy */}
        <p className="text-[var(--muted)] text-base leading-relaxed mb-6">
          An unexpected error occurred. You can try again or return to your
          dashboard if the problem persists.
        </p>

        {/* Error digest — for support reference */}
        {error.digest && (
          <p className="text-[var(--muted)] text-xs font-mono mb-8 bg-[var(--ink-900)] rounded px-3 py-2 inline-block">
            Error code: {error.digest}
          </p>
        )}

        {/* CTAs */}
        <div className="flex flex-col sm:flex-row gap-3 justify-center mt-2">
          <button
            onClick={reset}
            className="inline-flex items-center justify-center gap-2 px-8 py-3
                       bg-[var(--gold-500)] text-[var(--ink-950)] font-semibold
                       text-base rounded-lg hover:bg-[var(--gold-600)]
                       transition-colors focus-visible:outline-none
                       focus-visible:ring-2 focus-visible:ring-[var(--gold-500)]"
          >
            Try again
          </button>

          <Link
            href="/dashboard"
            className="inline-flex items-center justify-center gap-2 px-8 py-3
                       border border-[var(--gold-500)] text-[var(--gold-500)] font-semibold
                       text-base rounded-lg hover:bg-[var(--gold-500)] hover:text-[var(--ink-950)]
                       transition-colors focus-visible:outline-none
                       focus-visible:ring-2 focus-visible:ring-[var(--gold-500)]"
          >
            Go home
          </Link>
        </div>

        {/* Footer brand */}
        <p className="mt-10 text-[var(--muted)] text-xs">
          &copy; {new Date().getFullYear()} DingDawg &mdash; Universal AI Agent Platform
        </p>
      </div>
    </div>
  );
}
