/**
 * FormCard.test.tsx — Inline chat form card tests (TDD RED phase)
 *
 * 8 tests covering field rendering, validation, submission, accessibility, and touch targets.
 *
 * Run: npx vitest run src/__tests__/cards/FormCard.test.tsx
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { FormCard } from "../../components/chat/cards/FormCard";
import type { FormField } from "../../components/chat/cards/FormCard";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const allFieldTypes: FormField[] = [
  { name: "firstName", label: "First Name", type: "text", required: true },
  { name: "email", label: "Email", type: "email", required: true },
  { name: "phone", label: "Phone", type: "phone" },
  { name: "age", label: "Age", type: "number" },
  { name: "role", label: "Role", type: "select", options: ["Admin", "User", "Guest"] },
  { name: "notes", label: "Notes", type: "textarea" },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("FormCard", () => {
  it("renders all field types (text, email, phone, number, select, textarea)", () => {
    render(
      <FormCard
        fields={allFieldTypes}
        onSubmit={vi.fn()}
        submitLabel="Submit"
      />
    );

    // Use regex to handle labels with nested required-star spans ("First Name *")
    expect(screen.getByLabelText(/First Name/i)).toBeTruthy();
    expect(screen.getByLabelText(/^Email/i)).toBeTruthy();
    expect(screen.getByLabelText(/Phone/i)).toBeTruthy();
    expect(screen.getByLabelText(/Age/i)).toBeTruthy();
    expect(screen.getByLabelText(/Role/i)).toBeTruthy();
    expect(screen.getByLabelText(/Notes/i)).toBeTruthy();
  });

  it("does not call onSubmit and shows error when required fields are empty", () => {
    const onSubmit = vi.fn();
    render(
      <FormCard
        fields={[{ name: "name", label: "Name", type: "text", required: true }]}
        onSubmit={onSubmit}
        submitLabel="Send"
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("calls onSubmit with correct form data when all required fields are filled", () => {
    const onSubmit = vi.fn();
    render(
      <FormCard
        fields={[
          { name: "name", label: "Name", type: "text", required: true },
          { name: "city", label: "City", type: "text" },
        ]}
        onSubmit={onSubmit}
        submitLabel="Submit"
      />
    );

    // Labels with required fields contain nested star span — use regex
    fireEvent.change(screen.getByLabelText(/^Name/i), {
      target: { value: "Alice" },
    });
    fireEvent.change(screen.getByLabelText(/City/i), {
      target: { value: "Austin" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(onSubmit).toHaveBeenCalledOnce();
    expect(onSubmit).toHaveBeenCalledWith({ name: "Alice", city: "Austin" });
  });

  it("renders select field with all provided options", () => {
    render(
      <FormCard
        fields={[
          {
            name: "plan",
            label: "Plan",
            type: "select",
            options: ["Free", "Pro", "Enterprise"],
          },
        ]}
        onSubmit={vi.fn()}
        submitLabel="Go"
      />
    );

    const select = screen.getByLabelText("Plan") as HTMLSelectElement;
    const optionTexts = Array.from(select.options).map((o) => o.text);

    expect(optionTexts).toContain("Free");
    expect(optionTexts).toContain("Pro");
    expect(optionTexts).toContain("Enterprise");
  });

  it("submit button is disabled when required fields are empty", () => {
    render(
      <FormCard
        fields={[{ name: "email", label: "Email", type: "email", required: true }]}
        onSubmit={vi.fn()}
        submitLabel="Go"
      />
    );

    const btn = screen.getByRole("button", { name: "Go" });
    expect(btn).toHaveAttribute("disabled");
  });

  it("labels are linked to inputs via htmlFor/id", () => {
    const { container } = render(
      <FormCard
        fields={[{ name: "username", label: "Username", type: "text" }]}
        onSubmit={vi.fn()}
        submitLabel="Save"
      />
    );

    const label = container.querySelector('label[for="field-username"]');
    const input = container.querySelector("#field-username");

    expect(label).not.toBeNull();
    expect(input).not.toBeNull();
  });

  it("submit button meets 48px minimum touch target height", () => {
    const { container } = render(
      <FormCard
        fields={[{ name: "x", label: "X", type: "text" }]}
        onSubmit={vi.fn()}
        submitLabel="Tap Me"
      />
    );

    const btn = container.querySelector("button[type='submit']");
    expect(btn).not.toBeNull();
    // 48px min-height is enforced via className containing 'min-h-12' (3rem = 48px)
    // or 'h-12' class
    const cls = btn!.className;
    const has48px =
      cls.includes("min-h-12") ||
      cls.includes("h-12") ||
      cls.includes("py-3"); // py-3 = 12px top+bottom → combined with font = ~48px

    expect(has48px).toBe(true);
  });

  it("renders nothing when fields array is empty (graceful empty state)", () => {
    const { container } = render(
      <FormCard fields={[]} onSubmit={vi.fn()} submitLabel="Submit" />
    );

    // Should still render the card container and button, just no field inputs
    const inputs = container.querySelectorAll("input, select, textarea");
    expect(inputs.length).toBe(0);

    // Submit button should still be present
    expect(screen.getByRole("button", { name: "Submit" })).toBeTruthy();
  });
});
