/**
 * DingDawg Agent 1 — Service Worker
 * Strategy matrix:
 *   Static assets (CSS/JS/fonts/images): Cache-first, network fallback
 *   API calls (/api/*):                  Network-first, cache fallback (offline reads)
 *   Navigation (HTML pages):             Network-first, offline.html fallback
 *   Widget cross-origin:                 Network-only (never cache)
 *
 * Background sync: queues failed POST/PUT/PATCH for retry when back online.
 * Push notifications: scaffolded event listeners ready for server integration.
 */

"use strict";

// ---------------------------------------------------------------------------
// Version — bump this on every deploy to force cache invalidation
// ---------------------------------------------------------------------------
const CACHE_VERSION = "v1.0.0";
const STATIC_CACHE = `dingdawg-static-${CACHE_VERSION}`;
const API_CACHE = `dingdawg-api-${CACHE_VERSION}`;
const SYNC_QUEUE_KEY = "dingdawg-sync-queue";

// App shell — pre-cached on install for instant offline load
const APP_SHELL = [
  "/",
  "/dashboard",
  "/explore",
  "/claim",
  "/admin",
  "/offline.html",
  "/manifest.json",
];

// Static asset extensions — these get cache-first treatment
const STATIC_EXTENSIONS = new Set([
  "css", "js", "woff", "woff2", "ttf", "otf",
  "png", "jpg", "jpeg", "gif", "webp", "avif", "svg", "ico",
]);

// Mutation methods that need background sync
const MUTATION_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getExtension(url) {
  try {
    const pathname = new URL(url).pathname;
    const parts = pathname.split(".");
    return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : "";
  } catch {
    return "";
  }
}

function isStaticAsset(url) {
  return STATIC_EXTENSIONS.has(getExtension(url));
}

function isApiCall(url) {
  try {
    return new URL(url).pathname.startsWith("/api/");
  } catch {
    return false;
  }
}

function isNavigationRequest(request) {
  return request.mode === "navigate";
}

function isCrossOriginWidget(url) {
  try {
    const parsed = new URL(url);
    return (
      parsed.hostname !== self.location.hostname &&
      parsed.pathname.includes("widget")
    );
  } catch {
    return false;
  }
}

/**
 * Log helper — structured so errors are always visible, never silently swallowed.
 */
function swLog(level, message, context) {
  const prefix = `[SW ${CACHE_VERSION}]`;
  if (context !== undefined) {
    console[level](`${prefix} ${message}`, context);
  } else {
    console[level](`${prefix} ${message}`);
  }
}

// ---------------------------------------------------------------------------
// Install — pre-cache app shell
// ---------------------------------------------------------------------------

self.addEventListener("install", (event) => {
  swLog("log", "Installing, pre-caching app shell...");

  event.waitUntil(
    caches
      .open(STATIC_CACHE)
      .then((cache) => {
        // Add all shell URLs — individual failures won't block install
        return Promise.allSettled(
          APP_SHELL.map((url) =>
            cache.add(url).catch((err) => {
              swLog("warn", `Failed to cache shell URL: ${url}`, err.message);
            })
          )
        );
      })
      .then(() => {
        swLog("log", "App shell cached. Skipping waiting.");
        return self.skipWaiting();
      })
      .catch((err) => {
        swLog("error", "Install failed", err);
        throw err;
      })
  );
});

// ---------------------------------------------------------------------------
// Activate — purge old caches from previous versions
// ---------------------------------------------------------------------------

self.addEventListener("activate", (event) => {
  swLog("log", "Activating, cleaning old caches...");

  const validCaches = new Set([STATIC_CACHE, API_CACHE]);

  event.waitUntil(
    caches
      .keys()
      .then((keys) => {
        const stale = keys.filter((k) => !validCaches.has(k));
        if (stale.length > 0) {
          swLog("log", `Deleting ${stale.length} stale cache(s)`, stale);
        }
        return Promise.all(stale.map((k) => caches.delete(k)));
      })
      .then(() => {
        swLog("log", "Claiming all clients.");
        return self.clients.claim();
      })
      .catch((err) => {
        swLog("error", "Activate cleanup failed", err);
        throw err;
      })
  );
});

// ---------------------------------------------------------------------------
// Fetch — routing strategy
// ---------------------------------------------------------------------------

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = request.url;

  // Never intercept non-GET in most cases (mutations go to background sync)
  // Exception: let them pass through — background sync handles failed ones
  if (request.method !== "GET" && !isApiCall(url)) {
    return;
  }

  // Widget cross-origin — always network-only, never cache
  if (isCrossOriginWidget(url)) {
    event.respondWith(fetch(request));
    return;
  }

  // API calls (GET) — network-first with cache fallback
  if (isApiCall(url)) {
    event.respondWith(networkFirstWithCacheFallback(request, API_CACHE));
    return;
  }

  // Navigation requests — network-first, fallback to offline.html
  if (isNavigationRequest(request)) {
    event.respondWith(navigationStrategy(request));
    return;
  }

  // Static assets — cache-first with network fallback
  if (isStaticAsset(url)) {
    event.respondWith(cacheFirstWithNetworkFallback(request, STATIC_CACHE));
    return;
  }

  // Default: network-first for everything else
  event.respondWith(networkFirstWithCacheFallback(request, STATIC_CACHE));
});

// ---------------------------------------------------------------------------
// Fetch strategies
// ---------------------------------------------------------------------------

/**
 * Cache-first: serve from cache if available, fetch from network and cache if not.
 * Ideal for static assets with content-addressed URLs.
 */
