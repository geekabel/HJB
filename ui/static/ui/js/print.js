// "Imprimer" (print) buttons: <button type="button" data-print>.
document.querySelectorAll("[data-print]").forEach((button) => {
  button.addEventListener("click", () => window.print());
});
