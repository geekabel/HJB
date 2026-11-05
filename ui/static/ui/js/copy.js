/*
 * "Copy" buttons (card T16).
 *
 * A button with data-copy="<id>" copies the text of the element with that id.
 * The buttons stay hidden without JavaScript, or when the browser cannot
 * write to the clipboard (Clipboard API: only on a secure page, https).
 * Docs: https://developer.mozilla.org/en-US/docs/Web/API/Clipboard/writeText
 */
(function () {
  "use strict";

  if (!window.isSecureContext || !navigator.clipboard) {
    return;
  }
  var status = document.querySelector("[data-copy-status]");

  // Empty the live region first, so that the same message is read again.
  function say(text) {
    if (!status) {
      return;
    }
    status.textContent = "";
    window.setTimeout(function () {
      status.textContent = text;
    }, 100);
  }

  document.querySelectorAll("button[data-copy]").forEach(function (button) {
    var source = document.getElementById(button.dataset.copy);
    if (!source) {
      return;
    }
    button.hidden = false;
    button.addEventListener("click", function () {
      navigator.clipboard.writeText(source.textContent.trim()).then(
        function () {
          say(button.dataset.copied || "Copié.");
        },
        function () {
          say("La copie n'a pas marché. Touchez le texte pour le sélectionner, puis copiez-le.");
        }
      );
    });
  });
})();
