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
from p2p_exchange.models import P2PTrade, P2PEscrow
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

logger = logging.getLogger(__name__)


def _b64_to_bytes(s: str) -> bytes:
    ss = s.strip().replace('-', '+').replace('_', '/')
    pad = (-len(ss)) % 4
    if pad:
        ss += '=' * pad
    return base64.b64decode(ss)


def accept_trade_for_trade_id(trade_id: str) -> tuple[bool, str | None]:
    """Server-internal helper to accept a trade on-chain (sponsor-only),
    resolving the buyer address directly from the trade record.

    Returns (success, error_message).
    """
    try:
        trade = P2PTrade.objects.filter(id=trade_id).select_related('offer').first()
        if not trade:
            return False, 'Trade not found'

        # Resolve buyer address from DB (business or personal)
        acct = None
        if getattr(trade, 'buyer_business_id', None):
            from users.models import Business
            try:
                biz = Business.objects.get(id=trade.buyer_business_id)
            except Business.DoesNotExist:
                return False, 'Buyer business not found'
            # Prefer account matching the business; fallback by index or any business account
            acct = (
                Account.objects.filter(business=biz, account_type='business', deleted_at__isnull=True).order_by('account_index').first()
            )
        elif getattr(trade, 'buyer_user_id', None):
            acct = Account.objects.filter(user_id=trade.buyer_user_id, account_type='personal', account_index=0, deleted_at__isnull=True).first()
        if not acct or not acct.algorand_address:
            return False, 'Buyer Algorand address not found'
        # Defensive: avoid accepting with sponsor address as buyer (would imprint wrong box buyer)
        try:
            sponsor_addr = getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', None)
            if sponsor_addr and acct.algorand_address == sponsor_addr:
                return False, 'Buyer Algorand address equals sponsor; skipping auto-accept to prevent wrong buyer'
        except Exception:
            pass

        builder = P2PTradeTransactionBuilder()
        # Preflight: ensure buyer is opted into required asset
        try:
            asset_id = builder._asset_id_for_type(str(trade.offer.token_type).upper()) if trade.offer and trade.offer.token_type else None
            if asset_id:
                algod_client_pref = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
                logger.info('[P2P AutoAccept] Preflight: buyer=%s asset_id=%s', acct.algorand_address, asset_id)
                algod_client_pref.account_asset_info(acct.algorand_address, asset_id)
        except Exception:
            return False, f'Buyer address not opted into asset {asset_id}'

        res = builder.build_accept_trade(acct.algorand_address, str(trade_id))
        if not res.success:
            return False, res.error or 'Failed to build accept trade group'

        sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
        if not sponsor_mn:
            return False, 'Server missing ALGORAND_SPONSOR_MNEMONIC'
        sk = mnemonic.to_private_key(sponsor_mn)
        algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)

        signed = []
        for e in (res.sponsor_transactions or []):
            tx = transaction.Transaction.undictify(msgpack.unpackb(base64.b64decode(e.get('txn')), raw=False))
            signed.append(tx.sign(sk))
        if not signed:
            return False, 'No sponsor transactions built'
        txid = algod_client.send_transactions(signed)
        logger.info('[P2P AutoAccept] Submitted sponsor group: trade_id=%s txid=%s', trade_id, txid)
        try:
            transaction.wait_for_confirmation(algod_client, signed[-1].get_txid(), 8)
        except Exception:
            pass

        # After on-chain accept, align DB expiry and broadcast to clients
        try:
            from django.utils import timezone
            from datetime import timedelta
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync

            trade = P2PTrade.objects.filter(id=trade_id).first()
            if trade:
                # If still pending, move to PAYMENT_PENDING
                if trade.status == 'PENDING':
                    trade.status = 'PAYMENT_PENDING'
                trade.expires_at = timezone.now() + timedelta(minutes=15)
                trade.save(update_fields=['status', 'expires_at', 'updated_at'])

                # Broadcast to trade chat room
                try:
                    channel_layer = get_channel_layer()
                    room_group_name = f'trade_chat_{trade.id}'
                    async_to_sync(channel_layer.group_send)(
                        room_group_name,
                        {
                            'type': 'trade_status_update',
                            'status': 'PAYMENT_PENDING',
                            'updated_by': 'system',
                            'expires_at': trade.expires_at.isoformat(),
                        },
                    )
                except Exception:
                    pass
        except Exception:
            pass

        return True, None
    except Exception as e:
        logger.exception('[P2P AutoAccept] Exception: trade_id=%s err=%r', trade_id, e)
        return False, str(e)


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
        try:
            logger.info('[P2P Create][env] Using P2P app_id=%s network=%s', getattr(settings, 'ALGORAND_P2P_TRADE_APP_ID', None), getattr(settings, 'ALGORAND_NETWORK', None))
        except Exception:
            pass
        builder = P2PTradeTransactionBuilder()
        try:
            logger.info('[P2P Create] Preparing group trade_id=%s seller=%s token=%s amount_u=%s', trade_id, getattr(acct, 'algorand_address', None), asset_type, amount_u)
        except Exception:
            pass
        # Idempotency: if box already exists on-chain, short-circuit success
        try:
            algod_client_pref = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
            try:
                algod_client_pref.application_box_by_name(builder.app_id, trade_id.encode('utf-8'))
                logger.info('[P2P Create] Box already exists for trade_id=%s; returning success without building group', trade_id)
                return P2PPreparedGroup(
                    success=True,
                    error=None,
                    user_transactions=[],
                    sponsor_transactions=[],
                    group_id=None,
                    trade_id=trade_id,
                )
            except Exception:
                pass
            logger.info('[P2P Create] Env check: app_id=%s sponsor=%s...', builder.app_id, (builder.sponsor_address or '')[:8])
        except Exception:
            pass
        res = builder.build_create_trade(acct.algorand_address, asset_type, amount_u, trade_id)
        if not res.success:
            return P2PPreparedGroup(success=False, error=res.error)

        # Collect user txns (unsigned) and sponsor entries
        user_txns = [t.get('txn') for t in (res.transactions_to_sign or [])]
        sponsor_entries = []
        for e in (res.sponsor_transactions or []):
            sponsor_entries.append(SponsorTxnType(txn=e.get('txn'), index=e.get('index')))

        # Debug: inspect app-call accounts (apat)
        try:
            def _core(x):
                return x if isinstance(x, dict) and 'type' in x else (x or {}).get('txn', {})
            appl = None
            for e in (res.sponsor_transactions or []):
                unpacked = msgpack.unpackb(base64.b64decode(e.get('txn')), raw=False)
                core = _core(unpacked)
                if core.get('type') == 'appl':
                    appl = core
                    break
            if appl is not None:
                apat = appl.get('apat')
                logger.info('[P2P Create] AppCall accounts (apat) present=%s len=%s', apat is not None, (len(apat) if isinstance(apat, list) else None))
        except Exception:
            pass

        return P2PPreparedGroup(
            success=True,
            user_transactions=user_txns,
            sponsor_transactions=sponsor_entries,
            group_id=res.group_id,
            trade_id=trade_id,
        )


