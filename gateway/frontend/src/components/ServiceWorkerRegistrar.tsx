"use client";

/**
 * ServiceWorkerRegistrar
 *
 * Registers /sw.js on first mount. Client component so it runs only in the
 * browser. Fires a SKIP_WAITING message to activate updates immediately.
 *
 * Listens for SW_SYNC_TRIGGER messages from the service worker to replay
 * queued API mutations when back online.
 */

import { useEffect } from "react";

export default function ServiceWorkerRegistrar() {
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!("serviceWorker" in navigator)) return;

    let registration: ServiceWorkerRegistration | null = null;

    async function register() {
      try {
        registration = await navigator.serviceWorker.register("/sw.js", {
          scope: "/",
          updateViaCache: "none",
        });

        console.log("[SW Registrar] Registered:", registration.scope);

        // Check for waiting worker and prompt update
        registration.addEventListener("updatefound", () => {
          const newWorker = registration?.installing;
          if (!newWorker) return;

          newWorker.addEventListener("statechange", () => {
            if (
              newWorker.state === "installed" &&
              navigator.serviceWorker.controller
            ) {
              // New SW waiting — activate immediately without user prompt
              newWorker.postMessage({ type: "SKIP_WAITING" });
              console.log("[SW Registrar] New SW activated via SKIP_WAITING");
            }
          });
        });
      } catch (err) {
        // Log but never crash the app — PWA is enhancement, not requirement
        console.error("[SW Registrar] Registration failed:", err);
      }
    }

    // Listen for messages from the service worker
    function handleMessage(event: MessageEvent) {
      if (!event.data) return;

      if (event.data.type === "SW_SYNC_TRIGGER") {
        console.log("[SW Registrar] Sync trigger received, replaying queue");
        // Dispatch custom event for any component that wants to retry
        window.dispatchEvent(new CustomEvent("dingdawg:sync-retry"));
      }
    }

    register();
    navigator.serviceWorker.addEventListener("message", handleMessage);

    return () => {
      navigator.serviceWorker.removeEventListener("message", handleMessage);
    };
  }, []);

  // Renders nothing — purely a side-effect component
  return null;
}
