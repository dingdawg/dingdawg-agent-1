import type { Metadata, Viewport } from "next";
import { Outfit, DM_Sans } from "next/font/google";
import "./globals.css";
import ServiceWorkerRegistrar from "@/components/ServiceWorkerRegistrar";
import OfflineIndicator from "@/components/OfflineIndicator";
import InstallPrompt from "@/components/InstallPrompt";
import WebVitalsReporter from "@/components/WebVitalsReporter";
import CookieConsent from "@/components/CookieConsent";
import { I18nProvider } from "@/lib/i18n";
import { GlobalErrorBoundary } from "@/components/GlobalErrorBoundary";
import { LayoutEditor } from "@/components/dev/LayoutEditor";

// ---------------------------------------------------------------------------
// Self-hosted Google Fonts via next/font/google
// Fonts are downloaded at build time and served from the same origin.
// Benefits: no external DNS lookup, no Google tracking, zero CLS, no CSP
// exception needed for fonts.googleapis.com / fonts.gstatic.com.
// ---------------------------------------------------------------------------
const outfit = Outfit({
  subsets: ["latin"],
  // Maps to the --font-heading CSS custom property used in globals.css
  variable: "--font-heading-loaded",
  display: "swap",
  weight: ["300", "400", "500", "600", "700", "800"],
});

const dmSans = DM_Sans({
  subsets: ["latin"],
  // Maps to the --font-body CSS custom property used in globals.css
  variable: "--font-body-loaded",
  display: "swap",
  weight: ["300", "400", "500", "600", "700"],
});

// ---------------------------------------------------------------------------
// Metadata — controls <head> tags for SEO and social sharing
// ---------------------------------------------------------------------------
export const metadata: Metadata = {
  metadataBase: new URL("https://app.dingdawg.com"),
  title: {
    default: "DingDawg — Your AI Agent Platform | $1/Action",
    template: "%s | DingDawg",
  },
  description:
    "Claim your @handle and get an AI agent that works for you. " +
    "DingDawg powers AI agents for businesses, creators, and individuals.",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    title: "DingDawg",
    statusBarStyle: "black-translucent",
    startupImage: [
      {
        url: "/splash/iphone14.png",
        media:
          "(device-width: 390px) and (device-height: 844px) and (-webkit-device-pixel-ratio: 3)",
      },
      {
        url: "/splash/iphone15plus.png",
        media:
          "(device-width: 430px) and (device-height: 932px) and (-webkit-device-pixel-ratio: 3)",
      },
      {
        url: "/splash/iphonese.png",
        media:
          "(device-width: 375px) and (device-height: 667px) and (-webkit-device-pixel-ratio: 2)",
      },
      {
        url: "/splash/ipad.png",
        media:
          "(device-width: 820px) and (device-height: 1180px) and (-webkit-device-pixel-ratio: 2)",
      },
    ],
  },
  icons: {
    icon: [
      { url: "/icons/icon-32.png", sizes: "32x32", type: "image/png" },
      { url: "/icons/icon-96.png", sizes: "96x96", type: "image/png" },
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
    ],
    apple: [
      { url: "/icons/apple-touch-icon-180.png", sizes: "180x180", type: "image/png" },
      { url: "/icons/icon-152.png", sizes: "152x152", type: "image/png" },
      { url: "/icons/icon-144.png", sizes: "144x144", type: "image/png" },
    ],
    shortcut: "/icons/icon-192.png",
  },
  openGraph: {
    type: "website",
    siteName: "DingDawg",
    title: "DingDawg — Your AI Agent Platform | $1/Action",
    description: "Claim your @handle and get an AI agent that works for you.",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
        alt: "DingDawg AI Agent Platform",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "DingDawg — Your AI Agent Platform | $1/Action",
    description: "Claim your @handle and get an AI agent that works for you.",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
        alt: "DingDawg AI Agent Platform",
      },
    ],
  },
  keywords: [
    "AI agent",
    "universal agent",
    "business automation",
    "DingDawg",
    "claim handle",
    "AI assistant",
    "productivity",
  ],
  robots: {
    index: true,
    follow: true,
  },
};

