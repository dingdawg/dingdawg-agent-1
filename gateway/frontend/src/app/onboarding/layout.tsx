/**
 * Onboarding route layout — SEO metadata for the new-user onboarding wizard.
 *
 * Server component wrapper required because the page itself is "use client".
 * Follows the same pattern as /claim/layout.tsx.
 */

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Welcome to DingDawg — Set Up Your Agent",
  description:
    "Create your AI business agent in under 5 minutes. Name it, pick your industry, see it in action, then go live.",
};

export default function OnboardingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
