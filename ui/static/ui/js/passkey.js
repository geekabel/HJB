// Passkeys: creation during activation, login and confirmation.
//
// Browser API: navigator.credentials.create() and get() (MDN, Web
// Authentication API). The server (django-otp-webauthn) sends its options as
// JSON, with binary data in base64url, and expects the response in the same
// format. The conversions are done here, without a library.
//
// Expected template:
// - <script type="application/json" id="passkey-config">: mode (register,
//   login or confirm), begin and complete URLs, next page;
// - a CSRF token ({% csrf_token %});
// - [data-passkey-button] (hidden at first), [data-passkey-status] (area
//   announced to screen readers), [data-passkey-unavailable] (hidden).
(() => {
  const configElement = document.getElementById("passkey-config");
  const button = document.querySelector("[data-passkey-button]");
  const status = document.querySelector("[data-passkey-status]");
  const unavailable = document.querySelector("[data-passkey-unavailable]");
  const csrfInput = document.querySelector("input[name='csrfmiddlewaretoken']");
  if (!configElement || !button || !status || !csrfInput) return;
  const config = JSON.parse(configElement.textContent);

  if (!window.PublicKeyCredential || !navigator.credentials) {
    if (unavailable) unavailable.hidden = false;
    return;
  }
  button.hidden = false;
  const label = button.textContent;

  // base64url <-> bytes
  const toBytes = (text) => {
    const base64 = text.replace(/-/g, "+").replace(/_/g, "/");
    const binary = atob(base64 + "=".repeat((4 - (base64.length % 4)) % 4));
    return Uint8Array.from(binary, (c) => c.charCodeAt(0)).buffer;
  };
  const toText = (buffer) => {
    let binary = "";
    for (const byte of new Uint8Array(buffer)) binary += String.fromCharCode(byte);
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  };
  const withBinaryIds = (list) => (list || []).map((c) => ({ ...c, id: toBytes(c.id) }));

  class ServerError extends Error {
    constructor(message, httpStatus, code) {
      super(message);
      this.httpStatus = httpStatus;
      this.code = code;
    }
  }

  function show(message, kind) {
    status.replaceChildren();
    if (!message) return;
    const banner = document.createElement("div");
    banner.className = `alert alert--${kind}`;
    const icon = document.querySelector(`template[data-passkey-icon="${kind}"]`);
    if (icon) banner.append(icon.content.cloneNode(true));
    const text = document.createElement("p");
    text.textContent = message;
    banner.append(text);
    status.append(banner);
  }

  function setBusy(busy, text) {
    button.disabled = busy;
    button.setAttribute("aria-busy", busy ? "true" : "false");
    button.textContent = busy ? text : label;
  }

  async function callServer(url, body) {
    let response;
    try {
      response = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "X-CSRFToken": csrfInput.value,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: body === undefined ? "" : JSON.stringify(body),
      });
    } catch {
      // fetch() fails (TypeError) when the network does not answer.
      throw new ServerError(
        "Pas de connexion au réseau. Vérifiez votre wifi ou vos données, puis réessayez.",
        0,
        "network",
      );
    }
    let data = null;
    try {
      data = await response.json();
    } catch {
      // No JSON: a server error, handled below.
    }
    if (!response.ok || !data) {
      let message = "Le serveur ne répond pas. Réessayez dans un instant.";
      if (data && data.detail) {
        message = data.detail;
      } else if (response.status === 403) {
        // CSRF failure HTML page: the token changed (login in another tab).
        message = "La page a expiré. Rechargez-la, puis réessayez.";
      }
      throw new ServerError(message, response.status, data && data.code);
    }
    return data;
  }

  async function createCredential(options) {
    const publicKey = {
      ...options,
      challenge: toBytes(options.challenge),
      user: { ...options.user, id: toBytes(options.user.id) },
      excludeCredentials: withBinaryIds(options.excludeCredentials),
    };
    const credential = await navigator.credentials.create({ publicKey });
    const response = credential.response;
    return {
      id: credential.id,
      rawId: toText(credential.rawId),
      type: credential.type,
      authenticatorAttachment: credential.authenticatorAttachment || undefined,
      clientExtensionResults: credential.getClientExtensionResults(),
      response: {
        clientDataJSON: toText(response.clientDataJSON),
        attestationObject: toText(response.attestationObject),
        transports: response.getTransports ? response.getTransports() : [],
      },
    };
  }

  async function getCredential(options) {
    const publicKey = {
      ...options,
      challenge: toBytes(options.challenge),
      allowCredentials: withBinaryIds(options.allowCredentials),
    };
    const credential = await navigator.credentials.get({ publicKey });
    const response = credential.response;
    const result = {
      id: credential.id,
      rawId: toText(credential.rawId),
      type: credential.type,
      authenticatorAttachment: credential.authenticatorAttachment || undefined,
      clientExtensionResults: credential.getClientExtensionResults(),
      response: {
        clientDataJSON: toText(response.clientDataJSON),
        authenticatorData: toText(response.authenticatorData),
        signature: toText(response.signature),
      },
    };
    if (response.userHandle) result.response.userHandle = toText(response.userHandle);
    return result;
  }

  // Messages for browser errors (DOMException).
  function browserMessage(error) {
    const registering = config.mode === "register";
    switch (error.name) {
      case "NotAllowedError":
        return registering
          ? "La création a été annulée, ou le délai est dépassé. Réessayez quand vous êtes prêt."
          : "La vérification a été annulée, ou le délai est dépassé. Réessayez. Pas de clé sur cet appareil ? Utilisez le téléphone où vous l'avez créée.";
      case "SecurityError":
        return "Les clés d'accès ne marchent pas à cette adresse. Prévenez l'accueil.";
      case "AbortError":
        return "L'opération a été interrompue. Réessayez.";
      default:
        return "Votre appareil n'a pas pu utiliser la clé d'accès. Réessayez, ou passez à l'accueil.";
    }
  }

  // The server does not know this passkey: ask the browser to forget it,
  // if it can (PublicKeyCredential.signalUnknownCredential, MDN).
  async function signalUnknownPasskey(credentialId, rpId) {
    if (!credentialId || !rpId || !("signalUnknownCredential" in PublicKeyCredential)) return;
    try {
      await PublicKeyCredential.signalUnknownCredential({ rpId, credentialId });
    } catch {
      // Not important: the person will only see the passkey in their list.
    }
  }

  button.addEventListener("click", async () => {
    const registering = config.mode === "register";
    show("");
    setBusy(true, "Patientez…");
    let options = null;
    let result = null;
    try {
      options = await callServer(config.begin);
      result = registering ? await createCredential(options) : await getCredential(options);
      setBusy(true, "Vérification…");
      const completeUrl = new URL(config.complete, window.location.origin);
      if (config.next) completeUrl.searchParams.set("next", config.next);
      const response = await callServer(completeUrl.pathname + completeUrl.search, result);
      show(registering ? "Votre clé d'accès est créée. Bienvenue." : "C'est bien vous.", "success");
      window.location.assign(response.redirect_url || config.next || "/");
    } catch (error) {
      setBusy(false);
      if (error instanceof ServerError) {
        if (error.code === "credential_not_found" && result && options) {
          signalUnknownPasskey(result.id, options.rpId);
        }
        show(error.message, "warning");
      } else {
        show(browserMessage(error), "warning");
      }
      button.focus();
    }
  });
})();
