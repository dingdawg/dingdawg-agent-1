"use client";

/**
 * MessageFeedback — thumbs up/down rating for assistant messages.
 * Visible on hover via group-hover pattern.
 * Calls POST /api/v1/feedback with message_id and rating.
 * Optimistic update: fills the icon immediately on click.
 */

import { useState, useCallback } from "react";
import { ThumbsUp, ThumbsDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { post } from "@/services/api/client";

interface MessageFeedbackProps {
  messageId: string;
}

type Rating = "up" | "down" | null;

export function MessageFeedback({ messageId }: MessageFeedbackProps) {
  const [rating, setRating] = useState<Rating>(null);

  const handleRate = useCallback(
    async (value: "up" | "down") => {
      // Optimistic update
      setRating((prev) => (prev === value ? null : value));

      try {
        await post("/api/v1/feedback", {
          message_id: messageId,
          rating: value,
        });
      } catch {
        // Silently revert on failure — feedback is non-critical
        setRating((prev) => (prev === value ? null : prev));
      }
    },
    [messageId]
  );

  return (
    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
      <button
        onClick={() => handleRate("up")}
        aria-label="Helpful"
        className={cn(
          "min-h-[44px] min-w-[44px] flex items-center justify-center rounded-lg transition-colors",
          rating === "up"
            ? "text-[var(--color-success)]"
            : "text-[var(--color-muted)] hover:text-[var(--foreground)] hover:bg-white/5"
        )}
      >
        <ThumbsUp
          className="h-3.5 w-3.5"
          fill={rating === "up" ? "currentColor" : "none"}
        />
      </button>
      <button
        onClick={() => handleRate("down")}
        aria-label="Not helpful"
        className={cn(
          "min-h-[44px] min-w-[44px] flex items-center justify-center rounded-lg transition-colors",
          rating === "down"
            ? "text-[var(--color-danger)]"
            : "text-[var(--color-muted)] hover:text-[var(--foreground)] hover:bg-white/5"
        )}
      >
        <ThumbsDown
          className="h-3.5 w-3.5"
          fill={rating === "down" ? "currentColor" : "none"}
        />
      </button>
    </div>
  );
}
