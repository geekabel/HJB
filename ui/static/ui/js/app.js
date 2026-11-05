/*
 * Installable application (card T18), loaded on every page.
 *
 * - Registers the service worker (/sw.js).
 * - Installation: Chromium browsers fire "beforeinstallprompt"; the
 *   [data-install-box] block then shows a button that opens their dialog.
 *   Other browsers (Safari) keep the written steps.
 * - [data-hide-when-installed] and [data-show-when-installed] follow the
 *   display mode: "standalone" when opened from the home screen icon.
 * - Notifications (card T19): once per session, tells the server that this
 *   browser is the device of the session (so that a logout stops it). It
 *   never adds a device: that needs the "Activer" button (push.js).
 * Docs: https://developer.mozilla.org/en-US/docs/Web/API/Window/beforeinstallprompt_event
 */
(function () {
  "use strict";

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js").catch(function () {
        // No worker (private mode, old browser): the site works the same, without offline page.
      });
    });
  }

  function installed() {
    return window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  }

  function showInstallState() {
    var done = installed();
    document.querySelectorAll("[data-hide-when-installed]").forEach(function (element) {
      element.hidden = done;
    });
    document.querySelectorAll("[data-show-when-installed]").forEach(function (element) {
      element.hidden = !done;
    });
  }

  var deferredPrompt = null;

  window.addEventListener("beforeinstallprompt", function (event) {
    // Keep the browser's own suggestion, except on the page that has its button.
    if (!document.querySelector("[data-install-box]")) {
      return;
    }
    event.preventDefault();
    deferredPrompt = event;
    document.querySelectorAll("[data-install-box]").forEach(function (box) {
      box.hidden = false;
    });
  });

  window.addEventListener("appinstalled", function () {
    deferredPrompt = null;
    document.querySelectorAll("[data-install-box]").forEach(function (box) {
      box.hidden = true;
    });
  });

  function syncPushDevice() {
    var url = document.body.dataset.pushSync;
    if (!url || !("serviceWorker" in navigator) || !("PushManager" in window)) {
      return;
    }
    if (!("Notification" in window) || Notification.permission !== "granted") {
      return;
    }
    try {
      if (window.sessionStorage.getItem("hjb-push-synced")) {
        return;
      }
      window.sessionStorage.setItem("hjb-push-synced", "1");
    } catch (error) {
      return; // no storage: the settings page does it instead
    }
    navigator.serviceWorker.ready
      .then(function (registration) {
        return registration.pushManager.getSubscription();
      })
      .then(function (subscription) {
        if (!subscription) {
          return;
        }
        var data = subscription.toJSON();
        data.mode = "sync";
        return fetch(url, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRFToken": document.body.dataset.csrf },
          body: JSON.stringify(data),
        });
      })
      .catch(function () {
        // Not important: the notifications keep working.
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    showInstallState();
    syncPushDevice();
    document.querySelectorAll("[data-install-button]").forEach(function (button) {
      button.addEventListener("click", function () {
        if (!deferredPrompt) {
          return;
        }
        deferredPrompt.prompt();
        deferredPrompt.userChoice.finally(function () {
          deferredPrompt = null;
          document.querySelectorAll("[data-install-box]").forEach(function (box) {
            box.hidden = true;
          });
        });
      });
    });
  });
})();
