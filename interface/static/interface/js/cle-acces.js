// Clés d'accès (passkeys) : création à l'activation, connexion et confirmation.
//
// API du navigateur : navigator.credentials.create() et get() (MDN, Web
// Authentication API). Le serveur (django-otp-webauthn) envoie ses options en
// JSON, avec les données binaires en base64url, et attend la réponse au même
// format. Les conversions sont faites ici, sans bibliothèque.
//
// Gabarit attendu :
// - <script type="application/json" id="cle-acces-config"> : mode (creation,
//   connexion ou confirmation), adresses debut et fin, page suivante ;
// - un jeton CSRF ({% csrf_token %}) ;
// - [data-cle-acces-bouton] (caché au départ), [data-cle-acces-statut] (zone
//   annoncée aux lecteurs d'écran), [data-cle-acces-indisponible] (caché).
(() => {
  const elementConfig = document.getElementById("cle-acces-config");
  const bouton = document.querySelector("[data-cle-acces-bouton]");
  const statut = document.querySelector("[data-cle-acces-statut]");
  const indisponible = document.querySelector("[data-cle-acces-indisponible]");
  const jeton = document.querySelector("input[name='csrfmiddlewaretoken']");
  if (!elementConfig || !bouton || !statut || !jeton) return;
  const config = JSON.parse(elementConfig.textContent);

  if (!window.PublicKeyCredential || !navigator.credentials) {
    if (indisponible) indisponible.hidden = false;
    return;
  }
  bouton.hidden = false;
  const libelle = bouton.textContent;

  // base64url <-> octets
  const versOctets = (texte) => {
    const base64 = texte.replace(/-/g, "+").replace(/_/g, "/");
    const binaire = atob(base64 + "=".repeat((4 - (base64.length % 4)) % 4));
    return Uint8Array.from(binaire, (c) => c.charCodeAt(0)).buffer;
  };
  const versTexte = (tampon) => {
    let binaire = "";
    for (const octet of new Uint8Array(tampon)) binaire += String.fromCharCode(octet);
    return btoa(binaire).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  };
  const avecIdentifiants = (liste) => (liste || []).map((c) => ({ ...c, id: versOctets(c.id) }));

  class ErreurServeur extends Error {
    constructor(message, statutHttp, code) {
      super(message);
      this.statutHttp = statutHttp;
      this.code = code;
    }
  }

  function afficher(message, genre) {
    statut.replaceChildren();
    if (!message) return;
    const bandeau = document.createElement("div");
    bandeau.className = `alerte alerte--${genre}`;
    const icone = document.querySelector(`template[data-cle-acces-icone="${genre}"]`);
    if (icone) bandeau.append(icone.content.cloneNode(true));
    const texte = document.createElement("p");
    texte.textContent = message;
    bandeau.append(texte);
    statut.append(bandeau);
  }

  function occupe(oui, texte) {
    bouton.disabled = oui;
    bouton.setAttribute("aria-busy", oui ? "true" : "false");
    bouton.textContent = oui ? texte : libelle;
  }

  async function appeler(adresse, corps) {
    let reponse;
    try {
      reponse = await fetch(adresse, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "X-CSRFToken": jeton.value,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: corps === undefined ? "" : JSON.stringify(corps),
      });
    } catch {
      // fetch() échoue (TypeError) quand le réseau ne répond pas.
      throw new ErreurServeur(
        "Pas de connexion au réseau. Vérifiez votre wifi ou vos données, puis réessayez.",
        0,
        "reseau",
      );
    }
    let donnees = null;
    try {
      donnees = await reponse.json();
    } catch {
      // Pas de JSON : erreur du serveur, traitée ci-dessous.
    }
    if (!reponse.ok || !donnees) {
      let message = "Le serveur ne répond pas. Réessayez dans un instant.";
      if (donnees && donnees.detail) {
        message = donnees.detail;
      } else if (reponse.status === 403) {
        // Page HTML de refus CSRF : le jeton a changé (connexion dans un autre onglet).
        message = "La page a expiré. Rechargez-la, puis réessayez.";
      }
      throw new ErreurServeur(message, reponse.status, donnees && donnees.code);
    }
    return donnees;
  }

  async function creer(options) {
    const publicKey = {
      ...options,
      challenge: versOctets(options.challenge),
      user: { ...options.user, id: versOctets(options.user.id) },
      excludeCredentials: avecIdentifiants(options.excludeCredentials),
    };
    const cle = await navigator.credentials.create({ publicKey });
    const reponse = cle.response;
    return {
      id: cle.id,
      rawId: versTexte(cle.rawId),
      type: cle.type,
      authenticatorAttachment: cle.authenticatorAttachment || undefined,
      clientExtensionResults: cle.getClientExtensionResults(),
      response: {
        clientDataJSON: versTexte(reponse.clientDataJSON),
        attestationObject: versTexte(reponse.attestationObject),
        transports: reponse.getTransports ? reponse.getTransports() : [],
      },
    };
  }

  async function verifier(options) {
    const publicKey = {
      ...options,
      challenge: versOctets(options.challenge),
      allowCredentials: avecIdentifiants(options.allowCredentials),
    };
    const cle = await navigator.credentials.get({ publicKey });
    const reponse = cle.response;
    const resultat = {
      id: cle.id,
      rawId: versTexte(cle.rawId),
      type: cle.type,
      authenticatorAttachment: cle.authenticatorAttachment || undefined,
      clientExtensionResults: cle.getClientExtensionResults(),
      response: {
        clientDataJSON: versTexte(reponse.clientDataJSON),
        authenticatorData: versTexte(reponse.authenticatorData),
        signature: versTexte(reponse.signature),
      },
    };
    if (reponse.userHandle) resultat.response.userHandle = versTexte(reponse.userHandle);
    return resultat;
  }

  // Messages pour les erreurs du navigateur (DOMException).
  function messageNavigateur(erreur) {
    const creation = config.mode === "creation";
    switch (erreur.name) {
      case "NotAllowedError":
        return creation
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

  // Le serveur ne connaît pas cette clé : on demande au navigateur de l'oublier,
  // s'il sait le faire (PublicKeyCredential.signalUnknownCredential, MDN).
  async function signalerCleInconnue(identifiant, domaine) {
    if (!identifiant || !domaine || !("signalUnknownCredential" in PublicKeyCredential)) return;
    try {
      await PublicKeyCredential.signalUnknownCredential({ rpId: domaine, credentialId: identifiant });
    } catch {
      // Sans importance : la personne verra seulement la clé dans sa liste.
    }
  }

  bouton.addEventListener("click", async () => {
    const creation = config.mode === "creation";
    afficher("");
    occupe(true, "Patientez…");
    let options = null;
    let resultat = null;
    try {
      options = await appeler(config.debut);
      resultat = creation ? await creer(options) : await verifier(options);
      occupe(true, "Vérification…");
      const fin = new URL(config.fin, window.location.origin);
      if (config.suite) fin.searchParams.set("next", config.suite);
      const reponse = await appeler(fin.pathname + fin.search, resultat);
      afficher(
        creation ? "Votre clé d'accès est créée. Bienvenue." : "C'est bien vous.",
        "succes",
      );
      window.location.assign(reponse.redirect_url || config.suite || "/");
    } catch (erreur) {
      occupe(false);
      if (erreur instanceof ErreurServeur) {
        if (erreur.code === "credential_not_found" && resultat && options) {
          signalerCleInconnue(resultat.id, options.rpId);
        }
        afficher(erreur.message, "attention");
      } else {
        afficher(messageNavigateur(erreur), "attention");
      }
      bouton.focus();
    }
  });
})();
