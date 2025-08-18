"""
P2P Trade GraphQL Mutations (Algorand)

Server builds fully sponsored groups for P2P trades via the p2p_trade app.
Client signs only their own tx(s) where required; server signs sponsor
transactions and submits the complete group.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import List, Optional

import graphene
from django.conf import settings
from algosdk.v2client import algod
from algosdk import mnemonic, encoding as algo_encoding
from algosdk import transaction
import msgpack

from .p2p_trade_transaction_builder import P2PTradeTransactionBuilder
from users.jwt_context import get_jwt_business_context_with_validation
from users.models import Account

logger = logging.getLogger(__name__)


def _b64_to_bytes(s: str) -> bytes:
    ss = s.strip().replace('-', '+').replace('_', '/')
    pad = (-len(ss)) % 4
    if pad:
        ss += '=' * pad
    return base64.b64decode(ss)


class SponsorTxnType(graphene.ObjectType):
    txn = graphene.String()
    index = graphene.Int()


class P2PPreparedGroup(graphene.ObjectType):
    success = graphene.Boolean()
    error = graphene.String()
    user_transactions = graphene.List(graphene.String, description='Base64-encoded unsigned txns user must sign')
    sponsor_transactions = graphene.List(SponsorTxnType)
    group_id = graphene.String()
    trade_id = graphene.String()


class PrepareP2PCreateTrade(graphene.Mutation):
    class Arguments:
        trade_id = graphene.String(required=True)
        amount = graphene.Float(required=True)
        asset_type = graphene.String(required=False, default_value='CUSD')

    Output = P2PPreparedGroup

    @classmethod
    def mutate(cls, root, info, trade_id: str, amount: float, asset_type: str = 'CUSD'):
        user = info.context.user
        if not user.is_authenticated:
            return P2PPreparedGroup(success=False, error='Not authenticated')

        # Resolve SELLER address from JWT
        jwt_ctx = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_ctx:
            return P2PPreparedGroup(success=False, error='Invalid JWT context')
        # Resolve seller address from JWT context, preferring the current user's account within the business
        if jwt_ctx['account_type'] == 'business' and jwt_ctx.get('business_id'):
            from users.models import Business
            try:
                biz = Business.objects.get(id=jwt_ctx['business_id'])
            except Business.DoesNotExist:
                return P2PPreparedGroup(success=False, error='Business not found for seller')
            # Prefer an account record scoped to this user within the business (employees/owners)
            acct = (
                Account.objects.filter(
                    business=biz,
                    account_type='business',
                    user_id=jwt_ctx.get('user_id'),
                    deleted_at__isnull=True,
                ).first()
                or Account.objects.filter(
                    business=biz,
                    account_type='business',
                    account_index=jwt_ctx.get('account_index', 0),
                    deleted_at__isnull=True,
                ).first()
                or Account.objects.filter(
                    business=biz,
                    account_type='business',
                    deleted_at__isnull=True,
                ).first()
            )
        else:
            acct = Account.objects.filter(
                user_id=jwt_ctx['user_id'],
                account_type='personal',
                account_index=jwt_ctx.get('account_index', 0),
                deleted_at__isnull=True,
            ).first()
        if not acct or not acct.algorand_address:
            return P2PPreparedGroup(success=False, error='Seller Algorand address not found')

        amount_u = int(amount * 1_000_000)
        builder = P2PTradeTransactionBuilder()
        res = builder.build_create_trade(acct.algorand_address, asset_type, amount_u, trade_id)
        if not res.success:
            return P2PPreparedGroup(success=False, error=res.error)

        # Collect user txns (unsigned) and sponsor entries
        user_txns = [t.get('txn') for t in (res.transactions_to_sign or [])]
        sponsor_entries = []
        for e in (res.sponsor_transactions or []):
            sponsor_entries.append(SponsorTxnType(txn=e.get('txn'), index=e.get('index')))

        return P2PPreparedGroup(
            success=True,
            user_transactions=user_txns,
            sponsor_transactions=sponsor_entries,
            group_id=res.group_id,
            trade_id=trade_id,
        )


class SubmitP2PCreateTrade(graphene.Mutation):
    class Arguments:
        signed_user_txn = graphene.String(required=True, description='Signed AXFER from seller (base64 msgpack)')
        sponsor_transactions = graphene.List(graphene.JSONString, required=True, description='List of sponsor txns as JSON strings {txn, index}')
        trade_id = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()
    txid = graphene.String()

    @classmethod
    def mutate(cls, root, info, signed_user_txn: str, sponsor_transactions: List[str], trade_id: str):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, error='Not authenticated')

        algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)

        # Decode signed user AXFER
        try:
            user_signed = _b64_to_bytes(signed_user_txn)
            user_dict = msgpack.unpackb(user_signed, raw=False)
            if not isinstance(user_dict, dict) or 'txn' not in user_dict:
                return cls(success=False, error='Invalid signed user transaction payload')
            txd = user_dict['txn']
            if txd.get('type') != 'axfer':
                return cls(success=False, error='Signed transaction is not an AXFER')
        except Exception as e:
            return cls(success=False, error=f'Invalid signed AXFER: {e}')

        # Sign sponsor transactions
        try:
            sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
            if not sponsor_mn:
                return cls(success=False, error='Server missing ALGORAND_SPONSOR_MNEMONIC')
            sk = mnemonic.to_private_key(sponsor_mn)

            parsed = []
            for s in sponsor_transactions:
                parsed.append(json.loads(s) if isinstance(s, str) else s)
            signed_by_idx: dict[int, transaction.SignedTransaction] = {}
            for e in parsed:
                b = base64.b64decode(e.get('txn'))
                tx = transaction.Transaction.undictify(msgpack.unpackb(b, raw=False))
                stx = tx.sign(sk)
                signed_by_idx[int(e.get('index'))] = stx

            # Missing index is user AXFER (idx 2)
            user_index = next(i for i in range(4) if i not in signed_by_idx)
        except Exception as e:
            return cls(success=False, error=f'Failed to sign sponsor txns: {e}')

        # Submit group
        try:
            ordered: list[transaction.SignedTransaction] = []
            user_stx = transaction.SignedTransaction.undictify(user_dict)
            for i in range(4):
                if i == user_index:
                    ordered.append(user_stx)
                else:
                    ordered.append(signed_by_idx[i])
            txid = algod_client.send_transactions(ordered)
            # Prefer app call txid at index 3
            ref_txid = ordered[3].get_txid()
            transaction.wait_for_confirmation(algod_client, ref_txid, 8)
            return cls(success=True, txid=ref_txid)
        except Exception as e:
            logger.exception('[P2P Submit] send_transactions failed: %r', e)
            return cls(success=False, error=str(e))


class AcceptP2PTrade(graphene.Mutation):
    class Arguments:
        trade_id = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()
    txid = graphene.String()

    @classmethod
    def mutate(cls, root, info, trade_id: str):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, error='Not authenticated')

        # Resolve BUYER address from JWT
        jwt_ctx = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_ctx:
            return cls(success=False, error='Invalid JWT context')
        if jwt_ctx['account_type'] == 'business' and jwt_ctx.get('business_id'):
            from users.models import Business
            try:
                biz = Business.objects.get(id=jwt_ctx['business_id'])
            except Business.DoesNotExist:
                return cls(success=False, error='Buyer business not found')
            # Prefer account for this user within business, then fallback by index, then any business account
            acct = (
                Account.objects.filter(
                    business=biz,
                    account_type='business',
                    user_id=jwt_ctx.get('user_id'),
                    deleted_at__isnull=True,
                ).first()
                or Account.objects.filter(
                    business=biz,
                    account_type='business',
                    account_index=jwt_ctx.get('account_index', 0),
                    deleted_at__isnull=True,
                ).first()
                or Account.objects.filter(
                    business=biz,
                    account_type='business',
                    deleted_at__isnull=True,
                ).first()
            )
        else:
            acct = Account.objects.filter(
                user_id=jwt_ctx['user_id'],
                account_type='personal',
                account_index=jwt_ctx.get('account_index', 0),
                deleted_at__isnull=True,
            ).first()
        if not acct or not acct.algorand_address:
            return cls(success=False, error='Buyer Algorand address not found')

        builder = P2PTradeTransactionBuilder()
        res = builder.build_accept_trade(acct.algorand_address, trade_id)
        if not res.success:
            return cls(success=False, error=res.error)

        # Sign sponsor txns and submit (2 transactions)
        try:
            sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
            if not sponsor_mn:
                return cls(success=False, error='Server missing ALGORAND_SPONSOR_MNEMONIC')
            sk = mnemonic.to_private_key(sponsor_mn)
            algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)

            # Decode and sign
            signed = []
            for e in (res.sponsor_transactions or []):
                tx = transaction.Transaction.undictify(msgpack.unpackb(base64.b64decode(e.get('txn')), raw=False))
                signed.append(tx.sign(sk))
            txid = algod_client.send_transactions(signed)
            transaction.wait_for_confirmation(algod_client, signed[-1].get_txid(), 8)
            return cls(success=True, txid=signed[-1].get_txid())
        except Exception as e:
            return cls(success=False, error=str(e))


class MarkP2PTradePaid(graphene.Mutation):
    class Arguments:
        trade_id = graphene.String(required=True)
        payment_ref = graphene.String(required=True)
        signed_user_txn = graphene.String(required=True, description='Signed AppCall from buyer (base64 msgpack)')
        sponsor_transactions = graphene.List(graphene.JSONString, required=True)

    success = graphene.Boolean()
    error = graphene.String()
    txid = graphene.String()

    @classmethod
    def mutate(cls, root, info, trade_id: str, payment_ref: str, signed_user_txn: str, sponsor_transactions: List[str]):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, error='Not authenticated')

        algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
        # Decode buyer-signed app call
        try:
            user_signed = _b64_to_bytes(signed_user_txn)
            user_dict = msgpack.unpackb(user_signed, raw=False)
            if user_dict.get('txn', {}).get('type') != 'appl':
                return cls(success=False, error='Signed transaction is not an AppCall')
        except Exception as e:
            return cls(success=False, error=f'Invalid signed AppCall: {e}')

        # Sign sponsor payment and submit pair
        try:
            sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
            if not sponsor_mn:
                return cls(success=False, error='Server missing ALGORAND_SPONSOR_MNEMONIC')
            sk = mnemonic.to_private_key(sponsor_mn)

            parsed = []
            for s in sponsor_transactions:
                parsed.append(json.loads(s) if isinstance(s, str) else s)
            if not parsed:
                return cls(success=False, error='Missing sponsor transaction')
            b = base64.b64decode(parsed[0].get('txn'))
            tx = transaction.Transaction.undictify(msgpack.unpackb(b, raw=False))
            stx0 = tx.sign(sk)
            user_stx = transaction.SignedTransaction.undictify(user_dict)
            txid = algod_client.send_transactions([stx0, user_stx])
            transaction.wait_for_confirmation(algod_client, user_stx.get_txid(), 8)
            return cls(success=True, txid=user_stx.get_txid())
        except Exception as e:
            return cls(success=False, error=str(e))


class ConfirmP2PTradeReceived(graphene.Mutation):
    class Arguments:
        trade_id = graphene.String(required=True)
        signed_user_txn = graphene.String(required=True, description='Signed AppCall from seller (base64 msgpack)')
        sponsor_transactions = graphene.List(graphene.JSONString, required=True)

    success = graphene.Boolean()
    error = graphene.String()
    txid = graphene.String()

    @classmethod
    def mutate(cls, root, info, trade_id: str, signed_user_txn: str, sponsor_transactions: List[str]):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, error='Not authenticated')

        algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
        # Decode seller-signed app call
        try:
            user_signed = _b64_to_bytes(signed_user_txn)
            user_dict = msgpack.unpackb(user_signed, raw=False)
            if user_dict.get('txn', {}).get('type') != 'appl':
                return cls(success=False, error='Signed transaction is not an AppCall')
        except Exception as e:
            return cls(success=False, error=f'Invalid signed AppCall: {e}')

        # Sign sponsor payment and submit pair
        try:
            sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
            if not sponsor_mn:
                return cls(success=False, error='Server missing ALGORAND_SPONSOR_MNEMONIC')
            sk = mnemonic.to_private_key(sponsor_mn)

            parsed = []
            for s in sponsor_transactions:
                parsed.append(json.loads(s) if isinstance(s, str) else s)
            if not parsed:
                return cls(success=False, error='Missing sponsor transaction')
            b = base64.b64decode(parsed[0].get('txn'))
            tx = transaction.Transaction.undictify(msgpack.unpackb(b, raw=False))
            stx0 = tx.sign(sk)
            user_stx = transaction.SignedTransaction.undictify(user_dict)
            txid = algod_client.send_transactions([stx0, user_stx])
            transaction.wait_for_confirmation(algod_client, user_stx.get_txid(), 8)
            return cls(success=True, txid=user_stx.get_txid())
        except Exception as e:
            return cls(success=False, error=str(e))


class P2PTradeMutations(graphene.ObjectType):
    prepare_p2p_create_trade = PrepareP2PCreateTrade.Field()
    submit_p2p_create_trade = SubmitP2PCreateTrade.Field()
    accept_p2p_trade = AcceptP2PTrade.Field()
    mark_p2p_trade_paid = MarkP2PTradePaid.Field()
    confirm_p2p_trade_received = ConfirmP2PTradeReceived.Field()


# Additional prepare helpers for user-signed steps
class PrepareP2PMarkPaid(graphene.Mutation):
    class Arguments:
        trade_id = graphene.String(required=True)
        payment_ref = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()
    user_transactions = graphene.List(graphene.String)
    sponsor_transactions = graphene.List(SponsorTxnType)
    group_id = graphene.String()
    trade_id = graphene.String()

    @classmethod
    def mutate(cls, root, info, trade_id: str, payment_ref: str):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, error='Not authenticated')
        # Resolve buyer address from JWT
        jwt_ctx = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_ctx:
            return cls(success=False, error='Invalid JWT context')
        if jwt_ctx['account_type'] == 'business' and jwt_ctx.get('business_id'):
            from users.models import Business
            try:
                biz = Business.objects.get(id=jwt_ctx['business_id'])
                acct = Account.objects.get(business=biz, account_type='business')
            except (Business.DoesNotExist, Account.DoesNotExist):
                return cls(success=False, error='Buyer business Algorand address not found')
        else:
            acct = Account.objects.filter(user_id=jwt_ctx['user_id'], account_type='personal', account_index=jwt_ctx.get('account_index', 0), deleted_at__isnull=True).first()
        if not acct or not acct.algorand_address:
            return cls(success=False, error='Buyer Algorand address not found')
        builder = P2PTradeTransactionBuilder()
        res = builder.build_mark_paid(acct.algorand_address, trade_id, payment_ref)
        if not res.success:
            return cls(success=False, error=res.error)
        return cls(
            success=True,
            user_transactions=[t.get('txn') for t in (res.transactions_to_sign or [])],
            sponsor_transactions=[SponsorTxnType(txn=e.get('txn'), index=e.get('index')) for e in (res.sponsor_transactions or [])],
            group_id=res.group_id,
            trade_id=trade_id,
        )


class PrepareP2PConfirmReceived(graphene.Mutation):
    class Arguments:
        trade_id = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()
    user_transactions = graphene.List(graphene.String)
    sponsor_transactions = graphene.List(SponsorTxnType)
    group_id = graphene.String()
    trade_id = graphene.String()

    @classmethod
    def mutate(cls, root, info, trade_id: str):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, error='Not authenticated')
        # Resolve seller address from JWT
        jwt_ctx = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_ctx:
            return cls(success=False, error='Invalid JWT context')
        if jwt_ctx['account_type'] == 'business' and jwt_ctx.get('business_id'):
            from users.models import Business
            try:
                biz = Business.objects.get(id=jwt_ctx['business_id'])
                acct = Account.objects.get(business=biz, account_type='business')
            except (Business.DoesNotExist, Account.DoesNotExist):
                return cls(success=False, error='Seller business Algorand address not found')
        else:
            acct = Account.objects.filter(user_id=jwt_ctx['user_id'], account_type='personal', account_index=jwt_ctx.get('account_index', 0), deleted_at__isnull=True).first()
        if not acct or not acct.algorand_address:
            return cls(success=False, error='Seller Algorand address not found')
        builder = P2PTradeTransactionBuilder()
        res = builder.build_confirm_received(acct.algorand_address, trade_id)
        if not res.success:
            return cls(success=False, error=res.error)
        return cls(
            success=True,
            user_transactions=[t.get('txn') for t in (res.transactions_to_sign or [])],
            sponsor_transactions=[SponsorTxnType(txn=e.get('txn'), index=e.get('index')) for e in (res.sponsor_transactions or [])],
            group_id=res.group_id,
            trade_id=trade_id,
        )


class P2PTradePrepareMutations(graphene.ObjectType):
    prepare_p2p_mark_paid = PrepareP2PMarkPaid.Field()
    prepare_p2p_confirm_received = PrepareP2PConfirmReceived.Field()
