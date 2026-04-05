/**
 * useChatScroll — Auto-scroll management for chat lists.
 *
 * Returns a bottomRef to attach to the last element in a message list,
 * and a scrollToBottom() function to imperatively scroll to it.
 *
 * Usage:
 *   const { bottomRef, scrollToBottom } = useChatScroll();
 *   // Attach bottomRef to a div at the bottom of your message list
 *   // Call scrollToBottom() when new messages arrive
 *
 * Note: When using react-virtuoso's followOutput="smooth", this hook
 * is supplementary — Virtuoso handles auto-scroll internally.
 * Use this hook for non-virtualized lists or custom scroll containers.
 */

import { useRef, useCallback } from "react";

interface UseChatScrollReturn {
  bottomRef: React.MutableRefObject<HTMLDivElement | null>;
  scrollToBottom: () => void;
}

export function useChatScroll(): UseChatScrollReturn {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const scrollToBottom = useCallback(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, []);

  return { bottomRef, scrollToBottom };
}
