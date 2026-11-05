/*
 * Service worker of HJB Résidence (card T18).
 *
 * - Pages always come from the network: personal data (wifi, messages)
 *   never goes into a cache.
 * - Without network, a page is replaced by the offline page.
 * - Only public files are kept: the offline page, the style sheet, the fonts
 *   and the logo.
 * - Notifications (card T19): shows each push message, and opens its page
 *   on a tap.
 * Docs: https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API/Using_Service_Workers
 * and https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorkerGlobalScope/push_event
 */
"use strict";

const CACHE = "hjb-offline-{{ version }}";
const OFFLINE_URL = {{ offline_url_json|safe }};
const PRECACHE = {{ precache_json|safe }};
const ICON = {{ icon_json|safe }};

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
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL, { ignoreVary: true })));
    return;
  }
  const url = new URL(request.url);
  if (url.origin === self.location.origin && PRECACHE.includes(url.pathname)) {
    // Network first, so that a new style sheet is used at once; the cache only without network.
    event.respondWith(fetch(request).catch(() => caches.match(request)));
  }
});

// Notifications (card T19). The message is JSON: title, body, url, tag.
self.addEventListener("push", (event) => {
  let message = {};
  try {
    message = event.data ? event.data.json() : {};
  } catch (error) {
    message = {};
  }
  const title = message.title || "HJB Résidence";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: message.body || "",
      icon: ICON,
      lang: "fr",
      tag: message.tag || undefined,
      data: { url: message.url || "/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  // Only a page of this site: never an address given by the message.
  const target = new URL((event.notification.data && event.notification.data.url) || "/", self.location.origin);
  const url = target.origin === self.location.origin ? target.href : self.location.origin + "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const open = windows.find((client) => client.url === url && "focus" in client);
      return open ? open.focus() : self.clients.openWindow(url);
    })
  );
});
