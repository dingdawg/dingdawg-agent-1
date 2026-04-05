import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description:
    "DingDawg Privacy Policy — how Innovative Systems Global collects, uses, and protects your data.",
};

export default function PrivacyPage() {
  return (
    <div className="min-h-screen bg-[var(--background)] text-[var(--foreground)]">
      <div className="max-w-2xl mx-auto px-4 py-12">
        {/* Back link */}
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm text-[var(--color-muted)] hover:text-[var(--gold-500)] transition-colors mb-8"
        >
          <span aria-hidden="true">&#8592;</span>
          Back to DingDawg
        </Link>

        {/* Title */}
        <h1 className="text-3xl font-bold text-[var(--gold-500)] mb-2">
          Privacy Policy
        </h1>
        <p className="text-sm text-[var(--color-muted)] mb-10">
          Last updated: March 2, 2026
        </p>

        <p className="text-sm leading-relaxed text-[var(--foreground)]/90 mb-10">
          Innovative Systems Global LLC (&quot;ISG,&quot; &quot;we,&quot; &quot;us,&quot; or &quot;our&quot;) operates
          the DingDawg AI agent platform. This Privacy Policy explains what
          information we collect, how we use it, and the choices you have.
          We are committed to protecting your privacy and handling your data
          with care.
        </p>

        <div className="space-y-10 text-sm leading-relaxed text-[var(--foreground)]/90">

          {/* 1. Information We Collect */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              1. Information We Collect
            </h2>
            <p>We collect the following categories of information:</p>

            <h3 className="font-semibold mt-4 mb-1.5">Account Information</h3>
            <ul className="list-disc pl-5 space-y-1">
              <li>Email address (required for registration)</li>
              <li>
                Password (stored as a one-way cryptographic hash — we never
                store your plain-text password)
              </li>
              <li>Display name, if provided</li>
            </ul>

            <h3 className="font-semibold mt-4 mb-1.5">Agent Data</h3>
            <ul className="list-disc pl-5 space-y-1">
              <li>
                Your claimed{" "}
                <span className="text-[var(--gold-500)] font-medium">@handle</span>,
                agent name, sector, and template selections
              </li>
              <li>Agent configuration and system prompt customizations</li>
            </ul>

            <h3 className="font-semibold mt-4 mb-1.5">Conversation Logs</h3>
            <ul className="list-disc pl-5 space-y-1">
              <li>
                Messages sent to and received from your AI agent are stored
                to enable conversation history and to improve service quality.
              </li>
              <li>
                Conversations are associated with your account and retained
                per the data retention policy described in Section 6.
              </li>
            </ul>

            <h3 className="font-semibold mt-4 mb-1.5">Usage Analytics</h3>
            <ul className="list-disc pl-5 space-y-1">
              <li>Pages visited and features used within the platform</li>
              <li>API call counts, error rates, and performance metrics</li>
              <li>Device type, browser type, and operating system (anonymized)</li>
            </ul>

            <h3 className="font-semibold mt-4 mb-1.5">Payment Information</h3>
            <ul className="list-disc pl-5 space-y-1">
              <li>
                Payment card details are collected and stored exclusively by
                Stripe, our payment processor. ISG does not store full card
                numbers or CVV codes.
              </li>
              <li>
                We retain a record of transaction amounts, timestamps, and
                Stripe transaction IDs for billing and dispute resolution.
              </li>
            </ul>
          </section>

          {/* 2. How We Use Your Information */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              2. How We Use Your Information
            </h2>
            <p>We use the information we collect to:</p>
            <ul className="list-disc pl-5 mt-2 space-y-1">
              <li>
                <strong>Deliver the Service:</strong> Operate your agent,
                process messages, and maintain your account.
              </li>
              <li>
                <strong>Process payments:</strong> Charge transaction fees and
                provide billing records.
              </li>
              <li>
                <strong>Improve the platform:</strong> Analyze usage patterns
                to fix bugs, improve performance, and develop new features.
              </li>
              <li>
                <strong>Send communications:</strong> Deliver account
                confirmations, password resets, billing receipts, and
                important policy updates. We will not send unsolicited
                marketing emails without your explicit consent.
              </li>
              <li>
                <strong>Ensure security:</strong> Detect and prevent fraud,
                abuse, and unauthorized access.
              </li>
              <li>
                <strong>Comply with legal obligations:</strong> Respond to
                lawful requests from authorities where required.
              </li>
            </ul>
          </section>

          {/* 3. Data Storage & Security */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              3. Data Storage &amp; Security
            </h2>
            <p>
              We take the security of your data seriously and implement
              industry-standard protections:
            </p>
            <ul className="list-disc pl-5 mt-2 space-y-1">
              <li>
                All data is encrypted at rest using AES-256 encryption.
              </li>
              <li>
                All data transmitted between your device and our servers is
                encrypted in transit using TLS 1.2 or higher (HTTPS).
              </li>
              <li>
                Passwords are hashed using bcrypt with a per-user salt and
                are never stored in recoverable form.
              </li>
              <li>
                We are working toward SOC 2 Type II compliance and follow
                security best practices across our infrastructure.
              </li>
            </ul>
            <p className="mt-2">
              No method of transmission over the internet or electronic storage
              is 100% secure. While we use commercially reasonable means to
              protect your data, we cannot guarantee absolute security. In the
              event of a data breach affecting your account, we will notify you
              as required by applicable law.
            </p>
          </section>

          {/* 4. Third-Party Services */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              4. Third-Party Services
            </h2>
            <p>
              We use the following trusted third-party services to operate
              DingDawg. Each has its own privacy policy and data handling
              practices:
            </p>
            <ul className="list-disc pl-5 mt-2 space-y-2">
              <li>
                <strong>Stripe</strong> — Payment processing. Stripe handles
                all payment card data. See{" "}
                <a
                  href="https://stripe.com/privacy"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[var(--gold-500)] hover:underline"
                >
                  stripe.com/privacy
                </a>.
              </li>
              <li>
                <strong>OpenAI</strong> — AI language model processing.
                Conversation messages are sent to OpenAI&apos;s API to generate
                agent responses. See{" "}
                <a
                  href="https://openai.com/policies/privacy-policy"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[var(--gold-500)] hover:underline"
                >
                  openai.com/policies/privacy-policy
                </a>.
              </li>
              <li>
                <strong>Vercel</strong> — Frontend hosting and CDN. See{" "}
                <a
                  href="https://vercel.com/legal/privacy-policy"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[var(--gold-500)] hover:underline"
                >
                  vercel.com/legal/privacy-policy
                </a>.
              </li>
              <li>
                <strong>Railway</strong> — Backend infrastructure and
                database hosting. See{" "}
                <a
                  href="https://railway.app/legal/privacy"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[var(--gold-500)] hover:underline"
                >
                  railway.app/legal/privacy
                </a>.
              </li>
            </ul>
            <p className="mt-2">
              We do not sell your personal information to any third party.
            </p>
          </section>

          {/* 5. Cookies & Tracking */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              5. Cookies &amp; Tracking
            </h2>
            <p>
              We use a minimal set of cookies and local storage to operate
              the Service:
            </p>
            <ul className="list-disc pl-5 mt-2 space-y-1">
              <li>
                <strong>Authentication tokens:</strong> A secure, HTTP-only
                session token is used to keep you signed in. This is essential
                for the Service to function and cannot be disabled.
              </li>
              <li>
                <strong>Preference storage:</strong> Lightweight local storage
                may be used to remember non-sensitive UI preferences such as
                your last active view.
              </li>
              <li>
                <strong>Web analytics:</strong> We may collect anonymized
                analytics about platform usage (page views, feature usage)
                to improve the product. We do not use third-party advertising
                trackers.
              </li>
            </ul>
            <p className="mt-2">
              We do not use cross-site tracking cookies or sell browsing data
              to advertisers.
            </p>
          </section>

          {/* 6. Data Retention */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              6. Data Retention
            </h2>
            <ul className="list-disc pl-5 space-y-1">
              <li>
                We retain your account data and agent data for as long as your
                account is active.
              </li>
              <li>
                Conversation logs are retained for up to 12 months by default.
                You may request earlier deletion (see Section 7).
              </li>
              <li>
                Billing records are retained for a minimum of 7 years as
                required for financial compliance purposes.
              </li>
              <li>
                When you close your account, we will delete or anonymize your
                personal data within 30 days, except where retention is
                required by law.
              </li>
            </ul>
          </section>

          {/* 7. Your Rights */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              7. Your Rights
            </h2>
            <p>
              You have the following rights with respect to your personal data:
            </p>
            <ul className="list-disc pl-5 mt-2 space-y-1">
              <li>
                <strong>Access:</strong> Request a copy of the personal data
                we hold about you.
              </li>
              <li>
                <strong>Correction:</strong> Request that we correct inaccurate
                or incomplete data.
              </li>
              <li>
                <strong>Deletion:</strong> Request that we delete your personal
                data, subject to our legal retention obligations.
              </li>
              <li>
                <strong>Data export:</strong> Request an export of your account
                data and conversation history in a machine-readable format.
              </li>
              <li>
                <strong>Opt out of communications:</strong> Unsubscribe from
                non-essential emails at any time via the link in our emails
                or by contacting us directly.
              </li>
            </ul>
            <p className="mt-2">
              To exercise any of these rights, email{" "}
              <a
                href="mailto:privacy@dingdawg.com"
                className="text-[var(--gold-500)] hover:underline"
              >
                privacy@dingdawg.com
              </a>. We will respond within 30 days.
            </p>
          </section>

          {/* 8. Children's Privacy */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              8. Children&apos;s Privacy
            </h2>
            <p>
              DingDawg is not intended for or directed at children under the
              age of 13. We do not knowingly collect personal information from
              children under 13. If you believe we have inadvertently collected
              data from a child under 13, please contact us immediately at{" "}
              <a
                href="mailto:privacy@dingdawg.com"
                className="text-[var(--gold-500)] hover:underline"
              >
                privacy@dingdawg.com
              </a>{" "}
              and we will delete the information promptly. This policy is
              consistent with the requirements of the Children&apos;s Online Privacy
              Protection Act (COPPA).
            </p>
          </section>

          {/* 9. International Users */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              9. International Users
            </h2>
            <p>
              DingDawg is operated from the United States. If you are accessing
              the Service from outside the United States, your data will be
              transferred to and processed in the United States, which may have
              different data protection laws than your country.
            </p>
            <p className="mt-2">
              <strong>European Union users (GDPR):</strong> If you are located
              in the European Economic Area (EEA), you have additional rights
              under the General Data Protection Regulation (GDPR), including
              the right to object to processing, the right to restrict
              processing, and the right to lodge a complaint with your local
              supervisory authority. Our legal basis for processing your data
              is primarily the performance of the contract between you and ISG
              (Article 6(1)(b) GDPR).
            </p>
          </section>

          {/* 10. Changes */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              10. Changes to This Policy
            </h2>
            <p>
              We may update this Privacy Policy from time to time. When we
              make material changes, we will notify you by email and by
              updating the &quot;Last updated&quot; date at the top of this page. Your
              continued use of the Service after any changes constitutes your
              acceptance of the revised policy.
            </p>
            <p className="mt-2">
              We encourage you to review this policy periodically to stay
              informed about how we protect your information.
            </p>
          </section>

          {/* 11. Contact */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              11. Contact
            </h2>
            <p>
              If you have questions, concerns, or requests related to this
              Privacy Policy or the handling of your personal data, please
              contact us:
            </p>
            <div className="mt-3 p-4 rounded-xl bg-white/[0.04] border border-[var(--stroke)] space-y-1">
              <p className="font-semibold">Innovative Systems Global LLC</p>
              <p>
                Privacy inquiries:{" "}
                <a
                  href="mailto:privacy@dingdawg.com"
                  className="text-[var(--gold-500)] hover:underline"
                >
                  privacy@dingdawg.com
                </a>
              </p>
              <p>
                General support:{" "}
                <a
                  href="mailto:support@dingdawg.com"
                  className="text-[var(--gold-500)] hover:underline"
                >
                  support@dingdawg.com
                </a>
              </p>
            </div>
          </section>

        </div>

        {/* Footer nav */}
        <div className="mt-12 pt-8 border-t border-[var(--stroke)] flex flex-wrap gap-4 text-sm text-[var(--color-muted)]">
          <Link
            href="/terms"
            className="hover:text-[var(--gold-500)] transition-colors"
          >
            Terms of Service
          </Link>
          <Link
            href="/"
            className="hover:text-[var(--gold-500)] transition-colors"
          >
            Back to DingDawg
          </Link>
        </div>
      </div>
    </div>
  );
}
