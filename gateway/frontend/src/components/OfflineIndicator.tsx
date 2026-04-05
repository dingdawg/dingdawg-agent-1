"use client";

/**
 * OfflineIndicator
 *
 * Listens for browser online/offline events and shows a non-intrusive
 * top banner when the device loses internet connectivity.
 *
 * Design constraints:
 * - Never blocks interaction (pointer-events:none when hidden)
 * - Auto-hides 2s after coming back online
 * - Respects prefers-reduced-motion
 * - 44px+ touch target height
 * - Uses CSS transforms for 60fps animation
 *
 * Test IDs:
 * - data-testid="offline-indicator" — always in DOM, visible only when offline
 */

import { useEffect, useState } from "react";

export default function OfflineIndicator() {
  const [isOffline, setIsOffline] = useState(false);
  // "back-online" state: show "Back online!" briefly before hiding
  const [showReconnected, setShowReconnected] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;

    // Hydrate with current network state
    setIsOffline(!navigator.onLine);

    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    function handleOffline() {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      setShowReconnected(false);
      setIsOffline(true);
    }

    function handleOnline() {
      setShowReconnected(true);
      setIsOffline(false);
      // Hide reconnected message after 2.5 seconds
      reconnectTimer = setTimeout(() => {
        setShowReconnected(false);
      }, 2500);
    }

    window.addEventListener("offline", handleOffline);
    window.addEventListener("online", handleOnline);

    return () => {
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener("online", handleOnline);
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, []);

  const isVisible = isOffline || showReconnected;

  return (
    <div
      data-testid="offline-indicator"
      role="status"
      aria-live="polite"
      aria-atomic="true"
      aria-hidden={!isVisible}
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 9999,
        // Account for notched phones
        paddingTop: "env(safe-area-inset-top)",
        transform: isVisible ? "translateY(0)" : "translateY(-100%)",
        transition: "transform 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
        pointerEvents: isVisible ? "auto" : "none",
        // prefers-reduced-motion handled via will-change hint
        willChange: "transform",
      }}
    >
      <div
        style={{
          minHeight: "44px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: "8px",
          padding: "10px 16px",
          backgroundColor: isOffline ? "rgba(239, 68, 68, 0.95)" : "rgba(34, 197, 94, 0.95)",
          backdropFilter: "blur(8px)",
          WebkitBackdropFilter: "blur(8px)",
          color: "#ffffff",
          fontSize: "13px",
          fontWeight: 600,
          letterSpacing: "0.01em",
          userSelect: "none",
        }}
      >
        {/* Status dot */}
        <span
          aria-hidden="true"
          style={{
            width: "7px",
            height: "7px",
            borderRadius: "50%",
            backgroundColor: isOffline ? "#fca5a5" : "#bbf7d0",
            flexShrink: 0,
            animation: isOffline ? "dd-pulse 2s infinite" : "none",
          }}
        />

        {/* Message */}
        <span>
          {isOffline
            ? "You're offline — some features may be limited"
            : "Back online"}
        </span>

        {/* Inline keyframe injection — avoids external CSS dep */}
        <style>{`
          @keyframes dd-pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.35; }
          }
          @media (prefers-reduced-motion: reduce) {
            [data-testid="offline-indicator"] {
              transition: none !important;
            }
            @keyframes dd-pulse { 0%, 100% { opacity: 1; } }
          }
        `}</style>
      </div>
    </div>
  );
}
