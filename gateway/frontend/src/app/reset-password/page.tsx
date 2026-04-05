"use client";

/**
 * Reset Password — Request phase.
 *
 * The existing /forgot-password page already handles this flow. This page
 * re-exports it so both /reset-password and /forgot-password routes work.
 * This keeps the URL that users type into browsers consistent with
 * the navigation link in the login page footer.
 */

export { default } from "@/app/forgot-password/page";
