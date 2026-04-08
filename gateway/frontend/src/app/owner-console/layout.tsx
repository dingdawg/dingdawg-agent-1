/**
 * Owner Console layout — auth-gated to admin email only.
 * robots: noindex — must never appear in search results.
 */
import type { Metadata } from "next";
import AdminRoute from "@/components/auth/AdminRoute";

export const metadata: Metadata = {
  title: "Owner Console — DingDawg",
  robots: { index: false, follow: false },
};

export default function OwnerConsoleLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <AdminRoute>{children}</AdminRoute>;
}
