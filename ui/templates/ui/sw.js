/*
 * Service worker of HJB Résidence (card T18).
 *
 * - Pages always come from the network: personal data (wifi, messages)
 *   never goes into a cache.
 * - Without network, a page is replaced by the offline page.
 * - Only public files are kept: the offline page, the style sheet, the fonts
 *   and the logo.
 * Docs: https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API/Using_Service_Workers
 */
"use strict";

const CACHE = "hjb-offline-{{ version }}";
const OFFLINE_URL = {{ offline_url_json|safe }};
const PRECACHE = {{ precache_json|safe }};

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(PRECACHE.map((url) => new Request(url, { cache: "reload" }))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names.filter((name) => name.startsWith("hjb-") && name !== CACHE).map((name) => caches.delete(name))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") {
    return;
  }
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }
  const url = new URL(request.url);
  if (url.origin === self.location.origin && PRECACHE.includes(url.pathname)) {
    // Network first, so that a new style sheet is used at once; the cache only without network.
    event.respondWith(fetch(request).catch(() => caches.match(request)));
  }
});
