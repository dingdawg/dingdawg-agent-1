/**
 * usePolling.test.ts — Unit tests for the usePolling hook.
 *
 * Tests:
 *   - Calls callback immediately on mount (before first interval tick)
 *   - Calls callback again after intervalMs elapses (respects interval)
 *   - Does NOT call callback when enabled=false
 *   - Disabling after mount stops future calls
 *   - Re-enabling after disable fires callback immediately
 *   - Cleans up interval on unmount (no calls after unmount)
 *   - Pauses polling when document becomes hidden
 *   - Resumes and fires immediately when document becomes visible again
 *   - Uses the latest callback ref (does not capture stale closure)
 *   - Handles async callback without throwing
 *
 * Run: npx vitest run src/__tests__/admin/usePolling.test.ts
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { usePolling } from "@/hooks/usePolling";

// ─── Setup: fake timers ───────────────────────────────────────────────────────

beforeEach(() => {
  vi.useFakeTimers();
  // Restore document.hidden to its default (visible) state
  Object.defineProperty(document, "hidden", {
    configurable: true,
    get: () => false,
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

// ─── Helper: fire a visibilitychange event ─────────────────────────────────

function setDocumentHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", {
    configurable: true,
    get: () => hidden,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("usePolling", () => {
  // ── Immediate call on mount ───────────────────────────────────────────────────

  it("calls callback immediately on mount before any interval tick", () => {
    const callback = vi.fn();

    renderHook(() => usePolling(callback, 30_000));

    // No timers advanced — callback must have fired synchronously on mount
    expect(callback).toHaveBeenCalledTimes(1);
  });

  // ── Respects interval ─────────────────────────────────────────────────────────

  it("calls callback again after intervalMs elapses", () => {
    const callback = vi.fn();

    renderHook(() => usePolling(callback, 5_000));

    // 1 call on mount
    expect(callback).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(5_000);
    });

    // 1 mount + 1 interval tick
    expect(callback).toHaveBeenCalledTimes(2);
  });

  it("calls callback on each interval tick", () => {
    const callback = vi.fn();

    renderHook(() => usePolling(callback, 1_000));

    expect(callback).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(3_000);
    });

    // 1 mount + 3 ticks
    expect(callback).toHaveBeenCalledTimes(4);
  });

  // ── enabled=false ─────────────────────────────────────────────────────────────

  it("does NOT call callback on mount when enabled=false", () => {
    const callback = vi.fn();

    renderHook(() => usePolling(callback, 5_000, false));

    expect(callback).not.toHaveBeenCalled();
  });

  it("does NOT call callback on interval ticks when enabled=false", () => {
    const callback = vi.fn();

    renderHook(() => usePolling(callback, 1_000, false));

    act(() => {
      vi.advanceTimersByTime(5_000);
    });

    expect(callback).not.toHaveBeenCalled();
  });

  // ── Dynamic enable/disable ────────────────────────────────────────────────────

  it("stops calling callback when enabled transitions from true to false", () => {
    const callback = vi.fn();
    let enabled = true;

    const { rerender } = renderHook(() => usePolling(callback, 1_000, enabled));

    // 1 call on mount
    expect(callback).toHaveBeenCalledTimes(1);

    // Disable
    enabled = false;
    rerender();

    act(() => {
      vi.advanceTimersByTime(5_000);
    });

    // Still only the initial call — no new ticks while disabled
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("fires callback immediately when re-enabled after being disabled", () => {
    const callback = vi.fn();
    let enabled = false;

    const { rerender } = renderHook(() => usePolling(callback, 1_000, enabled));

    expect(callback).toHaveBeenCalledTimes(0);

    // Enable
    enabled = true;
    rerender();

    // Should fire immediately on re-enable
    expect(callback).toHaveBeenCalledTimes(1);
  });

  // ── Cleanup on unmount ────────────────────────────────────────────────────────

  it("clears interval on unmount — no further calls after unmount", () => {
    const callback = vi.fn();

    const { unmount } = renderHook(() => usePolling(callback, 1_000));

    expect(callback).toHaveBeenCalledTimes(1);

    unmount();

    act(() => {
      vi.advanceTimersByTime(5_000);
    });

    // Count must not increase after unmount
    expect(callback).toHaveBeenCalledTimes(1);
  });

  // ── Page Visibility API ───────────────────────────────────────────────────────

  it("pauses polling when document becomes hidden", () => {
    const callback = vi.fn();

    renderHook(() => usePolling(callback, 1_000));

    expect(callback).toHaveBeenCalledTimes(1);

    // Hide the tab
    act(() => {
      setDocumentHidden(true);
    });

    // Advance — interval ticks should be skipped because document.hidden=true
    act(() => {
      vi.advanceTimersByTime(3_000);
    });

    // Still only the initial mount call
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("resumes and fires callback immediately when tab becomes visible again", () => {
    const callback = vi.fn();

    renderHook(() => usePolling(callback, 1_000));

    // 1 call on mount
    expect(callback).toHaveBeenCalledTimes(1);

    act(() => {
      setDocumentHidden(true);
    });

    // No additional calls while hidden
    act(() => {
      vi.advanceTimersByTime(2_000);
    });
    expect(callback).toHaveBeenCalledTimes(1);

    // Make visible — should fire immediately
    act(() => {
      setDocumentHidden(false);
    });

    expect(callback).toHaveBeenCalledTimes(2);
  });

  it("resumes interval ticks after becoming visible", () => {
    const callback = vi.fn();

    renderHook(() => usePolling(callback, 1_000));

    act(() => {
      setDocumentHidden(true);
    });
    act(() => {
      setDocumentHidden(false);
    });

    // 1 mount + 1 on-visible = 2 so far
    const countAfterVisible = callback.mock.calls.length;

    act(() => {
      vi.advanceTimersByTime(3_000);
    });

    // Should get 3 more ticks
    expect(callback.mock.calls.length).toBe(countAfterVisible + 3);
  });

  // ── Stale closure guard ───────────────────────────────────────────────────────

  it("always calls the latest callback reference, not a stale one", () => {
    const firstCallback = vi.fn();
    const secondCallback = vi.fn();
    let currentCallback = firstCallback;

    const { rerender } = renderHook(() =>
      usePolling(() => currentCallback(), 1_000)
    );

    expect(firstCallback).toHaveBeenCalledTimes(1);

    // Switch callback
    currentCallback = secondCallback;
    rerender();

    act(() => {
      vi.advanceTimersByTime(1_000);
    });

    // The tick should invoke secondCallback via the ref, not firstCallback
    expect(secondCallback).toHaveBeenCalledTimes(1);
    // firstCallback is still only 1 (mount call before switch)
    expect(firstCallback).toHaveBeenCalledTimes(1);
  });

  // ── Async callback ────────────────────────────────────────────────────────────

  it("handles async callback without throwing", async () => {
    const asyncCallback = vi.fn().mockResolvedValue(undefined);

    const { unmount } = renderHook(() => usePolling(asyncCallback, 1_000));

    expect(asyncCallback).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(2_000);
    });

    // Allow any pending promises to settle
    await Promise.resolve();

    expect(asyncCallback).toHaveBeenCalledTimes(3);

    // unmount must not throw even if async callbacks are still pending
    expect(() => unmount()).not.toThrow();
  });

  // ── Default intervalMs ────────────────────────────────────────────────────────

  it("defaults to 60-second interval when intervalMs is not provided", () => {
    const callback = vi.fn();

    renderHook(() => usePolling(callback));

    expect(callback).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(59_999);
    });

    // Not yet — 60s hasn't elapsed
    expect(callback).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(1);
    });

    // Now 60s has elapsed
    expect(callback).toHaveBeenCalledTimes(2);
  });
});
