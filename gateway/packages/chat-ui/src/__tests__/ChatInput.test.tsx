/**
 * ChatInput — TDD tests (RED phase written before implementation).
 *
 * SACRED invariants from UI Lock (must PASS or package is broken):
 *   - Textarea has classes: flex-1 w-full min-w-0 text-base
 *   - Enter key sends message
 *   - Shift+Enter adds newline (does NOT send)
 *   - Disabled prop prevents sending
 *   - Auto-resize on content growth
 *   - Send button is exactly 48x48px (48px touch target)
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatInput } from "../components/ChatInput";

describe("ChatInput", () => {
  it("calls onSend when Enter is pressed with content", async () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    const textarea = screen.getByRole("textbox");
    await userEvent.type(textarea, "Hello{Enter}");
    expect(onSend).toHaveBeenCalledWith("Hello");
  });

  it("does NOT call onSend on Shift+Enter (newline only)", async () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    const textarea = screen.getByRole("textbox");
    await userEvent.type(textarea, "Hello{Shift>}{Enter}{/Shift}");
    expect(onSend).not.toHaveBeenCalled();
  });

  it("preserves SACRED layout classes: flex-1 w-full min-w-0 text-base", () => {
    render(<ChatInput onSend={vi.fn()} />);
    const textarea = screen.getByRole("textbox");
    expect(textarea.className).toContain("flex-1");
    expect(textarea.className).toContain("w-full");
    expect(textarea.className).toContain("min-w-0");
    expect(textarea.className).toContain("text-base");
  });

  it("send button is disabled when input is empty", () => {
    render(<ChatInput onSend={vi.fn()} />);
    const button = screen.getByRole("button", { name: /send/i });
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it("send button is disabled when disabled prop is true", async () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} disabled />);
    const textarea = screen.getByRole("textbox");
    expect((textarea as HTMLTextAreaElement).disabled).toBe(true);
    const button = screen.getByRole("button", { name: /send/i });
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it("send button meets 48px minimum touch target", () => {
    render(<ChatInput onSend={vi.fn()} />);
    const button = screen.getByRole("button", { name: /send/i });
    // h-12 w-12 = 48px — verify class presence
    expect(button.className).toContain("h-12");
    expect(button.className).toContain("w-12");
  });
});
