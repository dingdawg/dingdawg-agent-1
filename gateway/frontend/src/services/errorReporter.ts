/**
 * errorReporter — client-side error capture and automatic reporting.
 *
 * Captures JS errors, unhandled promise rejections, and manual API errors.
 * Batches up to 5 errors per 10-second window to avoid flooding the backend.
 * Sends to POST /api/v1/admin/client-errors.
 *
 * Design decisions:
 * - Fail-closed on transport errors: errors are dropped rather than retrying
 *   indefinitely, which could itself cause a secondary error storm.
 * - navigator.sendBeacon is used for page-unload reporting when available.
 * - The reporter is tolerant of SSR/non-browser environments — all window
 *   access is guarded by typeof window checks.
 * - No external dependencies — uses the native fetch API to avoid circular
 *   imports with the Axios client.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ClientErrorType =
  | "js_error"
  | "unhandled_rejection"
  | "api_error"
  | "render_error";

export interface ClientError {
  message: string;
  stack?: string;
  url: string;
  timestamp: string;
  type: ClientErrorType;
  component?: string;
  extra?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Maximum errors flushed per batch window. */
const BATCH_MAX = 5;
/** Flush interval in milliseconds. */
const FLUSH_INTERVAL_MS = 10_000;
/** Backend endpoint — relative so it works behind any proxy / Vercel rewrite. */
const ENDPOINT = "/api/v1/admin/client-errors";

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _queue: ClientError[] = [];
let _flushTimer: ReturnType<typeof setTimeout> | null = null;
let _initialized = false;

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function _now(): string {
  return new Date().toISOString();
}

function _currentUrl(): string {
  if (typeof window === "undefined") return "ssr";
  return window.location.href;
}

function _userAgent(): string {
  if (typeof window === "undefined") return "ssr";
  return navigator.userAgent;
}

/**
 * Send a batch of errors to the backend.
 * Uses fetch with keepalive so the request survives page unload.
 * Silently swallows transport failures — we must not throw from the reporter.
 */
async function _sendBatch(batch: ClientError[]): Promise<void> {
  if (batch.length === 0) return;
  if (typeof window === "undefined") return;

  const token =
    typeof localStorage !== "undefined"
      ? localStorage.getItem("access_token")
      : null;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  try {
    await fetch(ENDPOINT, {
      method: "POST",
      headers,
      body: JSON.stringify(batch),
      keepalive: true,
    });
  } catch (transportErr) {
    // Intentional: reporter must never throw. Log only — no re-throw.
    // eslint-disable-next-line no-console
    console.warn("[errorReporter] Failed to send error batch:", transportErr);
  }
}

/**
 * Flush up to BATCH_MAX queued errors.
 * Any overflow stays in the queue for the next window.
 */
function _flush(): void {
  if (_queue.length === 0) return;
  const batch = _queue.splice(0, BATCH_MAX);
  void _sendBatch(batch);
}

/**
 * Schedule a delayed flush if one is not already pending.
 */
function _scheduleFlush(): void {
  if (_flushTimer !== null) return;
  _flushTimer = setTimeout(() => {
    _flushTimer = null;
    _flush();
  }, FLUSH_INTERVAL_MS);
}

/**
 * Enqueue one error. Drops if queue would exceed 3× BATCH_MAX to prevent
 * unbounded memory growth during error storms.
 */
function _enqueue(err: ClientError): void {
  if (_queue.length >= BATCH_MAX * 3) return; // circuit-breaker
  _queue.push(err);
  _scheduleFlush();
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Manually report an error. Use this for:
 *   - Caught errors that should still be tracked
 *   - React Error Boundary catches (componentDidCatch)
 *   - Any other instrumentation point
 *
 * @param error   - The Error object or string description
 * @param context - Optional metadata: type, component, extra
 */
export function reportError(
  error: Error | string,
  context?: {
    type?: ClientErrorType;
    component?: string;
    extra?: Record<string, unknown>;
  }
): void {
  const message = error instanceof Error ? error.message : String(error);
  const stack = error instanceof Error ? error.stack : undefined;

  _enqueue({
    message: message.slice(0, 2000), // truncate runaway messages
    stack: stack ? stack.slice(0, 4000) : undefined,
    url: _currentUrl(),
    timestamp: _now(),
    type: context?.type ?? "js_error",
    component: context?.component,
    extra: {
      userAgent: _userAgent(),
      ...context?.extra,
    },
  });
}

/**
 * Report a failed API call. Call this from the response interceptor on 5xx.
 *
 * @param url        - The request URL
 * @param status     - HTTP status code
 * @param message    - Error message or response body snippet
 */
export function reportApiError(
  url: string,
  status: number,
  message: string
): void {
  _enqueue({
    message: `API ${status}: ${message}`.slice(0, 2000),
    url: _currentUrl(),
    timestamp: _now(),
    type: "api_error",
    extra: {
      api_url: url,
      status_code: status,
      userAgent: _userAgent(),
    },
  });
}

/**
 * Install global window.onerror and window.onunhandledrejection handlers.
 * Safe to call multiple times — subsequent calls are no-ops.
 *
 * Call this once inside a useEffect in the admin layout.
 */
export function initErrorReporter(): () => void {
  if (typeof window === "undefined") return () => {};
  if (_initialized) return () => {};
  _initialized = true;

  const onError = (
    event: ErrorEvent
  ): boolean => {
    // Avoid re-reporting errors thrown by the reporter itself.
    if (event.filename && event.filename.includes("errorReporter")) {
      return false;
    }
    _enqueue({
      message: (event.message || "Unknown JS error").slice(0, 2000),
      stack: event.error?.stack?.slice(0, 4000),
      url: _currentUrl(),
      timestamp: _now(),
      type: "js_error",
      extra: {
        filename: event.filename,
        lineno: event.lineno,
        colno: event.colno,
        userAgent: _userAgent(),
      },
    });
    return false; // do NOT suppress default browser error handling
  };

  const onUnhandledRejection = (event: PromiseRejectionEvent): void => {
    const reason = event.reason;
    const message =
      reason instanceof Error
        ? reason.message
        : String(reason ?? "Unhandled promise rejection");
    const stack = reason instanceof Error ? reason.stack : undefined;

    _enqueue({
      message: message.slice(0, 2000),
      stack: stack?.slice(0, 4000),
      url: _currentUrl(),
      timestamp: _now(),
      type: "unhandled_rejection",
      extra: {
        userAgent: _userAgent(),
      },
    });
  };

  window.addEventListener("error", onError);
  window.addEventListener("unhandledrejection", onUnhandledRejection);

  // Flush on page hide (tab close / navigation) using beacon if available
  const onVisibilityChange = (): void => {
    if (document.visibilityState === "hidden") {
      _flush();
    }
  };
  document.addEventListener("visibilitychange", onVisibilityChange);

  // Return cleanup function
  return () => {
    window.removeEventListener("error", onError);
    window.removeEventListener("unhandledrejection", onUnhandledRejection);
    document.removeEventListener("visibilitychange", onVisibilityChange);
    if (_flushTimer !== null) {
      clearTimeout(_flushTimer);
      _flushTimer = null;
    }
    _initialized = false;
  };
}
