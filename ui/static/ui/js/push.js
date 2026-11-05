/*
 * Notification settings (card T19): turn Web Push on or off on this device.
 *
 * The permission is asked only after a tap on "Activer" (MDN: browsers refuse
 * a request that does not follow a user gesture). On iPhone, the Push API
 * exists only in the application opened from the home screen.
 * Docs: https://developer.mozilla.org/en-US/docs/Web/API/PushManager/subscribe
 */
(function () {
  "use strict";

  var box = document.querySelector("[data-push]");
  if (!box) {
    return;
  }
  var errorLine = box.querySelector("[data-push-error]");
  var token = box.querySelector("[name=csrfmiddlewaretoken]").value;

  function show(state) {
    box.querySelectorAll("[data-push-state]").forEach(function (element) {
      element.hidden = element.dataset.pushState !== state;
    });
  }

  function fail(text) {
    errorLine.textContent = text;
  }

  // applicationServerKey: the base64url public key, as bytes (MDN example).
  function keyBytes(base64url) {
    var padding = "=".repeat((4 - (base64url.length % 4)) % 4);
    var raw = window.atob((base64url + padding).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, function (c) {
      return c.charCodeAt(0);
    });
  }

  function post(url, data) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": token },
      body: JSON.stringify(data),
    }).then(function (response) {
      if (!response.ok) {
        throw new Error("server " + response.status);
      }
      return response.json();
    });
  }

  function send(subscription, mode) {
    var data = subscription.toJSON();
    data.mode = mode;
    return post(box.dataset.subscribeUrl, data);
  }

  function isAppleMobile() {
    return /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  }

  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    show(isAppleMobile() ? "install" : "unsupported");
    return;
  }
  if (!box.dataset.publicKey) {
    show("unconfigured");
    return;
  }

  function refresh() {
    if (Notification.permission === "denied") {
      show("denied");
      return Promise.resolve();
    }
    return navigator.serviceWorker.ready
      .then(function (registration) {
        return registration.pushManager.getSubscription();
      })
      .then(function (subscription) {
        if (!subscription) {
          show("off");
          return;
        }
        // Known for this account? A device left by someone else stays "off" here.
        return send(subscription, "sync").then(function (answer) {
          show(answer.known ? "on" : "off");
        });
      })
      .catch(function () {
        show("off");
      });
  }

  box.querySelector("[data-push-enable]").addEventListener("click", function () {
    fail("");
    Notification.requestPermission()
      .then(function (permission) {
        if (permission !== "granted") {
          show(permission === "denied" ? "denied" : "off");
          return null;
        }
        return navigator.serviceWorker.ready.then(function (registration) {
          return registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: keyBytes(box.dataset.publicKey),
          });
        });
      })
      .then(function (subscription) {
        if (subscription) {
          return send(subscription, "enable").then(function () {
            window.location.reload(); // the list of devices shows the new one
          });
        }
      })
      .catch(function () {
        fail("L'activation n'a pas marché. Réessayez, ou vérifiez que les notifications sont permises pour ce site.");
      });
  });

  box.querySelector("[data-push-disable]").addEventListener("click", function () {
    fail("");
    navigator.serviceWorker.ready
      .then(function (registration) {
        return registration.pushManager.getSubscription();
      })
      .then(function (subscription) {
        if (!subscription) {
          return null;
        }
        var endpoint = subscription.endpoint;
        return subscription.unsubscribe().then(function () {
          return post(box.dataset.unsubscribeUrl, { endpoint: endpoint });
        });
      })
      .then(function () {
        window.location.reload();
      })
      .catch(function () {
        fail("La désactivation n'a pas marché. Réessayez.");
      });
  });

  refresh();
})();
