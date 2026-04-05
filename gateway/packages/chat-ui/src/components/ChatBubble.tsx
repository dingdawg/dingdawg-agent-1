"use client";

/**
 * ChatBubble — SMS-style message bubble.
 *
 * Design:
 *   - User messages: right-aligned, blue background
 *   - Assistant messages: left-aligned, gray background
 *   - System messages: centered pill
 *   - Timestamps below each bubble
 *   - Dark mode via CSS variables in chat.module.css
 */

import type { ChatMessage } from "../types";
import { DeliveryStatus } from "./DeliveryStatus";
import styles from "../styles/chat.module.css";

interface ChatBubbleProps {
  message: ChatMessage;
  /** Whether to show delivery status indicator (user messages only). Default: true */
  showDeliveryStatus?: boolean;
  /** Whether the message is currently streaming content. */
  isStreaming?: boolean;
}

/**
 * Format a unix-ms timestamp for display. Returns "just now", "5m ago", etc.
 */
function formatTimestamp(ms: number): string {
  const diffMs = Date.now() - ms;
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHrs = Math.floor(diffMin / 60);
  if (diffHrs < 24) return `${diffHrs}h ago`;
  const diffDays = Math.floor(diffHrs / 24);
  return `${diffDays}d ago`;
}

export function ChatBubble({
  message,
  showDeliveryStatus = true,
  isStreaming = false,
}: ChatBubbleProps) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  // ─── System message: centered pill ───────────────────────────────────────
  if (isSystem) {
    return (
      <div className={`${styles.messageRow} ${styles.messageRowSystem}`}>
        <span className={styles.systemPill}>{message.content}</span>
      </div>
    );
  }

  // ─── User / Assistant bubble ──────────────────────────────────────────────
  const rowClass = isUser ? styles.messageRowUser : styles.messageRowAssistant;
  const bubbleClass = isUser ? styles.bubbleUser : styles.bubbleAssistant;

  return (
    <div className={`${styles.messageRow} ${rowClass}`}>
      {/* Text bubble */}
      <div className={`${styles.bubble} ${bubbleClass}`}>
        {message.content}
        {isStreaming && <span className={styles.streamingCursor} aria-hidden="true" />}
      </div>

      {/* Metadata row: timestamp + delivery status */}
      <div className={styles.timestamp}>
        <time dateTime={new Date(message.timestamp).toISOString()}>
          {formatTimestamp(message.timestamp)}
        </time>
        {isUser && showDeliveryStatus && (
          <DeliveryStatus status={message.deliveryStatus} />
        )}
      </div>
    </div>
  );
}
