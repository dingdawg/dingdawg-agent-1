"use client";

/**
 * TypingIndicator — iMessage-style three bouncing dots.
 *
 * Renders inside an assistant-style bubble. Uses CSS keyframe animation
 * defined in chat.module.css (chatTypingBounce). Each dot has a staggered
 * animation delay to produce the cascading bounce effect.
 *
 * Accessibility: aria-live="polite" lets screen readers announce
 * "Agent is typing" when the indicator appears.
 */

import styles from "../styles/chat.module.css";

interface TypingIndicatorProps {
  /** Whether the indicator is visible. When false, nothing is rendered. */
  visible: boolean;
  /** Custom aria-label for the live region. Default: "Agent is typing" */
  ariaLabel?: string;
}

export function TypingIndicator({
  visible,
  ariaLabel = "Agent is typing",
}: TypingIndicatorProps) {
  return (
    <div aria-live="polite" aria-atomic="true" aria-label={ariaLabel}>
      {visible && (
        <div
          className={`${styles.messageRow} ${styles.messageRowAssistant}`}
          style={{ paddingBottom: "8px" }}
        >
          <div className={styles.typingBubble} role="status">
            <span
              className={`${styles.typingDot} animate-bounce`}
              data-testid="typing-dot"
              aria-hidden="true"
              style={{ animationDelay: "0s" }}
            />
            <span
              className={`${styles.typingDot} animate-bounce`}
              data-testid="typing-dot"
              aria-hidden="true"
              style={{ animationDelay: "0.2s" }}
            />
            <span
              className={`${styles.typingDot} animate-bounce`}
              data-testid="typing-dot"
              aria-hidden="true"
              style={{ animationDelay: "0.4s" }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
