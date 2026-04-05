import { redirect } from "next/navigation";

/**
 * /verify-email root — redirect to login.
 *
 * Real verification links go to /verify-email/[token].
 * If someone lands on the root (e.g. stripped link), send them to login
 * with a message so they know to check their email.
 */
export default function VerifyEmailRoot() {
  redirect("/login?message=check-email");
}
