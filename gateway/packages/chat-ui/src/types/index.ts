/**
 * @dingdawg/chat-ui — Core type definitions.
 *
 * These types are the data contract for all chat-ui components.
 * Both Agent 1 and DD Main frontends must use these types.
 */

/** Delivery state for a chat message. */
export type DeliveryStatus =
  | "sending"   // optimistic — message queued locally
  | "sent"      // server acknowledged receipt
  | "delivered" // remote device received
  | "read"      // recipient opened/read
  | "failed";   // delivery failed (show retry UI)

/** Data for embedded agent cards inside messages. */
export interface CardData {
  type: "kpi-cards" | "task-card" | "task-list" | "agent-status" | "quick-replies";
  [key: string]: unknown;
}

/** Core chat message shape for the @dingdawg/chat-ui package. */
export interface ChatMessage {
  id: string;
  content: string;
  role: "user" | "assistant" | "system";
  /** Unix timestamp in milliseconds. */
  timestamp: number;
  deliveryStatus: DeliveryStatus;
  /** ID of the message this replies to, for quote-reply. */
  replyTo?: string;
  /** Embedded card data rendered below the text bubble. */
  cards?: CardData[];
}

/** Configuration for the ChatUI components. */
export interface ChatUIConfig {
  /** Minimum touch target size in px. Default: 48 */
  touchTargetSize?: number;
  /** Enable swipe-to-reply gesture. Default: true */
  enableSwipeReply?: boolean;
  /** Enable iMessage-style typing indicator. Default: true */
  enableTypingIndicator?: boolean;
  /** Enable sent/delivered/read delivery indicators. Default: true */
  enableDeliveryStatus?: boolean;
  /** Color theme. Default: 'system' */
  theme?: "light" | "dark" | "system";
}

/** State returned by useDeliveryStatus hook. */
export interface DeliveryStatusState {
  status: DeliveryStatus;
  setStatus: (status: DeliveryStatus) => void;
  transition: (next: DeliveryStatus) => void;
}

/** State returned by useTypingState hook. */
export interface TypingState {
  isTyping: boolean;
  setTyping: (typing: boolean) => void;
  /** Notify the hook that local user is typing (debounces automatic clear). */
  onKeyPress: () => void;
}

/** Swipe direction for SwipeReply. */
export type SwipeDirection = "left" | "right";

/** Props for the SwipeReply trigger callback. */
export interface SwipeReplyEvent {
  messageId: string;
  direction: SwipeDirection;
}
