/**
 * Nango integration API service.
 *
 * Handles: connection sessions, status checks, disconnections.
 */

import { get, del } from "@/services/api/client";

export interface ConnectionStatus {
  integration_id: string;
  connected: boolean;
  provider: string | null;
  metadata: Record<string, unknown> | null;
}

export interface NangoConfig {
  public_key: string;
}

/** Get Nango public key for frontend */
export async function getNangoConfig(): Promise<NangoConfig> {
  return get<NangoConfig>("/api/v1/integrations/nango/config");
}

/** Check if a specific integration is connected */
export async function getConnectionStatus(
  integrationId: string
): Promise<ConnectionStatus> {
  return get<ConnectionStatus>(
    `/api/v1/integrations/nango/status/${integrationId}`
  );
}

/** Disconnect an integration */
export async function disconnectIntegration(
  integrationId: string
): Promise<{ status: string }> {
  return del<{ status: string }>(
    `/api/v1/integrations/nango/disconnect/${integrationId}`
  );
}
