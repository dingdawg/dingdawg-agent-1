"use client";

/**
 * ChatStream — message list with card rendering and auto-scroll.
 *
 * Renders text messages via MessageBubble and embedded card types
 * (KPI, task, task-list, quick-replies, agent-status, form, payment,
 * calendar, map, media, progress, confirmation) inline in the stream.
 *
 * Generative UI: Also renders structured JSON specs from AI responses via
 * GenerativeUIRenderer. The catalog constrains what MiLA can emit — unknown
 * types fall back to plain text. All specs are validated before rendering.
 *
 * Uses react-virtuoso for virtual rendering — keeps DOM nodes low even with
 * 100+ messages. followOutput="smooth" auto-scrolls on new messages and
 * automatically pauses when the user scrolls up.
 *
 * UX Phase 1 additions:
 * - MessageSkeleton shown when last user message has no assistant reply yet
 * - onRetry prop wired to MessageBubble for error recovery
 */

import { useCallback } from "react";
import { Virtuoso } from "react-virtuoso";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/store/chatStore";
import {
  GenerativeUIRenderer,
  type AIResponse,
  type GenerativeUIRendererCallbacks,
} from "@/components/generative-ui";
import { MessageBubble } from "./MessageBubble";
import { MessageSkeleton } from "./MessageSkeleton";
import { KPICards } from "./cards/KPICards";
import type { KPIMetric } from "./cards/KPICards";
import { TaskCard } from "./cards/TaskCard";
import type { TaskCardData } from "./cards/TaskCard";
import { TaskListCard } from "./cards/TaskListCard";
import { QuickReplies } from "./cards/QuickReplies";
import { AgentStatusCard } from "./cards/AgentStatusCard";
import type { AgentInfo } from "./cards/AgentStatusCard";
import { FormCard } from "./cards/FormCard";
import type { FormField } from "./cards/FormCard";
import { PaymentCard } from "./cards/PaymentCard";
import type { PaymentStatus } from "./cards/PaymentCard";
import { CalendarCard } from "./cards/CalendarCard";
import type { DateSlot } from "./cards/CalendarCard";
import { MapCard } from "./cards/MapCard";
import { MediaCard } from "./cards/MediaCard";
import type { MediaItem } from "./cards/MediaCard";
import { ProgressCard } from "./cards/ProgressCard";
import type { ProgressStep } from "./cards/ProgressCard";
import { ConfirmationCard } from "./cards/ConfirmationCard";
import { HealthStatusCard } from "./cards/HealthStatusCard";
import type { HealthStatusData } from "./cards/HealthStatusCard";
import { IntegrationConnectCard } from "./cards/IntegrationConnectCard";
import {
  WelcomeCard,
  SelectionCard,
  InputCard,
  OAuthCard,
  StepProgressCard,
  ConfirmSummaryCard,
  SuccessCard,
  ChecklistCard,
} from "./cards/OnboardingCards";

