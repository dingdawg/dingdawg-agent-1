/**
 * Homepage — SSR landing page with SEO metadata.
 *
 * This file is a React Server Component (no "use client") so that Next.js
 * renders meaningful HTML before any JavaScript runs.  The only client piece
 * is <AuthRedirect />, which silently forwards authenticated users to
 * /dashboard without changing what unauthenticated visitors see.
 */

import type { Metadata } from "next";
import Link from "next/link";
import Image from "next/image";
import {
  DollarSign,
  Palette,
  ArrowRight,
  Bot,
  Zap,
  MessageSquare,
  BrainCircuit,
  Users,
  Megaphone,
  Calendar,
  FileText,
  Phone,
  Shield,
  CheckCircle,
  Star,
  Clock,
  TrendingUp,
  Plug,
} from "lucide-react";
import { AuthRedirect } from "@/components/auth/AuthRedirect";

// ─── SEO metadata ─────────────────────────────────────────────────────────────

export const metadata: Metadata = {
  title: {
    absolute: "DingDawg — AI Agent for Small Business | $1/Action",
  },
  description:
    "Give your business an AI agent that books appointments, sends invoices, collects payments, manages clients, and handles customer conversations — for $1 per action. 50 free actions, no credit card required. Works with Claude, ChatGPT, and Zapier.",
  openGraph: {
    title: "DingDawg — AI Agent for Small Business | $1/Action",
    description:
      "One AI agent for appointments, invoicing, payments, CRM, and marketing — $1 per action instead of $300+/month in separate tools.",
    type: "website",
  },
  keywords: [
    "AI agent small business",
    "AI appointment booking",
    "AI invoicing",
    "small business automation",
    "AI agent",
    "MCP server",
    "ChatGPT integration",
  ],
};

// ─── Reusable components ──────────────────────────────────────────────────────

function StatPill({
  icon,
  value,
  label,
}: {
  icon: React.ReactNode;
  value: string;
  label: string;
}) {
  return (
    <div className="glass-panel px-5 py-4 flex flex-col items-center gap-1.5 text-center transition-all duration-200 hover:scale-[1.03] hover:border-[var(--gold-500)]/20 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
      <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-[var(--gold-500)]/10 border border-[var(--gold-500)]/20 mb-0.5">
        {icon}
      </div>
      <span className="font-heading text-2xl font-bold text-[var(--gold-500)]">
        {value}
      </span>
      <span className="text-xs text-[var(--color-muted)] leading-tight">
        {label}
      </span>
    </div>
  );
}

function SkillCard({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="glass-panel p-5 flex flex-col gap-2.5 hover:border-[var(--gold-500)]/30 transition-all duration-200 group relative overflow-hidden">
      <div className="absolute left-0 top-0 bottom-0 w-[2px] bg-[var(--gold-500)] rounded-l-[22px] opacity-0 group-hover:opacity-100 transition-opacity duration-200" />
      <div className="flex items-center gap-3">
        <div className="flex-shrink-0 flex items-center justify-center w-9 h-9 rounded-lg bg-[var(--gold-500)]/10 border border-[var(--gold-500)]/20 group-hover:bg-[var(--gold-500)]/15 transition-colors duration-200">
          {icon}
        </div>
        <h3 className="font-heading text-[15px] font-semibold text-[var(--foreground)] leading-tight">
          {title}
        </h3>
      </div>
      <p className="text-xs text-[var(--color-muted)] leading-relaxed pl-0.5">
        {description}
      </p>
    </div>
  );
}

function Step({
  number,
  title,
  description,
}: {
  number: number;
  title: string;
  description: string;
}) {
  return (
    <div className="flex gap-4 items-start">
      <div className="flex-shrink-0 w-10 h-10 rounded-full bg-[var(--gold-500)]/10 border border-[var(--gold-500)]/30 flex items-center justify-center shadow-[0_0_12px_rgba(246,180,0,0.08)]">
        <span className="text-sm font-bold text-[var(--gold-500)]">{number}</span>
      </div>
      <div className="pt-1">
        <p className="font-semibold text-[var(--foreground)] text-sm">{title}</p>
        <p className="text-sm text-[var(--color-muted)] mt-1 leading-relaxed">{description}</p>
      </div>
    </div>
  );
}