class SubmitP2PCreateTrade(graphene.Mutation):
    class Arguments:
        signed_user_txns = graphene.List(graphene.String, required=True, description='Signed user txns: AXFER and AppCall (base64 msgpack)')
        sponsor_transactions = graphene.List(graphene.JSONString, required=True, description='List of sponsor txns as JSON strings {txn, index}')
        trade_id = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()
    txid = graphene.String()

    @classmethod
    def mutate(cls, root, info, signed_user_txns: List[str], sponsor_transactions: List[str], trade_id: str):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, error='Not authenticated')

        algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)

        # Decode signed user transactions (AXFER and AppCall)
        try:
            if not signed_user_txns or len(signed_user_txns) < 2:
                return cls(success=False, error='Expected two signed user transactions (AXFER and AppCall)')
            user_signed_dicts = []
            for s in signed_user_txns:
                b = _b64_to_bytes(s)
                d = msgpack.unpackb(b, raw=False)
                if not isinstance(d, dict) or 'txn' not in d:
                    return cls(success=False, error='Invalid signed user transaction payload')
                user_signed_dicts.append(d)
            # Classify
            axfer_dict = next((d for d in user_signed_dicts if d.get('txn', {}).get('type') == 'axfer'), None)
            app_dict = next((d for d in user_signed_dicts if d.get('txn', {}).get('type') == 'appl'), None)
            if not axfer_dict or not app_dict:
                return cls(success=False, error='Missing AXFER or AppCall in signed user transactions')
            try:
                user_sender_addr = algo_encoding.encode_address(axfer_dict['txn'].get('snd')) if axfer_dict.get('txn', {}).get('snd') else None
                logger.info('[P2P Submit] Decoded user AXFER: sender=%s asset=%s amt=%s', user_sender_addr, axfer_dict['txn'].get('xaid'), axfer_dict['txn'].get('aamt'))
            except Exception:
                pass
        except Exception as e:
            return cls(success=False, error=f'Invalid signed user transactions: {e}')

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
            app_call_txn_dict = None
            try:
                seller_addr_from_user = algo_encoding.encode_address(axfer_dict['txn'].get('snd')) if axfer_dict.get('txn', {}).get('snd') else None
            except Exception:
                seller_addr_from_user = None
            for e in parsed:
                b = base64.b64decode(e.get('txn'))
                unpacked = msgpack.unpackb(b, raw=False)
                # Unsigned txns encode fields at top-level, not under 'txn'
                txn_core = unpacked if isinstance(unpacked, dict) and 'type' in unpacked else (unpacked or {}).get('txn', {})
                tx = transaction.Transaction.undictify(unpacked)
                # Do not inject accounts at submit-time; allow on-chain validation to fail if absent.
                stx = tx.sign(sk)
                signed_by_idx[int(e.get('index'))] = stx
                try:
                    ttype = (txn_core or {}).get('type')
                    if ttype == 'appl' and app_call_txn_dict is None:
                        app_call_txn_dict = txn_core
                except Exception:
                    pass

            # Determine total group size dynamically: sponsor txns + user-signed txns (AXFER + AppCall)
            total_count = len(signed_by_idx) + len(user_signed_dicts)
            # Determine missing indices (user-signed: AXFER and AppCall)
            missing = sorted([i for i in range(total_count) if i not in signed_by_idx])
            if len(missing) != len(user_signed_dicts):
                return cls(success=False, error='Unexpected group shape: expected two user transactions')
            # Enforce that the AXFER sender matches the expected seller address from the AppCall accounts
            try:
                expected_seller = None
                if app_call_txn_dict and app_call_txn_dict.get('apat'):
                    expected_seller = algo_encoding.encode_address(app_call_txn_dict['apat'][0])
                # Classify user-signed dicts earlier
                axfer_dict = next((d for d in user_signed_dicts if d.get('txn', {}).get('type') == 'axfer'), None)
                user_sender_addr = algo_encoding.encode_address(axfer_dict['txn'].get('snd')) if axfer_dict and axfer_dict.get('txn', {}).get('snd') else None
                logger.info('[P2P Submit] Seller address check: expected=%s actual=%s', expected_seller, user_sender_addr)
                if expected_seller and user_sender_addr and expected_seller != user_sender_addr:
                    return cls(success=False, error=f'Active wallet does not match seller address for this trade. Expected {expected_seller}, got {user_sender_addr}. Switch wallet or update your active account and retry.')
            except Exception:
                # If we cannot determine addresses, proceed and rely on on-chain validation
                pass
        except Exception as e:
            return cls(success=False, error=f'Failed to sign sponsor txns: {e}')

        # Submit group
        try:
            ordered: list[transaction.SignedTransaction] = []
            axfer_stx = transaction.SignedTransaction.undictify(axfer_dict)
            app_stx = transaction.SignedTransaction.undictify(app_dict)
            # Heuristic: lower missing index is AXFER, higher is AppCall (matches builder order)
            idx_axfer, idx_app = missing[0], missing[1]
            for i in range(total_count):
                if i == idx_axfer:
                    ordered.append(axfer_stx)
                elif i == idx_app:
                    ordered.append(app_stx)
                else:
                    ordered.append(signed_by_idx[i])
            try:
                # Best-effort debug of ordered group composition
                parts = []
                for i, stx in enumerate(ordered):
                    txd_i = stx.dictify().get('txn', {})
                    itype = txd_i.get('type')
                    isnd = txd_i.get('snd')
                    parts.append(f"{i}:{itype}:{algo_encoding.encode_address(isnd) if isnd else '-'}")
                logger.info('[P2P Submit] Ordered group: %s', ' | '.join(parts))
            except Exception:
                pass
            txid = algod_client.send_transactions(ordered)
            # Prefer the last transaction's txid (AppCall is built last by the builder)
            ref_txid = ordered[-1].get_txid()
            transaction.wait_for_confirmation(algod_client, ref_txid, 8)
            # Best-effort: mark escrow as funded/started on the trade
            try:
                trade = P2PTrade.objects.filter(id=trade_id).first()
                if trade and hasattr(trade, 'escrow') and trade.escrow and not trade.escrow.is_escrowed:
                    escrow = trade.escrow
                    escrow.is_escrowed = True
                    escrow.escrow_transaction_hash = ref_txid
                    escrow.escrowed_at = timezone.now()
                    escrow.save(update_fields=['is_escrowed', 'escrow_transaction_hash', 'escrowed_at', 'updated_at'])
                    # Keep trade in PENDING until seller shares payment details
            except Exception as _:
                # Do not fail the mutation if local bookkeeping fails
                pass
            return cls(success=True, txid=ref_txid)
        except Exception as e:
            logger.exception('[P2P Submit] send_transactions failed: %r', e)
            # Idempotency: if the trade box exists on-chain after failure, treat as success
            try:
                builder = P2PTradeTransactionBuilder()
                algod_client_pref = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
                algod_client_pref.application_box_by_name(builder.app_id, trade_id.encode('utf-8'))
                logger.warning('[P2P Submit] Box exists after failure; returning success trade_id=%s', trade_id)
                return cls(success=True, txid=None)
            except Exception:
                pass
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
        try:
            logger.info('[P2P Accept][env] Using P2P app_id=%s network=%s', getattr(settings, 'ALGORAND_P2P_TRADE_APP_ID', None), getattr(settings, 'ALGORAND_NETWORK', None))
        except Exception:
            pass
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
        # Defensive: do not proceed if buyer address equals sponsor address (would imprint wrong buyer)
        try:
            sponsor_addr = getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', None)
            if sponsor_addr and acct.algorand_address == sponsor_addr:
                return cls(success=False, error='Buyer address equals sponsor. Switch to your buyer wallet and retry.')
        except Exception:
            pass

        # Authorization: only the trade's buyer may accept
        try:
            trade_check = P2PTrade.objects.filter(id=trade_id).first()
            if not trade_check:
                logger.warning('[P2P Accept] Trade not found: %s', trade_id)
                return cls(success=False, error='Trade not found')
            is_buyer = False
            buyer_side = 'unknown'
            # Business buyer
            if trade_check.buyer_business_id:
                buyer_side = f'business:{trade_check.buyer_business_id}'
                is_buyer = (
                    jwt_ctx.get('account_type') == 'business'
                    and str(jwt_ctx.get('business_id')) == str(trade_check.buyer_business_id)
                )
            # Personal buyer
            elif trade_check.buyer_user_id:
                buyer_side = f'user:{trade_check.buyer_user_id}'
                is_buyer = (
                    jwt_ctx.get('account_type') != 'business'
                    and int(jwt_ctx.get('user_id')) == int(trade_check.buyer_user_id)
                )
            if not is_buyer:
                logger.warning(
                    '[P2P Accept] Rejecting: only buyer may accept (trade=%s buyer=%s jwt_type=%s jwt_user=%s jwt_biz=%s)',
                    trade_id,
                    buyer_side,
                    jwt_ctx.get('account_type'),
                    jwt_ctx.get('user_id'),
                    jwt_ctx.get('business_id'),
                )
                return cls(success=False, error='Only the buyer can accept this trade')
        except Exception as e:
            logger.exception('[P2P Accept] Authorization check failed for trade %s: %r', trade_id, e)
            return cls(success=False, error='Authorization check failed')

        builder = P2PTradeTransactionBuilder()
        # Preflights to avoid opaque on-chain asserts
        # 1) Check buyer asset opt-in from DB token type if available
        try:
            trade_obj = P2PTrade.objects.filter(id=trade_id).select_related('offer').first()
            if trade_obj and trade_obj.offer and trade_obj.offer.token_type:
                token = str(trade_obj.offer.token_type).upper()
                asset_id = builder._asset_id_for_type(token)
                algod_client_pref = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
                try:
                    algod_client_pref.account_asset_info(acct.algorand_address, asset_id)
                except Exception:
                    msg = f'Buyer address not opted into {token} (asset {asset_id}); please opt in and retry'
                    logger.warning('[P2P Accept] %s (buyer=%s)', msg, acct.algorand_address)
                    return cls(success=False, error=msg)
                # 2) Ensure on-chain trade box exists (seller escrow created)
                try:
                    algod_client_pref.application_box_by_name(builder.app_id, trade_id.encode('utf-8'))
                except Exception:
                    msg = 'Trade escrow not found on-chain. Seller must deposit escrow before accept.'
                    logger.warning('[P2P Accept] %s trade_id=%s', msg, trade_id)
                    return cls(success=False, error=msg)
                # 3) Ensure buyer and seller Algorand addresses differ to prevent self-trade
                try:
                    seller_addr = None
                    if getattr(trade_obj, 'seller_business_id', None):
                        s_acct = Account.objects.filter(business_id=trade_obj.seller_business_id, account_type='business', deleted_at__isnull=True).first()
                        seller_addr = getattr(s_acct, 'algorand_address', None)
                    elif getattr(trade_obj, 'seller_user_id', None):
                        s_acct = Account.objects.filter(user_id=trade_obj.seller_user_id, account_type='personal', account_index=0, deleted_at__isnull=True).first()
                        seller_addr = getattr(s_acct, 'algorand_address', None)
                    if seller_addr and seller_addr == acct.algorand_address:
                        msg = 'Buyer and seller Algorand addresses are identical; self-trade is not allowed. Configure distinct addresses.'
                        logger.warning('[P2P Accept] %s trade_id=%s buyer=%s', msg, trade_id, acct.algorand_address)
                        return cls(success=False, error=msg)
                except Exception:
                    pass
        except Exception:
            pass

        res = builder.build_accept_trade(acct.algorand_address, trade_id)
        if not res.success:
            logger.error('[P2P Accept] build_accept_trade failed: trade_id=%s error=%s', trade_id, res.error)
            return cls(success=False, error=res.error)
        logger.info('[P2P Accept] Built sponsor group: trade_id=%s tx_count=%d', trade_id, len(res.sponsor_transactions or []))

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
            logger.info('[P2P Accept] Submitted sponsor group: trade_id=%s txid=%s', trade_id, txid)
            transaction.wait_for_confirmation(algod_client, signed[-1].get_txid(), 8)
            logger.info('[P2P Accept] Confirmed: trade_id=%s appcall_txid=%s', trade_id, signed[-1].get_txid())

            # After on-chain accept, update trade status locally and broadcast
            try:
                trade = P2PTrade.objects.filter(id=trade_id).first()
                if trade:
                    # Only transition from PENDING -> PAYMENT_PENDING
                    if trade.status == 'PENDING':
                        from django.utils import timezone
                        from datetime import timedelta
                        trade.status = 'PAYMENT_PENDING'
                        # Align local expiry to contract window (15 minutes from accept)
                        trade.expires_at = timezone.now() + timedelta(minutes=15)
                        trade.save(update_fields=['status', 'expires_at', 'updated_at'])

                        # Broadcast status update to WebSocket trade room
                        channel_layer = get_channel_layer()
                        room_group_name = f'trade_chat_{trade.id}'
                        async_to_sync(channel_layer.group_send)(
                            room_group_name,
                            {
                                'type': 'trade_status_update',
                                'status': 'PAYMENT_PENDING',
                                'updated_by': str(info.context.user.id),
                                'payment_reference': '',
                                'payment_notes': '',
                                'expires_at': trade.expires_at.isoformat() if getattr(trade, 'expires_at', None) else None,
                            },
                        )
            except Exception as _:
                # Best-effort: do not fail the blockchain accept on local update errors
                pass

            return cls(success=True, txid=signed[-1].get_txid())
        except Exception as e:
            logger.exception('[P2P Accept] Exception sending sponsor group: trade_id=%s err=%r', trade_id, e)
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
            ref_txid = user_stx.get_txid()
        except Exception as e:
            return cls(success=False, error=str(e))

        # Reflect 10-minute extension locally if still within original window
        try:
            trade = P2PTrade.objects.filter(id=trade_id).first()
            if trade and getattr(trade, 'expires_at', None):
                from django.utils import timezone
                from datetime import timedelta
                if timezone.now() <= trade.expires_at:
                    trade.expires_at = trade.expires_at + timedelta(minutes=10)
                    trade.save(update_fields=['expires_at', 'updated_at'])
                    # Optionally broadcast updated expiry to chat room listeners
                    try:
                        channel_layer = get_channel_layer()
                        room_group_name = f'trade_chat_{trade.id}'
                        async_to_sync(channel_layer.group_send)(
                            room_group_name,
                            {
                                'type': 'trade_status_update',
                                'status': getattr(trade, 'status', ''),
                                'updated_by': str(info.context.user.id),
                                'expires_at': trade.expires_at.isoformat(),
                            },
                        )
                    except Exception:
                        pass
        except Exception:
            pass

        return cls(success=True, txid=ref_txid)


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
            # Wait for the AppCall confirmation (user_stx is the AppCall)
            ref_txid = user_stx.get_txid()
            transaction.wait_for_confirmation(algod_client, ref_txid, 8)

            # Reflect CRYPTO_RELEASED in DB, update escrow bookkeeping, and broadcast
            try:
                from django.utils import timezone
                trade = P2PTrade.objects.filter(id=trade_id).select_related('escrow').first()
                if trade:
                    # Update trade status and completion time
                    trade.status = 'CRYPTO_RELEASED'
                    trade.completed_at = timezone.now()
                    trade.save(update_fields=['status', 'completed_at', 'updated_at'])

                    # Update escrow bookkeeping if present
                    try:
                        escrow = getattr(trade, 'escrow', None)
                        if escrow and escrow.is_escrowed and not escrow.is_released:
                            escrow.is_released = True
                            escrow.release_type = 'NORMAL'
                            escrow.release_amount = escrow.escrow_amount
                            escrow.release_transaction_hash = ref_txid
                            escrow.released_at = timezone.now()
                            escrow.save(update_fields=[
                                'is_released', 'release_type', 'release_amount',
                                'release_transaction_hash', 'released_at', 'updated_at'
                            ])
                    except Exception:
                        # Do not fail the mutation if escrow update bookkeeping fails
                        pass

                    # Broadcast to trade chat room so clients can react immediately
                    try:
                        channel_layer = get_channel_layer()
                        room_group_name = f'trade_chat_{trade.id}'
                        async_to_sync(channel_layer.group_send)(
                            room_group_name,
                            {
                                'type': 'trade_status_update',
                                'status': 'CRYPTO_RELEASED',
                                'updated_by': str(getattr(info.context.user, 'id', 'system')),
                                'txid': ref_txid,
                            },
                        )
                    except Exception:
                        pass

                    # Send success notifications to both parties
                    try:
                        from notifications.utils import create_p2p_notification
                        from notifications.models import NotificationType as NotificationTypeChoices

                        buyer_user = trade.buyer_user if trade.buyer_user else (trade.buyer_business.accounts.first().user if trade.buyer_business else None)
                        seller_user = trade.seller_user if trade.seller_user else (trade.seller_business.accounts.first().user if trade.seller_business else None)
                        notification_data = {
                            'amount': str(trade.crypto_amount),
                            'token_type': trade.offer.token_type if trade.offer else 'CUSD',
                            'trade_id': str(trade.id),
                            'counterparty_name': trade.seller_display_name if buyer_user else trade.buyer_display_name,
                            'fiat_amount': str(trade.fiat_amount),
                            'fiat_currency': trade.offer.currency_code if trade.offer else '',
                            'payment_method': trade.payment_method.name if getattr(trade, 'payment_method', None) else '',
                            'trader_name': trade.seller_display_name,
                            'counterparty_phone': trade.buyer_user.phone_number if trade.buyer_user else None,
                        }
                        # Notify buyer that crypto was released
                        if buyer_user:
                            create_p2p_notification(
                                notification_type=NotificationTypeChoices.P2P_CRYPTO_RELEASED,
                                user=buyer_user,
                                business=trade.buyer_business,
                                trade_id=str(trade.id),
                                amount=str(trade.crypto_amount),
                                token_type=(trade.offer.token_type if trade.offer else 'CUSD'),
                                counterparty_name=trade.seller_display_name,
                                additional_data=notification_data,
                            )
                        # Optionally notify seller as well
                        if seller_user:
                            create_p2p_notification(
                                notification_type=NotificationTypeChoices.P2P_CRYPTO_RELEASED,
                                user=seller_user,
                                business=trade.seller_business,
                                trade_id=str(trade.id),
                                amount=str(trade.crypto_amount),
                                token_type=(trade.offer.token_type if trade.offer else 'CUSD'),
                                counterparty_name=trade.buyer_display_name,
                                additional_data=notification_data,
                            )
                    except Exception:
                        pass
            except Exception:
                # Non-fatal if local DB bookkeeping fails
                pass

            # Ensure unified transaction row exists/updated for this P2P exchange
            try:
                from users.signals import create_unified_transaction_from_p2p_trade
                trade_obj = P2PTrade.objects.filter(id=trade_id).first()
                if trade_obj:
                    create_unified_transaction_from_p2p_trade(trade_obj)
            except Exception:
                pass

            return cls(success=True, txid=ref_txid)
        except Exception as e:
            return cls(success=False, error=str(e))


