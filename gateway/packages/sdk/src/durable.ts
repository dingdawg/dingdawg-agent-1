/**
 * @dingdawg/sdk/durable — DurableDingDawgClient
 *
 * Extends DingDawgClient with DDAG v1 crash-proof execution:
 *   - invokeWithCheckpoint() — run agent step, get back a CID resume token
 *   - resume()              — continue from a checkpoint CID (any machine)
 *   - getSoul()             — retrieve an agent's IPFS-pinned identity
 *
 * What competitors don't have (in one SDK):
 *   ✅ Log-first WAL execution  — crash = replay from log, never lose progress
 *   ✅ IPFS content-addressed checkpoints — stateless resume on any machine
 *   ✅ Exactly-once semantics   — idempotency keys prevent double-execution
 *   ✅ Agent Soul persistence   — identity survives crashes and migrations
 *   ✅ Memory class retention   — A/B/C/D with IPFS anchoring for Class A
 */

import { DingDawgClient, DingDawgApiError } from "./client.js";
import type {
  DingDawgClientOptions,
  SendMessageOptions,
  TriggerResponse,
  ApiErrorBody,
} from "./types.js";

// ---------------------------------------------------------------------------
// FSM state enum — matches the DDAG v1 protocol state machine
// ---------------------------------------------------------------------------

export enum AgentFSMState {
  Idle         = "idle",
  Running      = "running",
  ToolPending  = "tool_pending",
  Verifying    = "verifying",
  Committing   = "committing",
  Remediating  = "remediating",
  Checkpointed = "checkpointed",
  Resuming     = "resuming",
  Done         = "done",
  Failed       = "failed",
}

// ---------------------------------------------------------------------------
// Durable types
// ---------------------------------------------------------------------------

/**
 * A content-addressed checkpoint snapshot.
 * Save `state_cid` — pass it to `resume()` to continue from this exact point.
 */
export interface CheckpointState {
  /** Session this checkpoint belongs to. */
  session_id: string;
  /** Execution step index (0-based). */
  step_index: number;
  /**
   * Content-addressed CID — the durable resume token.
   * Format: "ipfs:<hash>" when IPFS is available, "sha256:<hex>" for local fallback.
   */
  state_cid: string;
  /** FSM state at checkpoint time. */
  fsm_state: AgentFSMState;
  /** ISO-8601 UTC timestamp. */
  created_at: string;
}

/** IPFS-pinned agent identity — survives crashes, restarts, and migrations. */
export interface AgentSoul {
  soul_id: string;
  agent_id: string;
  /** CID of the current serialised soul state. */
  soul_cid: string;
  /** Plain-text mission statement — never changes. */
  mission: string;
  /** Mutable preferences updated each session. */
  learned_prefs: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** Options for a durable agent invocation. */
export interface DurableSession extends SendMessageOptions {
  /**
   * Resume from this checkpoint CID.
   * When provided, the agent skips already-completed steps (exactly-once guarantee).
   */
  resume_cid?: string;
  /**
   * Caller-supplied idempotency key.
   * If omitted the server derives one from (session_id + step_index + tool_name).
   */
  idempotency_key?: string;
  /** Checkpoint after every N steps (default: 1 — checkpoint every step). */
  checkpoint_every?: number;
}

/** Response from a durable invocation — always includes a CID for future resume. */
export interface DurableResponse extends TriggerResponse {
  /** Always returned — store this to resume after a crash. */
  checkpoint_cid: string;
  /** Current execution step index. */
  step_index: number;
  /** True when CHR PALP verification passed. */
  verified: boolean;
  /** IPFS CID of the CHR PALP proof (present only when verification ran). */
  proof_cid?: string;
  /** FSM state at response time. */
  fsm_state: AgentFSMState;
}

// ---------------------------------------------------------------------------
// SDK version
// ---------------------------------------------------------------------------

const SDK_USER_AGENT_DURABLE = "@dingdawg/sdk-durable/2.0.0";

// ---------------------------------------------------------------------------
// DurableDingDawgClient
// ---------------------------------------------------------------------------

/**
 * DurableDingDawgClient — crash-proof agent execution SDK.
 *
 * @example Basic durable invocation
 * ```ts
 * import { DurableDingDawgClient } from "@dingdawg/sdk";
 *
 * const client = new DurableDingDawgClient({ apiKey: "dd_live_..." });
 *
 * const result = await client.invokeWithCheckpoint("acme-support", {
 *   message: "Run the quarterly compliance report",
 *   userId: "user_123",
 * });
 *
 * // Save checkpoint_cid — if the process crashes, pass it to resume()
 * console.log(result.checkpoint_cid); // "ipfs:Qm..." or "sha256:..."
 * ```
 *
 * @example Resume after crash
 * ```ts
 * const resumed = await client.resume("acme-support", savedCheckpointCid);
 * // Agent continues from the exact step it left off — no re-execution
 * ```
 */
export class DurableDingDawgClient extends DingDawgClient {
  private readonly _durableApiKey: string;
  private readonly _durableBaseUrl: string;

