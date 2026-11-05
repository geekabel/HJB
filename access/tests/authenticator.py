"""Software authenticator for the tests: a "phone" that creates and uses passkeys.

It produces the same JSON responses as a browser (the format expected by
django-otp-webauthn): a real ES256 key, signed data, "none" attestation.
So the server checks everything (challenge, origin, RP ID, signature,
user verification) as in real life, without mocks.

Data format: WebAuthn Level 3 specification, "Authenticator Data" and
"Attestation Object" (https://www.w3.org/TR/webauthn-3/).
"""

import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

ORIGIN = "http://localhost:8000"
RP_ID = "localhost"

FLAG_USER_PRESENT = 0x01  # UP: the person touched the device
FLAG_USER_VERIFIED = 0x04  # UV: Face ID, fingerprint or PIN
FLAG_ATTESTED_DATA = 0x40  # AT: the public key follows


class SoftwareAuthenticator:
    def __init__(self, origin=ORIGIN, rp_id=RP_ID):
        self.origin = origin
        self.rp_id = rp_id
        self.keys = {}  # credential id -> (private key, user handle)

    def _authenticator_data(self, flags, extra=b""):
        rp_id_hash = hashlib.sha256(self.rp_id.encode()).digest()
        return rp_id_hash + bytes([flags]) + struct.pack(">I", 0) + extra

    def _client_data(self, type_, challenge, origin):
        return json.dumps(
            {"type": type_, "challenge": challenge, "origin": origin or self.origin},
            separators=(",", ":"),
        ).encode()

    @staticmethod
    def _new_key():
        private_key = ec.generate_private_key(ec.SECP256R1())
        numbers = private_key.public_key().public_numbers()
        cose_key = cbor2.dumps(
            {
                1: 2,  # kty: EC2
                3: -7,  # alg: ES256
                -1: 1,  # crv: P-256
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )
        return private_key, cose_key, os.urandom(32)

    def register(self, user):
        """Create a passkey and save it straight to the database (a shortcut for the tests)."""
        from django_otp_webauthn.models import WebAuthnUserHandle
        from django_otp_webauthn.utils import get_credential_model

        private_key, cose_key, credential_id = self._new_key()
        self.keys[credential_id] = (private_key, WebAuthnUserHandle.get_handle_for_user(user))
        return get_credential_model().objects.create(
            user=user,
            credential_id=credential_id,
            public_key=cose_key,
            aaguid="00000000-0000-0000-0000-000000000000",
            transports=["internal"],
            discoverable=True,
        )

    def create(self, options, *, user_verified=True, origin=None, credential_id=None):
        """Response to navigator.credentials.create() for these options."""
        private_key, cose_key, new_credential_id = self._new_key()
        credential_id = credential_id or new_credential_id
        self.keys[credential_id] = (private_key, base64url_to_bytes(options["user"]["id"]))
        flags = (
            FLAG_USER_PRESENT | FLAG_ATTESTED_DATA | (FLAG_USER_VERIFIED if user_verified else 0)
        )
        attested_data = bytes(16) + struct.pack(">H", len(credential_id)) + credential_id + cose_key
        attestation = cbor2.dumps(
            {
                "fmt": "none",
                "attStmt": {},
                "authData": self._authenticator_data(flags, attested_data),
            }
        )
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        encoded_id = bytes_to_base64url(credential_id)
        return {
            "id": encoded_id,
            "rawId": encoded_id,
            "type": "public-key",
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {"credProps": {"rk": True}},
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "attestationObject": bytes_to_base64url(attestation),
                "transports": ["internal", "hybrid"],
            },
        }

    def get(self, options, *, credential_id=None, user_verified=True, origin=None):
        """Response to navigator.credentials.get(). By default, the last passkey created."""
        if credential_id is None:
            credential_id = list(self.keys)[-1]
        private_key, user_handle = self.keys[credential_id]
        auth_data = self._authenticator_data(
            FLAG_USER_PRESENT | (FLAG_USER_VERIFIED if user_verified else 0)
        )
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        signature = private_key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        encoded_id = bytes_to_base64url(credential_id)
        return {
            "id": encoded_id,
            "rawId": encoded_id,
            "type": "public-key",
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(signature),
                "userHandle": bytes_to_base64url(user_handle),
            },
        }
