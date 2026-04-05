/**
 * TypingIndicator — TDD tests (RED phase written before implementation).
 *
 * Requirements:
 *   - Shows 3 animated dots when visible=true
 *   - Hidden (not in DOM or hidden) when visible=false
 *   - Has aria-live="polite" for screen readers
 *   - Animation CSS class is present on dots
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TypingIndicator } from "../components/TypingIndicator";

describe("TypingIndicator", () => {
  it("renders 3 dot elements when visible is true", () => {
    const { container } = render(<TypingIndicator visible />);
    const dots = container.querySelectorAll("[data-testid='typing-dot']");
    expect(dots.length).toBe(3);
  });

  it("is not rendered in DOM when visible is false", () => {
    const { container } = render(<TypingIndicator visible={false} />);
    const dots = container.querySelectorAll("[data-testid='typing-dot']");
    expect(dots.length).toBe(0);
  });

  it("has aria-live='polite' attribute for accessibility", () => {
    const { container } = render(<TypingIndicator visible />);
    const liveRegion = container.querySelector("[aria-live='polite']");
    expect(liveRegion).toBeTruthy();
  });

  it("dots have bounce animation CSS class", () => {
    const { container } = render(<TypingIndicator visible />);
    const dots = container.querySelectorAll("[data-testid='typing-dot']");
    // At least one dot should have the bounce animation class
    expect(dots[0].className).toContain("animate-bounce");
  });
});
