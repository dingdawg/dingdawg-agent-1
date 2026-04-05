"use client";

/**
 * usePolling — generic polling hook that calls a callback on an interval.
 *
 * - Fires immediately on mount (before first interval tick)
 * - Clears the interval on unmount to prevent memory leaks
 * - Pauses when the document is hidden (Page Visibility API) to conserve resources
 * - Resumes and immediately re-fetches when the document becomes visible again
 * - Supports dynamic enable/disable toggle (e.g. pause while a modal is open)
 * - intervalMs defaults to 60_000 (60 seconds)
 *
 * Usage:
 *   usePolling(fetchData, 30_000);           // poll every 30 s
 *   usePolling(fetchData, 30_000, isActive); // conditionally enabled
 */

import { useEffect, useRef, useCallback } from "react";

export function usePolling(
  callback: () => void | Promise<void>,
  intervalMs: number = 60_000,
  enabled: boolean = true
): void {
  // Stable ref so interval closure never captures stale callback
  const callbackRef = useRef<() => void | Promise<void>>(callback);
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Guard against setState calls after unmount (Safari SPA navigation crash)
  const mountedRef = useRef(true);

  const fire = useCallback(() => {
    if (!mountedRef.current) return;
    void callbackRef.current();
  }, []);

  const startInterval = useCallback(() => {
    if (intervalRef.current !== null) return;
    intervalRef.current = setInterval(() => {
      if (!mountedRef.current) return;
      if (typeof document !== "undefined" && document.hidden) return;
      fire();
    }, intervalMs);
  }, [fire, intervalMs]);

  const stopInterval = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;

    if (!enabled) {
      stopInterval();
      return () => {
        mountedRef.current = false;
      };
    }

    // Fire immediately on mount / re-enable
    fire();

    // Start polling unless tab is already hidden
    if (typeof document === "undefined" || !document.hidden) {
      startInterval();
    }

    function handleVisibilityChange() {
      if (typeof document === "undefined") return;
      if (!mountedRef.current) return;
      if (document.hidden) {
        stopInterval();
      } else {
        // Immediately refresh when user returns to the tab
        fire();
        startInterval();
      }
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      mountedRef.current = false;
      stopInterval();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [enabled, fire, startInterval, stopInterval]);
}
