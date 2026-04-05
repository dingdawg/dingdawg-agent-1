/**
 * Notification store — tracks in-app notifications for the business owner.
 *
 * Notifications are created when the agent completes actions:
 * - New booking confirmed
 * - Task completed
 * - New customer message
 * - Payment received
 * - Integration connected/disconnected
 *
 * Supports: in-app bell with badge count, browser push notifications.
 */

import { create } from "zustand";

export type NotificationType =
  | "booking"
  | "task"
  | "message"
  | "payment"
  | "integration"
  | "system";

export interface AppNotification {
  id: string;
  type: NotificationType;
  title: string;
  body: string;
  timestamp: string;
  read: boolean;
  /** Optional action URL — clicking the notification navigates here */
  actionUrl?: string;
  /** Agent handle that generated this notification */
  agentHandle?: string;
}

interface NotificationState {
  notifications: AppNotification[];
  unreadCount: number;
  pushEnabled: boolean;

  /** Add a new notification (also triggers browser push if enabled) */
  addNotification: (n: Omit<AppNotification, "id" | "timestamp" | "read">) => void;
  /** Mark a single notification as read */
  markRead: (id: string) => void;
  /** Mark all as read */
  markAllRead: () => void;
  /** Clear all notifications */
  clearAll: () => void;
  /** Enable/disable browser push notifications */
  setPushEnabled: (enabled: boolean) => void;
  /** Request browser push permission */
  requestPushPermission: () => Promise<boolean>;
}

function generateId(): string {
  return `notif_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function sendBrowserNotification(title: string, body: string) {
  if (typeof window === "undefined") return;
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;

  try {
    new Notification(title, {
      body,
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-72.png",
      tag: "dingdawg-agent",
    });
  } catch {
    // Service worker notification fallback
    navigator.serviceWorker?.ready?.then((registration) => {
      registration.showNotification(title, {
        body,
        icon: "/icons/icon-192.png",
        badge: "/icons/icon-72.png",
        tag: "dingdawg-agent",
      });
    }).catch(() => {});
  }
}

const STORAGE_KEY = "dingdawg_notifications";

function loadFromStorage(): AppNotification[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as AppNotification[];
    // Keep only last 50 notifications, max 7 days old
    const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
    return parsed
      .filter((n) => new Date(n.timestamp).getTime() > cutoff)
      .slice(0, 50);
  } catch {
    return [];
  }
}

function saveToStorage(notifications: AppNotification[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(notifications.slice(0, 50)));
  } catch {}
}

export const useNotificationStore = create<NotificationState>((set, get) => ({
  notifications: loadFromStorage(),
  unreadCount: loadFromStorage().filter((n) => !n.read).length,
  pushEnabled:
    typeof window !== "undefined" && typeof Notification !== "undefined" && Notification.permission === "granted",

  addNotification: (n) => {
    const notification: AppNotification = {
      ...n,
      id: generateId(),
      timestamp: new Date().toISOString(),
      read: false,
    };

    set((state) => {
      const updated = [notification, ...state.notifications].slice(0, 50);
      saveToStorage(updated);
      return {
        notifications: updated,
        unreadCount: updated.filter((x) => !x.read).length,
      };
    });

    // Browser push notification
    if (get().pushEnabled) {
      sendBrowserNotification(n.title, n.body);
    }
  },

  markRead: (id) => {
    set((state) => {
      const updated = state.notifications.map((n) =>
        n.id === id ? { ...n, read: true } : n
      );
      saveToStorage(updated);
      return {
        notifications: updated,
        unreadCount: updated.filter((x) => !x.read).length,
      };
    });
  },

  markAllRead: () => {
    set((state) => {
      const updated = state.notifications.map((n) => ({ ...n, read: true }));
      saveToStorage(updated);
      return { notifications: updated, unreadCount: 0 };
    });
  },

  clearAll: () => {
    saveToStorage([]);
    set({ notifications: [], unreadCount: 0 });
  },

  setPushEnabled: (enabled) => set({ pushEnabled: enabled }),

  requestPushPermission: async () => {
    if (typeof window === "undefined" || typeof Notification === "undefined") return false;
    if (!("Notification" in window)) return false;

    if (Notification.permission === "granted") {
      set({ pushEnabled: true });
      return true;
    }

    if (Notification.permission === "denied") return false;

    const result = await Notification.requestPermission();
    const granted = result === "granted";
    set({ pushEnabled: granted });
    return granted;
  },
}));
