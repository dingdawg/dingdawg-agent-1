"use client";

/**
 * CommunityOnboardingWizard — 3-step onboarding flow for community businesses.
 *
 * Step 1: Choose Community Type (bodega, nail salon, taqueria, Haitian restaurant,
 *          pho shop, food pantry, immigrant entrepreneur)
 * Step 2: Set Primary Language (en, es, ht, vi — with native names and preview)
 * Step 3: Business Details + Claim @handle
 *
 * Designed for immigrant and community entrepreneurs who may prefer a language
 * other than English. The wizard itself is fully i18n-aware via useTranslation().
 *
 * On submit: calls POST /api/v1/onboarding/claim with community-specific payload
 *            then redirects to /dashboard.
 *
 * Follows the same component patterns as the existing ClaimPage wizard:
 *   - Same styling (Tailwind + CSS variables)
 *   - Same state management (React useState)
 *   - Same UI components (Button, Input, Card, OnboardingProgress)
 *   - Same mobile-first dark theme with gold accents
 */

import { useState, useCallback, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { ChevronRight, ChevronLeft, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { OnboardingProgress } from "@/components/onboarding/OnboardingProgress";
import { useTranslation } from "@/lib/i18n";
import { get, post } from "@/services/api/client";
import type { HandleStatus } from "@/components/onboarding/StepHandle";
import type { SupportedLocale } from "@/lib/i18n";

// ─── Constants ────────────────────────────────────────────────────────────────

const TOTAL_STEPS = 3;

/** Community business types with icons and i18n keys. */
interface CommunityType {
  id: string;
  icon: string;
  nameKey: string;
  descKey: string;
}

const COMMUNITY_TYPES: CommunityType[] = [
  {
    id: "bodega",
    icon: "🏪",
    nameKey: "community.type_bodega",
    descKey: "community.type_bodega_desc",
  },
  {
    id: "salon",
    icon: "💅",
    nameKey: "community.type_salon",
    descKey: "community.type_salon_desc",
  },
  {
    id: "taqueria",
    icon: "🌮",
    nameKey: "community.type_taqueria",
    descKey: "community.type_taqueria_desc",
  },
  {
    id: "haitian",
    icon: "🍛",
    nameKey: "community.type_haitian",
    descKey: "community.type_haitian_desc",
  },
  {
    id: "pho",
    icon: "🍜",
    nameKey: "community.type_pho",
    descKey: "community.type_pho_desc",
  },
  {
    id: "pantry",
    icon: "🤲",
    nameKey: "community.type_pantry",
    descKey: "community.type_pantry_desc",
  },
  {
    id: "entrepreneur",
    icon: "🚀",
    nameKey: "community.type_entrepreneur",
    descKey: "community.type_entrepreneur_desc",
  },
];

/** Language options for the community wizard (subset of supported locales). */
interface LanguageOption {
  code: SupportedLocale;
  nativeName: string;
  englishName: string;
  previewKey: string;
}

const LANGUAGE_OPTIONS: LanguageOption[] = [
  {
    code: "en",
    nativeName: "English",
    englishName: "English",
    previewKey: "community.preview_en",
  },
  {
    code: "es",
    nativeName: "Espanol",
    englishName: "Spanish",
    previewKey: "community.preview_es",
  },
  {
    code: "ht",
    nativeName: "Kreyol Ayisyen",
    englishName: "Haitian Creole",
    previewKey: "community.preview_ht",
  },
  {
    code: "vi",
    nativeName: "Tieng Viet",
    englishName: "Vietnamese",
    previewKey: "community.preview_vi",
  },
];

// ─── Helper: generate handle from business name ──────────────────────────────

function generateHandle(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 30);
}

// ─── Exported component ──────────────────────────────────────────────────────

export default function CommunityOnboardingWizard() {
  const router = useRouter();
  const { t, locale, setLocale } = useTranslation();

  // ── Wizard state ──────────────────────────────────────────────────────────
  const [step, setStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Step 1: Community type
  const [selectedType, setSelectedType] = useState<string | null>(null);

  // Step 2: Language
  const [selectedLanguage, setSelectedLanguage] = useState<SupportedLocale>(
    (["en", "es", "ht", "vi"].includes(locale) ? locale : "en") as SupportedLocale
  );

  // Step 3: Business details + handle
  const [businessName, setBusinessName] = useState("");
  const [handle, setHandle] = useState("");
  const [handleTouched, setHandleTouched] = useState(false);
  const [handleStatus, setHandleStatus] = useState<HandleStatus>("idle");
  const [handleReason, setHandleReason] = useState<string | null>(null);
  const [phone, setPhone] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Step labels (translated)
  const stepLabels = [
    t("community.step_type"),
    t("community.step_language"),
    t("community.step_details"),
  ];

  // ── Auto-generate handle from business name ─────────────────────────────
  const onBusinessNameChange = useCallback((value: string) => {
    setBusinessName(value);
    const generated = generateHandle(value);
    setHandle(generated);
    setHandleTouched(false);
    setHandleStatus("idle");
    setHandleReason(null);
  }, []);

  // ── Handle change (manual edit) ─────────────────────────────────────────
  const onHandleChange = useCallback((rawValue: string) => {
    const v = rawValue.toLowerCase().replace(/[^a-z0-9-]/g, "");
    setHandle(v);
    setHandleTouched(true);
    setHandleStatus("idle");
    setHandleReason(null);

    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (v.length < 3) return;

    debounceRef.current = setTimeout(async () => {
      setHandleStatus("checking");
      try {
        const res = await get<{
          handle: string;
          available: boolean;
          reason?: string | null;
        }>(`/api/v1/onboarding/check-handle/${encodeURIComponent(v)}`);

        if (res.available) {
          setHandleStatus("available");
          setHandleReason(null);
        } else if (res.reason) {
          setHandleStatus("invalid");
          setHandleReason(res.reason);
        } else {
          setHandleStatus("taken");
          setHandleReason(null);
        }
      } catch {
        setHandleStatus("idle");
      }
    }, 300);
  }, []);

  // ── Trigger handle check when auto-generated handle changes ─────────────
  useEffect(() => {
    if (!handleTouched && handle.length >= 3) {
      onHandleChange(handle);
    }
    // Only run when handle changes from auto-generation (not manual edits)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handle]);

  // ── Apply selected language ─────────────────────────────────────────────
  const onLanguageSelect = useCallback(
    (code: SupportedLocale) => {
      setSelectedLanguage(code);
      setLocale(code);
    },
    [setLocale]
  );

  // ── Step navigation ─────────────────────────────────────────────────────
  const canProceed = (() => {
    if (step === 0) return selectedType !== null;
    if (step === 1) return true; // Language always has a default selection
    if (step === 2) {
      return (
        businessName.trim().length >= 2 &&
        handle.length >= 3 &&
        handleStatus === "available"
      );
    }
    return false;
  })();

  const onNext = () => {
    if (canProceed && step < TOTAL_STEPS - 1) setStep((s) => s + 1);
  };

  const onBack = () => {
    if (step > 0) setStep((s) => s - 1);
  };

  // ── Submit ──────────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    if (!selectedType || !handle || !businessName.trim() || submitting) return;
    setErrorMsg(null);
    setSubmitting(true);
    try {
      await post("/api/v1/onboarding/claim", {
        handle,
        name: businessName.trim(),
        agent_type: "business",
        template_id: null,
        industry_type: selectedType,
        preferred_language: selectedLanguage,
        phone: phone.trim() || null,
      });
      router.push("/dashboard");
    } catch (err: unknown) {
      setSubmitting(false);
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? t("community.claim_failed");
      setErrorMsg(detail);
    }
  };

  return (
    <div className="flex items-start justify-center min-h-screen px-4 pt-8 pb-28">
      <div className="w-full max-w-md">
        {/* ── Header ────────────────────────────────────────────────────── */}
        <div className="flex flex-col items-center gap-2 mb-6">
          <span className="text-4xl" role="img" aria-hidden="true">
            🏘️
          </span>
          <h1 className="text-2xl font-bold text-[var(--foreground)] font-heading">
            {t("community.title")}
          </h1>
          <p className="text-sm text-[var(--color-muted)] text-center max-w-xs">
            {t("community.subtitle")}
          </p>
        </div>

        {/* ── Progress ──────────────────────────────────────────────────── */}
        <OnboardingProgress
          currentStep={step}
          totalSteps={TOTAL_STEPS}
          labels={stepLabels}
        />

        {/* ── Error banner ──────────────────────────────────────────────── */}
        {errorMsg && (
          <div className="mb-4 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            <span className="flex-1">{errorMsg}</span>
            <button
              onClick={() => setErrorMsg(null)}
              className="underline text-xs opacity-70 hover:opacity-100"
            >
              {t("community.dismiss")}
            </button>
          </div>
        )}

        {/* ── Step card ─────────────────────────────────────────────────── */}
        <Card className="flex flex-col gap-4">
          {/* ── STEP 0: Choose community type ──────────────────────────── */}
          {step === 0 && (
            <>
              <div>
                <h2 className="text-base font-semibold text-[var(--foreground)]">
                  {t("community.choose_type")}
                </h2>
                <p className="text-xs text-[var(--color-muted)] mt-0.5">
                  {t("community.choose_type_desc")}
                </p>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
                {COMMUNITY_TYPES.map((type) => {
                  const isSelected = selectedType === type.id;
                  return (
                    <button
                      key={type.id}
                      onClick={() => setSelectedType(type.id)}
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
                      aria-label={t(type.nameKey)}
                    >
                      <span
                        className="text-2xl leading-none"
                        role="img"
                        aria-hidden="true"
                      >
                        {type.icon}
                      </span>
                      <p
                        className={`text-xs font-semibold leading-tight ${
                          isSelected
                            ? "text-[var(--gold-500)]"
                            : "text-[var(--foreground)]"
                        }`}
                      >
                        {t(type.nameKey)}
                      </p>
                      <p className="text-[10px] text-[var(--color-muted)] leading-tight">
                        {t(type.descKey)}
                      </p>
                    </button>
                  );
                })}
              </div>
            </>
          )}

          {/* ── STEP 1: Set primary language ───────────────────────────── */}
          {step === 1 && (
            <>
              <div>
                <h2 className="text-base font-semibold text-[var(--foreground)]">
                  {t("community.select_language")}
                </h2>
                <p className="text-xs text-[var(--color-muted)] mt-0.5">
                  {t("community.select_language_desc")}
                </p>
              </div>

              <div className="flex flex-col gap-2">
                {LANGUAGE_OPTIONS.map((lang) => {
                  const isSelected = selectedLanguage === lang.code;
                  return (
                    <button
                      key={lang.code}
                      onClick={() => onLanguageSelect(lang.code)}
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
                      aria-label={`${lang.nativeName} (${lang.englishName})`}
                    >
                      <div className="flex items-center gap-3">
                        <span
                          className={`text-lg font-bold w-8 text-center flex-shrink-0 ${
                            isSelected
                              ? "text-[var(--gold-500)]"
                              : "text-[var(--color-muted)]"
                          }`}
                        >
                          {lang.code.toUpperCase()}
                        </span>

                        <div className="flex-1 min-w-0">
                          <p
                            className={`text-sm font-semibold ${
                              isSelected
                                ? "text-[var(--gold-500)]"
                                : "text-[var(--foreground)]"
                            }`}
                          >
                            {lang.nativeName}
                          </p>
                          <p className="text-[11px] text-[var(--color-muted)] mt-0.5">
                            {lang.englishName}
                          </p>
                        </div>

                        {/* Selected checkmark */}
                        {isSelected && (
                          <svg
                            className="h-4 w-4 text-[var(--gold-500)] flex-shrink-0"
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

              {/* Preview text in selected language */}
              <div className="p-3 rounded-xl bg-white/4 border border-[var(--stroke)]">
                <p className="text-[10px] text-[var(--color-muted)] uppercase tracking-wider mb-1.5">
                  {t("community.preview_label")}
                </p>
                <p className="text-sm text-[var(--foreground)]">
                  {t(
                    LANGUAGE_OPTIONS.find((l) => l.code === selectedLanguage)
                      ?.previewKey ?? "community.preview_en"
                  )}
                </p>
              </div>
            </>
          )}

          {/* ── STEP 2: Business details + @handle ─────────────────────── */}
          {step === 2 && (
            <>
              <div>
                <h2 className="text-base font-semibold text-[var(--foreground)]">
                  {t("community.business_details")}
                </h2>
                <p className="text-xs text-[var(--color-muted)] mt-0.5">
                  {t("community.business_details_desc")}
                </p>
              </div>

              {/* Business name */}
              <div>
                <label
                  htmlFor="community-business-name"
                  className="block text-xs font-medium text-[var(--color-muted)] mb-1.5"
                >
                  {t("community.business_name")}
                  <span className="text-red-400 ml-0.5">*</span>
                </label>
                <Input
                  id="community-business-name"
                  value={businessName}
                  onChange={(e) => onBusinessNameChange(e.target.value)}
                  placeholder={t("community.business_name_placeholder")}
                  maxLength={100}
                  className="text-sm"
                  autoFocus
                />
              </div>

              {/* @handle */}
              <div>
                <label
                  htmlFor="community-handle"
                  className="block text-xs font-medium text-[var(--color-muted)] mb-1.5"
                >
                  {t("community.claim_handle")}
                  <span className="text-red-400 ml-0.5">*</span>
                </label>
                <HandleInput
                  value={handle}
                  onChange={onHandleChange}
                  status={handleStatus}
                  reason={handleReason}
                  touched={handleTouched || handle.length > 0}
                  t={t}
                />
              </div>

              {/* Phone (optional) */}
              <div>
                <label
                  htmlFor="community-phone"
                  className="block text-xs font-medium text-[var(--color-muted)] mb-1.5"
                >
                  {t("community.phone")}
                  <span className="text-[var(--color-muted)] text-[10px] ml-1">
                    ({t("community.optional")})
                  </span>
                </label>
                <Input
                  id="community-phone"
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="(555) 123-4567"
                  className="text-sm"
                />
              </div>

              {/* Summary review */}
              <div className="p-3 rounded-xl bg-white/4 border border-[var(--stroke)] space-y-1 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-[var(--color-muted)]">
                    {t("community.summary_type")}
                  </span>
                  <span className="text-[var(--foreground)] flex items-center gap-1">
                    <span aria-hidden="true">
                      {COMMUNITY_TYPES.find((ct) => ct.id === selectedType)?.icon}
                    </span>
                    {t(
                      COMMUNITY_TYPES.find((ct) => ct.id === selectedType)
                        ?.nameKey ?? ""
                    )}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[var(--color-muted)]">
                    {t("community.summary_language")}
                  </span>
                  <span className="text-[var(--foreground)]">
                    {LANGUAGE_OPTIONS.find((l) => l.code === selectedLanguage)
                      ?.nativeName ?? selectedLanguage}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[var(--color-muted)]">
                    {t("community.summary_handle")}
                  </span>
                  <span className="text-[var(--gold-500)] font-medium">
                    {handle ? `@${handle}` : "\u2014"}
                  </span>
                </div>
              </div>
            </>
          )}

          {/* ── Navigation buttons ─────────────────────────────────────── */}
          <div className="flex gap-2.5 mt-1">
            {step > 0 && (
              <Button
                variant="outline"
                onClick={onBack}
                className="flex-shrink-0 min-w-[80px]"
                aria-label={t("common.back")}
              >
                <ChevronLeft className="h-4 w-4 mr-1" />
                {t("common.back")}
              </Button>
            )}

            {step < TOTAL_STEPS - 1 ? (
              <Button
                variant="gold"
                disabled={!canProceed}
                onClick={onNext}
                className="flex-1"
                aria-label={t("common.next")}
              >
                {t("common.next")}
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            ) : (
              <Button
                variant="gold"
                disabled={!canProceed || submitting}
                isLoading={submitting}
                onClick={handleSubmit}
                className="flex-1"
                aria-label={t("community.claim_button")}
              >
                {submitting
                  ? t("community.claiming")
                  : t("community.claim_button")}
              </Button>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

// ─── Inline handle input (follows StepHandle pattern) ────────────────────────

interface HandleInputProps {
  value: string;
  onChange: (value: string) => void;
  status: HandleStatus;
  reason: string | null;
  touched: boolean;
  t: (key: string, params?: Record<string, string | number>) => string;
}

function HandleInput({
  value,
  onChange,
  status,
  reason,
  touched,
  t,
}: HandleInputProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  const showAvailable = touched && status === "available" && value.length >= 3;
  const showTaken = touched && status === "taken" && value.length >= 3;
  const showInvalid = touched && status === "invalid" && value.length > 0;
  const showChecking = touched && status === "checking" && value.length >= 3;

  const statusColor = showAvailable
    ? "text-emerald-400"
    : showTaken || showInvalid
    ? "text-red-400"
    : "text-[var(--color-muted)]";

  const borderColor = showAvailable
    ? "border-emerald-400/60 focus-within:border-emerald-400"
    : showTaken || showInvalid
    ? "border-red-400/60 focus-within:border-red-400"
    : "border-[var(--stroke)] focus-within:border-[var(--gold-500)]/70";

  const helperText = (() => {
    if (showAvailable) return t("community.handle_available", { handle: value });
    if (showTaken) return t("community.handle_taken", { handle: value });
    if (showInvalid) return reason ?? t("community.handle_invalid");
    return t("community.handle_hint");
  })();

  return (
    <div>
      <div
        className={`
          relative flex items-center rounded-2xl border transition-all duration-150
          bg-white/4 px-4 py-0
          ${borderColor}
        `}
      >
        <span
          className="text-[var(--gold-500)] font-bold text-xl select-none flex-shrink-0 mr-1"
          aria-hidden="true"
        >
          @
        </span>

        <input
          ref={inputRef}
          id="community-handle"
          type="text"
          value={value}
          onChange={(e) => {
            const v = e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "");
            onChange(v);
          }}
          placeholder="your-handle"
          maxLength={30}
          autoComplete="off"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          inputMode="text"
          className={`
            flex-1 bg-transparent text-xl font-medium py-3 outline-none
            placeholder:text-white/20 transition-colors
            ${showAvailable ? "text-emerald-400" : "text-[var(--foreground)]"}
          `}
          aria-label={t("community.claim_handle")}
          aria-describedby="community-handle-helper"
          aria-invalid={showTaken || showInvalid ? "true" : "false"}
        />

        <div className="flex-shrink-0 ml-2 w-6 flex justify-center">
          {showChecking && (
            <span className="inline-block h-5 w-5 rounded-full border-2 border-white/20 border-t-[var(--gold-500)] animate-spin" />
          )}
          {showAvailable && (
            <svg
              className="h-5 w-5 text-emerald-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2.5}
              aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          )}
          {(showTaken || showInvalid) && (
            <svg
              className="h-5 w-5 text-red-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2.5}
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          )}
        </div>
      </div>

      <p
        id="community-handle-helper"
        className={`mt-2 text-xs transition-colors ${statusColor}`}
      >
        {helperText}
      </p>
    </div>
  );
}