async function cacheFirstWithNetworkFallback(request, cacheName) {
  try {
    const cached = await caches.match(request);
    if (cached) {
      return cached;
    }
    const networkResponse = await fetch(request);
    if (networkResponse.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, networkResponse.clone()).catch((err) => {
        swLog("warn", "Cache put failed", err.message);
      });
    }
    return networkResponse;
  } catch (err) {
    swLog("warn", "Cache-first fetch failed", err.message);
    const cached = await caches.match(request);
    if (cached) return cached;
    throw err;
  }
}

/**
 * Network-first: try network, fall back to cache.
 * Used for API calls so offline reads still work.
 */
async function networkFirstWithCacheFallback(request, cacheName) {
  try {
    const networkResponse = await fetch(request);
    if (networkResponse.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, networkResponse.clone()).catch((err) => {
        swLog("warn", "API cache put failed", err.message);
      });
    }
    return networkResponse;
  } catch (err) {
    swLog("warn", "Network-first: network failed, trying cache", err.message);
    const cached = await caches.match(request);
    if (cached) return cached;
    throw err;
  }
}

/**
 * Navigation strategy: network-first for HTML pages.
 * Falls back to offline.html when both network and cache miss.
 */
async function navigationStrategy(request) {
  try {
    const networkResponse = await fetch(request);
    return networkResponse;
  } catch (err) {
    swLog("warn", "Navigation offline, serving offline.html", err.message);
    const cached = await caches.match(request);
    if (cached) return cached;
    const offline = await caches.match("/offline.html");
    if (offline) return offline;
    // Last resort — minimal offline response
    return new Response(
      "<html><body><h1>You are offline</h1><a href='/'>Retry</a></body></html>",
      { headers: { "Content-Type": "text/html" } }
    );
  }
}

// ---------------------------------------------------------------------------
// Background sync — queue failed API mutations for retry
// ---------------------------------------------------------------------------

self.addEventListener("sync", (event) => {
  swLog("log", `Background sync triggered: ${event.tag}`);

  if (event.tag === "dingdawg-api-sync") {
    event.waitUntil(replayQueuedRequests());
  }
});

async function replayQueuedRequests() {
  // Read queue from IndexedDB via clients message channel (simplified version
  // uses postMessage to wake up the page and retry from there)
  const clients = await self.clients.matchAll({ type: "window" });
  for (const client of clients) {
    client.postMessage({ type: "SW_SYNC_TRIGGER", tag: "dingdawg-api-sync" });
  }
}

/**
 * Queue a failed mutation request for background sync retry.
 * Called by pages via postMessage.
 */
self.addEventListener("message", (event) => {
  if (!event.data) return;

  if (event.data.type === "QUEUE_SYNC_REQUEST") {
    swLog("log", "Received sync queue request", event.data.url);
    // Acknowledge receipt — actual queue management is in the app layer
    event.source?.postMessage({ type: "SW_SYNC_QUEUED", url: event.data.url });
  }

  if (event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

// Register background sync when a mutation fails
self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (!MUTATION_METHODS.has(request.method) || !isApiCall(request.url)) {
    return;
  }

  // For mutations: pass through but register sync on failure
  event.respondWith(
    fetch(request.clone()).catch(async (err) => {
      swLog("warn", "Mutation failed, registering background sync", err.message);
      if ("sync" in self.registration) {
        try {
          await self.registration.sync.register("dingdawg-api-sync");
        } catch (syncErr) {
          swLog("error", "Failed to register background sync", syncErr.message);
        }
      }
      throw err;
    })
  );
});

// ---------------------------------------------------------------------------
// Push notifications — event listener scaffolding
// ---------------------------------------------------------------------------

self.addEventListener("push", (event) => {
  swLog("log", "Push notification received");

  let payload = {
    title: "DingDawg",
    body: "You have a new notification",
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-72.png",
    data: { url: "/" },
  };

  try {
    if (event.data) {
      const raw = event.data.json();
      payload = {
        title: raw.title || payload.title,
        body: raw.body || payload.body,
        icon: raw.icon || payload.icon,
        badge: raw.badge || payload.badge,
        data: raw.data || payload.data,
        tag: raw.tag,
        requireInteraction: raw.requireInteraction || false,
        actions: raw.actions || [],
      };
    }
  } catch (err) {
    swLog("warn", "Failed to parse push payload", err.message);
  }

  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: payload.icon,
      badge: payload.badge,
      data: payload.data,
      tag: payload.tag,
      requireInteraction: payload.requireInteraction,
      actions: payload.actions,
      vibrate: [200, 100, 200],
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  swLog("log", "Notification clicked", event.notification.tag);
  event.notification.close();

  const targetUrl = event.notification.data?.url || "/";

  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((clientList) => {
        // Focus existing window if one is open
        for (const client of clientList) {
          if (client.url === targetUrl && "focus" in client) {
            return client.focus();
          }
        }
        // Open new window
        if (self.clients.openWindow) {
          return self.clients.openWindow(targetUrl);
        }
      })
      .catch((err) => {
        swLog("error", "Notification click handler failed", err.message);
      })
  );
});

self.addEventListener("notificationclose", (event) => {
  swLog("log", "Notification dismissed", event.notification.tag);
  // Analytics hook point — send dismissal event to server
});

self.addEventListener("pushsubscriptionchange", (event) => {
  swLog("log", "Push subscription changed — re-subscribing");
  // Re-subscribe and update server with new endpoint
  event.waitUntil(
    self.registration.pushManager
      .subscribe({ userVisibleOnly: true })
      .then((subscription) => {
        swLog("log", "Re-subscribed to push", subscription.endpoint);
        // TODO: POST new subscription to /api/v1/push/subscribe
      })
      .catch((err) => {
        swLog("error", "Push re-subscription failed", err.message);
      })
  );
});

swLog("log", `Service worker loaded (${CACHE_VERSION})`);
