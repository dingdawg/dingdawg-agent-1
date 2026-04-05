import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "Simple, transparent pricing. Start free — upgrade when you need more power.",
};

// ─── Tier data ────────────────────────────────────────────────────────────────

interface Tier {
  id: string;
  label: string;
  price: number | null;
  period: string;
  actions: string;
  features: string[];
  cta: string;
  ctaHref: string;
  highlight: boolean;
  badgeColor: string;
  borderColor: string;
}

const TIERS: Tier[] = [
  {
    id: "free",
    label: "Free",
    price: 0,
    period: "/month",
    actions: "50 actions / month",
    features: [
      "50 AI actions per month",
      "1 agent",
      "Basic chat widget",
      "Community support",
    ],
    cta: "Get Started Free",
    ctaHref: "/register",
    highlight: false,
    badgeColor: "text-slate-400",
    borderColor: "border-slate-500/30",
  },
  {
    id: "starter",
    label: "Starter",
    price: 49.99,
    period: "/month",
    actions: "500 actions / month",
    features: [
      "500 AI actions per month",
      "Up to 3 agents",
      "Google Calendar integration",
      "Voice replies (Vapi)",
      "Email support",
    ],
    cta: "Start Starter",
    ctaHref: "/register",
    highlight: false,
    badgeColor: "text-blue-400",
    borderColor: "border-blue-500/30",
  },
  {
    id: "pro",
    label: "Pro",
    price: 79.99,
    period: "/month",
    actions: "2,000 actions / month",
    features: [
      "2,000 AI actions per month",
      "Unlimited agents",
      "All integrations",
      "Analytics dashboard",
      "Priority email support",
    ],
    cta: "Go Pro",
    ctaHref: "/register",
    highlight: true,
    badgeColor: "text-purple-400",
    borderColor: "border-purple-500/40",
  },
  {
    id: "enterprise",
    label: "Enterprise",
    price: 199.99,
    period: "/month",
    actions: "Unlimited actions",
    features: [
      "Unlimited AI actions",
      "Custom AI personality",
      "White-label option",
      "Dedicated account manager",
      "Priority SLA support",
    ],
    cta: "Contact Sales",
    ctaHref: "mailto:sales@dingdawg.com",
    highlight: false,
    badgeColor: "text-[var(--gold-500)]",
    borderColor: "border-[var(--gold-500)]/30",
  },
];

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function PricingPage() {
  return (
    <main className="min-h-screen bg-[var(--background)] px-6 py-16">
      {/* Header */}
      <div className="max-w-3xl mx-auto text-center mb-12">
        <h1 className="text-3xl sm:text-4xl font-bold text-[var(--foreground)] mb-3">
          Simple, transparent pricing
        </h1>
        <p className="text-[var(--color-muted)] text-base sm:text-lg">
          Start free. Upgrade only when you need more power.
          Every plan includes your own AI agent.
        </p>
      </div>

      {/* Tier grid */}
      <div className="max-w-5xl mx-auto grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        {TIERS.map((tier) => (
          <div
            key={tier.id}
            className={`relative flex flex-col rounded-2xl border p-6 bg-[var(--surface)] ${tier.borderColor} ${
              tier.highlight ? "ring-2 ring-purple-500/40 shadow-lg" : ""
            }`}
          >
            {tier.highlight && (
              <span className="absolute -top-3 left-1/2 -translate-x-1/2 text-xs font-semibold px-3 py-1 rounded-full bg-purple-500 text-white">
                Most Popular
              </span>
            )}

            {/* Label + price */}
            <div className="mb-5">
              <p className={`text-xs font-semibold uppercase tracking-widest mb-2 ${tier.badgeColor}`}>
                {tier.label}
              </p>
              <div className="flex items-end gap-1">
                {tier.price === null ? (
                  <span className="text-3xl font-bold text-[var(--foreground)]">Custom</span>
                ) : (
                  <>
                    <span className="text-3xl font-bold text-[var(--foreground)]">
                      ${tier.price === 0 ? "0" : tier.price.toFixed(2)}
                    </span>
                    <span className="text-sm text-[var(--color-muted)] mb-1">{tier.period}</span>
                  </>
                )}
              </div>
              <p className="text-xs text-[var(--color-muted)] mt-1">{tier.actions}</p>
            </div>

            {/* Features */}
            <ul className="flex-1 space-y-2 mb-6">
              {tier.features.map((f) => (
                <li key={f} className="flex items-start gap-2 text-sm text-[var(--color-muted)]">
                  <span className="mt-0.5 text-green-400 shrink-0">✓</span>
                  {f}
                </li>
              ))}
            </ul>

            {/* CTA */}
            <Link
              href={tier.ctaHref}
              className={`block text-center py-2.5 rounded-xl text-sm font-semibold transition-colors ${
                tier.highlight
                  ? "bg-purple-500 hover:bg-purple-600 text-white"
                  : "border border-[var(--stroke)] text-[var(--foreground)] hover:bg-[var(--surface-hover)]"
              }`}
            >
              {tier.cta}
            </Link>
          </div>
        ))}
      </div>

      {/* Footer note */}
      <p className="text-center text-xs text-[var(--color-muted)] mt-10">
        All plans include a 14-day money-back guarantee.{" "}
        <Link href="/billing" className="underline hover:text-[var(--foreground)]">
          Manage your plan
        </Link>{" "}
        anytime in your account.
      </p>
    </main>
  );
}