class PrepareP2pAcceptTrade(graphene.Mutation):
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

        # Resolve BUYER address from JWT
        jwt_ctx = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_ctx:
            return cls(success=False, error='Invalid JWT context')
        if jwt_ctx['account_type'] == 'business' and jwt_ctx.get('business_id'):
            from users.models import Business
            try:
                biz = Business.objects.get(id=jwt_ctx['business_id'])
                acct = Account.objects.filter(business=biz, account_type='business', deleted_at__isnull=True).first()
            except Business.DoesNotExist:
                return cls(success=False, error='Buyer business not found')
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
        res = builder.build_accept_trade_user(acct.algorand_address, trade_id)
        if not res.success:
            return cls(success=False, error=res.error)

        # Idempotency: if trade already ACTIVE, short-circuit
        try:
            algod_client_pref = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
            bx = algod_client_pref.application_box_by_name(builder.app_id, trade_id.encode('utf-8'))
            import base64 as _b64
            raw = _b64.b64decode((bx or {}).get('value', ''))
            status_b = raw[64:65] if len(raw) >= 65 else b''
            if status_b and status_b.hex() == '01':
                return cls(success=True, user_transactions=[], sponsor_transactions=[], group_id=res.group_id, trade_id=trade_id)
        except Exception:
            pass

        return cls(
            success=True,
            user_transactions=[t.get('txn') for t in (res.transactions_to_sign or [])],
            sponsor_transactions=[SponsorTxnType(txn=e.get('txn'), index=e.get('index')) for e in (res.sponsor_transactions or [])],
            group_id=res.group_id,
            trade_id=trade_id,
        )


