/*
 * Dates and times written in French under their field.
 *
 * A date field shows its value in the format of the phone or the browser,
 * not of the page: an iPhone set to the United States region shows
 * "Nov 12, 2026", even on a French page. Under each date or time field
 * that has a value, this line says it again in French:
 * "jeudi 12 novembre 2026 à 15 h 30". Nothing changes in what is sent.
 * Docs: https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/DateTimeFormat
 */
(function () {
  "use strict";

  if (!window.Intl) {
    return;
  }
  var DAY = new Intl.DateTimeFormat("fr-FR", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric"
  });

  function time(text) {
    var parts = text.split(":");
    var hour = parseInt(parts[0], 10);
    var minute = parts[1] || "00";
    return isNaN(hour) ? "" : minute === "00" ? hour + " h" : hour + " h " + minute;
  }

  function day(text) {
    var parts = text.split("-");
    var date = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
    return isNaN(date.getTime()) ? "" : DAY.format(date);
  }

  function inFrench(input) {
    var value = input.value;
    if (!value) {
      return "";
    }
    if (input.type === "date") {
      return day(value);
    }
    if (input.type === "time") {
      return time(value);
    }
    var both = value.split("T");
    return both.length === 2 ? day(both[0]) + " à " + time(both[1]) : "";
  }

  document
    .querySelectorAll('input[type="date"], input[type="time"], input[type="datetime-local"]')
    .forEach(function (input) {
      var echo = document.createElement("p");
      echo.className = "field__echo";
      echo.setAttribute("aria-hidden", "true"); // the field itself is read out
      input.insertAdjacentElement("afterend", echo);
      function update() {
        var text = inFrench(input);
        echo.textContent = text;
        echo.hidden = !text;
      }
      input.addEventListener("input", update);
      input.addEventListener("change", update);
      update();
    });
})();
