/**
 * Hooks — TDD tests (RED phase written before implementation).
 *
 * Tests for:
 *   - useChatScroll: scrolls to bottom on new message
 *   - useTypingState: debounces typing clear after keypress
 *   - useDeliveryStatus: transitions between states correctly
 *   - useDeliveryStatus: prevents invalid transitions (e.g., read -> sending)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useChatScroll } from "../hooks/useChatScroll";
import { useTypingState } from "../hooks/useTypingState";
import { useDeliveryStatus } from "../hooks/useDeliveryStatus";

// ─── useChatScroll ────────────────────────────────────────────────────────────

describe("useChatScroll", () => {
  it("returns a ref object and a scrollToBottom function", () => {
    const { result } = renderHook(() => useChatScroll());
    expect(result.current.bottomRef).toBeDefined();
    expect(typeof result.current.scrollToBottom).toBe("function");
  });

  it("scrollToBottom calls scrollIntoView on the ref element if attached", () => {
    const { result } = renderHook(() => useChatScroll());
    const mockEl = { scrollIntoView: vi.fn() };
    // Simulate DOM attachment
    (result.current.bottomRef as React.MutableRefObject<HTMLDivElement | null>).current =
      mockEl as unknown as HTMLDivElement;

    act(() => {
      result.current.scrollToBottom();
    });

    expect(mockEl.scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth" });
  });

  it("scrollToBottom does not throw when ref is null", () => {
    const { result } = renderHook(() => useChatScroll());
    expect(() => {
      act(() => {
        result.current.scrollToBottom();
      });
    }).not.toThrow();
  });
});

// ─── useTypingState ───────────────────────────────────────────────────────────

describe("useTypingState", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts with isTyping false", () => {
    const { result } = renderHook(() => useTypingState());
    expect(result.current.isTyping).toBe(false);
  });

  it("sets isTyping to true via setTyping(true)", () => {
    const { result } = renderHook(() => useTypingState());
    act(() => {
      result.current.setTyping(true);
    });
    expect(result.current.isTyping).toBe(true);
  });

  it("onKeyPress sets isTyping true and debounces clearing after 2000ms", () => {
    const { result } = renderHook(() => useTypingState({ debounceMs: 2000 }));

    act(() => {
      result.current.onKeyPress();
    });
    expect(result.current.isTyping).toBe(true);

    // After 1999ms — still typing
    act(() => {
      vi.advanceTimersByTime(1999);
    });
    expect(result.current.isTyping).toBe(true);

    // After 2000ms — typing clears
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.isTyping).toBe(false);
  });
});

// ─── useDeliveryStatus ────────────────────────────────────────────────────────

describe("useDeliveryStatus", () => {
  it("initializes with provided initial status", () => {
    const { result } = renderHook(() => useDeliveryStatus("sending"));
    expect(result.current.status).toBe("sending");
  });

  it("setStatus updates the status", () => {
    const { result } = renderHook(() => useDeliveryStatus("sending"));
    act(() => {
      result.current.setStatus("sent");
    });
    expect(result.current.status).toBe("sent");
  });

  it("transition follows valid state path: sending -> sent -> delivered -> read", () => {
    const { result } = renderHook(() => useDeliveryStatus("sending"));

    act(() => result.current.transition("sent"));
    expect(result.current.status).toBe("sent");

    act(() => result.current.transition("delivered"));
    expect(result.current.status).toBe("delivered");

    act(() => result.current.transition("read"));
    expect(result.current.status).toBe("read");
  });

  it("transition to 'failed' is always allowed (from any state)", () => {
    const { result } = renderHook(() => useDeliveryStatus("delivered"));
    act(() => {
      result.current.transition("failed");
    });
    expect(result.current.status).toBe("failed");
  });
});
