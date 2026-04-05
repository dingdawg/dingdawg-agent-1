/**
 * @dingdawg/sdk — Public API
 *
 * Re-exports everything a partner integration needs:
 * - DingDawgClient (main class)
 * - DurableDingDawgClient (crash-proof execution — DDAG v1)
 * - DingDawgApiError (typed error)
 * - All TypeScript interfaces and types
 */

export { DingDawgClient, DingDawgApiError } from "./client.js";

export type {
  // Client config
  DingDawgClientOptions,
  // Agent types
  AgentType,
  AgentStatus,
  AgentBranding,
  CreateAgentOptions,
  AgentRecord,
  // Message / trigger types
  SendMessageOptions,
  TriggerResponse,
  // Billing types
  BillingLineItem,
  MonthlyBillingSummary,
  BillingSummary,
  // Utilities
  PaginatedList,
  ApiErrorBody,
  DingDawgApiErrorDetails,
} from "./types.js";

// DDAG v1 — Durable execution SDK
export { DurableDingDawgClient, AgentFSMState } from "./durable.js";

export type {
  CheckpointState,
  AgentSoul,
  DurableSession,
  DurableResponse,
} from "./durable.js";
