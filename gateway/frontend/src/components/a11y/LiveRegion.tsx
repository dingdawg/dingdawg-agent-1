"use client";

/**
 * LiveRegion.tsx — React component wrapper for ARIA live regions.
 *
 * Renders an `aria-live` element that announces its content to screen readers
 * when the `message` prop changes. The region is visually hidden.
 *
 * Use this component when you need a reactive live region in JSX rather than
 * the imperative `announce()` utility.
 *
 * Usage:
 *   <LiveRegion message={status} />
 *   <LiveRegion message={errorMessage} priority="assertive" />
 *   <LiveRegion message={toast} clearAfter={4000} />
 *
 * Priority:
 *   "polite"    — Screen reader announces after current speech finishes.
 *                 Use for: status updates, success messages, progress.
 *   "assertive" — Screen reader interrupts current speech immediately.
 *                 Use for: errors, warnings, critical alerts.
 *
 * WCAG 4.1.3 — Status Messages
 * WCAG 1.3.1 — Info and Relationships
 */

import { useState, useEffect, useRef } from "react";

interface LiveRegionProps {
  /** Message to announce to screen readers. */
  message: string;
  /** Announcement priority. Default: "polite". */
  priority?: "polite" | "assertive";
  /**
   * Automatically clear the message after this many milliseconds.
   * Useful for toast-style announcements. Set to 0 to disable (default).
   */
  clearAfter?: number;
  /** Additional class names for the region element. */
  className?: string;
}

export function LiveRegion({
  message,
  priority = "polite",
  clearAfter = 0,
  className,
}: LiveRegionProps) {
  const [displayMessage, setDisplayMessage] = useState(message);
  const clearTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // Clear any pending auto-clear timer
    if (clearTimerRef.current !== null) {
      clearTimeout(clearTimerRef.current);
      clearTimerRef.current = null;
    }

    // Update the displayed message.
    // Brief clear → set cycle ensures screen readers detect the change even
    // when the new message is identical to the old one.
    setDisplayMessage("");

    const updateTimer = setTimeout(() => {
      setDisplayMessage(message);

      // Auto-clear after the specified duration
      if (clearAfter > 0) {
        clearTimerRef.current = setTimeout(() => {
          setDisplayMessage("");
          clearTimerRef.current = null;
        }, clearAfter);
      }
    }, 50);

    return () => {
      clearTimeout(updateTimer);
      if (clearTimerRef.current !== null) {
        clearTimeout(clearTimerRef.current);
        clearTimerRef.current = null;
      }
    };
  }, [message, clearAfter]);

  return (
    <div
      aria-live={priority}
      aria-atomic="true"
      aria-relevant="additions text"
      className={className}
      /**
       * Visually hidden — keeps the region out of visual flow but accessible
       * to screen readers. We use inline styles as a guarantee since Tailwind
       * purging may strip unused classes in the final bundle.
       */
      style={{
        position: "absolute",
        width: "1px",
        height: "1px",
        padding: 0,
        margin: "-1px",
        overflow: "hidden",
        clip: "rect(0 0 0 0)",
        clipPath: "inset(50%)",
        whiteSpace: "nowrap",
        borderWidth: 0,
      }}
    >
      {displayMessage}
    </div>
  );
}
