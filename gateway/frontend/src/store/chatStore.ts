/**
 * Chat store — Zustand state for messages and streaming.
 *
 * Dual storage strategy:
 *  - Zustand: in-memory, instant UI reads/writes (source of truth for rendering)
 *  - Dexie (IndexedDB): async, non-blocking writes for persistence across page reloads
 *
 * All Dexie writes are fire-and-forget (void async). They never block the UI.
 * On session load, Dexie is read once to hydrate Zustand.
 */

"use client";

import { create } from "zustand";
import { generateId } from "@/lib/utils";
import * as chatDb from "@/lib/chatDb";

// ─── Types ────────────────────────────────────────────────────────────────────

export type MessageType =
  | "text"
  | "kpi-cards"
  | "task-card"
  | "task-list"
  | "agent-status"
  | "quick-replies";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  type: MessageType;
  status: "pending" | "streaming" | "final" | "error";
  timestamp: number;
  model?: string;
  tokens_used?: number;
  governance_decision?: "PROCEED" | "REVIEW" | "HALT";
  governance_risk?: string;
}

interface FinalizeAssistantMeta {
  content: string;
  model?: string;
  tokens_used?: number;
  governance_decision?: "PROCEED" | "REVIEW" | "HALT";
  governance_risk?: string;
}

interface ChatState {
  messages: ChatMessage[];
  isStreaming: boolean;
  /** Active Dexie session ID — set externally via setActiveSession. */
  activeSessionId: string | null;

  /**
   * Set the active Dexie session ID.
   * Call this whenever the backend session changes so Dexie writes land
   * in the correct bucket.
   */
  setActiveSession: (sessionId: string | null) => void;

  appendUserMessage: (content: string) => string;
  appendAssistantMessage: (
    content: string,
    meta?: {
      model?: string;
      tokens_used?: number;
      governance_decision?: "PROCEED" | "REVIEW" | "HALT";
      governance_risk?: string;
    }
  ) => void;
  /** Append an empty assistant bubble with status "streaming" and return its id. */
  appendStreamingAssistantMessage: () => string;
  appendSystemMessage: (content: string) => void;
  setStreaming: (streaming: boolean) => void;
  updateLastAssistant: (content: string) => void;
  /** Flip the last streaming assistant bubble to "final" and attach metadata. */
  finalizeLastAssistant: (meta: FinalizeAssistantMeta) => void;
  setLastAssistantError: (errorMessage: string) => void;
  reset: () => void;
  loadMessages: (messages: ChatMessage[]) => void;

  /**
   * Load messages for a session from Dexie into Zustand.
   * Replaces current in-memory messages with the persisted history.
   */
  loadSession: (sessionId: string) => Promise<void>;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Convert a ChatMessage to the shape Dexie expects.
 * timestamp: number (ms) → ISO-8601 string.
 * Only "final" messages are persisted — streaming/pending/error bubbles are skipped.
 */
function toDbMessage(
  msg: ChatMessage,
  sessionId: string,
): chatDb.DbMessage {
  return {
    id: msg.id,
    sessionId,
    role: msg.role,
    content: msg.content,
    timestamp: new Date(msg.timestamp).toISOString(),
  };
}

/**
 * Convert a DbMessage back to a ChatMessage for Zustand hydration.
 */
function fromDbMessage(dbMsg: chatDb.DbMessage): ChatMessage {
  return {
    id: dbMsg.id,
    sessionId: dbMsg.sessionId,
    role: dbMsg.role,
    content: dbMsg.content,
    type: "text",
    status: "final",
    timestamp: new Date(dbMsg.timestamp).getTime(),
  } as ChatMessage & { sessionId?: string };
}

/**
 * Fire-and-forget Dexie write. Never throws to the caller.
 */
function persistMessage(msg: ChatMessage, sessionId: string | null): void {
  if (!sessionId) return;
  // Only persist fully complete messages
  if (msg.status !== "final") return;
  chatDb.addMessage(toDbMessage(msg, sessionId)).catch((err: unknown) => {
    console.warn("[chatStore] Dexie write failed:", err);
  });
}

/**
 * Fire-and-forget Dexie update for a finalized assistant message.
 */
function persistUpdate(
  msgId: string,
  updates: Partial<chatDb.DbMessage>,
): void {
  chatDb.updateMessage(msgId, updates).catch((err: unknown) => {
    console.warn("[chatStore] Dexie update failed:", err);
  });
}

// ─── Store ────────────────────────────────────────────────────────────────────

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isStreaming: false,
  activeSessionId: null,

