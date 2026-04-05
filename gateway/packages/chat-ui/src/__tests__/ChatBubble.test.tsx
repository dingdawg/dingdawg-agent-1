/**
 * ChatBubble — TDD tests (RED phase written before implementation).
 *
 * Tests derive from USER REQUIREMENTS, not implementation.
 * Requirements:
 *   - User messages right-aligned (blue bubble)
 *   - Assistant messages left-aligned (gray bubble)
 *   - System messages centered (pill)
 *   - Timestamps shown below bubble
 *   - Dark mode support via CSS variables
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ChatBubble } from "../components/ChatBubble";
import type { ChatMessage } from "../types";

function makeMessage(overrides: Partial<ChatMessage>): ChatMessage {
  return {
    id: "msg_test_1",
    content: "Hello, world!",
    role: "user",
    timestamp: new Date("2026-01-01T12:00:00Z").getTime(),
    deliveryStatus: "delivered",
    ...overrides,
  };
}

describe("ChatBubble", () => {
  it("renders user message content", () => {
    render(<ChatBubble message={makeMessage({ content: "Hi there!" })} />);
    expect(screen.getByText("Hi there!")).toBeTruthy();
  });

  it("applies right-alignment for user role", () => {
    const { container } = render(
      <ChatBubble message={makeMessage({ role: "user" })} />
    );
    // Outer wrapper should have items-end (right-align flex column)
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.className).toContain("items-end");
  });

  it("applies left-alignment for assistant role", () => {
    const { container } = render(
      <ChatBubble message={makeMessage({ role: "assistant", content: "Hello from assistant" })} />
    );
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.className).toContain("items-start");
  });

  it("renders system message as centered pill", () => {
    const { container } = render(
      <ChatBubble message={makeMessage({ role: "system", content: "Session started" })} />
    );
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.className).toContain("justify-center");
    expect(screen.getByText("Session started")).toBeTruthy();
  });

  it("shows formatted timestamp below bubble", () => {
    render(
      <ChatBubble
        message={makeMessage({ timestamp: new Date("2026-01-01T12:00:00Z").getTime() })}
      />
    );
    // Timestamp element should exist in the DOM (formatted string)
    const timeEl = screen.getByRole("time");
    expect(timeEl).toBeTruthy();
  });
});
