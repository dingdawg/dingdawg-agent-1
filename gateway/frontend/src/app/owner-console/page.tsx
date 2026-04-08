"use client";

/**
 * Owner Console — Tier 1 WebRTC call answering.
 *
 * Architecture (Tier 1):
 *   Customer → Vapi PSTN/web → transfer_to_owner webhook → backend stores webCallUrl
 *   → SSE pushes event here → owner clicks Answer → vapi.reconnect(webCallUrl)
 *   → WebRTC DTLS 1.3 + SRTP AES-128 via Daily.co (no PSTN hop)
 *
 * Env vars required on backend:
 *   VAPI_OWNER_CONSOLE_ENABLED=true
 *   ISG_AGENT_ADMIN_EMAIL=<owner email>
 *
 * Env vars required on frontend (.env.local):
 *   NEXT_PUBLIC_VAPI_PUBLIC_KEY=<from Vapi dashboard>
 */

import { useEffect, useRef, useState, useCallback } from "react";
import Vapi from "@vapi-ai/web";
import { getAccessToken, get, post } from "@/services/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PendingCall {
  call_id: string;
  webCallUrl: string;
  caller_id: string;
  timestamp: number;
  status: string;
}

type CallState = "idle" | "connecting" | "active" | "ending";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0");
  const s = (seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function formatCallerTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function OwnerConsolePage() {
  const [pendingCalls, setPendingCalls] = useState<PendingCall[]>([]);
  const [callState, setCallState] = useState<CallState>("idle");
  const [activeCallId, setActiveCallId] = useState<string | null>(null);
  const [isMuted, setIsMuted] = useState(false);
  const [volume, setVolume] = useState(0);
  const [duration, setDuration] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const vapiRef = useRef<Vapi | null>(null);
  const durationRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sseRef = useRef<EventSource | null>(null);

  const publicKey = process.env.NEXT_PUBLIC_VAPI_PUBLIC_KEY ?? "";

  // ── Initialize Vapi SDK ──────────────────────────────────────────────────
  useEffect(() => {
    if (!publicKey) return;
    const vapi = new Vapi(publicKey);

    vapi.on("call-start", () => {
      setCallState("active");
      setDuration(0);
      durationRef.current = setInterval(
        () => setDuration((d) => d + 1),
        1_000,
      );
    });

    vapi.on("call-end", () => {
      setCallState("idle");
      setActiveCallId(null);
      setIsMuted(false);
      setVolume(0);
      if (durationRef.current) clearInterval(durationRef.current);
    });

    vapi.on("volume-level", (v) => setVolume(Math.round(v * 100)));

    vapi.on("error", (err) => {
      console.error("[OwnerConsole] Vapi error:", err);
      setError("Call error — check microphone permissions and try again.");
      setCallState("idle");
    });

    vapiRef.current = vapi;
    return () => {
      vapi.stop();
      vapiRef.current = null;
    };
  }, [publicKey]);

  // ── Fetch initial pending calls ──────────────────────────────────────────
  const fetchPending = useCallback(async () => {
    try {
      const data = await get<{ calls: PendingCall[] }>(
        "/api/v1/voice/owner-console/pending",
      );
      setPendingCalls(data.calls ?? []);
    } catch {
      // silently ignore — SSE will hydrate on next event
    }
  }, []);

  useEffect(() => {
    fetchPending();
  }, [fetchPending]);

  // ── SSE stream ───────────────────────────────────────────────────────────
  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;

    const url = `/api/v1/voice/owner-console/stream?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);
    sseRef.current = es;

    es.onmessage = (evt) => {
      try {
        const call: PendingCall = JSON.parse(evt.data);
        setPendingCalls((prev) => {
          const exists = prev.some((c) => c.call_id === call.call_id);
          return exists ? prev : [call, ...prev];
        });
      } catch {
        // malformed event — ignore
      }
    };

    es.onerror = () => {
      // EventSource auto-reconnects — no manual action needed
    };

    return () => {
      es.close();
      sseRef.current = null;
    };
  }, []);

  // ── Answer call ──────────────────────────────────────────────────────────
  const handleAnswer = useCallback(
    async (call: PendingCall) => {
      if (!vapiRef.current) {
        setError("Vapi SDK not ready — set NEXT_PUBLIC_VAPI_PUBLIC_KEY");
        return;
      }
      if (!call.webCallUrl) {
        setError(
          "No WebRTC URL for this call. Ensure VAPI_OWNER_CONSOLE_ENABLED=true on backend.",
        );
        return;
      }
      setError(null);
      setCallState("connecting");
      setActiveCallId(call.call_id);
      try {
        await vapiRef.current.reconnect({ webCallUrl: call.webCallUrl });
      } catch (err) {
        console.error("[OwnerConsole] reconnect failed:", err);
        setError("Failed to connect — check mic permissions.");
        setCallState("idle");
        setActiveCallId(null);
      }
    },
    [],
  );

  // ── End call ─────────────────────────────────────────────────────────────
  const handleEnd = useCallback(async () => {
    if (!vapiRef.current) return;
    setCallState("ending");
    vapiRef.current.stop();
    if (activeCallId) {
      setPendingCalls((prev) => prev.filter((c) => c.call_id !== activeCallId));
      try {
        await post(`/api/v1/voice/owner-console/dismiss/${activeCallId}`);
      } catch {
        // best-effort dismiss
      }
    }
  }, [activeCallId]);

  // ── Mute toggle ──────────────────────────────────────────────────────────
  const handleMute = useCallback(() => {
    if (!vapiRef.current) return;
    const next = !isMuted;
    vapiRef.current.setMuted(next);
    setIsMuted(next);
  }, [isMuted]);

  // ── Dismiss pending call (decline) ───────────────────────────────────────
  const handleDismiss = useCallback(async (callId: string) => {
    setPendingCalls((prev) => prev.filter((c) => c.call_id !== callId));
    try {
      await post(`/api/v1/voice/owner-console/dismiss/${callId}`);
    } catch {
      // best-effort
    }
  }, []);

  // ── Render ───────────────────────────────────────────────────────────────
  const isInCall = callState !== "idle";

  return (
    <div className="min-h-screen bg-[var(--ink-950)] text-white p-6 lg:p-10">
      <div className="max-w-2xl mx-auto space-y-6">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              Owner Console
            </h1>
            <p className="text-sm text-[var(--ink-400)] mt-0.5">
              WebRTC · DTLS 1.3 · SRTP AES-128 · No PSTN
            </p>
          </div>
          {/* Connection status dot */}
          <div className="flex items-center gap-2 text-xs text-[var(--ink-400)]">
            <span
              className={`w-2 h-2 rounded-full ${
                isInCall ? "bg-green-400 animate-pulse" : "bg-[var(--ink-600)]"
              }`}
            />
            {isInCall ? "Live" : "Standby"}
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div
            role="alert"
            className="rounded-lg bg-red-500/10 border border-red-500/30 px-4 py-3 text-sm text-red-400"
          >
            {error}
            <button
              className="ml-3 underline opacity-70 hover:opacity-100"
              onClick={() => setError(null)}
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Active call card */}
        {isInCall && (
          <div className="rounded-xl border border-green-500/30 bg-green-500/5 p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-green-400 uppercase tracking-widest font-semibold">
                  {callState === "connecting" ? "Connecting…" : "Active Call"}
                </p>
                <p className="text-lg font-semibold mt-0.5">
                  {activeCallId
                    ? pendingCalls.find((c) => c.call_id === activeCallId)
                        ?.caller_id ?? "Unknown caller"
                    : "Unknown caller"}
                </p>
              </div>
              <span className="font-mono text-2xl text-green-400 tabular-nums">
                {formatDuration(duration)}
              </span>
            </div>

            {/* Volume bar */}
            <div className="space-y-1">
              <p className="text-xs text-[var(--ink-400)]">
                Caller volume — {volume}%
              </p>
              <div className="h-1.5 rounded-full bg-[var(--ink-800)] overflow-hidden">
                <div
                  className="h-full bg-green-400 transition-all duration-100 rounded-full"
                  style={{ width: `${volume}%` }}
                />
              </div>
            </div>

            {/* Controls */}
            <div className="flex gap-3">
              <button
                onClick={handleMute}
                className={`flex-1 py-2.5 rounded-lg text-sm font-semibold transition-colors ${
                  isMuted
                    ? "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30"
                    : "bg-[var(--ink-800)] text-white hover:bg-[var(--ink-700)]"
                }`}
              >
                {isMuted ? "Unmute" : "Mute"}
              </button>
              <button
                onClick={handleEnd}
                disabled={callState === "ending"}
                className="flex-1 py-2.5 rounded-lg text-sm font-semibold bg-red-500/20 text-red-400 border border-red-500/30 hover:bg-red-500/30 transition-colors disabled:opacity-50"
              >
                {callState === "ending" ? "Ending…" : "End Call"}
              </button>
            </div>
          </div>
        )}

        {/* Pending calls */}
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-[var(--ink-300)] uppercase tracking-widest">
            Incoming Calls
            {pendingCalls.length > 0 && (
              <span className="ml-2 px-1.5 py-0.5 rounded-full bg-[var(--gold-500)]/20 text-[var(--gold-400)] text-[10px]">
                {pendingCalls.length}
              </span>
            )}
          </h2>

          {pendingCalls.length === 0 ? (
            <div className="rounded-xl border border-[var(--ink-800)] bg-[var(--ink-900)] p-8 text-center">
              <p className="text-[var(--ink-500)] text-sm">
                No pending calls — standing by
              </p>
              <p className="text-[var(--ink-600)] text-xs mt-1">
                Calls appear here when a customer asks to speak with you
              </p>
            </div>
          ) : (
            <ul className="space-y-2">
              {pendingCalls.map((call) => (
                <li
                  key={call.call_id}
                  className="rounded-xl border border-[var(--ink-800)] bg-[var(--ink-900)] p-4 flex items-center justify-between gap-4"
                >
                  <div className="min-w-0">
                    <p className="font-medium truncate">{call.caller_id}</p>
                    <p className="text-xs text-[var(--ink-500)] mt-0.5">
                      {formatCallerTime(call.timestamp)}
                      {!call.webCallUrl && (
                        <span className="ml-2 text-yellow-500">
                          · no WebRTC URL
                        </span>
                      )}
                    </p>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <button
                      onClick={() => handleAnswer(call)}
                      disabled={isInCall || !call.webCallUrl}
                      className="px-4 py-1.5 rounded-lg text-sm font-semibold bg-green-500/20 text-green-400 border border-green-500/30 hover:bg-green-500/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      Answer
                    </button>
                    <button
                      onClick={() => handleDismiss(call.call_id)}
                      disabled={isInCall && activeCallId === call.call_id}
                      className="px-3 py-1.5 rounded-lg text-sm text-[var(--ink-400)] hover:text-white hover:bg-[var(--ink-800)] transition-colors disabled:opacity-40"
                    >
                      Decline
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Setup checklist */}
        {!publicKey && (
          <div className="rounded-xl border border-yellow-500/20 bg-yellow-500/5 p-4 text-sm space-y-1">
            <p className="font-semibold text-yellow-400">Setup required</p>
            <ul className="text-yellow-300/70 space-y-0.5 list-disc list-inside">
              <li>
                Add <code className="text-xs">NEXT_PUBLIC_VAPI_PUBLIC_KEY</code>{" "}
                to frontend <code className="text-xs">.env.local</code>
              </li>
              <li>
                Set <code className="text-xs">VAPI_OWNER_CONSOLE_ENABLED=true</code>{" "}
                on Railway backend
              </li>
              <li>
                Set <code className="text-xs">ISG_AGENT_ADMIN_EMAIL</code> to your email
              </li>
            </ul>
          </div>
        )}

      </div>
    </div>
  );
}
