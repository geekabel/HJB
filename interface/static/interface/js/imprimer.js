// Boutons « Imprimer » : <button type="button" data-imprimer>.
document.querySelectorAll("[data-imprimer]").forEach((bouton) => {
  bouton.addEventListener("click", () => window.print());
});
