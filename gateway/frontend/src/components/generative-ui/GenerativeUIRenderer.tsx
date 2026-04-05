"use client";

/**
 * GenerativeUIRenderer
 *
 * Maps a validated GenerativeUISpec (type + props) to its React component.
 * Only types in the ComponentCatalog are rendered — unknown types are silently
 * dropped (safe text-only fallback is handled by the caller, ChatStream).
 *
 * GOVERNANCE: Specs must be validated via catalog-validator before being passed
 * here. This renderer trusts the props are already schema-valid.
 */

import { useCallback } from "react";
import type { AIResponse, GenerativeUISpec, ComponentCatalog } from "./catalog";
import { PERMITTED_COMPONENT_TYPES } from "./catalog";

import { BookingSummary } from "./components/BookingSummary";
import { StatsGrid } from "./components/StatsGrid";
import { ClientList } from "./components/ClientList";
import { AgentActivity } from "./components/AgentActivity";
import { QuickActions } from "./components/QuickActions";
import { AlertCard } from "./components/AlertCard";
import { ChartView } from "./components/ChartView";
import { InvoiceView } from "./components/InvoiceView";
import { OnboardingStep } from "./components/OnboardingStep";
import { SettingsPanel } from "./components/SettingsPanel";

// ─── Renderer context (callbacks wired in from parent) ────────────────────

export interface GenerativeUIRendererCallbacks {
  onQuickAction?: (action: string) => void;
  onAlertAction?: (payload: string) => void;
  onOnboardingCta?: () => void;
  onSettingsChange?: (
    section: string,
    key: string,
    value: string | boolean | number
  ) => void;
}

// ─── Single-spec renderer ─────────────────────────────────────────────────

interface SpecRendererProps {
  spec: GenerativeUISpec;
  callbacks?: GenerativeUIRendererCallbacks;
}

function SpecRenderer({ spec, callbacks }: SpecRendererProps) {
  const { type, props } = spec;

  // Guard: only render types in the catalog whitelist
  if (!PERMITTED_COMPONENT_TYPES.includes(type)) {
    if (process.env.NODE_ENV === "development") {
      console.warn(`[GenerativeUIRenderer] Unknown component type: "${type}" — skipping`);
    }
    return null;
  }

  switch (type) {
    case "BookingSummary":
      return (
        <BookingSummary {...(props as ComponentCatalog["BookingSummary"])} />
      );

    case "StatsGrid":
      return <StatsGrid {...(props as ComponentCatalog["StatsGrid"])} />;

    case "ClientList":
      return <ClientList {...(props as ComponentCatalog["ClientList"])} />;

    case "AgentActivity":
      return <AgentActivity {...(props as ComponentCatalog["AgentActivity"])} />;

    case "QuickActions":
      return (
        <QuickActions
          {...(props as ComponentCatalog["QuickActions"])}
          onAction={callbacks?.onQuickAction}
        />
      );

    case "AlertCard":
      return (
        <AlertCard
          {...(props as ComponentCatalog["AlertCard"])}
          onAction={callbacks?.onAlertAction}
        />
      );

    case "ChartView":
      return <ChartView {...(props as ComponentCatalog["ChartView"])} />;

    case "InvoiceView":
      return <InvoiceView {...(props as ComponentCatalog["InvoiceView"])} />;

    case "OnboardingStep":
      return (
        <OnboardingStep
          {...(props as ComponentCatalog["OnboardingStep"])}
          onCta={callbacks?.onOnboardingCta}
        />
      );

    case "SettingsPanel":
      return (
        <SettingsPanel
          {...(props as ComponentCatalog["SettingsPanel"])}
          onFieldChange={callbacks?.onSettingsChange}
        />
      );

    default:
      // TypeScript exhaustive check — this branch should never be reached
      return null;
  }
}

// ─── Full response renderer ───────────────────────────────────────────────

interface GenerativeUIRendererProps {
  /** Validated AIResponse from catalog-validator.validate() */
  response: AIResponse;
  callbacks?: GenerativeUIRendererCallbacks;
  className?: string;
}

/**
 * Renders the components[] array from a validated AIResponse.
 * Text content is NOT rendered here — the caller (ChatStream / MessageBubble)
 * renders the text field via MarkdownRenderer.
 *
 * Returns null if no components are present.
 */
export function GenerativeUIRenderer({
  response,
  callbacks,
  className,
}: GenerativeUIRendererProps) {
  const { components } = response;

  if (!components || components.length === 0) return null;

  return (
    <div className={`flex flex-col gap-3 mt-2 ${className ?? ""}`}>
      {components.map((spec, i) => (
        <SpecRenderer key={`${spec.type}-${i}`} spec={spec} callbacks={callbacks} />
      ))}
    </div>
  );
}

// ─── Inline hook for chat stream integration ──────────────────────────────

/**
 * useGenerativeUI
 *
 * Provides a stable renderComponents function for use inside ChatStream.
 * Memoized — only re-creates when callbacks change.
 *
 * Usage:
 *   const { renderComponents } = useGenerativeUI({ onQuickAction: sendMessage });
 *   // In your render: {renderComponents(validatedResponse)}
 */
export function useGenerativeUI(callbacks?: GenerativeUIRendererCallbacks) {
  const renderComponents = useCallback(
    (response: AIResponse | null, className?: string) => {
      if (!response) return null;
      return (
        <GenerativeUIRenderer
          response={response}
          callbacks={callbacks}
          className={className}
        />
      );
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      callbacks?.onQuickAction,
      callbacks?.onAlertAction,
      callbacks?.onOnboardingCta,
      callbacks?.onSettingsChange,
    ]
  );

  return { renderComponents };
}
