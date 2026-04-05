"use client";

/**
 * Horizontal pill buttons for quick replies below agent messages.
 */

interface QuickRepliesProps {
  options: string[];
  onSelect: (option: string) => void;
  disabled?: boolean;
}

export function QuickReplies({
  options,
  onSelect,
  disabled = false,
}: QuickRepliesProps) {
  return (
    <div className="flex flex-wrap gap-2 card-enter-delay-1">
      {options.map((option) => (
        <button
          key={option}
          onClick={() => onSelect(option)}
          disabled={disabled}
          className="px-4 py-2 rounded-full text-sm font-medium border border-[var(--color-gold-stroke)] bg-white/5 text-[var(--foreground)] hover:bg-[var(--gold-500)]/10 hover:border-[var(--gold-500)]/30 hover:text-[var(--gold-500)] transition-all disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {option}
        </button>
      ))}
    </div>
  );
}
