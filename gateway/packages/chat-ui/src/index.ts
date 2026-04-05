/**
 * @dingdawg/chat-ui — Public API barrel export.
 *
 * Import from this package:
 *   import { ChatBubble, ChatInput, TypingIndicator } from '@dingdawg/chat-ui';
 *   import type { ChatMessage, DeliveryStatus } from '@dingdawg/chat-ui';
 */

// ─── Types ────────────────────────────────────────────────────────────────────
export type {
  ChatMessage,
  DeliveryStatus,
  CardData,
  ChatUIConfig,
  DeliveryStatusState,
  TypingState,
  SwipeDirection,
  SwipeReplyEvent,
} from "./types";

// ─── Components ───────────────────────────────────────────────────────────────
export { ChatBubble } from "./components/ChatBubble";
export { ChatInput } from "./components/ChatInput";
export { DeliveryStatus } from "./components/DeliveryStatus";
export { MessageList } from "./components/MessageList";
export { SwipeReply } from "./components/SwipeReply";
export { TypingIndicator } from "./components/TypingIndicator";

// ─── Hooks ────────────────────────────────────────────────────────────────────
export { useChatScroll } from "./hooks/useChatScroll";
export { useDeliveryStatus } from "./hooks/useDeliveryStatus";
export { useTypingState } from "./hooks/useTypingState";