class SubmitP2pAcceptTrade(graphene.Mutation):
    class Arguments:
        trade_id = graphene.String(required=True)
        signed_user_txn = graphene.String(required=True)
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
        # Decode user-signed AppCall
        try:
            user_b = _b64_to_bytes(signed_user_txn)
            user_dict = msgpack.unpackb(user_b, raw=False)
            if user_dict.get('txn', {}).get('type') != 'appl':
                return cls(success=False, error='Signed transaction is not an AppCall')
        except Exception as e:
            return cls(success=False, error=f'Invalid signed AppCall: {e}')

        # Sign sponsor fee-bump and submit atomic group [sponsorPay, userAppCall]
        try:
            sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
            if not sponsor_mn:
                return cls(success=False, error='Server missing ALGORAND_SPONSOR_MNEMONIC')
            sk = mnemonic.to_private_key(sponsor_mn)

            parsed = [json.loads(s) if isinstance(s, str) else s for s in sponsor_transactions or []]
            if not parsed:
                return cls(success=False, error='Missing sponsor transaction')
            b = base64.b64decode(parsed[0].get('txn'))
            stx0 = transaction.Transaction.undictify(msgpack.unpackb(b, raw=False)).sign(sk)
            user_stx = transaction.SignedTransaction.undictify(user_dict)

            txid = algod_client.send_transactions([stx0, user_stx])
            # Wait for confirmation
            transaction.wait_for_confirmation(algod_client, user_stx.get_txid(), 8)
            ref_txid = user_stx.get_txid()
        except Exception as e:
            return cls(success=False, error=str(e))

        # Update trade status and expiry, broadcast with expires_at
        try:
            trade = P2PTrade.objects.filter(id=trade_id).first()
            if trade:
                from django.utils import timezone
                from datetime import timedelta
                if trade.status == 'PENDING':
                    trade.status = 'PAYMENT_PENDING'
                trade.expires_at = timezone.now() + timedelta(minutes=15)
                trade.save(update_fields=['status', 'expires_at', 'updated_at'])

                try:
                    channel_layer = get_channel_layer()
                    room_group_name = f'trade_chat_{trade.id}'
                    async_to_sync(channel_layer.group_send)(
                        room_group_name,
                        {
                            'type': 'trade_status_update',
                            'status': 'PAYMENT_PENDING',
                            'updated_by': str(info.context.user.id),
                            'expires_at': trade.expires_at.isoformat(),
                        },
                    )
                except Exception:
                    pass
        except Exception:
            pass

        return cls(success=True, txid=ref_txid)


