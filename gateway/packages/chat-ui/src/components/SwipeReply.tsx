"use client";

/**
 * SwipeReply — Swipe-to-reply gesture wrapper.
 *
 * Wraps any chat message content. On horizontal swipe exceeding
 * SWIPE_THRESHOLD (80px), fires onReply(messageId). Below the threshold,
 * the touch is treated as a cancelled gesture and reverts.
 *
 * Supports:
 *   - Touch events (mobile)
 *   - Optional quotedContent to show a preview of the message being replied to
 *   - Visual translate feedback during drag
 *
 * Does NOT handle pointer events (mouse swipe) — chat is mobile-first.
 * Mouse users see the quoted preview via other UI.
 */

import { useRef, useState, useCallback } from "react";
import styles from "../styles/chat.module.css";

const SWIPE_THRESHOLD = 80; // px — minimum horizontal distance to trigger reply
const MAX_TRANSLATE = 100; // px — maximum visual feedback distance

interface SwipeReplyProps {
  messageId: string;
  onReply: (messageId: string) => void;
  children: React.ReactNode;
  /** Content of the message being replied to (shows preview bar). */
  quotedContent?: string;
  /** Whether swipe gesture is enabled. Default: true */
  enabled?: boolean;
}

export function SwipeReply({
  messageId,
  onReply,
  children,
  quotedContent,
  enabled = true,
}: SwipeReplyProps) {
  const touchStartX = useRef<number>(0);
  const touchStartY = useRef<number>(0);
  const [translateX, setTranslateX] = useState(0);
  const triggered = useRef(false);

  const handleTouchStart = useCallback(
    (e: React.TouchEvent<HTMLDivElement>) => {
      if (!enabled) return;
      touchStartX.current = e.touches[0].clientX;
      touchStartY.current = e.touches[0].clientY;
      triggered.current = false;
    },
    [enabled]
  );

  const handleTouchMove = useCallback(
    (e: React.TouchEvent<HTMLDivElement>) => {
      if (!enabled) return;
      const deltaX = e.touches[0].clientX - touchStartX.current;
      const deltaY = e.touches[0].clientY - touchStartY.current;

      // If vertical movement dominates, treat as scroll — don't intercept
      if (Math.abs(deltaY) > Math.abs(deltaX) * 1.5) return;

      // Only allow rightward swipe
      if (deltaX > 0) {
        const clamped = Math.min(deltaX, MAX_TRANSLATE);
        setTranslateX(clamped);
      }
    },
    [enabled]
  );

  const handleTouchEnd = useCallback(
    (e: React.TouchEvent<HTMLDivElement>) => {
      if (!enabled) {
        setTranslateX(0);
        return;
      }

      const deltaX = e.changedTouches[0].clientX - touchStartX.current;

      if (deltaX >= SWIPE_THRESHOLD && !triggered.current) {
        triggered.current = true;
        onReply(messageId);
      }

      // Always reset visual position
      setTranslateX(0);
    },
    [enabled, messageId, onReply]
  );

  return (
    <div
      className={styles.swipeContainer}
      style={{ transform: `translateX(${translateX}px)` }}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
    >
      {/* Quote preview bar — shows when a quotedContent is provided */}
      {quotedContent && (
        <div className={styles.quotePreview}>{quotedContent}</div>
      )}
      {children}
    </div>
  );
}
