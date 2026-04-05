/**
 * Restaurant industry landing page — SSR, no "use client".
 * Targets: AI agent for restaurants, restaurant chatbot, reservation booking AI.
 */

import type { Metadata } from "next";
import Link from "next/link";
import Image from "next/image";
import {
  ArrowRight,
  Bot,
  Calendar,
  MessageSquare,
  Star,
  Shield,
  CheckCircle,
  Clock,
  UtensilsCrossed,
  Phone,
  FileText,
  TrendingUp,
  Users,
  Zap,
} from "lucide-react";

// ─── SEO metadata ──────────────────────────────────────────────────────────────

export const metadata: Metadata = {
  title: "AI Agent for Restaurants | DingDawg",
  description:
    "Give your restaurant an AI agent that handles reservations, answers menu questions, tracks orders, and responds to reviews — 24/7, for $1 per action.",
  openGraph: {
    title: "AI Agent for Restaurants | DingDawg",
    description:
      "Automate reservations, menu inquiries, order tracking, and review responses. DingDawg is the AI agent every restaurant needs.",
    type: "website",
  },
  keywords: [
    "AI agent for restaurants",
    "restaurant chatbot",
    "reservation booking AI",
    "restaurant automation",
    "AI reservation system",
    "restaurant customer service AI",
    "menu inquiry bot",
  ],
};

// ─── Shared sub-components ────────────────────────────────────────────────────

