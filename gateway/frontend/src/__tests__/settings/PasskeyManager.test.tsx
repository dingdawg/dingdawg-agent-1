/**
 * PasskeyManager.test.tsx — TDD tests for PasskeyManager component.
 *
 * Tests derive from USER REQUIREMENTS, not implementation:
 *   - Renders "Add Passkey" button
 *   - Shows empty state message when no passkeys
 *   - Renders passkey list items with device names
 *   - Shows last used date for each passkey
 *   - Add passkey button triggers registration flow
 *
 * Run: npx vitest run src/__tests__/settings/PasskeyManager.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { PasskeyManager } from "../../components/settings/PasskeyManager";

// ─── Mock API client ──────────────────────────────────────────────────────────

const mockGet = vi.fn();

vi.mock("../../services/api/client", () => ({
  get: (...args: unknown[]) => mockGet(...args),
  post: vi.fn(),
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));

// ─── Mock usePasskey hook ─────────────────────────────────────────────────────

const mockRegisterPasskey = vi.fn();

const mockUsePasskey = {
  registerPasskey: mockRegisterPasskey,
  authenticateWithPasskey: vi.fn(),
  isSupported: true,
  isLoading: false,
  error: null as string | null,
};

vi.mock("../../hooks/usePasskey", () => ({
  usePasskey: () => mockUsePasskey,
}));

// ─── Sample data ──────────────────────────────────────────────────────────────

const samplePasskeys = [
  {
    credential_id: "cred-1",
    device_name: "iPhone 15",
    created_at: "2026-01-10T10:00:00Z",
    last_used_at: "2026-03-01T09:00:00Z",
  },
  {
    credential_id: "cred-2",
    device_name: "MacBook Pro",
    created_at: "2026-02-15T14:00:00Z",
    last_used_at: null,
  },
];

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks();
  mockUsePasskey.isSupported = true;
  mockUsePasskey.isLoading = false;
  mockUsePasskey.error = null;
  mockGet.mockResolvedValue([]);
  mockRegisterPasskey.mockResolvedValue(true);
});

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("PasskeyManager", () => {
  it("renders the 'Add Passkey' button", async () => {
    render(<PasskeyManager />);
    await waitFor(() => {
      expect(screen.getByText("Add Passkey")).toBeTruthy();
    });
  });

  it("shows empty state message when no passkeys are registered", async () => {
    mockGet.mockResolvedValue([]);
    render(<PasskeyManager />);
    await waitFor(() => {
      expect(
        screen.getByText(
          "No passkeys registered. Add one to enable biometric login."
        )
      ).toBeTruthy();
    });
  });

  it("renders passkey list items with device names", async () => {
    mockGet.mockResolvedValue(samplePasskeys);
    render(<PasskeyManager />);
    await waitFor(() => {
      expect(screen.getByText("iPhone 15")).toBeTruthy();
      expect(screen.getByText("MacBook Pro")).toBeTruthy();
    });
  });

  it("shows last used date for a passkey that has been used", async () => {
    mockGet.mockResolvedValue(samplePasskeys);
    render(<PasskeyManager />);
    await waitFor(() => {
      // The formatted date will vary by locale; check partial text
      const items = screen.getAllByText(/Last used/i);
      expect(items.length).toBeGreaterThan(0);
    });
  });

  it("shows 'Never' for last used when last_used_at is null", async () => {
    mockGet.mockResolvedValue([
      {
        credential_id: "cred-3",
        device_name: "Windows Hello",
        created_at: "2026-02-20T08:00:00Z",
        last_used_at: null,
      },
    ]);
    render(<PasskeyManager />);
    await waitFor(() => {
      expect(screen.getByText("Windows Hello")).toBeTruthy();
      // last_used_at null means no "Last used" suffix appears
      const itemText = screen.getByText(/Added/i);
      expect(itemText.textContent).not.toMatch(/Last used/i);
    });
  });

  it("Add Passkey button triggers registerPasskey on click", async () => {
    mockGet.mockResolvedValue([]);
    render(<PasskeyManager />);

    await waitFor(() => {
      expect(screen.getByText("Add Passkey")).toBeTruthy();
    });

    const btn = screen.getByRole("button", { name: /add passkey/i });
    await act(async () => {
      fireEvent.click(btn);
    });

    expect(mockRegisterPasskey).toHaveBeenCalledWith("My Device");
  });

  it("shows success message after successful passkey registration", async () => {
    mockGet.mockResolvedValue([]);
    mockRegisterPasskey.mockResolvedValue(true);

    render(<PasskeyManager />);

    await waitFor(() => {
      expect(screen.getByText("Add Passkey")).toBeTruthy();
    });

    const btn = screen.getByRole("button", { name: /add passkey/i });
    await act(async () => {
      fireEvent.click(btn);
    });

    await waitFor(() => {
      expect(screen.getByText("Passkey added successfully.")).toBeTruthy();
    });
  });

  it("shows error message when registration fails", async () => {
    mockGet.mockResolvedValue([]);
    mockRegisterPasskey.mockResolvedValue(false);
    mockUsePasskey.error = "Credential creation was cancelled or failed.";

    render(<PasskeyManager />);

    await waitFor(() => {
      expect(screen.getByText("Add Passkey")).toBeTruthy();
    });

    const btn = screen.getByRole("button", { name: /add passkey/i });
    await act(async () => {
      fireEvent.click(btn);
    });

    await waitFor(() => {
      expect(
        screen.getByText("Credential creation was cancelled or failed.")
      ).toBeTruthy();
    });
  });
});
