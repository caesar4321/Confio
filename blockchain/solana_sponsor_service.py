"""Policy-enforced Solana transaction fee sponsorship.

Protocol:

1. ``prepare()`` returns the KMS sponsor address and a fresh blockhash.
2. The client compiles a legacy or v0 transaction with that address as fee
   payer, signs its own signer slots, leaves signer slot zero empty, and sends
   the base64 transaction to ``sponsor_and_send()``.
3. The server validates the immutable message, adds only the fee-payer
   signature, simulates, and broadcasts the fully signed transaction.

By default no instruction may reference account zero (the sponsor). A fee
payer is implicitly writable and a signer; the narrow sponsor-aware opt-in is
therefore unavailable unless a flow-specific exact policy hook is supplied.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

import requests
from django.conf import settings
from solders.message import to_bytes_versioned
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from blockchain.solana_kms_signer import (
    get_solana_sponsor_signer_from_settings,
)

logger = logging.getLogger(__name__)

MAX_WIRE_TRANSACTION_BYTES = 1232
DEFAULT_COMMITMENT = "confirmed"


class SolanaSponsorPolicyError(Exception):
    """Stable rejection code safe to return to a client."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ValidatedSponsoredTransaction:
    transaction: VersionedTransaction
    message_bytes: bytes
    program_ids: tuple[str, ...]
    user_signers: tuple[str, ...]
    expected_user_signer: str


PolicyHook = Callable[[ValidatedSponsoredTransaction], None]
FeeAuthorizer = Callable[[int, int, int, ValidatedSponsoredTransaction], object]
TransactionLookup = Callable[[ValidatedSponsoredTransaction], Optional[dict]]
SignatureRecorder = Callable[[str, ValidatedSponsoredTransaction], None]


