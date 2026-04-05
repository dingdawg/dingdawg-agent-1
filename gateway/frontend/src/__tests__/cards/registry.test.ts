/**
 * registry.test.ts — Card Registry unit tests (TDD RED phase)
 *
 * 6 tests covering registration, retrieval, and category behavior.
 *
 * Run: npx vitest run src/__tests__/cards/registry.test.ts
 */

import { describe, it, expect, beforeEach } from "vitest";
import {
  cardRegistry,
  registerCard,
  getCard,
  getAllCards,
} from "../../components/chat/cards/registry";
import type { CardType, CardRegistryEntry } from "../../components/chat/cards/registry";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const makeMockEntry = (
  displayName: string,
  category: CardRegistryEntry["category"]
): CardRegistryEntry => ({
  component: () => null,
  displayName,
  category,
});

// ---------------------------------------------------------------------------
// Registry tests
// ---------------------------------------------------------------------------

describe("Card Registry", () => {
  it("registers a card and retrieves it by type", () => {
    // Use a safe custom type cast to test registration API generically
    const testType = "confirmation" as CardType;
    const entry = makeMockEntry("ConfirmationCard", "action");

    registerCard(testType, entry);
    const retrieved = getCard(testType);

    expect(retrieved).toBeDefined();
    expect(retrieved?.displayName).toBe("ConfirmationCard");
    expect(retrieved?.category).toBe("action");
  });

  it("returns undefined for an unknown card type", () => {
    const unknown = getCard("nonexistent" as CardType);
    expect(unknown).toBeUndefined();
  });

  it("getAllCards returns a map containing all registered cards", () => {
    const all = getAllCards();
    expect(all).toBeInstanceOf(Map);
    expect(all.size).toBeGreaterThanOrEqual(12); // 5 existing + 7 new
  });

  it("all 5 existing card types are registered", () => {
    const existingTypes: CardType[] = ["kpi", "task", "taskList", "quickReplies", "agentStatus"];
    for (const type of existingTypes) {
      const entry = getCard(type);
      expect(entry).toBeDefined();
      expect(entry?.displayName).toBeTruthy();
    }
  });

  it("all 7 new card types are registered", () => {
    const newTypes: CardType[] = [
      "form",
      "payment",
      "calendar",
      "map",
      "media",
      "progress",
      "confirmation",
    ];
    for (const type of newTypes) {
      const entry = getCard(type);
      expect(entry).toBeDefined();
      expect(entry?.displayName).toBeTruthy();
    }
  });

  it("can filter cards by category from the full map", () => {
    const all = getAllCards();
    const actionCards = Array.from(all.entries()).filter(
      ([, entry]) => entry.category === "action"
    );
    // confirmation and payment are 'action' category
    expect(actionCards.length).toBeGreaterThanOrEqual(2);

    const inputCards = Array.from(all.entries()).filter(
      ([, entry]) => entry.category === "input"
    );
    // form, calendar are 'input' category
    expect(inputCards.length).toBeGreaterThanOrEqual(2);
  });
});
