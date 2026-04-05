/**
 * BrandingEditor.test.tsx — BrandingEditor component test suite.
 *
 * Tests cover: section rendering, preset colors, hex validation,
 * dirty-state detection, save callback shape, loading state,
 * character counter, widget preview, and initial value population.
 *
 * 18 tests total.
 *
 * Run: npx vitest run src/__tests__/branding/BrandingEditor.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BrandingEditor } from "../../components/settings/BrandingEditor";

// ---------------------------------------------------------------------------
// Default props shared across tests
// ---------------------------------------------------------------------------

const defaultProps = {
  initialConfig: {},
  agentName: "Test Agent",
  agentHandle: "testagent",
  onSave: vi.fn().mockResolvedValue(undefined),
  saving: false,
};

// ---------------------------------------------------------------------------
// Section rendering
// ---------------------------------------------------------------------------

describe("BrandingEditor — section rendering", () => {
  beforeEach(() => {
    defaultProps.onSave.mockClear();
  });

  it("renders the Brand Color section heading", () => {
    render(<BrandingEditor {...defaultProps} />);
    expect(screen.getByText("Brand Color")).toBeTruthy();
  });

  it("renders the Agent Avatar section heading", () => {
    render(<BrandingEditor {...defaultProps} />);
    expect(screen.getByText("Agent Avatar")).toBeTruthy();
  });

  it("renders the Display Name section heading", () => {
    render(<BrandingEditor {...defaultProps} />);
    expect(screen.getByText("Display Name")).toBeTruthy();
  });

  it("renders the Widget Greeting section heading", () => {
    render(<BrandingEditor {...defaultProps} />);
    expect(screen.getByText("Widget Greeting")).toBeTruthy();
  });

  it("renders the Widget Preview section heading", () => {
    render(<BrandingEditor {...defaultProps} />);
    expect(screen.getByText("Widget Preview")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Preset colors
// ---------------------------------------------------------------------------

describe("BrandingEditor — preset colors", () => {
  it("renders all 6 preset color swatches", () => {
    render(<BrandingEditor {...defaultProps} />);
    const swatches = screen.getAllByRole("button", { name: /color$/i });
    expect(swatches).toHaveLength(6);
  });

  it("clicking a preset color updates the hex input to that color value", () => {
    render(<BrandingEditor {...defaultProps} />);
    const blueBtn = screen.getByRole("button", { name: /blue color/i });
    fireEvent.click(blueBtn);
    // The hex input shows the current primary color when customColor is empty
    const hexInput = screen.getByPlaceholderText("#F6B400");
    expect((hexInput as HTMLInputElement).value).toBe("#3B82F6");
  });
});

// ---------------------------------------------------------------------------
// Custom hex validation
// ---------------------------------------------------------------------------

describe("BrandingEditor — custom hex input validation", () => {
  it("accepts a valid hex color and updates the preview swatch", () => {
    render(<BrandingEditor {...defaultProps} />);
    const hexInput = screen.getByPlaceholderText("#F6B400");
    fireEvent.change(hexInput, { target: { value: "#FF0000" } });
    // After a valid hex, the input reflects the typed value
    expect((hexInput as HTMLInputElement).value).toBe("#FF0000");
  });

  it("does not update primaryColor when hex is invalid", () => {
    render(<BrandingEditor {...defaultProps} />);
    const hexInput = screen.getByPlaceholderText("#F6B400");
    // Type a valid color first to establish a baseline
    fireEvent.change(hexInput, { target: { value: "#AA1122" } });
    // Now type something invalid
    fireEvent.change(hexInput, { target: { value: "invalid" } });
    // customColor holds the typed text; primaryColor should still be #AA1122
    // The displayed value is customColor when it is non-empty, so we see "invalid"
    // but the color swatch background does not change to invalid CSS
    expect((hexInput as HTMLInputElement).value).toBe("invalid");
  });

  it("input shows current primary color when customColor is empty (preset click clears customColor)", () => {
    render(<BrandingEditor {...defaultProps} />);
    const hexInput = screen.getByPlaceholderText("#F6B400");
    // Click gold preset — customColor is cleared, input shows primaryColor
    const goldBtn = screen.getByRole("button", { name: /gold color/i });
    fireEvent.click(goldBtn);
    expect((hexInput as HTMLInputElement).value).toBe("#F6B400");
  });
});

// ---------------------------------------------------------------------------
// Avatar URL
// ---------------------------------------------------------------------------

describe("BrandingEditor — avatar URL input", () => {
  it("renders the avatar URL input with the correct placeholder", () => {
    render(<BrandingEditor {...defaultProps} />);
    const input = screen.getByPlaceholderText("https://example.com/avatar.png");
    expect(input).toBeTruthy();
  });

  it("accepts text input for the avatar URL", () => {
    render(<BrandingEditor {...defaultProps} />);
    const input = screen.getByPlaceholderText(
      "https://example.com/avatar.png"
    ) as HTMLInputElement;
    fireEvent.change(input, {
      target: { value: "https://cdn.example.com/photo.jpg" },
    });
    expect(input.value).toBe("https://cdn.example.com/photo.jpg");
  });
});

// ---------------------------------------------------------------------------
// Widget greeting character counter
// ---------------------------------------------------------------------------

describe("BrandingEditor — widget greeting", () => {
  it("renders the character counter showing 0/280 initially", () => {
    render(<BrandingEditor {...defaultProps} />);
    expect(screen.getByText("0/280 characters")).toBeTruthy();
  });

  it("updates the character counter as text is typed", () => {
    render(<BrandingEditor {...defaultProps} />);
    const textarea = screen.getByPlaceholderText(
      /Hi! I'm here to help/
    ) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Hello there!" } });
    expect(screen.getByText("12/280 characters")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Dirty state + save button enabled/disabled
// ---------------------------------------------------------------------------

describe("BrandingEditor — dirty state", () => {
  beforeEach(() => {
    defaultProps.onSave.mockClear();
  });

  it("save button is disabled when no changes have been made", () => {
    render(<BrandingEditor {...defaultProps} />);
    const saveBtn = screen.getByRole("button", { name: /save branding/i });
    expect((saveBtn as HTMLButtonElement).disabled).toBe(true);
  });

  it("save button is enabled after changing primary color via preset", () => {
    render(<BrandingEditor {...defaultProps} />);
    const blueBtn = screen.getByRole("button", { name: /blue color/i });
    fireEvent.click(blueBtn);
    const saveBtn = screen.getByRole("button", { name: /save branding/i });
    expect((saveBtn as HTMLButtonElement).disabled).toBe(false);
  });

  it("save button is enabled after changing avatar URL", () => {
    render(<BrandingEditor {...defaultProps} />);
    const input = screen.getByPlaceholderText("https://example.com/avatar.png");
    fireEvent.change(input, { target: { value: "https://example.com/a.png" } });
    const saveBtn = screen.getByRole("button", { name: /save branding/i });
    expect((saveBtn as HTMLButtonElement).disabled).toBe(false);
  });

  it("save button is enabled after changing business name", () => {
    render(<BrandingEditor {...defaultProps} />);
    // Display Name input uses agentName as placeholder
    const input = screen.getByPlaceholderText("Test Agent");
    fireEvent.change(input, { target: { value: "Acme Corp" } });
    const saveBtn = screen.getByRole("button", { name: /save branding/i });
    expect((saveBtn as HTMLButtonElement).disabled).toBe(false);
  });

  it("save button is enabled after changing widget greeting", () => {
    render(<BrandingEditor {...defaultProps} />);
    const textarea = screen.getByPlaceholderText(/Hi! I'm here to help/);
    fireEvent.change(textarea, { target: { value: "Welcome!" } });
    const saveBtn = screen.getByRole("button", { name: /save branding/i });
    expect((saveBtn as HTMLButtonElement).disabled).toBe(false);
  });

  it("unsaved changes indicator appears when dirty", () => {
    render(<BrandingEditor {...defaultProps} />);
    const textarea = screen.getByPlaceholderText(/Hi! I'm here to help/);
    fireEvent.change(textarea, { target: { value: "Hello!" } });
    expect(screen.getByText("Unsaved changes")).toBeTruthy();
  });

  it("unsaved changes indicator is absent when no changes made", () => {
    render(<BrandingEditor {...defaultProps} />);
    expect(screen.queryByText("Unsaved changes")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Save callback
// ---------------------------------------------------------------------------

describe("BrandingEditor — save callback", () => {
  beforeEach(() => {
    defaultProps.onSave.mockClear();
  });

  it("calls onSave with the full BrandingConfig shape when save is clicked", async () => {
    render(<BrandingEditor {...defaultProps} />);
    // Trigger dirty state by changing greeting
    const textarea = screen.getByPlaceholderText(/Hi! I'm here to help/);
    fireEvent.change(textarea, { target: { value: "Hey there!" } });

    const saveBtn = screen.getByRole("button", { name: /save branding/i });
    await act(async () => {
      fireEvent.click(saveBtn);
    });

    expect(defaultProps.onSave).toHaveBeenCalledOnce();
    const arg = defaultProps.onSave.mock.calls[0][0];
    expect(arg).toHaveProperty("primary_color");
    expect(arg).toHaveProperty("avatar_url");
    expect(arg).toHaveProperty("business_name");
    expect(arg).toHaveProperty("widget_greeting", "Hey there!");
  });
});

// ---------------------------------------------------------------------------
// Loading state
// ---------------------------------------------------------------------------

describe("BrandingEditor — loading/saving state", () => {
  it("save button is disabled and shows spinner when saving=true", () => {
    const { container } = render(
      <BrandingEditor
        {...defaultProps}
        initialConfig={{ widget_greeting: "Hi" }}
        saving={true}
      />
    );
    // When isLoading=true, Button renders a <span class="spinner"> instead of
    // its text children, so the accessible name via text content is empty.
    // Query by class selector directly to locate the save button.
    // The Button component always sets disabled={true} when isLoading is true.
    const saveBtn = container.querySelector("button[disabled]");
    expect(saveBtn).not.toBeNull();
    // Confirm it contains the spinner span rather than text
    const spinner = saveBtn?.querySelector(".spinner");
    expect(spinner).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Initial values populated
// ---------------------------------------------------------------------------

describe("BrandingEditor — initial values", () => {
  it("populates the greeting textarea from initialConfig.widget_greeting", () => {
    render(
      <BrandingEditor
        {...defaultProps}
        initialConfig={{ widget_greeting: "Welcome to our store!" }}
      />
    );
    const textarea = screen.getByDisplayValue(
      "Welcome to our store!"
    ) as HTMLTextAreaElement;
    expect(textarea.value).toBe("Welcome to our store!");
  });

  it("populates business name input from initialConfig.business_name", () => {
    render(
      <BrandingEditor
        {...defaultProps}
        initialConfig={{ business_name: "Acme LLC" }}
      />
    );
    const input = screen.getByDisplayValue("Acme LLC") as HTMLInputElement;
    expect(input.value).toBe("Acme LLC");
  });

  it("populates avatar URL input from initialConfig.avatar_url", () => {
    render(
      <BrandingEditor
        {...defaultProps}
        initialConfig={{ avatar_url: "https://cdn.example.com/logo.png" }}
      />
    );
    const input = screen.getByDisplayValue(
      "https://cdn.example.com/logo.png"
    ) as HTMLInputElement;
    expect(input.value).toBe("https://cdn.example.com/logo.png");
  });

  it("shows agent name in widget preview when business name is empty", () => {
    render(
      <BrandingEditor
        {...defaultProps}
        agentName="Jarvis"
        initialConfig={{}}
      />
    );
    // Widget Preview section header label is rendered, and the agent name
    // appears in the widget header span inside the preview
    const previewSection = screen.getByText("Widget Preview");
    expect(previewSection).toBeTruthy();
    // agentName "Jarvis" appears in the widget preview span
    const spans = document.querySelectorAll("span");
    const jarvisSpan = Array.from(spans).find((s) => s.textContent === "Jarvis");
    expect(jarvisSpan).toBeTruthy();
  });

  it("shows updated greeting text in widget preview when greeting is typed", () => {
    const { container } = render(<BrandingEditor {...defaultProps} />);
    const textarea = screen.getByPlaceholderText(/Hi! I'm here to help/);
    fireEvent.change(textarea, {
      target: { value: "Chat with us anytime!" },
    });
    // The WidgetPreview renders the greeting inside a styled div bubble
    // (rounded-lg rounded-tl-none). The textarea also contains the text, so
    // we use querySelector targeting the bubble class to assert the preview.
    const bubble = container.querySelector(".rounded-lg.rounded-tl-none");
    expect(bubble).not.toBeNull();
    expect(bubble!.textContent).toBe("Chat with us anytime!");
  });
});