  setActiveSession: (sessionId) => {
    set({ activeSessionId: sessionId });
  },

  appendUserMessage: (content: string) => {
    const id = generateId("msg");
    const msg: ChatMessage = {
      id,
      role: "user",
      content,
      type: "text" as const,
      status: "final",
      timestamp: Date.now(),
    };
    set((state) => ({ messages: [...state.messages, msg] }));
    persistMessage(msg, get().activeSessionId);
    return id;
  },

  appendAssistantMessage: (content, meta) => {
    const id = generateId("msg");
    const msg: ChatMessage = {
      id,
      role: "assistant",
      content,
      type: "text" as const,
      status: "final",
      timestamp: Date.now(),
      model: meta?.model,
      tokens_used: meta?.tokens_used,
      governance_decision: meta?.governance_decision,
      governance_risk: meta?.governance_risk,
    };
    set((state) => ({
      messages: [...state.messages, msg],
      isStreaming: false,
    }));
    persistMessage(msg, get().activeSessionId);
  },

  appendStreamingAssistantMessage: () => {
    const id = generateId("msg");
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id,
          role: "assistant" as const,
          content: "",
          type: "text" as const,
          status: "streaming" as const,
          timestamp: Date.now(),
        },
      ],
      isStreaming: true,
    }));
    // No Dexie write — message is not final yet
    return id;
  },

  finalizeLastAssistant: (meta) => {
    let finalizedId: string | null = null;
    let finalizedTimestamp: number | null = null;

    set((state) => {
      const msgs = [...state.messages];
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i]!.role === "assistant") {
          finalizedId = msgs[i]!.id;
          finalizedTimestamp = msgs[i]!.timestamp;
          msgs[i] = {
            ...msgs[i]!,
            content: meta.content,
            status: "final",
            model: meta.model,
            tokens_used: meta.tokens_used,
            governance_decision: meta.governance_decision,
            governance_risk: meta.governance_risk,
          };
          break;
        }
      }
      return { messages: msgs, isStreaming: false };
    });

    // Persist to Dexie now that the message is final.
    // Use addMessage (not updateMessage) because the streaming bubble was never written.
    const sessionId = get().activeSessionId;
    if (finalizedId && sessionId) {
      chatDb.addMessage({
        id: finalizedId,
        sessionId,
        role: "assistant",
        content: meta.content,
        timestamp: new Date(finalizedTimestamp ?? Date.now()).toISOString(),
      }).catch((err: unknown) => {
        // If the message already exists (e.g. double-fire), fall back to update
        void persistUpdate(finalizedId!, {
          content: meta.content,
          timestamp: new Date(finalizedTimestamp ?? Date.now()).toISOString(),
        });
        console.warn("[chatStore] Dexie finalizeLastAssistant add failed, retried update:", err);
      });
    }
  },

  appendSystemMessage: (content) => {
    const id = generateId("sys");
    const msg: ChatMessage = {
      id,
      role: "system",
      content,
      type: "text" as const,
      status: "final",
      timestamp: Date.now(),
    };
    set((state) => ({ messages: [...state.messages, msg] }));
    // System messages (welcome/greeting) are also persisted
    persistMessage(msg, get().activeSessionId);
  },

  setStreaming: (streaming) => set({ isStreaming: streaming }),

  updateLastAssistant: (content) => {
    set((state) => {
      const msgs = [...state.messages];
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i]!.role === "assistant") {
          msgs[i] = { ...msgs[i]!, content, status: "streaming" };
          break;
        }
      }
      return { messages: msgs };
    });
    // No Dexie write during streaming — wait for finalizeLastAssistant
  },

  setLastAssistantError: (errorMessage) => {
    set((state) => {
      const msgs = [...state.messages];
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i]!.role === "assistant") {
          msgs[i] = {
            ...msgs[i]!,
            content: errorMessage,
            status: "error",
          };
          break;
        }
      }
      return { messages: msgs, isStreaming: false };
    });
    // Error bubbles are not persisted — they reflect transient network failures
  },

  reset: () => {
    set({ messages: [], isStreaming: false });
    // Note: does NOT clear Dexie — session history is preserved for reload.
    // To wipe Dexie history, use chatDb.deleteSession(sessionId) directly.
  },

  loadMessages: (messages) => set({ messages }),

  loadSession: async (sessionId: string) => {
    try {
      const dbMessages = await chatDb.getMessages(sessionId);
      const messages = dbMessages.map(fromDbMessage);
      set({ messages, activeSessionId: sessionId });
    } catch (err: unknown) {
      console.warn("[chatStore] loadSession failed:", err);
    }
  },
}));
