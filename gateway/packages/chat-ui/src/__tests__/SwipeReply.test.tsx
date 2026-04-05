/**
 * SwipeReply — TDD tests (RED phase written before implementation).
 *
 * Requirements:
 *   - Wraps children with swipe gesture detection
 *   - Calls onReply(messageId) when swipe threshold is met
 *   - Shows quoted message preview when replyTo is provided
 *   - Cancel gesture (swipe back) does not trigger onReply
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SwipeReply } from "../components/SwipeReply";

describe("SwipeReply", () => {
  it("renders children without crashing", () => {
    render(
      <SwipeReply messageId="msg_1" onReply={vi.fn()}>
        <span>Message content</span>
      </SwipeReply>
    );
    expect(screen.getByText("Message content")).toBeTruthy();
  });

  it("calls onReply with messageId when swipe exceeds threshold", () => {
    const onReply = vi.fn();
    const { container } = render(
      <SwipeReply messageId="msg_1" onReply={onReply}>
        <span>Swipe me</span>
      </SwipeReply>
    );

    const swipeArea = container.firstChild as HTMLElement;
    // Simulate touch swipe right beyond threshold (80px)
    fireEvent.touchStart(swipeArea, { touches: [{ clientX: 0, clientY: 0 }] });
    fireEvent.touchMove(swipeArea, { touches: [{ clientX: 90, clientY: 0 }] });
    fireEvent.touchEnd(swipeArea, { changedTouches: [{ clientX: 90, clientY: 0 }] });

    expect(onReply).toHaveBeenCalledWith("msg_1");
  });

  it("shows quoted message preview when quotedContent is provided", () => {
    render(
      <SwipeReply
        messageId="msg_2"
        onReply={vi.fn()}
        quotedContent="Original message text"
      >
        <span>Reply content</span>
      </SwipeReply>
    );
    expect(screen.getByText("Original message text")).toBeTruthy();
  });

  it("does NOT call onReply when swipe is below threshold (cancel gesture)", () => {
    const onReply = vi.fn();
    const { container } = render(
      <SwipeReply messageId="msg_3" onReply={onReply}>
        <span>Short swipe</span>
      </SwipeReply>
    );

    const swipeArea = container.firstChild as HTMLElement;
    // Only 30px swipe — below 80px threshold
    fireEvent.touchStart(swipeArea, { touches: [{ clientX: 0, clientY: 0 }] });
    fireEvent.touchMove(swipeArea, { touches: [{ clientX: 30, clientY: 0 }] });
    fireEvent.touchEnd(swipeArea, { changedTouches: [{ clientX: 30, clientY: 0 }] });

    expect(onReply).not.toHaveBeenCalled();
  });
});
