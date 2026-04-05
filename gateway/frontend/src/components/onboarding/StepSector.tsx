"use client";

/**
 * StepSector — Step 1 of the onboarding wizard.
 *
 * Renders a visual grid of 8 sectors.  Each card shows:
 *   - Large emoji icon
 *   - Sector name
 *   - Short description
 *   - "Popular" badge for top picks
 *
 * Tapping a card immediately selects it (highlighted with gold border).
 * The parent page advances to step 2 on selection via `onSelect`.
 *
 * Layout:
 *   Mobile:  2 columns grid (390px viewport)
 *   Tablet+: 4 columns grid
 *
 * Touch targets: minimum 44px height guaranteed by the p-3/p-4 padding.
 */

export interface SectorItem {
  id: string;
  name: string;
  agent_type: string;
  icon: string;
  description: string;
  popular?: boolean;
}

interface StepSectorProps {
  sectors: SectorItem[];
  selectedSectorId: string | null;
  onSelect: (sector: SectorItem) => void;
  isLoading: boolean;
}

export function StepSector({
  sectors,
  selectedSectorId,
  onSelect,
  isLoading,
}: StepSectorProps) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="h-24 rounded-2xl bg-white/5 animate-pulse border border-white/8"
          />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
      {sectors.map((sector) => {
        const isSelected = selectedSectorId === sector.id;
        return (
          <button
            key={sector.id}
            onClick={() => onSelect(sector)}
            className={`
              relative flex flex-col items-center gap-2 p-3 rounded-2xl border
              text-center transition-all duration-150 min-h-[88px]
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)]
              ${
                isSelected
                  ? "border-[var(--gold-500)] bg-[var(--gold-500)]/10 shadow-[0_0_0_1px_var(--gold-500)]"
                  : "border-[var(--stroke)] bg-white/3 hover:border-white/25 hover:bg-white/5 active:scale-95"
              }
            `}
            aria-pressed={isSelected}
            aria-label={`Select ${sector.name} sector`}
          >
            {/* Popular badge */}
            {sector.popular && (
              <span className="absolute -top-1.5 -right-1.5 px-1.5 py-0.5 rounded-full bg-[var(--gold-500)] text-black text-[9px] font-bold leading-none">
                HOT
              </span>
            )}

            {/* Icon */}
            <span
              className="text-2xl leading-none"
              role="img"
              aria-hidden="true"
            >
              {sector.icon}
            </span>

            {/* Name */}
            <p
              className={`text-xs font-semibold leading-tight ${
                isSelected
                  ? "text-[var(--gold-500)]"
                  : "text-[var(--foreground)]"
              }`}
            >
              {sector.name}
            </p>
          </button>
        );
      })}
    </div>
  );
}
