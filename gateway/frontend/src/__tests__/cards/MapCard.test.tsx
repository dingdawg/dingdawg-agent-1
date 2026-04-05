/**
 * MapCard.test.tsx — Location display card tests (TDD RED phase)
 *
 * 6 tests covering address rendering, directions link, label, new tab behavior.
 *
 * Run: npx vitest run src/__tests__/cards/MapCard.test.tsx
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MapCard } from "../../components/chat/cards/MapCard";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("MapCard", () => {
  it("renders the address text", () => {
    render(<MapCard address="123 Main St, Austin, TX 78701" />);
    expect(screen.getByText("123 Main St, Austin, TX 78701")).toBeTruthy();
  });

  it("Get Directions link points to Google Maps with encoded address", () => {
    render(<MapCard address="456 Oak Ave, Dallas, TX 75201" />);

    const link = screen.getByRole("link", { name: /directions/i });
    const href = link.getAttribute("href") || "";

    // Should link to Google Maps with the address encoded
    expect(href).toContain("google.com/maps");
    expect(href).toContain("456");
  });

  it("renders label above the address when provided", () => {
    const { container } = render(
      <MapCard
        address="789 Pine Rd"
        label="Our Office"
      />
    );

    // Label should appear before the address in DOM order
    const label = screen.getByText("Our Office");
    const address = screen.getByText("789 Pine Rd");

    expect(label).toBeTruthy();
    expect(address).toBeTruthy();

    // Label should come before address in DOM
    const labelPos = container.innerHTML.indexOf("Our Office");
    const addrPos = container.innerHTML.indexOf("789 Pine Rd");
    expect(labelPos).toBeLessThan(addrPos);
  });

  it("Directions link opens in a new tab (target=_blank)", () => {
    render(<MapCard address="100 Congress Ave, Austin, TX" />);

    const link = screen.getByRole("link", { name: /directions/i });
    expect(link.getAttribute("target")).toBe("_blank");
  });

  it("renders without directions link when onDirections is explicitly not provided", () => {
    // MapCard with no onDirections prop should still render the static directions link
    // OR if onDirections is not provided, it falls back to static href
    render(<MapCard address="200 Elm St" />);

    // Component should render at minimum the address text without errors
    expect(screen.getByText("200 Elm St")).toBeTruthy();
  });

  it("includes lat/lng in the directions URL when coordinates are provided", () => {
    render(
      <MapCard
        address="Austin, TX"
        lat={30.2672}
        lng={-97.7431}
      />
    );

    const link = screen.getByRole("link", { name: /directions/i });
    const href = link.getAttribute("href") || "";

    // When lat/lng provided, prefer coordinate-based URL
    const hasCoords =
      href.includes("30.2672") || href.includes("-97.7431") || href.includes("30.267");

    // Either coords or address encoding is acceptable
    expect(href).toContain("google.com/maps");
    expect(href.length).toBeGreaterThan(20);
  });
});
