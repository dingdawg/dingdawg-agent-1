/**
 * Claim route layout — provides SEO metadata for the claim wizard.
 *
 * The claim page itself is "use client" so metadata cannot be exported there
 * directly; this server-component layout is the correct Next.js App Router
 * pattern for adding metadata to a client-only page.
 */

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Claim Your Agent",
  description:
    "Set up your AI business agent in 4 easy steps. Choose your type, pick a template, claim your @handle, and go live.",
};

export default function ClaimLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
