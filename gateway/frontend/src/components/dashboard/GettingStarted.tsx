"use client";

/**
 * GettingStarted — dismissible onboarding banner for new agent owners.
 *
 * Shows when the agent has fewer than 5 conversations. Provides a
 * 4-item checklist with actionable links. Dismissed state persists
 * in localStorage so it survives page reloads.
 *
 * Design: gold-accent card, dark background, dismissible with X.
 * Disappears entirely once all items are checked OR user dismisses.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import { X, CheckCircle2, Circle, Settings, Plug, Share2, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

interface ChecklistItem {
  id: string;
  label: string;
  sublabel?: string;
  done: boolean;
  action: React.ReactNode;
}

interface GettingStartedProps {
  /** Agent @handle — used for the share link. */
  handle: string;
  /** Number of conversations the agent has had. Banner only shows when < 5. */
  conversationCount: number;
  /**
   * Called when the user clicks "focus chat". Parent can use this to focus
   * the chat textarea.
   */
  onFocusChat?: () => void;
  /** Whether the agent has customized name (not default). */
  hasCustomizedSettings?: boolean;
  /** Whether any integrations are connected. */
  hasIntegrations?: boolean;
  className?: string;
}

// ─── Storage key ─────────────────────────────────────────────────────────────

function storageKey(handle: string): string {
  return `dd_getting_started_dismissed_${handle}`;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function GettingStarted({
  handle,
  conversationCount,
  onFocusChat,
  hasCustomizedSettings = false,
  hasIntegrations = false,
  className,
}: GettingStartedProps) {
  // Track dismissed state — persisted in localStorage
  const [dismissed, setDismissed] = useState(false);
  const [mounted, setMounted] = useState(false);

  // Hydrate dismissed state from localStorage after mount (avoids SSR mismatch)
  useEffect(() => {
    setMounted(true);
    try {
      const saved = localStorage.getItem(storageKey(handle));
      if (saved === "1") setDismissed(true);
    } catch {
      // localStorage unavailable — ignore
    }
  }, [handle]);

  const handleDismiss = useCallback(() => {
    setDismissed(true);
    try {
      localStorage.setItem(storageKey(handle), "1");
    } catch {
      // ignore
    }
  }, [handle]);

  // Whether the checklist is fully done (auto-dismiss)
  const hasConversation = conversationCount >= 1;
  const allDone =
    hasCustomizedSettings && hasIntegrations && hasConversation;

  // Auto-dismiss when all items checked
  const autoDismissedRef = useRef(false);
  useEffect(() => {
    if (allDone && mounted && !autoDismissedRef.current) {
      autoDismissedRef.current = true;
      handleDismiss();
    }
  }, [allDone, mounted, handleDismiss]);

  // Collapse smoothly instead of removing from DOM (prevents CLS)
  const shouldHide = !mounted || dismissed || conversationCount >= 5;

  // ── Checklist items ────────────────────────────────────────────────────────

  const items: ChecklistItem[] = [
    {
      id: "settings",
      label: "Customize your agent",
      sublabel: "Set a name, personality, and goal",
      done: hasCustomizedSettings,
      action: (
        <Link
          href="/settings"
          className="text-[var(--gold-500)] hover:underline text-xs font-medium flex items-center gap-1"
        >
          <Settings className="h-3 w-3" />
          Open settings
        </Link>
      ),
    },
    {
      id: "integrations",
      label: "Connect integrations",
      sublabel: "Calendar, email, Slack, and more",
      done: hasIntegrations,
      action: (
        <Link
          href="/integrations"
          className="text-[var(--gold-500)] hover:underline text-xs font-medium flex items-center gap-1"
        >
          <Plug className="h-3 w-3" />
          Add integration
        </Link>
      ),
    },
    {
      id: "share",
      label: "Share your agent",
      sublabel: `Your public link: @${handle}`,
      done: false, // always actionable — user decides
      action: (
        <button
          type="button"
          onClick={() => {
            const url = `${window.location.origin}/agent/${handle}`;
            navigator.clipboard?.writeText(url).catch(() => {});
          }}
          className="text-[var(--gold-500)] hover:underline text-xs font-medium flex items-center gap-1"
        >
          <Share2 className="h-3 w-3" />
          Copy link
        </button>
      ),
    },
    {
      id: "chat",
      label: "Have your first conversation",
      sublabel: "Ask your agent anything",
      done: hasConversation,
      action: (
        <button
          type="button"
          onClick={onFocusChat}
          className="text-[var(--gold-500)] hover:underline text-xs font-medium flex items-center gap-1"
        >
          <MessageSquare className="h-3 w-3" />
          Start chatting
        </button>
      ),
    },
  ];

  const completedCount = items.filter((i) => i.done).length;

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div
      className={cn(
        "transition-all duration-300 overflow-hidden",
        shouldHide ? "max-h-0 opacity-0 pointer-events-none m-0 p-0 border-0" : "max-h-[500px] opacity-100"
      )}
    >
    <div
      className={cn(
        // Card shell — gold border, dark background
        "mx-3 mt-3 rounded-2xl border border-[var(--gold-500)]/30",
        "bg-[var(--ink-950)]",
        "shadow-[0_0_24px_rgba(246,180,0,0.06)]",
        className
      )}
      role="complementary"
      aria-label="Getting started guide"
    >
      {/* Header row */}
      <div className="flex items-center justify-between px-4 pt-3.5 pb-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-[var(--foreground)]">
            Getting started
          </span>
          {/* Progress pill */}
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-[var(--gold-500)]/10 text-[var(--gold-500)]">
            {completedCount}/{items.length}
          </span>
        </div>

        {/* Dismiss button */}
        <button
          type="button"
          onClick={handleDismiss}
          className={cn(
            "h-6 w-6 flex items-center justify-center rounded-md",
            "text-[var(--color-muted)] hover:text-[var(--foreground)]",
            "hover:bg-white/5 transition-colors"
          )}
          aria-label="Dismiss getting started guide"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Progress bar */}
      <div className="px-4 mb-3">
        <div className="h-1 w-full rounded-full bg-white/5 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-700 ${
              completedCount === items.length
                ? "bg-green-400 animate-pulse"
                : "bg-[var(--gold-500)]"
            }`}
            style={{
              width: `${Math.round((completedCount / items.length) * 100)}%`,
            }}
          />
        </div>
      </div>

      {/* Checklist */}
      <ul className="px-4 pb-4 flex flex-col gap-2.5" role="list">
        {items.map((item) => (
          <li
            key={item.id}
            className="flex items-start gap-2.5"
            aria-checked={item.done}
          >
            {/* Check icon */}
            {item.done ? (
              <CheckCircle2
                className="h-4 w-4 text-[var(--color-success,#22c55e)] flex-shrink-0 mt-0.5"
                aria-hidden="true"
              />
            ) : (
              <Circle
                className="h-4 w-4 text-[var(--color-muted)] flex-shrink-0 mt-0.5"
                aria-hidden="true"
              />
            )}

            {/* Text + action */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <span
                  className={cn(
                    "text-sm leading-tight",
                    item.done
                      ? "text-[var(--color-muted)] line-through"
                      : "text-[var(--foreground)]"
                  )}
                >
                  {item.label}
                </span>
                {!item.done && (
                  <span className="flex-shrink-0">{item.action}</span>
                )}
              </div>
              {item.sublabel && (
                <p className="text-[11px] text-[var(--color-muted)] mt-0.5 leading-tight">
                  {item.sublabel}
                </p>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
    </div>
  );
}
