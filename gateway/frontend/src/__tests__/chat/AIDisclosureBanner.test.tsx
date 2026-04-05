/**
 * AIDisclosureBanner.test.tsx — AI disclosure compliance component tests
 *
 * Oregon SB 1546 + FTC AI disclosure compliance.
 * 18 tests covering: rendering, content, styling, dismissal, session keying,
 * accessibility (role/aria), and storage edge cases.
 *
 * Run: npx vitest run src/__tests__/chat/AIDisclosureBanner.test.tsx
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AIDisclosureBanner } from "../../components/chat/AIDisclosureBanner";

// ---------------------------------------------------------------------------
// localStorage mock helpers
// ---------------------------------------------------------------------------

function mockLocalStorage() {
  const store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => { store[key] = value; }),
    removeItem: vi.fn((key: string) => { delete store[key]; }),
    clear: vi.fn(() => { Object.keys(store).forEach((k) => delete store[k]); }),
    store,
  };
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

describe("AIDisclosureBanner — rendering", () => {
  let ls: ReturnType<typeof mockLocalStorage>;

  beforeEach(() => {
    ls = mockLocalStorage();
    vi.stubGlobal("localStorage", ls);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the banner when sessionId is provided and not dismissed", () => {
    render(<AIDisclosureBanner sessionId="session-abc" />);
    expect(screen.getByTestId("ai-disclosure-banner")).toBeTruthy();
  });

  it("renders the banner when sessionId is null (no active session yet)", () => {
    render(<AIDisclosureBanner sessionId={null} />);
    expect(screen.getByTestId("ai-disclosure-banner")).toBeTruthy();
  });

  it("contains the required disclosure text about AI", () => {
    render(<AIDisclosureBanner sessionId="session-abc" />);
    const banner = screen.getByTestId("ai-disclosure-banner");
    expect(banner.textContent).toContain("AI assistant");
    expect(banner.textContent).toContain("not a human");
  });

  it("contains 'AI Notice' label text", () => {
    render(<AIDisclosureBanner sessionId="session-abc" />);
    expect(screen.getByText(/AI Notice/i)).toBeTruthy();
  });

  it("renders a dismiss button", () => {
    render(<AIDisclosureBanner sessionId="session-abc" />);
    expect(
      screen.getByRole("button", { name: /dismiss ai disclosure/i })
    ).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Accessibility
// ---------------------------------------------------------------------------

describe("AIDisclosureBanner — accessibility", () => {
  let ls: ReturnType<typeof mockLocalStorage>;

  beforeEach(() => {
    ls = mockLocalStorage();
    vi.stubGlobal("localStorage", ls);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("has role='status' for screen reader announcement", () => {
    render(<AIDisclosureBanner sessionId="session-abc" />);
    const banner = screen.getByRole("status");
    expect(banner).toBeTruthy();
  });

  it("has aria-live='polite' on the banner element", () => {
    render(<AIDisclosureBanner sessionId="session-abc" />);
    const banner = screen.getByTestId("ai-disclosure-banner");
    expect(banner.getAttribute("aria-live")).toBe("polite");
  });

  it("has a descriptive aria-label on the banner", () => {
    render(<AIDisclosureBanner sessionId="session-abc" />);
    const banner = screen.getByTestId("ai-disclosure-banner");
    expect(banner.getAttribute("aria-label")).toBeTruthy();
    expect(banner.getAttribute("aria-label")).toContain("disclosure");
  });

  it("dismiss button has an accessible aria-label", () => {
    render(<AIDisclosureBanner sessionId="session-abc" />);
    const btn = screen.getByRole("button", { name: /dismiss/i });
    expect(btn.getAttribute("aria-label")).toBeTruthy();
  });

  it("paragraph text is present and readable (semantic p element)", () => {
    const { container } = render(<AIDisclosureBanner sessionId="session-abc" />);
    const p = container.querySelector("p");
    expect(p).not.toBeNull();
    expect(p!.textContent).toContain("AI assistant");
  });
});

// ---------------------------------------------------------------------------
// Dismissal behaviour
// ---------------------------------------------------------------------------

describe("AIDisclosureBanner — dismissal", () => {
  let ls: ReturnType<typeof mockLocalStorage>;

  beforeEach(() => {
    ls = mockLocalStorage();
    vi.stubGlobal("localStorage", ls);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("hides the banner after clicking the dismiss button", () => {
    const { queryByTestId } = render(
      <AIDisclosureBanner sessionId="session-abc" />
    );

    const btn = screen.getByRole("button", { name: /dismiss/i });
    fireEvent.click(btn);

    expect(queryByTestId("ai-disclosure-banner")).toBeNull();
  });

  it("persists dismissal to localStorage with correct key", () => {
    render(<AIDisclosureBanner sessionId="session-abc" />);

    fireEvent.click(screen.getByRole("button", { name: /dismiss/i }));

    expect(ls.setItem).toHaveBeenCalledWith(
      "dd_ai_disclosure_dismissed_session-abc",
      "1"
    );
  });

  it("does not call localStorage.setItem when sessionId is null on dismiss", () => {
    render(<AIDisclosureBanner sessionId={null} />);

    fireEvent.click(screen.getByRole("button", { name: /dismiss/i }));

    expect(ls.setItem).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Session keying — re-appears on new sessions
// ---------------------------------------------------------------------------

describe("AIDisclosureBanner — session keying", () => {
  let ls: ReturnType<typeof mockLocalStorage>;

  beforeEach(() => {
    ls = mockLocalStorage();
    vi.stubGlobal("localStorage", ls);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("stays hidden when localStorage shows prior dismissal for same session", () => {
    // Pre-seed dismissal for session-xyz
    ls.store["dd_ai_disclosure_dismissed_session-xyz"] = "1";

    const { queryByTestId } = render(
      <AIDisclosureBanner sessionId="session-xyz" />
    );

    expect(queryByTestId("ai-disclosure-banner")).toBeNull();
  });

  it("re-renders visible when sessionId changes to a new un-dismissed session", () => {
    // Pre-seed dismissal only for session-old
    ls.store["dd_ai_disclosure_dismissed_session-old"] = "1";

    const { queryByTestId, rerender } = render(
      <AIDisclosureBanner sessionId="session-old" />
    );

    // Old session — banner hidden
    expect(queryByTestId("ai-disclosure-banner")).toBeNull();

    // Switch to a new session that has never been dismissed
    rerender(<AIDisclosureBanner sessionId="session-new" />);

    // New session — banner visible again
    expect(queryByTestId("ai-disclosure-banner")).not.toBeNull();
  });

  it("resets to visible when sessionId changes from non-null to null", () => {
    ls.store["dd_ai_disclosure_dismissed_session-old"] = "1";

    const { queryByTestId, rerender } = render(
      <AIDisclosureBanner sessionId="session-old" />
    );
    expect(queryByTestId("ai-disclosure-banner")).toBeNull();

    rerender(<AIDisclosureBanner sessionId={null} />);
    expect(queryByTestId("ai-disclosure-banner")).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

describe("AIDisclosureBanner — edge cases", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders gracefully when localStorage throws on getItem (private mode)", () => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => { throw new Error("SecurityError"); }),
      setItem: vi.fn(() => { throw new Error("SecurityError"); }),
    });

    // Should not throw; banner should still render
    const { queryByTestId } = render(
      <AIDisclosureBanner sessionId="session-abc" />
    );
    expect(queryByTestId("ai-disclosure-banner")).not.toBeNull();
  });

  it("renders gracefully when localStorage throws on setItem during dismiss", () => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => null),
      setItem: vi.fn(() => { throw new Error("QuotaExceededError"); }),
    });

    render(<AIDisclosureBanner sessionId="session-abc" />);

    // Clicking dismiss should not throw
    expect(() => {
      fireEvent.click(screen.getByRole("button", { name: /dismiss/i }));
    }).not.toThrow();
  });

  it("accepts an optional className prop without errors", () => {
    const ls2 = mockLocalStorage();
    vi.stubGlobal("localStorage", ls2);

    const { queryByTestId } = render(
      <AIDisclosureBanner sessionId="session-abc" className="mt-2 custom-class" />
    );
    expect(queryByTestId("ai-disclosure-banner")).not.toBeNull();
  });
});