class P2PTradeMutations(graphene.ObjectType):
    prepare_p2p_create_trade = PrepareP2PCreateTrade.Field()
    submit_p2p_create_trade = SubmitP2PCreateTrade.Field()
    accept_p2p_trade = AcceptP2PTrade.Field()
    prepare_p2p_accept_trade = PrepareP2pAcceptTrade.Field()
    submit_p2p_accept_trade = SubmitP2pAcceptTrade.Field()
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
        try:
            logger.info('[P2P Prepare][mark_paid][env] Using P2P app_id=%s network=%s', getattr(settings, 'ALGORAND_P2P_TRADE_APP_ID', None), getattr(settings, 'ALGORAND_NETWORK', None))
        except Exception:
            pass
        # Preflight: validate status ACTIVE and buyer account matches current wallet; log sponsor config
        try:
            algod_client_pref = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
            app_info = algod_client_pref.application_info(builder.app_id)
            gs = { }
            for kv in app_info.get('params', {}).get('global-state', []) or []:
                key = base64.b64decode(kv.get('key', '')).decode('utf-8', errors='ignore')
                if 'bytes' in (kv.get('value') or {}):
                    try:
                        b = base64.b64decode(kv['value']['bytes'])
                        if len(b) == 32:
                            gs[key] = algo_encoding.encode_address(b)
                        else:
                            gs[key] = kv['value']['bytes']
                    except Exception:
                        gs[key] = kv['value']['bytes']
                else:
                    gs[key] = (kv.get('value') or {}).get('uint')
            app_sponsor = gs.get('sponsor_address')
            env_sponsor_addr = getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', None)
            try:
                from algosdk import account as algo_account
                _mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
                env_sponsor_from_mn = algo_account.address_from_private_key(mnemonic.to_private_key(_mn)) if _mn else None
            except Exception:
                env_sponsor_from_mn = None
            logger.info('[P2P Prepare][mark_paid] Sponsor sanity: app=%s env_addr=%s env_from_mn=%s', (app_sponsor or '')[:12], (env_sponsor_addr or '')[:12], (env_sponsor_from_mn or '')[:12])
            # Inspect trade box to verify on-chain buyer matches current wallet and status ACTIVE
            try:
                bx = algod_client_pref.application_box_by_name(builder.app_id, trade_id.encode('utf-8'))
                import base64 as _b64
                raw = _b64.b64decode((bx or {}).get('value', ''))
                status_b = raw[64:65] if len(raw) >= 65 else b''
                buyer_b = raw[73:105] if len(raw) >= 105 else b''
                buyer_addr = algo_encoding.encode_address(buyer_b) if len(buyer_b) == 32 else None
                status_hex = status_b.hex() if status_b else ''
                logger.info('[P2P Prepare][mark_paid] Box sanity: trade_id=%s box_len=%s buyer=%s status_hex=%s', trade_id, len(raw), (buyer_addr or '')[:12], status_hex)
                # Enforce ACTIVE and correct buyer to avoid on-chain assert
                if status_hex != '01':
                    return cls(success=False, error='El intercambio todavía no está ACTIVO en cadena. Espera unos segundos e inténtalo de nuevo.')
                if buyer_addr and buyer_addr != acct.algorand_address:
                    return cls(success=False, error=f'Debes marcar pagado desde la cuenta compradora: {buyer_addr}')
                # Do not special-case buyer == sponsor here; rely on proper group alignment elsewhere
            except Exception:
                pass
        except Exception:
            pass
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


class PrepareP2PCancel(graphene.Mutation):
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
        jwt_ctx = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_ctx:
            return cls(success=False, error='Invalid JWT context')
        if jwt_ctx['account_type'] == 'business' and jwt_ctx.get('business_id'):
            from users.models import Business
            try:
                biz = Business.objects.get(id=jwt_ctx['business_id'])
                acct = Account.objects.get(business=biz, account_type='business')
            except (Business.DoesNotExist, Account.DoesNotExist):
                return cls(success=False, error='Business Algorand address not found')
        else:
            acct = Account.objects.filter(user_id=jwt_ctx['user_id'], account_type='personal', account_index=jwt_ctx.get('account_index', 0), deleted_at__isnull=True).first()
        if not acct or not acct.algorand_address:
            return cls(success=False, error='Algorand address not found')
        builder = P2PTradeTransactionBuilder()

        # Preflight: read on-chain box and validate authorization conditions with friendly errors
        try:
            from django.utils import timezone
            algod_client_pref = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
            # 1) Trade box must exist (seller escrowed)
            try:
                bx = algod_client_pref.application_box_by_name(builder.app_id, trade_id.encode('utf-8'))
            except Exception:
                return cls(success=False, error='La custodia aún no existe en la cadena. Habilita el intercambio primero.')

            import base64 as _b64
            raw = _b64.b64decode((bx or {}).get('value', ''))
            if len(raw) < 106:
                return cls(success=False, error='Datos de intercambio incompletos en cadena')

            seller_b = raw[0:32]
            expires_at_b = raw[56:64]
            status_b = raw[64:65]
            accepted_at_b = raw[65:73]
            seller_addr = algo_encoding.encode_address(seller_b)
            expires_at = int.from_bytes(expires_at_b, byteorder='big', signed=False)
            status_hex = status_b.hex() if status_b else ''

            # Paid box (optional)
            paid_at = 0
            try:
                pbx = algod_client_pref.application_box_by_name(builder.app_id, f"{trade_id}_paid".encode('utf-8'))
                pval = _b64.b64decode((pbx or {}).get('value', ''))
                if len(pval) >= 8:
                    paid_at = int.from_bytes(pval[0:8], byteorder='big', signed=False)
            except Exception:
                paid_at = 0

            now = int(timezone.now().timestamp())
            caller = acct.algorand_address

            # Status PENDING (00): only the seller who created escrow can cancel immediately (or anyone after 24h; omitted here)
            if status_hex == '00':
                if caller != seller_addr:
                    return cls(success=False, error=f'Debes cancelar desde la cuenta vendedora que creó la custodia: {seller_addr}')
            else:
                # Status ACTIVE (01): must be expired + 120s grace and not marked as paid
                if expires_at <= 0:
                    return cls(success=False, error='La expiración en cadena no está establecida aún')
                if now <= expires_at:
                    return cls(success=False, error='El intercambio aún no ha expirado en cadena')
                GRACE = 120
                remain = (expires_at + GRACE) - now
                if remain > 0:
                    return cls(success=False, error=f'Espera {remain} segundos de gracia tras el vencimiento para recuperar fondoss')
                if paid_at and paid_at > 0:
                    return cls(success=False, error='Este intercambio ya fue marcado como pagado; no es posible recuperar. Usa disputa si es necesario.')
        except Exception:
            # Best-effort: continue to build, contract will enforce
            pass

        res = builder.build_cancel_trade(acct.algorand_address, trade_id)
        if not res.success:
            return cls(success=False, error=res.error)
        return cls(
            success=True,
            user_transactions=[t.get('txn') for t in (res.transactions_to_sign or [])],
            sponsor_transactions=[SponsorTxnType(txn=e.get('txn'), index=e.get('index')) for e in (res.sponsor_transactions or [])],
            group_id=res.group_id,
            trade_id=trade_id,
        )


