"use client";

/**
 * FormCard — inline form rendered within the chat stream.
 *
 * Supports text, email, phone, number, select, and textarea field types.
 * Validates required fields client-side before calling onSubmit.
 * All interactive elements meet 48px minimum touch targets.
 * Labels are linked to inputs via htmlFor/id for full accessibility.
 */

import { useState, useCallback, useMemo } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FormField {
  name: string;
  label: string;
  type: "text" | "email" | "phone" | "number" | "select" | "textarea";
  required?: boolean;
  options?: string[];
  placeholder?: string;
}

interface FormCardProps {
  fields: FormField[];
  onSubmit: (data: Record<string, string>) => void;
  submitLabel: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const BASE_INPUT =
  "w-full px-3 py-2.5 rounded-xl bg-white/5 border border-[var(--color-gold-stroke)] " +
  "text-[var(--foreground)] placeholder-[var(--color-muted)] text-sm " +
  "focus:outline-none focus:ring-2 focus:ring-[var(--gold-500)]/40 " +
  "focus:border-[var(--gold-500)]/60 transition-colors min-h-[48px]";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function FormCard({ fields, onSubmit, submitLabel }: FormCardProps) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    fields.reduce<Record<string, string>>((acc, f) => {
      acc[f.name] = "";
      return acc;
    }, {})
  );
  const [errors, setErrors] = useState<Record<string, boolean>>({});

  const isSubmitDisabled = useMemo(() => {
    return fields.some((f) => f.required && !values[f.name]?.trim());
  }, [fields, values]);

  const handleChange = useCallback(
    (name: string, value: string) => {
      setValues((prev) => ({ ...prev, [name]: value }));
      if (errors[name]) {
        setErrors((prev) => ({ ...prev, [name]: false }));
      }
    },
    [errors]
  );

  const handleSubmit = useCallback(() => {
    const newErrors: Record<string, boolean> = {};
    let hasError = false;

    for (const field of fields) {
      if (field.required && !values[field.name]?.trim()) {
        newErrors[field.name] = true;
        hasError = true;
      }
    }

    if (hasError) {
      setErrors(newErrors);
      return;
    }

    onSubmit(values);
  }, [fields, values, onSubmit]);

  const renderField = (field: FormField) => {
    const id = `field-${field.name}`;
    const hasError = errors[field.name];
    const errorClass = hasError ? "border-red-400/60 ring-1 ring-red-400/30" : "";

    const labelEl = (
      <label
        htmlFor={id}
        className="block text-xs font-medium text-[var(--color-muted)] mb-1"
      >
        {field.label}
        {field.required && <span className="text-red-400 ml-0.5">*</span>}
      </label>
    );

    if (field.type === "select") {
      return (
        <div key={field.name} className="flex flex-col">
          {labelEl}
          <select
            id={id}
            value={values[field.name]}
            onChange={(e) => handleChange(field.name, e.target.value)}
            className={`${BASE_INPUT} ${errorClass} appearance-none cursor-pointer`}
          >
            <option value="">{field.placeholder ?? "Select an option"}</option>
            {(field.options ?? []).map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
          {hasError && (
            <p className="mt-0.5 text-xs text-red-400">This field is required</p>
          )}
        </div>
      );
    }

    if (field.type === "textarea") {
      return (
        <div key={field.name} className="flex flex-col">
          {labelEl}
          <textarea
            id={id}
            value={values[field.name]}
            onChange={(e) => handleChange(field.name, e.target.value)}
            placeholder={field.placeholder}
            rows={3}
            className={`${BASE_INPUT} ${errorClass} resize-none min-h-[80px]`}
          />
          {hasError && (
            <p className="mt-0.5 text-xs text-red-400">This field is required</p>
          )}
        </div>
      );
    }

    // text | email | phone | number
    const inputType =
      field.type === "phone" ? "tel" : field.type;

    return (
      <div key={field.name} className="flex flex-col">
        {labelEl}
        <input
          id={id}
          type={inputType}
          value={values[field.name]}
          onChange={(e) => handleChange(field.name, e.target.value)}
          placeholder={field.placeholder}
          className={`${BASE_INPUT} ${errorClass}`}
        />
        {hasError && (
          <p className="mt-0.5 text-xs text-red-400">This field is required</p>
        )}
      </div>
    );
  };

  return (
    <div className="glass-panel-gold p-4 card-enter">
      {fields.length > 0 && (
        <div className="flex flex-col gap-3 mb-4">
          {fields.map(renderField)}
        </div>
      )}

      <button
        type="submit"
        onClick={handleSubmit}
        disabled={isSubmitDisabled}
        className={
          "w-full min-h-12 py-3 px-4 rounded-xl text-sm font-semibold font-heading " +
          "bg-[var(--gold-500)] text-[#07111c] " +
          "hover:bg-[var(--gold-600)] active:scale-[0.98] transition-all " +
          "disabled:opacity-40 disabled:cursor-not-allowed"
        }
      >
        {submitLabel}
      </button>
    </div>
  );
}
