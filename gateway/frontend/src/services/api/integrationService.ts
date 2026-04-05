/**
 * Integration service — wires to the real integration backend endpoints.
 *
 * Backend endpoints (wired up separately):
 *   GET  /api/v1/integrations/{agent_id}/status
 *   POST /api/v1/integrations/{agent_id}/google-calendar/connect
 *   POST /api/v1/integrations/{agent_id}/sendgrid/configure
 *   POST /api/v1/integrations/{agent_id}/twilio/configure
 *   POST /api/v1/integrations/{agent_id}/vapi/configure
 *   POST /api/v1/integrations/{agent_id}/disconnect
 *   POST /api/v1/integrations/{agent_id}/test
 *   GET  /api/v1/integrations/{agent_id}/webhooks
 *   POST /api/v1/integrations/{agent_id}/webhooks
 *   DELETE /api/v1/integrations/{agent_id}/webhooks/{webhook_id}
 *
 * Follows the same typing and export pattern as analyticsService.ts.
 * Handles gracefully if backend routes don't exist yet (404 → null status).
 */

import { get, post, del } from "./client";

// ─── Response Types ───────────────────────────────────────────────────────────

export interface GoogleCalendarStatus {
  connected: boolean;
  email?: string;
  calendar_id?: string;
}

export interface SendGridStatus {
  connected: boolean;
  from_email?: string;
  from_name?: string;
}

export interface TwilioStatus {
  connected: boolean;
  from_number?: string;
  account_sid_hint?: string; // last 4 chars only
}

export interface VapiStatus {
  connected: boolean;
  voice_model?: string;
  first_message?: string;
}

export interface WebhookEntry {
  id: string;
  url: string;
  events: string[];
  auth_type: "none" | "bearer" | "basic";
  active: boolean;
  created_at: string;
}

export interface WebhooksStatus {
  active_count: number;
  webhooks: WebhookEntry[];
}

export interface DdMainBridgeStatus {
  connected: boolean;
  bridge_url?: string;
  last_ping?: string;
}

export interface IntegrationStatus {
  google_calendar: GoogleCalendarStatus;
  sendgrid: SendGridStatus;
  twilio: TwilioStatus;
  vapi: VapiStatus;
  webhooks: WebhooksStatus;
  dd_main_bridge: DdMainBridgeStatus;
}

// ─── Default / fallback status ────────────────────────────────────────────────

const DEFAULT_STATUS: IntegrationStatus = {
  google_calendar: { connected: false },
  sendgrid: { connected: false },
  twilio: { connected: false },
  vapi: { connected: false },
  webhooks: { active_count: 0, webhooks: [] },
  dd_main_bridge: { connected: false },
};

// ─── Configure Payloads ───────────────────────────────────────────────────────

export interface SendGridConfig {
  api_key: string;
  from_email: string;
  from_name: string;
}

export interface TwilioConfig {
  account_sid: string;
  auth_token: string;
  from_number: string;
}

export interface VapiConfig {
  api_key: string;
  voice_model: "elevenlabs" | "browser" | "custom";
  first_message: string;
}

export interface WebhookConfig {
  url: string;
  events: string[];
  auth_type: "none" | "bearer" | "basic";
  auth_value?: string; // bearer token or basic password
}

export type IntegrationKey =
  | "google_calendar"
  | "sendgrid"
  | "twilio"
  | "vapi"
  | "dd_main_bridge";

// ─── API helpers ──────────────────────────────────────────────────────────────

function isAxiosNotFound(err: unknown): boolean {
  return (
    (err as { response?: { status?: number } })?.response?.status === 404 ||
    (err as { response?: { status?: number } })?.response?.status === 501
  );
}

function extractErrorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: string } } })
    ?.response?.data?.detail;
  if (detail) return detail;
  if (err instanceof Error) return err.message;
  return fallback;
}

// ─── API Functions ────────────────────────────────────────────────────────────

/**
 * Fetch integration status for an agent.
 * Returns a merged default status if the backend endpoint doesn't exist yet.
 */
export async function getIntegrationStatus(
  agentId: string
): Promise<IntegrationStatus> {
  try {
    const data = await get<Partial<IntegrationStatus>>(
      `/api/v1/integrations/${agentId}/status`
    );
    // Merge with defaults so missing keys don't cause undefined errors
    return {
      google_calendar: {
        ...DEFAULT_STATUS.google_calendar,
        ...(data.google_calendar ?? {}),
      },
      sendgrid: {
        ...DEFAULT_STATUS.sendgrid,
        ...(data.sendgrid ?? {}),
      },
      twilio: {
        ...DEFAULT_STATUS.twilio,
        ...(data.twilio ?? {}),
      },
      vapi: {
        ...DEFAULT_STATUS.vapi,
        ...(data.vapi ?? {}),
      },
      webhooks: {
        ...DEFAULT_STATUS.webhooks,
        ...(data.webhooks ?? {}),
      },
      dd_main_bridge: {
        ...DEFAULT_STATUS.dd_main_bridge,
        ...(data.dd_main_bridge ?? {}),
      },
    };
  } catch (err) {
    if (isAxiosNotFound(err)) {
      // Backend route not wired yet — return disconnected defaults
      return DEFAULT_STATUS;
    }
    throw new Error(extractErrorMessage(err, "Failed to load integration status"));
  }
}

