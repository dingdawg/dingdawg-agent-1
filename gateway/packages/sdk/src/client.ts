/**
 * @dingdawg/sdk — DingDawgClient
 *
 * The primary entry point for B2B2C partners embedding DingDawg agents.
 *
 * Design goals:
 * - Zero runtime dependencies (Node 18+ built-in fetch only)
 * - Full TypeScript types on all inputs and outputs
 * - Typed error class so callers can catch + inspect failures
 * - Grouped API namespaces: client.agent.* and client.billing.*
 */

import type {
  AgentRecord,
  BillingSummary,
  CreateAgentOptions,
  DingDawgClientOptions,
  MonthlyBillingSummary,
  PaginatedList,
  SendMessageOptions,
  TriggerResponse,
  ApiErrorBody,
  DingDawgApiErrorDetails,
} from "./types.js";

// ---------------------------------------------------------------------------
// Default configuration
// ---------------------------------------------------------------------------

const DEFAULT_BASE_URL = "https://api.dingdawg.com";

const SDK_USER_AGENT = "@dingdawg/sdk/0.1.0";

// ---------------------------------------------------------------------------
// Typed error class
// ---------------------------------------------------------------------------

/**
 * Thrown by all DingDawgClient methods when the API returns a non-2xx status.
 *
 * @example
 * ```ts
 * try {
 *   await client.agent.get("non-existent-id");
 * } catch (err) {
 *   if (err instanceof DingDawgApiError) {
 *     console.error(err.status, err.body?.detail);
 *   }
 * }
 * ```
 */
export class DingDawgApiError extends Error {
  /** HTTP status code. */
  readonly status: number;
  /** Parsed error body from the API, or null if the body was not JSON. */
  readonly body: ApiErrorBody | null;

  constructor(details: DingDawgApiErrorDetails, message?: string) {
    const derived =
      message ??
      details.body?.detail ??
      details.body?.message ??
      `DingDawg API error: HTTP ${details.status}`;
    super(String(derived));
    this.name = "DingDawgApiError";
    this.status = details.status;
    this.body = details.body;
    // Maintains proper prototype chain in transpiled environments
    Object.setPrototypeOf(this, DingDawgApiError.prototype);
  }
}

// ---------------------------------------------------------------------------
// Internal HTTP helpers
// ---------------------------------------------------------------------------

/**
 * Parse a Response, throwing DingDawgApiError on non-2xx status.
 *
 * @internal
 */
async function _parseResponse<T>(resp: Response): Promise<T> {
  let body: unknown = null;
  const contentType = resp.headers.get("content-type") ?? "";

  if (contentType.includes("application/json")) {
    try {
      body = await resp.json();
    } catch {
      body = null;
    }
  } else {
    try {
      body = await resp.text();
    } catch {
      body = null;
    }
  }

  if (!resp.ok) {
    const errorBody: ApiErrorBody | null =
      body !== null && typeof body === "object"
        ? (body as ApiErrorBody)
        : typeof body === "string"
        ? { detail: body }
        : null;

    throw new DingDawgApiError({ status: resp.status, body: errorBody });
  }

  return body as T;
}

// ---------------------------------------------------------------------------
// Agent API namespace
// ---------------------------------------------------------------------------

/** Methods for managing agents. Available as `client.agent`. */
export interface AgentApi {
  /**
   * Create a new agent.
   *
   * @param opts - Agent creation options.
   * @returns The newly created AgentRecord.
   */
  create(opts: CreateAgentOptions): Promise<AgentRecord>;

  /**
   * List all agents belonging to the authenticated partner account.
   *
   * @param params - Optional pagination parameters.
   * @returns Paginated list of AgentRecords.
   */
  list(params?: { limit?: number; offset?: number }): Promise<PaginatedList<AgentRecord>>;

  /**
   * Get a single agent by ID.
   *
   * @param id - Agent UUID.
   * @returns The AgentRecord.
   */
  get(id: string): Promise<AgentRecord>;

  /**
   * Send a message to an agent via the trigger endpoint.
   *
   * @param agentId - Agent UUID.
   * @param message - Message text or full options object.
   * @returns The agent's reply and session information.
   */
  sendMessage(
    agentId: string,
    message: string | SendMessageOptions
  ): Promise<TriggerResponse>;
}

// ---------------------------------------------------------------------------
// Billing API namespace
// ---------------------------------------------------------------------------

/** Methods for querying billing and usage. Available as `client.billing`. */
export interface BillingApi {
  /**
   * Get billing details for the current calendar month.
   *
   * @returns Monthly billing summary including line items and free-tier usage.
   */
  currentMonth(): Promise<MonthlyBillingSummary>;

