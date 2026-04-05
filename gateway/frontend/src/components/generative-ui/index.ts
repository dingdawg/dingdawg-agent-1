/**
 * Generative UI barrel export
 *
 * Public surface for the json-render pattern.
 * Import from "@/components/generative-ui" throughout the app.
 */

// Catalog types
export type {
  ComponentCatalog,
  ComponentType,
  AIResponse,
  GenerativeUISpec,
  BookingSummaryProps,
  StatsGridProps,
  ClientListProps,
  AgentActivityProps,
  QuickActionsProps,
  AlertCardProps,
  ChartViewProps,
  InvoiceViewProps,
  OnboardingStepProps,
  SettingsPanelProps,
} from "./catalog";

export { PERMITTED_COMPONENT_TYPES } from "./catalog";

// Validator
export type { ValidationResult, ValidationSuccess, ValidationError } from "./catalog-validator";
export { validate, validateSpec, parseAndValidate } from "./catalog-validator";

// Renderer + hook
export type { GenerativeUIRendererCallbacks } from "./GenerativeUIRenderer";
export { GenerativeUIRenderer, useGenerativeUI } from "./GenerativeUIRenderer";

// Individual components (for direct use outside chat stream)
export { BookingSummary } from "./components/BookingSummary";
export { StatsGrid } from "./components/StatsGrid";
export { ClientList } from "./components/ClientList";
export { AgentActivity } from "./components/AgentActivity";
export { QuickActions } from "./components/QuickActions";
export { AlertCard } from "./components/AlertCard";
export { ChartView } from "./components/ChartView";
export { InvoiceView } from "./components/InvoiceView";
export { OnboardingStep } from "./components/OnboardingStep";
export { SettingsPanel } from "./components/SettingsPanel";
