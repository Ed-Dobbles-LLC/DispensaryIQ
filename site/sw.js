// Service worker for the /cpo + /quality PWA shell (brief #403).
//
// Shell-cache ONLY. This deliberately does NOT implement a generic
// cache-everything strategy: /ops/api/* is a live ops surface (queue
// depths, run state, chat) and must never be served stale. Any
// cross-origin request (dip-service lives on a different Railway domain
// than this static site) or any same-origin path containing "/ops/api/"
// falls straight through to the network, uncached, unintercepted.

const SHELL_CACHE = "dip-ops-shell-v1";
const SHELL_ASSETS = [
  "/cpo.html",
  "/quality.html",
  "/manifest.json",
  "/assets/icons/icon-192.png",
  "/assets/icons/icon-512.png",
  "/assets/passkey-auth.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== SHELL_CACHE).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

function isLiveOpsSurface(url) {
  // Cross-origin (dip-service) — never intercept, never cache.
  if (url.origin !== self.location.origin) return true;
  // Same-origin ops/api path, if this ever changes shape — never cache.
  if (url.pathname.startsWith("/ops/api/")) return true;
  return false;
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  if (isLiveOpsSurface(url)) {
    // Do not call respondWith at all — let the browser handle it exactly
    // as if no service worker were installed.
    return;
  }

  if (event.request.method !== "GET") return;

  event.respondWith(
    caches.match(event.request).then((cached) => {
      const network = fetch(event.request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(SHELL_CACHE).then((cache) => cache.put(event.request, copy));
          }
          return response;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