/**
 * Initiate Google Calendar OAuth connection.
 * Returns an oauth_url if the backend redirects; otherwise show a success message.
 */
export async function connectGoogleCalendar(
  agentId: string
): Promise<{ oauth_url?: string; message?: string }> {
  try {
    return await post<{ oauth_url?: string; message?: string }>(
      `/api/v1/integrations/${agentId}/google-calendar/connect`
    );
  } catch (err) {
    if (isAxiosNotFound(err)) {
      throw new Error("Google Calendar integration is not yet available.");
    }
    throw new Error(extractErrorMessage(err, "Failed to initiate Google Calendar connection"));
  }
}

/**
 * Configure SendGrid email integration.
 */
export async function configureSendGrid(
  agentId: string,
  config: SendGridConfig
): Promise<{ success: boolean; message?: string }> {
  try {
    return await post<{ success: boolean; message?: string }>(
      `/api/v1/integrations/${agentId}/sendgrid/configure`,
      config
    );
  } catch (err) {
    if (isAxiosNotFound(err)) {
      throw new Error("SendGrid integration is not yet available.");
    }
    throw new Error(extractErrorMessage(err, "Failed to configure SendGrid"));
  }
}

/**
 * Configure Twilio SMS integration.
 */
export async function configureTwilio(
  agentId: string,
  config: TwilioConfig
): Promise<{ success: boolean; message?: string }> {
  try {
    return await post<{ success: boolean; message?: string }>(
      `/api/v1/integrations/${agentId}/twilio/configure`,
      config
    );
  } catch (err) {
    if (isAxiosNotFound(err)) {
      throw new Error("Twilio integration is not yet available.");
    }
    throw new Error(extractErrorMessage(err, "Failed to configure Twilio"));
  }
}

/**
 * Configure Vapi voice integration.
 */
export async function configureVapi(
  agentId: string,
  config: VapiConfig
): Promise<{ success: boolean; message?: string }> {
  try {
    return await post<{ success: boolean; message?: string }>(
      `/api/v1/integrations/${agentId}/vapi/configure`,
      config
    );
  } catch (err) {
    if (isAxiosNotFound(err)) {
      throw new Error("Vapi integration is not yet available.");
    }
    throw new Error(extractErrorMessage(err, "Failed to configure Vapi"));
  }
}

/**
 * Disconnect an integration.
 */
export async function disconnectIntegration(
  agentId: string,
  integration: IntegrationKey
): Promise<{ success: boolean }> {
  try {
    return await post<{ success: boolean }>(
      `/api/v1/integrations/${agentId}/disconnect`,
      { integration }
    );
  } catch (err) {
    if (isAxiosNotFound(err)) {
      throw new Error("Disconnect endpoint is not yet available.");
    }
    throw new Error(extractErrorMessage(err, "Failed to disconnect integration"));
  }
}

/**
 * Send a test message for sendgrid or twilio.
 */
export async function testIntegration(
  agentId: string,
  integration: "sendgrid" | "twilio"
): Promise<{ success: boolean; message?: string }> {
  try {
    return await post<{ success: boolean; message?: string }>(
      `/api/v1/integrations/${agentId}/test`,
      { integration }
    );
  } catch (err) {
    if (isAxiosNotFound(err)) {
      throw new Error("Test endpoint is not yet available.");
    }
    throw new Error(extractErrorMessage(err, "Failed to run integration test"));
  }
}

/**
 * List webhooks for an agent.
 */
export async function listWebhooks(agentId: string): Promise<WebhookEntry[]> {
  try {
    const data = await get<WebhookEntry[] | { webhooks: WebhookEntry[] }>(
      `/api/v1/integrations/${agentId}/webhooks`
    );
    if (Array.isArray(data)) return data;
    return data.webhooks ?? [];
  } catch (err) {
    if (isAxiosNotFound(err)) return [];
    throw new Error(extractErrorMessage(err, "Failed to load webhooks"));
  }
}

/**
 * Create a new webhook.
 */
export async function createWebhook(
  agentId: string,
  config: WebhookConfig
): Promise<WebhookEntry> {
  try {
    return await post<WebhookEntry>(
      `/api/v1/integrations/${agentId}/webhooks`,
      config
    );
  } catch (err) {
    if (isAxiosNotFound(err)) {
      throw new Error("Webhook creation is not yet available.");
    }
    throw new Error(extractErrorMessage(err, "Failed to create webhook"));
  }
}

/**
 * Delete a webhook by ID.
 */
export async function deleteWebhook(
  agentId: string,
  webhookId: string
): Promise<void> {
  try {
    await del<void>(`/api/v1/integrations/${agentId}/webhooks/${webhookId}`);
  } catch (err) {
    if (isAxiosNotFound(err)) {
      throw new Error("Webhook deletion is not yet available.");
    }
    throw new Error(extractErrorMessage(err, "Failed to delete webhook"));
  }
}
