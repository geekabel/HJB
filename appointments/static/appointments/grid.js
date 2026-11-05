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
  var rows = Array.prototype.slice.call(grid.tBodies[0].rows);
  var origin = null; // [row, column] of the first cell of the drag
  var mode = false; // true: open the cells, false: close them
  var skipClick = false;

  function place(target) {
    var cell = target.closest && target.closest("td");
    if (!cell || !grid.contains(cell) || !cell.querySelector(".slot")) {
      return null;
    }
    return [rows.indexOf(cell.parentElement), cell.cellIndex];
  }

  function boxAt(row, column) {
    var cell = rows[row] && rows[row].cells[column];
    return cell ? cell.querySelector("input") : null;
  }

  function set(box) {
    if (box && box.checked !== mode) {
      box.checked = mode;
      // Other scripts (a counter, an "unsaved" warning) see the change.
      box.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  // Every cell of the rectangle between the first cell and this one: a fast
  // drag skips cells on the way, the rectangle does not.
  function fill(to) {
    var top = Math.min(origin[0], to[0]);
    var bottom = Math.max(origin[0], to[0]);
    var left = Math.min(origin[1], to[1]);
    var right = Math.max(origin[1], to[1]);
    for (var row = top; row <= bottom; row += 1) {
      for (var column = left; column <= right; column += 1) {
        set(boxAt(row, column));
      }
    }
  }

  function stop() {
    origin = null;
  }

  grid.addEventListener("pointerdown", function (event) {
    var at = place(event.target);
    if (!at || event.pointerType !== "mouse" || event.button !== 0) {
      skipClick = false; // touch and pen: the normal tap on the checkbox
      return;
    }
    event.preventDefault(); // no text selection while dragging
    var box = boxAt(at[0], at[1]);
    origin = at;
    skipClick = true;
    mode = !box.checked;
    set(box);
    box.focus({ preventScroll: true });
  });

  grid.addEventListener("pointerover", function (event) {
    if (!origin) {
      return;
    }
    if ((event.buttons & 1) === 0) {
      stop(); // the button was released elsewhere (another window)
      return;
    }
    var at = place(event.target);
    if (at) {
      fill(at);
    }
  });

  document.addEventListener("pointerup", function (event) {
    stop();
    if (!grid.contains(event.target)) {
      skipClick = false; // released outside: no click will reach the grid
    }
  });
  document.addEventListener("pointercancel", stop);
  window.addEventListener("blur", stop);

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
