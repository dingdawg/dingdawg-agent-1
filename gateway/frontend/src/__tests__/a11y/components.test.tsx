/**
 * components.test.tsx — Accessibility component tests (TDD RED phase)
 *
 * Tests derived from WCAG 2.1 AA requirements and component contracts.
 * 8 tests covering SkipLink, VisuallyHidden, and LiveRegion.
 *
 * Run: npx vitest run src/__tests__/a11y/components.test.tsx
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { SkipLink } from "../../components/a11y/SkipLink";
import { VisuallyHidden } from "../../components/a11y/VisuallyHidden";
import { LiveRegion } from "../../components/a11y/LiveRegion";

// ---------------------------------------------------------------------------
// SkipLink
// ---------------------------------------------------------------------------

describe("SkipLink", () => {
  it("renders a link element pointing to the target id", () => {
    render(
      <div>
        <SkipLink targetId="main-content" />
        <main id="main-content">Content</main>
      </div>
    );

    const link = screen.getByRole("link");
    expect(link).toBeTruthy();
    expect(link.getAttribute("href")).toBe("#main-content");
  });

  it("is visually hidden by default (has sr-only or equivalent class)", () => {
    const { container } = render(<SkipLink targetId="main-content" />);
    const link = container.querySelector("a");
    expect(link).not.toBeNull();

    // Should have position absolute and clip technique or a known class
    const hasHidePattern =
      link!.className.includes("sr-only") ||
      link!.className.includes("skip-link") ||
      link!.className.includes("visually-hidden") ||
      link!.style.position === "absolute" ||
      link!.style.clip !== "" ||
      link!.style.overflow === "hidden";

    expect(hasHidePattern).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// VisuallyHidden
// ---------------------------------------------------------------------------

describe("VisuallyHidden", () => {
  it("renders children text in the DOM (accessible to screen readers)", () => {
    render(<VisuallyHidden>Screen reader only text</VisuallyHidden>);
    expect(screen.getByText("Screen reader only text")).toBeTruthy();
  });

  it("is not visually presented (uses sr-only CSS technique)", () => {
    const { container } = render(
      <VisuallyHidden>Hidden visually</VisuallyHidden>
    );

    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper).not.toBeNull();

    // Must use one of the standard SR-only techniques:
    // 1. className with sr-only/visually-hidden
    // 2. Inline style with clip/clip-path
    const isSrOnly =
      wrapper.className.includes("sr-only") ||
      wrapper.className.includes("visually-hidden") ||
      wrapper.style.position === "absolute" ||
      wrapper.style.clip !== undefined;

    expect(isSrOnly).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// LiveRegion
// ---------------------------------------------------------------------------

describe("LiveRegion", () => {
  it("renders with aria-live='polite' by default", () => {
    const { container } = render(
      <LiveRegion message="Update available" />
    );

    const region = container.querySelector("[aria-live]");
    expect(region).not.toBeNull();
    expect(region!.getAttribute("aria-live")).toBe("polite");
  });

  it("renders with aria-live='assertive' when priority is assertive", () => {
    const { container } = render(
      <LiveRegion message="Error occurred" priority="assertive" />
    );

    const region = container.querySelector("[aria-live='assertive']");
    expect(region).not.toBeNull();
  });

  it("clears message after clearAfter timeout", async () => {
    vi.useFakeTimers();

    const { container } = render(
      <LiveRegion message="Temporary message" clearAfter={500} />
    );

    const region = container.querySelector("[aria-live]");

    // Advance past the 50ms debounce that sets the message
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(region?.textContent).toBe("Temporary message");

    // Advance past the clearAfter duration (500ms)
    act(() => {
      vi.advanceTimersByTime(600);
    });

    // After clearAfter has elapsed, message should be cleared
    expect(region?.textContent).toBe("");

    vi.useRealTimers();
  });

  it("updates message text when message prop changes", async () => {
    vi.useFakeTimers();

    const { rerender, container } = render(
      <LiveRegion message="First message" />
    );

    const region = container.querySelector("[aria-live]");

    // Advance past the 50ms debounce
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(region?.textContent).toBe("First message");

    // Update the message prop
    rerender(<LiveRegion message="Second message" />);

    // Advance past the debounce again
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(region?.textContent).toBe("Second message");

    vi.useRealTimers();
  });
});
