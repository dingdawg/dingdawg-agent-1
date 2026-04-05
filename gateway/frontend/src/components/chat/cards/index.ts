/**
 * Barrel export for all chat card components.
 *
 * Existing 5 cards:
 *   KPICards, TaskCard, TaskListCard, QuickReplies, AgentStatusCard
 *
 * New 7 cards (item 2.4):
 *   FormCard, PaymentCard, CalendarCard, MapCard, MediaCard, ProgressCard, ConfirmationCard
 *
 * Registry:
 *   cardRegistry, registerCard, getCard, getAllCards
 */

// ---------------------------------------------------------------------------
// Existing cards
// ---------------------------------------------------------------------------
export { KPICards } from "./KPICards";
export type { KPIMetric } from "./KPICards";

export { TaskCard } from "./TaskCard";
export type { TaskCardData } from "./TaskCard";

export { TaskListCard } from "./TaskListCard";

export { QuickReplies } from "./QuickReplies";

export { AgentStatusCard } from "./AgentStatusCard";
export type { AgentInfo } from "./AgentStatusCard";

// ---------------------------------------------------------------------------
// New cards (item 2.4)
// ---------------------------------------------------------------------------
export { FormCard } from "./FormCard";
export type { FormField } from "./FormCard";

export { PaymentCard } from "./PaymentCard";
export type { PaymentStatus } from "./PaymentCard";

export { CalendarCard } from "./CalendarCard";
export type { DateSlot } from "./CalendarCard";

export { MapCard } from "./MapCard";

export { MediaCard } from "./MediaCard";
export type { MediaItem } from "./MediaCard";

export { ProgressCard } from "./ProgressCard";
export type { ProgressStep } from "./ProgressCard";

export { ConfirmationCard } from "./ConfirmationCard";

export { HealthStatusCard } from "./HealthStatusCard";
export type { HealthStatusData, HealthIncident, CircuitStatus } from "./HealthStatusCard";

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------
export { cardRegistry, registerCard, getCard, getAllCards } from "./registry";
export type { CardType, CardRegistryEntry } from "./registry";
