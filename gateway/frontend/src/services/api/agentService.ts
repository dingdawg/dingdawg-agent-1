/**
 * Agent service — session and message management.
 *
 * Backend endpoints (all require auth):
 *   POST   /api/v1/sessions              — create session
 *   GET    /api/v1/sessions              — list sessions
 *   POST   /api/v1/sessions/{id}/message — send message
 *   DELETE /api/v1/sessions/{id}         — delete session
 *
 * Streaming (widget SSE — public, CORS open):
 *   POST   /api/v1/widget/{agent_handle}/stream
 *     body:   { session_id, message, visitor_id? }
 *     events: token | action | done | error
 */

import { get, post, del, getAccessToken } from "./client";

export interface Session {
  session_id: string;
  user_id: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  total_tokens: number;
  status: string;
}

export interface SessionCreateRequest {
  system_prompt?: string;
  agent_id?: string;
}

export interface MessageRequest {
  content: string;
}

export interface MessageResponse {
  content: string;
  session_id: string;
  model_used: string;
  input_tokens: number;
  output_tokens: number;
  governance_decision: string;
  convergence_status: string;
  halted: boolean;
}

/**
 * Create a new agent session.
 */
export async function createSession(
  body?: SessionCreateRequest
): Promise<Session> {
  return post<Session>("/api/v1/sessions", body ?? {});
}

/**
 * List all sessions for the current user.
 */
export async function listSessions(): Promise<Session[]> {
  const data = await get<{ sessions: Session[]; count: number } | Session[]>(
    "/api/v1/sessions"
  );
  if (Array.isArray(data)) return data;
  return data.sessions ?? [];
}

/**
 * Send a message to a session and get the response.
 */
export async function sendMessage(
  sessionId: string,
  content: string
): Promise<MessageResponse> {
  return post<MessageResponse>(
    `/api/v1/sessions/${sessionId}/message`,
    { content }
  );
}

/**
 * Delete a session.
 */
export async function deleteSession(sessionId: string): Promise<void> {
  await del(`/api/v1/sessions/${sessionId}`);
}

// ─── Streaming types ──────────────────────────────────────────────────────────

export interface StreamCallbacks {
  /** Called for each token chunk as it arrives. */
  onToken: (token: string) => void;
  /** Called once when the stream completes successfully. */
  onDone: (payload: {
    full_response: string;
    session_id: string;
    halted: boolean;
    action?: {
      skill: string;
      action: string;
      result: unknown;
    } | null;
  }) => void;
  /** Called if the stream encounters an error (mid-stream or connection). */
  onError: (message: string) => void;
}

/**
 * Stream tokens from the widget SSE endpoint using native fetch + ReadableStream.
 *
 * Uses POST /api/v1/widget/{agent_handle}/stream.
 * The endpoint is public (no JWT required) but we attach the bearer token
 * if available so authenticated users get per-agent personalisation.
 *
 * Returns an AbortController — call .abort() to cancel the stream on navigation
 * or user cancellation.
 *
 * Falls back to sendMessage() if ReadableStream is unsupported.
 */
export function sendMessageStream(
  agentHandle: string,
  sessionId: string,
  message: string,
  callbacks: StreamCallbacks
): AbortController {
  const controller = new AbortController();

  // Check ReadableStream support — if missing, fall back to single-shot
  if (
    typeof ReadableStream === "undefined" ||
    !("getReader" in ReadableStream.prototype)
  ) {
    sendMessage(sessionId, message)
      .then((res) => {
        callbacks.onToken(res.content);
        callbacks.onDone({
          full_response: res.content,
          session_id: res.session_id,
          halted: res.halted,
          action: null,
        });
      })
      .catch((err: unknown) => {
        callbacks.onError(
          err instanceof Error ? err.message : "Failed to get response"
        );
      });
    return controller;
  }

  const handle = agentHandle.replace(/^@/, "");

  // Build headers — attach auth token if present (best-effort)
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    // Hint: disable Nginx response buffering so tokens flush immediately
    "X-Accel-Buffering": "no",
  };
  const token = getAccessToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  // Run the stream in the background (non-blocking, errors routed to callbacks)
  void _runStream(handle, sessionId, message, headers, controller, callbacks);

  return controller;
}

/**
 * Internal async runner for the SSE stream.
 * Separated from sendMessageStream so the public API stays synchronous.
 */
