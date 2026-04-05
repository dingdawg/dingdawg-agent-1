/**
 * @dingdawg/sdk — TypeScript types for all request and response shapes.
 *
 * All interfaces are exported so partner integrations can type their own code.
 * Zero runtime imports — types are erased at compile time.
 */

// ---------------------------------------------------------------------------
// Client configuration
// ---------------------------------------------------------------------------

/** Options passed to the DingDawgClient constructor. */
export interface DingDawgClientOptions {
  /** API key issued via the DingDawg dashboard or partner program. */
  apiKey: string;
  /** Base URL of the DingDawg API. Defaults to https://api.dingdawg.com */
  baseUrl?: string;
}

// ---------------------------------------------------------------------------
// Error types
// ---------------------------------------------------------------------------

/** Structured API error returned by the DingDawg backend. */
export interface ApiErrorBody {
  detail?: string;
  message?: string;
  code?: string;
  [key: string]: unknown;
}

/** Error thrown when an API call fails with a non-2xx response. */
export interface DingDawgApiErrorDetails {
  /** HTTP status code (e.g. 401, 422, 500). */
  status: number;
  /** Parsed error body from the API, if available. */
  body: ApiErrorBody | null;
}

// ---------------------------------------------------------------------------
// Agent types
// ---------------------------------------------------------------------------

/** Agent type identifier. */
export type AgentType =
  | "personal"
  | "business"
  | "b2b"
  | "a2a"
  | "compliance"
  | "enterprise"
  | "health"
  | "gaming";

/** Agent status values. */
export type AgentStatus = "active" | "inactive" | "suspended";

/** Branding configuration for an agent. */
export interface AgentBranding {
  /** Hex color string (e.g. "#7C3AED"). */
  primaryColor?: string;
  /** Public URL to an avatar image. */
  avatarUrl?: string;
}

/** Options for creating a new agent. */
export interface CreateAgentOptions {
  /** Display name of the agent. */
  name: string;
  /** Unique handle (without @). Must be 3-32 alphanumeric + underscores. */
  handle: string;
  /** Agent type selector. Defaults to "business". */
  agentType?: AgentType;
  /** Sector / industry label (e.g. "restaurant", "gaming", "legal"). */
  industry?: string;
  /** System prompt / constitution text. */
  systemPrompt?: string;
  /** Template ID to initialise the agent from. */
  templateId?: string;
  /** Branding overrides. */
  branding?: AgentBranding;
}

/** A deployed agent record returned by the API. */
export interface AgentRecord {
  id: string;
  handle: string;
  name: string;
  agentType: AgentType;
  industry: string | null;
  status: AgentStatus;
  createdAt: string;
  updatedAt: string;
  /** Parsed branding config. Present on GET /agents/:id, may be absent in list. */
  branding?: AgentBranding;
}

// ---------------------------------------------------------------------------
// Message / trigger types
// ---------------------------------------------------------------------------

/** Options for sending a message to an agent via the trigger endpoint. */
export interface SendMessageOptions {
  /** The message text to deliver. */
  message: string;
  /** User / customer identifier (for conversation continuity). */
  userId?: string;
  /** Session identifier to continue an existing conversation. */
  sessionId?: string;
  /** Arbitrary metadata forwarded to the agent runtime. */
  metadata?: Record<string, unknown>;
}

/** Response returned after triggering an agent. */
export interface TriggerResponse {
  /** The agent's reply text. */
  reply: string;
  /** Session ID (reuse to continue the conversation). */
  sessionId: string;
  /** ISO-8601 timestamp of the response. */
  timestamp: string;
  /** Model / provider used to generate the reply. */
  model?: string;
  /** True when the agent queued the message for async processing. */
  queued?: boolean;
}

// ---------------------------------------------------------------------------
// Billing types
// ---------------------------------------------------------------------------

/** Line item in a billing period. */
export interface BillingLineItem {
  /** Action / skill name (e.g. "crm_lookup", "email_send"). */
  action: string;
  /** Number of times this action was executed. */
  count: number;
  /** Cost in USD cents. */
  costCents: number;
}

/** Billing summary for a single month. */
export interface MonthlyBillingSummary {
  /** ISO-8601 month string (e.g. "2026-03"). */
  month: string;
  /** Total actions executed. */
  totalActions: number;
  /** Total charges in USD cents. */
  totalCents: number;
  /** Number of free-tier actions remaining (50 free/month). */
  freeActionsRemaining: number;
  /** Breakdown by action type. */
  lineItems: BillingLineItem[];
}

/** Aggregate billing summary across all time. */
export interface BillingSummary {
  /** Total lifetime actions. */
  totalActions: number;
  /** Total lifetime spend in USD cents. */
  totalCents: number;
  /** Current month billing. */
  currentMonth: MonthlyBillingSummary;
  /** Stripe customer ID if billing is set up. */
  stripeCustomerId?: string;
}

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------

/** Generic paginated list wrapper. */
export interface PaginatedList<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
