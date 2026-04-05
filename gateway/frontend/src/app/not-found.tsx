import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Page Not Found",
  description: "The page you were looking for could not be found.",
};

export default function NotFound() {
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
          404
        </h1>

        {/* Heading */}
        <h2 className="text-2xl font-semibold text-white mb-3 font-heading">
          Page not found
        </h2>

        {/* Body copy */}
        <p className="text-[var(--muted)] text-base leading-relaxed mb-8">
          The page you&apos;re looking for doesn&apos;t exist or has been moved.
          Head back to your dashboard to continue.
        </p>

        {/* CTA */}
        <Link
          href="/dashboard"
          className="inline-flex items-center justify-center gap-2 px-8 py-3
                     bg-[var(--gold-500)] text-[var(--ink-950)] font-semibold
                     text-base rounded-lg hover:bg-[var(--gold-600)]
                     transition-colors focus-visible:outline-none
                     focus-visible:ring-2 focus-visible:ring-[var(--gold-500)]"
        >
          Return to Dashboard
        </Link>

        {/* Footer brand */}
        <p className="mt-10 text-[var(--muted)] text-xs">
          &copy; {new Date().getFullYear()} DingDawg &mdash; Universal AI Agent Platform
        </p>
      </div>
    </div>
  );
}
