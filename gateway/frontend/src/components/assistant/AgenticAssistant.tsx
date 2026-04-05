"use client";

/**
 * AgenticAssistant — floating contextual helper widget.
 *
 * Lives on non-dashboard pages (settings, integrations, billing, analytics,
 * tasks, explore). The dashboard already has full chat; this is a lightweight
 * overlay that opens a mini panel without touching any dashboard state.
 *
 * Layout:
 *   Desktop (≥ 1024px): FAB bottom-right → expands to 320×480 glass panel.
 *   Mobile (< 1024px):  FAB bottom-right → bottom sheet (full-width, slides up).
 *
 * Z-index: z-35 — above mobile bottom nav (z-30), below modals (z-50).
 * State:   Independent local useState. Never touches useChatStore.
 * API:     createSession() once on first open, then sendMessage(sessionId, text).
 */

import { useState, useRef, useEffect, useCallback, KeyboardEvent } from "react";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { MessageCircle, X, Send, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAgentStore } from "@/store/agentStore";
import { createSession, sendMessage } from "@/services/api/agentService";

// ─── Types ────────────────────────────────────────────────────────────────────

interface AssistantMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

// ─── Page-specific context hints ─────────────────────────────────────────────

const PAGE_HINTS: Record<string, string> = {
  "/settings": "Customize your agent — name, branding, behavior. I'll walk you through it.",
  "/integrations": "Connect your tools and apps so your agent can do more for you.",
  "/billing": "Your plan, usage, and billing — I can break it down for you.",
  "/analytics": "See what's working and what needs attention — I'll explain the numbers.",
  "/tasks": "Manage your tasks — create, track, or delegate. Just tell me what you need.",
  "/explore": "Discover what your agent can do. I'll show you around.",
};

function getPageHint(pathname: string): string {
  // Exact match first, then prefix match for nested routes
  if (PAGE_HINTS[pathname]) return PAGE_HINTS[pathname];
  for (const [prefix, hint] of Object.entries(PAGE_HINTS)) {
    if (pathname.startsWith(prefix + "/")) return hint;
  }
  return "I'm here whenever you need me. Just ask.";
}

// ─── ID generator (no crypto dependency) ─────────────────────────────────────