function UseCaseCard({
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

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function RestaurantsPage() {
  return (
    <div className="min-h-screen">
      {/* ── Nav ──────────────────────────────────────────────────────────── */}
      <nav
        className="flex items-center justify-between px-6 py-4 max-w-5xl mx-auto"
        style={{ paddingTop: "calc(env(safe-area-inset-top, 0px) + 16px)" }}
      >
        <div className="flex items-center gap-2">
          <Image src="/icons/logo.png" alt="DingDawg" width={40} height={32} priority />
          <span className="font-heading font-bold text-[var(--foreground)] text-lg tracking-tight">
            DingDawg
          </span>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/explore" className="text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors hidden sm:inline">
            Explore
          </Link>
          <Link href="/billing" className="text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors hidden sm:inline">
            Pricing
          </Link>
          <Link href="/login" className="text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors">
            Sign In
          </Link>
          <Link href="/claim" className="text-sm px-4 py-2 rounded-lg bg-[var(--gold-500)] text-[#07111c] font-semibold hover:bg-[var(--gold-600)] transition-colors">
            Get Started
          </Link>
        </div>
      </nav>

      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <section className="px-6 pt-16 pb-12 max-w-5xl mx-auto text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-[var(--gold-500)]/30 bg-[var(--gold-500)]/8 mb-8">
          <UtensilsCrossed className="h-3.5 w-3.5 text-[var(--gold-500)]" />
          <span className="text-xs font-medium text-[var(--gold-500)]">
            Built for Restaurants
          </span>
        </div>

        <h1 className="font-heading text-4xl sm:text-5xl md:text-6xl font-bold text-[var(--foreground)] leading-[1.1] tracking-tight mb-6 heading-depth">
          Your restaurant deserves
          <br />
          <span className="text-gradient-gold">an AI agent.</span>
        </h1>

        <p className="text-lg sm:text-xl text-[var(--color-muted)] max-w-2xl mx-auto leading-relaxed mb-4">
          DingDawg handles reservations, menu questions, order status, and online
          review responses so your staff can focus on delivering great food and
          hospitality — not answering the same questions over and over.
        </p>

        <p className="text-sm text-[var(--color-muted)] mb-10">
          50 free actions. No credit card. Set up in 60 seconds.
        </p>

        <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-6">
          <Link
            href="/claim"
            className="inline-flex items-center gap-2 px-8 py-4 rounded-xl bg-[var(--gold-500)] text-[#07111c] font-semibold text-base hover:bg-[var(--gold-600)] hover:scale-[1.02] active:scale-[0.98] transition-all duration-200 shadow-[0_0_20px_rgba(246,180,0,0.20)]"
          >
            Get Started Free
            <ArrowRight className="h-4 w-4" />
          </Link>
          <Link
            href="/explore"
            className="inline-flex items-center gap-2 px-7 py-3.5 rounded-xl border border-[var(--stroke2)] text-[var(--foreground)] font-medium text-base hover:border-white/22 hover:bg-white/4 transition-all duration-200"
          >
            See Live Agents
          </Link>
        </div>

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

      {/* ── Use Cases ────────────────────────────────────────────────────── */}
      <section className="px-6 pb-20 max-w-5xl mx-auto">
        <h2 className="font-heading text-2xl sm:text-3xl font-bold text-[var(--foreground)] text-center mb-3">
          Everything your front-of-house needs, automated
        </h2>
        <p className="text-center text-sm text-[var(--color-muted)] mb-10 max-w-xl mx-auto">
          From reservation requests at midnight to review replies on Monday morning — your
          AI agent never clocks out.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <UseCaseCard
            icon={<Calendar className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Reservation Booking"
            description="Accept table reservations 24/7 via chat or web widget. Confirm, reschedule, and send reminders automatically — no phone tag."
          />
          <UseCaseCard
            icon={<UtensilsCrossed className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Menu Inquiries"
            description="Answer questions about dishes, allergens, specials, and dietary options instantly. Keep your menu info always up to date."
          />
          <UseCaseCard
            icon={<FileText className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Order Tracking"
            description="Let customers check on delivery or pickup status without calling. Reduce hold times and free up your staff."
          />
          <UseCaseCard
            icon={<Star className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Review Responses"
            description="Draft and send personalized replies to Google and Yelp reviews. Protect your reputation on autopilot."
          />
          <UseCaseCard
            icon={<Phone className="h-4 w-4 text-[var(--gold-500)]" />}
            title="SMS & Reminders"
            description="Send reservation reminders, waitlist updates, and promotional texts to customers who opt in."
          />
          <UseCaseCard
            icon={<Users className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Guest Profiles"
            description="Build loyalty by remembering preferences, dietary restrictions, birthdays, and visit history for returning guests."
          />
        </div>
      </section>

      {/* ── Pricing ──────────────────────────────────────────────────────── */}
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
            <Link href="/claim" className="inline-flex items-center justify-center w-full px-4 py-2.5 rounded-lg border border-[var(--stroke2)] text-sm font-medium text-[var(--foreground)] hover:bg-white/5 transition-colors">
              Start Free
            </Link>
          </div>
          <div className="glass-panel p-6 text-center">
            <p className="text-sm font-semibold text-[var(--color-muted)] mb-1">Starter</p>
            <p className="font-heading text-3xl font-bold text-[var(--foreground)]">$49.99</p>
            <p className="text-xs text-[var(--color-muted)] mt-1 mb-4">500 actions/month</p>
            <Link href="/claim" className="inline-flex items-center justify-center w-full px-4 py-2.5 rounded-lg border border-[var(--stroke2)] text-sm font-medium text-[var(--foreground)] hover:bg-white/5 transition-colors">
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
            <Link href="/claim" className="inline-flex items-center justify-center w-full px-4 py-2.5 rounded-lg bg-[var(--gold-500)] text-[#07111c] text-sm font-semibold hover:bg-[var(--gold-600)] transition-colors">
              Get Started
            </Link>
          </div>
          <div className="glass-panel p-6 text-center">
            <p className="text-sm font-semibold text-[var(--color-muted)] mb-1">Enterprise</p>
            <p className="font-heading text-3xl font-bold text-[var(--foreground)]">$199.99</p>
            <p className="text-xs text-[var(--color-muted)] mt-1 mb-4">Unlimited actions</p>
            <Link href="/claim" className="inline-flex items-center justify-center w-full px-4 py-2.5 rounded-lg border border-[var(--stroke2)] text-sm font-medium text-[var(--foreground)] hover:bg-white/5 transition-colors">
              Contact Sales
            </Link>
          </div>
        </div>
      </section>

      {/* ── Live Demo ────────────────────────────────────────────────────── */}
      <section className="px-6 pb-20 max-w-2xl mx-auto">
        <h2 className="font-heading text-2xl sm:text-3xl font-bold text-[var(--foreground)] text-center mb-3">
          See it live — no sign-up needed
        </h2>
        <p className="text-center text-sm text-[var(--color-muted)] mb-8 max-w-xl mx-auto">
          Chat with Sofia, the AI assistant for Mario&apos;s Italian Kitchen. This is a real DingDawg agent, running live.
        </p>
        <div className="glass-panel-gold p-6 rounded-2xl">
          <div className="flex items-center gap-3 mb-4 pb-3 border-b border-[var(--stroke)]/40">
            <div className="w-10 h-10 rounded-full bg-[#C41E3A]/20 flex items-center justify-center text-xl">
              🍝
            </div>
            <div>
              <p className="text-sm font-semibold text-[var(--foreground)]">Mario&apos;s Italian Kitchen</p>
              <p className="text-xs text-green-400 flex items-center gap-1">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                Sofia is online
              </p>
            </div>
            <a
              href="/api/v1/public/agents/marios-italian/card"
              target="_blank"
              rel="noopener noreferrer"
              className="ml-auto text-xs px-3 py-1.5 rounded-lg border border-[var(--gold-500)]/40 text-[var(--gold-500)] hover:bg-[var(--gold-500)]/10 transition-colors font-medium"
            >
              Open Full Chat ↗
            </a>
          </div>
          {/* Static preview conversation — shows prospects what an interaction looks like */}
          <div className="flex flex-col gap-3 mb-4">
            <div className="flex justify-end">
              <div className="bg-[var(--gold-500)]/15 border border-[var(--gold-500)]/20 rounded-2xl rounded-tr-sm px-4 py-2.5 max-w-[75%]">
                <p className="text-sm text-[var(--foreground)]">What&apos;s your most popular dish?</p>
              </div>
            </div>
            <div className="flex justify-start">
              <div className="bg-white/6 border border-[var(--stroke)]/40 rounded-2xl rounded-tl-sm px-4 py-2.5 max-w-[80%]">
                <p className="text-sm text-[var(--foreground)]">
                  Our guests absolutely love the <strong>Pappardelle al Ragù</strong> — slow-braised beef and pork, aged Parmigiano, and fresh pappardelle. It&apos;s been on the menu since day one. 🇮🇹
                </p>
              </div>
            </div>
            <div className="flex justify-end">
              <div className="bg-[var(--gold-500)]/15 border border-[var(--gold-500)]/20 rounded-2xl rounded-tr-sm px-4 py-2.5 max-w-[75%]">
                <p className="text-sm text-[var(--foreground)]">Are you open Sunday?</p>
              </div>
            </div>
            <div className="flex justify-start">
              <div className="bg-white/6 border border-[var(--stroke)]/40 rounded-2xl rounded-tl-sm px-4 py-2.5 max-w-[80%]">
                <p className="text-sm text-[var(--foreground)]">
                  Yes! We&apos;re open Sunday from <strong>11 AM to 10 PM</strong> (kitchen closes at 9:30). Walk-ins welcome or I can book you a table right now — just tell me the date, time, and party size. 🍷
                </p>
              </div>
            </div>
            <div className="flex justify-end">
              <div className="bg-[var(--gold-500)]/15 border border-[var(--gold-500)]/20 rounded-2xl rounded-tr-sm px-4 py-2.5 max-w-[75%]">
                <p className="text-sm text-[var(--foreground)]">Book for Sunday, 7pm, 2 people</p>
              </div>
            </div>
            <div className="flex justify-start">
              <div className="bg-white/6 border border-[var(--stroke)]/40 rounded-2xl rounded-tl-sm px-4 py-2.5 max-w-[80%]">
                <p className="text-sm text-[var(--foreground)]">
                  Perfetto! What name should I put the reservation under? 🍝
                </p>
              </div>
            </div>
          </div>
          <a
            href="/api/v1/public/agents/marios-italian/card"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-center gap-2 w-full py-3 rounded-xl bg-[#C41E3A] text-white font-semibold text-sm hover:bg-[#a01830] hover:scale-[1.01] active:scale-[0.99] transition-all duration-200"
          >
            <MessageSquare className="h-4 w-4" />
            Chat with Sofia — Live Demo
          </a>
          <p className="text-center text-xs text-[var(--color-muted)] mt-3">
            Real agent, real data. No login required.
          </p>
        </div>
      </section>

      {/* ── Bottom CTA ───────────────────────────────────────────────────── */}
      <section className="px-6 pb-24 max-w-5xl mx-auto text-center">
        <div className="glass-panel-gold cta-gradient-border p-10 sm:p-14">
          <h2 className="font-heading text-2xl sm:text-3xl font-bold text-[var(--foreground)] mb-4 heading-depth">
            Your tables are waiting.
            <br />
            <span className="text-gradient-gold">Let your AI fill them.</span>
          </h2>
          <p className="text-[var(--color-muted)] mb-8 max-w-md mx-auto leading-relaxed">
            50 free actions. 60-second setup. No credit card.
            <br />
            Your restaurant AI agent is ready to go.
          </p>
          <Link
            href="/claim"
            className="inline-flex items-center gap-2 px-8 py-4 rounded-xl bg-[var(--gold-500)] text-[#07111c] font-semibold text-base hover:bg-[var(--gold-600)] hover:scale-[1.02] active:scale-[0.98] transition-all duration-200 shadow-[0_0_24px_rgba(246,180,0,0.20)]"
          >
            Get Started Free
            <ArrowRight className="h-4 w-4" />
          </Link>
          <p className="text-xs text-[var(--color-muted)] mt-4 flex items-center justify-center gap-1.5">
            <TrendingUp className="h-3.5 w-3.5" />
            Start free — upgrade anytime
          </p>
        </div>
      </section>

      {/* ── Footer ───────────────────────────────────────────────────────── */}
      <footer className="px-6 pb-14 max-w-5xl mx-auto border-t border-[var(--stroke)]/60 pt-10">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-2">
            <Image src="/icons/logo.png" alt="DingDawg" width={28} height={22} />
            <span className="text-sm text-[var(--color-muted)]">
              DingDawg &mdash; AI Agent for Small Business
            </span>
          </div>
          <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm text-[var(--color-muted)]">
            <Link href="/explore" className="hover:text-[var(--foreground)] transition-colors">Explore</Link>
            <Link href="/billing" className="hover:text-[var(--foreground)] transition-colors">Pricing</Link>
            <Link href="/privacy" className="hover:text-[var(--foreground)] transition-colors">Privacy</Link>
            <Link href="/terms" className="hover:text-[var(--foreground)] transition-colors">Terms</Link>
          </div>
        </div>
        <p className="text-center text-xs text-[var(--color-muted)] mt-8">
          &copy; 2026 Innovative Systems Global LLC. All rights reserved.
        </p>
      </footer>
    </div>
  );
}
