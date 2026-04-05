"use client";

/**
 * IntegrationConnectCard — renders inline in the chat stream
 * when the user asks to connect a service.
 *
 * Shows a friendly card with the integration name, description,
 * and a one-tap connect button. Triggers Nango OAuth or
 * a simple input form depending on the integration type.
 *
 * Usage in chat:
 *   User: "connect my google calendar"
 *   Agent: "Let me help you connect your calendar."
 *          [IntegrationConnectCard: Google Calendar — Sign in with Google]
 */

import { useState } from "react";
import {
  CheckCircle,
  Loader2,
  Calendar,
  Phone,
  Mail,
  Zap,
  CreditCard,
  Link2,
} from "lucide-react";
import { cn } from "@/lib/utils";

export interface IntegrationConnectData {
  integrationId: string;
  name: string;
  description: string;
  actionLabel: string;
  type: "oauth" | "phone" | "email" | "api_key";
  icon?: string;
  connected?: boolean;
}

interface IntegrationConnectCardProps {
  data: IntegrationConnectData;
  onConnect: (integrationId: string, inputValue?: string) => void;
}

const ICON_MAP: Record<string, typeof Calendar> = {
  google_calendar: Calendar,
  microsoft_calendar: Calendar,
  apple_calendar: Calendar,
  cronofy: Calendar,
  twilio: Phone,
  vapi: Phone,
  sendgrid: Mail,
  zapier: Zap,
  stripe: CreditCard,
};

export function IntegrationConnectCard({
  data,
  onConnect,
}: IntegrationConnectCardProps) {
  const [isConnecting, setIsConnecting] = useState(false);
  const [isConnected, setIsConnected] = useState(data.connected ?? false);
  const [inputValue, setInputValue] = useState("");
  const [inputError, setInputError] = useState("");

  const IconComponent = ICON_MAP[data.integrationId] || Link2;
  const needsInput = data.type === "phone" || data.type === "email";

  async function handleConnect() {
    if (needsInput && !inputValue.trim()) {
      setInputError(
        data.type === "phone" ? "Enter your phone number" : "Enter your email"
      );
      return;
    }

    if (data.type === "phone" && inputValue) {
      const cleaned = inputValue.replace(/\D/g, "");
      if (cleaned.length < 10) {
        setInputError("Enter a valid phone number (10+ digits)");
        return;
      }
    }

    if (data.type === "email" && inputValue) {
      if (!inputValue.includes("@") || !inputValue.includes(".")) {
        setInputError("Enter a valid email address");
        return;
      }
    }

    setInputError("");
    setIsConnecting(true);

    try {
      await onConnect(data.integrationId, inputValue || undefined);
      setIsConnected(true);
    } catch {
      setInputError("Connection failed. Try again.");
    } finally {
      setIsConnecting(false);
    }
  }

  if (isConnected) {
    return (
      <div className="glass-panel p-4 max-w-sm">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-xl bg-green-500/10 border border-green-500/20 flex items-center justify-center flex-shrink-0">
            <CheckCircle className="h-5 w-5 text-green-400" />
          </div>
          <div>
            <p className="text-sm font-medium text-[var(--foreground)]">
              {data.name} connected
            </p>
            <p className="text-xs text-green-400">
              Your agent can now use this service
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="glass-panel p-4 max-w-sm">
      {/* Header */}
      <div className="flex items-start gap-3 mb-3">
        <div className="h-10 w-10 rounded-xl bg-[var(--gold-500)]/10 border border-[var(--gold-500)]/20 flex items-center justify-center flex-shrink-0">
          {data.icon ? (
            <span className="text-xl">{data.icon}</span>
          ) : (
            <IconComponent className="h-5 w-5 text-[var(--gold-500)]" />
          )}
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-[var(--foreground)]">
            {data.name}
          </p>
          <p className="text-xs text-[var(--color-muted)] leading-relaxed mt-0.5">
            {data.description}
          </p>
        </div>
      </div>

      {/* Input for phone/email */}
      {needsInput && (
        <div className="mb-3">
          <input
            type={data.type === "phone" ? "tel" : "email"}
            value={inputValue}
            onChange={(e) => {
              setInputValue(e.target.value);
              setInputError("");
            }}
            onKeyDown={(e) => e.key === "Enter" && handleConnect()}
            placeholder={
              data.type === "phone"
                ? "(555) 123-4567"
                : "you@business.com"
            }
            className={cn(
              "w-full px-3 py-2.5 rounded-lg text-sm",
              "bg-white/5 border text-[var(--foreground)]",
              "placeholder:text-[var(--color-muted)]",
              "focus:outline-none focus:ring-2 focus:ring-[var(--gold-500)]",
              inputError
                ? "border-red-400/50"
                : "border-[var(--stroke)]"
            )}
            aria-label={
              data.type === "phone" ? "Phone number" : "Email address"
            }
          />
          {inputError && (
            <p className="text-xs text-red-400 mt-1">{inputError}</p>
          )}
        </div>
      )}

      {/* Connect button */}
      <button
        onClick={handleConnect}
        disabled={isConnecting}
        className={cn(
          "w-full py-2.5 px-4 rounded-lg text-sm font-semibold transition-colors",
          "flex items-center justify-center gap-2",
          "bg-[var(--gold-500)] text-[#07111c]",
          "hover:bg-[var(--gold-600)] hover:brightness-110",
          "disabled:opacity-50 disabled:cursor-not-allowed",
          "min-h-[44px]"
        )}
      >
        {isConnecting ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Connecting...
          </>
        ) : (
          data.actionLabel
        )}
      </button>
    </div>
  );
}
