"use client";

/**
 * WebVitalsReporter
 *
 * Client component that calls reportWebVitals() once on mount.
 * Renders nothing — purely a side-effect component.
 * Wire into layout.tsx so it runs on every page load.
 */

import { useEffect } from "react";
import { reportWebVitals } from "@/lib/vitals";

export default function WebVitalsReporter() {
  useEffect(() => {
    reportWebVitals();
  }, []);

  return null;
}
