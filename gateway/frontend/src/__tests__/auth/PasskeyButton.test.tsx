/**
 * PasskeyButton.test.tsx — TDD tests for PasskeyButton component.
 *
 * Tests derive from USER REQUIREMENTS, not implementation:
 *   - Renders "Sign in with Passkey" text
 *   - Disabled when email is empty
 *   - Disabled when WebAuthn is not supported
 *   - Shows "Verifying..." during authentication
 *   - Calls onSuccess with token on successful auth
 *   - Calls onError on failed auth
 *   - Has correct aria-label for accessibility
 *
 * Run: npx vitest run src/__tests__/auth/PasskeyButton.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { PasskeyButton } from "../../components/auth/PasskeyButton";

// ─── Mock usePasskey hook ─────────────────────────────────────────────────────

const mockAuthenticateWithPasskey = vi.fn();

const mockUsePasskey = {
  registerPasskey: vi.fn(),
  authenticateWithPasskey: mockAuthenticateWithPasskey,
  isSupported: true,
  isLoading: false,
  error: null as string | null,
};

vi.mock("../../hooks/usePasskey", () => ({
  usePasskey: () => mockUsePasskey,
}));

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks();
  mockUsePasskey.isSupported = true;
  mockUsePasskey.isLoading = false;
  mockUsePasskey.error = null;
  mockAuthenticateWithPasskey.mockResolvedValue(null);
});

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("PasskeyButton", () => {
  it("renders button text 'Sign in with Passkey'", () => {
    render(
      <PasskeyButton email="user@example.com" onSuccess={vi.fn()} />
    );
    expect(screen.getByText("Sign in with Passkey")).toBeTruthy();
  });

  it("button is disabled when email is empty", () => {
    render(<PasskeyButton email="" onSuccess={vi.fn()} />);
    const btn = screen.getByRole("button", { name: /sign in with passkey/i });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it("button is disabled when WebAuthn is not supported", () => {
    mockUsePasskey.isSupported = false;
    render(
      <PasskeyButton email="user@example.com" onSuccess={vi.fn()} />
    );
    const btn = screen.getByRole("button", { name: /sign in with passkey/i });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows 'Verifying...' text during authentication", () => {
    mockUsePasskey.isLoading = true;
    render(
      <PasskeyButton email="user@example.com" onSuccess={vi.fn()} />
    );
    expect(screen.getByText("Verifying...")).toBeTruthy();
  });

  it("calls onSuccess with access_token on successful authentication", async () => {
    const onSuccess = vi.fn();
    mockAuthenticateWithPasskey.mockResolvedValue({
      access_token: "tok_abc123",
      user_id: "user-1",
      email: "user@example.com",
    });

    render(
      <PasskeyButton email="user@example.com" onSuccess={onSuccess} />
    );

    const btn = screen.getByRole("button", { name: /sign in with passkey/i });
    await act(async () => {
      fireEvent.click(btn);
    });

    expect(onSuccess).toHaveBeenCalledWith({
      access_token: "tok_abc123",
      user_id: "user-1",
      email: "user@example.com",
    });
  });

  it("calls onError with error message on failed authentication", async () => {
    const onError = vi.fn();
    mockUsePasskey.error = "Passkey authentication failed.";
    mockAuthenticateWithPasskey.mockResolvedValue(null);

    render(
      <PasskeyButton
        email="user@example.com"
        onSuccess={vi.fn()}
        onError={onError}
      />
    );

    const btn = screen.getByRole("button", { name: /sign in with passkey/i });
    await act(async () => {
      fireEvent.click(btn);
    });

    expect(onError).toHaveBeenCalledWith("Passkey authentication failed.");
  });

  it("calls onError with fallback message when error is null and auth returns null", async () => {
    const onError = vi.fn();
    mockUsePasskey.error = null;
    mockAuthenticateWithPasskey.mockResolvedValue(null);

    render(
      <PasskeyButton
        email="user@example.com"
        onSuccess={vi.fn()}
        onError={onError}
      />
    );

    const btn = screen.getByRole("button", { name: /sign in with passkey/i });
    await act(async () => {
      fireEvent.click(btn);
    });

    expect(onError).toHaveBeenCalledWith("Passkey authentication failed.");
  });

  it("has aria-label 'Sign in with Passkey' for accessibility", () => {
    render(
      <PasskeyButton email="user@example.com" onSuccess={vi.fn()} />
    );
    const btn = screen.getByRole("button", { name: /sign in with passkey/i });
    expect(btn.getAttribute("aria-label")).toBe("Sign in with Passkey");
  });

  it("button is enabled when email is provided and passkeys are supported", () => {
    render(
      <PasskeyButton email="user@example.com" onSuccess={vi.fn()} />
    );
    const btn = screen.getByRole("button", { name: /sign in with passkey/i });
    expect((btn as HTMLButtonElement).disabled).toBe(false);
  });

  it("does not call onSuccess when authentication returns null", async () => {
    const onSuccess = vi.fn();
    mockAuthenticateWithPasskey.mockResolvedValue(null);

    render(
      <PasskeyButton email="user@example.com" onSuccess={onSuccess} />
    );

    const btn = screen.getByRole("button", { name: /sign in with passkey/i });
    await act(async () => {
      fireEvent.click(btn);
    });

    expect(onSuccess).not.toHaveBeenCalled();
  });
});
