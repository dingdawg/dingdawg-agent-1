/**
 * AgenticAssistant.test.tsx — floating contextual assistant widget tests.
 *
 * 20 tests covering: visibility rules, panel open/close, page hints, input,
 * submission, loading state, agent name, empty state, z-index, FAB size,
 * mobile bottom sheet, input clearing, form default prevention.
 *
 * Run: npx vitest run src/__tests__/assistant/AgenticAssistant.test.tsx
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import React from "react";

// ─── Mock next/navigation ─────────────────────────────────────────────────────

const mockUsePathname = vi.fn(() => "/settings");

vi.mock("next/navigation", () => ({
  usePathname: () => mockUsePathname(),
}));

// ─── Mock agentStore ──────────────────────────────────────────────────────────

const mockUseAgentStore = vi.fn(() => ({
  currentAgent: { id: "agent-1", name: "TestBot", handle: "testbot" },
}));

vi.mock("@/store/agentStore", () => ({
  useAgentStore: () => mockUseAgentStore(),
}));

// ─── Mock framer-motion ───────────────────────────────────────────────────────
// Replace animated wrappers with plain divs/spans so tests are deterministic.

vi.mock("framer-motion", () => {
  const React = require("react");
  return {
    AnimatePresence: ({ children }: { children: React.ReactNode }) =>
      React.createElement(React.Fragment, null, children),
    motion: {
      div: React.forwardRef(
        (
          {
            children,
            className,
            style,
            ...rest
          }: React.HTMLAttributes<HTMLDivElement> & { [key: string]: unknown },
          ref: React.Ref<HTMLDivElement>
        ) =>
          React.createElement(
            "div",
            { ref, className, style, "data-motion": "true", ...filterMotionProps(rest) },
            children
          )
      ),
      span: React.forwardRef(
        (
          {
            children,
            className,
            ...rest
          }: React.HTMLAttributes<HTMLSpanElement> & { [key: string]: unknown },
          ref: React.Ref<HTMLSpanElement>
        ) =>
          React.createElement(
            "span",
            { ref, className, "data-motion": "true", ...filterMotionProps(rest) },
            children
          )
      ),
    },
  };
});

/** Strip framer-motion-specific props that are not valid HTML attributes. */
function filterMotionProps(props: Record<string, unknown>): Record<string, unknown> {
  const MOTION_ONLY = new Set([
    "initial", "animate", "exit", "transition", "variants",
    "whileHover", "whileTap", "whileFocus", "whileInView",
    "layout", "layoutId", "onAnimationComplete", "onAnimationStart",
    "onUpdate", "transformTemplate", "drag", "dragConstraints",
    "dragElastic", "dragMomentum",
  ]);
  return Object.fromEntries(
    Object.entries(props).filter(([k]) => !MOTION_ONLY.has(k))
  );
}

// ─── Mock agentService ────────────────────────────────────────────────────────

const mockCreateSession = vi.fn().mockResolvedValue({
  session_id: "sess-test-001",
  user_id: "user-1",
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  message_count: 0,
  total_tokens: 0,
  status: "active",
});

const mockSendMessage = vi.fn().mockResolvedValue({
  content: "Hello! How can I help?",
  session_id: "sess-test-001",
  model_used: "gpt-4o",
  input_tokens: 10,
  output_tokens: 12,
  governance_decision: "PROCEED",
  convergence_status: "ok",
  halted: false,
});

vi.mock("@/services/api/agentService", () => ({
  createSession: (...args: unknown[]) => mockCreateSession(...args),
  sendMessage: (...args: unknown[]) => mockSendMessage(...args),
}));

// ─── Import component AFTER mocks are registered ─────────────────────────────

import { AgenticAssistant } from "../../components/assistant/AgenticAssistant";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function renderWidget() {
  return render(<AgenticAssistant />);
}

function openPanel() {
  const fab = screen.getByTestId("agentic-assistant-fab");
  fireEvent.click(fab);
}

// ─── Test suite ───────────────────────────────────────────────────────────────

