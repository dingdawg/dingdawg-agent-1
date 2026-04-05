"use client";

/**
 * VoiceButton.tsx — Standalone microphone button for voice input.
 *
 * Integrates with VoiceEngine for STT. Designed to sit alongside ChatInput
 * without modifying it (UI Lock invariant preserved).
 *
 * UI Behavior:
 *   - Tap to start listening → icon pulses red, aria-label updates
 *   - Tap again to stop → transcript sent to onTranscript callback
 *   - Error state shown inline when microphone access is denied
 *   - 48px minimum touch target (h-12 w-12)
 *   - Accessible: aria-label, role="button", keyboard (Enter/Space)
 */

import { useState, useCallback, useEffect, useRef } from "react";
import { Mic, MicOff, Volume2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { VoiceEngine } from "@/lib/voiceEngine";
import type { VoiceEngineConfig } from "@/lib/voiceEngine";

// ─── Props ────────────────────────────────────────────────────────────────────

export interface VoiceButtonProps {
  /** Called with the final transcript when the user stops speaking. */
  onTranscript: (text: string) => void;
  /** Optional callback fired when TTS speaking state changes. */
  onSpeakingChange?: (isSpeaking: boolean) => void;
  /** Disables the button entirely. */
  disabled?: boolean;
  /** Additional CSS classes applied to the button. */
  className?: string;
  /** Touch target size in pixels (min 48). Default: 48. */
  size?: number;
  /** Voice engine config overrides. */
  voiceConfig?: Partial<VoiceEngineConfig>;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function VoiceButton({
  onTranscript,
  onSpeakingChange,
  disabled = false,
  className,
  size = 48,
  voiceConfig,
}: VoiceButtonProps) {
  // Enforce minimum 48px touch target
  const safeSz = Math.max(48, size);

  const [isListening, setIsListening] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Stable engine ref — created once, destroyed on unmount
  const engineRef = useRef<VoiceEngine | null>(null);
  if (engineRef.current === null) {
    engineRef.current = new VoiceEngine(voiceConfig);
  }

  // Register transcript callback once on mount
  useEffect(() => {
    const engine = engineRef.current!;

    engine.onTranscript((text, isFinal) => {
      if (isFinal && text.trim()) {
        onTranscript(text.trim());
      }
    });

    return () => {
      engine.destroy();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ─── Toggle handler ──────────────────────────────────────────────────────

  const handleToggle = useCallback(async () => {
    if (disabled) return;

    const engine = engineRef.current!;

    if (isListening) {
      engine.stopListening();
      setIsListening(false);
      return;
    }

    setError(null);

    try {
      await engine.startListening();
      setIsListening(true);
    } catch (err) {
      setIsListening(false);
      const msg =
        err instanceof Error
          ? err.message
          : "Microphone not available. Please check your browser permissions.";
      setError(msg);
    }
  }, [disabled, isListening]);

  // ─── Keyboard handler (Enter / Space toggle) ─────────────────────────────

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLButtonElement>) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        handleToggle();
      }
    },
    [handleToggle]
  );

  // ─── Derived state ───────────────────────────────────────────────────────

  const ariaLabel = isListening
    ? "Stop listening — click to stop voice input"
    : "Start voice input — click to speak";

  const buttonTitle = isListening ? "Stop listening" : "Start voice input";

  // ─── Render ──────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col items-center gap-1">
      <button
        type="button"
        role="button"
        aria-label={ariaLabel}
        title={buttonTitle}
        aria-pressed={isListening}
        disabled={disabled}
        onClick={handleToggle}
        onKeyDown={handleKeyDown}
        style={{ width: safeSz, height: safeSz, minWidth: safeSz, minHeight: safeSz }}
        className={cn(
          // Base sizing — 48px touch target
          "h-12 w-12 rounded-2xl flex-shrink-0",
          "flex items-center justify-center",
          // Transition
          "transition-all duration-200 ease-in-out",
          // Active: listening state — red pulse ring
          isListening && [
            "bg-red-500/20 border-2 border-red-500",
            "shadow-[0_0_16px_rgba(239,68,68,0.4)]",
            "animate-pulse",
          ],
          // Idle: matches DingDawg gold theme
          !isListening && [
            "bg-white/5 border border-[var(--color-gold-stroke,rgba(246,180,0,0.3))]",
            "hover:bg-white/10 hover:border-[var(--gold-500,#f6b400)]",
            "active:scale-95",
          ],
          // Disabled
          disabled && "opacity-40 cursor-not-allowed pointer-events-none",
          // Error state
          error && !isListening && "border-orange-500/50",
          className
        )}
      >
        {isListening ? (
          // Listening: show mic-off so user knows "click to stop"
          <MicOff
            className="h-5 w-5 text-red-400"
            aria-hidden="true"
          />
        ) : error ? (
          // Error: volume-x or mic with muted color
          <Volume2
            className="h-5 w-5 text-orange-400"
            aria-hidden="true"
          />
        ) : (
          // Idle: standard mic
          <Mic
            className="h-5 w-5 text-[var(--color-muted,rgba(255,255,255,0.5))] group-hover:text-[var(--gold-500,#f6b400)]"
            aria-hidden="true"
          />
        )}
      </button>

      {/* Status label — hidden when idle, shown when listening or error */}
      {isListening && (
        <span
          className="text-[10px] font-medium text-red-400 leading-none select-none"
          aria-live="polite"
        >
          Listening...
        </span>
      )}

      {/* Error message — accessible alert */}
      {error && !isListening && (
        <span
          role="alert"
          className="text-[10px] text-orange-400 leading-none text-center max-w-[80px] select-none"
        >
          {error.includes("not-allowed") || error.includes("Permission") || error.includes("permission")
            ? "Mic permission denied"
            : error.includes("supported")
            ? "Not supported"
            : "Mic unavailable"}
        </span>
      )}
    </div>
  );
}
