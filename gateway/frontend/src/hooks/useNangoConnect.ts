/**
 * useNangoConnect — hook for triggering Nango OAuth flows.
 *
 * Usage:
 *   const { connect, isConnecting } = useNangoConnect();
 *   <button onClick={() => connect("google_calendar")}>Sign in with Google</button>
 *
 * Flow:
 *   1. Frontend calls backend POST /api/v1/integrations/nango/connect
 *   2. Backend returns session token
 *   3. Frontend opens Nango's Connect UI (OAuth popup)
 *   4. User authorizes → Nango stores tokens server-side
 *   5. Frontend receives callback → triggers onSuccess
 */

import { useState, useCallback } from "react";
import { ConnectUI } from "@nangohq/frontend";
import { post } from "@/services/api/client";

interface ConnectResult {
  token?: string;
  public_key?: string;
  error?: string;
}

interface UseNangoConnectOptions {
  onSuccess?: (integrationId: string) => void;
  onError?: (integrationId: string, error: string) => void;
  agentId?: string;
}

export function useNangoConnect(options?: UseNangoConnectOptions) {
  const [isConnecting, setIsConnecting] = useState(false);
  const [connectingId, setConnectingId] = useState<string | null>(null);

  const connect = useCallback(
    async (integrationId: string) => {
      setIsConnecting(true);
      setConnectingId(integrationId);

      try {
        // 1. Get session token from backend
        const result = await post<ConnectResult>(
          "/api/v1/integrations/nango/connect",
          {
            integration_id: integrationId,
            agent_id: options?.agentId,
          }
        );

        if (result.error || !result.token) {
          throw new Error(result.error || "Failed to create connection session");
        }

        // 2. Open Nango Connect UI
        const connectUI = new ConnectUI({
          sessionToken: result.token,
          onEvent: (event) => {
            if (event.type === "connect") {
              options?.onSuccess?.(integrationId);
            } else if (event.type === "error") {
              options?.onError?.(integrationId, "Connection failed");
            }
          },
        });

        connectUI.open();
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Connection failed";
        console.error(`[NangoConnect] Failed to connect ${integrationId}:`, message);
        options?.onError?.(integrationId, message);
      } finally {
        setIsConnecting(false);
        setConnectingId(null);
      }
    },
    [options]
  );

  return { connect, isConnecting, connectingId };
}
