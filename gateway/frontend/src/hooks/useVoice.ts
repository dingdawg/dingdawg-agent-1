"use client";

/**
 * useVoice.ts — React hook wrapping VoiceEngine for component use.
 *
 * Manages engine lifecycle (create on mount, destroy on unmount),
 * exposes reactive state (isListening, isSpeaking, transcript, error),
 * and provides stable action callbacks.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { VoiceEngine } from "@/lib/voiceEngine";
import type { VoiceEngineConfig } from "@/lib/voiceEngine";

// ─── Hook Return Type ─────────────────────────────────────────────────────────

export interface UseVoiceResult {
  /** The underlying VoiceEngine instance (for advanced use). */
  engine: VoiceEngine;
  /** True while STT is actively listening. */
  isListening: boolean;
  /** True while TTS is actively speaking. */
  isSpeaking: boolean;
  /** Latest transcript text from STT (cleared when startListening is called again). */
  transcript: string;
  /** Error message if the last operation failed, or null. */
  error: string | null;
  /** Start speech-to-text listening. */
  startListening: () => Promise<void>;
  /** Stop speech-to-text listening. */
  stopListening: () => void;
  /** Speak the given text via TTS. */
  speak: (text: string) => Promise<void>;
  /** Stop current TTS playback. */
  stop: () => void;
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

/**
 * React hook for voice interaction (TTS + STT).
 *
 * @param config - Optional partial VoiceEngineConfig to override defaults.
 */
export function useVoice(config?: Partial<VoiceEngineConfig>): UseVoiceResult {
  const engineRef = useRef<VoiceEngine | null>(null);

  // Lazily initialize the engine on first access to avoid SSR issues
  if (engineRef.current === null) {
    engineRef.current = new VoiceEngine(config);
  }

  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Register the transcript callback once on mount
  useEffect(() => {
    const engine = engineRef.current!;

    engine.onTranscript((text, isFinal) => {
      if (isFinal) {
        setTranscript(text);
      }
    });

    // Cleanup on unmount
    return () => {
      engine.destroy();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ─── Actions ──────────────────────────────────────────────────────────────

  const startListening = useCallback(async () => {
    const engine = engineRef.current!;
    setError(null);
    setTranscript("");

    try {
      await engine.startListening();
      setIsListening(true);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to start listening.";
      setError(message);
      setIsListening(false);
    }
  }, []);

  const stopListening = useCallback(() => {
    const engine = engineRef.current!;
    engine.stopListening();
    setIsListening(false);
  }, []);

  const speak = useCallback(async (text: string) => {
    const engine = engineRef.current!;
    setError(null);

    try {
      setIsSpeaking(true);
      await engine.speak(text);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to speak text.";
      setError(message);
    } finally {
      setIsSpeaking(false);
    }
  }, []);

  const stop = useCallback(() => {
    const engine = engineRef.current!;
    engine.stop();
    setIsSpeaking(false);
  }, []);

  return {
    engine: engineRef.current,
    isListening,
    isSpeaking,
    transcript,
    error,
    startListening,
    stopListening,
    speak,
    stop,
  };
}
