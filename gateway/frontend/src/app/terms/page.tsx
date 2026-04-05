import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Terms of Service",
  description:
    "DingDawg Terms of Service — rules and policies for using the DingDawg AI agent platform.",
};

export default function TermsPage() {
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
          Terms of Service
        </h1>
        <p className="text-sm text-[var(--color-muted)] mb-10">
          Last updated: March 2, 2026
        </p>

        <div className="space-y-10 text-sm leading-relaxed text-[var(--foreground)]/90">

          {/* 1. Acceptance */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              1. Acceptance of Terms
            </h2>
            <p>
              By accessing or using DingDawg (the &quot;Service&quot;), you agree to be bound
              by these Terms of Service and all applicable laws and regulations.
              If you do not agree with any part of these terms, you may not use
              the Service. These terms constitute a legally binding agreement
              between you and Innovative Systems Global LLC (&quot;ISG,&quot; &quot;we,&quot; &quot;us,&quot; or
              &quot;our&quot;).
            </p>
            <p className="mt-2">
              Using the Service after any updates to these terms constitutes
              your acceptance of the revised terms.
            </p>
          </section>

          {/* 2. Description */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              2. Description of Service
            </h2>
            <p>
              DingDawg is a universal AI agent platform that allows individuals
              and organizations to create, configure, and deploy AI agents under
              a unique <span className="text-[var(--gold-500)] font-medium">@handle</span> identity.
              Agents can be configured across a range of sectors including
              personal, business, enterprise, healthcare, compliance, and gaming.
            </p>
            <p className="mt-2">
              The Service includes agent creation tools, conversation interfaces,
              template libraries, developer APIs, and related features. ISG
              reserves the right to modify, suspend, or discontinue any aspect
              of the Service at any time with reasonable notice.
            </p>
          </section>

          {/* 3. User Accounts */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              3. User Accounts
            </h2>
            <p>
              To use the Service, you must register for an account by providing
              a valid email address and a secure password. You are responsible for:
            </p>
            <ul className="list-disc pl-5 mt-2 space-y-1">
              <li>Maintaining the confidentiality of your account credentials</li>
              <li>All activity that occurs under your account</li>
              <li>Ensuring your account information is accurate and up to date</li>
              <li>Notifying us immediately at{" "}
                <a
                  href="mailto:support@dingdawg.com"
                  className="text-[var(--gold-500)] hover:underline"
                >
                  support@dingdawg.com
                </a>{" "}
                if you suspect unauthorized access
              </li>
            </ul>
            <p className="mt-2">
              You must be at least 13 years old to create an account. Accounts
              may not be shared or transferred to another person.
            </p>
          </section>

          {/* 4. @Handle Policy */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              4. @Handle Policy
            </h2>
            <p>
              Your <span className="text-[var(--gold-500)] font-medium">@handle</span> is
              your agent&apos;s unique public identifier on the DingDawg platform.
            </p>
            <ul className="list-disc pl-5 mt-2 space-y-1">
              <li>
                <strong>Uniqueness:</strong> Each @handle is unique and
                cannot be claimed by more than one account.
              </li>
              <li>
                <strong>Permanence:</strong> Once claimed, a @handle is
                permanent and cannot be changed, transferred, or sold to
                another party.
              </li>
              <li>
                <strong>Ownership:</strong> You may not sell, rent, or
                transfer your @handle to another person or entity.
              </li>
              <li>
                <strong>ISG Rights:</strong> ISG reserves the right to
                reclaim any @handle that is found to be in violation of these
                terms, including handles that impersonate others, promote
                illegal activity, or contain offensive content. ISG also
                reserves the right to reclaim inactive handles after a period
                of extended inactivity.
              </li>
              <li>
                <strong>Format:</strong> Handles must be 3–30 characters,
                contain only letters, numbers, and underscores, and must
                not begin with a number.
              </li>
            </ul>
          </section>

          {/* 5. Acceptable Use */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              5. Acceptable Use
            </h2>
            <p>You agree not to use DingDawg to:</p>
            <ul className="list-disc pl-5 mt-2 space-y-1">
              <li>Violate any applicable law or regulation</li>
              <li>Infringe on the intellectual property rights of others</li>
              <li>
                Impersonate any person, business, or entity, or misrepresent
                your affiliation with any person or organization
              </li>
              <li>
                Transmit spam, unsolicited messages, or harassing communications
                through your agent
              </li>
              <li>
                Attempt to circumvent, disable, or interfere with the security
                features of the Service
              </li>
              <li>
                Use the Service to generate, distribute, or promote illegal,
                harmful, abusive, or objectionable content
              </li>
              <li>
                Conduct automated scraping or data harvesting beyond what is
                expressly permitted by the API terms
              </li>
              <li>
                Use the Service to engage in fraudulent transactions or
                deceive end users interacting with your agent
              </li>
            </ul>
            <p className="mt-2">
              ISG reserves the right to investigate any suspected violations
              and to suspend or terminate accounts found to be in breach of
              this policy.
            </p>
          </section>

          {/* 6. Payment Terms */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              6. Payment Terms
            </h2>
            <p>
              DingDawg operates on a per-transaction billing model. Claiming an
              agent is free. Your first{" "}
              <span className="font-semibold">50 actions are free</span> — no
              credit card required. After that, each agent action incurs a
              transaction fee of{" "}
              <span className="font-semibold">$1.00 USD per action</span>.
              There are no monthly minimums or subscription fees.
            </p>
            <ul className="list-disc pl-5 mt-2 space-y-1">
              <li>
                <strong>Billing:</strong> All payments are processed securely
                through Stripe. By initiating a paid transaction, you authorize
                ISG to charge your payment method on file.
              </li>
              <li>
                <strong>Pricing changes:</strong> We may change transaction
                fees at any time with at least 14 days&apos; notice via email or
                in-app notification.
              </li>
              <li>
                <strong>Refunds:</strong> Refunds are handled on a case-by-case
                basis. To request a refund, contact{" "}
                <a
                  href="mailto:support@dingdawg.com"
                  className="text-[var(--gold-500)] hover:underline"
                >
                  support@dingdawg.com
                </a>{" "}
                within 7 days of the transaction. ISG does not guarantee
                refunds for completed AI interactions.
              </li>
              <li>
                <strong>Taxes:</strong> You are responsible for any applicable
                taxes on your transactions.
              </li>
            </ul>
          </section>

          {/* 7. Intellectual Property */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              7. Intellectual Property
            </h2>
            <p>
              <strong>ISG&apos;s IP:</strong> The DingDawg platform, including its
              software, design, trademarks, logos, templates, and documentation,
              is owned by Innovative Systems Global and protected by copyright
              and other intellectual property laws. You may not copy, reproduce,
              or create derivative works from ISG&apos;s intellectual property
              without express written permission.
            </p>
            <p className="mt-2">
              <strong>Your content:</strong> You retain ownership of the content
              you create — including agent configurations, conversation data, and
              any original material you provide to your agent. By using the
              Service, you grant ISG a limited, non-exclusive license to store
              and process your content solely for the purpose of operating and
              improving the Service.
            </p>
            <p className="mt-2">
              We do not claim ownership of your conversations or the outputs
              your agent generates on your behalf.
            </p>
          </section>

          {/* 8. API & Developer Terms */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              8. API &amp; Developer Terms
            </h2>
            <p>
              Access to the DingDawg API is subject to the following conditions:
            </p>
            <ul className="list-disc pl-5 mt-2 space-y-1">
              <li>
                API usage is subject to rate limits, which may vary by account
                tier and are communicated in the developer documentation.
              </li>
              <li>
                You may not use the API to build a competing product that
                substantially replicates the core functionality of DingDawg.
              </li>
              <li>
                Automated requests must respect rate limits and must not
                interfere with the stability or availability of the platform.
              </li>
              <li>
                ISG may revoke API access for any account that violates these
                terms or places unreasonable load on the infrastructure.
              </li>
            </ul>
          </section>

          {/* 9. AI-Generated Content */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              9. AI-Generated Content
            </h2>
            <p>
              DingDawg agents produce responses using artificial intelligence
              language models. You acknowledge and agree that:
            </p>
            <ul className="list-disc pl-5 mt-2 space-y-1">
              <li>
                AI-generated outputs may contain inaccuracies, errors, or
                outdated information. You are responsible for reviewing and
                verifying any content before relying on it.
              </li>
              <li>
                ISG does not guarantee the accuracy, completeness, or
                suitability of any AI-generated response for a particular
                purpose.
              </li>
              <li>
                AI outputs do not constitute professional advice (legal,
                medical, financial, or otherwise). Consult a qualified
                professional for decisions in those areas.
              </li>
              <li>
                You are solely responsible for how you use, publish, or act
                on content generated by your agent.
              </li>
            </ul>
          </section>

          {/* 10. Limitation of Liability */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              10. Limitation of Liability
            </h2>
            <p>
              The Service is provided &quot;as is&quot; and &quot;as available&quot; without
              warranties of any kind, either express or implied. ISG does not
              warrant that the Service will be uninterrupted, error-free, or
              free of viruses or other harmful components.
            </p>
            <p className="mt-2">
              To the fullest extent permitted by law, ISG shall not be liable
              for any indirect, incidental, special, consequential, or punitive
              damages arising from your use of the Service, including but not
              limited to loss of profits, data, or business opportunities — even
              if ISG has been advised of the possibility of such damages.
            </p>
            <p className="mt-2">
              ISG&apos;s total liability to you for any claim arising out of or
              relating to these terms or the Service shall not exceed the
              greater of (a) the amount you paid to ISG in the 3 months
              preceding the claim, or (b) $10.00 USD.
            </p>
          </section>

          {/* 11. Modifications */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              11. Modifications to Terms
            </h2>
            <p>
              ISG reserves the right to update or modify these Terms of Service
              at any time. When we make material changes, we will notify you by:
            </p>
            <ul className="list-disc pl-5 mt-2 space-y-1">
              <li>Sending an email to the address associated with your account</li>
              <li>Displaying a notice within the Service</li>
              <li>Updating the &quot;Last updated&quot; date at the top of this page</li>
            </ul>
            <p className="mt-2">
              Your continued use of the Service after any changes constitutes
              your acceptance of the new terms. If you do not agree to the
              modified terms, you should discontinue use of the Service.
            </p>
          </section>

          {/* 12. Termination */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              12. Termination
            </h2>
            <p>
              <strong>Your right to terminate:</strong> You may close your
              account at any time by contacting{" "}
              <a
                href="mailto:support@dingdawg.com"
                className="text-[var(--gold-500)] hover:underline"
              >
                support@dingdawg.com
              </a>{" "}
              or through the account settings in your dashboard. Account
              closure does not entitle you to a refund of any fees already
              charged.
            </p>
            <p className="mt-2">
              <strong>ISG&apos;s right to terminate:</strong> ISG may suspend or
              terminate your account immediately and without notice if you:
            </p>
            <ul className="list-disc pl-5 mt-2 space-y-1">
              <li>Violate any provision of these Terms of Service</li>
              <li>Engage in fraudulent or abusive behavior</li>
              <li>Take actions that harm other users or the platform</li>
              <li>Fail to pay outstanding fees</li>
            </ul>
            <p className="mt-2">
              Upon termination, your right to use the Service ceases immediately.
              ISG may retain certain data as required by law or for legitimate
              business purposes.
            </p>
          </section>

          {/* 13. Governing Law */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              13. Governing Law
            </h2>
            <p>
              These Terms of Service are governed by and construed in accordance
              with the laws of the State of Texas, United States, without
              regard to its conflict of law provisions. Any disputes arising
              from these terms or the Service shall be subject to the exclusive
              jurisdiction of the state and federal courts located in Texas.
            </p>
          </section>

          {/* 14. Contact */}
          <section>
            <h2 className="text-lg font-semibold text-[var(--gold-500)] mb-3">
              14. Contact
            </h2>
            <p>
              If you have questions about these Terms of Service, please contact
              us at:
            </p>
            <div className="mt-3 p-4 rounded-xl bg-white/[0.04] border border-[var(--stroke)] space-y-1">
              <p className="font-semibold">Innovative Systems Global LLC</p>
              <p>
                Email:{" "}
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
            href="/privacy"
            className="hover:text-[var(--gold-500)] transition-colors"
          >
            Privacy Policy
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
