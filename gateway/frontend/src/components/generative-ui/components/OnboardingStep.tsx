"use client";

import { CheckCircle2, Circle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { OnboardingStepProps } from "../catalog";

interface OnboardingStepComponentProps extends OnboardingStepProps {
  onCta?: () => void;
}

export function OnboardingStep({
  step,
  totalSteps,
  title,
  description,
  completed,
  cta,
  onCta,
}: OnboardingStepComponentProps) {
  return (
    <div className="glass-panel-gold rounded-xl p-4 space-y-3 card-enter">
      {/* Step indicator */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {completed ? (
            <CheckCircle2 className="h-5 w-5 text-green-400 shrink-0" />
          ) : (
            <div className="h-5 w-5 rounded-full border-2 border-[var(--gold-500)] flex items-center justify-center shrink-0">
              <span className="text-xs font-bold text-[var(--gold-500)]">{step}</span>
            </div>
          )}
          <span
            className={cn(
              "text-sm font-heading font-semibold",
              completed ? "text-green-400" : "text-[var(--foreground)]"
            )}
          >
            {title}
          </span>
        </div>
        {totalSteps && (
          <span className="text-xs text-[var(--color-muted)]">
            {step} / {totalSteps}
          </span>
        )}
      </div>

      {/* Progress bar */}
      {totalSteps && (
        <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
          <div
            className="h-full bg-[var(--gold-500)] rounded-full transition-all duration-500"
            style={{ width: `${(step / totalSteps) * 100}%` }}
          />
        </div>
      )}

      {/* Description */}
      <p className="text-sm font-body text-[var(--color-muted)] leading-relaxed">
        {description}
      </p>

      {/* CTA */}
      {cta && !completed && (
        <button
          onClick={onCta}
          className="px-4 py-2 rounded-lg text-sm font-medium bg-[var(--gold-500)] hover:bg-[var(--gold-500)]/90 text-black transition-colors min-h-[44px]"
        >
          {cta}
        </button>
      )}
    </div>
  );
}
