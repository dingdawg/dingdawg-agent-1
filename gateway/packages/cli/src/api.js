/**
 * HTTP client wrapper for @dingdawg/cli
 *
 * Wraps fetch() with base URL, auth headers, error handling, and retry logic.
 * Zero dependencies — uses only Node.js 18+ built-in fetch.
 */

import { getBaseUrl, buildAuthHeaders } from './config.js';

// ---------------------------------------------------------------------------
// Retry with exponential backoff
// ---------------------------------------------------------------------------

/**
 * Retry a fetch-producing function with exponential backoff and jitter.
 *
 * Retries on:
 *   - HTTP 429 (Too Many Requests) — respects Retry-After header
 *   - HTTP 5xx (Server errors)
 *
 * Does NOT retry on 4xx (except 429) — those are caller errors.
 *
 * @param {() => Promise<Response>} fn       - Function that returns a fetch Promise
 * @param {Object}                  [opts]
 * @param {number}                  [opts.maxAttempts=3]    - Max total attempts
 * @param {number}                  [opts.initialDelay=500] - Initial backoff delay in ms
 * @param {number}                  [opts.maxDelay=5000]    - Cap on backoff delay in ms
 * @returns {Promise<Response>}
 */
async function retryWithBackoff(fn, { maxAttempts = 3, initialDelay = 500, maxDelay = 5000 } = {}) {
  let attempt = 0;

  while (true) {
    attempt++;
    const resp = await fn();

    // Success or non-retryable client error — return immediately
    const shouldRetry = resp.status === 429 || resp.status >= 500;
    if (!shouldRetry || attempt >= maxAttempts) {
      return resp;
    }

    // Compute delay: exponential backoff with ±30% jitter
    let delay = Math.min(initialDelay * Math.pow(2, attempt - 1), maxDelay);
    delay = delay * (0.7 + Math.random() * 0.6); // ±30% jitter

    // Respect Retry-After header on 429 (value is seconds)
    if (resp.status === 429) {
      const retryAfter = resp.headers.get('Retry-After');
      if (retryAfter) {
        const parsed = parseFloat(retryAfter);
        if (!isNaN(parsed)) {
          delay = Math.min(parsed * 1000, maxDelay);
        }
      }
    }

    await new Promise((resolve) => setTimeout(resolve, delay));
  }
}

// ---------------------------------------------------------------------------
// Header construction
// ---------------------------------------------------------------------------

/**
 * Build the default request headers including auth.
 * Delegates auth logic to buildAuthHeaders() in config.js — single source of truth.
 *
 * @param {Object} [extra] - Additional headers to merge
 * @returns {Object}
 */
function buildHeaders(extra = {}) {
  return buildAuthHeaders({
    'Content-Type': 'application/json',
    'User-Agent': '@dingdawg/cli/0.1.0',
    ...extra,
  });
}

// ---------------------------------------------------------------------------
// HTTP methods
// ---------------------------------------------------------------------------

/**
 * Perform a JSON POST request with retry on 429/5xx.
 *
 * @param {string} path    - API path (e.g. '/api/v1/cli/invoke')
 * @param {Object} body    - Request body (will be JSON.stringify'd)
 * @param {Object} [opts]  - Additional fetch options
 * @returns {Promise<Response>}
 */
export async function post(path, body, opts = {}) {
  const url = `${getBaseUrl()}${path}`;
  const { headers: extraHeaders = {}, ...restOpts } = opts;
  return retryWithBackoff(() =>
    fetch(url, {
      method: 'POST',
      headers: buildHeaders(extraHeaders),
      body: JSON.stringify(body),
      ...restOpts,
    })
  );
}

/**
 * Perform a JSON GET request with retry on 429/5xx.
 *
 * @param {string} path   - API path
 * @param {Object} [opts] - Additional fetch options
 * @returns {Promise<Response>}
 */
export async function get(path, opts = {}) {
  const url = `${getBaseUrl()}${path}`;
  const { headers: extraHeaders = {}, ...restOpts } = opts;
  return retryWithBackoff(() =>
    fetch(url, {
      method: 'GET',
      headers: buildHeaders(extraHeaders),
      ...restOpts,
    })
  );
}

/**
 * Perform a JSON DELETE request with retry on 429/5xx.
 *
 * @param {string} path   - API path
 * @param {Object} [opts] - Additional fetch options
 * @returns {Promise<Response>}
 */
export async function del(path, opts = {}) {
  const url = `${getBaseUrl()}${path}`;
  const { headers: extraHeaders = {}, ...restOpts } = opts;
  return retryWithBackoff(() =>
    fetch(url, {
      method: 'DELETE',
      headers: buildHeaders(extraHeaders),
      ...restOpts,
    })
  );
}

/**
 * Parse a JSON response, throwing a descriptive error on failure.
 *
 * @param {Response} resp
 * @returns {Promise<Object>}
 */
export async function parseJson(resp) {
  const text = await resp.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(
      `Server returned non-JSON response (status ${resp.status}): ${text.slice(0, 200)}`
    );
  }
}

/**
 * Check response status and throw a user-friendly error on failure.
 *
 * @param {Response} resp
 * @param {string}   [context] - Context message for error
 * @returns {Promise<void>}
 */
export async function assertOk(resp, context = '') {
  if (!resp.ok) {
    let detail = '';
    try {
      const data = await resp.clone().json();
      detail = data.detail || data.error || JSON.stringify(data);
    } catch {
      detail = await resp.text();
    }
    const prefix = context ? `${context}: ` : '';
    throw new Error(`${prefix}${resp.status} ${resp.statusText} — ${detail.slice(0, 300)}`);
  }
}