  /**
   * Get aggregate billing summary (lifetime + current month).
   *
   * @returns Full billing summary.
   */
  summary(): Promise<BillingSummary>;
}

// ---------------------------------------------------------------------------
// Main client class
// ---------------------------------------------------------------------------

/**
 * DingDawgClient — the single entry point for the DingDawg Agent SDK.
 *
 * @example
 * ```ts
 * import { DingDawgClient } from "@dingdawg/sdk";
 *
 * const client = new DingDawgClient({ apiKey: "dd_live_..." });
 *
 * const agent = await client.agent.create({
 *   name: "Support Bot",
 *   handle: "acme-support",
 *   agentType: "business",
 * });
 *
 * const reply = await client.agent.sendMessage(agent.id, "Hello!");
 * console.log(reply.reply);
 * ```
 */
export class DingDawgClient {
  private readonly _apiKey: string;
  private readonly _baseUrl: string;

  /** Methods for managing agents. */
  readonly agent: AgentApi;

  /** Methods for querying billing and usage. */
  readonly billing: BillingApi;

  /**
   * Create a new DingDawgClient instance.
   *
   * @param opts - Configuration options.
   * @throws {TypeError} When apiKey is missing or empty.
   */
  constructor(opts: DingDawgClientOptions) {
    if (!opts.apiKey || typeof opts.apiKey !== "string" || opts.apiKey.trim() === "") {
      throw new TypeError(
        "DingDawgClient: apiKey is required and must be a non-empty string"
      );
    }

    this._apiKey = opts.apiKey.trim();
    this._baseUrl = (opts.baseUrl ?? DEFAULT_BASE_URL).replace(/\/$/, "");

    // Bind namespace objects so methods can be destructured safely
    this.agent = this._buildAgentApi();
    this.billing = this._buildBillingApi();
  }

  // -------------------------------------------------------------------------
  // Internal HTTP request
  // -------------------------------------------------------------------------

  /**
   * Perform an authenticated JSON request.
   *
   * @internal
   */
  private async _request<T>(
    method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
    path: string,
    body?: unknown
  ): Promise<T> {
    const url = `${this._baseUrl}${path}`;

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "User-Agent": SDK_USER_AGENT,
      Authorization: `Bearer ${this._apiKey}`,
      "X-DingDawg-SDK": "1",
    };

    const init: RequestInit = { method, headers };

    if (body !== undefined && method !== "GET") {
      init.body = JSON.stringify(body);
    }

    let resp: Response;
    try {
      resp = await fetch(url, init);
    } catch (err: unknown) {
      // Network-level failure (DNS, connection refused, etc.)
      const message = err instanceof Error ? err.message : String(err);
      throw new DingDawgApiError(
        { status: 0, body: { detail: `Network error: ${message}` } },
        `Network error reaching DingDawg API: ${message}`
      );
    }

