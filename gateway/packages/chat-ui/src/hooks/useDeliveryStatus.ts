/**
 * useDeliveryStatus — Message delivery status state management.
 *
 * Manages the delivery status lifecycle for a single message.
 * Provides both setStatus (direct) and transition (validated) APIs.
 *
 * Valid transition graph:
 *   sending -> sent -> delivered -> read
 *   any state -> failed (always allowed)
 *
 * Invalid forward transitions are silently ignored (e.g., read -> sending).
 * This prevents race conditions from out-of-order status updates.
 *
 * Usage:
 *   const { status, setStatus, transition } = useDeliveryStatus('sending');
 *   // After server ACK: transition('sent')
 *   // After remote receipt: transition('delivered')
 */

import { useState, useCallback } from "react";
import type { DeliveryStatus } from "../types";

interface UseDeliveryStatusReturn {
  status: DeliveryStatus;
  setStatus: (status: DeliveryStatus) => void;
  transition: (next: DeliveryStatus) => void;
}

/** Ordered state rank — higher index = further in lifecycle */
const STATUS_RANK: Record<DeliveryStatus, number> = {
  sending: 0,
  sent: 1,
  delivered: 2,
  read: 3,
  failed: 99, // always reachable
};

export function useDeliveryStatus(
  initialStatus: DeliveryStatus = "sending"
): UseDeliveryStatusReturn {
  const [status, setStatusState] = useState<DeliveryStatus>(initialStatus);

  /** Direct setter — bypasses transition validation. Use for external updates. */
  const setStatus = useCallback((next: DeliveryStatus) => {
    setStatusState(next);
  }, []);

  /**
   * Validated transition — only advances if next rank >= current rank,
   * or next is 'failed' (always allowed).
   */
  const transition = useCallback((next: DeliveryStatus) => {
    setStatusState((current) => {
      if (next === "failed") return next;
      if (STATUS_RANK[next] >= STATUS_RANK[current]) return next;
      // Ignore backwards transitions (e.g., read -> sending)
      return current;
    });
  }, []);

  return { status, setStatus, transition };
}
