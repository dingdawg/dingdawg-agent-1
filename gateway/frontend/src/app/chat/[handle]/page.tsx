"use client";

/**
 * Public standalone chat page — /chat/[handle]
 *
 * - Public page (no auth required)
 * - Fetches agent profile from GET /api/v1/public/agents/{handle}
 * - Full-screen chat interface powered by /api/v1/widget/{handle}/message
 * - Anonymous sessions via /api/v1/widget/{handle}/session
 * - Persists session_id in sessionStorage to survive reloads within the tab
 * - Mobile responsive, dark-mode compatible
 * - Cold-load UX: shows formatted name & skeleton UI BEFORE API resolves
 */

import { use, useState, useEffect, useRef, useCallback } from "react";
import Head from "next/head";
import Link from "next/link";
import {
  ArrowLeft,
  Send,
  RefreshCw,
  User,
  Store,
  Zap,
  AlertCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AgentProfile {
  handle: string;
  name: string;
  industry: string;
  description: string;
  agent_type: string;
  avatar_url: string;
  primary_color: string;
  greeting: string;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

interface PageProps {
  params: Promise<{ handle: string }>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generateId(): string {
  return Math.random().toString(36).slice(2, 11);
}

/**
 * Converts a URL handle into a display name.
 * "marios-italian"  → "Mario's Italian"
 * "joes-bbq-shack"  → "Joe's Bbq Shack"  (title-case, hyphens → spaces)
 *
 * Special-cases common possessives: if a word ends with "s" preceded by
 * another word that looks like a name, we leave it — but we do insert an
 * apostrophe when the segment ends in 's' and the next segment could be a
 * noun phrase (simple heuristic: just title-case each segment, which is good
 * enough for immediate display before the real name arrives).
 */
function formatHandle(handle: string): string {
  return handle
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function AgentAvatar({
  profile,
  size = "sm",
}: {
  profile: AgentProfile;
  size?: "sm" | "lg";
}) {
  const dim = size === "lg" ? "h-12 w-12" : "h-8 w-8";
  const iconDim = size === "lg" ? "h-6 w-6" : "h-4 w-4";
  const color = profile.primary_color || "#7C3AED";
  const isBusinessAgent = profile.agent_type === "business";

  if (profile.avatar_url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={profile.avatar_url}
        alt={profile.name}
        className={`${dim} rounded-full object-cover flex-shrink-0`}
      />
    );
  }

  return (
    <div
      className={`${dim} rounded-full flex items-center justify-center flex-shrink-0`}
      style={{ backgroundColor: `${color}26` }}
    >
      {isBusinessAgent ? (
        <Store className={`${iconDim}`} style={{ color }} />
      ) : (
        <User className={`${iconDim}`} style={{ color }} />
      )}
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-end gap-2 max-w-[80%]">
      <div className="h-8 w-8 rounded-full bg-[var(--surface-2)] flex items-center justify-center flex-shrink-0">
        <Zap className="h-4 w-4 text-[var(--gold-500)]" />
      </div>
      <div className="bg-[var(--surface-2)] rounded-2xl rounded-bl-sm px-4 py-3">
        <span className="flex gap-1 items-center h-4">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-muted)] animate-bounce [animation-delay:0ms]" />
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-muted)] animate-bounce [animation-delay:150ms]" />
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-muted)] animate-bounce [animation-delay:300ms]" />
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function PublicChatPage({ params }: PageProps) {
  const { handle } = use(params);
  const cleanHandle = handle.replace(/^@/, "");

  // Agent profile
  const [profile, setProfile] = useState<AgentProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileError, setProfileError] = useState<string | null>(null);

  // Session
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);

  // Messages
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [streamingContent, setStreamingContent] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent]);

  // Load agent profile
  useEffect(() => {
    let cancelled = false;

    async function loadProfile() {
      setProfileLoading(true);
      setProfileError(null);
      try {
        const res = await fetch(`/api/v1/public/agents/${cleanHandle}`);
        if (!res.ok) {
          if (res.status === 404) {
            setProfileError("Agent not found");
          } else {
            setProfileError("Failed to load agent");
          }
          return;
        }
        const data: AgentProfile = await res.json();
        if (!cancelled) {
          setProfile(data);
        }
      } catch {
        if (!cancelled) {
          setProfileError("Network error — please try again");
        }
      } finally {
        if (!cancelled) {
          setProfileLoading(false);
        }
      }
    }

    loadProfile();
    return () => {
      cancelled = true;
    };
  }, [cleanHandle]);

  // Start widget session once we have the profile
  const startSession = useCallback(
    async (greetingOverride?: string) => {
      setSessionError(null);
      const storageKey = `dd_session_${cleanHandle}`;

      // Reuse existing session within the same browser tab
      const existing = sessionStorage.getItem(storageKey);
      if (existing && !greetingOverride) {
        setSessionId(existing);
        return;
      }

      try {
        const res = await fetch(`/api/v1/widget/${cleanHandle}/session`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ metadata: { source: "public_chat_page" } }),
        });

        if (!res.ok) {
          setSessionError("Could not start chat session");
          return;
        }

        const data = await res.json();
        const sid: string = data.session_id;
        sessionStorage.setItem(storageKey, sid);
        setSessionId(sid);

        // Show agent greeting
        const greeting: string = greetingOverride || data.greeting || "";
        if (greeting) {
          setMessages([
            {
              id: generateId(),
              role: "assistant",
              content: greeting,
              timestamp: new Date(),
            },
          ]);
        }
      } catch {
        setSessionError("Network error — could not start session");
      }
    },
    [cleanHandle]
  );

  useEffect(() => {
    if (profile) {
      startSession();
    }
  }, [profile, startSession]);

  // Send a message
  async function sendMessage() {
    const text = input.trim();
    if (!text || !sessionId || sending) return;

    const userMsg: ChatMessage = {
      id: generateId(),
      role: "user",
      content: text,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setSending(true);
    setStreamingContent("");

    try {
      const res = await fetch(`/api/v1/widget/${cleanHandle}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: text }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        const errMsg =
          (errData as { detail?: string }).detail ||
          "Something went wrong. Please try again.";
        setMessages((prev) => [
          ...prev,
          {
            id: generateId(),
            role: "assistant",
            content: errMsg,
            timestamp: new Date(),
          },
        ]);
        setStreamingContent(null);
        return;
      }

      // Handle streaming (text/event-stream) or plain JSON
      const contentType = res.headers.get("content-type") || "";
      if (contentType.includes("text/event-stream")) {
        // SSE streaming
        const reader = res.body?.getReader();
        const decoder = new TextDecoder();
        let accumulated = "";

        if (reader) {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            const chunk = decoder.decode(value, { stream: true });
            // Parse SSE lines: "data: ..."
            for (const line of chunk.split("\n")) {
              if (line.startsWith("data: ")) {
                const payload = line.slice(6).trim();
                if (payload === "[DONE]") break;
                try {
                  const parsed = JSON.parse(payload) as {
                    delta?: string;
                    content?: string;
                  };
                  const delta = parsed.delta ?? parsed.content ?? payload;
                  accumulated += delta;
                  setStreamingContent(accumulated);
                } catch {
                  // Non-JSON delta — treat as raw text
                  accumulated += payload;
                  setStreamingContent(accumulated);
                }
              }
            }
          }
        }

        setMessages((prev) => [
          ...prev,
          {
            id: generateId(),
            role: "assistant",
            content: accumulated || "...",
            timestamp: new Date(),
          },
        ]);
      } else {
        // Plain JSON response
        const data = await res.json();
        const reply: string =
          (data as { response?: string; message?: string; content?: string })
            .response ??
          (data as { response?: string; message?: string; content?: string })
            .message ??
          (data as { response?: string; message?: string; content?: string })
            .content ??
          "...";

        setMessages((prev) => [
          ...prev,
          {
            id: generateId(),
            role: "assistant",
            content: reply,
            timestamp: new Date(),
          },
        ]);
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: generateId(),
          role: "assistant",
          content: "Connection error — please check your network and try again.",
          timestamp: new Date(),
        },
      ]);
    } finally {
      setSending(false);
      setStreamingContent(null);
      inputRef.current?.focus();
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  function handleRestart() {
    sessionStorage.removeItem(`dd_session_${cleanHandle}`);
    setMessages([]);
    setSessionId(null);
    setSessionError(null);
    if (profile) {
      startSession(profile.greeting || "");
    }
  }

  // Auto-resize textarea
  function handleInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
  }

  const accentColor = profile?.primary_color || "#7C3AED";

  // Derived display name — available IMMEDIATELY from the URL handle,
  // replaced by the real API name once the profile loads.
  const displayName = profile?.name || formatHandle(cleanHandle);
  const pageTitle = `Chat with ${displayName}`;
  const pageDescription =
    profile?.description ||
    `Ask ${displayName} anything — powered by DingDawg AI.`;

  // ---------------------------------------------------------------------------
  // Render: skeleton (loading state — shown before API responds)
  // ---------------------------------------------------------------------------

  if (profileLoading) {
    return (
      <>
        <Head>
          <title>{pageTitle}</title>
          <meta name="description" content={pageDescription} />
          <meta property="og:title" content={pageTitle} />
          <meta property="og:description" content={pageDescription} />
          <meta property="og:type" content="website" />
        </Head>

        <div className="flex h-dvh flex-col bg-[var(--background)]">
          {/* Skeleton header */}
          <header className="flex items-center gap-3 px-4 py-3 border-b border-[var(--stroke)] bg-[var(--surface)] flex-shrink-0">
            {/* Back arrow placeholder */}
            <div className="h-5 w-5 rounded bg-[var(--surface-2)] animate-pulse flex-shrink-0" />

            {/* Avatar placeholder */}
            <div
              className="h-8 w-8 rounded-full flex-shrink-0 animate-pulse"
              style={{ backgroundColor: `${accentColor}33` }}
            />

            {/* Name + industry placeholders */}
            <div className="flex-1 min-w-0 space-y-1.5">
              <p className="font-semibold text-sm text-[var(--foreground)] truncate">
                {displayName}
              </p>
              <div className="h-2.5 w-24 rounded bg-[var(--surface-2)] animate-pulse" />
            </div>

            {/* Online indicator */}
            <div className="flex items-center gap-1.5 text-xs text-green-400 flex-shrink-0">
              <span className="h-1.5 w-1.5 rounded-full bg-green-400 animate-pulse" />
              Online
            </div>
          </header>

          {/* Skeleton message area */}
          <main className="flex-1 overflow-y-auto px-4 py-6 flex flex-col items-center justify-center gap-6">
            {/* Agent welcome card */}
            <div className="flex flex-col items-center gap-3 text-center px-4">
              {/* Large avatar placeholder */}
              <div
                className="h-14 w-14 rounded-full animate-pulse flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: `${accentColor}26` }}
              >
                <Store className="h-7 w-7 opacity-40" style={{ color: accentColor }} />
              </div>
              <div>
                <p className="font-semibold text-[var(--foreground)] text-base mb-1">
                  Welcome to {displayName}
                </p>
                <div className="space-y-1.5">
                  <div className="h-3 w-56 rounded bg-[var(--surface-2)] animate-pulse mx-auto" />
                  <div className="h-3 w-40 rounded bg-[var(--surface-2)] animate-pulse mx-auto" />
                </div>
              </div>
            </div>

            {/* Skeleton chat bubble (assistant) */}
            <div className="w-full max-w-sm">
              <div className="flex items-end gap-2 max-w-[80%]">
                <div
                  className="h-8 w-8 rounded-full animate-pulse flex-shrink-0"
                  style={{ backgroundColor: `${accentColor}26` }}
                />
                <div className="bg-[var(--surface-2)] rounded-2xl rounded-bl-sm px-4 py-3 space-y-2 animate-pulse">
                  <div className="h-3 w-44 rounded bg-[var(--stroke)]" />
                  <div className="h-3 w-32 rounded bg-[var(--stroke)]" />
                </div>
              </div>
            </div>
          </main>

          {/* Input bar — visible and styled but disabled */}
          <footer className="flex-shrink-0 border-t border-[var(--stroke)] bg-[var(--surface)] px-4 py-3">
            <div className="flex items-end gap-2 max-w-2xl mx-auto">
              <div className="flex-1 min-w-0">
                <textarea
                  placeholder={`Message ${displayName}...`}
                  rows={1}
                  disabled
                  className="w-full resize-none bg-[var(--surface-2)] border border-[var(--stroke)] rounded-2xl px-4 py-2.5 text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none overflow-hidden leading-relaxed opacity-60 cursor-not-allowed"
                />
              </div>
              <button
                disabled
                aria-label="Send message"
                className="flex-shrink-0 h-10 w-10 rounded-full flex items-center justify-center opacity-40 cursor-not-allowed"
                style={{ backgroundColor: accentColor }}
              >
                <Send className="h-4 w-4 text-white" />
              </button>
            </div>
            <p className="text-center text-xs text-[var(--color-muted)] mt-2">
              Powered by{" "}
              <Link href="/" className="hover:underline">
                DingDawg
              </Link>
            </p>
          </footer>
        </div>
      </>
    );
  }

  // ---------------------------------------------------------------------------
  // Render: profile error / 404
  // ---------------------------------------------------------------------------

  if (profileError || !profile) {
    return (
      <div className="flex h-dvh flex-col items-center justify-center gap-4 bg-[var(--background)] px-4">
        <AlertCircle className="h-12 w-12 text-[var(--color-muted)]" />
        <p className="text-[var(--foreground)] font-semibold text-lg">
          {profileError || "Agent not found"}
        </p>
        <p className="text-sm text-[var(--color-muted)] text-center max-w-xs">
          The agent <span className="font-mono">@{cleanHandle}</span> could not be found or is not available.
        </p>
        <Link href="/explore">
          <Button variant="outline">Browse agents</Button>
        </Link>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Render: session error
  // ---------------------------------------------------------------------------

  if (sessionError) {
    return (
      <div className="flex h-dvh flex-col items-center justify-center gap-4 bg-[var(--background)] px-4">
        <AlertCircle className="h-12 w-12 text-red-400" />
        <p className="text-[var(--foreground)] font-semibold">{sessionError}</p>
        <Button onClick={() => startSession()} variant="outline">
          Retry
        </Button>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Render: main chat UI
  // ---------------------------------------------------------------------------

  return (
    <>
    <Head>
      <title>{pageTitle}</title>
      <meta name="description" content={pageDescription} />
      <meta property="og:title" content={pageTitle} />
      <meta property="og:description" content={pageDescription} />
      <meta property="og:type" content="website" />
      {profile.avatar_url && (
        <meta property="og:image" content={profile.avatar_url} />
      )}
    </Head>
    <div className="flex h-dvh flex-col bg-[var(--background)]">
      {/* Header */}
      <header
        className="flex items-center gap-3 px-4 py-3 border-b border-[var(--stroke)] bg-[var(--surface)] flex-shrink-0"
        style={{ borderBottomColor: `${accentColor}33` }}
      >
        <Link
          href={`/agents/${cleanHandle}`}
          className="text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors flex-shrink-0"
          aria-label="Back to agent profile"
        >
          <ArrowLeft className="h-5 w-5" />
        </Link>

        <AgentAvatar profile={profile} size="sm" />

        <div className="flex-1 min-w-0">
          <p className="font-semibold text-sm text-[var(--foreground)] truncate">
            {profile.name}
          </p>
          {profile.industry && (
            <p className="text-xs text-[var(--color-muted)] truncate">
              {profile.industry}
            </p>
          )}
        </div>

        <div className="flex items-center gap-1.5 text-xs text-green-400 flex-shrink-0">
          <span className="h-1.5 w-1.5 rounded-full bg-green-400 animate-pulse" />
          Online
        </div>

        <button
          onClick={handleRestart}
          className="text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors flex-shrink-0 ml-1"
          title="Restart conversation"
          aria-label="Restart conversation"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
      </header>

      {/* Messages */}
      <main className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0 && !streamingContent && (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-4">
            <AgentAvatar profile={profile} size="lg" />
            <div>
              <p className="font-semibold text-[var(--foreground)] mb-1">{profile.name}</p>
              <p className="text-sm text-[var(--color-muted)] max-w-xs">
                {profile.description || profile.greeting || "Start a conversation below."}
              </p>
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`group/msg flex items-end gap-2 ${
              msg.role === "user" ? "flex-row-reverse" : "flex-row"
            } max-w-[85%] ${msg.role === "user" ? "ml-auto" : "mr-auto"}`}
          >
            {msg.role === "assistant" && (
              <AgentAvatar profile={profile} size="sm" />
            )}
            {msg.role === "user" && (
              <div className="h-8 w-8 rounded-full bg-[var(--surface-2)] flex items-center justify-center flex-shrink-0">
                <User className="h-4 w-4 text-[var(--color-muted)]" />
              </div>
            )}
            <div className="flex flex-col gap-0.5">
              <div
                className={`px-4 py-2.5 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap break-words ${
                  msg.role === "user"
                    ? "rounded-br-sm text-white"
                    : "rounded-bl-sm bg-[var(--surface-2)] text-[var(--foreground)]"
                }`}
                style={
                  msg.role === "user"
                    ? { backgroundColor: accentColor }
                    : undefined
                }
              >
                {msg.content}
              </div>
              {/* Timestamp — visible on hover (Intercom pattern) */}
              <span
                className={`text-[10px] text-[var(--color-muted)] opacity-0 group-hover/msg:opacity-100 transition-opacity duration-150 px-1 ${
                  msg.role === "user" ? "text-right" : "text-left"
                }`}
                aria-label={msg.timestamp.toLocaleString()}
              >
                {msg.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
            </div>
          </div>
        ))}

        {/* Streaming / typing indicator */}
        {sending && streamingContent === "" && <TypingIndicator />}
        {sending && streamingContent !== null && streamingContent !== "" && (
          <div className="flex items-end gap-2 max-w-[85%] mr-auto">
            <AgentAvatar profile={profile} size="sm" />
            <div className="px-4 py-2.5 rounded-2xl rounded-bl-sm bg-[var(--surface-2)] text-sm text-[var(--foreground)] leading-relaxed whitespace-pre-wrap break-words">
              {streamingContent}
              <span className="inline-block h-3 w-0.5 bg-current ml-0.5 animate-pulse" />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </main>

      {/* Input bar */}
      <footer className="flex-shrink-0 border-t border-[var(--stroke)] bg-[var(--surface)] px-4 py-3">
        <div className="flex items-end gap-2 max-w-2xl mx-auto">
          <div className="flex-1 min-w-0">
            <textarea
              ref={inputRef}
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder={`Message ${profile.name}...`}
              rows={1}
              disabled={sending || !sessionId}
              className="w-full resize-none bg-[var(--surface-2)] border border-[var(--stroke)] rounded-2xl px-4 py-2.5 text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:ring-2 disabled:opacity-50 disabled:cursor-not-allowed overflow-hidden leading-relaxed"
              style={{ "--tw-ring-color": accentColor } as React.CSSProperties}
            />
          </div>
          <button
            onClick={sendMessage}
            disabled={!input.trim() || sending || !sessionId}
            aria-label="Send message"
            className="flex-shrink-0 h-10 w-10 rounded-full flex items-center justify-center transition-all disabled:opacity-40 disabled:cursor-not-allowed hover:opacity-90 active:scale-95"
            style={{ backgroundColor: accentColor }}
          >
            <Send className="h-4 w-4 text-white" />
          </button>
        </div>
        <p className="text-center text-[9px] text-[var(--color-muted)] opacity-40 mt-1.5">
          Powered by{" "}
          <Link href="/" className="hover:opacity-80">
            DingDawg
          </Link>
          {" · "}
          <Link href={`/agents/${cleanHandle}`} className="hover:opacity-80">
            View profile
          </Link>
        </p>
      </footer>
    </div>
    </>
  );
}
