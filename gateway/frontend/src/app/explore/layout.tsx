import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Explore AI Agents",
  description:
    "Browse and discover AI business agents on DingDawg. Filter by category and industry to find the right agent for your needs.",
};

export default function ExploreLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