class CancelP2PTrade(graphene.Mutation):
    class Arguments:
        trade_id = graphene.String(required=True)
        signed_user_txn = graphene.String(required=True)
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
        try:
            user_signed = _b64_to_bytes(signed_user_txn)
            user_dict = msgpack.unpackb(user_signed, raw=False)
            if user_dict.get('txn', {}).get('type') != 'appl':
                return cls(success=False, error='Signed transaction is not an AppCall')
        except Exception as e:
            return cls(success=False, error=f'Invalid signed AppCall: {e}')

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
            # Wait for the AppCall confirmation (user_stx is the AppCall)
            ref_txid = user_stx.get_txid()
            transaction.wait_for_confirmation(algod_client, ref_txid, 8)

            # Reflect cancellation in DB and broadcast to clients
            try:
                trade = P2PTrade.objects.filter(id=trade_id).select_related('escrow').first()
                if trade:
                    # Update trade status
                    trade.status = 'CANCELLED'
                    trade.updated_at = timezone.now()
                    trade.save(update_fields=['status', 'updated_at'])

                    # Update escrow bookkeeping if present
                    try:
                        escrow = getattr(trade, 'escrow', None)
                        if escrow and escrow.is_escrowed and not escrow.is_released:
                            # Funds were in escrow on-chain and have been refunded to seller
                            escrow.is_released = True
                            escrow.release_type = 'REFUND'
                            escrow.release_amount = escrow.escrow_amount
                            escrow.release_transaction_hash = ref_txid
                            escrow.released_at = timezone.now()
                            escrow.save(update_fields=[
                                'is_released', 'release_type', 'release_amount',
                                'release_transaction_hash', 'released_at', 'updated_at'
                            ])
                    except Exception:
                        # Do not fail the mutation if escrow update bookkeeping fails
                        pass

                    # Broadcast to trade room so clients can update immediately
                    try:
                        channel_layer = get_channel_layer()
                        room_group_name = f'trade_chat_{trade.id}'
                        async_to_sync(channel_layer.group_send)(
                            room_group_name,
                            {
                                'type': 'trade_status_update',
                                'status': 'CANCELLED',
                                'updated_by': str(getattr(info.context.user, 'id', 'system')),
                                'txid': ref_txid,
                            },
                        )
                    except Exception:
                        pass
            except Exception:
                # Non-fatal if local DB bookkeeping fails
                pass

            return cls(success=True, txid=ref_txid)
        except Exception as e:
            return cls(success=False, error=str(e))

class PrepareP2POpenDispute(graphene.Mutation):
    class Arguments:
        trade_id = graphene.String(required=True)
        reason = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()
    user_transactions = graphene.List(graphene.String)
    sponsor_transactions = graphene.List(SponsorTxnType)
    group_id = graphene.String()
    trade_id = graphene.String()

    @classmethod
    def mutate(cls, root, info, trade_id: str, reason: str):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, error='Not authenticated')

        # Ensure user is part of the trade (buyer/seller; user or business)
        trade = P2PTrade.objects.filter(id=trade_id).select_related('buyer_user', 'seller_user', 'buyer_business', 'seller_business').first()
        if not trade:
            return cls(success=False, error='Trade not found')

        # Resolve opener address from the side the user controls
        acct = None
        try:
            # Business side first
            if trade.buyer_business_id:
                from users.models import Business
                try:
                    biz = Business.objects.get(id=trade.buyer_business_id)
                    if biz.accounts.filter(user=user, deleted_at__isnull=True).exists():
                        acct = Account.objects.filter(business=biz, account_type='business', user=user, deleted_at__isnull=True).first() or \
                               Account.objects.filter(business=biz, account_type='business', deleted_at__isnull=True).first()
                except Business.DoesNotExist:
                    pass
            if not acct and trade.seller_business_id:
                from users.models import Business
                try:
                    biz = Business.objects.get(id=trade.seller_business_id)
                    if biz.accounts.filter(user=user, deleted_at__isnull=True).exists():
                        acct = Account.objects.filter(business=biz, account_type='business', user=user, deleted_at__isnull=True).first() or \
                               Account.objects.filter(business=biz, account_type='business', deleted_at__isnull=True).first()
                except Business.DoesNotExist:
                    pass
            # Personal side fallback
            if not acct and (trade.buyer_user_id == user.id or trade.seller_user_id == user.id):
                acct = Account.objects.filter(user_id=user.id, account_type='personal', deleted_at__isnull=True).order_by('account_index').first()
        except Exception:
            acct = None
        if not acct or not acct.algorand_address:
            return cls(success=False, error='Opener Algorand address not found for this trade')

        builder = P2PTradeTransactionBuilder()
        res = builder.build_open_dispute(acct.algorand_address, trade_id, reason)
        if not res.success:
            return cls(success=False, error=res.error)

        return cls(
            success=True,
            user_transactions=[t.get('txn') for t in (res.transactions_to_sign or [])],
            sponsor_transactions=[SponsorTxnType(txn=e.get('txn'), index=e.get('index')) for e in (res.sponsor_transactions or [])],
            group_id=res.group_id,
            trade_id=trade_id,
        )


