/*
 * Message fields (cards T20, T21): a button writes its {field} where the
 * cursor is, in the last text field with [data-field-target] that had focus
 * (the message, else). No typing mistake in a name like {début}.
 * Docs: https://developer.mozilla.org/en-US/docs/Web/API/HTMLInputElement/setRangeText
 */
(function () {
  "use strict";

  var targets = document.querySelectorAll("[data-field-target]");
  if (!targets.length) {
    return;
  }
  var last = document.querySelector("textarea[data-field-target]") || targets[0];
  targets.forEach(function (field) {
    field.addEventListener("focus", function () {
      last = field;
    });
  });

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-insert]");
    if (!button) {
      return;
    }
    var text = button.getAttribute("data-insert");
    var start = typeof last.selectionStart === "number" ? last.selectionStart : last.value.length;
    var end = typeof last.selectionEnd === "number" ? last.selectionEnd : start;
    last.setRangeText(text, start, end, "end");
    last.focus();
    // Counters and other listeners see the new text.
    last.dispatchEvent(new Event("input", { bubbles: true }));
  });
})();