function ChatBubble({ role, text }: { role: "user" | "agent"; text: string }) {
  return (
    <div className={`flex ${role === "user" ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
          role === "user"
            ? "bg-[var(--gold-500)]/15 text-[var(--foreground)] rounded-br-md"
            : "glass-panel text-[var(--foreground)] rounded-bl-md"
        }`}
      >
        {text}
      </div>
    </div>
  );
}

function ComparisonRow({
  feature,
  dingdawg,
  others,
}: {
  feature: string;
  dingdawg: string;
  others: string;
}) {
  return (
    <div className="grid grid-cols-3 gap-4 py-3 border-b border-[var(--stroke)]/40 last:border-0">
      <span className="text-sm text-[var(--color-muted)]">{feature}</span>
      <span className="text-sm text-[var(--gold-500)] font-medium text-center">{dingdawg}</span>
      <span className="text-sm text-[var(--color-muted)] text-center">{others}</span>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function HomePage() {
  return (
    <>
      <AuthRedirect to="/dashboard" />

      {/* JSON-LD structured data for search engines */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify([
            {
              "@context": "https://schema.org",
              "@type": "Organization",
              name: "DingDawg",
              url: "https://app.dingdawg.com",
              logo: "https://app.dingdawg.com/icons/icon-192.png",
              description:
                "AI agent platform for small businesses. Book appointments, send invoices, collect payments, manage clients, and handle customer conversations.",
              sameAs: [],
            },
            {
              "@context": "https://schema.org",
              "@type": "SoftwareApplication",
              name: "DingDawg",
              operatingSystem: "Web",
              applicationCategory: "BusinessApplication",
              description:
                "Give your business an AI agent that books appointments, sends invoices, collects payments, manages clients, and handles customer conversations — for $1 per action.",
              offers: [
                {
                  "@type": "Offer",
                  name: "Free",
                  price: "0",
                  priceCurrency: "USD",
                  description: "50 actions/month",
                },
                {
                  "@type": "Offer",
                  name: "Starter",
                  price: "49.99",
                  priceCurrency: "USD",
                  description: "500 actions/month",
                },
                {
                  "@type": "Offer",
                  name: "Pro",
                  price: "79.99",
                  priceCurrency: "USD",
                  description: "2,000 actions/month",
                },
                {
                  "@type": "Offer",
                  name: "Enterprise",
                  price: "199.99",
                  priceCurrency: "USD",
                  description: "Unlimited actions",
                },
              ],
            },
          ]),
        }}
      />

      <div className="min-h-screen">
        {/* ── Nav ─────────────────────────────────────────────────────────── */}
        <nav className="flex items-center justify-between px-6 py-4 max-w-5xl mx-auto" style={{ paddingTop: "calc(env(safe-area-inset-top, 0px) + 16px)" }}>
          <div className="flex items-center gap-2">
            <Image
              src="/icons/logo.png"
              alt="DingDawg"
              width={40}
              height={32}
              priority
            />
            <span className="font-heading font-bold text-[var(--foreground)] text-lg tracking-tight">
              DingDawg
            </span>
          </div>
          <div className="flex items-center gap-4">
            <Link
              href="/explore"
              className="text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors hidden sm:inline"
            >
              Explore
            </Link>
            <Link
              href="/pricing"
              className="text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors hidden sm:inline"
            >
              Pricing
            </Link>
            <Link
              href="/login"
              className="text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors"
            >
              Sign In
            </Link>
            <Link
              href="/claim"
              className="text-sm px-4 py-2 rounded-lg bg-[var(--gold-500)] text-[#07111c] font-semibold hover:bg-[var(--gold-600)] transition-colors"
            >
              Get Started
            </Link>
          </div>
        </nav>

        {/* ── Hero ────────────────────────────────────────────────────────── */}
        <section className="px-6 pt-16 pb-12 max-w-5xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-green-500/30 bg-green-500/8 mb-8">
            <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
            <span className="text-xs font-medium text-green-400">
              Live — Books appointments, sends invoices, chases payments. 24/7.
            </span>
          </div>

          <h1 className="font-heading text-4xl sm:text-5xl md:text-6xl font-bold text-[var(--foreground)] leading-[1.1] tracking-tight mb-6 heading-depth">
            Your business deserves
            <br />
            <span className="text-gradient-gold">an AI agent.</span>
          </h1>

          <p className="text-lg sm:text-xl text-[var(--color-muted)] max-w-2xl mx-auto leading-relaxed mb-4">
            Stop losing customers to voicemail. DingDawg books appointments,
            sends invoices, collects payments, and follows up automatically —
            while you sleep — for{" "}
            <span className="text-[var(--foreground)] font-semibold">
              $1 per action
            </span>{" "}
            instead of $300+/month in separate tools.
          </p>

          <p className="text-sm text-[var(--color-muted)] mb-10">
            Start free — 50 actions included. No credit card. Live in 60 seconds.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-6">
            <Link
              href="/claim"
              className="inline-flex items-center gap-2 px-8 py-4 rounded-xl bg-[var(--gold-500)] text-[#07111c] font-semibold text-base hover:bg-[var(--gold-600)] hover:scale-[1.02] active:scale-[0.98] transition-all duration-200 shadow-[0_0_20px_rgba(246,180,0,0.20)]"
            >
              Claim Your Agent Free
              <ArrowRight className="h-4 w-4" />
            </Link>
            <Link
              href="/explore"
              className="inline-flex items-center gap-2 px-7 py-3.5 rounded-xl border border-[var(--stroke2)] text-[var(--foreground)] font-medium text-base hover:border-white/22 hover:bg-white/4 transition-all duration-200"
            >
              See Live Agents
            </Link>
          </div>

          {/* Trust bar */}
          <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs text-[var(--color-muted)]">
            <span className="flex items-center gap-1.5">
              <Shield className="h-3.5 w-3.5 text-green-400" />
              Enterprise-grade security
            </span>
            <span className="flex items-center gap-1.5">
              <CheckCircle className="h-3.5 w-3.5 text-green-400" />
              No credit card required
            </span>
            <span className="flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5 text-green-400" />
              60-second setup
            </span>
          </div>
        </section>

        {/* ── Live demo chat ────────────────────────────────────────────── */}
        <section className="px-6 pb-20 max-w-2xl mx-auto">
          <div className="glass-panel-gold p-6 rounded-2xl">
            <div className="flex items-center gap-3 mb-4 pb-3 border-b border-[var(--stroke)]/40">
              <div className="w-9 h-9 rounded-full bg-[#C41E3A]/20 flex items-center justify-center text-lg">
                🍝
              </div>
              <div>
                <p className="text-sm font-semibold text-[var(--foreground)]">Mario&apos;s Italian Kitchen — Sofia</p>
                <p className="text-xs text-green-400 flex items-center gap-1">
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-400" />
                  Live demo agent
                </p>
              </div>
              <a
                href="/explore"
                className="ml-auto text-xs px-3 py-1.5 rounded-lg border border-[var(--gold-500)]/40 text-[var(--gold-500)] hover:bg-[var(--gold-500)]/10 transition-colors font-medium whitespace-nowrap"
              >
                Try Live ↗
              </a>
            </div>
            <div className="flex flex-col gap-3">
              <ChatBubble role="user" text="What's on the menu?" />
              <ChatBubble role="agent" text="Ciao! We have antipasti, pasta, wood-fired pizza, and mains. Our Pappardelle al Ragù ($22) and Margherita pizza ($16) are guest favorites. Want the full menu or a recommendation?" />
              <ChatBubble role="user" text="I'd like the Margherita pizza" />
              <ChatBubble role="agent" text="Great choice! Our Margherita is San Marzano tomatoes, fresh mozzarella, and basil — $16. Dine-in, takeout, or shall I place a delivery order?" />
              <ChatBubble role="user" text="Are you open Sunday?" />
              <ChatBubble role="agent" text="Yes! Open Sunday 11 AM – 10 PM (kitchen closes 9:30 PM). Want to book a table? Just tell me the time and party size. 🇮🇹" />
            </div>
            <a
              href="/explore"
              className="flex items-center justify-center gap-2 w-full mt-4 py-2.5 rounded-xl border border-[var(--gold-500)]/40 text-[var(--gold-500)] font-medium text-sm hover:bg-[var(--gold-500)]/8 transition-colors"
            >
              <Bot className="h-4 w-4" />
              Explore live agents — no login needed
            </a>
          </div>
        </section>

        {/* ── Platform stats ───────────────────────────────────────────────── */}
        <section className="px-6 pb-16 max-w-5xl mx-auto">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatPill
              icon={<Zap className="h-4 w-4 text-[var(--gold-500)]" />}
              value="17"
              label="Built-In Skills"
            />
            <StatPill
              icon={<Bot className="h-4 w-4 text-[var(--gold-500)]" />}
              value="38"
              label="Industry Templates"
            />
            <StatPill
              icon={<Plug className="h-4 w-4 text-[var(--gold-500)]" />}
              value="3"
              label="Platform Integrations"
            />
            <StatPill
              icon={<DollarSign className="h-4 w-4 text-[var(--gold-500)]" />}
              value="$1"
              label="Per Action, No Minimums"
            />
          </div>
        </section>

        {/* ── What your agent can do ──────────────────────────────────────── */}
        <section className="px-6 pb-20 max-w-5xl mx-auto">
          <h2 className="font-heading text-2xl sm:text-3xl font-bold text-[var(--foreground)] text-center mb-3">
            Everything your front desk does — automated
          </h2>
          <p className="text-center text-sm text-[var(--color-muted)] mb-10 max-w-xl mx-auto">
            17 built-in skills covering the full business loop: book it, invoice it,
            collect it, follow it up — no extra apps, no extra staff.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <SkillCard
              icon={<Calendar className="h-4 w-4 text-[var(--gold-500)]" />}
              title="Appointments"
              description="Book, reschedule, cancel, and send reminders. Integrates with Google Calendar."
            />
            <SkillCard
              icon={<FileText className="h-4 w-4 text-[var(--gold-500)]" />}
              title="Invoicing"
              description="Create invoices, send payment links, track paid/unpaid, and chase overdue balances automatically."
            />
            <SkillCard
              icon={<DollarSign className="h-4 w-4 text-[var(--gold-500)]" />}
              title="Payments"
              description="Collect payments via Stripe. Process refunds. Track revenue. Send receipts."
            />
            <SkillCard
              icon={<MessageSquare className="h-4 w-4 text-[var(--gold-500)]" />}
              title="Customer Chat"
              description="Two-way conversations via web widget, SMS, or email. Your agent reads context and takes action."
            />
            <SkillCard
              icon={<Users className="h-4 w-4 text-[var(--gold-500)]" />}
              title="CRM & Contacts"
              description="Build client profiles automatically — purchase history, preferences, tags, lifetime value."
            />
            <SkillCard
              icon={<Phone className="h-4 w-4 text-[var(--gold-500)]" />}
              title="SMS & Notifications"
              description="Send texts via Twilio. Appointment reminders. Follow-ups. Marketing blasts."
            />
            <SkillCard
              icon={<BrainCircuit className="h-4 w-4 text-[var(--gold-500)]" />}
              title="Staff Operations"
              description="Assign tasks, manage schedules, track progress, route escalations to the right person."
            />
            <SkillCard
              icon={<Megaphone className="h-4 w-4 text-[var(--gold-500)]" />}
              title="Marketing"
              description="Draft campaigns, send targeted outreach, and track conversions — all from chat."
            />
            <SkillCard
              icon={<Zap className="h-4 w-4 text-[var(--gold-500)]" />}
              title="+ 9 More Skills"
              description="Inventory, expenses, forms, reviews, referrals, webhooks, data store, customer engagement, and business ops."
            />
          </div>
        </section>

        {/* ── Works with ─────────────────────────────────────────────────── */}
        <section className="px-6 pb-20 max-w-5xl mx-auto">
          <h2 className="font-heading text-2xl sm:text-3xl font-bold text-[var(--foreground)] text-center mb-3">
            Works with tools you already use
          </h2>
          <p className="text-center text-sm text-[var(--color-muted)] mb-10 max-w-xl mx-auto">
            Connect DingDawg to Claude, ChatGPT, Zapier, Google Calendar, Stripe,
            Twilio, and more via MCP, OpenAPI, or webhooks.
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            {[
              { name: "Claude (MCP)", desc: "25 tools" },
              { name: "ChatGPT (GPT)", desc: "6 actions" },
              { name: "Zapier", desc: "8 triggers/actions" },
              { name: "Google Calendar", desc: "OAuth" },
              { name: "Stripe", desc: "Payments" },
              { name: "Twilio", desc: "SMS" },
            ].map((item) => (
              <div
                key={item.name}
                className="glass-panel p-4 text-center hover:border-[var(--gold-500)]/20 transition-colors"
              >
                <p className="text-sm font-medium text-[var(--foreground)]">{item.name}</p>
                <p className="text-xs text-[var(--color-muted)] mt-0.5">{item.desc}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ── Comparison table ──────────────────────────────────────────── */}
        <section className="px-6 pb-20 max-w-3xl mx-auto">
          <h2 className="font-heading text-2xl sm:text-3xl font-bold text-[var(--foreground)] text-center mb-3">
            Stop overpaying for basic tools
          </h2>
          <p className="text-center text-sm text-[var(--color-muted)] mb-10">
            DingDawg consolidates 3-5 separate subscriptions into one AI agent.
          </p>
          <div className="glass-panel p-6">
            <div className="grid grid-cols-3 gap-4 pb-3 border-b border-[var(--stroke)]/60 mb-1">
              <span className="text-sm font-semibold text-[var(--foreground)]">Feature</span>
              <span className="text-sm font-semibold text-[var(--gold-500)] text-center">DingDawg</span>
              <span className="text-sm font-semibold text-[var(--color-muted)] text-center">Others</span>
            </div>
            <ComparisonRow feature="Scheduling" dingdawg="Included" others="$29-59/mo" />
            <ComparisonRow feature="Invoicing" dingdawg="Included" others="$15-39/mo" />
            <ComparisonRow feature="CRM" dingdawg="Included" others="$25-100/mo" />
            <ComparisonRow feature="SMS/Chat" dingdawg="Included" others="$29-74/mo" />
            <ComparisonRow feature="Marketing" dingdawg="Included" others="$49-297/mo" />
            <ComparisonRow feature="AI Agent" dingdawg="Included" others="$0.99/reply" />
            <div className="grid grid-cols-3 gap-4 pt-4 mt-2 border-t border-[var(--gold-500)]/30">
              <span className="text-sm font-bold text-[var(--foreground)]">Total cost</span>
              <span className="text-sm font-bold text-[var(--gold-500)] text-center">~$50-100/mo</span>
              <span className="text-sm font-bold text-[var(--color-muted)] text-center line-through">$147-569/mo</span>
            </div>
          </div>
        </section>

        {/* ── Industry templates ──────────────────────────────────────────── */}
        <section className="px-6 pb-20 max-w-5xl mx-auto">
          <h2 className="font-heading text-2xl sm:text-3xl font-bold text-[var(--foreground)] text-center mb-3">
            Built for your industry
          </h2>
          <p className="text-center text-sm text-[var(--color-muted)] mb-10">
            38 pre-built templates across 8 verticals. Pick one and customize.
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { name: "Salons & Spas", emoji: "💇" },
              { name: "Restaurants", emoji: "🍕" },
              { name: "Home Services", emoji: "🔧" },
              { name: "Fitness & Gyms", emoji: "💪" },
              { name: "Tutoring", emoji: "📚" },
              { name: "Freelancers", emoji: "💼" },
              { name: "Real Estate", emoji: "🏠" },
              { name: "Gaming & Esports", emoji: "🎮" },
            ].map((v) => (
              <div key={v.name} className="glass-panel p-4 text-center hover:border-[var(--gold-500)]/20 transition-colors">
                <span className="text-2xl">{v.emoji}</span>
                <p className="text-sm font-medium text-[var(--foreground)] mt-2">{v.name}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ── How it works ────────────────────────────────────────────────── */}
        <section className="px-6 pb-20 max-w-5xl mx-auto">
          <h2 className="font-heading text-2xl sm:text-3xl font-bold text-[var(--foreground)] text-center mb-10">
            From sign-up to first booking in 60 seconds
          </h2>
          <div className="glass-panel p-8 max-w-xl mx-auto flex flex-col gap-7">
            <Step
              number={1}
              title="Claim your @handle"
              description="Pick a unique handle — like @joes-pizza or @bella-salon. It becomes your agent's identity."
            />
            <div className="border-l-2 border-dashed border-[var(--stroke)] ml-4 h-4" aria-hidden="true" />
            <Step
              number={2}
              title="Add your business info"
              description="Enter your prices, hours, address, and services. Your agent learns them instantly."
            />
            <div className="border-l-2 border-dashed border-[var(--stroke)] ml-4 h-4" aria-hidden="true" />
            <Step
              number={3}
              title="Embed or share"
              description="Paste a one-line widget into your website, or share your agent's profile link. Done."
            />
            <div className="border-l-2 border-dashed border-[var(--stroke)] ml-4 h-4" aria-hidden="true" />
            <Step
              number={4}
              title="Your agent goes to work"
              description="Customers chat. Your agent books, invoices, follows up, and reports back — 24/7."
            />
          </div>
        </section>

        {/* ── Social proof / testimonial ──────────────────────────────────── */}
        <section className="px-6 pb-20 max-w-3xl mx-auto">
          <div className="glass-panel-gold p-8 text-center">
            <div className="flex items-center justify-center gap-1 mb-4">
              {[...Array(5)].map((_, i) => (
                <Star key={i} className="h-5 w-5 text-[var(--gold-500)] fill-[var(--gold-500)]" />
              ))}
            </div>
            <blockquote className="text-lg text-[var(--foreground)] leading-relaxed mb-4 italic">
              &ldquo;I cancelled Calendly, my invoicing software, and my chat widget.
              DingDawg does all three. A customer booked at 11 PM last Tuesday —
              my agent confirmed the appointment, sent the invoice, and collected
              the deposit. I didn&apos;t lift a finger.&rdquo;
            </blockquote>
            <div className="flex items-center justify-center gap-3">
              <div className="w-10 h-10 rounded-full bg-[var(--gold-500)]/20 flex items-center justify-center text-sm font-bold text-[var(--gold-500)]">
                <span className="text-base">💇</span>
              </div>
              <div className="text-left">
                <p className="text-sm font-semibold text-[var(--foreground)]">Salon owner, early adopter</p>
                <p className="text-xs text-[var(--color-muted)]">Saving 10+ hours/week on admin tasks</p>
              </div>
            </div>
          </div>
        </section>

        {/* ── Pricing preview ─────────────────────────────────────────────── */}
        <section className="px-6 pb-20 max-w-5xl mx-auto">
          <h2 className="font-heading text-2xl sm:text-3xl font-bold text-[var(--foreground)] text-center mb-3">
            Simple, honest pricing
          </h2>
          <p className="text-center text-sm text-[var(--color-muted)] mb-10">
            Pay only for what your agent does. No hidden fees. No contracts.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 max-w-4xl mx-auto">
            <div className="glass-panel p-6 text-center">
              <p className="text-sm font-semibold text-[var(--color-muted)] mb-1">Free</p>
              <p className="font-heading text-3xl font-bold text-[var(--foreground)]">$0</p>
              <p className="text-xs text-[var(--color-muted)] mt-1 mb-4">50 actions/month</p>
              <Link
                href="/claim"
                className="inline-flex items-center justify-center w-full px-4 py-2.5 rounded-lg border border-[var(--stroke2)] text-sm font-medium text-[var(--foreground)] hover:bg-white/5 transition-colors"
              >
                Start Free
              </Link>
            </div>
            <div className="glass-panel p-6 text-center">
              <p className="text-sm font-semibold text-[var(--color-muted)] mb-1">Starter</p>
              <p className="font-heading text-3xl font-bold text-[var(--foreground)]">$49.99</p>
              <p className="text-xs text-[var(--color-muted)] mt-1 mb-4">500 actions/month</p>
              <Link
                href="/claim"
                className="inline-flex items-center justify-center w-full px-4 py-2.5 rounded-lg border border-[var(--stroke2)] text-sm font-medium text-[var(--foreground)] hover:bg-white/5 transition-colors"
              >
                Get Started
              </Link>
            </div>
            <div className="glass-panel-gold p-6 text-center relative">
              <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 rounded-full bg-[var(--gold-500)] text-[#07111c] text-xs font-bold">
                Most Popular
              </div>
              <p className="text-sm font-semibold text-[var(--gold-500)] mb-1">Pro</p>
              <p className="font-heading text-3xl font-bold text-[var(--foreground)]">$79.99</p>
              <p className="text-xs text-[var(--color-muted)] mt-1 mb-4">2,000 actions/month</p>
              <Link
                href="/claim"
                className="inline-flex items-center justify-center w-full px-4 py-2.5 rounded-lg bg-[var(--gold-500)] text-[#07111c] text-sm font-semibold hover:bg-[var(--gold-600)] transition-colors"
              >
                Get Started
              </Link>
            </div>
            <div className="glass-panel p-6 text-center">
              <p className="text-sm font-semibold text-[var(--color-muted)] mb-1">Enterprise</p>
              <p className="font-heading text-3xl font-bold text-[var(--foreground)]">$199.99</p>
              <p className="text-xs text-[var(--color-muted)] mt-1 mb-4">Unlimited actions</p>
              <Link
                href="/claim"
                className="inline-flex items-center justify-center w-full px-4 py-2.5 rounded-lg border border-[var(--stroke2)] text-sm font-medium text-[var(--foreground)] hover:bg-white/5 transition-colors"
              >
                Contact Sales
              </Link>
            </div>
          </div>
        </section>

        {/* ── Bottom CTA ──────────────────────────────────────────────────── */}
        <section className="px-6 pb-24 max-w-5xl mx-auto text-center">
          <div className="glass-panel-gold cta-gradient-border p-10 sm:p-14">
            <h2 className="font-heading text-2xl sm:text-3xl font-bold text-[var(--foreground)] mb-4 heading-depth">
              Your competitors are automating.
              <br />
              <span className="text-gradient-gold">Are you?</span>
            </h2>
            <p className="text-[var(--color-muted)] mb-8 max-w-md mx-auto leading-relaxed">
              Get 50 free actions — enough to book real appointments, send real invoices,
              and see exactly what your AI agent can do.
              <br />
              No credit card. Live in 60 seconds.
            </p>
            <Link
              href="/claim"
              className="inline-flex items-center gap-2 px-8 py-4 rounded-xl bg-[var(--gold-500)] text-[#07111c] font-semibold text-base hover:bg-[var(--gold-600)] hover:scale-[1.02] active:scale-[0.98] transition-all duration-200 shadow-[0_0_24px_rgba(246,180,0,0.20)]"
            >
              Claim Your Agent Free
              <ArrowRight className="h-4 w-4" />
            </Link>
            <p className="text-xs text-[var(--color-muted)] mt-4 flex items-center justify-center gap-1.5">
              <TrendingUp className="h-3.5 w-3.5" />
              Start free — upgrade anytime
            </p>
          </div>
        </section>

        {/* ── Footer ──────────────────────────────────────────────────────── */}
        <footer className="px-6 pb-14 max-w-5xl mx-auto border-t border-[var(--stroke)]/60 pt-10">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-6">
            <div className="flex items-center gap-2">
              <Image
                src="/icons/logo.png"
                alt="DingDawg"
                width={28}
                height={22}
              />
              <span className="text-sm text-[var(--color-muted)]">
                DingDawg &mdash; AI Agent for Small Business
              </span>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm text-[var(--color-muted)]">
              <Link href="/explore" className="hover:text-[var(--foreground)] transition-colors">
                Explore
              </Link>
              <Link href="/pricing" className="hover:text-[var(--foreground)] transition-colors">
                Pricing
              </Link>
              <Link href="/login" className="hover:text-[var(--foreground)] transition-colors">
                Sign In
              </Link>
              <Link href="/privacy" className="hover:text-[var(--foreground)] transition-colors">
                Privacy
              </Link>
              <Link href="/terms" className="hover:text-[var(--foreground)] transition-colors">
                Terms
              </Link>
              <a href="mailto:support@dingdawg.com" className="hover:text-[var(--foreground)] transition-colors">
                Support
              </a>
            </div>
          </div>
          <p className="text-center text-xs text-[var(--color-muted)] mt-8">
            &copy; 2026 Innovative Systems Global LLC. All rights reserved.
          </p>
        </footer>
      </div>
    </>
  );
}
