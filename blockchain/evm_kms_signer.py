"""
Native AWS KMS secp256k1 signer for the BSC sponsor hot wallet.

EVM counterpart of ``blockchain.kms_manager.NativeKMSSigner``: the sponsor
key is an asymmetric KMS key with

    KeySpec=ECC_SECG_P256K1
    KeyUsage=SIGN_VERIFY
    SigningAlgorithm=ECDSA_SHA_256
    MessageType=DIGEST

The private key never leaves KMS. The signer sends the 32-byte keccak256
transaction digest to KMS, DER-decodes the returned (r, s), normalizes s to
the low-s form required by EVM chains (EIP-2), determines the recovery id by
comparing recovered addresses against the KMS public key, and RLP-encodes
the signed transaction.

The 3-of-5 admin multisig (Gnosis Safe owned by the confio1-confio5 KMS
keys) is deliberately NOT integrated here — its tooling lives outside the
repository, next to the Algorand multisig scripts.
"""

import logging
from typing import Optional, Tuple

import boto3
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

BSC_MAINNET_CHAIN_ID = 56
BSC_TESTNET_CHAIN_ID = 97


def _der_decode_signature(der: bytes) -> Tuple[int, int]:
    """Decode a DER ECDSA signature into (r, s) integers."""
    if der[0] != 0x30:
        raise ValueError("Invalid DER signature: missing SEQUENCE tag")
    offset = 2
    if der[1] & 0x80:
        offset = 2 + (der[1] & 0x7F)
    if der[offset] != 0x02:
        raise ValueError("Invalid DER signature: missing INTEGER tag for r")
    r_len = der[offset + 1]
    r = int.from_bytes(der[offset + 2:offset + 2 + r_len], "big")
    offset = offset + 2 + r_len
    if der[offset] != 0x02:
        raise ValueError("Invalid DER signature: missing INTEGER tag for s")
    s_len = der[offset + 1]
    s = int.from_bytes(der[offset + 2:offset + 2 + s_len], "big")
    return r, s


