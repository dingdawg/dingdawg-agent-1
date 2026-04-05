"use client";

import { Settings } from "lucide-react";
import type { SettingsPanelProps } from "../catalog";

interface SettingsPanelComponentProps extends SettingsPanelProps {
  onFieldChange?: (sectionName: string, fieldKey: string, value: string | boolean | number) => void;
}

export function SettingsPanel({
  sections,
  title = "Settings",
  onFieldChange,
}: SettingsPanelComponentProps) {
  return (
    <div className="glass-panel-gold rounded-xl p-4 space-y-4 card-enter">
      <div className="flex items-center gap-2">
        <Settings className="h-4 w-4 text-[var(--gold-500)]" />
        <span className="text-sm font-heading font-semibold text-[var(--foreground)]">
          {title}
        </span>
      </div>

      {sections.map((section) => (
        <div key={section.name} className="space-y-3">
          <p className="text-xs font-medium text-[var(--color-muted)] uppercase tracking-wider border-b border-white/10 pb-2">
            {section.name}
          </p>

          <div className="space-y-3">
            {section.fields.map((field) => (
              <div key={field.key} className="flex items-start justify-between gap-4">
                <div className="flex flex-col gap-0.5 min-w-0">
                  <label className="text-sm font-body text-[var(--foreground)]">
                    {field.label}
                  </label>
                  {field.description && (
                    <p className="text-xs text-[var(--color-muted)]">{field.description}</p>
                  )}
                </div>

                <div className="shrink-0">
                  {field.type === "toggle" && (
                    <button
                      role="switch"
                      aria-checked={!!field.value}
                      onClick={() =>
                        onFieldChange?.(section.name, field.key, !field.value)
                      }
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                        field.value ? "bg-[var(--gold-500)]" : "bg-white/20"
                      }`}
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                          field.value ? "translate-x-6" : "translate-x-1"
                        }`}
                      />
                    </button>
                  )}

                  {field.type === "select" && field.options && (
                    <select
                      value={String(field.value)}
                      onChange={(e) =>
                        onFieldChange?.(section.name, field.key, e.target.value)
                      }
                      className="bg-white/10 text-[var(--foreground)] text-sm rounded-lg px-2 py-1 border border-white/20 focus:outline-none focus:border-[var(--gold-500)]"
                    >
                      {field.options.map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                    </select>
                  )}

                  {(field.type === "text" || field.type === "number") && (
                    <input
                      type={field.type}
                      value={String(field.value)}
                      onChange={(e) =>
                        onFieldChange?.(
                          section.name,
                          field.key,
                          field.type === "number" ? Number(e.target.value) : e.target.value
                        )
                      }
                      className="bg-white/10 text-[var(--foreground)] text-sm rounded-lg px-2 py-1 border border-white/20 focus:outline-none focus:border-[var(--gold-500)] w-32"
                    />
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
