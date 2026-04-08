"use client";

/**
 * VoiceInput.tsx — Hold-to-talk voice input component.
 *
 * Complements VoiceButton (tap-to-toggle) with a press-and-hold UX pattern.
 * Uses pointer events (onPointerDown/Up) for cross-device support (desktop + mobile).
 *
 * iOS Safari note: AudioContext.resume() must be called inside a user gesture
 * handler for iOS audio playback to work. The VoiceEngine handles this internally
 * via its _playAudioBuffer method, but any future AudioContext usage in this
 * component must also be triggered from within a pointer/click handler.
 *
 * TODO: Add @ricky0123/vad-web for voice activity detection (auto-stop on silence).
 * Currently relies on manual pointer-up to end recording. VAD would enable
 * hands-free auto-stop when the user stops speaking.
 */

import { useEffect, useRef, useCallback } from "react";
import { Mic, MicOff, Loader2, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { useVoice } from "@/hooks/useVoice";
import type { VoiceEngineConfig } from "@/lib/voiceEngine";

// ─── Props ────────────────────────────────────────────────────────────────────

export interface VoiceInputProps {
  /** Called with the final transcript text when recording completes. */
  onTranscript?: (text: string) => void;
  /** Optional voice engine config overrides. */
  voiceConfig?: Partial<VoiceEngineConfig>;
  /** Disables the input entirely. */
  disabled?: boolean;
  /** Additional CSS classes. */
  className?: string;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function VoiceInput({
  onTranscript,
  voiceConfig,
  disabled = false,
  className = "",
}: VoiceInputProps) {
  const {
    isListening,
    isSpeaking,
    transcript,
    error,
    startListening,
    stopListening,
  } = useVoice(voiceConfig);

  // Track previous transcript to detect changes
  const prevTranscriptRef = useRef("");

  // Fire onTranscript when a new final transcript arrives
  useEffect(() => {
    if (
      transcript &&
      transcript !== prevTranscriptRef.current &&
      onTranscript
    ) {
      prevTranscriptRef.current = transcript;
      onTranscript(transcript);
    }
  }, [transcript, onTranscript]);

  // ─── Pointer handlers (hold-to-talk) ────────────────────────────────────

  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLButtonElement>) => {
      if (disabled || isListening || isSpeaking) return;
      // Prevent default to avoid text selection on long press (mobile)
      e.preventDefault();
      // Capture pointer so pointerup fires even if finger slides off button
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      startListening().catch(() => {
        // Error state handled by useVoice hook
      });
    },
    [disabled, isListening, isSpeaking, startListening],
  );

  const handlePointerUp = useCallback(
    (e: React.PointerEvent<HTMLButtonElement>) => {
      if (!isListening) return;
      (e.target as HTMLElement).releasePointerCapture(e.pointerId);
      stopListening();
    },
    [isListening, stopListening],
  );

  // Also handle pointer cancel (e.g. incoming call interrupts touch)
  const handlePointerCancel = useCallback(
    (_e: React.PointerEvent<HTMLButtonElement>) => {
      if (isListening) {
        stopListening();
      }
    },
    [isListening, stopListening],
  );

  // ─── Derived state ──────────────────────────────────────────────────────

  const state = error
    ? "error"
    : isListening
      ? "recording"
      : isSpeaking
        ? "speaking"
        : "idle";

  const ariaLabel =
    state === "recording"
      ? "Release to stop recording"
      : state === "error"
        ? `Voice input error: ${error}`
        : "Hold to talk";

  const statusLabel =
    state === "recording"
      ? "Recording..."
      : state === "speaking"
        ? "Speaking..."
        : state === "error"
          ? "Error"
          : "Hold to talk";

  // ─── Render ─────────────────────────────────────────────────────────────

  return (
    <div className={cn("flex flex-col items-center gap-1.5", className)}>
      <button
        type="button"
        aria-label={ariaLabel}
        aria-pressed={isListening}
        disabled={disabled}
        onPointerDown={handlePointerDown}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerCancel}
        // Prevent context menu on long press (mobile)
        onContextMenu={(e) => e.preventDefault()}
        className={cn(
          // Base — 48px min touch target
          "h-12 w-12 rounded-2xl flex-shrink-0",
          "flex items-center justify-center",
          "transition-all duration-200 ease-in-out",
          "touch-none select-none",

          // Recording — pulsing red
          state === "recording" && [
            "bg-red-500/20 border-2 border-red-500",
            "shadow-[0_0_16px_rgba(239,68,68,0.4)]",
            "animate-pulse",
            "scale-110",
          ],

          // Speaking — subtle gold glow
          state === "speaking" && [
            "bg-[var(--gold-500)]/10 border-2 border-[var(--gold-500)]",
            "shadow-[0_0_12px_rgba(246,180,0,0.3)]",
          ],

          // Error — orange border
          state === "error" && [
            "bg-orange-500/10 border border-orange-500/50",
          ],

          // Idle — matches DingDawg gold theme
          state === "idle" && [
            "bg-white/5 border border-[var(--color-gold-stroke,rgba(246,180,0,0.3))]",
            "hover:bg-white/10 hover:border-[var(--gold-500,#f6b400)]",
            "active:scale-95",
          ],

          // Disabled
          disabled && "opacity-40 cursor-not-allowed pointer-events-none",
        )}
      >
        {state === "recording" ? (
          <MicOff className="h-5 w-5 text-red-400" aria-hidden="true" />
        ) : state === "speaking" ? (
          <Loader2
            className="h-5 w-5 text-[var(--gold-500,#f6b400)] animate-spin"
            aria-hidden="true"
          />
        ) : state === "error" ? (
          <AlertCircle
            className="h-5 w-5 text-orange-400"
            aria-hidden="true"
          />
        ) : (
          <Mic
            className="h-5 w-5 text-[var(--color-muted,rgba(255,255,255,0.5))]"
            aria-hidden="true"
          />
        )}
      </button>

      {/* Status label */}
      <span
        className={cn(
          "text-[10px] font-medium leading-none select-none",
          state === "recording" && "text-red-400",
          state === "speaking" && "text-[var(--gold-500,#f6b400)]",
          state === "error" && "text-orange-400",
          state === "idle" && "text-[var(--color-muted,rgba(255,255,255,0.5))]",
        )}
        aria-live="polite"
      >
        {statusLabel}
      </span>

      {/* Error detail */}
      {error && (
        <span
          role="alert"
          className="text-[10px] text-orange-400 leading-tight text-center max-w-[120px] select-none"
        >
          {error.includes("not-allowed") ||
          error.includes("Permission") ||
          error.includes("permission")
            ? "Mic permission denied"
            : error.includes("supported")
              ? "Not supported in this browser"
              : "Mic unavailable"}
        </span>
      )}
    </div>
  );
}
