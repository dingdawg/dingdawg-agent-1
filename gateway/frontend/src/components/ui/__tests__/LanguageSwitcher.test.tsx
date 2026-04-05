// @vitest-environment jsdom

/**
 * LanguageSwitcher.test.tsx — Unit tests for the LanguageSwitcher component.
 *
 * TDD: Tests written before/alongside implementation.
 *
 * Coverage (18 tests):
 *   - Renders a select element (1)
 *   - Has accessible aria-label (1)
 *   - Shows all 7 supported locales as options (1)
 *   - Each option has the correct locale code as value (7)
 *   - Each option displays the correct native label (7)
 *   - Current locale is selected by default (1)
 *   - Changing selection calls setLocale (1)
 *   - setLocale receives the correct locale code on change (1)
 *   - Haitian Creole option is present with correct label (1)
 *   - Vietnamese option is present with correct label (1)
 *
 * Run: npx vitest run src/components/ui/__tests__/LanguageSwitcher.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { SupportedLocale } from "@/lib/i18n";

// ---------------------------------------------------------------------------
// Mock @/lib/i18n  — isolate the component from the real context provider
// ---------------------------------------------------------------------------

const mockSetLocale = vi.fn();
let mockLocale: SupportedLocale = "en";

vi.mock("@/lib/i18n", () => ({
  useTranslation: () => ({
    locale: mockLocale,
    setLocale: mockSetLocale,
  }),
}));

// Import AFTER the mock is set up
import LanguageSwitcher from "../LanguageSwitcher";

// ---------------------------------------------------------------------------
// Expected locale data
// ---------------------------------------------------------------------------

const EXPECTED_LOCALES: Array<{ code: SupportedLocale; label: string }> = [
  { code: "en", label: "English" },
  { code: "es", label: "Español" },
  { code: "zh", label: "中文" },
  { code: "fr", label: "Français" },
  { code: "ar", label: "العربية" },
  { code: "ht", label: "Kreyòl Ayisyen" },
  { code: "vi", label: "Tiếng Việt" },
];

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  mockLocale = "en";
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("LanguageSwitcher", () => {
  it("renders a select element", () => {
    render(<LanguageSwitcher />);
    const select = screen.getByRole("combobox");
    expect(select).toBeTruthy();
  });

  it("has an accessible aria-label for the language selector", () => {
    render(<LanguageSwitcher />);
    const select = screen.getByRole("combobox");
    const ariaLabel = select.getAttribute("aria-label");
    expect(ariaLabel).toBeTruthy();
    expect(ariaLabel!.length).toBeGreaterThan(0);
  });

  it("renders exactly 7 language options", () => {
    render(<LanguageSwitcher />);
    const options = screen.getAllByRole("option");
    expect(options.length).toBe(7);
  });

  it("English option has value 'en'", () => {
    render(<LanguageSwitcher />);
    const opt = screen.getByRole("option", { name: "English" });
    expect(opt.getAttribute("value")).toBe("en");
  });

  it("Spanish option has value 'es'", () => {
    render(<LanguageSwitcher />);
    const opt = screen.getByRole("option", { name: "Español" });
    expect(opt.getAttribute("value")).toBe("es");
  });

  it("Chinese option has value 'zh'", () => {
    render(<LanguageSwitcher />);
    const opt = screen.getByRole("option", { name: "中文" });
    expect(opt.getAttribute("value")).toBe("zh");
  });

  it("French option has value 'fr'", () => {
    render(<LanguageSwitcher />);
    const opt = screen.getByRole("option", { name: "Français" });
    expect(opt.getAttribute("value")).toBe("fr");
  });

  it("Arabic option has value 'ar'", () => {
    render(<LanguageSwitcher />);
    const opt = screen.getByRole("option", { name: "العربية" });
    expect(opt.getAttribute("value")).toBe("ar");
  });

  it("Haitian Creole option has value 'ht'", () => {
    render(<LanguageSwitcher />);
    const opt = screen.getByRole("option", { name: "Kreyòl Ayisyen" });
    expect(opt.getAttribute("value")).toBe("ht");
  });

  it("Vietnamese option has value 'vi'", () => {
    render(<LanguageSwitcher />);
    const opt = screen.getByRole("option", { name: "Tiếng Việt" });
    expect(opt.getAttribute("value")).toBe("vi");
  });

  it("displays the correct native label for each locale", () => {
    render(<LanguageSwitcher />);
    for (const { code, label } of EXPECTED_LOCALES) {
      const opt = screen.getByRole("option", { name: label });
      expect(opt, `Option for '${code}' with label '${label}' should exist`).toBeTruthy();
    }
  });

  it("shows the current locale as the selected value", () => {
    mockLocale = "es";
    render(<LanguageSwitcher />);
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("es");
  });

  it("calls setLocale when the user selects a different language", () => {
    render(<LanguageSwitcher />);
    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "fr" } });
    expect(mockSetLocale).toHaveBeenCalledTimes(1);
  });

  it("calls setLocale with the correct locale code on change", () => {
    render(<LanguageSwitcher />);
    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "vi" } });
    expect(mockSetLocale).toHaveBeenCalledWith("vi");
  });

  it("calls setLocale with 'ht' when Haitian Creole is selected", () => {
    render(<LanguageSwitcher />);
    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "ht" } });
    expect(mockSetLocale).toHaveBeenCalledWith("ht");
  });

  it("shows Haitian Creole option with native script label 'Kreyòl Ayisyen'", () => {
    render(<LanguageSwitcher />);
    // Must display native name — not English translation "Haitian Creole"
    const htOption = screen.getByRole("option", { name: "Kreyòl Ayisyen" });
    expect(htOption).toBeTruthy();
    expect(htOption.textContent).toBe("Kreyòl Ayisyen");
  });

  it("shows Vietnamese option with native script label 'Tiếng Việt'", () => {
    render(<LanguageSwitcher />);
    // Must display native name with proper diacritics — not 'Tieng Viet'
    const viOption = screen.getByRole("option", { name: "Tiếng Việt" });
    expect(viOption).toBeTruthy();
    expect(viOption.textContent).toBe("Tiếng Việt");
    // Verify diacritics are preserved
    expect(viOption.textContent).toContain("\u1EBF"); // ế in Tiếng
  });
});
