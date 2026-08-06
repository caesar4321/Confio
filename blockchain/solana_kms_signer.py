"""Native AWS KMS Ed25519 signer for the Solana fee sponsor.

The sponsor key is an asymmetric KMS key with::

    KeySpec=ECC_NIST_EDWARDS25519
    KeyUsage=SIGN_VERIFY
    SigningAlgorithm=ED25519_SHA_512
    MessageType=RAW

Solana signs the serialized transaction message directly.  The private key
therefore never needs to leave KMS (unlike the legacy Algorand sponsor key).
"""

from __future__ import annotations

from typing import Optional

import boto3
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.core.exceptions import ImproperlyConfigured


class SolanaKMSSigner:
    """Sign Solana transaction messages with a native KMS Ed25519 key."""

    def __init__(
        self,
        key_alias: str,
        region_name: str = "eu-central-2",
        profile_name: Optional[str] = None,
        kms_client=None,
    ):
        if not key_alias:
            raise ImproperlyConfigured("SolanaKMSSigner requires a key alias or ARN.")
        self.key_id = (
            key_alias
            if key_alias.startswith(("arn:", "alias/"))
            else f"alias/{key_alias}"
        )
        self.key_alias = key_alias
        self.region_name = region_name
        if kms_client is not None:
            self.kms_client = kms_client
        else:
            session_kwargs = {"region_name": region_name}
            if profile_name:
                session_kwargs["profile_name"] = profile_name
            self.kms_client = boto3.Session(**session_kwargs).client("kms")
        self._public_key: Optional[bytes] = None

    @property
    def public_key_bytes(self) -> bytes:
        """Return the raw 32-byte Ed25519 public key from KMS SPKI DER."""
        if self._public_key is not None:
            return self._public_key

        response = self.kms_client.get_public_key(KeyId=self.key_id)
        spec = (response.get("KeySpec"), response.get("KeyUsage"))
        if spec != ("ECC_NIST_EDWARDS25519", "SIGN_VERIFY"):
            raise ImproperlyConfigured(
                f"KMS key {self.key_id} is {spec}; expected "
                "('ECC_NIST_EDWARDS25519', 'SIGN_VERIFY') for Solana signing."
            )
        public_key = serialization.load_der_public_key(response["PublicKey"])
        if not isinstance(public_key, Ed25519PublicKey):
            raise ImproperlyConfigured(
                f"KMS key {self.key_id} did not contain an Ed25519 public key."
            )
        self._public_key = public_key.public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        return self._public_key

    @property
    def address(self) -> str:
        from solders.pubkey import Pubkey

        return str(Pubkey.from_bytes(self.public_key_bytes))

    def sign_message(self, message: bytes) -> bytes:
        """Return the 64-byte Ed25519 signature over a Solana message."""
        if not message:
            raise ValueError("Cannot sign an empty Solana message.")
        response = self.kms_client.sign(
            KeyId=self.key_id,
            Message=message,
            MessageType="RAW",
            SigningAlgorithm="ED25519_SHA_512",
        )
        signature = bytes(response["Signature"])
        if len(signature) != 64:
            raise ValueError(
                f"KMS returned a {len(signature)}-byte Ed25519 signature; expected 64."
            )
        Ed25519PublicKey.from_public_bytes(self.public_key_bytes).verify(
            signature, message
        )
        return signature

    def assert_matches_address(self, expected_address: Optional[str]) -> None:
        if expected_address and expected_address != self.address:
            raise ImproperlyConfigured(
                f"Solana KMS alias '{self.key_alias}' resolves to {self.address}, "
                f"but settings configured {expected_address}."
            )


def get_solana_sponsor_signer_from_settings() -> SolanaKMSSigner:
    from django.conf import settings

    if not getattr(settings, "USE_SOLANA_KMS_SIGNING", False):
        raise ImproperlyConfigured(
            "USE_SOLANA_KMS_SIGNING must be enabled for Solana sponsorship."
        )
    alias = getattr(settings, "SOLANA_KMS_KEY_ALIAS", None)
    if not alias:
        raise ImproperlyConfigured(
            "SOLANA_KMS_KEY_ALIAS is required when USE_SOLANA_KMS_SIGNING=True."
        )
    signer = SolanaKMSSigner(
        alias,
        region_name=getattr(settings, "SOLANA_KMS_REGION", None)
        or "eu-central-2",
    )
    signer.assert_matches_address(
        getattr(settings, "SOLANA_SPONSOR_ADDRESS", None)
    )
    return signer
