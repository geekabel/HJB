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
 *   browser is the device of the session (so that a logout stops it, and the
 *   previous person of a shared phone stops receiving here). It never adds a
 *   device: that needs the "Activer" button (push.js).
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

  // Same bytes as the base64url public key of the server?
  function sameServerKey(subscription, base64url) {
    var current = subscription.options && subscription.options.applicationServerKey;
    if (!current || !base64url) {
      return false;
    }
    var padding = "=".repeat((4 - (base64url.length % 4)) % 4);
    var expected = window.atob((base64url + padding).replace(/-/g, "+").replace(/_/g, "/"));
    var bytes = new Uint8Array(current);
    if (bytes.length !== expected.length) {
      return false;
    }
    for (var i = 0; i < bytes.length; i += 1) {
      if (bytes[i] !== expected.charCodeAt(i)) {
        return false;
      }
    }
    return true;
  }
  window.hjbSameServerKey = sameServerKey;

  // The server adds data-push-sync until this session has told it which device it is.
  function syncPushDevice() {
    var body = document.body;
    var url = body.dataset.pushSync;
    if (!url || !("serviceWorker" in navigator) || !("PushManager" in window)) {
      return;
    }
    if (!("Notification" in window) || Notification.permission !== "granted") {
      return;
    }
    navigator.serviceWorker.ready
      .then(function (registration) {
        return registration.pushManager.getSubscription();
      })
      .then(function (subscription) {
        // No device, or one made with an old server key: the settings page handles it.
        if (!subscription || !sameServerKey(subscription, body.dataset.pushKey)) {
          return;
        }
        var data = subscription.toJSON();
        data.mode = "sync";
        return fetch(url, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRFToken": body.dataset.csrf },
          body: JSON.stringify(data),
        });
      })
      .catch(function () {
        // Not important: tried again on the next page.
      });
  }

  // Staff menu below 64rem (design card D1): the "Menu" button opens and
  // closes it. Without JavaScript the button stays hidden and the menu open.
  function setUpStaffMenu() {
    var menu = document.querySelector(".staff-menu");
    var toggle = document.querySelector("[data-menu-toggle]");
    if (!menu || !toggle) {
      return;
    }
    function setOpen(open) {
      toggle.setAttribute("aria-expanded", String(open));
      menu.classList.toggle("staff-menu--closed", !open);
    }
    toggle.hidden = false;
    menu.classList.add("staff-menu--enhanced");
    setOpen(false);
    toggle.addEventListener("click", function () {
      setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });
    document.addEventListener("keydown", function (event) {
      if (event.defaultPrevented || event.key !== "Escape") {
        return;
      }
      if (toggle.getAttribute("aria-expanded") === "true" && menu.contains(document.activeElement)) {
        setOpen(false);
        toggle.focus();
      }
    });
  }

  // Install page (design card D2): show the steps of this phone first.
  function openStepsOfThisPhone() {
    var agent = navigator.userAgent || "";
    var apple = /iPhone|iPad|iPod/.test(agent) || (/Macintosh/.test(agent) && navigator.maxTouchPoints > 1);
    var android = /Android/.test(agent);
    if (!apple && !android) {
      return;
    }
    document.querySelectorAll("details[data-platform]").forEach(function (box) {
      box.open = box.dataset.platform === (apple ? "ios" : "android");
    });
  }

  // A strip that scrolls sideways shows its chosen item (the booking days).
  function keepCurrentInView() {
    document.querySelectorAll("[data-keep-current-in-view]").forEach(function (strip) {
      var current = strip.querySelector("[aria-current]");
      if (current) {
        strip.scrollLeft = current.offsetLeft - strip.clientWidth / 2 + current.clientWidth / 2;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    keepCurrentInView();
    openStepsOfThisPhone();
    showInstallState();
    syncPushDevice();
    setUpStaffMenu();
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
