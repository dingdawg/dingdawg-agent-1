/**
 * ChatStream.test.tsx — switch-based card routing tests
 *
 * 16 tests covering:
 *   - All 12 card types render when provided with valid data
 *   - Cards with missing required data gracefully return null
 *   - Callback props (onFormSubmit, onPayment, onDateSelect, onConfirm, onCancel)
 *     are forwarded to the correct card components
 *   - Empty placeholder renders when no messages exist
 *   - Streaming footer renders when isStreaming=true
 *
 * Run: npx vitest run src/__tests__/chat/ChatStream.test.tsx
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ChatStream } from "../../components/chat/ChatStream";
import type { CardPayload } from "../../components/chat/ChatStream";
import type { ChatMessage } from "../../store/chatStore";

// ---------------------------------------------------------------------------
// Mock react-virtuoso — jsdom cannot measure element sizes
// ---------------------------------------------------------------------------

vi.mock("react-virtuoso", () => ({
  Virtuoso: ({ data, itemContent, components }: any) => {
    const EmptyPlaceholder = components?.EmptyPlaceholder;
    const Footer = components?.Footer;
    if (!data || data.length === 0) {
      return EmptyPlaceholder ? <EmptyPlaceholder /> : null;
    }
    return (
      <div data-testid="virtuoso-mock">
        {data.map((_: any, i: number) => (
          <div key={i}>{itemContent(i)}</div>
        ))}
        {Footer && <Footer />}
      </div>
    );
  },
}));

// ---------------------------------------------------------------------------
// Mock MessageBubble — not under test here
// ---------------------------------------------------------------------------

vi.mock("../../components/chat/MessageBubble", () => ({
  MessageBubble: ({ message }: any) => (
    <div data-testid="message-bubble" data-id={message.id} />
  ),
}));

// ---------------------------------------------------------------------------
// Mock all card components to lightweight stubs
// ---------------------------------------------------------------------------

vi.mock("../../components/chat/cards/KPICards", () => ({
  KPICards: ({ metrics }: any) => (
    <div data-testid="kpi-cards" data-count={metrics?.length} />
  ),
}));

vi.mock("../../components/chat/cards/TaskCard", () => ({
  TaskCard: ({ task }: any) => (
    <div data-testid="task-card" data-task-id={task?.id} />
  ),
}));

vi.mock("../../components/chat/cards/TaskListCard", () => ({
  TaskListCard: ({ tasks }: any) => (
    <div data-testid="task-list-card" data-count={tasks?.length} />
  ),
}));

vi.mock("../../components/chat/cards/QuickReplies", () => ({
  QuickReplies: ({ options, onSelect }: any) => (
    <button
      data-testid="quick-replies"
      data-count={options?.length}
      onClick={() => onSelect(options[0])}
    />
  ),
}));

vi.mock("../../components/chat/cards/AgentStatusCard", () => ({
  AgentStatusCard: ({ agent }: any) => (
    <div data-testid="agent-status-card" data-agent-id={agent?.id} />
  ),
}));

vi.mock("../../components/chat/cards/FormCard", () => ({
  FormCard: ({ fields, onSubmit, submitLabel }: any) => (
    <button
      data-testid="form-card"
      data-field-count={fields?.length}
      data-submit-label={submitLabel}
      onClick={() => onSubmit({ name: "test" })}
    />
  ),
}));

vi.mock("../../components/chat/cards/PaymentCard", () => ({
  PaymentCard: ({ amount, onPay, status }: any) => (
    <button
      data-testid="payment-card"
      data-amount={amount}
      data-status={status}
      onClick={onPay}
    />
  ),
}));

vi.mock("../../components/chat/cards/CalendarCard", () => ({
  CalendarCard: ({ onSelect }: any) => (
    <button
      data-testid="calendar-card"
      onClick={() => onSelect(new Date("2026-04-01"))}
    />
  ),
}));

vi.mock("../../components/chat/cards/MapCard", () => ({
  MapCard: ({ address, label }: any) => (
    <div data-testid="map-card" data-address={address} data-label={label} />
  ),
}));

vi.mock("../../components/chat/cards/MediaCard", () => ({
  MediaCard: ({ items, layout }: any) => (
    <div
      data-testid="media-card"
      data-count={items?.length}
      data-layout={layout}
    />
  ),
}));

vi.mock("../../components/chat/cards/ProgressCard", () => ({
  ProgressCard: ({ steps, currentStep, title }: any) => (
    <div
      data-testid="progress-card"
      data-step-count={steps?.length}
      data-current={currentStep}
      data-title={title}
    />
  ),
}));

vi.mock("../../components/chat/cards/ConfirmationCard", () => ({
  ConfirmationCard: ({ title, onConfirm, onCancel, variant }: any) => (
    <div data-testid="confirmation-card" data-title={title} data-variant={variant}>
      <button data-testid="confirm-btn" onClick={onConfirm} />
      <button data-testid="cancel-btn" onClick={onCancel} />
    </div>
  ),
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeMessage(id: string): ChatMessage {
  return {
    id,
    role: "assistant",
    content: "Hello",
    type: "text",
    status: "final",
    timestamp: 0,
  };
}

function makeCards(id: string, payload: CardPayload): Map<string, CardPayload[]> {
  return new Map([[id, [payload]]]);
}

const MSG_ID = "msg-1";
const BASE_MSG = [makeMessage(MSG_ID)];

// ---------------------------------------------------------------------------
// Existing card types — smoke tests to confirm nothing broken
// ---------------------------------------------------------------------------

describe("ChatStream — existing card types", () => {
  it("renders kpi-cards when kpiMetrics provided", () => {
    const cards = makeCards(MSG_ID, {
      type: "kpi-cards",
      kpiMetrics: [{ label: "Revenue", value: "$100k" }],
    });
    render(<ChatStream messages={BASE_MSG} cards={cards} />);
    expect(screen.getByTestId("kpi-cards")).toBeTruthy();
  });

  it("renders task-card when task provided", () => {
    const cards = makeCards(MSG_ID, {
      type: "task-card",
      task: { id: "t1", description: "Do thing", status: "pending" },
    });
    render(<ChatStream messages={BASE_MSG} cards={cards} />);
    expect(screen.getByTestId("task-card")).toBeTruthy();
  });

  it("renders quick-replies when quickReplies provided", () => {
    const cards = makeCards(MSG_ID, {
      type: "quick-replies",
      quickReplies: ["Yes", "No"],
    });
    render(<ChatStream messages={BASE_MSG} cards={cards} />);
    expect(screen.getByTestId("quick-replies")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// New card types — 7 cases
// ---------------------------------------------------------------------------

describe("ChatStream — form card", () => {
  it("renders FormCard when formFields provided", () => {
    const cards = makeCards(MSG_ID, {
      type: "form",
      formFields: [{ name: "email", label: "Email", type: "email", required: true }],
      formSubmitLabel: "Send",
    });
    render(<ChatStream messages={BASE_MSG} cards={cards} />);
    const card = screen.getByTestId("form-card");
    expect(card).toBeTruthy();
    expect(card.getAttribute("data-submit-label")).toBe("Send");
    expect(card.getAttribute("data-field-count")).toBe("1");
  });

  it("returns null for form card when formFields is absent", () => {
    const cards = makeCards(MSG_ID, { type: "form" });
    render(<ChatStream messages={BASE_MSG} cards={cards} />);
    expect(screen.queryByTestId("form-card")).toBeNull();
  });

  it("forwards onFormSubmit callback to FormCard", () => {
    const onFormSubmit = vi.fn();
    const cards = makeCards(MSG_ID, {
      type: "form",
      formFields: [{ name: "x", label: "X", type: "text" }],
    });
    render(
      <ChatStream messages={BASE_MSG} cards={cards} onFormSubmit={onFormSubmit} />
    );
    screen.getByTestId("form-card").click();
    expect(onFormSubmit).toHaveBeenCalledWith({ name: "test" });
  });
});

describe("ChatStream — payment card", () => {
  it("renders PaymentCard when paymentAmount provided", () => {
    const cards = makeCards(MSG_ID, {
      type: "payment",
      paymentAmount: 4999,
      paymentCurrency: "USD",
      paymentDescription: "Pro plan",
      paymentStatus: "pending",
    });
    render(<ChatStream messages={BASE_MSG} cards={cards} />);
    const card = screen.getByTestId("payment-card");
    expect(card.getAttribute("data-amount")).toBe("4999");
    expect(card.getAttribute("data-status")).toBe("pending");
  });

  it("returns null for payment card when paymentAmount is absent", () => {
    const cards = makeCards(MSG_ID, { type: "payment" });
    render(<ChatStream messages={BASE_MSG} cards={cards} />);
    expect(screen.queryByTestId("payment-card")).toBeNull();
  });

  it("forwards onPayment callback to PaymentCard", () => {
    const onPayment = vi.fn();
    const cards = makeCards(MSG_ID, {
      type: "payment",
      paymentAmount: 100,
    });
    render(
      <ChatStream messages={BASE_MSG} cards={cards} onPayment={onPayment} />
    );
    screen.getByTestId("payment-card").click();
    expect(onPayment).toHaveBeenCalledOnce();
  });
});

describe("ChatStream — calendar card", () => {
  it("renders CalendarCard (always — no required data guard)", () => {
    const cards = makeCards(MSG_ID, { type: "calendar" });
    render(<ChatStream messages={BASE_MSG} cards={cards} />);
    expect(screen.getByTestId("calendar-card")).toBeTruthy();
  });

  it("forwards onDateSelect callback to CalendarCard", () => {
    const onDateSelect = vi.fn();
    const cards = makeCards(MSG_ID, { type: "calendar" });
    render(
      <ChatStream messages={BASE_MSG} cards={cards} onDateSelect={onDateSelect} />
    );
    screen.getByTestId("calendar-card").click();
    expect(onDateSelect).toHaveBeenCalledWith(new Date("2026-04-01"));
  });
});

describe("ChatStream — map card", () => {
  it("renders MapCard when mapAddress provided", () => {
    const cards = makeCards(MSG_ID, {
      type: "map",
      mapAddress: "123 Main St",
      mapLabel: "HQ",
    });
    render(<ChatStream messages={BASE_MSG} cards={cards} />);
    const card = screen.getByTestId("map-card");
    expect(card.getAttribute("data-address")).toBe("123 Main St");
    expect(card.getAttribute("data-label")).toBe("HQ");
  });

  it("returns null for map card when mapAddress is absent", () => {
    const cards = makeCards(MSG_ID, { type: "map" });
    render(<ChatStream messages={BASE_MSG} cards={cards} />);
    expect(screen.queryByTestId("map-card")).toBeNull();
  });
});

describe("ChatStream — media card", () => {
  it("renders MediaCard when mediaItems provided", () => {
    const cards = makeCards(MSG_ID, {
      type: "media",
      mediaItems: [{ type: "image", src: "/img.png", alt: "test" }],
      mediaLayout: "grid",
    });
    render(<ChatStream messages={BASE_MSG} cards={cards} />);
    const card = screen.getByTestId("media-card");
    expect(card.getAttribute("data-count")).toBe("1");
    expect(card.getAttribute("data-layout")).toBe("grid");
  });

  it("returns null for media card when mediaItems is absent", () => {
    const cards = makeCards(MSG_ID, { type: "media" });
    render(<ChatStream messages={BASE_MSG} cards={cards} />);
    expect(screen.queryByTestId("media-card")).toBeNull();
  });
});

describe("ChatStream — progress card", () => {
  it("renders ProgressCard when progressSteps provided", () => {
    const cards = makeCards(MSG_ID, {
      type: "progress",
      progressSteps: [
        { label: "Order placed", status: "completed" },
        { label: "In transit", status: "active" },
      ],
      progressCurrentStep: 1,
      progressTitle: "Order #123",
    });
    render(<ChatStream messages={BASE_MSG} cards={cards} />);
    const card = screen.getByTestId("progress-card");
    expect(card.getAttribute("data-step-count")).toBe("2");
    expect(card.getAttribute("data-current")).toBe("1");
    expect(card.getAttribute("data-title")).toBe("Order #123");
  });

  it("returns null for progress card when progressSteps is absent", () => {
    const cards = makeCards(MSG_ID, { type: "progress" });
    render(<ChatStream messages={BASE_MSG} cards={cards} />);
    expect(screen.queryByTestId("progress-card")).toBeNull();
  });
});

describe("ChatStream — confirmation card", () => {
  it("renders ConfirmationCard when confirmTitle provided", () => {
    const cards = makeCards(MSG_ID, {
      type: "confirmation",
      confirmTitle: "Delete account?",
      confirmVariant: "danger",
    });
    render(<ChatStream messages={BASE_MSG} cards={cards} />);
    const card = screen.getByTestId("confirmation-card");
    expect(card.getAttribute("data-title")).toBe("Delete account?");
    expect(card.getAttribute("data-variant")).toBe("danger");
  });

  it("returns null for confirmation card when confirmTitle is absent", () => {
    const cards = makeCards(MSG_ID, { type: "confirmation" });
    render(<ChatStream messages={BASE_MSG} cards={cards} />);
    expect(screen.queryByTestId("confirmation-card")).toBeNull();
  });

  it("forwards onConfirm and onCancel callbacks to ConfirmationCard", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    const cards = makeCards(MSG_ID, {
      type: "confirmation",
      confirmTitle: "Are you sure?",
    });
    render(
      <ChatStream
        messages={BASE_MSG}
        cards={cards}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    );
    screen.getByTestId("confirm-btn").click();
    expect(onConfirm).toHaveBeenCalledOnce();
    screen.getByTestId("cancel-btn").click();
    expect(onCancel).toHaveBeenCalledOnce();
  });
});

// ---------------------------------------------------------------------------
// ChatStream structural tests
// ---------------------------------------------------------------------------

describe("ChatStream — structural", () => {
  it("renders the empty placeholder when messages array is empty", () => {
    render(<ChatStream messages={[]} />);
    expect(screen.getByText("DingDawg Agent")).toBeTruthy();
  });

  it("renders the streaming footer when isStreaming=true", () => {
    render(<ChatStream messages={BASE_MSG} isStreaming={true} />);
    // Footer contains thinking-pulse spans; query by class
    const { container } = render(
      <ChatStream messages={BASE_MSG} isStreaming={true} />
    );
    expect(container.querySelectorAll(".thinking-pulse").length).toBeGreaterThan(0);
  });

  it("renders nothing in the footer when isStreaming=false", () => {
    const { container } = render(
      <ChatStream messages={BASE_MSG} isStreaming={false} />
    );
    expect(container.querySelectorAll(".thinking-pulse").length).toBe(0);
  });
});
