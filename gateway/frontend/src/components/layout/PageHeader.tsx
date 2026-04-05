"use client";

/**
 * PageHeader — Consistent back-navigation header for all sub-pages.
 *
 * SaaS best practice: every page should have a clear way to go back
 * to the dashboard or parent page. This component provides:
 * - Back arrow (left) linking to parent or dashboard
 * - Page title
 * - Optional right-side actions
 *
 * Usage:
 *   <PageHeader title="Billing" backHref="/dashboard" />
 *   <PageHeader title="Client Details" backHref="/operations" backLabel="Operations" />
 */

import Link from "next/link";
import { ChevronLeft } from "lucide-react";

interface PageHeaderProps {
  title: string;
  backHref?: string;
  backLabel?: string;
  children?: React.ReactNode;
}

export function PageHeader({
  title,
  backHref = "/dashboard",
  backLabel = "Dashboard",
  children,
}: PageHeaderProps) {
  return (
    <div className="flex items-center justify-between gap-3 mb-6">
      <div className="flex items-center gap-2 min-w-0">
        <Link
          href={backHref}
          className="flex items-center gap-1 text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors flex-shrink-0"
          aria-label={`Back to ${backLabel}`}
        >
          <ChevronLeft className="h-4 w-4" />
          <span className="hidden sm:inline">{backLabel}</span>
        </Link>
        <span className="text-[var(--stroke)] hidden sm:inline">/</span>
        <h1 className="text-lg font-semibold text-[var(--foreground)] truncate">
          {title}
        </h1>
      </div>
      {children && (
        <div className="flex items-center gap-2 flex-shrink-0">
          {children}
        </div>
      )}
    </div>
  );
}
