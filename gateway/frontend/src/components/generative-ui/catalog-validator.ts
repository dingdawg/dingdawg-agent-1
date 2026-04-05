/**
 * Catalog Validator
 *
 * Zod schemas for every component in the GenerativeUI catalog.
 * validate(spec) returns a validated spec or a typed error.
 *
 * GOVERNANCE RULE: Never render unvalidated specs. All AI output
 * passes through validate() before reaching the renderer.
 */

import { z } from "zod";
import type { AIResponse, GenerativeUISpec } from "./catalog";

// ─── Individual component schemas ─────────────────────────────────────────

const BookingSummarySchema = z.object({
  total: z.number().int().nonnegative(),
  completed: z.number().int().nonnegative(),
  upcoming: z.array(
    z.object({
      id: z.string(),
      clientName: z.string().min(1),
      service: z.string().min(1),
      date: z.string().min(1),
      time: z.string().min(1),
    })
  ),
});

const StatsGridSchema = z.object({
  metrics: z
    .array(
      z.object({
        label: z.string().min(1),
        value: z.union([z.string(), z.number()]),
        trend: z.enum(["up", "down", "flat"]).optional(),
        trendValue: z.string().optional(),
        unit: z.string().optional(),
      })
    )
    .min(1),
});

const ClientListSchema = z.object({
  clients: z
    .array(
      z.object({
        id: z.string(),
        name: z.string().min(1),
        status: z.enum(["active", "inactive", "pending"]),
        lastVisit: z.string().optional(),
        email: z.string().email().optional(),
        phone: z.string().optional(),
      })
    )
    .min(1),
  title: z.string().optional(),
});

const AgentActivitySchema = z.object({
  actions: z
    .array(
      z.object({
        type: z.enum(["task", "message", "booking", "payment", "alert", "system"]),
        description: z.string().min(1),
        timestamp: z.string().min(1),
        status: z.enum(["success", "pending", "failed"]).optional(),
      })
    )
    .min(1),
  title: z.string().optional(),
});

const QuickActionsSchema = z.object({
  actions: z.array(z.string().min(1)).min(1).max(8),
  title: z.string().optional(),
});

const AlertCardSchema = z.object({
  severity: z.enum(["info", "warning", "error", "success"]),
  title: z.string().min(1),
  message: z.string().min(1),
  action: z
    .object({
      label: z.string().min(1),
      payload: z.string().min(1),
    })
    .optional(),
});

const ChartViewSchema = z.object({
  type: z.enum(["bar", "line", "pie", "area"]),
  data: z.array(z.number()).min(1),
  labels: z.array(z.string()).min(1),
  title: z.string().optional(),
  color: z.string().optional(),
});

const InvoiceViewSchema = z.object({
  invoiceNumber: z.string().optional(),
  clientName: z.string().optional(),
  items: z
    .array(
      z.object({
        description: z.string().min(1),
        quantity: z.number().nonnegative(),
        unitPrice: z.number().nonnegative(),
        total: z.number().nonnegative(),
      })
    )
    .min(1),
  subtotal: z.number().nonnegative().optional(),
  tax: z.number().nonnegative().optional(),
  total: z.number().nonnegative(),
  status: z.enum(["draft", "pending", "paid", "overdue"]),
  dueDate: z.string().optional(),
});

const OnboardingStepSchema = z.object({
  step: z.number().int().positive(),
  totalSteps: z.number().int().positive().optional(),
  title: z.string().min(1),
  description: z.string().min(1),
  completed: z.boolean(),
  cta: z.string().optional(),
});

const SettingsPanelSchema = z.object({
  sections: z
    .array(
      z.object({
        name: z.string().min(1),
        fields: z.array(
          z.object({
            key: z.string().min(1),
            label: z.string().min(1),
            type: z.enum(["text", "toggle", "select", "number"]),
            value: z.union([z.string(), z.boolean(), z.number()]),
            options: z.array(z.string()).optional(),
            description: z.string().optional(),
          })
        ),
      })
    )
    .min(1),
  title: z.string().optional(),
});

