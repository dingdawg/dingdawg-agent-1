"use client";

/**
 * StepTemplate — Step 2 of the onboarding wizard.
 *
 * Renders a scrollable list of templates filtered to the selected sector.
 * Each template card shows:
 *   - Emoji icon
 *   - Template name
 *   - Capabilities list (short, truncated)
 *   - "Popular" badge for the top 2 per sector
 *
 * Tapping a card selects it with gold highlight.
 * Loading state: 4 shimmer skeleton cards.
 */

export interface TemplateItem {
  id: string;
  name: string;
  agent_type: string;
  industry_type?: string | null;
  capabilities: string;  // JSON array string from backend
  icon?: string | null;
}

interface StepTemplateProps {
  templates: TemplateItem[];
  selectedTemplateId: string | null;
  onSelect: (template: TemplateItem) => void;
  isLoading: boolean;
  sectorName?: string;
}

/** Parse a JSON capabilities string safely. Returns up to 3 items. */
function parseCapabilities(caps: string): string[] {
  try {
    const parsed = JSON.parse(caps);
    if (Array.isArray(parsed)) {
      return parsed.slice(0, 3).map(String);
    }
  } catch {
    // ignore parse errors
  }
  return [];
}

export function StepTemplate({
  templates,
  selectedTemplateId,
  onSelect,
  isLoading,
  sectorName,
}: StepTemplateProps) {
  if (isLoading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="h-16 rounded-2xl bg-white/5 animate-pulse border border-white/8"
          />
        ))}
      </div>
    );
  }

  if (templates.length === 0) {
    return (
      <div className="py-10 text-center text-[var(--color-muted)]">
        <p className="text-2xl mb-2">🔍</p>
        <p className="text-sm">
          No templates available for{" "}
          <span className="text-[var(--foreground)]">{sectorName ?? "this sector"}</span>
          .
        </p>
        <p className="text-xs mt-1 opacity-60">More coming soon!</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 max-h-64 overflow-y-auto scrollbar-thin pr-0.5">
      {templates.map((template, idx) => {
        const isSelected = selectedTemplateId === template.id;
        const caps = parseCapabilities(template.capabilities);
        // Mark first 2 templates as "popular" picks for the sector
        const isPopular = idx < 2;

        return (
          <button
            key={template.id}
            onClick={() => onSelect(template)}
            className={`
              relative w-full text-left p-3.5 rounded-2xl border transition-all duration-150
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)]
              ${
                isSelected
                  ? "border-[var(--gold-500)] bg-[var(--gold-500)]/10"
                  : "border-[var(--stroke)] bg-white/3 hover:border-white/25 hover:bg-white/5 active:scale-[0.99]"
              }
            `}
            aria-pressed={isSelected}
            aria-label={`Select ${template.name} template`}
          >
            <div className="flex items-start gap-3">
              {/* Icon */}
              <span
                className="text-xl leading-none mt-0.5 flex-shrink-0"
                role="img"
                aria-hidden="true"
              >
                {template.icon ?? "🤖"}
              </span>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <p
                    className={`text-sm font-semibold truncate ${
                      isSelected
                        ? "text-[var(--gold-500)]"
                        : "text-[var(--foreground)]"
                    }`}
                  >
                    {template.name}
                  </p>
                  {isPopular && (
                    <span className="inline-flex items-center px-1.5 py-0.5 rounded-full bg-[var(--gold-500)]/15 text-[var(--gold-500)] text-[9px] font-bold leading-none border border-[var(--gold-500)]/30">
                      POPULAR
                    </span>
                  )}
                </div>
                {caps.length > 0 && (
                  <p className="text-[11px] text-[var(--color-muted)] mt-0.5 truncate">
                    {caps.join(" · ")}
                  </p>
                )}
              </div>

              {/* Selected checkmark */}
              {isSelected && (
                <svg
                  className="h-4 w-4 text-[var(--gold-500)] flex-shrink-0 mt-0.5"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2.5}
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M5 13l4 4L19 7"
                  />
                </svg>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}
