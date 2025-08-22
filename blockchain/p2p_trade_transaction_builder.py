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
import logging
from typing import Dict, List, Optional

from django.conf import settings
from algosdk.v2client import algod
from algosdk import encoding as algo_encoding
from algosdk import transaction
from algosdk.logic import get_application_address
from algosdk import abi
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
        self.logger = logging.getLogger(__name__)
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

    @staticmethod
    def _dispute_box_mbr(key_len: int) -> int:
        # DISPUTE_VALUE_LEN = 104; MBR = 2500 + 400 * (key_len + 104)
        return 2500 + 400 * (key_len + 104)

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
                seller_asset = self.algod_client.account_asset_info(seller_address, asset_id)
                # Ensure seller is opted-in and has sufficient balance to escrow
                holding = (seller_asset or {}).get('asset-holding') or {}
                seller_balance = int(holding.get('amount', 0))
                self.logger.info('[P2P Builder] Seller asset check: addr=%s asset=%s balance=%s network=%s', seller_address, asset_id, seller_balance, getattr(settings, 'ALGORAND_NETWORK', 'unknown'))
                if seller_balance <= 0:
                    return BuildResult(False, error=f'Seller not opted into asset {asset_id} on {getattr(settings, "ALGORAND_NETWORK", "unknown")} (address {seller_address})')
                if seller_balance < amount:
                    # Convert to token units (assumes 6 decimals for cUSD/CONFIO)
                    need = amount / 1_000_000
                    have = seller_balance / 1_000_000
                    return BuildResult(False, error=f'Insufficient {token} balance: need {need:.6f}, have {have:.6f} on {getattr(settings, "ALGORAND_NETWORK", "unknown")} (address {seller_address})')
            except Exception as e:
                self.logger.info('[P2P Builder] Seller asset check failed: addr=%s asset=%s error=%r', seller_address, asset_id, e)
                return BuildResult(False, error=f'Unable to verify seller balance for asset {asset_id} on {getattr(settings, "ALGORAND_NETWORK", "unknown")} (address {seller_address})')

            # Calculate MBR for trade_id box
            key_len = len(trade_id.encode())
            if key_len == 0 or key_len > 56:
                return BuildResult(False, error='trade_id must be 1..56 bytes')
            mbr = self._trade_box_mbr(key_len)

            params = self.algod_client.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000

            # Build with ATC to correctly pass the AXFER txn as ABI arg
            atc = AtomicTransactionComposer()

            # Tx 0: Sponsor MBR payment for trade box (must be first, consumed as gtxn 0 in app logic)
            sp1 = transaction.SuggestedParams(fee=3*min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            pay1 = transaction.PaymentTxn(sender=self.sponsor_address, sp=sp1, receiver=self.app_address, amt=mbr, note=b'P2P trade MBR')
            atc.add_transaction(TransactionWithSigner(pay1, AccountTransactionSigner('0'*64)))

            # Tx 1: AXFER from seller to app (fee=0)
            sp2 = transaction.SuggestedParams(fee=0, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            axfer = transaction.AssetTransferTxn(sender=seller_address, sp=sp2, receiver=self.app_address, amt=amount, index=asset_id)

            # Tx 2: App call by SELLER with ABI (create_trade)
            method = self._method('create_trade')
            if method is None:
                return BuildResult(False, error='ABI method create_trade not found')
            # Set fee 0 here; sponsor payment covers total group fee budget
            sp3 = transaction.SuggestedParams(fee=0, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            atc.add_method_call(
                app_id=self.app_id,
                method=method,
                sender=seller_address,
                sp=sp3,
                # Placeholder signer; we will return the unsigned tx for client to sign
                signer=AccountTransactionSigner('0'*64),
                method_args=[trade_id, TransactionWithSigner(axfer, _NoopSigner())],
                accounts=[seller_address],
                foreign_assets=[asset_id],
                boxes=[(0, trade_id.encode())],
            )

            # Build group and ensure accounts are present on appcall
            tws = atc.build_group()
            try:
                ensured = False
                for tw in tws:
                    tx = tw.txn
                    if isinstance(tx, transaction.ApplicationCallTxn) and not getattr(tx, 'accounts', None):
                        tx.accounts = [seller_address]
                        ensured = True
                if ensured:
                    self.logger.info('[P2P Builder] Ensured seller address present in app-call accounts')
            except Exception:
                pass

            gid = transaction.calculate_group_id([t.txn for t in tws])

            sponsor_txs: List[Dict] = []
            user_txs: List[Dict] = []
            # Identify indices to mark user-signed
            axfer_index = None
            app_index = None
            for idx, tw in enumerate(tws):
                if isinstance(tw.txn, transaction.AssetTransferTxn) and tw.txn.sender == seller_address:
                    axfer_index = idx
                if isinstance(tw.txn, transaction.ApplicationCallTxn) and tw.txn.sender == seller_address:
                    app_index = idx
            if axfer_index is None:
                return BuildResult(False, error='AXFER transaction not found in group')
            if app_index is None:
                return BuildResult(False, error='AppCall transaction not found in group')

            for idx, tw in enumerate(tws):
                b64 = algo_encoding.msgpack_encode(tw.txn)
                if idx == axfer_index:
                    user_txs.append({'txn': b64, 'signers': [seller_address], 'message': 'Deposit assets to P2P escrow'})
                elif idx == app_index:
                    user_txs.append({'txn': b64, 'signers': [seller_address], 'message': 'Create trade (AppCall)'})
                else:
                    sponsor_txs.append({'txn': b64, 'signed': None, 'index': idx})

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
            # Group has 2 txns (sponsor pay + buyer app call). Use fee pooling by
            # setting sponsor fee to cover both min fees to avoid 1000<->2000 errors.
            sp0 = transaction.SuggestedParams(fee=2*min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            pay0 = transaction.PaymentTxn(sender=self.sponsor_address, sp=sp0, receiver=self.app_address, amt=0, note=b'P2P accept')
            atc.add_transaction(TransactionWithSigner(pay0, AccountTransactionSigner('0'*64)))

            method = self._method('accept_trade')
            if method is None:
                return BuildResult(False, error='ABI method accept_trade not found')
            sp1 = transaction.SuggestedParams(fee=min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            # Include both common assets to satisfy asset_holding_get availability in app logic
            foreign_assets = [a for a in [self.cusd_asset_id, self.confio_asset_id] if a]
            atc.add_method_call(
                app_id=self.app_id,
                method=method,
                sender=self.sponsor_address,
                sp=sp1,
                signer=AccountTransactionSigner('0'*64),
                method_args=[trade_id],
                accounts=[buyer_address],  # actual_buyer inferred on-chain
                foreign_assets=foreign_assets,
                boxes=[(0, trade_id.encode())],
            )

            tws = atc.build_group()
            gid = transaction.calculate_group_id([t.txn for t in tws])
            sponsor_txs = [{'txn': algo_encoding.msgpack_encode(t.txn), 'signed': None, 'index': i} for i, t in enumerate(tws)]
            return BuildResult(True, transactions_to_sign=[], sponsor_transactions=sponsor_txs, group_id=base64.b64encode(gid).decode(), trade_id=trade_id)
        except Exception as e:
            return BuildResult(False, error=str(e))

    def build_accept_trade_user(
        self,
        buyer_address: str,
        trade_id: str,
    ) -> BuildResult:
        """Build [Payment(sponsor fee-bump), AppCall(buyer)] so buyer is txn.Sender.

        This guarantees buyer is written correctly even if the approval uses txn.Sender.
        """
        try:
            params = self.algod_client.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000

            atc = AtomicTransactionComposer()
            # Fee bump
            sp0 = transaction.SuggestedParams(fee=2*min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            pay = transaction.PaymentTxn(sender=self.sponsor_address, sp=sp0, receiver=self.app_address, amt=0, note=b'P2P accept user')
            atc.add_transaction(TransactionWithSigner(pay, AccountTransactionSigner('0'*64)))

            method = self._method('accept_trade')
            if method is None:
                return BuildResult(False, error='ABI method accept_trade not found')
            sp1 = transaction.SuggestedParams(fee=min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            # Include both common assets to satisfy asset_holding_get availability in app logic
            foreign_assets = [a for a in [self.cusd_asset_id, self.confio_asset_id] if a]
            atc.add_method_call(
                app_id=self.app_id,
                method=method,
                sender=buyer_address,
                sp=sp1,
                signer=AccountTransactionSigner('0'*64),
                method_args=[trade_id],
                boxes=[(0, trade_id.encode())],
                foreign_assets=foreign_assets,
            )

            tws = atc.build_group()
            gid = transaction.calculate_group_id([t.txn for t in tws])
            sponsor_txs = [{'txn': algo_encoding.msgpack_encode(tws[0].txn), 'signed': None, 'index': 0}]
            user_txs = [{'txn': algo_encoding.msgpack_encode(tws[1].txn), 'signers': [buyer_address], 'message': 'Accept trade'}]
            return BuildResult(True, transactions_to_sign=user_txs, sponsor_transactions=sponsor_txs, group_id=base64.b64encode(gid).decode(), trade_id=trade_id)
        except Exception as e:
            return BuildResult(False, error=str(e))

    def build_mark_paid(
        self,
        buyer_address: str,
        trade_id: str,
        payment_ref: str,
    ) -> BuildResult:
        """Build [Payment(sponsor→app, MBR), AppCall(buyer)]. Buyer signs only AppCall.

        Requires contract to accept sponsor as payer for the MBR/fee payment.
        """
        try:
            key = (trade_id + "_paid").encode()
            if len(key) > 64:
                return BuildResult(False, error='trade_id too long for _paid box key')
            mbr = self._paid_box_mbr(len(key))
            params = self.algod_client.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000

            atc = AtomicTransactionComposer()
            # Group has 2 txns (sponsor MBR pay + buyer app call). Pool fees on sponsor.
            sp0 = transaction.SuggestedParams(fee=2*min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
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

            # Debug: log key params for troubleshooting
            try:
                self.logger.info('[P2P Builder] mark_paid: app_id=%s sponsor=%s buyer=%s mbr=%s fee_each=%s', self.app_id, (self.sponsor_address or '')[:10], (buyer_address or '')[:10], mbr, min_fee)
            except Exception:
                pass

            tws = atc.build_group()
            gid = transaction.calculate_group_id([t.txn for t in tws])
            sponsor_txs = [{'txn': algo_encoding.msgpack_encode(tws[0].txn), 'signed': None, 'index': 0}]
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
            # Derive buyer address from on-chain box so we can include it in AppCall accounts
            buyer_addr: Optional[str] = None
            try:
                bx = self.algod_client.application_box_by_name(self.app_id, trade_id.encode('utf-8'))
                import base64 as _b64
                raw = _b64.b64decode((bx or {}).get('value', ''))
                buyer_b = raw[73:105] if len(raw) >= 105 else b''
                if len(buyer_b) == 32:
                    buyer_addr = algo_encoding.encode_address(buyer_b)
            except Exception:
                buyer_addr = None

            params = self.algod_client.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000

            atc = AtomicTransactionComposer()
            # Fee bump must cover inner itxns (asset transfer + up to 2 MBR refunds)
            # Pool a generous budget to avoid 'fee too small' during itxn_submit
            sp0 = transaction.SuggestedParams(fee=6*min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            pay = transaction.PaymentTxn(sender=self.sponsor_address, sp=sp0, receiver=self.app_address, amt=0, note=b'P2P confirm')
            atc.add_transaction(TransactionWithSigner(pay, AccountTransactionSigner('0'*64)))

            method = self._method('confirm_payment_received')
            if method is None:
                return BuildResult(False, error='ABI method confirm_payment_received not found')
            sp1 = transaction.SuggestedParams(fee=0, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            # Include assets for asset_holding_get checks inside approval
            foreign_assets = [a for a in [self.cusd_asset_id, self.confio_asset_id] if a]
            # Accounts: include sponsor (for MBR refunds/receivers) and buyer (for asset_holding_get)
            accounts: List[str] = []
            if self.sponsor_address:
                accounts.append(self.sponsor_address)
            if buyer_addr and buyer_addr not in accounts:
                accounts.append(buyer_addr)
            atc.add_method_call(
                app_id=self.app_id,
                method=method,
                sender=seller_address,
                sp=sp1,
                signer=AccountTransactionSigner('0'*64),  # placeholder; user signs
                method_args=[trade_id],
                boxes=[
                    (0, trade_id.encode()),
                    (0, (trade_id + "_paid").encode()),
                ],
                foreign_assets=foreign_assets,
                accounts=accounts,
            )

            tws = atc.build_group()
            gid = transaction.calculate_group_id([t.txn for t in tws])
            sponsor_txs = [{'txn': algo_encoding.msgpack_encode(tws[0].txn), 'signed': None, 'index': 0}]
            user_txs = [{'txn': algo_encoding.msgpack_encode(tws[1].txn), 'signers': [seller_address], 'message': 'Confirm payment received'}]
            return BuildResult(True, transactions_to_sign=user_txs, sponsor_transactions=sponsor_txs, group_id=base64.b64encode(gid).decode(), trade_id=trade_id)
        except Exception as e:
            return BuildResult(False, error=str(e))

    def build_cancel_trade(
        self,
        caller_address: str,
        trade_id: str,
    ) -> BuildResult:
        """Build cancellation group for expired trades.
        Pattern: optional sponsor fee-bump Payment + user AppCall(cancel_trade).
        Boxes: trade_id, trade_id+"_paid", trade_id+"_dispute" (the app tolerates missing boxes).
        """
        try:
            params = self.algod_client.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000

            atc = AtomicTransactionComposer()
            # Sponsor fee bump to cover inner tx fees during cancel cleanup.
            # Worst-case inner txns: 1 asset transfer + up to 2 MBR refund payments = 3.
            # Group (2 outers) + 3 inners => budget ~5 * min_fee pooled on sponsor.
            sp0 = transaction.SuggestedParams(fee=5*min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            pay = transaction.PaymentTxn(sender=self.sponsor_address, sp=sp0, receiver=self.app_address, amt=0, note=b'P2P cancel')
            atc.add_transaction(TransactionWithSigner(pay, AccountTransactionSigner('0'*64)))

            method = self._method('cancel_trade')
            if method is None:
                return BuildResult(False, error='ABI method cancel_trade not found')
            sp1 = transaction.SuggestedParams(fee=0, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            # Include both common assets to satisfy asset_holding_get availability in app logic
            foreign_assets = [a for a in [self.cusd_asset_id, self.confio_asset_id] if a]
            atc.add_method_call(
                app_id=self.app_id,
                method=method,
                sender=caller_address,
                sp=sp1,
                signer=AccountTransactionSigner('0'*64),  # placeholder; user signs
                method_args=[trade_id],
                boxes=[
                    (0, trade_id.encode()),
                    (0, (trade_id + "_paid").encode()),
                    (0, (trade_id + "_dispute").encode()),
                ],
                foreign_assets=foreign_assets,
                accounts=[self.sponsor_address],
            )

            tws = atc.build_group()
            gid = transaction.calculate_group_id([t.txn for t in tws])
            sponsor_txs = [{'txn': algo_encoding.msgpack_encode(tws[0].txn), 'signed': None, 'index': 0}]
            user_txs = [{'txn': algo_encoding.msgpack_encode(tws[1].txn), 'signers': [caller_address], 'message': 'Cancelar intercambio (expirado)'}]
            return BuildResult(True, transactions_to_sign=user_txs, sponsor_transactions=sponsor_txs, group_id=base64.b64encode(gid).decode(), trade_id=trade_id)
        except Exception as e:
            return BuildResult(False, error=str(e))

    def build_open_dispute(
        self,
        opener_address: str,
        trade_id: str,
        reason: str,
    ) -> BuildResult:
        """Build [Payment(sponsor→app, MBR), AppCall(opener)] to open dispute.

        Boxes required: trade_id, trade_id+"_dispute" (created if missing).
        """
        try:
            # Key for dispute box
            key = (trade_id + "_dispute").encode()
            if len(trade_id.encode()) == 0 or len(trade_id.encode()) > 56:
                return BuildResult(False, error='trade_id must be 1..56 bytes')
            if len(key) > 64:
                return BuildResult(False, error='trade_id too long for _dispute box key')
            mbr = self._dispute_box_mbr(len(key))

            params = self.algod_client.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000

            atc = AtomicTransactionComposer()
            # Pool minimal fees on sponsor; user AppCall uses fee=0
            sp0 = transaction.SuggestedParams(fee=2*min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            pay = transaction.PaymentTxn(sender=self.sponsor_address, sp=sp0, receiver=self.app_address, amt=mbr, note=b'P2P dispute MBR')
            atc.add_transaction(TransactionWithSigner(pay, AccountTransactionSigner('0'*64)))

            method = self._method('open_dispute')
            if method is None:
                return BuildResult(False, error='ABI method open_dispute not found')
            sp1 = transaction.SuggestedParams(fee=0, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            atc.add_method_call(
                app_id=self.app_id,
                method=method,
                sender=opener_address,
                sp=sp1,
                signer=AccountTransactionSigner('0'*64),  # placeholder; user signs
                method_args=[trade_id, reason],
                boxes=[(0, trade_id.encode()), (0, key)],
            )

            tws = atc.build_group()
            gid = transaction.calculate_group_id([t.txn for t in tws])
            sponsor_txs = [{'txn': algo_encoding.msgpack_encode(tws[0].txn), 'signed': None, 'index': 0}]
            user_txs = [{'txn': algo_encoding.msgpack_encode(tws[1].txn), 'signers': [opener_address], 'message': 'Open dispute'}]
            return BuildResult(True, transactions_to_sign=user_txs, sponsor_transactions=sponsor_txs, group_id=base64.b64encode(gid).decode(), trade_id=trade_id)
        except Exception as e:
            return BuildResult(False, error=str(e))

    def build_resolve_dispute(
        self,
        admin_address: str,
        trade_id: str,
        winner_address: str,
    ) -> BuildResult:
        """Build [Payment(sponsor fee-bump), AppCall(admin)] to resolve dispute.

        Boxes required: trade_id, trade_id+"_dispute", trade_id+"_paid" (optional but include).
        Include common assets to satisfy asset_holding_get for inner transfers.
        """
        try:
            params = self.algod_client.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000

            atc = AtomicTransactionComposer()
            # Budget generously for inner itxns: asset transfer + up to 2 MBR refunds
            sp0 = transaction.SuggestedParams(fee=6*min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            pay = transaction.PaymentTxn(sender=self.sponsor_address, sp=sp0, receiver=self.app_address, amt=0, note=b'P2P resolve dispute')
            atc.add_transaction(TransactionWithSigner(pay, AccountTransactionSigner('0'*64)))

            method = self._method('resolve_dispute')
            if method is None:
                return BuildResult(False, error='ABI method resolve_dispute not found')
            sp1 = transaction.SuggestedParams(fee=0, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True)
            foreign_assets = [a for a in [self.cusd_asset_id, self.confio_asset_id] if a]
            # Accounts: include sponsor (for refunds) and winner (for asset_holding_get)
            accounts: List[str] = []
            if self.sponsor_address:
                accounts.append(self.sponsor_address)
            if winner_address and winner_address not in accounts:
                accounts.append(winner_address)

            # Best-effort: include buyer, mbr_payer, dispute_payer derived from boxes to avoid 'unavailable Account' during inner refunds
            try:
                import base64 as _b64
                bx = self.algod_client.application_box_by_name(self.app_id, trade_id.encode('utf-8'))
                raw = _b64.b64decode((bx or {}).get('value', ''))
                if len(raw) >= 137:
                    buyer_b = raw[73:105]
                    mbr_payer_b = raw[105:137]
                    if len(buyer_b) == 32:
                        from algosdk import encoding as algo_encoding
                        buyer_addr = algo_encoding.encode_address(buyer_b)
                        if buyer_addr not in accounts:
                            accounts.append(buyer_addr)
                    if len(mbr_payer_b) == 32:
                        from algosdk import encoding as algo_encoding
                        mbr_payer_addr = algo_encoding.encode_address(mbr_payer_b)
                        if mbr_payer_addr not in accounts:
                            accounts.append(mbr_payer_addr)
                # Dispute box payer
                dbx = self.algod_client.application_box_by_name(self.app_id, (trade_id + "_dispute").encode('utf-8'))
                dval = _b64.b64decode((dbx or {}).get('value', ''))
                if len(dval) >= 104:
                    dispute_payer_b = dval[72:104]
                    if len(dispute_payer_b) == 32:
                        from algosdk import encoding as algo_encoding
                        dispute_payer_addr = algo_encoding.encode_address(dispute_payer_b)
                        if dispute_payer_addr not in accounts:
                            accounts.append(dispute_payer_addr)
            except Exception:
                pass

            atc.add_method_call(
                app_id=self.app_id,
                method=method,
                sender=admin_address,
                sp=sp1,
                signer=AccountTransactionSigner('0'*64),  # placeholder; admin signs
                method_args=[trade_id, winner_address],
                boxes=[
                    (0, trade_id.encode()),
                    (0, (trade_id + "_dispute").encode()),
                    (0, (trade_id + "_paid").encode()),
                ],
                foreign_assets=foreign_assets,
                accounts=accounts,
            )

            tws = atc.build_group()
            gid = transaction.calculate_group_id([t.txn for t in tws])
            sponsor_txs = [{'txn': algo_encoding.msgpack_encode(tws[0].txn), 'signed': None, 'index': 0}]
            user_txs = [{'txn': algo_encoding.msgpack_encode(tws[1].txn), 'signers': [admin_address], 'message': 'Resolve dispute'}]
            return BuildResult(True, transactions_to_sign=user_txs, sponsor_transactions=sponsor_txs, group_id=base64.b64encode(gid).decode(), trade_id=trade_id)
        except Exception as e:
            return BuildResult(False, error=str(e))