export interface CardPayload {
  type:
    | "kpi-cards"
    | "task-card"
    | "task-list"
    | "agent-status"
    | "quick-replies"
    | "form"
    | "payment"
    | "calendar"
    | "map"
    | "media"
    | "progress"
    | "confirmation"
    | "health-status"
    | "integration-connect"
    | "welcome"
    | "selection"
    | "input-field"
    | "oauth"
    | "step-progress"
    | "confirm-summary"
    | "success"
    | "checklist";
  // Health status card
  healthData?: HealthStatusData;
  // Integration connect card
  integrationData?: import("./cards/IntegrationConnectCard").IntegrationConnectData;
  // Onboarding cards
  welcomeData?: import("./cards/OnboardingCards").WelcomeCardProps;
  selectionData?: import("./cards/OnboardingCards").SelectionCardProps;
  inputData?: import("./cards/OnboardingCards").InputCardProps;
  oauthData?: import("./cards/OnboardingCards").OAuthCardProps;
  stepProgressData?: import("./cards/OnboardingCards").StepProgressCardProps;
  confirmData?: import("./cards/OnboardingCards").ConfirmSummaryCardProps;
  successData?: import("./cards/OnboardingCards").SuccessCardProps;
  checklistData?: import("./cards/OnboardingCards").ChecklistCardProps;
  // Existing card fields
  kpiMetrics?: KPIMetric[];
  task?: TaskCardData;
  tasks?: TaskCardData[];
  taskListTitle?: string;
  agent?: AgentInfo;
  quickReplies?: string[];
  // Form card
  formFields?: FormField[];
  formSubmitLabel?: string;
  // Payment card
  paymentAmount?: number;
  paymentCurrency?: string;
  paymentDescription?: string;
  paymentStatus?: PaymentStatus;
  // Calendar card
  calendarSlots?: DateSlot[];
  // Map card
  mapAddress?: string;
  mapLat?: number;
  mapLng?: number;
  mapLabel?: string;
  // Media card
  mediaItems?: MediaItem[];
  mediaLayout?: "single" | "grid" | "carousel";
  // Progress card
  progressSteps?: ProgressStep[];
  progressCurrentStep?: number;
  progressTitle?: string;
  // Confirmation card
  confirmTitle?: string;
  confirmDescription?: string;
  confirmVariant?: "default" | "danger";
}

interface ChatStreamProps {
  messages: ChatMessage[];
  cards?: Map<string, CardPayload[]>;
  /**
   * Generative UI specs keyed by message ID.
   * Each entry is a validated AIResponse containing structured component specs
   * emitted by MiLA. Pass through catalog-validator.validate() before storing.
   */
  generativeUI?: Map<string, AIResponse>;
  /** Callbacks forwarded to GenerativeUIRenderer for interactive components. */
  generativeUICallbacks?: GenerativeUIRendererCallbacks;
  onQuickReply?: (reply: string) => void;
  onTaskAction?: (action: "start" | "edit" | "cancel", taskId: string) => void;
  onTaskClick?: (taskId: string) => void;
  onFormSubmit?: (data: Record<string, string>) => void;
  onPayment?: () => void;
  onDateSelect?: (date: Date) => void;
  onConfirm?: () => void;
  onCancel?: () => void;
  onRetry?: (messageId: string) => void;
  onIntegrationConnect?: (integrationId: string, inputValue?: string) => void;
  isStreaming?: boolean;
  isLoading?: boolean;
  className?: string;
}