  constructor(opts: DingDawgClientOptions) {
    super(opts);
    this._durableApiKey = opts.apiKey.trim();
    this._durableBaseUrl = (opts.baseUrl ?? "https://api.dingdawg.com").replace(/\/$/, "");
  }

  // -------------------------------------------------------------------------
  // Internal HTTP helper (mirrors DingDawgClient._request — kept private)
  // -------------------------------------------------------------------------

  private async _durableRequest<T>(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
    extraHeaders?: Record<string, string>
  ): Promise<T> {
    const url = `${this._durableBaseUrl}${path}`;

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "User-Agent": SDK_USER_AGENT_DURABLE,
      Authorization: `Bearer ${this._durableApiKey}`,
      "X-DingDawg-SDK": "2",
      ...extraHeaders,
    };

    const init: RequestInit = {
      method,
      headers,
      ...(body !== undefined && method !== "GET"
        ? { body: JSON.stringify(body) }
        : {}),
    };

    let resp: Response;
    try {
      resp = await fetch(url, init);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      throw new DingDawgApiError(
        { status: 0, body: { detail: `Network error: ${msg}` } },
        `Network error reaching DingDawg API: ${msg}`
      );
    }

    if (!resp.ok) {
      let errBody: ApiErrorBody | null = null;
      try {
        errBody = (await resp.json()) as ApiErrorBody;
      } catch { /* non-JSON error */ }
      throw new DingDawgApiError({ status: resp.status, body: errBody });
    }

    return (await resp.json()) as T;
  }

  // -------------------------------------------------------------------------
  // Public durable API
  // -------------------------------------------------------------------------

  /**
   * Invoke an agent with checkpoint support.
   *
   * The server journalises intent before execution and checkpoints state after.
   * The returned `checkpoint_cid` is the durable resume token — store it.
   * On crash, call `resume(handle, checkpoint_cid)` to continue without re-executing
   * completed steps.
   *
   * @param agentHandle - Agent handle (e.g. "acme-support").
   * @param opts        - Message options + optional resume_cid, idempotency_key, checkpoint_every.
   * @returns DurableResponse including checkpoint_cid, step_index, verified, fsm_state.
   */
  async invokeWithCheckpoint(
    agentHandle: string,
    opts: DurableSession
  ): Promise<DurableResponse> {
    const payload: Record<string, unknown> = {
      message: opts.message,
      user_id: opts.userId,
      session_id: opts.sessionId,
      metadata: opts.metadata,
      checkpoint_every: opts.checkpoint_every ?? 1,
    };

    if (opts.resume_cid !== undefined) payload["resume_cid"] = opts.resume_cid;
    if (opts.idempotency_key !== undefined) payload["idempotency_key"] = opts.idempotency_key;

    const extraHeaders: Record<string, string> = {};
    if (opts.idempotency_key !== undefined) {
      extraHeaders["Idempotency-Key"] = opts.idempotency_key;
    }

    const raw = await this._durableRequest<Record<string, unknown>>(
      "POST",
      `/api/v2/agents/${encodeURIComponent(agentHandle)}/durable/invoke`,
      payload,
      extraHeaders
    );

    return _normalizeDurableResponse(raw);
  }

