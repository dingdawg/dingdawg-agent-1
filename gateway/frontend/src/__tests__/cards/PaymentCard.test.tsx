/**
 * PaymentCard.test.tsx — Chat payment display card tests (TDD RED phase)
 *
 * 8 tests covering amount display, currency formatting, status states, and callbacks.
 *
 * Run: npx vitest run src/__tests__/cards/PaymentCard.test.tsx
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PaymentCard } from "../../components/chat/cards/PaymentCard";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PaymentCard", () => {
  it("renders the amount and description", () => {
    render(
      <PaymentCard
        amount={2999}
        currency="USD"
        description="Monthly subscription"
        onPay={vi.fn()}
        status="pending"
      />
    );

    expect(screen.getByText("Monthly subscription")).toBeTruthy();
    // Amount appears in multiple places (header + button) — use getAllByText
    const amountEls = screen.getAllByText(/29\.99/);
    expect(amountEls.length).toBeGreaterThan(0);
  });

  it("formats USD currency correctly (cents to dollars)", () => {
    render(
      <PaymentCard
        amount={1050}
        currency="USD"
        description="Service fee"
        onPay={vi.fn()}
        status="pending"
      />
    );

    // 1050 cents = $10.50 — may appear in header + button
    const amountEls = screen.getAllByText(/10\.50/);
    expect(amountEls.length).toBeGreaterThan(0);
  });

  it("calls onPay callback when Pay button is clicked in pending state", () => {
    const onPay = vi.fn();
    render(
      <PaymentCard
        amount={500}
        currency="USD"
        description="Test"
        onPay={onPay}
        status="pending"
      />
    );

    const payBtn = screen.getByRole("button");
    fireEvent.click(payBtn);
    expect(onPay).toHaveBeenCalledOnce();
  });

  it("shows a spinner/loading indicator during processing status", () => {
    const { container } = render(
      <PaymentCard
        amount={1000}
        currency="USD"
        description="Processing..."
        onPay={vi.fn()}
        status="processing"
      />
    );

    // Spinner: an element with role='status', or an aria-label, or a class indicating spin
    const spinner =
      container.querySelector("[role='status']") ||
      container.querySelector(".animate-spin") ||
      container.querySelector("[aria-label*='process']") ||
      container.querySelector("[aria-label*='loading']");

    expect(spinner).not.toBeNull();
  });

  it("shows a check mark / success indicator when status is completed", () => {
    const { container } = render(
      <PaymentCard
        amount={1000}
        currency="USD"
        description="Order total"
        onPay={vi.fn()}
        status="completed"
      />
    );

    // Success state: check icon or "Paid"/"Successful" text — may appear multiple times
    const successTexts =
      screen.queryAllByText(/paid/i).length > 0 ||
      screen.queryAllByText(/completed/i).length > 0 ||
      screen.queryAllByText(/success/i).length > 0;
    const checkIcon = container.querySelector("[data-status='completed']");

    expect(successTexts || checkIcon).toBeTruthy();
  });

  it("shows an error indicator when status is failed", () => {
    const { container } = render(
      <PaymentCard
        amount={1000}
        currency="USD"
        description="Order total"
        onPay={vi.fn()}
        status="failed"
      />
    );

    // Error state: "declined" / error indicator — use queryAllByText to handle multiple matches
    const declinedText = screen.queryAllByText(/declined/i);
    const failText = screen.queryAllByText(/fail/i);
    const errorEl = container.querySelector("[data-status='failed']");

    expect(
      declinedText.length > 0 || failText.length > 0 || errorEl !== null
    ).toBe(true);
  });

  it("pay button is disabled when status is processing", () => {
    render(
      <PaymentCard
        amount={500}
        currency="USD"
        description="Processing"
        onPay={vi.fn()}
        status="processing"
      />
    );

    // Either button doesn't exist or is disabled
    const btn = screen.queryByRole("button");
    if (btn) {
      expect(btn).toHaveAttribute("disabled");
    }
    // If no button rendered in processing state, test passes inherently
  });

  it("applies pending status styling with blue accent", () => {
    const { container } = render(
      <PaymentCard
        amount={750}
        currency="USD"
        description="Pending payment"
        onPay={vi.fn()}
        status="pending"
      />
    );

    // Status indicator element should have blue styling
    const statusEl =
      container.querySelector("[data-status='pending']") ||
      container.querySelector(".text-blue-400") ||
      container.querySelector(".bg-blue-500\\/15") ||
      container.querySelector("[class*='blue']");

    expect(statusEl).not.toBeNull();
  });
});
