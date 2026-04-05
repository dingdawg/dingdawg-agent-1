/**
 * Generative UI Component Catalog
 *
 * Canonical TypeScript interfaces for every component MiLA is allowed to emit.
 * The catalog IS the constraint — MiLA can only reference component types
 * defined here. Unknown types fall back to plain text in the renderer.
 *
 * AI NEVER generates raw HTML — only JSON specs conforming to these interfaces.
 */

// ─── Individual component prop interfaces ──────────────────────────────────

export interface BookingSummaryProps {
  total: number;
  completed: number;
  upcoming: {
    id: string;
    clientName: string;
    service: string;
    date: string;
    time: string;
  }[];
}

export interface StatsGridProps {
  metrics: {
    label: string;
    value: string | number;
    trend?: "up" | "down" | "flat";
    trendValue?: string;
    unit?: string;
  }[];
}

export interface ClientListProps {
  clients: {
    id: string;
    name: string;
    status: "active" | "inactive" | "pending";
    lastVisit?: string;
    email?: string;
    phone?: string;
  }[];
  title?: string;
}

export interface AgentActivityProps {
  actions: {
    type: "task" | "message" | "booking" | "payment" | "alert" | "system";
    description: string;
    timestamp: string;
    status?: "success" | "pending" | "failed";
  }[];
  title?: string;
}

export interface QuickActionsProps {
  actions: string[];
  title?: string;
}

export interface AlertCardProps {
  severity: "info" | "warning" | "error" | "success";
  title: string;
  message: string;
  action?: {
    label: string;
    payload: string;
  };
}

export interface ChartViewProps {
  type: "bar" | "line" | "pie" | "area";
  data: number[];
  labels: string[];
  title?: string;
  color?: string;
}

export interface InvoiceViewProps {
  invoiceNumber?: string;
  clientName?: string;
  items: {
    description: string;
    quantity: number;
    unitPrice: number;
    total: number;
  }[];
  subtotal?: number;
  tax?: number;
  total: number;
  status: "draft" | "pending" | "paid" | "overdue";
  dueDate?: string;
}

export interface OnboardingStepProps {
  step: number;
  totalSteps?: number;
  title: string;
  description: string;
  completed: boolean;
  cta?: string;
}

export interface SettingsPanelProps {
  sections: {
    name: string;
    fields: {
      key: string;
      label: string;
      type: "text" | "toggle" | "select" | "number";
      value: string | boolean | number;
      options?: string[];
      description?: string;
    }[];
  }[];
  title?: string;
}

// ─── Component Catalog — union of all supported types ─────────────────────

export interface ComponentCatalog {
  BookingSummary: BookingSummaryProps;
  StatsGrid: StatsGridProps;
  ClientList: ClientListProps;
  AgentActivity: AgentActivityProps;
  QuickActions: QuickActionsProps;
  AlertCard: AlertCardProps;
  ChartView: ChartViewProps;
  InvoiceView: InvoiceViewProps;
  OnboardingStep: OnboardingStepProps;
  SettingsPanel: SettingsPanelProps;
}

export type ComponentType = keyof ComponentCatalog;

// ─── AI Response Spec Shape ────────────────────────────────────────────────

/**
 * The structured spec MiLA emits in every response.
 * text  → rendered as markdown
 * components → rendered as live UI components inline in the chat stream
 */
export interface GenerativeUISpec {
  type: ComponentType;
  props: ComponentCatalog[ComponentType];
}

export interface AIResponse {
  text: string;
  components?: GenerativeUISpec[];
}

// ─── Governance catalog listing ────────────────────────────────────────────

/**
 * Enumerated list of all permitted component types.
 * Used by the validator and renderer as the whitelist.
 */
export const PERMITTED_COMPONENT_TYPES: readonly ComponentType[] = [
  "BookingSummary",
  "StatsGrid",
  "ClientList",
  "AgentActivity",
  "QuickActions",
  "AlertCard",
  "ChartView",
  "InvoiceView",
  "OnboardingStep",
  "SettingsPanel",
] as const;
