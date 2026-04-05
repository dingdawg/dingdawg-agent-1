/**
 * Next.js Edge Middleware — Auth guard for protected routes.
 *
 * Redirects unauthenticated users from protected routes to /login.
 * Public routes are always allowed through without any token check.
 *
 * Protected routes: /dashboard, /billing, /settings, /operations
 * Public routes: /login, /register, /onboarding, /chat/*, /agents/*, /api/*
 *
 * Token detection order:
 *  1. Cookie: "access_token" or "auth_token"
 *  2. Header: Authorization: Bearer <token>
 */

import { NextRequest, NextResponse } from "next/server";

// ---------------------------------------------------------------------------
// Route classification
// ---------------------------------------------------------------------------

/** Route prefixes that require authentication. */
const PROTECTED_PREFIXES = [
  "/dashboard",
  "/billing",
  "/settings",
  "/operations",
  "/admin",       // Admin panel — defense-in-depth (client-side AdminRoute also checks)
  "/analytics",
  "/integrations",
  "/tasks",
];

/**
 * Route prefixes (and exact paths) that are always public.
 * Checked BEFORE protected prefix matching so explicit public routes win.
 */
const PUBLIC_PREFIXES = [
  "/login",
  "/register",
  "/onboarding",
  "/verify-email",    // Email verification — must be public
  "/forgot-password", // Password reset request — must be public
  "/reset-password",  // Password reset with token — must be public
  "/auth/callback",   // OAuth callback — must be public
  "/pricing",         // Public pricing page
  "/chat/",        // /chat/[handle] — public widget chat pages
  "/agents/",      // /agents/[handle] — public agent profile pages
  "/api/",         // All API routes — backend handles its own auth
  "/explore",
  "/claim",
  "/dashboard/ceo",  // CEO dashboard — auth handled in-page, not middleware
  "/privacy",
  "/terms",
  "/legal",
  // Static / Next.js internals
  "/_next/",
  "/favicon.ico",
  "/manifest.json",
  "/icons/",
  "/splash/",
  "/sw.js",
  "/workbox-",
];

function isPublicRoute(pathname: string): boolean {
  // Exact matches for root
  if (pathname === "/" || pathname === "/login" || pathname === "/register") {
    return true;
  }
  return PUBLIC_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

function isProtectedRoute(pathname: string): boolean {
  return PROTECTED_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

// ---------------------------------------------------------------------------
// Token extraction
// ---------------------------------------------------------------------------

function extractToken(request: NextRequest): string | null {
  // 1. Cookie — common storage for JWT in this app
  const cookieToken =
    request.cookies.get("access_token")?.value ||
    request.cookies.get("auth_token")?.value ||
    null;
  if (cookieToken) return cookieToken;

  // 2. Authorization header — for clients that use Bearer tokens
  const authHeader = request.headers.get("authorization") || "";
  if (authHeader.startsWith("Bearer ")) {
    const token = authHeader.slice(7).trim();
    if (token) return token;
  }

  return null;
}

function hasValidToken(request: NextRequest): boolean {
  const token = extractToken(request);
  if (!token) return false;

  // Basic structural validation — JWT has three base64url segments
  // We do NOT verify the signature here (that's the backend's job).
  // We only ensure the token looks plausible so we can gate the route.
  const parts = token.split(".");
  if (parts.length !== 3) return false;

  // Check expiry from JWT payload without signature verification
  try {
    const payload = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
    if (typeof payload.exp === "number" && payload.exp * 1000 < Date.now()) {
      return false; // Token expired
    }
  } catch {
    // Malformed payload — treat as invalid
    return false;
  }

  return true;
}

// ---------------------------------------------------------------------------
// Middleware
// ---------------------------------------------------------------------------

export function middleware(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;

  // Always let public routes through
  if (isPublicRoute(pathname)) {
    return NextResponse.next();
  }

  // Only gate explicitly protected routes
  if (!isProtectedRoute(pathname)) {
    return NextResponse.next();
  }

  // Check for a valid auth token
  if (hasValidToken(request)) {
    return NextResponse.next();
  }

  // No valid token — redirect to login, preserving the intended destination
  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = "/login";
  loginUrl.search = "";
  loginUrl.searchParams.set("returnTo", pathname);

  return NextResponse.redirect(loginUrl);
}

// ---------------------------------------------------------------------------
// Matcher — limits which paths this middleware runs on (performance)
// ---------------------------------------------------------------------------

export const config = {
  matcher: [
    /*
     * Match all paths EXCEPT:
     * - Static files (_next/static, _next/image, favicon.ico, etc.)
     * - Next.js internals
     */
    "/((?!_next/static|_next/image|favicon\\.ico|icons/|splash/|sw\\.js|workbox-).*)",
  ],
};
