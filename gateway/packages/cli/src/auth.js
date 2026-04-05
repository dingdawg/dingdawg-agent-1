/**
 * Authentication commands for @dingdawg/cli
 *
 * Handles: dd login, dd login --api-key, dd logout, dd whoami
 * Zero dependencies — uses Node.js 18+ built-in fetch.
 */

import { loadConfig, saveConfig, deleteConfigValue, CONFIG_FILE, getBaseUrl } from './config.js';
import { post, get, parseJson, assertOk } from './api.js';
import {
  println,
  printError,
  printSuccess,
  printWhoami,
  printDevicePrompt,
  createSpinner,
  bold,
  cyan,
  dim,
  gray,
} from './format.js';

/** Device flow polling interval in ms. */
const POLL_INTERVAL_MS = 5000;

/** Maximum poll attempts (300s / 5s = 60 attempts = 5 minutes). */
const MAX_POLL_ATTEMPTS = 60;

/**
 * Pause for the given number of milliseconds.
 *
 * @param {number} ms
 * @returns {Promise<void>}
 */
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// dd login
// ---------------------------------------------------------------------------

/**
 * Run the login flow.
 *
 * With --api-key <key>: saves key directly.
 * Without: starts OAuth device flow.
 *
 * @param {string[]} args - Remaining CLI args after 'login'
 * @returns {Promise<void>}
 */
export async function cmdLogin(args) {
  // --api-key flag: direct API key auth
  const apiKeyIndex = args.indexOf('--api-key');
  if (apiKeyIndex !== -1) {
    const apiKey = args[apiKeyIndex + 1];
    if (!apiKey || apiKey.startsWith('--')) {
      printError('--api-key requires a key value. Example: dd login --api-key sk_live_xxx');
      process.exit(1);
    }
    await _loginWithApiKey(apiKey);
    return;
  }

  // OAuth device flow
  await _loginDeviceFlow();
}

/**
 * Save an API key to config.
 *
 * @param {string} apiKey
 */
async function _loginWithApiKey(apiKey) {
  const cfg = loadConfig();
  cfg.api_key = apiKey;
  if (!cfg.base_url) {
    cfg.base_url = getBaseUrl();
  }
  saveConfig(cfg);

  // Verify the key works
  const spinner = createSpinner('Verifying API key...');
  try {
    const resp = await get('/auth/me');
    spinner.stop();
    if (resp.ok) {
      const data = await parseJson(resp);
      cfg.user_id = data.user_id;
      cfg.email = data.email;
      saveConfig(cfg);
      printSuccess(`Logged in as ${bold(data.email || data.user_id)}`);
      println(dim(`  Config saved to ${CONFIG_FILE}`));
    } else {
      printError('API key verification failed. Check the key and try again.');
      process.exit(1);
    }
  } catch (err) {
    spinner.stop();
    printError(`Login failed: ${err.message}`);
    process.exit(1);
  }
}

/**
 * OAuth device flow: generate code → display to user → poll for token.
 */
async function _loginDeviceFlow() {
  const spinner = createSpinner('Starting device flow...');

  let deviceData;
  try {
    const resp = await post('/api/v1/cli/device-code', {});
    spinner.stop();
    await assertOk(resp, 'Device code generation failed');
    deviceData = await parseJson(resp);
  } catch (err) {
    spinner.stop();
    printError(err.message);
    process.exit(1);
  }

  const { device_code, user_code, verification_url, interval = 5 } = deviceData;
  printDevicePrompt(user_code, verification_url);

  // Poll until authorized or expired
  const pollMs = (interval || 5) * 1000;
  let attempts = 0;

  while (attempts < MAX_POLL_ATTEMPTS) {
    await sleep(pollMs);
    attempts++;

    let resp;
    try {
      resp = await post('/api/v1/cli/device-token', { device_code });
    } catch (err) {
      printError(`Polling error: ${err.message}`);
      process.exit(1);
    }

    if (resp.status === 202) {
      // Still pending — keep polling silently
      process.stdout.write('.');
      continue;
    }

    if (resp.status === 200) {
      println('');
      const data = await parseJson(resp);
      const cfg = loadConfig();
      cfg.access_token = data.access_token;
      cfg.user_id = data.user_id;
      cfg.email = data.email;
      if (!cfg.base_url) {
        cfg.base_url = getBaseUrl();
      }
      saveConfig(cfg);
      printSuccess(`Logged in as ${bold(data.email || data.user_id)}`);
      println(dim(`  Config saved to ${CONFIG_FILE}`));
      return;
    }

    // Error (400/401 = expired/invalid)
    println('');
    const data = await parseJson(resp);
    printError(data.detail || 'Device flow failed. Please run dd login again.');
    process.exit(1);
  }

  println('');
  printError('Device flow timed out. Please run dd login again.');
  process.exit(1);
}

// ---------------------------------------------------------------------------
// dd logout
// ---------------------------------------------------------------------------

/**
 * Clear stored credentials.
 *
 * @returns {Promise<void>}
 */
export async function cmdLogout() {
  const cfg = loadConfig();

  // Attempt server-side token revocation (best-effort)
  if (cfg.access_token) {
    try {
      await post('/auth/logout', {}, {
        headers: { Authorization: `Bearer ${cfg.access_token}` },
      });
    } catch {
      // Non-fatal — config will be cleared regardless
    }
  }

  // Wipe credentials from config
  delete cfg.access_token;
  delete cfg.api_key;
  delete cfg.user_id;
  delete cfg.email;
  saveConfig(cfg);

  printSuccess('Logged out. Credentials cleared.');
}

// ---------------------------------------------------------------------------
// dd whoami
// ---------------------------------------------------------------------------

/**
 * Show the current authenticated user.
 *
 * @returns {Promise<void>}
 */
export async function cmdWhoami() {
  const cfg = loadConfig();

  if (!cfg.access_token && !cfg.api_key) {
    printError('Not logged in. Run: dd login');
    process.exit(1);
  }

  const spinner = createSpinner('Fetching profile...');

  try {
    const resp = await get('/auth/me');
    spinner.stop();

    if (!resp.ok) {
      if (resp.status === 401) {
        printError('Session expired. Run: dd login');
        process.exit(1);
      }
      await assertOk(resp, 'Profile fetch failed');
    }

    const data = await parseJson(resp);
    printWhoami({
      email: data.email,
      user_id: data.user_id,
      default_agent: cfg.default_agent,
    });
  } catch (err) {
    spinner.stop();
    printError(err.message);
    process.exit(1);
  }
}
