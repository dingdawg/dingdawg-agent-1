import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Analytics",
  description:
    "View your AI agent performance analytics. Track conversations, messages, skill usage, and revenue metrics on DingDawg.",
};

export default function AnalyticsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
