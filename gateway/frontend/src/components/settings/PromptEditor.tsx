"use client";

/**
 * PromptEditor — Personality & AI configuration tab.
 *
 * Stores into config_json:
 *   { system_prompt, tone, language, response_length }
 *
 * All state is local; parent commits via onSave(config).
 */

import { useState, useEffect } from "react";
import { Save, Sparkles, Eye, EyeOff } from "lucide-react";
import { Button } from "@/components/ui/button";

// ─── Types ────────────────────────────────────────────────────────────────────

export type Tone = "professional" | "friendly" | "casual" | "formal";
export type ResponseLength = "concise" | "balanced" | "detailed";
export type LanguageStyle =
  | "english"
  | "spanish"
  | "bilingual_en_es"
  | "french"
  | "portuguese";

export interface PersonalityConfig {
  system_prompt: string;
  tone: Tone;
  language: LanguageStyle;
  response_length: ResponseLength;
}

interface PromptEditorProps {
  initialConfig: Partial<PersonalityConfig>;
  agentName: string;
  onSave: (config: PersonalityConfig) => Promise<void>;
  saving: boolean;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const TONE_OPTIONS: { value: Tone; label: string; description: string }[] = [
  {
    value: "professional",
    label: "Professional",
    description: "Formal and authoritative",
  },
  {
    value: "friendly",
    label: "Friendly",
    description: "Warm and approachable",
  },
  { value: "casual", label: "Casual", description: "Relaxed and conversational" },
  { value: "formal", label: "Formal", description: "Structured and precise" },
];

const LENGTH_OPTIONS: {
  value: ResponseLength;
  label: string;
  description: string;
}[] = [
  {
    value: "concise",
    label: "Concise",
    description: "Short, direct answers",
  },
  {
    value: "balanced",
    label: "Balanced",
    description: "Moderate detail",
  },
  {
    value: "detailed",
    label: "Detailed",
    description: "Thorough explanations",
  },
];

const LANGUAGE_OPTIONS: { value: LanguageStyle; label: string }[] = [
  { value: "english", label: "English" },
  { value: "spanish", label: "Spanish (Español)" },
  { value: "bilingual_en_es", label: "Bilingual (English / Spanish)" },
  { value: "french", label: "French (Français)" },
  { value: "portuguese", label: "Portuguese (Português)" },
];

const SAMPLE_QUESTIONS: Record<Tone, string> = {
  professional:
    "Good day. I'm here to assist you with any professional inquiries you may have. How may I be of service?",
  friendly:
    "Hey there! I'm so glad you stopped by. What can I help you with today? 😊",
  casual: "Hey! What's up? What do you need?",
  formal:
    "Greetings. I am at your service. Please state your inquiry and I shall assist you accordingly.",
};

// ─── Component ────────────────────────────────────────────────────────────────

export function PromptEditor({
  initialConfig,
  agentName,
  onSave,
  saving,
}: PromptEditorProps) {
  const [systemPrompt, setSystemPrompt] = useState(
    initialConfig.system_prompt ?? ""
  );
  const [tone, setTone] = useState<Tone>(initialConfig.tone ?? "friendly");
  const [language, setLanguage] = useState<LanguageStyle>(
    initialConfig.language ?? "english"
  );
  const [responseLength, setResponseLength] = useState<ResponseLength>(
    initialConfig.response_length ?? "balanced"
  );
  const [showPreview, setShowPreview] = useState(false);
  const [dirty, setDirty] = useState(false);

  // Track unsaved changes
  useEffect(() => {
    const orig = initialConfig;
    const changed =
      systemPrompt !== (orig.system_prompt ?? "") ||
      tone !== (orig.tone ?? "friendly") ||
      language !== (orig.language ?? "english") ||
      responseLength !== (orig.response_length ?? "balanced");
    setDirty(changed);
  }, [systemPrompt, tone, language, responseLength, initialConfig]);

  const handleSave = async () => {
    await onSave({ system_prompt: systemPrompt, tone, language, response_length: responseLength });
    setDirty(false);
  };

  const defaultPromptPlaceholder = `You are ${agentName || "an AI assistant"}, a helpful and knowledgeable agent. Your goal is to assist users with their questions and tasks efficiently and accurately.

Guidelines:
- Always be helpful and respectful
- Provide clear, actionable answers
- If unsure, acknowledge limitations and offer alternatives
- Stay focused on the user's needs`;

  return (
    <div className="space-y-5">
      {/* Unsaved indicator */}
      {dirty && (
        <div className="px-3 py-2 rounded-lg bg-[var(--gold-500)]/10 border border-[var(--gold-500)]/20 text-[var(--gold-500)] text-xs font-medium">
          Unsaved changes
        </div>
      )}

      {/* System Prompt */}
      <div className="glass-panel p-5">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="text-sm font-semibold text-[var(--foreground)] flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-[var(--gold-500)]" />
              System Prompt
            </h3>
            <p className="text-xs text-[var(--color-muted)] mt-0.5">
              Instructions that define your agent&apos;s core behavior
            </p>
          </div>
          <button
            onClick={() => setShowPreview(!showPreview)}
            className="flex items-center gap-1.5 text-xs text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors"
          >
            {showPreview ? (
              <EyeOff className="h-3.5 w-3.5" />
            ) : (
              <Eye className="h-3.5 w-3.5" />
            )}
            {showPreview ? "Hide" : "Preview"}
          </button>
        </div>

        <textarea
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          placeholder={defaultPromptPlaceholder}
          rows={6}
          className="w-full rounded-md px-3 py-2.5 text-sm bg-white/5 border border-[var(--stroke2)] text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)] resize-none font-mono leading-relaxed"
        />
        <p className="text-xs text-[var(--color-muted)] mt-1.5">
          {systemPrompt.length} characters
          {systemPrompt.length === 0 && " · Default prompt will be used"}
        </p>

        {/* Preview */}
        {showPreview && (
          <div className="mt-3 p-3 rounded-lg bg-white/[0.03] border border-[var(--stroke)]">
            <p className="text-xs font-medium text-[var(--color-muted)] mb-2">
              Sample greeting based on your tone setting:
            </p>
            <p className="text-sm text-[var(--foreground)] italic">
              &quot;{SAMPLE_QUESTIONS[tone]}&quot;
            </p>
          </div>
        )}
      </div>

      {/* Tone */}
      <div className="glass-panel p-5">
        <h3 className="text-sm font-semibold text-[var(--foreground)] mb-1">
          Tone
        </h3>
        <p className="text-xs text-[var(--color-muted)] mb-3">
          How your agent communicates with users
        </p>
        <div className="grid grid-cols-2 gap-2">
          {TONE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setTone(opt.value)}
              className={`text-left px-3 py-2.5 rounded-lg border text-sm transition-all ${
                tone === opt.value
                  ? "border-[var(--gold-500)] bg-[var(--gold-500)]/10 text-[var(--foreground)]"
                  : "border-[var(--stroke2)] bg-white/[0.03] text-[var(--color-muted)] hover:border-white/20 hover:text-[var(--foreground)]"
              }`}
            >
              <span className="block font-medium text-xs">{opt.label}</span>
              <span className="block text-xs mt-0.5 opacity-70">
                {opt.description}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Language */}
      <div className="glass-panel p-5">
        <h3 className="text-sm font-semibold text-[var(--foreground)] mb-1">
          Language Style
        </h3>
        <p className="text-xs text-[var(--color-muted)] mb-3">
          Primary language for conversations
        </p>
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value as LanguageStyle)}
          className="w-full h-10 rounded-md px-3 py-2 text-sm bg-white/5 border border-[var(--stroke2)] text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)] cursor-pointer"
        >
          {LANGUAGE_OPTIONS.map((opt) => (
            <option
              key={opt.value}
              value={opt.value}
              className="bg-[#0a1624] text-[var(--foreground)]"
            >
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {/* Response Length */}
      <div className="glass-panel p-5">
        <h3 className="text-sm font-semibold text-[var(--foreground)] mb-1">
          Response Length
        </h3>
        <p className="text-xs text-[var(--color-muted)] mb-3">
          How detailed your agent&apos;s responses should be
        </p>
        <div className="grid grid-cols-3 gap-2">
          {LENGTH_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setResponseLength(opt.value)}
              className={`text-center px-2 py-2.5 rounded-lg border text-sm transition-all ${
                responseLength === opt.value
                  ? "border-[var(--gold-500)] bg-[var(--gold-500)]/10 text-[var(--foreground)]"
                  : "border-[var(--stroke2)] bg-white/[0.03] text-[var(--color-muted)] hover:border-white/20 hover:text-[var(--foreground)]"
              }`}
            >
              <span className="block font-medium text-xs">{opt.label}</span>
              <span className="block text-xs mt-0.5 opacity-70">
                {opt.description}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Save */}
      <Button
        variant="gold"
        onClick={handleSave}
        isLoading={saving}
        disabled={!dirty}
        className="w-full"
      >
        <Save className="h-4 w-4" />
        Save Personality
      </Button>
    </div>
  );
}
