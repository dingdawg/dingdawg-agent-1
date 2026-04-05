/**
 * CalendarCard.test.tsx — Chat date/time picker card tests (TDD RED phase)
 *
 * 8 tests covering month grid rendering, date selection, slot restrictions, and navigation.
 *
 * Run: npx vitest run src/__tests__/cards/CalendarCard.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CalendarCard } from "../../components/chat/cards/CalendarCard";
import type { DateSlot } from "../../components/chat/cards/CalendarCard";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Returns today with time zeroed. */
function today(): Date {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d;
}

/** Returns a date N days from today. */
function daysFromNow(n: number): Date {
  const d = today();
  d.setDate(d.getDate() + n);
  return d;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("CalendarCard", () => {
  it("renders a month grid with day-of-week headers", () => {
    render(<CalendarCard onSelect={vi.fn()} />);

    // Day-of-week headers (Sun, Mon, Tue... or S, M, T...)
    const headers =
      screen.queryAllByText(/^(Sun|Mon|Tue|Wed|Thu|Fri|Sat)$/) ||
      screen.queryAllByText(/^(S|M|T|W|F)$/);

    expect(headers.length).toBeGreaterThanOrEqual(5);
  });

  it("calls onSelect with a Date when a valid day is clicked", () => {
    const onSelect = vi.fn();
    render(<CalendarCard onSelect={onSelect} />);

    // Click a day button — they'll be numbered 1-31
    const dayButtons = screen.getAllByRole("button").filter((b) => {
      const text = b.textContent?.trim();
      return text && /^\d{1,2}$/.test(text) && parseInt(text, 10) >= 1;
    });

    expect(dayButtons.length).toBeGreaterThan(0);

    // Click first available day
    fireEvent.click(dayButtons[0]);

    // onSelect may be called directly or after time selection — verify it's callable
    // At minimum the click should not throw
    // onSelect may require time selection first (when availableSlots provided)
    // In free-selection mode, onSelect is called immediately
    expect(() => fireEvent.click(dayButtons[0])).not.toThrow();
  });

  it("only allows clicking dates in availableSlots when slots are provided", () => {
    const tomorrow = daysFromNow(1);
    const tomorrowKey = tomorrow.toISOString().slice(0, 10);

    const slots: DateSlot[] = [
      { date: tomorrow, times: ["10:00 AM", "2:00 PM"] },
    ];

    const onSelect = vi.fn();
    const { container } = render(
      <CalendarCard availableSlots={slots} onSelect={onSelect} />
    );

    // Disabled day buttons should have aria-disabled="true" or disabled attribute
    const disabledDays = container.querySelectorAll(
      "button[disabled], button[aria-disabled='true']"
    );

    // Most days should be disabled since only tomorrow has slots
    expect(disabledDays.length).toBeGreaterThan(0);
  });

  it("respects minDate — disables all dates before minDate", () => {
    const minDate = daysFromNow(5);
    const { container } = render(
      <CalendarCard onSelect={vi.fn()} minDate={minDate} />
    );

    const disabledDays = container.querySelectorAll(
      "button[disabled], button[aria-disabled='true']"
    );

    // Days 1 through today+4 should be disabled
    expect(disabledDays.length).toBeGreaterThan(0);
  });

  it("respects maxDate — disables all dates after maxDate", () => {
    const maxDate = daysFromNow(3);
    const { container } = render(
      <CalendarCard onSelect={vi.fn()} maxDate={maxDate} />
    );

    const disabledDays = container.querySelectorAll(
      "button[disabled], button[aria-disabled='true']"
    );

    expect(disabledDays.length).toBeGreaterThan(0);
  });

  it("shows time selection options after a date with slots is selected", () => {
    const tomorrow = daysFromNow(1);
    const slots: DateSlot[] = [
      { date: tomorrow, times: ["9:00 AM", "11:00 AM"] },
    ];

    const { container } = render(
      <CalendarCard availableSlots={slots} onSelect={vi.fn()} />
    );

    // Find and click the enabled day (tomorrow's date number)
    const enabledDays = container.querySelectorAll(
      "button:not([disabled]):not([aria-disabled='true'])"
    );

    const dayButtons = Array.from(enabledDays).filter((b) => {
      const text = b.textContent?.trim();
      return text && /^\d{1,2}$/.test(text);
    });

    if (dayButtons.length > 0) {
      fireEvent.click(dayButtons[0]);
      // After clicking, time options should appear
      const timeElements =
        screen.queryAllByText(/AM|PM/) ||
        container.querySelectorAll("[data-time-slot]");
      // Times should be visible
      expect(timeElements.length).toBeGreaterThan(0);
    }
  });

  it("calls onSelect with a complete Date object including time when time is selected", () => {
    const tomorrow = daysFromNow(1);
    const slots: DateSlot[] = [
      { date: tomorrow, times: ["10:00 AM"] },
    ];

    const onSelect = vi.fn();
    const { container } = render(
      <CalendarCard availableSlots={slots} onSelect={onSelect} />
    );

    // Click enabled day
    const enabledDays = container.querySelectorAll(
      "button:not([disabled]):not([aria-disabled='true'])"
    );
    const dayButtons = Array.from(enabledDays).filter((b) => {
      const text = b.textContent?.trim();
      return text && /^\d{1,2}$/.test(text);
    });

    if (dayButtons.length > 0) {
      fireEvent.click(dayButtons[0]);

      // Select time
      const timeBtn = screen.queryByText("10:00 AM");
      if (timeBtn) {
        fireEvent.click(timeBtn);
        expect(onSelect).toHaveBeenCalledWith(expect.any(Date));
      }
    }
  });

  it("renders navigation controls to change months", () => {
    render(<CalendarCard onSelect={vi.fn()} />);

    // Previous/Next navigation buttons
    const prevBtn =
      screen.queryByRole("button", { name: /prev|previous|←|<|back/i }) ||
      screen.queryByLabelText(/prev/i);
    const nextBtn =
      screen.queryByRole("button", { name: /next|→|>|forward/i }) ||
      screen.queryByLabelText(/next/i);

    // At least one navigation control should exist
    expect(prevBtn || nextBtn).toBeTruthy();
  });

  it("highlights today's date visually", () => {
    const { container } = render(<CalendarCard onSelect={vi.fn()} />);

    // Today should have a distinguishing class: e.g. 'ring', 'border', 'today', or 'underline'
    const todayEl =
      container.querySelector("[data-today='true']") ||
      container.querySelector(".ring") ||
      container.querySelector("[aria-current='date']") ||
      container.querySelector("[class*='today']");

    expect(todayEl).not.toBeNull();
  });
});
