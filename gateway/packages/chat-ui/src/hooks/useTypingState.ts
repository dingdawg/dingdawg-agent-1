/**
 * useTypingState — Typing indicator state with debounced auto-clear.
 *
 * Call onKeyPress() every time the local user presses a key.
 * The hook sets isTyping=true immediately and auto-clears after
 * debounceMs of inactivity (default: 2000ms).
 *
 * Also exposes setTyping() for manual control (e.g., when the remote
 * party's typing status arrives via WebSocket).
 *
 * Usage:
 *   const { isTyping, onKeyPress, setTyping } = useTypingState();
 *   // In ChatInput: onChange={() => onKeyPress()}
 *   // Show TypingIndicator: <TypingIndicator visible={isTyping} />
 */

import { useState, useRef, useCallback } from "react";

interface UseTypingStateOptions {
  /** Milliseconds of inactivity after which typing auto-clears. Default: 2000 */
  debounceMs?: number;
}

interface UseTypingStateReturn {
  isTyping: boolean;
  setTyping: (typing: boolean) => void;
  onKeyPress: () => void;
}

export function useTypingState(
  options: UseTypingStateOptions = {}
): UseTypingStateReturn {
  const { debounceMs = 2000 } = options;
  const [isTyping, setIsTyping] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const setTyping = useCallback((typing: boolean) => {
    setIsTyping(typing);
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const onKeyPress = useCallback(() => {
    setIsTyping(true);

    // Reset debounce timer on every keypress
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }
    timerRef.current = setTimeout(() => {
      setIsTyping(false);
      timerRef.current = null;
    }, debounceMs);
  }, [debounceMs]);

  return { isTyping, setTyping, onKeyPress };
}
