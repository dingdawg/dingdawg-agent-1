"use client";

/**
 * OnboardingProgress — animated progress bar + step label for the claim wizard.
 *
 * Shows a thin progress bar across the top of the claim card, filling as the
 * user advances through steps.  Each step is labeled with a short title so
 * users always know where they are in the flow.
 *
 * Usage:
 *   <OnboardingProgress currentStep={1} totalSteps={3} labels={["Sector", "Template", "Handle"]} />
 */

interface OnboardingProgressProps {
  /** Zero-based current step index (0 = first step). */
  currentStep: number;
  /** Total number of steps in the flow. */
  totalSteps: number;
  /** Short label for each step — shown under the progress bar. */
  labels?: string[];
}

export function OnboardingProgress({
  currentStep,
  totalSteps,
  labels,
}: OnboardingProgressProps) {
  const pct = Math.round(((currentStep + 1) / totalSteps) * 100);

  return (
    <div className="w-full mb-6">
      {/* Step counter */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-[var(--color-muted)] font-medium tracking-wide uppercase">
          Step {currentStep + 1} of {totalSteps}
        </span>
        {labels && labels[currentStep] && (
          <span className="text-xs font-medium text-[var(--gold-500)]">
            {labels[currentStep]}
          </span>
        )}
      </div>

      {/* Progress track */}
      <div
        className="w-full h-1.5 bg-white/8 rounded-full overflow-hidden"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Step ${currentStep + 1} of ${totalSteps}`}
      >
        <div
          className="h-full bg-[var(--gold-500)] rounded-full transition-all duration-400 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Step dots */}
      {labels && (
        <div className="flex items-start justify-between mt-2 px-0.5">
          {labels.map((label, i) => (
            <div key={i} className="flex flex-col items-center gap-1 min-w-0">
              <div
                className={`w-2 h-2 rounded-full transition-all duration-300 ${
                  i < currentStep
                    ? "bg-[var(--gold-500)] opacity-60"
                    : i === currentStep
                    ? "bg-[var(--gold-500)] scale-125"
                    : "bg-white/15"
                }`}
              />
              <span
                className={`text-[10px] hidden sm:block truncate transition-colors ${
                  i === currentStep
                    ? "text-[var(--gold-500)] font-medium"
                    : i < currentStep
                    ? "text-[var(--color-muted)] opacity-70"
                    : "text-[var(--color-muted)] opacity-40"
                }`}
              >
                {label}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
