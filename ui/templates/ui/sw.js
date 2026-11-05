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
      data: { url: message.url || "/", reply: message.reply || "" },
      // Answer in one gesture (card T22), where the browser shows the buttons.
      actions: message.reply
        ? [
            { action: "present", title: "Présent" },
            { action: "absent", title: "Absent" },
          ]
        : [],
    })
  );
});

// Path of this site only, never an address given by the message.
function sitePath(value) {
  const target = new URL(value || "/", self.location.origin);
  return target.origin === self.location.origin ? target : null;
}

// A tap on "Présent" or "Absent": the personal link records the answer. It
// needs no session nor CSRF token: the signed link is the proof (card T22).
function answer(notification, choice) {
  const reply = sitePath(notification.data && notification.data.reply);
  if (!reply) {
    return Promise.resolve();
  }
  return fetch(reply.href, {
    method: "POST",
    credentials: "omit",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: "answer=" + encodeURIComponent(choice),
  })
    .then((response) => {
      const done = response.ok;
      return self.registration.showNotification(done ? "Réponse enregistrée" : "Réponse non enregistrée", {
        body: done
          ? (choice === "present" ? "Vous serez présent. Merci !" : "Vous serez absent. Merci de l'avoir dit.")
          : "Ouvrez le message pour répondre.",
        icon: ICON,
        lang: "fr",
        tag: notification.tag || undefined,
        data: { url: notification.data.url },
      });
    })
    .catch(() => undefined);
}

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  if (event.action === "present" || event.action === "absent") {
    event.waitUntil(answer(event.notification, event.action));
    return;
  }
  const target = sitePath(event.notification.data && event.notification.data.url);
  const url = target ? target.href : self.location.origin + "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const open = windows.find((client) => client.url === url && "focus" in client);
      return open ? open.focus() : self.clients.openWindow(url);
    })
  );
});