class SubmitP2POpenDispute(graphene.Mutation):
    class Arguments:
        trade_id = graphene.String(required=True)
        signed_user_txn = graphene.String(required=True)
        sponsor_transactions = graphene.List(graphene.JSONString, required=True)
        reason = graphene.String(required=False)

    success = graphene.Boolean()
    error = graphene.String()
    txid = graphene.String()

    @classmethod
    def mutate(cls, root, info, trade_id: str, signed_user_txn: str, sponsor_transactions: List[str], reason: Optional[str] = None):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, error='Not authenticated')

        algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)

        # Decode user-signed AppCall
        try:
            user_signed = _b64_to_bytes(signed_user_txn)
            user_dict = msgpack.unpackb(user_signed, raw=False)
            if user_dict.get('txn', {}).get('type') != 'appl':
                return cls(success=False, error='Signed transaction is not an AppCall')
        except Exception as e:
            return cls(success=False, error=f'Invalid signed AppCall: {e}')

        # Sign sponsor txn and submit group
        try:
            sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
            if not sponsor_mn:
                return cls(success=False, error='Server missing ALGORAND_SPONSOR_MNEMONIC')
            sk = mnemonic.to_private_key(sponsor_mn)

            parsed = [json.loads(s) if isinstance(s, str) else s for s in (sponsor_transactions or [])]
            if not parsed:
                return cls(success=False, error='Missing sponsor transaction')
            b = base64.b64decode(parsed[0].get('txn'))
            tx = transaction.Transaction.undictify(msgpack.unpackb(b, raw=False))
            stx0 = tx.sign(sk)
            user_stx = transaction.SignedTransaction.undictify(user_dict)
            txid = algod_client.send_transactions([stx0, user_stx])
            ref_txid = user_stx.get_txid()
            transaction.wait_for_confirmation(algod_client, ref_txid, 8)

            # Reflect in DB: set status and create dispute record
            try:
                trade = P2PTrade.objects.filter(id=trade_id).first()
                if trade and trade.status not in ('DISPUTED', 'CANCELLED', 'COMPLETED'):
                    trade.status = 'DISPUTED'
                    trade.updated_at = timezone.now()
                    trade.save(update_fields=['status', 'updated_at'])
                # Create dispute record if missing
                try:
                    from users.jwt_context import get_jwt_business_context_with_validation
                    from p2p_exchange.models import P2PDispute
                    exists = False
                    try:
                        _ = trade.dispute_details
                        exists = True
                    except Exception:
                        exists = False
                    if trade and not exists:
                        dispute_kwargs = {
                            'trade': trade,
                            'reason': (reason or 'Dispute opened on-chain').strip(),
                            'priority': 2,
                            'status': 'UNDER_REVIEW',
                        }
                        jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
                        user = getattr(info.context, 'user', None)
                        if jwt_context and jwt_context.get('account_type') == 'business' and jwt_context.get('business_id'):
                            # Assign to buyer/seller business if matches
                            try:
                                if trade.buyer_business_id == jwt_context.get('business_id'):
                                    dispute_kwargs['initiator_business'] = trade.buyer_business
                                elif trade.seller_business_id == jwt_context.get('business_id'):
                                    dispute_kwargs['initiator_business'] = trade.seller_business
                                elif user and getattr(user, 'id', None):
                                    dispute_kwargs['initiator_user'] = user
                            except Exception:
                                if user and getattr(user, 'id', None):
                                    dispute_kwargs['initiator_user'] = user
                        else:
                            if user and getattr(user, 'id', None):
                                dispute_kwargs['initiator_user'] = user
                        P2PDispute.objects.create(**dispute_kwargs)
                except Exception:
                    pass
                # Record system message
                try:
                    from p2p_exchange.models import P2PMessage
                    P2PMessage.objects.create(
                        trade=trade,
                        message='🚩 Disputa abierta en cadena',
                        sender_type='system',
                        message_type='system',
                    )
                except Exception:
                    pass
            except Exception:
                pass

            return cls(success=True, txid=ref_txid)
        except Exception as e:
            return cls(success=False, error=str(e))


class PrepareP2PResolveDispute(graphene.Mutation):
    class Arguments:
        trade_id = graphene.String(required=True)
        winner = graphene.String(required=True, description='"BUYER" or "SELLER"')

    success = graphene.Boolean()
    error = graphene.String()
    user_transactions = graphene.List(graphene.String)
    sponsor_transactions = graphene.List(SponsorTxnType)
    group_id = graphene.String()
    trade_id = graphene.String()

    @classmethod
    def mutate(cls, root, info, trade_id: str, winner: str):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, error='Not authenticated')
        if not (user.is_staff or user.is_superuser):
            return cls(success=False, error='Admin privileges required')

        trade = P2PTrade.objects.filter(id=trade_id).select_related('buyer_user', 'seller_user', 'buyer_business', 'seller_business').first()
        if not trade:
            return cls(success=False, error='Trade not found')

        # Resolve winner address from side
        side = (winner or '').strip().upper()
        if side not in ('BUYER', 'SELLER'):
            return cls(success=False, error='winner must be BUYER or SELLER')

        def _resolve_address_for_user(u) -> Optional[str]:
            a = Account.objects.filter(user_id=u.id, account_type='personal', deleted_at__isnull=True).order_by('account_index').first()
            return getattr(a, 'algorand_address', None) if a else None

        def _resolve_address_for_business(biz_id) -> Optional[str]:
            from users.models import Business
            try:
                biz = Business.objects.get(id=biz_id)
            except Business.DoesNotExist:
                return None
            a = Account.objects.filter(business=biz, account_type='business', deleted_at__isnull=True).order_by('account_index').first()
            return getattr(a, 'algorand_address', None) if a else None

        winner_addr = None
        if side == 'BUYER':
            winner_addr = _resolve_address_for_business(trade.buyer_business_id) if trade.buyer_business_id else (
                _resolve_address_for_user(trade.buyer_user) if trade.buyer_user_id else None)
        else:
            winner_addr = _resolve_address_for_business(trade.seller_business_id) if trade.seller_business_id else (
                _resolve_address_for_user(trade.seller_user) if trade.seller_user_id else None)
        if not winner_addr:
            return cls(success=False, error='Winner Algorand address not found')

        # Resolve admin caller address (personal account)
        admin_acct = Account.objects.filter(user_id=user.id, account_type='personal', deleted_at__isnull=True).order_by('account_index').first()
        if not admin_acct or not admin_acct.algorand_address:
            return cls(success=False, error='Admin Algorand address not found')

        builder = P2PTradeTransactionBuilder()
        res = builder.build_resolve_dispute(admin_acct.algorand_address, trade_id, winner_addr)
        if not res.success:
            return cls(success=False, error=res.error)
        return cls(
            success=True,
            user_transactions=[t.get('txn') for t in (res.transactions_to_sign or [])],
            sponsor_transactions=[SponsorTxnType(txn=e.get('txn'), index=e.get('index')) for e in (res.sponsor_transactions or [])],
            group_id=res.group_id,
            trade_id=trade_id,
        )


class SubmitP2PResolveDispute(graphene.Mutation):
    class Arguments:
        trade_id = graphene.String(required=True)
        signed_user_txn = graphene.String(required=True)
        sponsor_transactions = graphene.List(graphene.JSONString, required=True)

    success = graphene.Boolean()
    error = graphene.String()
    txid = graphene.String()

    @classmethod
    def mutate(cls, root, info, trade_id: str, signed_user_txn: str, sponsor_transactions: List[str]):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, error='Not authenticated')
        if not (user.is_staff or user.is_superuser):
            return cls(success=False, error='Admin privileges required')

        algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)

        try:
            user_signed = _b64_to_bytes(signed_user_txn)
            user_dict = msgpack.unpackb(user_signed, raw=False)
            if user_dict.get('txn', {}).get('type') != 'appl':
                return cls(success=False, error='Signed transaction is not an AppCall')
        except Exception as e:
            return cls(success=False, error=f'Invalid signed AppCall: {e}')

        try:
            sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
            if not sponsor_mn:
                return cls(success=False, error='Server missing ALGORAND_SPONSOR_MNEMONIC')
            sk = mnemonic.to_private_key(sponsor_mn)

            parsed = [json.loads(s) if isinstance(s, str) else s for s in (sponsor_transactions or [])]
            if not parsed:
                return cls(success=False, error='Missing sponsor transaction')
            b = base64.b64decode(parsed[0].get('txn'))
            tx = transaction.Transaction.undictify(msgpack.unpackb(b, raw=False))
            stx0 = tx.sign(sk)
            user_stx = transaction.SignedTransaction.undictify(user_dict)
            txid = algod_client.send_transactions([stx0, user_stx])
            ref_txid = user_stx.get_txid()
            transaction.wait_for_confirmation(algod_client, ref_txid, 8)

            # Reflect resolution locally (best-effort)
            try:
                trade = P2PTrade.objects.filter(id=trade_id).select_related('escrow').first()
                if trade:
                    # If escrow exists, mark as released
                    try:
                        escrow = getattr(trade, 'escrow', None)
                        if escrow and escrow.is_escrowed and not escrow.is_released:
                            escrow.is_released = True
                            # Do not guess winner here; just mark disputed release
                            escrow.release_type = 'DISPUTE_RELEASE'
                            escrow.release_amount = escrow.escrow_amount
                            escrow.release_transaction_hash = ref_txid
                            escrow.released_at = timezone.now()
                            escrow.save(update_fields=['is_released', 'release_type', 'release_amount', 'release_transaction_hash', 'released_at', 'updated_at'])
                    except Exception:
                        pass
                    # Trade terminal status will be updated by the admin DB flow as well
                    trade.updated_at = timezone.now()
                    trade.save(update_fields=['updated_at'])
                    try:
                        from p2p_exchange.models import P2PMessage
                        P2PMessage.objects.create(
                            trade=trade,
                            message='✅ Disputa resuelta en cadena',
                            sender_type='system',
                            message_type='system',
                        )
                    except Exception:
                        pass
            except Exception:
                pass

            return cls(success=True, txid=ref_txid)
        except Exception as e:
            return cls(success=False, error=str(e))


