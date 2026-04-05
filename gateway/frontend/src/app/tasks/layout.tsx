import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Tasks",
  description:
    "Manage and track your AI agent tasks on DingDawg. Create, filter, and monitor task progress across all your agents.",
};

export default function TasksLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
