"use client";

/**
 * CollapsibleSidebar — exact PHS mechanics.
 *
 * 340px width, translateX(-320px) when collapsed, 20px hover trigger zone,
 * auto-expand on mouse enter, collapse when mouse > 360px from left edge.
 * Mobile: fixed overlay at z-1001.
 */

import { useState, useCallback, useEffect } from "react";
import { Plus, Trash2, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/utils";
import { useSessionStore } from "@/store/sessionStore";

interface CollapsibleSidebarProps {
  collapsed: boolean;
  onCollapsedChange?: (collapsed: boolean) => void;
}

export function CollapsibleSidebar({
  collapsed,
  onCollapsedChange,
}: CollapsibleSidebarProps) {
  const [isHovered, setIsHovered] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const {
    sessions,
    activeSessionId,
    isLoading,
    loadSessions,
    createSession,
    switchSession,
    deleteSession,
  } = useSessionStore();

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  const handleMouseEnter = useCallback(() => {
    setIsHovered(true);
  }, []);

  const handleMouseLeave = useCallback(
    (e: React.MouseEvent) => {
      if (e.clientX > 360) {
        setIsHovered(false);
      }
    },
    []
  );

  const handleCreate = async () => {
    try {
      await createSession();
    } catch {
      // Error handled in store
    }
  };

  const handleDelete = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    if (deletingId === sessionId) {
      await deleteSession(sessionId);
      setDeletingId(null);
    } else {
      setDeletingId(sessionId);
      setTimeout(() => setDeletingId(null), 3000);
    }
  };

  const isVisible = !collapsed || isHovered;

  return (
    <>
      {/* Sidebar */}
      <aside
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        className={cn(
          "dd-sidebar flex flex-col",
          "bg-[var(--background)] border-r border-[var(--color-gold-stroke)]",
          collapsed && !isHovered && "collapsed"
        )}
      >
        {/* Hover trigger zone */}
        <div className="dd-sidebar-trigger" />

        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-[var(--stroke)]">
          <h2 className="text-sm font-heading font-semibold text-[var(--foreground)]">
            Sessions
          </h2>
          {collapsed && (
            <button
              onClick={() => onCollapsedChange?.(!collapsed)}
              className="text-xs text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors"
            >
              {isVisible ? "Pin" : ""}
            </button>
          )}
        </div>

        {/* New Chat button */}
        <div className="p-3">
          <button
            onClick={handleCreate}
            disabled={isLoading}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold bg-[var(--gold-500)] text-[#07111c] hover:bg-[var(--gold-600)] transition-colors disabled:opacity-50"
          >
            <Plus className="h-4 w-4" />
            New Chat
          </button>
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
              onClick={() => switchSession(session.session_id)}
              className={cn(
                "w-full text-left px-3 py-2.5 rounded-xl mb-1",
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
                    "text-sm font-body truncate",
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
