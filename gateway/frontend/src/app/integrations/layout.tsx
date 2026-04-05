import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Integrations",
  description:
    "Connect your DingDawg AI agent to external services. Google Calendar, SendGrid, Twilio, Vapi, webhooks, and more.",
};

export default function IntegrationsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