    return _parseResponse<T>(resp);
  }

  // -------------------------------------------------------------------------
  // Agent API builder
  // -------------------------------------------------------------------------

  private _buildAgentApi(): AgentApi {
    return {
      create: async (opts: CreateAgentOptions): Promise<AgentRecord> => {
        const payload = {
          name: opts.name,
          handle: opts.handle,
          agent_type: opts.agentType ?? "business",
          industry_type: opts.industry,
          system_prompt: opts.systemPrompt,
          template_id: opts.templateId,
          branding: opts.branding
            ? {
                primary_color: opts.branding.primaryColor,
                avatar_url: opts.branding.avatarUrl,
              }
            : undefined,
        };

        const raw = await this._request<Record<string, unknown>>(
          "POST",
          "/api/v2/partner/agents",
          payload
        );

        return _normalizeAgent(raw);
      },

      list: async (
        params: { limit?: number; offset?: number } = {}
      ): Promise<PaginatedList<AgentRecord>> => {
        const qs = new URLSearchParams();
        if (params.limit !== undefined) qs.set("limit", String(params.limit));
        if (params.offset !== undefined) qs.set("offset", String(params.offset));
        const queryString = qs.toString();
        const path = queryString
          ? `/api/v2/partner/agents?${queryString}`
          : "/api/v2/partner/agents";

        const raw = await this._request<Record<string, unknown>>("GET", path);
        const items = (raw["items"] ?? raw["agents"] ?? []) as Record<
          string,
          unknown
        >[];

        return {
          items: items.map(_normalizeAgent),
          total: (raw["total"] as number) ?? items.length,
          limit: (raw["limit"] as number) ?? (params.limit ?? 20),
          offset: (raw["offset"] as number) ?? (params.offset ?? 0),
        };
      },

      get: async (id: string): Promise<AgentRecord> => {
        const raw = await this._request<Record<string, unknown>>(
          "GET",
          `/api/v2/partner/agents/${encodeURIComponent(id)}`
        );
        return _normalizeAgent(raw);
      },

      sendMessage: async (
        agentId: string,
        message: string | SendMessageOptions
      ): Promise<TriggerResponse> => {
        const opts: SendMessageOptions =
          typeof message === "string" ? { message } : message;

        const payload = {
          message: opts.message,
          user_id: opts.userId,
          session_id: opts.sessionId,
          metadata: opts.metadata,
        };

        const raw = await this._request<Record<string, unknown>>(
          "POST",
          `/api/v1/agents/${encodeURIComponent(agentId)}/trigger`,
          payload
        );

        const triggerResult: TriggerResponse = {
          reply: String(raw["reply"] ?? raw["response"] ?? ""),
          sessionId: String(raw["session_id"] ?? raw["sessionId"] ?? ""),
          timestamp: String(raw["timestamp"] ?? new Date().toISOString()),
          queued: raw["queued"] === true,
          ...(raw["model"] !== undefined ? { model: String(raw["model"]) } : {}),
        };
        return triggerResult;
      },
    };
  }

  // -------------------------------------------------------------------------
  // Billing API builder
  // -------------------------------------------------------------------------

  private _buildBillingApi(): BillingApi {
    return {
      currentMonth: async (): Promise<MonthlyBillingSummary> => {
        const raw = await this._request<Record<string, unknown>>(
          "GET",
          "/api/v2/partner/billing/current-month"
        );
        return _normalizeMonthlySummary(raw);
      },

      summary: async (): Promise<BillingSummary> => {
        const raw = await this._request<Record<string, unknown>>(
          "GET",
          "/api/v2/partner/billing"
        );

        const currentMonth = _normalizeMonthlySummary(
          (raw["current_month"] as Record<string, unknown> | undefined) ?? {}
        );

        const billingSummaryResult: BillingSummary = {
          totalActions: (raw["total_actions"] as number) ?? 0,
          totalCents: (raw["total_cents"] as number) ?? 0,
          currentMonth,
          ...(raw["stripe_customer_id"] !== undefined
            ? { stripeCustomerId: String(raw["stripe_customer_id"]) }
            : {}),
        };
        return billingSummaryResult;
      },
    };
  }
}

// ---------------------------------------------------------------------------
// Normalizer helpers (snake_case → camelCase)
// ---------------------------------------------------------------------------

function _normalizeAgent(raw: Record<string, unknown>): AgentRecord {
  const branding = raw["branding"] as Record<string, unknown> | undefined;

  return {
    id: String(raw["id"] ?? raw["agent_id"] ?? ""),
    handle: String(raw["handle"] ?? ""),
    name: String(raw["name"] ?? ""),
    agentType: (raw["agent_type"] ?? raw["agentType"] ?? "business") as AgentRecord["agentType"],
    industry: raw["industry_type"] !== undefined
      ? String(raw["industry_type"])
      : raw["industry"] !== undefined
      ? String(raw["industry"])
      : null,
    status: (raw["status"] ?? "active") as AgentRecord["status"],
    createdAt: String(raw["created_at"] ?? raw["createdAt"] ?? ""),
    updatedAt: String(raw["updated_at"] ?? raw["updatedAt"] ?? ""),
    ...(branding
      ? {
          branding: {
            ...(branding["primary_color"] !== undefined
              ? { primaryColor: String(branding["primary_color"]) }
              : {}),
            ...(branding["avatar_url"] !== undefined
              ? { avatarUrl: String(branding["avatar_url"]) }
              : {}),
          },
        }
      : {}),
  };
}

function _normalizeMonthlySummary(
  raw: Record<string, unknown>
): MonthlyBillingSummary {
  const lineItemsRaw = Array.isArray(raw["line_items"]) ? raw["line_items"] : [];

  return {
    month: String(raw["month"] ?? ""),
    totalActions: (raw["total_actions"] as number) ?? 0,
    totalCents: (raw["total_cents"] as number) ?? 0,
    freeActionsRemaining: (raw["free_actions_remaining"] as number) ?? 0,
    lineItems: (lineItemsRaw as Record<string, unknown>[]).map((item) => ({
      action: String(item["action"] ?? ""),
      count: (item["count"] as number) ?? 0,
      costCents: (item["cost_cents"] as number) ?? 0,
    })),
  };
}
