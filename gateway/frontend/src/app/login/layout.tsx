/**
 * Login route layout — provides SEO metadata for the sign-in page.
 *
 * The login page is "use client" so metadata cannot be exported there
 * directly; this server-component layout is the correct Next.js App Router
 * pattern for adding metadata to a client-only page.
 */

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Sign In",
  description: "Sign in to your DingDawg AI agent dashboard. Manage your agents, view analytics, and automate your business.",
};

export default function LoginLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
