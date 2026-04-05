"use client";

/**
 * HoneypotField — invisible bot trap input.
 *
 * Renders an input that is completely invisible to real users (positioned
 * far off-screen, zero opacity, zero height, aria-hidden). Bots that auto-fill
 * forms will populate it. The server checks this field and silently rejects
 * requests where it has any value.
 *
 * Security design:
 *   - Field name "website" looks legitimate to bots.
 *   - tabIndex={-1} prevents keyboard navigation to the field.
 *   - autoComplete="off" prevents browser from suggesting values.
 *   - aria-hidden="true" hides from screen readers (accessibility preserved).
 *
 * Usage:
 * ```tsx
 * import { HoneypotField } from "@/components/security/HoneypotField";
 *
 * function RegisterForm() {
 *   const [honeypot, setHoneypot] = useState("");
 *
 *   return (
 *     <form>
 *       <HoneypotField value={honeypot} onChange={setHoneypot} />
 *       ... rest of form ...
 *     </form>
 *   );
 * }
 * ```
 */

import React, { forwardRef } from "react";

interface HoneypotFieldProps {
  /** Current value of the honeypot field (should always be empty string for real users). */
  value: string;
  /** Called when the field value changes (bots may trigger this). */
  onChange: (value: string) => void;
  /** Optional field name override. Defaults to "website". */
  fieldName?: string;
}

/**
 * HoneypotField renders an invisible trap input for bot detection.
 *
 * Include this in every registration and high-value form. The value must
 * be submitted with the form data so the server can validate it.
 *
 * Real users will never fill this field. Bots that auto-fill everything will.
 */
const HoneypotField = forwardRef<HTMLInputElement, HoneypotFieldProps>(
  function HoneypotField(
    { value, onChange, fieldName = "website" },
    ref
  ) {
    return (
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          left: "-9999px",
          top: "-9999px",
          opacity: 0,
          height: 0,
          width: 0,
          overflow: "hidden",
          pointerEvents: "none",
        }}
      >
        <label htmlFor={`hp-${fieldName}`}>
          {/* Intentionally blank label — real users should never reach this */}
          Leave this field empty
        </label>
        <input
          ref={ref}
          id={`hp-${fieldName}`}
          name={fieldName}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          tabIndex={-1}
          autoComplete="off"
          aria-hidden="true"
          // Honeypot fields must NOT be required — bots may skip required fields
        />
      </div>
    );
  }
);

HoneypotField.displayName = "HoneypotField";

export { HoneypotField };
export type { HoneypotFieldProps };