async function _runStream(
  handle: string,
  sessionId: string,
  message: string,
  headers: Record<string, string>,
  controller: AbortController,
  callbacks: StreamCallbacks
): Promise<void> {
  let response: Response;

  try {
    response = await fetch(`/api/v1/widget/${handle}/stream`, {
      method: "POST",
      headers,
      body: JSON.stringify({ session_id: sessionId, message }),
      signal: controller.signal,
    });
  } catch (err: unknown) {
    if ((err as { name?: string })?.name === "AbortError") return; // intentional cancel
    callbacks.onError(
      err instanceof Error ? err.message : "Network error — could not connect"
    );
    return;
  }

  if (!response.ok) {
    callbacks.onError(`Server error ${response.status}: ${response.statusText}`);
    return;
  }

  const body = response.body;
  if (!body) {
    callbacks.onError("No response body from streaming endpoint");
    return;
  }

  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");

  // Accumulate partial lines across chunks (SSE lines may be split across TCP frames)
  let lineBuffer = "";

  // requestAnimationFrame batching — we queue token updates and flush on the
  // next animation frame to avoid thrashing the React store on every token.
  let pendingTokens = "";
  let rafHandle: ReturnType<typeof requestAnimationFrame> | null = null;

  const flushTokens = () => {
    rafHandle = null;
    if (pendingTokens) {
      callbacks.onToken(pendingTokens);
      pendingTokens = "";
    }
  };

  const scheduleFlush = () => {
    if (rafHandle === null) {
      rafHandle = requestAnimationFrame(flushTokens);
    }
  };

  try {
    while (true) {
      let done: boolean;
      let value: Uint8Array | undefined;

      try {
        ({ done, value } = await reader.read());
      } catch (err: unknown) {
        if ((err as { name?: string })?.name === "AbortError") break; // intentional cancel
        throw err;
      }

      if (done) break;
      if (!value) continue;

      lineBuffer += decoder.decode(value, { stream: true });

      // Process complete lines from the buffer
      const lines = lineBuffer.split("\n");
      // Last element may be an incomplete line — keep it for the next chunk
      lineBuffer = lines.pop() ?? "";

      let currentEvent = "";

      for (const rawLine of lines) {
        const line = rawLine.trimEnd();

        if (line === "") {
          // Blank line = end of an SSE event block; reset event name
          currentEvent = "";
          continue;
        }

        if (line.startsWith("event:")) {
          currentEvent = line.slice("event:".length).trim();
          continue;
        }

        if (line.startsWith("data:")) {
          const jsonText = line.slice("data:".length).trim();
          let payload: Record<string, unknown>;

          try {
            payload = JSON.parse(jsonText) as Record<string, unknown>;
          } catch {
            continue; // malformed data line — skip
          }

          switch (currentEvent) {
            case "token": {
              const tok = (payload["token"] as string) ?? "";
              if (tok) {
                pendingTokens += tok;
                scheduleFlush();
              }
              break;
            }
            case "done": {
              // Flush any buffered tokens immediately before finalising
              if (rafHandle !== null) {
                cancelAnimationFrame(rafHandle);
                rafHandle = null;
              }
              flushTokens();

              callbacks.onDone({
                full_response: (payload["full_response"] as string) ?? "",
                session_id: (payload["session_id"] as string) ?? sessionId,
                halted: Boolean(payload["halted"]),
                action: (payload["action"] as {
                  skill: string;
                  action: string;
                  result: unknown;
                } | null) ?? null,
              });
              return; // stream finished cleanly
            }
            case "error": {
              // Flush any partial tokens before showing the error
              if (rafHandle !== null) {
                cancelAnimationFrame(rafHandle);
                rafHandle = null;
              }
              flushTokens();

              const errMsg =
                (payload["message"] as string) ??
                "An error occurred during streaming";
              callbacks.onError(errMsg);
              return;
            }
            default:
              break; // "action" events (skill dispatch info) are informational only
          }
        }
      }
    }
  } catch (err: unknown) {
    if ((err as { name?: string })?.name === "AbortError") return; // intentional cancel
    if (rafHandle !== null) {
      cancelAnimationFrame(rafHandle);
    }
    callbacks.onError(
      err instanceof Error ? err.message : "Stream read error"
    );
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // ignore
    }
  }
}