  /**
   * Resume execution from a checkpoint CID.
   *
   * Stateless — can be called from any process, any machine.
   * The server restores state from the CID, skips already-completed steps,
   * and continues forward.
   *
   * @param agentHandle    - Agent handle.
   * @param checkpointCid  - The CID returned by a previous invokeWithCheckpoint call.
   * @returns DurableResponse with the next checkpoint_cid.
   */
  async resume(agentHandle: string, checkpointCid: string): Promise<DurableResponse> {
    const raw = await this._durableRequest<Record<string, unknown>>(
      "POST",
      `/api/v2/agents/${encodeURIComponent(agentHandle)}/durable/resume`,
      { checkpoint_cid: checkpointCid }
    );

    return _normalizeDurableResponse(raw);
  }

  /**
   * Retrieve an agent's soul — IPFS-pinned identity that survives all restarts.
   *
   * @param agentHandle - Agent handle.
   * @returns AgentSoul with soul_cid, mission, and learned_prefs.
   */
  async getSoul(agentHandle: string): Promise<AgentSoul> {
    const raw = await this._durableRequest<Record<string, unknown>>(
      "GET",
      `/api/v2/agents/${encodeURIComponent(agentHandle)}/soul`
    );

    return {
      soul_id: String(raw["soul_id"] ?? ""),
      agent_id: String(raw["agent_id"] ?? ""),
      soul_cid: String(raw["soul_cid"] ?? ""),
      mission: String(raw["mission"] ?? ""),
      learned_prefs: (raw["learned_prefs"] as Record<string, unknown>) ?? {},
      created_at: String(raw["created_at"] ?? ""),
      updated_at: String(raw["updated_at"] ?? ""),
    };
  }

  /**
   * Get the latest checkpoint for a session.
   *
   * Useful for polling long-running agent tasks.
   *
   * @param agentHandle - Agent handle.
   * @param sessionId   - Session ID.
   * @returns CheckpointState or null if no checkpoint exists yet.
   */
  async getCheckpoint(
    agentHandle: string,
    sessionId: string
  ): Promise<CheckpointState | null> {
    try {
      const raw = await this._durableRequest<Record<string, unknown>>(
        "GET",
        `/api/v2/agents/${encodeURIComponent(agentHandle)}/durable/checkpoint/${encodeURIComponent(sessionId)}`
      );
      return _normalizeCheckpointState(raw);
    } catch (err: unknown) {
      if (err instanceof DingDawgApiError && err.status === 404) return null;
      throw err;
    }
  }
}

// ---------------------------------------------------------------------------
// Normalizers
// ---------------------------------------------------------------------------

function _normalizeDurableResponse(raw: Record<string, unknown>): DurableResponse {
  return {
    reply: String(raw["reply"] ?? raw["response"] ?? ""),
    sessionId: String(raw["session_id"] ?? raw["sessionId"] ?? ""),
    timestamp: String(raw["timestamp"] ?? new Date().toISOString()),
    queued: raw["queued"] === true,
    ...(raw["model"] !== undefined ? { model: String(raw["model"]) } : {}),
    checkpoint_cid: String(raw["checkpoint_cid"] ?? ""),
    step_index: (raw["step_index"] as number) ?? 0,
    verified: raw["verified"] === true,
    fsm_state: (raw["fsm_state"] as AgentFSMState) ?? AgentFSMState.Done,
    ...(raw["proof_cid"] !== undefined ? { proof_cid: String(raw["proof_cid"]) } : {}),
  };
}

function _normalizeCheckpointState(raw: Record<string, unknown>): CheckpointState {
  return {
    session_id: String(raw["session_id"] ?? ""),
    step_index: (raw["step_index"] as number) ?? 0,
    state_cid: String(raw["state_cid"] ?? ""),
    fsm_state: (raw["fsm_state"] as AgentFSMState) ?? AgentFSMState.Idle,
    created_at: String(raw["created_at"] ?? ""),
  };
}
