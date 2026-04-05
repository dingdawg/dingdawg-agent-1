"use client";

/**
 * MapCard — static location display within the chat stream.
 *
 * Shows a label (optional), address, and a "Get Directions" link that
 * opens Google Maps in a new tab. No Google Maps API key required —
 * the URL encodes the address or coordinates directly.
 *
 * No external map library dependency.
 */

import { MapPin, ExternalLink } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MapCardProps {
  address: string;
  lat?: number;
  lng?: number;
  label?: string;
  onDirections?: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildMapsUrl(address: string, lat?: number, lng?: number): string {
  if (lat !== undefined && lng !== undefined) {
    // Coordinate-based query is more accurate
    return `https://www.google.com/maps/search/?api=1&query=${lat},${lng}`;
  }
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address)}`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MapCard({
  address,
  lat,
  lng,
  label,
  onDirections,
}: MapCardProps) {
  const mapsUrl = buildMapsUrl(address, lat, lng);

  const handleDirections = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (onDirections) {
      e.preventDefault();
      onDirections();
    }
    // If no onDirections callback, default anchor behavior (opens in new tab) takes over
  };

  return (
    <div className="glass-panel-gold p-4 card-enter">
      {/* Label */}
      {label && (
        <p className="text-xs font-medium text-[var(--gold-500)] uppercase tracking-wider mb-2">
          {label}
        </p>
      )}

      {/* Address row */}
      <div className="flex items-start gap-3">
        <div className="h-9 w-9 rounded-xl bg-[var(--gold-500)]/15 flex items-center justify-center flex-shrink-0 mt-0.5">
          <MapPin className="h-4 w-4 text-[var(--gold-500)]" />
        </div>

        <div className="flex-1 min-w-0">
          <p className="text-sm text-[var(--foreground)] leading-snug">{address}</p>
        </div>
      </div>

      {/* Divider */}
      <div className="border-t border-[var(--color-gold-stroke)] mt-3 mb-3" />

      {/* Directions link */}
      <a
        href={mapsUrl}
        target="_blank"
        rel="noopener noreferrer"
        onClick={handleDirections}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-[var(--gold-500)] hover:text-[var(--gold-600)] transition-colors"
      >
        <ExternalLink className="h-3.5 w-3.5" />
        Get Directions
      </a>
    </div>
  );
}
