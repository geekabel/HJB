// The front desk QR code opens /activer/#ABCDE-FGHJK. The code is after the "#":
// the browser never sends it to the server. We copy it into the field, then
// remove it from the address so that it does not stay in the history.
(() => {
  const code = decodeURIComponent(window.location.hash.slice(1)).trim();
  const field = document.getElementById("id_code");
  if (!code || !field) return;
  if (!field.value) field.value = code;
  history.replaceState(null, "", window.location.pathname + window.location.search);
})();
