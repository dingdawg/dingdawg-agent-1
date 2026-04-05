/**
 * Shared type definitions for ISG Agent 1 bridges.
 */

/** A message received from or sent to a messaging platform. */
export interface BridgeMessage {
  /** Unique message identifier from the originating platform. */
  id: string;
  /** The platform this message originated from. */
  platform: "discord" | "telegram" | "websocket";
  /** User or channel identifier on the platform. */
  senderId: string;
  /** Human-readable sender name, if available. */
  senderName?: string;
  /** The text content of the message. */
  content: string;
  /** ISO 8601 timestamp of when the message was received. */
  timestamp: string;
  /** Optional metadata attached by the platform bridge. */
  metadata?: Record<string, unknown>;
}

/** Configuration for connecting a bridge to the gateway. */
export interface BridgeConfig {
  /** WebSocket URL of the ISG Agent 1 gateway. */
  gatewayUrl: string;
  /** Shared secret for authenticating with the gateway. */
  gatewaySecret: string;
  /** Platform-specific authentication token. */
  platformToken: string;
  /** Optional reconnect interval in milliseconds (default: 5000). */
  reconnectIntervalMs?: number;
  /** Optional maximum reconnect attempts (default: 10). */
  maxReconnectAttempts?: number;
}

/** Runtime status of a bridge connection. */
export interface BridgeStatus {
  /** Whether the bridge is currently connected to the gateway. */
  connected: boolean;
  /** The platform this bridge serves. */
  platform: BridgeMessage["platform"];
  /** Number of messages processed since last connection. */
  messagesProcessed: number;
  /** ISO 8601 timestamp of last successful heartbeat. */
  lastHeartbeat: string | null;
  /** Number of reconnect attempts since last successful connection. */
  reconnectAttempts: number;
}
