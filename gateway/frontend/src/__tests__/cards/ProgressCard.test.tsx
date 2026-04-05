/**
 * ProgressCard.test.tsx — Order/task progress timeline card tests (TDD RED phase)
 *
 * 6 tests covering step rendering, current step highlighting, timestamps, and edge cases.
 *
 * Run: npx vitest run src/__tests__/cards/ProgressCard.test.tsx
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProgressCard } from "../../components/chat/cards/ProgressCard";
import type { ProgressStep } from "../../components/chat/cards/ProgressCard";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const steps: ProgressStep[] = [
  { label: "Order Placed", status: "completed", timestamp: new Date("2026-03-05T09:00:00") },
  { label: "Payment Confirmed", status: "completed", timestamp: new Date("2026-03-05T09:01:00") },
  { label: "Preparing", status: "active" },
  { label: "Ready for Pickup", status: "pending" },
  { label: "Delivered", status: "pending" },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ProgressCard", () => {
  it("renders all steps with their labels", () => {
    render(<ProgressCard steps={steps} currentStep={2} />);

    expect(screen.getByText("Order Placed")).toBeTruthy();
    expect(screen.getByText("Payment Confirmed")).toBeTruthy();
    expect(screen.getByText("Preparing")).toBeTruthy();
    expect(screen.getByText("Ready for Pickup")).toBeTruthy();
    expect(screen.getByText("Delivered")).toBeTruthy();
  });

  it("visually highlights the current/active step differently from others", () => {
    const { container } = render(
      <ProgressCard steps={steps} currentStep={2} />
    );

    // Active step should have a blue or highlight indicator
    // Look for an element with a 'active' class or blue color class near the active step text
    const activeEl =
      container.querySelector("[data-status='active']") ||
      container.querySelector(".text-blue-400") ||
      container.querySelector("[class*='active']") ||
      container.querySelector(".bg-blue-500");

    expect(activeEl).not.toBeNull();
  });

  it("renders completed steps with a check mark icon", () => {
    const { container } = render(
      <ProgressCard steps={steps} currentStep={2} />
    );

    // Completed steps should show check icons — data-status="completed" or SVG with check
    const completedEls = container.querySelectorAll("[data-status='completed']");
    expect(completedEls.length).toBe(2); // "Order Placed" and "Payment Confirmed"
  });

  it("formats and displays timestamps on steps that have them", () => {
    render(<ProgressCard steps={steps} currentStep={2} />);

    // "Order Placed" step has timestamp — some formatted version should be visible
    // Format can be "9:00 AM", "09:00", or similar
    const timeTexts =
      screen.queryAllByText(/\d{1,2}:\d{2}/) ||
      screen.queryAllByText(/AM|PM/);

    expect(timeTexts.length).toBeGreaterThan(0);
  });

  it("renders the optional title above the step list", () => {
    render(
      <ProgressCard
        steps={steps}
        currentStep={2}
        title="Order #12345 Status"
      />
    );

    expect(screen.getByText("Order #12345 Status")).toBeTruthy();
  });

  it("handles a single step edge case without error", () => {
    const singleStep: ProgressStep[] = [
      { label: "Processing", status: "active" },
    ];

    const { container } = render(
      <ProgressCard steps={singleStep} currentStep={0} />
    );

    expect(screen.getByText("Processing")).toBeTruthy();
    // Should render without crashing
    expect(container.firstChild).not.toBeNull();
  });
});
