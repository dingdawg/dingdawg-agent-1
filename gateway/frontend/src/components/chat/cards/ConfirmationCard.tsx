"use client";

/**
 * ConfirmationCard — Yes/No decision prompt rendered in the chat stream.
 *
 * Variants:
 *   default → gold confirm button (standard action)
 *   danger  → red confirm button (destructive action)
 *
 * Both buttons meet 48px minimum touch target height.
 * Custom button labels supported via confirmLabel / cancelLabel props.
 */

import { AlertTriangle, HelpCircle } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ConfirmationCardProps {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  variant?: "default" | "danger";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ConfirmationCard({
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  onConfirm,
  onCancel,
  variant = "default",
}: ConfirmationCardProps) {
  const isDanger = variant === "danger";

  return (
    <div className="glass-panel-gold p-4 card-enter">
      {/* Icon + title */}
      <div className="flex items-start gap-3 mb-3">
        <div
          className={[
            "h-9 w-9 rounded-xl flex items-center justify-center flex-shrink-0",
            isDanger
              ? "bg-red-500/15"
              : "bg-[var(--gold-500)]/15",
          ].join(" ")}
        >
          {isDanger ? (
            <AlertTriangle
              className="h-4 w-4 text-red-400"
            />
          ) : (
            <HelpCircle
              className="h-4 w-4 text-[var(--gold-500)]"
            />
          )}
        </div>

        <div className="flex-1 min-w-0">
          <p className="text-sm font-heading font-semibold text-[var(--foreground)]">
            {title}
          </p>
          {description && (
            <p className="text-xs text-[var(--color-muted)] mt-1">{description}</p>
          )}
        </div>
      </div>

      {/* Divider */}
      <div className="border-t border-[var(--color-gold-stroke)] mb-4" />

      {/* Action buttons */}
      <div className="flex gap-2">
        {/* Cancel button */}
        <button
          onClick={onCancel}
          className={
            "flex-1 min-h-12 py-3 px-4 rounded-xl text-sm font-semibold font-heading " +
            "bg-white/5 text-[var(--color-muted)] border border-[var(--color-gold-stroke)] " +
            "hover:bg-white/10 hover:text-[var(--foreground)] transition-all active:scale-[0.98]"
          }
        >
          {cancelLabel}
        </button>

        {/* Confirm button */}
        <button
          onClick={onConfirm}
          className={[
            "flex-1 min-h-12 py-3 px-4 rounded-xl text-sm font-semibold font-heading",
            "transition-all active:scale-[0.98]",
            isDanger
              ? "bg-red-500/80 text-white hover:bg-red-500 border border-red-500/30 danger"
              : "bg-[var(--gold-500)] text-[#07111c] hover:bg-[var(--gold-600)]",
          ].join(" ")}
        >
          {confirmLabel}
        </button>
      </div>
    </div>
  );
}
