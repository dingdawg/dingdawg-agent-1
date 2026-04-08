"use client";

/**
 * Chat message bubble with governance badge, feedback, and error/retry state.
 */

import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/utils";
import type { ChatMessage } from "@/store/chatStore";
import { Shield, ShieldAlert, ShieldOff, AlertCircle, RotateCcw } from "lucide-react";
import MarkdownRenderer from "./MarkdownRenderer";
import { MessageFeedback } from "./MessageFeedback";

interface MessageBubbleProps {
  message: ChatMessage;
  onRetry?: (messageId: string) => void;
}

function GovernanceBadge({
  decision,
  risk,
}: {
  decision: string;
  risk?: string;
}) {
  const config = {
    PROCEED: {
      icon: Shield,
      color: "text-green-400",
      bg: "bg-green-400/10",
    },
    REVIEW: {
      icon: ShieldAlert,
      color: "text-yellow-400",
      bg: "bg-yellow-400/10",
    },
    HALT: {
      icon: ShieldOff,
      color: "text-red-400",
      bg: "bg-red-400/10",
    },
  }[decision] ?? {
    icon: Shield,
    color: "text-gray-400",
    bg: "bg-gray-400/10",
  };

  const Icon = config.icon;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs",
        config.color,
        config.bg
      )}
    >
      <Icon className="h-3 w-3" />
      {decision}
      {risk && <span className="opacity-60">({risk})</span>}
    </span>
  );
}

export function MessageBubble({ message, onRetry }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";
  const isError = message.status === "error";
  const isStreaming = message.status === "streaming";
  const isAssistant = message.role === "assistant";

  if (isSystem) {
    return (
      <div className="flex justify-center my-2">
        <span className="text-xs text-[var(--color-muted)] bg-white/5 px-3 py-1 rounded-full">
          {message.content}
        </span>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex flex-col gap-1 mb-4 group",
        isUser ? "items-end" : "items-start"
      )}
    >
      <div
        className={cn(
          "dd-chat-bubble",
          isUser ? "user user-glow" : "assistant",
          isError && "border border-red-500/50"
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap break-words text-[15px] font-body leading-relaxed">
            {message.content}
          </p>
        ) : isError ? (
          /* ── Error state with inline retry ── */
          <div className="flex flex-col gap-2" role="alert" aria-live="assertive">
            <div className="flex items-start gap-2 text-red-400">
              <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
              <p className="text-[15px] font-body leading-relaxed">
                {message.content}
              </p>
            </div>
            {onRetry && (
              <button
                onClick={() => onRetry(message.id)}
                className={cn(
                  "self-start flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium",
                  "bg-white/5 hover:bg-white/10 text-[var(--foreground)] transition-colors",
                  "min-h-[44px]"
                )}
              >
                <RotateCcw className="h-3 w-3" />
                Retry
              </button>
            )}
          </div>
        ) : (
          <div className="text-[15px] font-body leading-relaxed">
            <MarkdownRenderer content={message.content} />
            {isStreaming && (
              <span className="inline-block w-1 h-4 ml-0.5 bg-current animate-pulse" />
            )}
          </div>
        )}
      </div>

      {/* Metadata row + feedback */}
      <div
        className={cn(
          "flex items-center gap-2 px-1 text-xs text-[var(--color-muted)]",
          isUser ? "flex-row-reverse" : "flex-row"
        )}
      >
        <span>{formatRelativeTime(new Date(message.timestamp))}</span>

        {message.governance_decision && (
          <GovernanceBadge
            decision={message.governance_decision}
            risk={message.governance_risk}
          />
        )}

        {message.model && (
          <span className="opacity-60">{message.model}</span>
        )}

        {message.tokens_used != null && message.tokens_used > 0 && (
          <span className="opacity-60">{message.tokens_used} tokens</span>
        )}

        {/* Feedback buttons — only on finalized assistant messages */}
        {isAssistant && message.status === "final" && (
          <MessageFeedback messageId={message.id} />
        )}
      </div>
    </div>
  );
}
