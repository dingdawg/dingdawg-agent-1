"use client";

/**
 * NotificationBell — bell icon with unread badge + dropdown panel.
 *
 * Sits in the dashboard top bar. Shows unread count badge.
 * Click opens a dropdown with recent notifications.
 * Each notification is tappable (navigates to actionUrl if set).
 *
 * On first click, requests browser push notification permission.
 */

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Bell, Check, Trash2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useNotificationStore,
  type AppNotification,
  type NotificationType,
} from "@/store/notificationStore";

const TYPE_ICONS: Record<NotificationType, string> = {
  booking: "📅",
  task: "✅",
  message: "💬",
  payment: "💳",
  integration: "🔗",
  system: "⚡",
};

function timeAgo(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function NotificationBell() {
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const {
    notifications,
    unreadCount,
    pushEnabled,
    markRead,
    markAllRead,
    clearAll,
    requestPushPermission,
  } = useNotificationStore();

  // Request push permission on first open
  useEffect(() => {
    if (isOpen && !pushEnabled) {
      requestPushPermission();
    }
  }, [isOpen, pushEnabled, requestPushPermission]);

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [isOpen]);

  function handleNotificationClick(n: AppNotification) {
    markRead(n.id);
    if (n.actionUrl) {
      router.push(n.actionUrl);
      setIsOpen(false);
    }
  }

  return (
    <div className="relative" ref={panelRef}>
      {/* Bell button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center justify-center h-9 w-9 min-h-[44px] min-w-[44px] rounded-lg text-[var(--color-muted)] hover:text-[var(--foreground)] hover:bg-white/5 transition-colors relative"
        aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ""}`}
      >
        <Bell className="h-5 w-5" />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 h-5 min-w-[20px] px-1 flex items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown panel */}
      {isOpen && (
        <div className="absolute right-0 top-full mt-2 w-80 max-h-[420px] glass-panel shadow-xl z-50 flex flex-col overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--stroke)]">
            <h3 className="text-sm font-semibold text-[var(--foreground)]">
              Notifications
            </h3>
            <div className="flex items-center gap-2">
              {notifications.length > 0 && (
                <>
                  <button
                    onClick={markAllRead}
                    className="text-xs text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors flex items-center gap-1"
                    title="Mark all as read"
                  >
                    <Check className="h-3 w-3" />
                  </button>
                  <button
                    onClick={clearAll}
                    className="text-xs text-[var(--color-muted)] hover:text-red-400 transition-colors flex items-center gap-1"
                    title="Clear all"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </>
              )}
              <button
                onClick={() => setIsOpen(false)}
                className="text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors lg:hidden"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Notification list */}
          <div className="flex-1 overflow-y-auto scrollbar-thin">
            {notifications.length === 0 ? (
              <div className="px-4 py-10 text-center">
                <Bell className="h-8 w-8 text-[var(--color-muted)] mx-auto mb-2 opacity-40" />
                <p className="text-sm text-[var(--color-muted)]">
                  No notifications yet
                </p>
                <p className="text-xs text-[var(--color-muted)] mt-1">
                  Your agent will notify you when something happens
                </p>
              </div>
            ) : (
              notifications.map((n) => (
                <button
                  key={n.id}
                  onClick={() => handleNotificationClick(n)}
                  className={cn(
                    "w-full text-left px-4 py-3 flex gap-3 transition-colors border-b border-[var(--stroke)]/50",
                    n.read
                      ? "hover:bg-white/3"
                      : "bg-[var(--gold-500)]/5 hover:bg-[var(--gold-500)]/10"
                  )}
                >
                  {/* Type icon */}
                  <span className="text-lg flex-shrink-0 mt-0.5">
                    {TYPE_ICONS[n.type]}
                  </span>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <p
                      className={cn(
                        "text-sm leading-tight mb-0.5",
                        n.read
                          ? "text-[var(--color-muted)]"
                          : "text-[var(--foreground)] font-medium"
                      )}
                    >
                      {n.title}
                    </p>
                    <p className="text-xs text-[var(--color-muted)] line-clamp-2 leading-relaxed">
                      {n.body}
                    </p>
                    <p className="text-[10px] text-[var(--color-muted)] mt-1">
                      {timeAgo(n.timestamp)}
                    </p>
                  </div>

                  {/* Unread dot */}
                  {!n.read && (
                    <span className="h-2 w-2 rounded-full bg-[var(--gold-500)] flex-shrink-0 mt-2" />
                  )}
                </button>
              ))
            )}
          </div>

          {/* Push notification opt-in */}
          {!pushEnabled && notifications.length > 0 && (
            <div className="px-4 py-3 border-t border-[var(--stroke)] bg-[var(--gold-500)]/5">
              <button
                onClick={requestPushPermission}
                className="text-xs text-[var(--gold-500)] hover:underline"
              >
                Enable push notifications to get alerts on your phone
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
