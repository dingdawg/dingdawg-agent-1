import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,

  /* Image optimisation — allow remote images from known domains */
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**.dingdawg.com" },
      { protocol: "https", hostname: "lh3.googleusercontent.com" }, // Google OAuth avatars
      { protocol: "https", hostname: "avatars.githubusercontent.com" }, // GitHub avatars
    ],
  },

  /* Standalone output for Docker — disabled for Vercel (uses default) */
  ...(process.env.STANDALONE === "true" ? { output: "standalone" as const } : {}),

  /* Turbopack (default in Next.js 16) */
  turbopack: {
    root: __dirname,
  },

  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8420";

    // P0 safety: warn loudly if BACKEND_URL is missing in non-dev environments
    if (!process.env.BACKEND_URL && process.env.NODE_ENV === "production") {
      console.error(
        "[CRITICAL] BACKEND_URL not set in production — API rewrites will target localhost and FAIL silently. Set BACKEND_URL in Vercel environment variables."
      );
    }

    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
      {
        source: "/auth/:path*",
        destination: `${backendUrl}/auth/:path*`,
      },
      {
        // Proxy /health to Railway backend so the health monitor can detect
        // domain mismatches via the Vercel→Railway proxy path.
        // Without this rule, app.dingdawg.com/health returns 404 even when
        // the Railway backend is healthy.
        source: "/health",
        destination: `${backendUrl}/health`,
      },
    ];
  },

  async headers() {
    return [
      // -----------------------------------------------------------------------
      // Security headers — applied to all routes
      // -----------------------------------------------------------------------
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(self), geolocation=()",
          },
          {
            // ---------------------------------------------------------------
            // Content-Security-Policy
            //
            // Fonts: Google Fonts CDN domains (fonts.googleapis.com and
            // fonts.gstatic.com) have been intentionally removed. Fonts are
            // now self-hosted via next/font/google, served from 'self'.
            // This closes the privacy leak, removes the extra DNS lookup,
            // and eliminates the need for CDN exceptions in style-src and
            // font-src.
            //
            // Turnstile: https://challenges.cloudflare.com is kept in
            // script-src and frame-src. SRI is not applied to the Turnstile
            // script because Cloudflare updates it without version-bumping
            // the URL — see TurnstileWidget.tsx for the full rationale.
            // CSP-only restriction to challenges.cloudflare.com provides
            // the equivalent defence.
            // ---------------------------------------------------------------
            key: "Content-Security-Policy",
            value: "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self' https://api.dingdawg.com https://api.stripe.com; img-src 'self' data: https:; object-src 'none'; base-uri 'self'; form-action 'self';",
          },
        ],
      },

      // -----------------------------------------------------------------------
      // Service Worker — must be served from root scope with correct headers
      // Service-Worker-Allowed: / grants the SW control over the entire origin
      // -----------------------------------------------------------------------
      {
        source: "/sw.js",
        headers: [
          {
            key: "Cache-Control",
            // SW must never be cached — browser must always fetch fresh copy
            value: "no-cache, no-store, must-revalidate",
          },
          {
            key: "Service-Worker-Allowed",
            value: "/",
          },
          {
            key: "Content-Type",
            value: "application/javascript; charset=utf-8",
          },
        ],
      },

      // -----------------------------------------------------------------------
      // manifest.json — short cache so updates propagate quickly
      // -----------------------------------------------------------------------
      {
        source: "/manifest.json",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=3600, s-maxage=3600",
          },
          {
            key: "Content-Type",
            value: "application/manifest+json",
          },
        ],
      },

      // -----------------------------------------------------------------------
      // offline.html — short cache so branding updates reach quickly
      // -----------------------------------------------------------------------
      {
        source: "/offline.html",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=86400, s-maxage=86400",
          },
        ],
      },

      // -----------------------------------------------------------------------
      // Static icons — content-addressed, immutable for 1 year
      // (icons are versioned by manifest.json bump, not by filename)
      // -----------------------------------------------------------------------
      {
        source: "/icons/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },

      // -----------------------------------------------------------------------
      // Next.js static assets (_next/static) — immutable, 1 year
      // These are content-addressed by Next.js (hash in filename)
      // -----------------------------------------------------------------------
      {
        source: "/_next/static/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },

      // -----------------------------------------------------------------------
      // Fonts from public directory (if self-hosted in future)
      // -----------------------------------------------------------------------
      {
        source: "/fonts/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
          {
            key: "Access-Control-Allow-Origin",
            value: "*",
          },
        ],
      },

      // -----------------------------------------------------------------------
      // Screenshots directory (used by manifest.json)
      // -----------------------------------------------------------------------
      {
        source: "/screenshots/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=86400, s-maxage=86400",
          },
        ],
      },
    ];
  },

  env: {
    NEXT_PUBLIC_APP_NAME: "DingDawg Agent 1",
    NEXT_PUBLIC_APP_VERSION: "0.1.0",
  },

  poweredByHeader: false,
};

export default nextConfig;