# Backend-only: Admin resolves dispute on-chain (server signs both txns)
class ResolveP2pDisputeOnchain(graphene.Mutation):
    class Arguments:
        trade_id = graphene.String(required=True)
        winner = graphene.String(required=True, description='"BUYER" or "SELLER"')

    success = graphene.Boolean()
    error = graphene.String()
    txid = graphene.String()

    @classmethod
    def mutate(cls, root, info, trade_id: str, winner: str):
        user = info.context.user
        if not (user and getattr(user, 'is_authenticated', False)):
            return cls(success=False, error='Authentication required')
        if not (user.is_staff or user.is_superuser):
            return cls(success=False, error='Admin privileges required')

        # Require server-held admin mnemonic
        admin_mn = getattr(settings, 'ALGORAND_ADMIN_MNEMONIC', None)
        if not admin_mn:
            return cls(success=False, error='Server missing ALGORAND_ADMIN_MNEMONIC')

        try:
            from algosdk import mnemonic
            from algosdk.v2client import algod
            from algosdk import encoding as algo_encoding
            from algosdk import transaction
            import msgpack

            # Resolve winner address from trade
            trade = P2PTrade.objects.filter(id=trade_id).select_related('buyer_user', 'seller_user', 'buyer_business', 'seller_business').first()
            if not trade:
                return cls(success=False, error='Trade not found')

            side = (winner or '').strip().upper()
            if side not in ('BUYER', 'SELLER'):
                return cls(success=False, error='winner must be BUYER or SELLER')

            def _resolve_addr_user(u) -> Optional[str]:
                a = Account.objects.filter(user_id=getattr(u, 'id', None), account_type='personal', deleted_at__isnull=True).order_by('account_index').first()
                return getattr(a, 'algorand_address', None) if a else None

            def _resolve_addr_biz(biz_id) -> Optional[str]:
                from users.models import Business
                try:
                    biz = Business.objects.get(id=biz_id)
                except Business.DoesNotExist:
                    return None
                a = Account.objects.filter(business=biz, account_type='business', deleted_at__isnull=True).order_by('account_index').first()
                return getattr(a, 'algorand_address', None) if a else None

            winner_addr = None
            if side == 'BUYER':
                winner_addr = _resolve_addr_biz(trade.buyer_business_id) if trade.buyer_business_id else _resolve_addr_user(trade.buyer_user)
            else:
                winner_addr = _resolve_addr_biz(trade.seller_business_id) if trade.seller_business_id else _resolve_addr_user(trade.seller_user)
            if not winner_addr:
                return cls(success=False, error='Winner Algorand address not found')

            # Admin sender address
            from algosdk import account as algo_account
            admin_sk = mnemonic.to_private_key(admin_mn)
            admin_addr = algo_account.address_from_private_key(admin_sk)

            # Build group
            builder = P2PTradeTransactionBuilder()
            res = builder.build_resolve_dispute(admin_addr, trade_id, winner_addr)
            if not res.success:
                return cls(success=False, error=res.error)

            # Sign sponsor txn
            sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
            if not sponsor_mn:
                return cls(success=False, error='Server missing ALGORAND_SPONSOR_MNEMONIC')
            sponsor_sk = mnemonic.to_private_key(sponsor_mn)

            parsed = [json.loads(s) if isinstance(s, str) else s for s in (res.sponsor_transactions or [])]
            if not parsed:
                return cls(success=False, error='Missing sponsor transaction from builder')

            # Undictify and sign
            sponsor_b = base64.b64decode(parsed[0].get('txn'))
            sponsor_tx = transaction.Transaction.undictify(msgpack.unpackb(sponsor_b, raw=False))
            stx0 = sponsor_tx.sign(sponsor_sk)

            # User/admin appcall: res.transactions_to_sign[0]
            if not res.transactions_to_sign:
                return cls(success=False, error='Missing admin AppCall from builder')
            appcall_b64 = (res.transactions_to_sign[0] or {}).get('txn')
            if not appcall_b64:
                return cls(success=False, error='Missing admin AppCall payload')
            appcall_tx = transaction.Transaction.undictify(msgpack.unpackb(base64.b64decode(appcall_b64), raw=False))
            stx1 = appcall_tx.sign(admin_sk)

            algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
            txid = algod_client.send_transactions([stx0, stx1])
            ref_txid = stx1.get_txid()
            try:
                transaction.wait_for_confirmation(algod_client, ref_txid, 8)
            except Exception:
                pass

            # Best-effort local bookkeeping (status handled elsewhere in admin flow)
            try:
                trade.updated_at = timezone.now()
                trade.save(update_fields=['updated_at'])
                from p2p_exchange.models import P2PMessage
                P2PMessage.objects.create(
                    trade=trade,
                    message=f'✅ Disputa resuelta en cadena ({side})',
                    sender_type='system',
                    message_type='system',
                )
            except Exception:
                pass

            return cls(success=True, txid=ref_txid)
        except Exception as e:
            logger.exception('[P2P Dispute] Backend resolve error: %r', e)
            return cls(success=False, error=str(e))
# Late-bind fields that depend on classes defined earlier in the module
P2PTradeMutations.cancel_p2p_trade = CancelP2PTrade.Field()
P2PTradePrepareMutations.prepare_p2p_cancel = PrepareP2PCancel.Field()
P2PTradePrepareMutations.prepare_p2p_open_dispute = PrepareP2POpenDispute.Field()
P2PTradeMutations.submit_p2p_open_dispute = SubmitP2POpenDispute.Field()
P2PTradePrepareMutations.prepare_p2p_resolve_dispute = PrepareP2PResolveDispute.Field()
P2PTradeMutations.submit_p2p_resolve_dispute = SubmitP2PResolveDispute.Field()
P2PTradeMutations.resolve_p2p_dispute_onchain = ResolveP2pDisputeOnchain.Field()
