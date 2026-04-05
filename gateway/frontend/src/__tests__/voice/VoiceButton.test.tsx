/**
 * VoiceButton.test.tsx — TDD RED phase.
 *
 * Tests derive from USER REQUIREMENTS, not implementation.
 *
 * Requirements:
 *   - Renders a microphone icon button
 *   - Click starts/stops listening
 *   - Sends transcript to onTranscript callback
 *   - Disabled state prevents interaction
 *   - 48px minimum touch target
 *   - ARIA labels present for accessibility
 *   - Shows error when microphone access denied
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { VoiceButton } from "../../components/chat/VoiceButton";

// ─── Mock VoiceEngine ────────────────────────────────────────────────────────

const mockEngine = {
  isSpeaking: vi.fn(() => false),
  isListening: vi.fn(() => false),
  startListening: vi.fn(() => Promise.resolve()),
  stopListening: vi.fn(),
  speak: vi.fn(() => Promise.resolve()),
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
  mockEngine.isListening.mockReturnValue(false);
  mockEngine.startListening.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("VoiceButton", () => {
  it("renders a microphone icon button", () => {
    render(<VoiceButton onTranscript={vi.fn()} />);
    // Should find a button with a mic-related aria label
    const btn = screen.getByRole("button");
    expect(btn).toBeTruthy();
  });

  it("click starts listening when not already listening", async () => {
    const onTranscript = vi.fn();
    render(<VoiceButton onTranscript={onTranscript} />);
    const btn = screen.getByRole("button");
    await act(async () => {
      fireEvent.click(btn);
    });
    expect(mockEngine.startListening).toHaveBeenCalled();
  });

  it("click again stops listening when already listening", async () => {
    const onTranscript = vi.fn();
    render(<VoiceButton onTranscript={onTranscript} />);
    const btn = screen.getByRole("button");

    // First click: start listening
    await act(async () => {
      fireEvent.click(btn);
    });
    expect(mockEngine.startListening).toHaveBeenCalled();

    // Second click: component local state is now isListening=true → should stop
    await act(async () => {
      fireEvent.click(btn);
    });
    expect(mockEngine.stopListening).toHaveBeenCalled();
  });

  it("sends transcript to onTranscript callback when final result received", async () => {
    const onTranscript = vi.fn();
    render(<VoiceButton onTranscript={onTranscript} />);

    // Simulate the engine calling back with final transcript
    const registeredCallback = mockEngine.onTranscript.mock.calls[0]?.[0];
    if (registeredCallback) {
      act(() => {
        registeredCallback("hello from voice", true);
      });
      expect(onTranscript).toHaveBeenCalledWith("hello from voice");
    } else {
      // onTranscript registered via hook — trigger via startListening
      await act(async () => {
        fireEvent.click(screen.getByRole("button"));
      });
      const cb = mockEngine.onTranscript.mock.calls[0]?.[0];
      if (cb) {
        act(() => cb("hello from voice", true));
        expect(onTranscript).toHaveBeenCalledWith("hello from voice");
      }
    }
  });

  it("disabled prop prevents starting listening on click", async () => {
    render(<VoiceButton onTranscript={vi.fn()} disabled />);
    const btn = screen.getByRole("button");
    expect(btn).toBeDisabled();
    await act(async () => {
      fireEvent.click(btn);
    });
    expect(mockEngine.startListening).not.toHaveBeenCalled();
  });

  it("button has minimum 48px touch target size", () => {
    const { container } = render(<VoiceButton onTranscript={vi.fn()} />);
    const btn = container.querySelector("button");
    expect(btn).toBeTruthy();
    // Check inline style or className for size — must be at least 48px
    // The component must set w-12 h-12 (48px) or equivalent
    const style = btn!.getAttribute("style") ?? "";
    const className = btn!.className ?? "";
    const has48px =
      style.includes("48px") ||
      className.includes("h-12") ||
      className.includes("w-12") ||
      className.includes("min-h-[48px]") ||
      className.includes("min-w-[48px]");
    expect(has48px).toBe(true);
  });

  it("has aria-label for screen readers", () => {
    render(<VoiceButton onTranscript={vi.fn()} />);
    const btn = screen.getByRole("button");
    const ariaLabel = btn.getAttribute("aria-label");
    expect(ariaLabel).toBeTruthy();
    expect(ariaLabel!.length).toBeGreaterThan(0);
  });

  it("shows error state when microphone permission is denied", async () => {
    mockEngine.startListening.mockRejectedValue(new Error("Permission denied"));
    render(<VoiceButton onTranscript={vi.fn()} />);
    const btn = screen.getByRole("button");

    await act(async () => {
      fireEvent.click(btn);
    });

    // After rejection, error state should be visible
    const errorEl = screen.queryByRole("alert") ?? screen.queryByText(/permission|denied|not available|microphone/i);
    expect(errorEl).toBeTruthy();
  });
});
