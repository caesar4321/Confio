"""
P2P Trade Transaction Builder (Algorand)

Builds fully server-sponsored transaction groups for P2P trade flows
against the contracts/p2p_trade Beaker app. The server constructs the
entire group; the client signs only their own transaction(s) and returns
them for submission. Patterns mirror Invite/Payment builders.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Dict, List, Optional

from django.conf import settings
from algosdk.v2client import algod
from algosdk import encoding as algo_encoding
from algosdk import transaction
from algosdk.logic import get_application_address
from algosdk.abi import Contract
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer,
    TransactionWithSigner,
    AccountTransactionSigner,
    TransactionSigner,
)


def _abi_contract() -> Contract:
    from pathlib import Path
    path = Path('contracts/p2p_trade/contract.json')
    return Contract.from_json(path.read_text())


class _NoopSigner(TransactionSigner):
    def sign_transactions(self, txns: List[transaction.Transaction]) -> List[bytes]:
        raise RuntimeError("Noop signer should not be used for signing")


@dataclass
class BuildResult:
    success: bool
    error: Optional[str] = None
    transactions_to_sign: Optional[List[Dict]] = None
    sponsor_transactions: Optional[List[Dict]] = None
    group_id: Optional[str] = None
    trade_id: Optional[str] = None
    asset_id: Optional[int] = None
    amount: Optional[int] = None


class P2PTradeTransactionBuilder:
    """Builds sponsored transaction groups for P2P trade operations."""

    def __init__(self):
        # Algod client
        self.algod_address = settings.ALGORAND_ALGOD_ADDRESS
        self.algod_token = settings.ALGORAND_ALGOD_TOKEN
        self.algod_client = algod.AlgodClient(self.algod_token, self.algod_address)

        # Contract/App
        self.app_id = getattr(settings, 'ALGORAND_P2P_TRADE_APP_ID', 0)
        if not self.app_id:
            raise ValueError('ALGORAND_P2P_TRADE_APP_ID missing or 0 in settings')
        self.app_address = get_application_address(self.app_id)

        # Assets and sponsor
        self.cusd_asset_id = int(settings.ALGORAND_CUSD_ASSET_ID)
        self.confio_asset_id = int(getattr(settings, 'ALGORAND_CONFIO_ASSET_ID', 0))
        self.sponsor_address = settings.ALGORAND_SPONSOR_ADDRESS
        self.sponsor_mnemonic = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)

        # ABI
        self.contract = _abi_contract()

    @staticmethod
    def _trade_box_mbr(key_len: int) -> int:
        # TRADE_VALUE_FIXED_LEN = 137; MBR = 2500 + 400 * (key_len + 137)
        return 2500 + 400 * (key_len + 137)

    @staticmethod
    def _paid_box_mbr(key_len: int) -> int:
        # PAID_VALUE_LEN = 41; MBR = 2500 + 400 * (key_len + 41)
        return 2500 + 400 * (key_len + 41)

    def _asset_id_for_type(self, token: str) -> int:
        t = (token or 'CUSD').upper()
        if t == 'CUSD':
            return self.cusd_asset_id
        if t == 'CONFIO':
            return self.confio_asset_id
        raise ValueError('Unsupported asset type')

    def _method(self, name: str):
        return next((m for m in self.contract.methods if m.name == name), None)

    def build_create_trade(
        self,
        seller_address: str,
        token: str,
        amount: int,
        trade_id: str,
    ) -> BuildResult:
        try:
            asset_id = self._asset_id_for_type(token)

            # Preflight: app must be opted into asset and seller must be opted-in too
            try:
                self.algod_client.account_asset_info(self.app_address, asset_id)
            except Exception:
                return BuildResult(False, error=f'P2P app not opted into asset {asset_id}')
            try:
                self.algod_client.account_asset_info(seller_address, asset_id)
            except Exception:
                return BuildResult(False, error=f'Seller not opted into asset {asset_id}')

            # Calculate MBR for trade_id box
            key_len = len(trade_id.encode())
            if key_len == 0 or key_len > 56:
                return BuildResult(False, error='trade_id must be 1..56 bytes')
            mbr = self._trade_box_mbr(key_len)

            params = self.algod_client.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000

            atc = AtomicTransactionComposer()

            # Tx 0: Sponsor fee-bump (0 ALGO) to app (covers group fees via fee pooling)
            sp0 = transaction.SuggestedParams(fee=min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            pay0 = transaction.PaymentTxn(sender=self.sponsor_address, sp=sp0, receiver=self.app_address, amt=0, note=b'P2P sponsor')
            atc.add_transaction(TransactionWithSigner(pay0, AccountTransactionSigner('0'*64)))

            # Tx 1: Sponsor MBR payment for trade box
            sp1 = transaction.SuggestedParams(fee=min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            pay1 = transaction.PaymentTxn(sender=self.sponsor_address, sp=sp1, receiver=self.app_address, amt=mbr, note=b'P2P trade MBR')
            atc.add_transaction(TransactionWithSigner(pay1, AccountTransactionSigner('0'*64)))

            # Tx 2: AXFER from seller to app (fee=0)
            sp2 = transaction.SuggestedParams(fee=0, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            axfer = transaction.AssetTransferTxn(sender=seller_address, sp=sp2, receiver=self.app_address, amt=amount, index=asset_id)

            # Tx 3: App call by sponsor with ABI (create_trade)
            method = self._method('create_trade')
            if method is None:
                return BuildResult(False, error='ABI method create_trade not found')
            sp3 = transaction.SuggestedParams(fee=2*min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            # Add method call with seller in accounts to mark actual_seller
            atc.add_method_call(
                app_id=self.app_id,
                method=method,
                sender=self.sponsor_address,
                sp=sp3,
                signer=AccountTransactionSigner('0'*64),
                method_args=[trade_id, TransactionWithSigner(axfer, _NoopSigner())],
                accounts=[seller_address],
                foreign_assets=[asset_id],
                boxes=[(0, trade_id.encode())],
            )

            # Build group
            tws = atc.build_group()
            gid = transaction.calculate_group_id([t.txn for t in tws])

            sponsor_txs: List[Dict] = []
            user_txs: List[Dict] = []
            # Identify the AXFER by type and sender, do not rely on fixed index
            axfer_index = None
            for idx, tw in enumerate(tws):
                tx = tw.txn
                if isinstance(tx, transaction.AssetTransferTxn) and tx.sender == seller_address:
                    axfer_index = idx
                    break
            if axfer_index is None:
                return BuildResult(False, error='AXFER transaction not found in group')

            for idx, tw in enumerate(tws):
                tx = tw.txn
                b64 = algo_encoding.msgpack_encode(tx)
                entry = {'txn': b64, 'signed': None, 'index': idx}
                if idx == axfer_index:
                    user_txs.append({'txn': b64, 'signers': [seller_address], 'message': 'Deposit assets to P2P escrow'})
                else:
                    sponsor_txs.append(entry)

            return BuildResult(
                success=True,
                transactions_to_sign=user_txs,
                sponsor_transactions=sponsor_txs,
                group_id=base64.b64encode(gid).decode(),
                trade_id=trade_id,
                asset_id=asset_id,
                amount=amount,
            )
        except Exception as e:
            return BuildResult(False, error=str(e))

    def build_accept_trade(
        self,
        buyer_address: str,
        trade_id: str,
    ) -> BuildResult:
        """Build sponsor-only accept_trade group: [AppCall] or [Pay, AppCall].
        Only the sponsor signs; client signs nothing.
        """
        try:
            params = self.algod_client.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000
            atc = AtomicTransactionComposer()

            # Optional fee-bump payment (0 ALGO) just to robustly cover fee pooling across SDKs
            sp0 = transaction.SuggestedParams(fee=min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            pay0 = transaction.PaymentTxn(sender=self.sponsor_address, sp=sp0, receiver=self.app_address, amt=0, note=b'P2P accept')
            atc.add_transaction(TransactionWithSigner(pay0, AccountTransactionSigner('0'*64)))

            method = self._method('accept_trade')
            if method is None:
                return BuildResult(False, error='ABI method accept_trade not found')
            sp1 = transaction.SuggestedParams(fee=min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            atc.add_method_call(
                app_id=self.app_id,
                method=method,
                sender=self.sponsor_address,
                sp=sp1,
                signer=AccountTransactionSigner('0'*64),
                method_args=[trade_id],
                accounts=[buyer_address],  # actual_buyer inferred on-chain
                boxes=[(0, trade_id.encode())],
            )

            tws = atc.build_group()
            gid = transaction.calculate_group_id([t.txn for t in tws])
            sponsor_txs = [{'txn': algo_encoding.msgpack_encode(t.txn), 'signed': None, 'index': i} for i, t in enumerate(tws)]
            return BuildResult(True, transactions_to_sign=[], sponsor_transactions=sponsor_txs, group_id=base64.b64encode(gid).decode(), trade_id=trade_id)
        except Exception as e:
            return BuildResult(False, error=str(e))

    def build_mark_paid(
        self,
        buyer_address: str,
        trade_id: str,
        payment_ref: str,
    ) -> BuildResult:
        """Build [Payment(sponsor→app, MBR), AppCall(buyer)] with user-signed AppCall."""
        try:
            key = (trade_id + "_paid").encode()
            if len(key) > 64:
                return BuildResult(False, error='trade_id too long for _paid box key')
            mbr = self._paid_box_mbr(len(key))
            params = self.algod_client.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000

            atc = AtomicTransactionComposer()
            sp0 = transaction.SuggestedParams(fee=min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            pay = transaction.PaymentTxn(sender=self.sponsor_address, sp=sp0, receiver=self.app_address, amt=mbr, note=b'P2P paid MBR')
            atc.add_transaction(TransactionWithSigner(pay, AccountTransactionSigner('0'*64)))

            method = self._method('mark_as_paid')
            if method is None:
                return BuildResult(False, error='ABI method mark_as_paid not found')
            sp1 = transaction.SuggestedParams(fee=0, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            atc.add_method_call(
                app_id=self.app_id,
                method=method,
                sender=buyer_address,
                sp=sp1,
                signer=AccountTransactionSigner('0'*64),  # placeholder; user signs
                method_args=[trade_id, payment_ref],
                boxes=[(0, trade_id.encode()), (0, (trade_id + "_paid").encode())],
            )

            tws = atc.build_group()
            gid = transaction.calculate_group_id([t.txn for t in tws])
            sponsor_txs = [{'txn': algo_encoding.msgpack_encode(t.txn), 'signed': None, 'index': i} for i, t in enumerate(tws) if i == 0]
            user_txs = [{'txn': algo_encoding.msgpack_encode(tws[1].txn), 'signers': [buyer_address], 'message': 'Mark P2P trade as paid'}]
            return BuildResult(True, transactions_to_sign=user_txs, sponsor_transactions=sponsor_txs, group_id=base64.b64encode(gid).decode(), trade_id=trade_id)
        except Exception as e:
            return BuildResult(False, error=str(e))

    def build_confirm_received(
        self,
        seller_address: str,
        trade_id: str,
    ) -> BuildResult:
        """Build [Payment(sponsor fee-bump), AppCall(seller)] with user-signed AppCall."""
        try:
            params = self.algod_client.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000

            atc = AtomicTransactionComposer()
            # Fee bump needs 3000 per contract
            sp0 = transaction.SuggestedParams(fee=3*min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            pay = transaction.PaymentTxn(sender=self.sponsor_address, sp=sp0, receiver=self.app_address, amt=0, note=b'P2P confirm')
            atc.add_transaction(TransactionWithSigner(pay, AccountTransactionSigner('0'*64)))

            method = self._method('confirm_payment_received')
            if method is None:
                return BuildResult(False, error='ABI method confirm_payment_received not found')
            sp1 = transaction.SuggestedParams(fee=0, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            atc.add_method_call(
                app_id=self.app_id,
                method=method,
                sender=seller_address,
                sp=sp1,
                signer=AccountTransactionSigner('0'*64),  # placeholder; user signs
                method_args=[trade_id],
                boxes=[(0, trade_id.encode())],
            )

            tws = atc.build_group()
            gid = transaction.calculate_group_id([t.txn for t in tws])
            sponsor_txs = [{'txn': algo_encoding.msgpack_encode(tws[0].txn), 'signed': None, 'index': 0}]
            user_txs = [{'txn': algo_encoding.msgpack_encode(tws[1].txn), 'signers': [seller_address], 'message': 'Confirm payment received'}]
            return BuildResult(True, transactions_to_sign=user_txs, sponsor_transactions=sponsor_txs, group_id=base64.b64encode(gid).decode(), trade_id=trade_id)
        except Exception as e:
            return BuildResult(False, error=str(e))
