// Le code QR de l'accueil ouvre /activer/#ABCDE-FGHJK. Le code est après le « # » :
// le navigateur ne l'envoie jamais au serveur. On le copie dans le champ, puis
// on l'efface de l'adresse pour qu'il ne reste pas dans l'historique.
(() => {
  const code = decodeURIComponent(window.location.hash.slice(1)).trim();
  const champ = document.getElementById("id_code");
  if (!code || !champ) return;
  if (!champ.value) champ.value = code;
  history.replaceState(null, "", window.location.pathname + window.location.search);
})();
