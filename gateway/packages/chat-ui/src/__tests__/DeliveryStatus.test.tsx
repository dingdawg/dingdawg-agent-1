/**
 * DeliveryStatus — TDD tests (RED phase written before implementation).
 *
 * Requirements:
 *   - 'sending'   → single gray clock icon, aria-label "Sending"
 *   - 'sent'      → single gray checkmark, aria-label "Sent"
 *   - 'delivered' → double gray checkmark, aria-label "Delivered"
 *   - 'read'      → double blue checkmark, aria-label "Read"
 *   - 'failed'    → red X icon, aria-label "Failed"
 *   - Transitions between states render correct new state
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DeliveryStatus } from "../components/DeliveryStatus";
import type { DeliveryStatus as DeliveryStatusType } from "../types";

describe("DeliveryStatus", () => {
  it("renders 'sending' state with correct aria-label", () => {
    render(<DeliveryStatus status="sending" />);
    expect(screen.getByRole("img", { name: /sending/i })).toBeTruthy();
  });

  it("renders 'sent' state with correct aria-label", () => {
    render(<DeliveryStatus status="sent" />);
    expect(screen.getByRole("img", { name: /sent/i })).toBeTruthy();
  });

  it("renders 'delivered' state with correct aria-label", () => {
    render(<DeliveryStatus status="delivered" />);
    expect(screen.getByRole("img", { name: /delivered/i })).toBeTruthy();
  });

  it("renders 'read' state with correct aria-label and blue color indicator", () => {
    const { container } = render(<DeliveryStatus status="read" />);
    expect(screen.getByRole("img", { name: /read/i })).toBeTruthy();
    // Blue color class on the icon wrapper
    const blueEl = container.querySelector(".text-blue-500");
    expect(blueEl).toBeTruthy();
  });

  it("renders 'failed' state with correct aria-label and red color indicator", () => {
    const { container } = render(<DeliveryStatus status="failed" />);
    expect(screen.getByRole("img", { name: /failed/i })).toBeTruthy();
    const redEl = container.querySelector(".text-red-500");
    expect(redEl).toBeTruthy();
  });
});
