/**
 * Admin layout — wraps all /admin/* routes with auth gate and shell.
 *
 * AdminRoute: redirects non-admin users to /dashboard
 * AdminShell: renders header + bottom tab bar + desktop sidebar
 * AdminErrorBoundary: catches render-time exceptions so Safari shows a
 *   readable error panel instead of a blank "Application error" screen.
 *
 * robots: noindex/nofollow — admin UI must never appear in search results.
 */

import type { Metadata } from "next";
import AdminRoute from "@/components/auth/AdminRoute";
import AdminShell from "@/components/layout/AdminShell";
import { AdminErrorBoundary } from "@/components/admin/AdminErrorBoundary";

export const metadata: Metadata = {
  title: "Command Center",
  robots: { index: false, follow: false },
};

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AdminErrorBoundary>
      <AdminRoute>
        <AdminShell>{children}</AdminShell>
      </AdminRoute>
    </AdminErrorBoundary>
  );
}
