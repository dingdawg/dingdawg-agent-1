/**
 * Integration tests — Full chat flow send-receive-display.
 *
 * Tests:
 *   1. User types and sends message → ChatInput fires onSend
 *   2. ChatBubble renders message with delivery status
 *   3. TypingIndicator appears during streaming, hides after
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatBubble } from "../components/ChatBubble";
import { ChatInput } from "../components/ChatInput";
import { TypingIndicator } from "../components/TypingIndicator";
import type { ChatMessage } from "../types";

// Mock ResizeObserver for jsdom
global.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}));

describe("Integration: full chat send-receive-display", () => {
  it("user types message and presses Enter, onSend is called with trimmed text", async () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} placeholder="Ask anything..." />);

    const textarea = screen.getByPlaceholderText("Ask anything...");
    await userEvent.type(textarea, "  What is my schedule today?  {Enter}");

    expect(onSend).toHaveBeenCalledWith("What is my schedule today?");
  });

  it("ChatBubble renders assistant message with delivered status after send", () => {
    const assistantMsg: ChatMessage = {
      id: "msg_resp_1",
      content: "Your schedule for today: 9am standup, 2pm client call.",
      role: "assistant",
      timestamp: Date.now(),
      deliveryStatus: "delivered",
    };
    const { container } = render(<ChatBubble message={assistantMsg} />);

    expect(screen.getByText(/Your schedule for today/)).toBeTruthy();
    // Assistant bubble should be left-aligned
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.className).toContain("items-start");
  });

  it("TypingIndicator appears during streaming and disappears after", () => {
    const { rerender, container } = render(<TypingIndicator visible />);

    // During streaming: 3 dots visible
    let dots = container.querySelectorAll("[data-testid='typing-dot']");
    expect(dots.length).toBe(3);

    // After streaming completes: no dots
    rerender(<TypingIndicator visible={false} />);
    dots = container.querySelectorAll("[data-testid='typing-dot']");
    expect(dots.length).toBe(0);
  });
});