class EVMKMSSigner:
    """
    Signs EVM (BSC) transactions using an AWS KMS native secp256k1 key.

    Construction accepts a KMS key alias (e.g.
    "confio-mainnet-sponsor-evm-secp256k1"), a fully-qualified alias path
    ("alias/<name>"), or a key ARN. AWS credentials come from the default
    boto3 chain unless a profile is supplied; on EC2/ECS this is the
    instance role.
    """

    def __init__(
        self,
        key_alias: str,
        region_name: str = "eu-central-2",
        profile_name: Optional[str] = None,
    ):
        if not key_alias:
            raise ImproperlyConfigured("EVMKMSSigner requires a key alias or ARN.")
        if key_alias.startswith("arn:") or key_alias.startswith("alias/"):
            self.key_id = key_alias
        else:
            self.key_id = f"alias/{key_alias}"
        self.key_alias = key_alias
        self.region_name = region_name

        session_kwargs = {"region_name": region_name}
        if profile_name:
            session_kwargs["profile_name"] = profile_name
        self.kms_client = boto3.Session(**session_kwargs).client("kms")

        self._public_key: Optional[bytes] = None
        self._address: Optional[str] = None

    def _get_public_key_bytes(self) -> bytes:
        """Return the raw 64-byte secp256k1 public key (X||Y) from KMS."""
        if self._public_key is not None:
            return self._public_key

        response = self.kms_client.get_public_key(KeyId=self.key_id)
        spec = (response.get("KeySpec"), response.get("KeyUsage"))
        if spec != ("ECC_SECG_P256K1", "SIGN_VERIFY"):
            raise ImproperlyConfigured(
                f"KMS key {self.key_id} is {spec}; expected "
                "('ECC_SECG_P256K1', 'SIGN_VERIFY') for EVM signing."
            )

        point = response["PublicKey"][-65:]
        if point[0] != 0x04 or len(point) != 65:
            raise ValueError(
                f"Expected uncompressed secp256k1 point in SPKI DER for {self.key_id}"
            )

        self._public_key = point[1:]
        return self._public_key

    @property
    def address(self) -> str:
        """EIP-55 checksummed EVM address of the KMS key."""
        if self._address is None:
            from eth_utils import keccak, to_checksum_address

            self._address = to_checksum_address(
                keccak(self._get_public_key_bytes())[-20:]
            )
        return self._address

    def sign_digest(self, digest: bytes) -> Tuple[int, int, int]:
        """
        Sign a 32-byte digest with KMS and return (v, r, s) with v in {0, 1}
        (the raw recovery id / y-parity, before any EIP-155 offset).
        """
        from eth_keys.datatypes import Signature
        from eth_utils import to_checksum_address

        if len(digest) != 32:
            raise ValueError(f"Expected 32-byte digest, got {len(digest)}")

        response = self.kms_client.sign(
            KeyId=self.key_id,
            Message=digest,
            MessageType="DIGEST",
            SigningAlgorithm="ECDSA_SHA_256",
        )
        r, s = _der_decode_signature(response["Signature"])
        if s > SECP256K1_N // 2:
            s = SECP256K1_N - s

        expected = self.address
        for v in (0, 1):
            recovered = Signature(vrs=(v, r, s)).recover_public_key_from_msg_hash(digest)
            if to_checksum_address(recovered.to_address()) == expected:
                return v, r, s
        raise ValueError(f"Could not determine recovery id for {self.key_id}")

    def sign_transaction(self, tx: dict) -> Tuple[str, str]:
        """
        Sign a legacy (type-0, EIP-155) transaction dict and return
        (raw_tx_hex, tx_hash_hex) ready for eth_sendRawTransaction.

        The dict must include chainId, nonce, gasPrice, gas, to, value, data.
        """
        from eth_account._utils.legacy_transactions import (
            encode_transaction,
            serializable_unsigned_transaction_from_dict,
        )
        from eth_utils import keccak

        chain_id = tx["chainId"]
        unsigned = serializable_unsigned_transaction_from_dict(dict(tx))
        v, r, s = self.sign_digest(unsigned.hash())
        encoded = encode_transaction(unsigned, vrs=(v + 35 + chain_id * 2, r, s))
        raw_hex = "0x" + encoded.hex()
        tx_hash = "0x" + keccak(encoded).hex()
        logger.info(
            "BSC transaction %s signed with native KMS key %s (alias=%s)",
            tx_hash,
            self.key_id,
            self.key_alias,
        )
        return raw_hex, tx_hash

    def assert_matches_address(self, expected_address: Optional[str]) -> None:
        if expected_address and expected_address.lower() != self.address.lower():
            raise ImproperlyConfigured(
                f"BSC KMS alias '{self.key_alias}' resolves to {self.address}, "
                f"but settings configured {expected_address}"
            )


def get_bsc_sponsor_signer_from_settings() -> EVMKMSSigner:
    """
    Construct the BSC sponsor hot wallet signer from Django settings.

    Unlike the Algorand signer, this is lazy — nothing is instantiated at
    settings import time, so environments without BSC signing configured
    (USE_BSC_KMS_SIGNING=False) are unaffected.
    """
    from django.conf import settings

    if not getattr(settings, "USE_BSC_KMS_SIGNING", False):
        raise ImproperlyConfigured("USE_BSC_KMS_SIGNING must be enabled for BSC sponsor signing.")

    alias = getattr(settings, "BSC_KMS_KEY_ALIAS", None)
    if not alias:
        raise ImproperlyConfigured("BSC_KMS_KEY_ALIAS is required when USE_BSC_KMS_SIGNING=True.")

    region = getattr(settings, "BSC_KMS_REGION", None) or "eu-central-2"
    signer = EVMKMSSigner(alias, region_name=region)
    signer.assert_matches_address(getattr(settings, "BSC_SPONSOR_ADDRESS", None))
    return signer
