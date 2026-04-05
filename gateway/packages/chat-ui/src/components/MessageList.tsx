"use client";

/**
 * MessageList — react-virtuoso powered scrolling chat message list.
 *
 * Uses Virtuoso for virtual DOM rendering — keeps memory flat even at
 * 1000+ messages. followOutput="smooth" auto-scrolls on new messages
 * and automatically pauses when the user scrolls up.
 *
 * Renders:
 *   - ChatBubble for each message
 *   - TypingIndicator in the Footer when isStreaming=true
 *   - Empty state placeholder when messages array is empty
 *
 * Props match the shape used by Agent 1's ChatStream for easy migration.
 */

import { useCallback } from "react";
import { Virtuoso } from "react-virtuoso";
import type { ChatMessage } from "../types";
import { ChatBubble } from "./ChatBubble";
import { TypingIndicator } from "./TypingIndicator";

interface MessageListProps {
  messages: ChatMessage[];
  isStreaming?: boolean;
  onQuickReply?: (reply: string) => void;
  /** Custom className on the Virtuoso root. */
  className?: string;
  /** Custom empty state label. Default: "DingDawg Agent" headline. */
  emptyStateHeadline?: string;
  emptyStateBody?: string;
}

export function MessageList({
  messages,
  isStreaming = false,
  className,
  emptyStateHeadline = "DingDawg Agent",
  emptyStateBody = "Your personal AI assistant. Ask me anything or use the quick actions below.",
}: MessageListProps) {
  /** Per-item renderer for Virtuoso */
  const itemContent = useCallback(
    (index: number) => {
      const message = messages[index];
      return (
        <div style={{ padding: "2px 0" }}>
          <ChatBubble
            message={message}
            isStreaming={isStreaming && index === messages.length - 1}
          />
        </div>
      );
    },
    [messages, isStreaming]
  );

  /** Empty state shown when no messages exist */
  const EmptyPlaceholder = useCallback(
    () => (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          height: "100%",
          textAlign: "center",
          padding: "16px",
        }}
      >
        <div
          style={{
            width: "64px",
            height: "64px",
            borderRadius: "16px",
            background: "rgba(246,180,0,0.1)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            marginBottom: "16px",
          }}
        >
          <span
            style={{
              fontSize: "1.5rem",
              fontWeight: "bold",
              color: "var(--gold-500, #f6b400)",
            }}
          >
            D
          </span>
        </div>
        <h2
          style={{
            fontSize: "1.125rem",
            fontWeight: "600",
            marginBottom: "4px",
            color: "var(--foreground, #e2e8f0)",
          }}
        >
          {emptyStateHeadline}
        </h2>
        <p
          style={{
            fontSize: "0.875rem",
            color: "var(--color-muted, #64748b)",
            maxWidth: "280px",
          }}
        >
          {emptyStateBody}
        </p>
      </div>
    ),
    [emptyStateHeadline, emptyStateBody]
  );

  /** Footer: typing indicator below the virtual list */
  const Footer = useCallback(
    () => (
      <TypingIndicator visible={isStreaming} />
    ),
    [isStreaming]
  );

  return (
    <Virtuoso
      role="log"
      aria-live="polite"
      aria-label="Chat messages"
      className={className}
      style={{ flex: 1 }}
      data={messages}
      totalCount={messages.length}
      itemContent={itemContent}
      followOutput="smooth"
      alignToBottom
      components={{
        EmptyPlaceholder,
        Footer,
      }}
      initialTopMostItemIndex={messages.length > 0 ? messages.length - 1 : 0}
    />
  );
}
