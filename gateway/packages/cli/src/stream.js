/**
 * SSE stream consumer for @dingdawg/cli
 *
 * Connects to POST /api/v1/cli/invoke and streams the response
 * token-by-token to the terminal.
 *
 * Zero dependencies — uses Node.js 18+ built-in fetch + ReadableStream.
 *
 * Signal handling:
 *   SIGINT (Ctrl+C) aborts the in-flight fetch and exits with code 130
 *   (Unix convention for SIGINT termination).
 *
 * Timeout:
 *   A 30-second connect timeout is applied. If no response headers arrive
 *   within 30s the request is aborted and the process exits with code 1.
 */

import { getBaseUrl, buildAuthHeaders } from './config.js';
import { renderMarkdown, print, println, createSpinner, printError, gray, dim } from './format.js';

/** Connect timeout in milliseconds. */
const CONNECT_TIMEOUT_MS = 30_000;

/**
 * Stream an agent response from the CLI invoke endpoint.
 *
 * Displays a spinner while waiting for the first token.
 * Tokens stream in real-time as they arrive.
 * Metadata event is silently consumed (not printed).
 * [DONE] terminates the stream.
 *
 * @param {Object} options
 * @param {string} options.handle       - Agent handle (@mybusiness or mybusiness)
 * @param {string} options.message      - User message
 * @param {string} [options.skill]      - Optional skill name
 * @param {string} [options.action]     - Optional action within skill
 * @param {Object} [options.parameters] - Optional skill parameters
 * @returns {Promise<void>}
 */
export async function streamInvoke({ handle, message, skill, action, parameters }) {
  const url = `${getBaseUrl()}/api/v1/cli/invoke`;

  // Build auth headers from the single source of truth in config.js
  const headers = buildAuthHeaders({
    'Content-Type': 'application/json',
    'User-Agent': '@dingdawg/cli/0.1.0',
    Accept: 'text/event-stream',
  });

  const body = {
    handle,
    message,
    source: 'cli',
  };
  if (skill) body.skill = skill;
  if (action) body.action = action;
  if (parameters) body.parameters = parameters;

  // -------------------------------------------------------------------------
  // AbortController — wired to SIGINT and a connect timeout
  // -------------------------------------------------------------------------
  const controller = new AbortController();
  const { signal } = controller;

  /** Clean up timeout and SIGINT listener regardless of outcome. */
  let connectTimer = null;

  const onSigint = () => {
    controller.abort();
    // Exit code 130 = 128 + SIGINT(2), the Unix convention for SIGINT exit
    process.exit(130);
  };

  process.on('SIGINT', onSigint);

  connectTimer = setTimeout(() => {
    controller.abort();
  }, CONNECT_TIMEOUT_MS);

  const spinner = createSpinner('Thinking...');
  let firstToken = false;

  let resp;
  try {
    resp = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    clearTimeout(connectTimer);
    process.removeListener('SIGINT', onSigint);
    spinner.stop();

    if (err.name === 'AbortError') {
      printError('Connection timed out after 30 seconds.');
      process.exit(1);
    }
    printError(`Connection failed: ${err.message}`);
    process.exit(1);
  }

  // Response headers received — clear the connect timeout
  clearTimeout(connectTimer);

  if (!resp.ok) {
    process.removeListener('SIGINT', onSigint);
    spinner.stop();
    let detail = '';
    try {
      const data = await resp.json();
      detail = data.detail || data.error || JSON.stringify(data);
    } catch {
      detail = await resp.text();
    }
    if (resp.status === 401) {
      printError('Not authenticated. Run: dd login');
    } else if (resp.status === 404) {
      printError(`Agent not found: ${handle}`);
    } else {
      printError(`Request failed (${resp.status}): ${detail.slice(0, 300)}`);
    }
    process.exit(1);
  }

  // Stream SSE events line by line
  const reader = resp.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let fullResponse = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Process complete SSE lines (double-newline terminated)
      const events = buffer.split('\n\n');
      // Keep the last incomplete chunk in buffer
      buffer = events.pop() || '';

      for (const event of events) {
        const lines = event.trim().split('\n');

        // Check for named event (event: metadata, event: error, event: done)
        const eventType = lines
          .find((l) => l.startsWith('event:'))
          ?.replace('event:', '')
          .trim();

        const dataLine = lines.find((l) => l.startsWith('data:'));
        if (!dataLine) continue;

        const data = dataLine.replace('data:', '').trimStart();

        // Termination marker
        if (data === '[DONE]') {
          if (!firstToken) {
            spinner.stop('');
          }
          // Final newline
          println('');
          return;
        }

        // Error event
        if (eventType === 'error') {
          spinner.stop();
          try {
            const err = JSON.parse(data);
            printError(err.error || data);
          } catch {
            printError(data);
          }
          process.exit(1);
        }

        // Metadata event — consume silently
        if (eventType === 'metadata') {
          continue;
        }

        // Token chunk — first token: stop spinner and start printing
        if (!firstToken) {
          firstToken = true;
          spinner.stop('');
          println('');
        }

        // Render markdown inline and stream to terminal
        const rendered = renderMarkdown(data);
        print(rendered);
        fullResponse += data;
      }
    }

    // Flush any remaining buffer
    if (buffer.trim()) {
      const lines = buffer.trim().split('\n');
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          if (data !== '[DONE]') {
            if (!firstToken) {
              firstToken = true;
              spinner.stop('');
              println('');
            }
            print(renderMarkdown(data));
          }
        }
      }
    }

    if (!firstToken) {
      spinner.stop('');
    }
    println('');
  } finally {
    // Always clean up: remove SIGINT listener and cancel the stream reader
    process.removeListener('SIGINT', onSigint);
    try {
      reader.cancel();
    } catch {
      // Ignore cancel errors
    }
  }
}