// ─── Catalog schema map ────────────────────────────────────────────────────

const SCHEMA_MAP = {
  BookingSummary: BookingSummarySchema,
  StatsGrid: StatsGridSchema,
  ClientList: ClientListSchema,
  AgentActivity: AgentActivitySchema,
  QuickActions: QuickActionsSchema,
  AlertCard: AlertCardSchema,
  ChartView: ChartViewSchema,
  InvoiceView: InvoiceViewSchema,
  OnboardingStep: OnboardingStepSchema,
  SettingsPanel: SettingsPanelSchema,
} as const;

// ─── GenerativeUISpec schema ───────────────────────────────────────────────

const GenerativeUISpecSchema = z.object({
  type: z.enum([
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
  ]),
  props: z.record(z.string(), z.unknown()),
});

const AIResponseSchema = z.object({
  text: z.string(),
  components: z.array(GenerativeUISpecSchema).optional(),
});

// ─── Validation result types ───────────────────────────────────────────────

export type ValidationSuccess<T> = {
  ok: true;
  data: T;
};

export type ValidationError = {
  ok: false;
  error: string;
  issues: string[];
};

export type ValidationResult<T> = ValidationSuccess<T> | ValidationError;

// ─── Public API ────────────────────────────────────────────────────────────

/**
 * Validate a single GenerativeUISpec (type + props).
 * Performs two-pass validation:
 *  1. type must be in the catalog
 *  2. props must match the component's Zod schema
 *
 * Returns a typed ValidationResult — never throws.
 */
export function validateSpec(
  raw: unknown
): ValidationResult<GenerativeUISpec> {
  // Pass 1: validate the outer shape (type field required)
  const outer = GenerativeUISpecSchema.safeParse(raw);
  if (!outer.success) {
    return {
      ok: false,
      error: "Invalid spec shape",
      issues: outer.error.issues.map((i) => i.message),
    };
  }

  const { type, props } = outer.data;

  // Pass 2: validate props against the component-specific schema
  const schema = SCHEMA_MAP[type as keyof typeof SCHEMA_MAP];
  if (!schema) {
    return {
      ok: false,
      error: `Unknown component type: ${type}`,
      issues: [`"${type}" is not in the component catalog`],
    };
  }

  const propsResult = schema.safeParse(props);
  if (!propsResult.success) {
    return {
      ok: false,
      error: `Invalid props for ${type}`,
      issues: propsResult.error.issues.map(
        (i) => `${i.path.join(".")}: ${i.message}`
      ),
    };
  }

  return {
    ok: true,
    data: { type: type as GenerativeUISpec["type"], props: propsResult.data as GenerativeUISpec["props"] },
  };
}

/**
 * Validate a full AIResponse (text + optional components array).
 * Each component spec is validated individually.
 * Invalid specs are dropped with a console warning — the text still renders.
 *
 * Returns a ValidationResult with a clean AIResponse.
 */
export function validate(raw: unknown): ValidationResult<AIResponse> {
  const outer = AIResponseSchema.safeParse(raw);
  if (!outer.success) {
    return {
      ok: false,
      error: "Invalid AIResponse shape",
      issues: outer.error.issues.map((i) => i.message),
    };
  }

  const validatedComponents: GenerativeUISpec[] = [];

  for (const spec of outer.data.components ?? []) {
    const result = validateSpec(spec);
    if (result.ok) {
      validatedComponents.push(result.data);
    } else {
      console.warn(
        `[GenerativeUI] Dropping invalid component spec:`,
        result.error,
        result.issues
      );
    }
  }

  return {
    ok: true,
    data: {
      text: outer.data.text,
      components: validatedComponents.length > 0 ? validatedComponents : undefined,
    },
  };
}

/**
 * Parse a raw JSON string from the AI stream into a validated AIResponse.
 * Returns null if the string is not valid JSON or fails schema validation.
 * Safe to call with any AI output — never throws.
 */
export function parseAndValidate(raw: string): AIResponse | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  const result = validate(parsed);
  return result.ok ? result.data : null;
}