class SolanaSponsorService:
    """Validate, KMS-sign, simulate, and relay sponsor-paid transactions."""

    def __init__(
        self,
        *,
        signer=None,
        rpc_url: Optional[str] = None,
        rpc_call: Optional[Callable[[str, list], object]] = None,
        allowed_program_ids: Optional[Iterable[str]] = None,
        max_fee_lamports: Optional[int] = None,
        min_sponsor_balance_lamports: Optional[int] = None,
    ):
        self.signer = signer or get_solana_sponsor_signer_from_settings()
        self.rpc_url = rpc_url or getattr(settings, "SOLANA_RPC_URL", "")
        self._rpc_override = rpc_call
        configured_allowlist = frozenset(
            allowed_program_ids
            if allowed_program_ids is not None
            else getattr(settings, "SOLANA_SPONSOR_ALLOWED_PROGRAM_IDS", ())
        )
        # Program restriction is optional on Solana. If the sponsor account is
        # absent from every instruction, an arbitrary program can consume only
        # the bounded fee: it cannot read, write, or debit an account it was
        # not given. Product deployments may still configure a narrower list.
        self.allowed_program_ids = configured_allowlist or None
        self.max_fee_lamports = int(
            max_fee_lamports
            if max_fee_lamports is not None
            else getattr(settings, "SOLANA_SPONSOR_MAX_FEE_LAMPORTS", 100_000)
        )
        self.min_sponsor_balance_lamports = int(
            min_sponsor_balance_lamports
            if min_sponsor_balance_lamports is not None
            else getattr(settings, "SOLANA_SPONSOR_MIN_BALANCE_LAMPORTS", 0)
        )

    def _rpc(self, method: str, params: list):
        if self._rpc_override:
            return self._rpc_override(method, params)
        if not self.rpc_url:
            raise SolanaSponsorPolicyError("rpc_not_configured")
        response = requests.post(
            self.rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise SolanaSponsorPolicyError("rpc_error")
        return payload.get("result")

    def prepare(self) -> dict:
        """Return the values a client must bind into the signed message."""
        latest = self._rpc(
            "getLatestBlockhash", [{"commitment": DEFAULT_COMMITMENT}]
        )
        value = (latest or {}).get("value") or {}
        if not value.get("blockhash") or value.get("lastValidBlockHeight") is None:
            raise SolanaSponsorPolicyError("blockhash_unavailable")
        return {
            "sponsorAddress": self.signer.address,
            "blockhash": value["blockhash"],
            "lastValidBlockHeight": int(value["lastValidBlockHeight"]),
            "maxFeeLamports": self.max_fee_lamports,
        }

    @staticmethod
    def _decode_transaction(transaction_base64: str) -> tuple[bytes, VersionedTransaction]:
        if not isinstance(transaction_base64, str):
            raise SolanaSponsorPolicyError("bad_transaction_encoding")
        # 1232 wire bytes encode to at most 1644 base64 characters. Reject
        # before decoding so a small GraphQL request cannot force a large
        # allocation merely to discover that it exceeds Solana's wire limit.
        max_encoded = ((MAX_WIRE_TRANSACTION_BYTES + 2) // 3) * 4
        if not transaction_base64 or len(transaction_base64) > max_encoded:
            raise SolanaSponsorPolicyError("bad_transaction_size")
        try:
            raw = base64.b64decode(transaction_base64, validate=True)
        except (TypeError, ValueError):
            raise SolanaSponsorPolicyError("bad_transaction_encoding") from None
        if not raw or len(raw) > MAX_WIRE_TRANSACTION_BYTES:
            raise SolanaSponsorPolicyError("bad_transaction_size")
        try:
            return raw, VersionedTransaction.from_bytes(raw)
        except Exception:
            raise SolanaSponsorPolicyError("bad_transaction") from None

    def validate_transaction(
        self,
        transaction_base64: str,
        *,
        expected_user_signer: str,
        policy_hook: Optional[PolicyHook] = None,
        allow_sponsor_account_reference: bool = False,
    ) -> ValidatedSponsoredTransaction:
        """Validate a user-partially-signed transaction without mutating it."""
        if allow_sponsor_account_reference and policy_hook is None:
            # A sponsor-aware instruction receives the fee payer's signer and
            # writable privileges. Only an exact, flow-specific validator may
            # opt into that larger trust boundary.
            raise SolanaSponsorPolicyError("sponsor_policy_required")
        _, tx = self._decode_transaction(transaction_base64)
        try:
            # VersionedTransaction.sanitize covers both legacy and v0 message
            # headers. Legacy Message does not expose sanitize(), so checking
            # only the message leaves malformed header counts admissible.
            tx.sanitize()
        except Exception:
            raise SolanaSponsorPolicyError("bad_transaction") from None
        message = tx.message
        # MessageV0 exposes the Rust sanitizer directly; legacy Message does
        # not.  from_bytes already rejects malformed legacy wire data and the
        # explicit signer/program/account bounds below cover what we consume.
        if hasattr(message, "sanitize"):
            message.sanitize()
        account_keys = tuple(message.account_keys)
        required = int(message.header.num_required_signatures)
        if required < 2 or required > len(account_keys):
            raise SolanaSponsorPolicyError("bad_signer_count")
        if len(tx.signatures) != required:
            raise SolanaSponsorPolicyError("bad_signature_count")
        if str(account_keys[0]) != self.signer.address:
            raise SolanaSponsorPolicyError("bad_fee_payer")
        if tx.signatures[0] != Signature.default():
            raise SolanaSponsorPolicyError("sponsor_slot_not_empty")

        # Address lookup tables make program and account policy dependent on
        # mutable external state.  Start fail-closed; support can be added by
        # resolving and pinning every table at validation time.
        if getattr(message, "address_table_lookups", ()):
            raise SolanaSponsorPolicyError("address_tables_not_supported")

        message_bytes = to_bytes_versioned(message)
        user_signers = []
        for index in range(1, required):
            signature = tx.signatures[index]
            signer_key = account_keys[index]
            if signature == Signature.default() or not signature.verify(
                signer_key, message_bytes
            ):
                raise SolanaSponsorPolicyError("bad_user_signature")
            user_signers.append(str(signer_key))
        if expected_user_signer not in user_signers:
            raise SolanaSponsorPolicyError("wrong_user_signer")

        program_ids = []
        for instruction in message.instructions:
            program_index = int(instruction.program_id_index)
            if program_index >= len(account_keys):
                raise SolanaSponsorPolicyError("bad_program_index")
            program_id = str(account_keys[program_index])
            program_ids.append(program_id)
            if (
                self.allowed_program_ids is not None
                and program_id not in self.allowed_program_ids
            ):
                raise SolanaSponsorPolicyError("program_not_allowed")
            instruction_accounts = bytes(instruction.accounts)
            if any(index >= len(account_keys) for index in instruction_accounts):
                raise SolanaSponsorPolicyError("bad_account_index")
            sponsor_referenced = any(
                account_keys[index] == account_keys[0]
                for index in instruction_accounts
            )
            if sponsor_referenced and not allow_sponsor_account_reference:
                raise SolanaSponsorPolicyError("sponsor_account_referenced")

        validated = ValidatedSponsoredTransaction(
            transaction=tx,
            message_bytes=message_bytes,
            program_ids=tuple(program_ids),
            user_signers=tuple(user_signers),
            expected_user_signer=expected_user_signer,
        )
        if policy_hook:
            policy_hook(validated)
        return validated

    def sponsor_and_send(
        self,
        transaction_base64: str,
        *,
        expected_user_signer: str,
        policy_hook: Optional[PolicyHook] = None,
        allow_sponsor_account_reference: bool = False,
        fee_authorizer: Optional[FeeAuthorizer] = None,
        transaction_lookup: Optional[TransactionLookup] = None,
        signature_recorder: Optional[SignatureRecorder] = None,
    ) -> dict:
        """Validate and relay a transaction; return its RPC signature."""
        if fee_authorizer is None:
            raise SolanaSponsorPolicyError("fee_authorization_required")
        validated = self.validate_transaction(
            transaction_base64,
            expected_user_signer=expected_user_signer,
            policy_hook=policy_hook,
            allow_sponsor_account_reference=allow_sponsor_account_reference,
        )
        existing = transaction_lookup(validated) if transaction_lookup else None
        if existing and existing.get("signature"):
            if existing.get("status") in ("sent", "confirmed"):
                return {
                    "success": True,
                    "signature": existing["signature"],
                    "feeLamports": int(existing["fee_lamports"]),
                }
            status_result = self._rpc(
                "getSignatureStatuses",
                [[existing["signature"]], {"searchTransactionHistory": True}],
            )
            statuses = (status_result or {}).get("value") or []
            status = statuses[0] if statuses else None
            if status and status.get("err") is None:
                return {
                    "success": True,
                    "signature": existing["signature"],
                    "feeLamports": int(existing["fee_lamports"]),
                }
        message = validated.transaction.message
        blockhash_valid = self._rpc(
            "isBlockhashValid",
            [str(message.recent_blockhash), {"commitment": DEFAULT_COMMITMENT}],
        )
        if not (blockhash_valid or {}).get("value"):
            raise SolanaSponsorPolicyError("blockhash_expired")

        message_b64 = base64.b64encode(validated.message_bytes).decode("ascii")
        fee = self._rpc(
            "getFeeForMessage",
            [message_b64, {"commitment": DEFAULT_COMMITMENT}],
        )
        fee_lamports = (fee or {}).get("value")
        if fee_lamports is None:
            raise SolanaSponsorPolicyError("fee_unavailable")
        fee_lamports = int(fee_lamports)
        if fee_lamports <= 0:
            raise SolanaSponsorPolicyError("invalid_fee")
        if fee_lamports > self.max_fee_lamports:
            raise SolanaSponsorPolicyError("fee_too_high")

        balance = self._rpc(
            "getBalance",
            [self.signer.address, {"commitment": DEFAULT_COMMITMENT}],
        )
        balance_lamports = (balance or {}).get("value")
        balance_slot = ((balance or {}).get("context") or {}).get("slot")
        if balance_lamports is None or balance_slot is None:
            raise SolanaSponsorPolicyError("sponsor_balance_unavailable")
        if (
            int(balance_lamports) - int(fee_lamports)
            < self.min_sponsor_balance_lamports
        ):
            raise SolanaSponsorPolicyError("sponsor_balance_low")

        # Commit the durable fee/balance reservation before producing a KMS
        # signature. simulateTransaction sends a fully broadcastable wire
        # transaction to an external RPC, so authorization after signing is a
        # real budget bypass rather than merely an efficiency concern.
        fee_authorizer(
            int(fee_lamports), int(balance_lamports), int(balance_slot), validated
        )

        signatures = list(validated.transaction.signatures)
        signatures[0] = Signature.from_bytes(
            self.signer.sign_message(validated.message_bytes)
        )
        signed_tx = VersionedTransaction.populate(message, signatures)
        if not all(signed_tx.verify_with_results()):
            raise SolanaSponsorPolicyError("signature_verification_failed")
        tx_signature_string = str(signatures[0])
        if signature_recorder:
            signature_recorder(tx_signature_string, validated)
        signed_b64 = base64.b64encode(bytes(signed_tx)).decode("ascii")

        simulation = self._rpc(
            "simulateTransaction",
            [
                signed_b64,
                {
                    "encoding": "base64",
                    "sigVerify": True,
                    "replaceRecentBlockhash": False,
                    "commitment": DEFAULT_COMMITMENT,
                },
            ],
        )
        simulation_value = (simulation or {}).get("value") or {}
        if simulation_value.get("err") is not None:
            raise SolanaSponsorPolicyError("simulation_failed")

        tx_signature = self._rpc(
            "sendTransaction",
            [
                signed_b64,
                {
                    "encoding": "base64",
                    "skipPreflight": False,
                    "preflightCommitment": DEFAULT_COMMITMENT,
                    "maxRetries": 3,
                },
            ],
        )
        if not tx_signature:
            raise SolanaSponsorPolicyError("broadcast_failed")
        if str(tx_signature) != tx_signature_string:
            raise SolanaSponsorPolicyError("broadcast_signature_mismatch")
        logger.info(
            "Sponsored Solana transaction %s for signer %s (%s lamports)",
            tx_signature,
            expected_user_signer,
            fee_lamports,
        )
        return {
            "success": True,
            "signature": tx_signature_string,
            "feeLamports": fee_lamports,
        }