let _seq = 0;
function nextId(): string {
  return `asst-msg-${Date.now()}-${++_seq}`;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function AgenticAssistant() {
  const pathname = usePathname();
  const { currentAgent } = useAgentStore();

  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  // Track whether we are on mobile — computed once on mount, not at render time,
  // to avoid SSR/hydration mismatch from reading window.innerWidth during render.
  const [isMobile, setIsMobile] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // Detect mobile after mount (safe — no SSR mismatch)
  useEffect(() => {
    setIsMobile(window.innerWidth < 1024);
  }, []);

  // ── Auto-scroll to bottom when messages change ────────────────────────────
  // Guard: jsdom does not implement scrollIntoView; real browsers always have it.
  useEffect(() => {
    if (open && messagesEndRef.current && typeof messagesEndRef.current.scrollIntoView === "function") {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, open]);

  // ── Focus input when panel opens ──────────────────────────────────────────
  useEffect(() => {
    if (open) {
      // Small delay to let framer-motion complete the open animation
      const t = setTimeout(() => inputRef.current?.focus(), 150);
      return () => clearTimeout(t);
    }
  }, [open]);

  // ── Click-outside to close ─────────────────────────────────────────────────
  useEffect(() => {
    if (!open) return;

    function handlePointerDown(e: PointerEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [open]);

  // Do not render on /dashboard — that page has full chat.
  // This check must come AFTER all hooks to satisfy Rules of Hooks.
  if (pathname === "/dashboard" || pathname.startsWith("/dashboard/")) {
    return null;
  }

  // ── Lazy session creation — only on first real message send ───────────────
  const ensureSession = useCallback(async (): Promise<string | null> => {
    if (sessionId) return sessionId;
    try {
      const session = await createSession({
        system_prompt: `You are the friendly guide inside DingDawg — think helpful concierge, not tech support.
The user is on the "${pathname.replace('/', '')}" page. ${getPageHint(pathname)}
Rules:
- Plain language only. No jargon. If a 5th grader can't understand it, rewrite it.
- Keep answers to 2-3 sentences max. Link to the right page if they need to take action.
- Be warm but efficient. Respect their time.
- If they ask something you can't do yet, say so honestly and suggest what they CAN do.`,
      });
      setSessionId(session.session_id);
      setSessionError(null);
      return session.session_id;
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "Could not start assistant session.";
      setSessionError(msg);
      return null;
    }
  }, [sessionId, pathname]);

  // ── Submit handler ────────────────────────────────────────────────────────
  const handleSubmit = useCallback(async () => {
    const text = input.trim();
    if (!text || isLoading) return;

    // Append user message immediately
    const userMsg: AssistantMessage = {
      id: nextId(),
      role: "user",
      content: text,
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsLoading(true);

    try {
      const sid = await ensureSession();
      if (!sid) {
        setMessages((prev) => [
          ...prev,
          {
            id: nextId(),
            role: "assistant",
            content: "Sorry, I could not connect. Please try again.",
          },
        ]);
        return;
      }

      const response = await sendMessage(sid, text);
      setMessages((prev) => [
        ...prev,
        {
          id: nextId(),
          role: "assistant",
          content: response.content,
        },
      ]);
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "Something went wrong. Please try again.";
      setMessages((prev) => [
        ...prev,
        {
          id: nextId(),
          role: "assistant",
          content: msg,
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  }, [input, isLoading, ensureSession]);

  // ── Keyboard handler: Enter submits, Shift+Enter is a newline ────────────
  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void handleSubmit();
      }
    },
    [handleSubmit]
  );

  const pageHint = getPageHint(pathname);
  const agentName = currentAgent?.name ?? "Assistant";

  // ── Panel variant — desktop vs mobile bottom sheet ───────────────────────
  const panelVariants = isMobile
    ? {
        initial: { y: "100%", opacity: 0 },
        animate: { y: 0, opacity: 1 },
        exit: { y: "100%", opacity: 0 },
      }
    : {
        initial: { scale: 0.92, opacity: 0, y: 12 },
        animate: { scale: 1, opacity: 1, y: 0 },
        exit: { scale: 0.92, opacity: 0, y: 12 },
      };

  const panelTransition = isMobile
    ? { type: "spring" as const, damping: 32, stiffness: 380, mass: 0.9 }
    : { type: "spring" as const, damping: 28, stiffness: 420, mass: 0.8 };

  return (
    <>
      {/* ── Floating Action Button ──────────────────────────────────────── */}
      <button
        data-testid="agentic-assistant-fab"
        onClick={() => setOpen((prev) => !prev)}
        aria-label={open ? "Close assistant" : "Open assistant"}
        className={cn(
          "fixed bottom-20 right-4 lg:bottom-6 lg:right-6",
          "h-14 w-14 rounded-full",
          "bg-[var(--gold-500)] text-[#07111c]",
          "flex items-center justify-center",
          "shadow-lg hover:shadow-xl",
          "transition-all duration-150 hover:scale-105 active:scale-95",
          "z-[35]",
          // Keep FAB visible even when panel is open (user can click to close)
          open && "ring-2 ring-[var(--gold-500)]/40 ring-offset-2 ring-offset-[var(--ink-950)]"
        )}
        style={{ width: 56, height: 56 }}
      >
        <AnimatePresence mode="wait" initial={false}>
          {open ? (
            <motion.span
              key="close"
              initial={{ rotate: -90, opacity: 0 }}
              animate={{ rotate: 0, opacity: 1 }}
              exit={{ rotate: 90, opacity: 0 }}
              transition={{ duration: 0.15 }}
            >
              <X className="h-5 w-5" />
            </motion.span>
          ) : (
            <motion.span
              key="open"
              initial={{ rotate: 90, opacity: 0 }}
              animate={{ rotate: 0, opacity: 1 }}
              exit={{ rotate: -90, opacity: 0 }}
              transition={{ duration: 0.15 }}
            >
              <MessageCircle className="h-5 w-5" />
            </motion.span>
          )}
        </AnimatePresence>
      </button>

      {/* ── Chat Panel ──────────────────────────────────────────────────── */}
      <AnimatePresence>
        {open && (
          <motion.div
            ref={panelRef}
            key="assistant-panel"
            data-testid="agentic-assistant-panel"
            variants={panelVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            transition={panelTransition}
            className={cn(
              // Mobile bottom sheet
              "fixed lg:hidden bottom-0 left-0 right-0",
              "max-h-[480px]",
              "bg-[var(--ink-950)] lg:bg-[var(--glass)] lg:backdrop-blur-[18px]",
              "border border-[var(--stroke)]",
              "rounded-t-2xl",
              "flex flex-col",
              "z-[35]",
              // Desktop panel
              "lg:block lg:bottom-24 lg:right-6 lg:left-auto",
              "lg:w-80 lg:h-auto lg:max-h-[480px]",
              "lg:rounded-2xl"
            )}
          >
            {/* Desktop panel — separate motion element for clarity */}
            <div
              className={cn(
                "hidden lg:flex flex-col",
                "w-80 max-h-[480px]",
                "bg-[var(--glass)] lg:backdrop-blur-[18px]",
                "border border-[var(--stroke)] rounded-2xl",
                "overflow-hidden"
              )}
              data-testid="agentic-assistant-panel-desktop"
            >
              <PanelContents
                agentName={agentName}
                pageHint={pageHint}
                messages={messages}
                input={input}
                isLoading={isLoading}
                sessionError={sessionError}
                inputRef={inputRef}
                messagesEndRef={messagesEndRef}
                onInputChange={setInput}
                onKeyDown={handleKeyDown}
                onSubmit={handleSubmit}
                onClose={() => setOpen(false)}
              />
            </div>

            {/* Mobile bottom sheet contents */}
            <div className="lg:hidden flex flex-col overflow-hidden rounded-t-2xl h-full max-h-[480px]">
              <PanelContents
                agentName={agentName}
                pageHint={pageHint}
                messages={messages}
                input={input}
                isLoading={isLoading}
                sessionError={sessionError}
                inputRef={inputRef}
                messagesEndRef={messagesEndRef}
                onInputChange={setInput}
                onKeyDown={handleKeyDown}
                onSubmit={handleSubmit}
                onClose={() => setOpen(false)}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

// ─── Panel Contents (shared between desktop + mobile) ────────────────────────

interface PanelContentsProps {
  agentName: string;
  pageHint: string;
  messages: AssistantMessage[];
  input: string;
  isLoading: boolean;
  sessionError: string | null;
  inputRef: React.RefObject<HTMLInputElement | null>;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  onInputChange: (value: string) => void;
  onKeyDown: (e: KeyboardEvent<HTMLInputElement>) => void;
  onSubmit: () => void;
  onClose: () => void;
}

function PanelContents({
  agentName,
  pageHint,
  messages,
  input,
  isLoading,
  sessionError,
  inputRef,
  messagesEndRef,
  onInputChange,
  onKeyDown,
  onSubmit,
  onClose,
}: PanelContentsProps) {
  return (
    <>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--stroke)] flex-shrink-0">
        <div className="flex items-center gap-2">
          <span className="h-7 w-7 rounded-lg bg-[var(--gold-500)]/10 flex items-center justify-center flex-shrink-0">
            <span className="text-xs font-bold text-[var(--gold-500)]">
              {agentName.charAt(0).toUpperCase()}
            </span>
          </span>
          <span
            className="text-sm font-semibold text-[var(--foreground)]"
            data-testid="assistant-agent-name"
          >
            {agentName}
          </span>
        </div>
        <button
          onClick={onClose}
          data-testid="assistant-close-btn"
          aria-label="Close assistant panel"
          className="p-1 rounded-md text-[var(--color-muted)] hover:text-[var(--foreground)] hover:bg-white/5 transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Context hint */}
      <div className="px-4 py-2 border-b border-[var(--stroke)] flex-shrink-0">
        <p
          className="text-xs text-[var(--color-muted)]"
          data-testid="assistant-page-hint"
        >
          {pageHint}
        </p>
      </div>

      {/* Messages */}
      <div
        className="flex-1 overflow-y-auto px-3 py-3 space-y-2 scrollbar-thin min-h-0"
        data-testid="assistant-messages-area"
      >
        {messages.length === 0 ? (
          <div
            className="flex flex-col items-center justify-center h-full py-8 gap-2"
            data-testid="assistant-empty-state"
          >
            <MessageCircle className="h-8 w-8 text-[var(--gold-500)]/40" />
            <p className="text-xs text-[var(--color-muted)] text-center leading-relaxed max-w-[200px]">
              Hey! I&apos;m your agent&apos;s sidekick. Ask me anything — no tech speak required.
            </p>
          </div>
        ) : (
          messages.map((msg) => (
            <div
              key={msg.id}
              data-testid={`message-${msg.role}`}
              className={cn(
                "max-w-[88%] rounded-2xl px-3 py-2 text-xs leading-relaxed",
                msg.role === "user"
                  ? "ml-auto bg-[var(--gold-500)] text-[#07111c] font-medium"
                  : "bg-[var(--glass)] border border-[var(--stroke)] text-[var(--foreground)]"
              )}
            >
              {msg.content}
            </div>
          ))
        )}

        {/* Loading indicator */}
        {isLoading && (
          <div
            className="flex items-center gap-1.5 max-w-[88%]"
            data-testid="assistant-loading"
          >
            <div className="bg-[var(--glass)] border border-[var(--stroke)] rounded-2xl px-3 py-2">
              <Loader2 className="h-3.5 w-3.5 text-[var(--gold-500)] animate-spin" />
            </div>
          </div>
        )}

        {/* Session error */}
        {sessionError && (
          <p className="text-xs text-red-400 px-1" data-testid="assistant-session-error">
            {sessionError}
          </p>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <form
        data-testid="assistant-form"
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit();
        }}
        className="flex items-center gap-2 px-3 py-3 border-t border-[var(--stroke)] flex-shrink-0"
      >
        <input
          ref={inputRef}
          data-testid="assistant-input"
          type="text"
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Type a question..."
          disabled={isLoading}
          className={cn(
            "flex-1 min-w-0 rounded-xl px-3 py-2",
            "text-base text-[var(--foreground)] placeholder:text-[var(--color-muted)]",
            "bg-white/5 border border-[var(--stroke2)]",
            "focus:outline-none focus:ring-1 focus:ring-[var(--gold-500)]/50",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            "transition-colors"
          )}
        />
        <button
          type="submit"
          data-testid="assistant-send-btn"
          disabled={!input.trim() || isLoading}
          aria-label="Send message"
          className={cn(
            "flex-shrink-0 h-10 w-10 min-h-[44px] min-w-[44px] rounded-xl",
            "bg-[var(--gold-500)] text-[#07111c]",
            "flex items-center justify-center",
            "transition-colors duration-150",
            "disabled:opacity-40 disabled:cursor-not-allowed",
            "hover:bg-[var(--gold-600)] hover:brightness-110"
          )}
        >
          <Send className="h-3.5 w-3.5" />
        </button>
      </form>
    </>
  );
}
