"use client";

/**
 * ChatInput — Enhanced textarea input for SMS-like chat.
 *
 * =====================================================================
 * UI LOCK: The following classes on <textarea> are SACRED and MUST NOT
 * be removed or modified:
 *   flex-1  w-full  min-w-0  text-base
 * They are required by the DingDawg UI Lock (ChatInput.tsx invariants).
 * =====================================================================
 *
 * Behavior:
 *   - Enter to send
 *   - Shift+Enter for newline
 *   - Auto-resize textarea up to 160px
 *   - 48px send button (min touch target)
 *   - Haptic feedback via navigator.vibrate (10ms)
 *   - Disabled state fully prevents sending
 */

import { useState, useRef, useCallback } from "react";
import { Send } from "lucide-react";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
  /** Additional CSS class on the outer wrapper. */
  className?: string;
}

export function ChatInput({
  onSend,
  disabled = false,
  placeholder = "Type a message...",
  className,
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    // Haptic feedback (preserved from original ChatInput)
    if (navigator.vibrate) navigator.vibrate(10);
    onSend(trimmed);
    setValue("");
    // Reset textarea height (preserved from original ChatInput)
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [value, disabled, onSend]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends — Shift+Enter newline (preserved from original ChatInput)
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    // Auto-resize textarea (preserved from original ChatInput)
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  };

  return (
    <div
      className={[
        "flex items-end gap-3 px-4 py-3",
        "border-t border-[var(--color-gold-stroke,#2a3a4a)]",
        "bg-[var(--glass,rgba(255,255,255,0.05))] backdrop-blur-xl",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {/*
       * ===== UI LOCK =====
       * These classes are SACRED: flex-1 w-full min-w-0 text-base
       * DO NOT remove or rename them. This is enforced by the DingDawg
       * UI Lock and the Agent Preamble stop rules.
       * ===================
       */}
      <textarea
        ref={textareaRef}
        value={value}
        onChange={handleInput}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder={placeholder}
        rows={1}
        aria-label="Message input"
        className={[
          // ── UI LOCK CLASSES (SACRED) ──
          "flex-1 w-full min-w-0 text-base",
          // ── Additional styling ──
          "font-sans",
          "resize-none",
          "bg-white/5 border border-[var(--color-gold-stroke,#2a3a4a)] rounded-2xl",
          "px-5 py-3 text-[var(--foreground,#e2e8f0)]",
          "placeholder:text-[var(--color-muted,#64748b)]",
          "focus:outline-none focus:ring-2 focus:ring-[var(--gold-500,#f6b400)] focus:border-transparent",
          "disabled:opacity-50 disabled:cursor-not-allowed",
          "scrollbar-thin",
        ].join(" ")}
      />
      <button
        onClick={handleSend}
        disabled={disabled || !value.trim()}
        aria-label="Send message"
        style={{ minHeight: "48px", minWidth: "48px" }}
        className={[
          // 48px touch target: h-12 w-12 = 48px
          "flex-shrink-0 h-12 w-12 rounded-2xl",
          "flex items-center justify-center",
          "bg-[var(--gold-500,#f6b400)] text-[#07111c]",
          "hover:bg-[var(--gold-600,#d4a000)] active:scale-95 transition-all",
          "disabled:opacity-40 disabled:cursor-not-allowed",
          "shadow-[0_0_20px_rgba(246,180,0,0.15)]",
        ].join(" ")}
      >
        <Send className="h-5 w-5" aria-hidden="true" />
      </button>
    </div>
  );
}
