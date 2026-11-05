"""Authentificateur logiciel pour les tests : un « téléphone » qui crée et utilise des clés.

Il produit les mêmes réponses JSON qu'un navigateur (format attendu par
django-otp-webauthn) : vraie clé ES256, données signées, attestation
« none ». Le serveur vérifie donc tout (défi, origine, domaine, signature,
vérification de l'utilisateur) comme en vrai, sans simulacre.

Format des données : spécification WebAuthn niveau 3, « Authenticator Data »
et « Attestation Object » (https://www.w3.org/TR/webauthn-3/).
"""

import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

ORIGINE = "http://localhost:8000"
DOMAINE = "localhost"

PRESENCE = 0x01  # UP : la personne a touché l'appareil
VERIFICATION = 0x04  # UV : Face ID, empreinte ou code
DONNEES_CLE = 0x40  # AT : la clé publique suit


class Authentificateur:
    def __init__(self, origine=ORIGINE, domaine=DOMAINE):
        self.origine = origine
        self.domaine = domaine
        self.cles = {}  # identifiant -> (clé privée, identifiant de l'utilisateur)

    def _donnees(self, drapeaux, suite=b""):
        empreinte = hashlib.sha256(self.domaine.encode()).digest()
        return empreinte + bytes([drapeaux]) + struct.pack(">I", 0) + suite

    def _client(self, type_, defi, origine):
        return json.dumps(
            {"type": type_, "challenge": defi, "origin": origine or self.origine},
            separators=(",", ":"),
        ).encode()

    @staticmethod
    def _nouvelle_cle():
        privee = ec.generate_private_key(ec.SECP256R1())
        nombres = privee.public_key().public_numbers()
        cle_cose = cbor2.dumps(
            {
                1: 2,  # kty : EC2
                3: -7,  # alg : ES256
                -1: 1,  # crv : P-256
                -2: nombres.x.to_bytes(32, "big"),
                -3: nombres.y.to_bytes(32, "big"),
            }
        )
        return privee, cle_cose, os.urandom(32)

    def enregistrer(self, utilisateur):
        """Crée une clé et l'enregistre directement en base (raccourci pour les tests)."""
        from django_otp_webauthn.models import WebAuthnUserHandle
        from django_otp_webauthn.utils import get_credential_model

        privee, cle_cose, identifiant = self._nouvelle_cle()
        self.cles[identifiant] = (privee, WebAuthnUserHandle.get_handle_for_user(utilisateur))
        return get_credential_model().objects.create(
            user=utilisateur,
            credential_id=identifiant,
            public_key=cle_cose,
            aaguid="00000000-0000-0000-0000-000000000000",
            transports=["internal"],
            discoverable=True,
        )

    def creer(self, options, *, verification=True, origine=None, identifiant=None):
        """Réponse à navigator.credentials.create() pour ces options."""
        privee, cle_cose, nouvel_identifiant = self._nouvelle_cle()
        identifiant = identifiant or nouvel_identifiant
        self.cles[identifiant] = (privee, base64url_to_bytes(options["user"]["id"]))
        drapeaux = PRESENCE | DONNEES_CLE | (VERIFICATION if verification else 0)
        suite = bytes(16) + struct.pack(">H", len(identifiant)) + identifiant + cle_cose
        attestation = cbor2.dumps(
            {"fmt": "none", "attStmt": {}, "authData": self._donnees(drapeaux, suite)}
        )
        client = self._client("webauthn.create", options["challenge"], origine)
        texte = bytes_to_base64url(identifiant)
        return {
            "id": texte,
            "rawId": texte,
            "type": "public-key",
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {"credProps": {"rk": True}},
            "response": {
                "clientDataJSON": bytes_to_base64url(client),
                "attestationObject": bytes_to_base64url(attestation),
                "transports": ["internal", "hybrid"],
            },
        }

    def verifier(self, options, *, identifiant=None, verification=True, origine=None):
        """Réponse à navigator.credentials.get(). Par défaut, la dernière clé créée."""
        if identifiant is None:
            identifiant = list(self.cles)[-1]
        privee, utilisateur = self.cles[identifiant]
        donnees = self._donnees(PRESENCE | (VERIFICATION if verification else 0))
        client = self._client("webauthn.get", options["challenge"], origine)
        signature = privee.sign(
            donnees + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256())
        )
        texte = bytes_to_base64url(identifiant)
        return {
            "id": texte,
            "rawId": texte,
            "type": "public-key",
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": bytes_to_base64url(client),
                "authenticatorData": bytes_to_base64url(donnees),
                "signature": bytes_to_base64url(signature),
                "userHandle": bytes_to_base64url(utilisateur),
            },
        }
