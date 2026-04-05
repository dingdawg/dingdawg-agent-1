/**
 * Config file management for @dingdawg/cli
 *
 * Reads and writes ~/.dingdawg/config.json
 * Zero dependencies — uses only Node.js built-ins.
 */

import { readFileSync, writeFileSync, renameSync, mkdirSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { homedir } from 'os';

/** Default backend URL for the DingDawg Agent 1 API. */
export const DEFAULT_BASE_URL = 'https://api.dingdawg.com';

/** Path to the config directory. */
export const CONFIG_DIR = join(homedir(), '.dingdawg');

/** Path to the config file. */
export const CONFIG_FILE = join(CONFIG_DIR, 'config.json');

/**
 * @typedef {Object} DingDawgConfig
 * @property {string} [api_key]       - API key (sk_live_xxx)
 * @property {string} [access_token]  - JWT from device flow
 * @property {string} [base_url]      - Backend base URL
 * @property {string} [default_agent] - Default @handle
 * @property {string} [theme]         - 'dark' | 'light'
 * @property {string} [user_id]       - Authenticated user ID
 * @property {string} [email]         - Authenticated user email
 */

/**
 * Load configuration from disk.
 * Returns empty object if config file does not exist.
 *
 * @returns {DingDawgConfig}
 */
export function loadConfig() {
  if (!existsSync(CONFIG_FILE)) {
    return {};
  }
  try {
    const raw = readFileSync(CONFIG_FILE, 'utf8');
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

/**
 * Save configuration to disk using an atomic write (write to tmp then rename).
 * Prevents config corruption if the process is killed mid-write.
 * Creates ~/.dingdawg/ directory if it does not exist.
 *
 * @param {DingDawgConfig} config
 */
export function saveConfig(config) {
  if (!existsSync(CONFIG_DIR)) {
    mkdirSync(CONFIG_DIR, { recursive: true });
  }
  const tmp = CONFIG_FILE + '.tmp';
  writeFileSync(tmp, JSON.stringify(config, null, 2) + '\n', {
    encoding: 'utf8',
    mode: 0o600,
  });
  renameSync(tmp, CONFIG_FILE);
}

/**
 * Get a single config value by key.
 *
 * @param {string} key
 * @returns {string | undefined}
 */
export function getConfigValue(key) {
  const cfg = loadConfig();
  return cfg[key];
}

/**
 * Set a single config value by key.
 *
 * @param {string} key
 * @param {string} value
 */
export function setConfigValue(key, value) {
  const cfg = loadConfig();
  cfg[key] = value;
  saveConfig(cfg);
}

/**
 * Delete a single config key.
 *
 * @param {string} key
 */
export function deleteConfigValue(key) {
  const cfg = loadConfig();
  delete cfg[key];
  saveConfig(cfg);
}

/**
 * Get the active base URL (from config or default).
 *
 * @returns {string}
 */
export function getBaseUrl() {
  const cfg = loadConfig();
  return cfg.base_url || DEFAULT_BASE_URL;
}

/**
 * Get the active auth header value.
 * Returns the Bearer JWT if present, else null.
 *
 * @returns {string | null}
 */
export function getAuthHeader() {
  const cfg = loadConfig();
  if (cfg.access_token) {
    return `Bearer ${cfg.access_token}`;
  }
  if (cfg.api_key) {
    return `Bearer ${cfg.api_key}`;
  }
  return null;
}

/**
 * Get the API key header value (X-DD-API-Key).
 * Returns the API key if set, else null.
 *
 * @returns {string | null}
 */
export function getApiKeyHeader() {
  const cfg = loadConfig();
  return cfg.api_key || null;
}

/**
 * Build auth headers for HTTP requests.
 *
 * Precedence: X-DD-API-Key (api_key) takes priority over Authorization Bearer
 * (access_token). Both are mutually exclusive per the DingDawg auth spec.
 *
 * This is the SINGLE source of truth for auth header construction — both
 * api.js and stream.js must call this function instead of reading config
 * values directly.
 *
 * @param {Object} [extra={}] - Additional headers to merge (merged last,
 *                              so callers can override Content-Type etc.)
 * @returns {Object} Headers object ready to pass to fetch()
 */
export function buildAuthHeaders(extra = {}) {
  const apiKey = getApiKeyHeader();
  const auth = getAuthHeader();

  const authHeaders = {};
  if (apiKey) {
    authHeaders['X-DD-API-Key'] = apiKey;
  } else if (auth) {
    authHeaders['Authorization'] = auth;
  }

  return { ...authHeaders, ...extra };
}

/**
 * Returns true if there is any stored credential.
 *
 * @returns {boolean}
 */
export function isAuthenticated() {
  const cfg = loadConfig();
  return Boolean(cfg.access_token || cfg.api_key);
}
