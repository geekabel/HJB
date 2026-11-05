/*
 * Weekly grid of the educator (card T26): click and drag with the mouse to
 * open or close several half hours at once. Without this script, each cell
 * is still a checkbox (keyboard, touch screens).
 * Docs: https://developer.mozilla.org/en-US/docs/Web/API/Pointer_events
 */
(function () {
  "use strict";

  var grid = document.querySelector("[data-slot-grid]");
  if (!grid) {
    return;
  }
  var dragging = false;
  var mode = false; // true: open the cells crossed, false: close them
  var skipClick = false;

  function boxOf(target) {
    var label = target.closest && target.closest(".slot");
    return label && grid.contains(label) ? label.querySelector("input") : null;
  }

  grid.addEventListener("pointerdown", function (event) {
    var box = boxOf(event.target);
    if (!box || event.pointerType !== "mouse" || event.button !== 0) {
      return; // touch and pen: the normal tap on the checkbox
    }
    event.preventDefault(); // no text selection while dragging
    dragging = true;
    skipClick = true;
    mode = !box.checked;
    box.checked = mode;
    box.focus({ preventScroll: true });
  });

  grid.addEventListener("pointerover", function (event) {
    var box = dragging ? boxOf(event.target) : null;
    if (box) {
      box.checked = mode;
    }
  });

  document.addEventListener("pointerup", function () {
    dragging = false;
  });

  // The click that follows a mouse press would toggle the cell again.
  grid.addEventListener(
    "click",
    function (event) {
      if (skipClick && event.detail > 0) {
        event.preventDefault();
      }
      skipClick = false;
    },
    true
  );
})();
