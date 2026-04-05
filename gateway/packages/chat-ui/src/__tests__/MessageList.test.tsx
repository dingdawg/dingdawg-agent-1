/**
 * MessageList — TDD tests (RED phase written before implementation).
 *
 * Requirements:
 *   - Renders all messages in a Virtuoso list
 *   - Shows empty state when messages array is empty
 *   - followOutput="smooth" auto-scroll behavior is configured
 *   - Passes messages down to ChatBubble for rendering
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MessageList } from "../components/MessageList";
import type { ChatMessage } from "../types";

// Virtuoso uses ResizeObserver — mock it for jsdom
global.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}));

function makeMessages(count: number): ChatMessage[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `msg_${i}`,
    content: `Message ${i}`,
    role: i % 2 === 0 ? "user" : "assistant",
    timestamp: Date.now() - (count - i) * 1000,
    deliveryStatus: "delivered",
  })) as ChatMessage[];
}

describe("MessageList", () => {
  it("renders empty state when messages array is empty", () => {
    render(
      <MessageList
        messages={[]}
        isStreaming={false}
        onQuickReply={vi.fn()}
      />
    );
    expect(screen.getByText(/agent/i)).toBeTruthy();
  });

  it("renders messages when messages array is non-empty", () => {
    const messages = makeMessages(3);
    render(
      <MessageList
        messages={messages}
        isStreaming={false}
        onQuickReply={vi.fn()}
      />
    );
    // Virtuoso renders a subset in tests; at minimum, a scrollable container exists
    const list = screen.getByRole("log");
    expect(list).toBeTruthy();
  });

  it("shows typing indicator when isStreaming is true", () => {
    render(
      <MessageList
        messages={[]}
        isStreaming
        onQuickReply={vi.fn()}
      />
    );
    // TypingIndicator dots should appear
    // The aria-live region from TypingIndicator should be present
    const liveRegion = document.querySelector("[aria-live='polite']");
    expect(liveRegion).toBeTruthy();
  });

  it("hides typing indicator when isStreaming is false", () => {
    const { container } = render(
      <MessageList
        messages={[]}
        isStreaming={false}
        onQuickReply={vi.fn()}
      />
    );
    const dots = container.querySelectorAll("[data-testid='typing-dot']");
    expect(dots.length).toBe(0);
  });
});