export function ChatStream({
  messages,
  cards,
  generativeUI,
  generativeUICallbacks,
  onQuickReply,
  onTaskAction,
  onTaskClick,
  onFormSubmit,
  onPayment,
  onDateSelect,
  onConfirm,
  onCancel,
  onRetry,
  onIntegrationConnect,
  isStreaming = false,
  isLoading = false,
  className,
}: ChatStreamProps) {
  // ── Generative UI rendering ──────────────────────────────────────────────
  const renderGenerativeUI = useCallback(
    (messageId: string) => {
      const spec = generativeUI?.get(messageId);
      if (!spec) return null;
      return (
        <GenerativeUIRenderer
          response={spec}
          callbacks={generativeUICallbacks}
          className="max-w-[85%]"
        />
      );
    },
    [generativeUI, generativeUICallbacks]
  );

  const renderCards = useCallback(
    (messageId: string) => {
      const messageCards = cards?.get(messageId);
      if (!messageCards || messageCards.length === 0) return null;

      return (
        <div className="flex flex-col gap-3 mt-2 max-w-[85%]">
          {messageCards.map((card, i) => {
            switch (card.type) {
              case "kpi-cards":
                return card.kpiMetrics ? (
                  <KPICards key={`kpi-${i}`} metrics={card.kpiMetrics} />
                ) : null;

              case "task-card":
                return card.task ? (
                  <TaskCard
                    key={`task-${i}`}
                    task={card.task}
                    onAction={onTaskAction}
                  />
                ) : null;

              case "task-list":
                return card.tasks ? (
                  <TaskListCard
                    key={`tasklist-${i}`}
                    tasks={card.tasks}
                    title={card.taskListTitle}
                    onTaskClick={onTaskClick}
                  />
                ) : null;

              case "agent-status":
                return card.agent ? (
                  <AgentStatusCard key={`agent-${i}`} agent={card.agent} />
                ) : null;

              case "quick-replies":
                return card.quickReplies ? (
                  <QuickReplies
                    key={`qr-${i}`}
                    options={card.quickReplies}
                    onSelect={onQuickReply ?? (() => {})}
                  />
                ) : null;

              case "form":
                return card.formFields ? (
                  <FormCard
                    key={`form-${i}`}
                    fields={card.formFields}
                    onSubmit={onFormSubmit ?? (() => {})}
                    submitLabel={card.formSubmitLabel ?? "Submit"}
                  />
                ) : null;

              case "payment":
                return card.paymentAmount != null ? (
                  <PaymentCard
                    key={`payment-${i}`}
                    amount={card.paymentAmount}
                    currency={card.paymentCurrency ?? "USD"}
                    description={card.paymentDescription ?? ""}
                    onPay={onPayment ?? (() => {})}
                    status={card.paymentStatus ?? "pending"}
                  />
                ) : null;

              case "calendar":
                return (
                  <CalendarCard
                    key={`calendar-${i}`}
                    availableSlots={card.calendarSlots}
                    onSelect={onDateSelect ?? (() => {})}
                  />
                );

              case "map":
                return card.mapAddress ? (
                  <MapCard
                    key={`map-${i}`}
                    address={card.mapAddress}
                    lat={card.mapLat}
                    lng={card.mapLng}
                    label={card.mapLabel}
                  />
                ) : null;

              case "media":
                return card.mediaItems ? (
                  <MediaCard
                    key={`media-${i}`}
                    items={card.mediaItems}
                    layout={card.mediaLayout ?? "single"}
                  />
                ) : null;

              case "progress":
                return card.progressSteps ? (
                  <ProgressCard
                    key={`progress-${i}`}
                    steps={card.progressSteps}
                    currentStep={card.progressCurrentStep ?? 0}
                    title={card.progressTitle}
                  />
                ) : null;

              case "confirmation":
                return card.confirmTitle ? (
                  <ConfirmationCard
                    key={`confirm-${i}`}
                    title={card.confirmTitle}
                    description={card.confirmDescription}
                    onConfirm={onConfirm ?? (() => {})}
                    onCancel={onCancel ?? (() => {})}
                    variant={card.confirmVariant}
                  />
                ) : null;

              case "health-status":
                return card.healthData ? (
                  <HealthStatusCard key={`health-${i}`} data={card.healthData} />
                ) : null;

              case "integration-connect":
                return card.integrationData ? (
                  <IntegrationConnectCard
                    key={`integration-${i}`}
                    data={card.integrationData}
                    onConnect={onIntegrationConnect ?? (() => {})}
                  />
                ) : null;

              case "welcome":
                return card.welcomeData ? (
                  <WelcomeCard key={`welcome-${i}`} {...card.welcomeData} />
                ) : null;

              case "selection":
                return card.selectionData ? (
                  <SelectionCard key={`selection-${i}`} {...card.selectionData} />
                ) : null;

              case "input-field":
                return card.inputData ? (
                  <InputCard key={`input-${i}`} {...card.inputData} />
                ) : null;

              case "oauth":
                return card.oauthData ? (
                  <OAuthCard key={`oauth-${i}`} {...card.oauthData} />
                ) : null;

              case "step-progress":
                return card.stepProgressData ? (
                  <StepProgressCard key={`progress-${i}`} {...card.stepProgressData} />
                ) : null;

              case "confirm-summary":
                return card.confirmData ? (
                  <ConfirmSummaryCard key={`confirm-summary-${i}`} {...card.confirmData} />
                ) : null;

              case "success":
                return card.successData ? (
                  <SuccessCard key={`success-${i}`} {...card.successData} />
                ) : null;

              case "checklist":
                return card.checklistData ? (
                  <ChecklistCard key={`checklist-${i}`} {...card.checklistData} />
                ) : null;

              default:
                return null;
            }
          })}
        </div>
      );
    },
    [
      cards,
      onQuickReply,
      onTaskAction,
      onTaskClick,
      onFormSubmit,
      onPayment,
      onDateSelect,
      onConfirm,
      onCancel,
      onIntegrationConnect,
    ]
  );

  // Per-item renderer for Virtuoso
  const itemContent = useCallback(
    (index: number) => {
      const message = messages[index];
      return (
        <div key={message.id} className="max-w-3xl mx-auto w-full px-4 sm:px-6 pb-1">
          <MessageBubble message={message} onRetry={onRetry} />
          {/* Legacy card system (backward compatible) */}
          {renderCards(message.id)}
          {/* Generative UI — structured JSON specs from MiLA */}
          {renderGenerativeUI(message.id)}
        </div>
      );
    },
    [messages, renderCards, renderGenerativeUI, onRetry]
  );

  // Empty placeholder shown when no messages exist
  const EmptyPlaceholder = useCallback(
    () => (
      <div className="flex flex-col items-center justify-center h-full text-center px-4">
        <div className="h-16 w-16 rounded-2xl bg-[var(--gold-500)]/10 flex items-center justify-center mb-4">
          <span className="text-2xl font-heading font-bold text-[var(--gold-500)]">
            D
          </span>
        </div>
        <h2 className="text-lg font-heading font-semibold text-[var(--foreground)] mb-1">
          DingDawg Agent
        </h2>
        <p className="text-sm text-[var(--color-muted)] max-w-xs">
          Your personal AI assistant. Ask me anything or use the quick
          actions below.
        </p>
      </div>
    ),
    []
  );

  // Footer: skeleton OR thinking indicator rendered below the virtual list
  const Footer = useCallback(
    () => {
      // Show skeleton when waiting for the first token after a user message
      const lastMessage = messages[messages.length - 1];
      const showSkeleton =
        isLoading && lastMessage?.role === "user";

      if (showSkeleton) {
        return (
          <div className="max-w-3xl mx-auto w-full px-4 sm:px-6 pb-1">
            <MessageSkeleton />
          </div>
        );
      }

      if (isStreaming) {
        return (
          <div className="flex items-start mb-4 px-4 sm:px-6 max-w-3xl mx-auto w-full">
            <div className="dd-chat-bubble assistant">
              <div className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-[var(--gold-500)] thinking-pulse" />
                <span
                  className="h-2 w-2 rounded-full bg-[var(--gold-500)] thinking-pulse"
                  style={{ animationDelay: "0.2s" }}
                />
                <span
                  className="h-2 w-2 rounded-full bg-[var(--gold-500)] thinking-pulse"
                  style={{ animationDelay: "0.4s" }}
                />
              </div>
            </div>
          </div>
        );
      }

      return null;
    },
    [isStreaming, isLoading, messages]
  );

  return (
    <Virtuoso
      role="log"
      aria-live="polite"
      aria-label="Chat messages"
      className={cn("flex-1 min-h-0 scrollbar-thin", className)}
      // min-h-0 prevents Virtuoso from overflowing a flex parent on mobile.
      // flex: 1 alone is insufficient in some mobile browsers without explicit
      // overflow:hidden on the ancestor — min-h-0 ensures the column shrinks.
      style={{ flex: 1, minHeight: 0 }}
      data={messages}
      totalCount={messages.length}
      itemContent={itemContent}
      followOutput="smooth"
      alignToBottom
      components={{
        EmptyPlaceholder,
        Footer,
      }}
      // Top padding: matches old py-6 (24px)
      topItemCount={0}
      initialTopMostItemIndex={messages.length > 0 ? messages.length - 1 : 0}
    />
  );
}
