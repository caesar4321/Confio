"""
Invite & Send Transaction Builder

Builds fully sponsored transaction groups for creating invitations that escrow
ASA in the InviteSend application. Server constructs deterministic groups;
client only signs the asset transfer; server signs and submits the rest.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from django.conf import settings
from algosdk.v2client import algod
from algosdk import encoding
from algosdk import transaction
from algosdk.logic import get_application_address
from algosdk.abi import Contract
import msgpack
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer,
    TransactionWithSigner,
    AccountTransactionSigner,
    TransactionSigner,
)
from users.country_codes import COUNTRY_CODES
from users.phone_utils import (
    normalize_phone as _normalize_phone,
    normalize_any_phone as _normalize_any_phone,
)


def _abi_contract() -> Contract:
    from pathlib import Path
    path = Path('contracts/invite_send/contract.json')
    return Contract.from_json(path.read_text())


class _NoopSigner(TransactionSigner):
    def sign_transactions(self, txns: List[transaction.Transaction]) -> List[bytes]:
        raise RuntimeError("Noop signer should not be used for signing")


@dataclass
class InviteBuildResult:
    success: bool
    error: Optional[str] = None
    transactions_to_sign: Optional[List[Dict]] = None
    sponsor_transactions: Optional[List[Dict]] = None
    group_id: Optional[str] = None
    invitation_id: Optional[str] = None
    asset_id: Optional[int] = None
    amount: Optional[int] = None


class InviteSendTransactionBuilder:
    """Builds sponsored invite transactions for the InviteSend app."""

    def __init__(self):
        # Config from Django settings/.env
        self.algod_address = settings.ALGORAND_ALGOD_ADDRESS
        self.algod_token = settings.ALGORAND_ALGOD_TOKEN
        self.algod_client = algod.AlgodClient(self.algod_token, self.algod_address)

        self.app_id = getattr(settings, 'ALGORAND_INVITE_SEND_APP_ID', 0)
        if not self.app_id:
            raise ValueError('ALGORAND_INVITE_SEND_APP_ID missing or 0 in settings')

        self.cusd_asset_id = settings.ALGORAND_CUSD_ASSET_ID
        self.confio_asset_id = settings.ALGORAND_CONFIO_ASSET_ID
        self.sponsor_address = settings.ALGORAND_SPONSOR_ADDRESS
        self.sponsor_mnemonic = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)

        self.app_address = get_application_address(self.app_id)

        # Load ABI for selector and arg typing
        self.contract = _abi_contract()

    @staticmethod
    def normalize_phone(phone_number: str, country: Optional[str]) -> str:
        """Strict canonical phone key: "cc:digits" only.

        Rules:
        - If `country` is provided (ISO alpha-2 or calling code), use it to produce
          "cc:digits" via `_normalize_phone`.
        - Else, if `phone_number` is in E.164 form (starts with '+') and contains a
          valid calling code, derive "cc:digits" via `normalize_any_phone`.
        - Otherwise, return an empty string to signal inability to canonicalize.
        """
        # Attempt ISO/calling-code driven normalization first
        key = _normalize_phone(phone_number, country)
        if key and ':' in key:
            return key
        # Next, allow E.164 parsing from the phone string itself
        if (phone_number or '').strip().startswith('+'):
            try:
                alt = _normalize_any_phone(phone_number)
                if alt and ':' in alt:
                    return alt
            except Exception:
                pass
        # Could not canonicalize to cc:digits
        return ''

    @staticmethod
    def make_invitation_id(phone_key: str) -> str:
        h = hashlib.sha256(phone_key.encode()).hexdigest()
        return f"ph:{h[:56]}"  # keep under 64 bytes total

    @staticmethod
    def _box_mbr_cost(key_len: int, msg_len: int) -> int:
        # value_len = sender(32) + amount(8) + asset_id(8) + created_at(8) + expires_at(8)
        #           + is_claimed(1) + is_reclaimed(1) + msg_len(2) + message
        value_len = 32 + 8 + 8 + 8 + 8 + 1 + 1 + 2 + msg_len
        return 2500 + 400 * (key_len + value_len)

    def preflight(self, inviter: str, asset_id: int) -> Tuple[bool, str]:
        # App must be opted-in to asset
        try:
            self.algod_client.account_asset_info(self.app_address, asset_id)
        except Exception:
            return False, f"Invite app not opted-in to asset {asset_id}. Run setup_assets."
        # Inviter must be opted into asset to send AXFER
        try:
            self.algod_client.account_asset_info(inviter, asset_id)
        except Exception:
            return False, f"Inviter is not opted into asset {asset_id}."
        return True, ''

    def build_create_invitation(
        self,
        inviter_address: str,
        asset_id: int,
        amount: int,
        phone_number: str,
        phone_country: Optional[str] = None,
        message: Optional[str] = '',
        invitation_id_override: Optional[str] = None,
    ) -> InviteBuildResult:
        try:
            if asset_id not in (self.cusd_asset_id, self.confio_asset_id):
                return InviteBuildResult(False, error='Unsupported asset for invite')

            ok, err = self.preflight(inviter_address, asset_id)
            if not ok:
                return InviteBuildResult(False, error=err)

            phone_key = self.normalize_phone(phone_number, phone_country)
            invitation_id = invitation_id_override or self.make_invitation_id(phone_key)
            msg = (message or '')[:256]
            mbr = self._box_mbr_cost(len(invitation_id.encode()), len(msg.encode()))

            params = self.algod_client.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000

            # Compose group with ATC to satisfy axfer ABI arg
            atc = AtomicTransactionComposer()

            # Txn 0: sponsor pay (0) to inviter for fee-bump; pays own fee and covers AXFER's min fee
            sp0 = transaction.SuggestedParams(
                fee=min_fee * 2,
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True,
            )
            # Pay0: sponsor fee-bump (0 ALGO) paid to app (satisfies current on-chain assert)
            pay0 = transaction.PaymentTxn(
                sender=self.sponsor_address,
                sp=sp0,
                receiver=self.app_address,
                amt=0,
                note=b"Invite sponsor"
            )
            atc.add_transaction(TransactionWithSigner(pay0, AccountTransactionSigner('0'*64)))

            # Txn 1: sponsor MBR payment to app (exact mbr or more)
            sp1 = transaction.SuggestedParams(
                fee=min_fee,
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True,
            )
            pay1 = transaction.PaymentTxn(
                sender=self.sponsor_address,
                sp=sp1,
                receiver=self.app_address,
                amt=mbr,
                note=b"Invite MBR"
            )
            atc.add_transaction(TransactionWithSigner(pay1, AccountTransactionSigner('0'*64)))

            # AXFER from inviter → app; fee=0 sponsored
            sp2 = transaction.SuggestedParams(
                fee=0,
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True,
            )
            axfer = transaction.AssetTransferTxn(
                sender=inviter_address,
                sp=sp2,
                receiver=self.app_address,
                amt=amount,
                index=asset_id,
            )
            # Do NOT add to composer list; pass as method arg instead

            # AppCall by sponsor at the end
            method = next((m for m in self.contract.methods if m.name == 'create_invitation'), None)
            if method is None:
                return InviteBuildResult(False, error='ABI method create_invitation not found')

            # App call fee only covers itself; refunds handled in app
            sp3 = transaction.SuggestedParams(
                fee=min_fee,
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True,
            )

            atc.add_method_call(
                app_id=self.app_id,
                method=method,
                sender=self.sponsor_address,
                sp=sp3,
                signer=AccountTransactionSigner('0'*64),  # placeholder, server signs on submit
                method_args=[invitation_id, TransactionWithSigner(axfer, _NoopSigner()), msg],
                accounts=[inviter_address],
                foreign_assets=[asset_id],
                # Use app index 0 to reference boxes on the current application
                boxes=[(0, invitation_id.encode())],
            )

            # Build to assign group ids
            tws_list = atc.build_group()

            # Order is [pay0, pay1, axfer, appcall]
            gid = transaction.calculate_group_id([t.txn for t in tws_list])

            # Encode txns for client/server signing responsibilities
            sponsor_txs = []
            user_txs = []
            for idx, tws in enumerate(tws_list):
                tx = tws.txn
                # Always produce canonical msgpack bytes then base64-encode
                raw_bytes = msgpack.packb(tx.dictify(), use_bin_type=True)
                payload_b64 = base64.b64encode(raw_bytes).decode()
                entry = {
                    'txn': payload_b64,
                    'index': idx
                }
                if isinstance(tx, transaction.AssetTransferTxn):
                    user_txs.append({
                        'txn': payload_b64,
                        'signers': [inviter_address],
                        'message': f'Escrow {amount} units for invite to phone',
                        'index': idx
                    })
                else:
                    sponsor_txs.append(entry)

            return InviteBuildResult(
                True,
                transactions_to_sign=user_txs,
                sponsor_transactions=sponsor_txs,
                group_id=base64.b64encode(gid).decode(),
                invitation_id=invitation_id,
                asset_id=asset_id,
                amount=amount,
            )

        except Exception as e:
            return InviteBuildResult(False, error=str(e))