describe("AgenticAssistant — visibility", () => {
  beforeEach(() => {
    mockUsePathname.mockReturnValue("/settings");
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("1. FAB renders on non-dashboard pages", () => {
    renderWidget();
    expect(screen.getByTestId("agentic-assistant-fab")).toBeTruthy();
  });

  it("2. FAB does NOT render on /dashboard", () => {
    mockUsePathname.mockReturnValue("/dashboard");
    renderWidget();
    expect(screen.queryByTestId("agentic-assistant-fab")).toBeNull();
  });
});

describe("AgenticAssistant — panel open/close", () => {
  beforeEach(() => {
    mockUsePathname.mockReturnValue("/settings");
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("3. Clicking FAB opens the panel", () => {
    renderWidget();
    expect(screen.queryByTestId("agentic-assistant-panel")).toBeNull();
    openPanel();
    expect(screen.getByTestId("agentic-assistant-panel")).toBeTruthy();
  });

  it("4. Clicking FAB again closes the panel", () => {
    renderWidget();
    openPanel();
    expect(screen.getByTestId("agentic-assistant-panel")).toBeTruthy();
    // Click FAB again to close
    fireEvent.click(screen.getByTestId("agentic-assistant-fab"));
    expect(screen.queryByTestId("agentic-assistant-panel")).toBeNull();
  });

  it("12. Panel has close button that closes it", () => {
    renderWidget();
    openPanel();
    const closeBtn = screen.getAllByTestId("assistant-close-btn")[0];
    fireEvent.click(closeBtn!);
    expect(screen.queryByTestId("agentic-assistant-panel")).toBeNull();
  });
});

describe("AgenticAssistant — page hints", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("5. Panel shows correct page hint for /settings", () => {
    mockUsePathname.mockReturnValue("/settings");
    renderWidget();
    openPanel();
    const hints = screen.getAllByTestId("assistant-page-hint");
    expect(hints[0]!.textContent).toContain("Customize your agent");
  });

  it("6. Panel shows correct page hint for /integrations", () => {
    mockUsePathname.mockReturnValue("/integrations");
    renderWidget();
    openPanel();
    const hints = screen.getAllByTestId("assistant-page-hint");
    expect(hints[0]!.textContent).toContain("Connect your tools");
  });

  it("7. Panel shows correct page hint for /billing", () => {
    mockUsePathname.mockReturnValue("/billing");
    renderWidget();
    openPanel();
    const hints = screen.getAllByTestId("assistant-page-hint");
    expect(hints[0]!.textContent).toContain("plan");
  });

  it("8. Panel shows correct page hint for /analytics", () => {
    mockUsePathname.mockReturnValue("/analytics");
    renderWidget();
    openPanel();
    const hints = screen.getAllByTestId("assistant-page-hint");
    expect(hints[0]!.textContent).toContain("explain the numbers");
  });
});

describe("AgenticAssistant — input and submission", () => {
  beforeEach(() => {
    mockUsePathname.mockReturnValue("/settings");
    mockCreateSession.mockResolvedValue({
      session_id: "sess-test-001",
      user_id: "user-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      message_count: 0,
      total_tokens: 0,
      status: "active",
    });
    mockSendMessage.mockResolvedValue({
      content: "Hello! How can I help?",
      session_id: "sess-test-001",
      model_used: "gpt-4o",
      input_tokens: 10,
      output_tokens: 12,
      governance_decision: "PROCEED",
      convergence_status: "ok",
      halted: false,
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("9. Text input accepts user input", () => {
    renderWidget();
    openPanel();
    const inputs = screen.getAllByTestId("assistant-input");
    fireEvent.change(inputs[0]!, { target: { value: "Hello agent" } });
    expect((inputs[0] as HTMLInputElement).value).toBe("Hello agent");
  });

  it("10. Submitting sends message (calls mock sendMessage)", async () => {
    renderWidget();
    openPanel();
    const inputs = screen.getAllByTestId("assistant-input");
    fireEvent.change(inputs[0]!, { target: { value: "Test question" } });

    const forms = screen.getAllByTestId("assistant-form");
    await act(async () => {
      fireEvent.submit(forms[0]!);
    });

    await waitFor(() => {
      expect(mockSendMessage).toHaveBeenCalledWith("sess-test-001", "Test question");
    });
  });

  it("11. User message appears in panel after submit", async () => {
    renderWidget();
    openPanel();
    const inputs = screen.getAllByTestId("assistant-input");
    fireEvent.change(inputs[0]!, { target: { value: "My question" } });

    const forms = screen.getAllByTestId("assistant-form");
    await act(async () => {
      fireEvent.submit(forms[0]!);
    });

    await waitFor(() => {
      const userMsgs = screen.getAllByTestId("message-user");
      expect(userMsgs.length).toBeGreaterThan(0);
      expect(userMsgs[0]!.textContent).toBe("My question");
    });
  });

  it("18. Input is cleared after submit", async () => {
    renderWidget();
    openPanel();
    const inputs = screen.getAllByTestId("assistant-input");
    fireEvent.change(inputs[0]!, { target: { value: "Clear me" } });

    const forms = screen.getAllByTestId("assistant-form");
    await act(async () => {
      fireEvent.submit(forms[0]!);
    });

    await waitFor(() => {
      const freshInputs = screen.getAllByTestId("assistant-input");
      expect((freshInputs[0] as HTMLInputElement).value).toBe("");
    });
  });

  it("19. Panel shows loading state while waiting for response", async () => {
    // Make sendMessage hang so we can observe the loading state
    let resolveMessage!: (val: unknown) => void;
    mockSendMessage.mockReturnValue(
      new Promise((resolve) => {
        resolveMessage = resolve;
      })
    );

    renderWidget();
    openPanel();
    const inputs = screen.getAllByTestId("assistant-input");
    fireEvent.change(inputs[0]!, { target: { value: "Loading test" } });

    const forms = screen.getAllByTestId("assistant-form");
    act(() => {
      fireEvent.submit(forms[0]!);
    });

    // Loading indicator should appear while waiting
    await waitFor(() => {
      expect(screen.getAllByTestId("assistant-loading").length).toBeGreaterThan(0);
    });

    // Resolve to clean up
    await act(async () => {
      resolveMessage({
        content: "Done",
        session_id: "sess-test-001",
        model_used: "gpt-4o",
        input_tokens: 5,
        output_tokens: 3,
        governance_decision: "PROCEED",
        convergence_status: "ok",
        halted: false,
      });
    });
  });

  it("20. Panel prevents default form submission", async () => {
    renderWidget();
    openPanel();
    const inputs = screen.getAllByTestId("assistant-input");
    fireEvent.change(inputs[0]!, { target: { value: "test" } });

    const forms = screen.getAllByTestId("assistant-form");
    const submitEvent = new Event("submit", { bubbles: true, cancelable: true });
    const preventDefaultSpy = vi.spyOn(submitEvent, "preventDefault");

    await act(async () => {
      forms[0]!.dispatchEvent(submitEvent);
    });

    expect(preventDefaultSpy).toHaveBeenCalled();
  });
});

describe("AgenticAssistant — agent name and empty state", () => {
  beforeEach(() => {
    mockUsePathname.mockReturnValue("/settings");
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("13. Agent name shows in panel header", () => {
    mockUseAgentStore.mockReturnValue({
      currentAgent: { id: "agent-1", name: "MyAgent", handle: "myagent" },
    });
    renderWidget();
    openPanel();
    const names = screen.getAllByTestId("assistant-agent-name");
    expect(names[0]!.textContent).toBe("MyAgent");
  });

  it("14. Empty state shows welcome message", () => {
    renderWidget();
    openPanel();
    const emptyStates = screen.getAllByTestId("assistant-empty-state");
    expect(emptyStates[0]).toBeTruthy();
    expect(emptyStates[0]!.textContent).toContain("sidekick");
  });
});

describe("AgenticAssistant — styling and layout", () => {
  beforeEach(() => {
    mockUsePathname.mockReturnValue("/settings");
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("15. Panel has correct z-index (z-[35])", () => {
    renderWidget();
    openPanel();
    const panel = screen.getByTestId("agentic-assistant-panel");
    // The z-[35] class is applied directly
    expect(panel.className).toContain("z-[35]");
  });

  it("16. FAB has correct size (56px via inline style)", () => {
    renderWidget();
    const fab = screen.getByTestId("agentic-assistant-fab");
    // Width and height are set via inline style as 56
    expect(fab.style.width).toBe("56px");
    expect(fab.style.height).toBe("56px");
  });
});

describe("AgenticAssistant — mobile bottom sheet", () => {
  let originalInnerWidth: number;

  beforeEach(() => {
    mockUsePathname.mockReturnValue("/settings");
    originalInnerWidth = window.innerWidth;
    // Simulate mobile viewport
    Object.defineProperty(window, "innerWidth", {
      writable: true,
      configurable: true,
      value: 375,
    });
  });

  afterEach(() => {
    Object.defineProperty(window, "innerWidth", {
      writable: true,
      configurable: true,
      value: originalInnerWidth,
    });
    vi.clearAllMocks();
  });

  it("17. Mobile renders as bottom sheet (fixed bottom-0, full-width classes present)", () => {
    renderWidget();
    openPanel();
    const panel = screen.getByTestId("agentic-assistant-panel");
    // Bottom sheet classes: bottom-0 left-0 right-0
    expect(panel.className).toContain("bottom-0");
    expect(panel.className).toContain("left-0");
    expect(panel.className).toContain("right-0");
  });
});
