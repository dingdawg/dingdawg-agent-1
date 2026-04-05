"use client";

/**
 * Session sidebar — lists sessions with create/switch/delete.
 */

import { useEffect, useState } from "react";
import { Plus, Trash2, MessageSquare, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/utils";
import { useSessionStore } from "@/store/sessionStore";
import { Button } from "@/components/ui/button";

interface SessionSidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

export function SessionSidebar({ isOpen, onClose }: SessionSidebarProps) {
  const {
    sessions,
    activeSessionId,
    isLoading,
    loadSessions,
    createSession,
    switchSession,
    deleteSession,
  } = useSessionStore();

  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  const handleCreate = async () => {
    try {
      await createSession();
    } catch {
      // Error handled in store
    }
  };

  const handleDelete = async (
    e: React.MouseEvent,
    sessionId: string
  ) => {
    e.stopPropagation();
    if (deletingId === sessionId) {
      // Confirm delete
      await deleteSession(sessionId);
      setDeletingId(null);
    } else {
      setDeletingId(sessionId);
      // Auto-cancel after 3 seconds
      setTimeout(() => setDeletingId(null), 3000);
    }
  };

  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          "fixed lg:relative z-50 lg:z-auto",
          "h-full w-[280px] lg:w-[260px]",
          "bg-[var(--ink-950)] border-r border-[var(--stroke)]",
          "flex flex-col",
          "transition-transform duration-200",
          isOpen
            ? "translate-x-0"
            : "-translate-x-full lg:translate-x-0"
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-[var(--stroke)]">
          <h2 className="text-sm font-semibold text-[var(--foreground)]">
            Sessions
          </h2>
          <div className="flex items-center gap-1">
            <button
              onClick={onClose}
              className="lg:hidden p-1.5 rounded-md hover:bg-white/5 text-[var(--color-muted)]"
              aria-label="Close sidebar"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* New Chat button */}
        <div className="p-3">
          <Button
            variant="gold"
            size="default"
            onClick={handleCreate}
            isLoading={isLoading}
            className="w-full"
          >
            <Plus className="h-4 w-4" />
            New Chat
          </Button>
        </div>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto scrollbar-thin px-2 pb-4">
          {sessions.length === 0 && !isLoading && (
            <p className="text-sm text-[var(--color-muted)] text-center py-8">
              No sessions yet.
              <br />
              Start a new chat!
            </p>
          )}

          {sessions.map((session) => (
            <button
              key={session.session_id}
              onClick={() => {
                switchSession(session.session_id);
                onClose();
              }}
              className={cn(
                "w-full text-left px-3 py-2.5 rounded-lg mb-1",
                "flex items-center gap-2 group transition-colors",
                session.session_id === activeSessionId
                  ? "bg-[var(--gold-500)]/10 border border-[var(--gold-500)]/20"
                  : "hover:bg-white/5"
              )}
            >
              <MessageSquare
                className={cn(
                  "h-4 w-4 flex-shrink-0",
                  session.session_id === activeSessionId
                    ? "text-[var(--gold-500)]"
                    : "text-[var(--color-muted)]"
                )}
              />

              <div className="flex-1 min-w-0">
                <p
                  className={cn(
                    "text-sm truncate",
                    session.session_id === activeSessionId
                      ? "text-[var(--gold-500)]"
                      : "text-[var(--foreground)]"
                  )}
                >
                  {`Session ${session.session_id.slice(0, 8)}`}
                </p>
                <p className="text-xs text-[var(--color-muted)]">
                  {session.message_count ?? 0} messages
                  {session.created_at && (
                    <>
                      {" "}
                      &middot;{" "}
                      {formatRelativeTime(new Date(session.created_at))}
                    </>
                  )}
                </p>
              </div>

              <button
                onClick={(e) => handleDelete(e, session.session_id)}
                className={cn(
                  "flex-shrink-0 p-1 rounded-md transition-colors",
                  deletingId === session.session_id
                    ? "text-red-400 bg-red-400/10"
                    : "text-[var(--color-muted)] opacity-0 group-hover:opacity-100 hover:text-red-400"
                )}
                aria-label={
                  deletingId === session.session_id
                    ? "Confirm delete"
                    : "Delete session"
                }
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </button>
          ))}
        </div>
      </aside>
    </>
  );
}
