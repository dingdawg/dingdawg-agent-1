/**
 * useVoice.test.ts — TDD RED phase.
 *
 * Tests derive from USER REQUIREMENTS, not implementation.
 *
 * Requirements:
 *   - Returns initial state (isListening=false, isSpeaking=false, error=null)
 *   - startListening() updates isListening to true
 *   - speak() can be called
 *   - Error state surfaced when operations fail
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useVoice } from "../../hooks/useVoice";

// ─── Mock VoiceEngine ────────────────────────────────────────────────────────

let mockIsListening = false;
let mockIsSpeaking = false;

const mockEngine = {
  isSpeaking: vi.fn(() => mockIsSpeaking),
  isListening: vi.fn(() => mockIsListening),
  startListening: vi.fn(async () => {
    mockIsListening = true;
  }),
  stopListening: vi.fn(() => {
    mockIsListening = false;
  }),
  speak: vi.fn(async () => {
    mockIsSpeaking = true;
    // Simulate speech ending
    setTimeout(() => {
      mockIsSpeaking = false;
    }, 50);
  }),
  stop: vi.fn(),
  onTranscript: vi.fn(),
  setProvider: vi.fn(),
  getAvailableProviders: vi.fn(() => ["browser"]),
  testProvider: vi.fn(() => Promise.resolve(true)),
  destroy: vi.fn(),
  speakStream: vi.fn(() => Promise.resolve()),
};

vi.mock("../../lib/voiceEngine", () => ({
  VoiceEngine: vi.fn(() => mockEngine),
}));

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks();
  mockIsListening = false;
  mockIsSpeaking = false;
  mockEngine.isListening.mockImplementation(() => mockIsListening);
  mockEngine.isSpeaking.mockImplementation(() => mockIsSpeaking);
  mockEngine.startListening.mockImplementation(async () => {
    mockIsListening = true;
  });
  mockEngine.stopListening.mockImplementation(() => {
    mockIsListening = false;
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("useVoice", () => {
  it("returns initial state: isListening=false, isSpeaking=false, error=null, transcript=''", () => {
    const { result } = renderHook(() => useVoice());
    expect(result.current.isListening).toBe(false);
    expect(result.current.isSpeaking).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.transcript).toBe("");
    expect(typeof result.current.startListening).toBe("function");
    expect(typeof result.current.stopListening).toBe("function");
    expect(typeof result.current.speak).toBe("function");
    expect(typeof result.current.stop).toBe("function");
    result.current.engine.destroy();
  });

  it("startListening() updates isListening to true", async () => {
    const { result } = renderHook(() => useVoice());

    await act(async () => {
      await result.current.startListening();
    });

    expect(result.current.isListening).toBe(true);
    result.current.engine.destroy();
  });

  it("speak() can be called without throwing", async () => {
    const { result } = renderHook(() => useVoice());

    await act(async () => {
      await result.current.speak("Hello");
    });

    expect(mockEngine.speak).toHaveBeenCalledWith("Hello");
    result.current.engine.destroy();
  });

  it("error state is set when startListening fails", async () => {
    mockEngine.startListening.mockRejectedValueOnce(new Error("Permission denied"));

    const { result } = renderHook(() => useVoice());

    await act(async () => {
      await result.current.startListening();
    });

    expect(result.current.error).toBeTruthy();
    expect(result.current.error).toMatch(/permission denied/i);
    result.current.engine.destroy();
  });
});
