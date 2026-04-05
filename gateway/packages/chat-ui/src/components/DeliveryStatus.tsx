"use client";

/**
 * DeliveryStatus — Sent/Delivered/Read indicators for user messages.
 *
 * States:
 *   sending   → gray clock (SVG)
 *   sent      → single gray checkmark
 *   delivered → double gray checkmark
 *   read      → double blue checkmark
 *   failed    → red X
 *
 * Each state has an aria-label for screen reader compatibility.
 * Each icon is role="img" so tests can query by accessible name.
 */

import type { DeliveryStatus as DeliveryStatusType } from "../types";
import styles from "../styles/chat.module.css";

interface DeliveryStatusProps {
  status: DeliveryStatusType;
}

/** Single check SVG */
function SingleCheck({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 16 16"
      width="12"
      height="12"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <polyline points="2 8 6 12 14 4" />
    </svg>
  );
}

/** Double check SVG (two overlapping checkmarks) */
function DoubleCheck({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 20 16"
      width="16"
      height="12"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {/* First check */}
      <polyline points="2 8 6 12 14 4" />
      {/* Second check (offset right) */}
      <polyline points="6 8 10 12 18 4" />
    </svg>
  );
}

/** Clock SVG for "sending" state */
function ClockIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 16 16"
      width="12"
      height="12"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <circle cx="8" cy="8" r="6" />
      <polyline points="8 4 8 8 11 10" />
    </svg>
  );
}

/** X icon for "failed" state */
function XIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 16 16"
      width="12"
      height="12"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <line x1="3" y1="3" x2="13" y2="13" />
      <line x1="13" y1="3" x2="3" y2="13" />
    </svg>
  );
}

export function DeliveryStatus({ status }: DeliveryStatusProps) {
  switch (status) {
    case "sending":
      return (
        <span
          className={`${styles.deliveryIcon} ${styles.deliveryDefault}`}
          role="img"
          aria-label="Sending"
        >
          <ClockIcon />
        </span>
      );

    case "sent":
      return (
        <span
          className={`${styles.deliveryIcon} ${styles.deliveryDefault}`}
          role="img"
          aria-label="Sent"
        >
          <SingleCheck />
        </span>
      );

    case "delivered":
      return (
        <span
          className={`${styles.deliveryIcon} ${styles.deliveryDefault}`}
          role="img"
          aria-label="Delivered"
        >
          <DoubleCheck />
        </span>
      );

    case "read":
      return (
        <span
          className={`${styles.deliveryIcon} text-blue-500`}
          role="img"
          aria-label="Read"
        >
          <DoubleCheck className="text-blue-500" />
        </span>
      );

    case "failed":
      return (
        <span
          className={`${styles.deliveryIcon} text-red-500`}
          role="img"
          aria-label="Failed"
        >
          <XIcon className="text-red-500" />
        </span>
      );

    default:
      return null;
  }
}
