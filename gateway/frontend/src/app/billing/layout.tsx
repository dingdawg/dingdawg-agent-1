import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Billing & Plans",
  description:
    "Manage your DingDawg subscription plan and billing. View usage, upgrade or downgrade plans, and track action history.",
};

export default function BillingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