// ---------------------------------------------------------------------------
// Viewport — separate export required by Next.js 14+ for viewport config
// ---------------------------------------------------------------------------
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,        // Allow user zoom for accessibility
  userScalable: true,
  viewportFit: "cover",   // Safe area support for notched phones
  // interactiveWidget: "resizes-content" makes the layout viewport shrink
  // when the mobile virtual keyboard appears so the chat input stays visible.
  // Without this, iOS Safari overlays the keyboard on top of the input bar.
  interactiveWidget: "resizes-content",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#F6B400" },
    { media: "(prefers-color-scheme: light)", color: "#F6B400" },
  ],
};

// ---------------------------------------------------------------------------
// Root layout
// ---------------------------------------------------------------------------
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      dir="ltr"
      suppressHydrationWarning
      className={`${outfit.variable} ${dmSans.variable}`}
    >
      <head>
        {/*
         * Explicit meta tags that Next.js metadata API doesn't cover cleanly.
         * apple-mobile-web-app-capable is set via appleWebApp.capable above,
         * but we also add explicit tags for maximum iOS compatibility.
         */}
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="application-name" content="DingDawg" />
        <meta name="apple-mobile-web-app-title" content="DingDawg" />

        {/* Microsoft tiles */}
        <meta name="msapplication-TileColor" content="#07111c" />
        <meta name="msapplication-TileImage" content="/icons/icon-144.png" />
        <meta name="msapplication-config" content="/browserconfig.xml" />

        {/*
         * Google Fonts are NO LONGER loaded from the CDN.
         * next/font/google downloads them at build time and serves them
         * from the same origin. The font variables (--font-heading-loaded,
         * --font-body-loaded) are injected via the <html> className above.
         * See globals.css for how they override --font-heading / --font-body.
         */}

        {/* Apple touch icons — explicit links for iOS home screen */}
        <link rel="apple-touch-icon" href="/icons/apple-touch-icon-180.png" />
        <link rel="apple-touch-icon" sizes="152x152" href="/icons/icon-152.png" />
        <link rel="apple-touch-icon" sizes="144x144" href="/icons/icon-144.png" />
        <link rel="apple-touch-icon" sizes="128x128" href="/icons/icon-128.png" />
        <link rel="apple-touch-icon" sizes="96x96" href="/icons/icon-96.png" />
        <link rel="apple-touch-icon" sizes="72x72" href="/icons/icon-72.png" />
      </head>
      <body className="min-h-screen antialiased font-body">
        <I18nProvider>
          {/*
           * Global error boundary: catches unexpected React render errors
           * anywhere in the tree and shows a friendly branded fallback
           * instead of a blank screen or raw stack trace.
           */}
          <GlobalErrorBoundary>
          {/*
           * Offline indicator: fixed position, top of screen.
           * Always in DOM — toggles visibility via CSS transform.
           */}
          <OfflineIndicator />

          {/* Page content */}
          {children}

          {/*
           * Install prompt: fixed position, bottom of screen.
           * Mobile-only, slides up when beforeinstallprompt fires.
           */}
          <InstallPrompt />

          {/*
           * Service worker registrar: renders null, just runs the registration
           * side effect on mount. Must be a client component.
           */}
          <ServiceWorkerRegistrar />

          {/*
           * Web Vitals reporter: renders null, fires CLS/INP/LCP/FCP/TTFB
           * metrics to console on every page load.
           */}
          <WebVitalsReporter />

          {/*
           * Cookie consent banner: shown on first visit, dismissed via
           * localStorage key "dd_cookie_consent". Never shown again once
           * the user has accepted or declined.
           */}
          <CookieConsent />

          {/*
           * Dev-only LayoutEditor: floating toolbar in top-right that lets
           * you click + drag any element on the page and persist its
           * position to localStorage. Renders only when
           * NODE_ENV=development AND NEXT_PUBLIC_DEV_BYPASS_AUTH=1.
           */}
          <LayoutEditor />
          </GlobalErrorBoundary>
        </I18nProvider>
      </body>
    </html>
  );
}
