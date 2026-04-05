"use client";

/**
 * Card Registry — centralized map of card type strings to React components.
 *
 * New card types are registered here and can be looked up by any renderer
 * without importing all components directly. This decouples ChatStream.tsx
 * from future card additions.
 *
 * Existing 5 types: kpi | task | taskList | quickReplies | agentStatus
 * New 7 types: form | payment | calendar | map | media | progress | confirmation
 * New 1 type:  healthStatus
 */

import type { ComponentType } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type CardType =
  // Existing 5
  | "kpi"
  | "task"
  | "taskList"
  | "quickReplies"
  | "agentStatus"
  // New 7
  | "form"
  | "payment"
  | "calendar"
  | "map"
  | "media"
  | "progress"
  | "confirmation"
  | "healthStatus";

export interface CardRegistryEntry {
  /** The React component that renders this card type. */
  component: ComponentType<any>;
  /** Human-readable name used for dev tooling and debugging. */
  displayName: string;
  /** Logical grouping for filtering and UI organisation. */
  category: "data" | "action" | "input" | "status";
}

// ---------------------------------------------------------------------------
// Internal registry store
// ---------------------------------------------------------------------------

const _registry = new Map<CardType, CardRegistryEntry>();

/**
 * Read-only reference to the underlying registry map.
 * Use registerCard/getCard/getAllCards for mutations and lookups.
 */
export const cardRegistry = _registry;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Registers a card type with its component and metadata.
 * Calling registerCard with an already-registered type overwrites the entry.
 */
export function registerCard(type: CardType, entry: CardRegistryEntry): void {
  _registry.set(type, entry);
}

/**
 * Retrieves a card registry entry by type.
 * Returns undefined if the type has not been registered.
 */
export function getCard(type: CardType): CardRegistryEntry | undefined {
  return _registry.get(type);
}

/**
 * Returns the full registry map.
 * Callers receive the live map reference — do not mutate it directly.
 */
export function getAllCards(): Map<CardType, CardRegistryEntry> {
  return _registry;
}

// ---------------------------------------------------------------------------
// Bootstrap — register all known card types on module load
// ---------------------------------------------------------------------------

// Lazy-import existing cards (avoid circular deps — these are already wired in ChatStream)
// We register them with placeholder components so the registry is type-safe.
// Real components are imported and registered at the bottom of this file to
// ensure we have one canonical source of truth.

import { KPICards } from "./KPICards";
import { TaskCard } from "./TaskCard";
import { TaskListCard } from "./TaskListCard";
import { QuickReplies } from "./QuickReplies";
import { AgentStatusCard } from "./AgentStatusCard";
import { FormCard } from "./FormCard";
import { PaymentCard } from "./PaymentCard";
import { CalendarCard } from "./CalendarCard";
import { MapCard } from "./MapCard";
import { MediaCard } from "./MediaCard";
import { ProgressCard } from "./ProgressCard";
import { ConfirmationCard } from "./ConfirmationCard";
import { HealthStatusCard } from "./HealthStatusCard";

// Existing 5
registerCard("kpi", {
  component: KPICards,
  displayName: "KPICards",
  category: "data",
});

registerCard("task", {
  component: TaskCard,
  displayName: "TaskCard",
  category: "status",
});

registerCard("taskList", {
  component: TaskListCard,
  displayName: "TaskListCard",
  category: "status",
});

registerCard("quickReplies", {
  component: QuickReplies,
  displayName: "QuickReplies",
  category: "action",
});

registerCard("agentStatus", {
  component: AgentStatusCard,
  displayName: "AgentStatusCard",
  category: "status",
});

// New 7
registerCard("form", {
  component: FormCard,
  displayName: "FormCard",
  category: "input",
});

registerCard("payment", {
  component: PaymentCard,
  displayName: "PaymentCard",
  category: "action",
});

registerCard("calendar", {
  component: CalendarCard,
  displayName: "CalendarCard",
  category: "input",
});

registerCard("map", {
  component: MapCard,
  displayName: "MapCard",
  category: "data",
});

registerCard("media", {
  component: MediaCard,
  displayName: "MediaCard",
  category: "data",
});

registerCard("progress", {
  component: ProgressCard,
  displayName: "ProgressCard",
  category: "status",
});

registerCard("confirmation", {
  component: ConfirmationCard,
  displayName: "ConfirmationCard",
  category: "action",
});

registerCard("healthStatus", {
  component: HealthStatusCard,
  displayName: "HealthStatusCard",
  category: "status",
});
