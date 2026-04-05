/**
 * ConfirmationCard.test.tsx — Yes/No decision prompt card tests (TDD RED phase)
 *
 * 6 tests covering title/desc rendering, callbacks, custom labels, danger variant, touch targets.
 *
 * Run: npx vitest run src/__tests__/cards/ConfirmationCard.test.tsx
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ConfirmationCard } from "../../components/chat/cards/ConfirmationCard";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ConfirmationCard", () => {
  it("renders title and optional description", () => {
    render(
      <ConfirmationCard
        title="Delete this agent?"
        description="This action cannot be undone."
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    expect(screen.getByText("Delete this agent?")).toBeTruthy();
    expect(screen.getByText("This action cannot be undone.")).toBeTruthy();
  });

  it("calls onConfirm when the confirm button is clicked", () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmationCard
        title="Confirm action?"
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("calls onCancel when the cancel button is clicked", () => {
    const onCancel = vi.fn();
    render(
      <ConfirmationCard
        title="Are you sure?"
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("renders custom confirmLabel and cancelLabel when provided", () => {
    render(
      <ConfirmationCard
        title="Remove item?"
        confirmLabel="Yes, Remove"
        cancelLabel="Keep It"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    expect(screen.getByRole("button", { name: "Yes, Remove" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Keep It" })).toBeTruthy();
  });

  it("applies red/danger styling to confirm button when variant='danger'", () => {
    const { container } = render(
      <ConfirmationCard
        title="Permanently delete?"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
        variant="danger"
      />
    );

    // The confirm button in danger variant should have red styling
    const confirmBtn = screen.getByRole("button", { name: /confirm|yes|delete/i });
    const cls = confirmBtn.className;

    const hasRedClass =
      cls.includes("red") ||
      cls.includes("danger") ||
      cls.includes("destructive");

    expect(hasRedClass).toBe(true);
  });

  it("buttons meet 48px minimum touch target height", () => {
    const { container } = render(
      <ConfirmationCard
        title="Confirm?"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    const buttons = container.querySelectorAll("button");
    expect(buttons.length).toBe(2);

    buttons.forEach((btn) => {
      const cls = btn.className;
      // 48px = min-h-12 (3rem) OR h-12 OR py-3 (12px top+bottom ~48px total with font)
      const has48px =
        cls.includes("min-h-12") ||
        cls.includes("h-12") ||
        cls.includes("py-3");
      expect(has48px).toBe(true);
    });
  });
});
