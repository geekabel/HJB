/*
 * Conversation page (card T28): new messages appear without reloading.
 *
 * Every 5 seconds while the page is on screen, asks the server for the
 * messages written after the last one shown (GET <data-poll>?apres=<id>):
 * 204 = nothing new, 200 = list items to add at the end. Stops on any other
 * answer (logged out, conversation closed). A hidden tab asks nothing; it
 * asks at once when it comes back.
 * Real time with WebSocket is for card T41; this is the simple step before.
 * Docs: https://developer.mozilla.org/en-US/docs/Web/API/Document/visibilitychange_event
 */
(function () {
  "use strict";

  var list = document.querySelector("ol.thread[data-poll]");
  if (!list || !window.fetch) {
    return;
  }
  var url = list.getAttribute("data-poll");
  var status = document.querySelector("[data-poll-status]");
  var DELAY = 5000;
  var timer = null;
  var busy = false;
  var stopped = false;

  function lastId() {
    var items = list.querySelectorAll("li[data-id]");
    return items.length ? items[items.length - 1].getAttribute("data-id") : "0";
  }

  function nearBottom() {
    return window.innerHeight + window.scrollY >= document.body.scrollHeight - 200;
  }

  function schedule() {
    clearTimeout(timer);
    if (!stopped && document.visibilityState === "visible") {
      timer = setTimeout(poll, DELAY);
    }
  }

  function poll() {
    if (busy || stopped) {
      return;
    }
    busy = true;
    var follow = nearBottom();
    fetch(url + "?apres=" + encodeURIComponent(lastId()), {
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "text/html" },
      // Logged out: the login redirect is not followed, and polling stops.
      redirect: "manual"
    })
      .then(function (response) {
        if (response.status === 204) {
          return "";
        }
        if (!response.ok) {
          stopped = true;
          return "";
        }
        return response.text();
      })
      .then(function (html) {
        if (!html.trim()) {
          return;
        }
        var before = list.querySelectorAll(".thread__new").length;
        list.insertAdjacentHTML("beforeend", html);
        if (status && list.querySelectorAll(".thread__new").length > before) {
          // Emptied first: the same words again are read out again.
          status.textContent = "";
          setTimeout(function () {
            status.textContent = "Nouveau message.";
          }, 100);
        }
        if (follow) {
          list.lastElementChild.scrollIntoView({ block: "end" });
        }
      })
      .catch(function () {
        // No network for a moment: the next round tries again.
      })
      .then(function () {
        busy = false;
        schedule();
      });
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") {
      poll();
    } else {
      clearTimeout(timer);
    }
  });
  schedule();
})();
