"""
P2P Trade GraphQL Mutations (Algorand)

Server builds fully sponsored groups for P2P trades via the p2p_trade app.
Client signs only their own tx(s) where required; server signs sponsor
transactions and submits the complete group.
"""

from __future__ import annotations

from blockchain.algorand_config import get_algod_client

import base64
import json
import logging
from typing import List, Optional

import graphene
from django.conf import settings
from algosdk.v2client import algod
from algosdk import encoding as algo_encoding
from algosdk import transaction
from blockchain.kms_manager import get_kms_signer_from_settings, KMSTransactionSigner
import msgpack

from .p2p_trade_transaction_builder import P2PTradeTransactionBuilder
from users.jwt_context import get_jwt_business_context_with_validation
from users.models import Account
from p2p_exchange.models import P2PTrade, P2PEscrow
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

logger = logging.getLogger(__name__)
SPONSOR_SIGNER = get_kms_signer_from_settings()


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
                algod_client_pref = get_algod_client()
                logger.info('[P2P AutoAccept] Preflight: buyer=%s asset_id=%s', acct.algorand_address, asset_id)
                algod_client_pref.account_asset_info(acct.algorand_address, asset_id)
        except Exception:
            return False, f'Buyer address not opted into asset {asset_id}'

        res = builder.build_accept_trade(acct.algorand_address, str(trade_id))
        if not res.success:
            return False, res.error or 'Failed to build accept trade group'

        SPONSOR_SIGNER.assert_matches_address(getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', None))
        algod_client = get_algod_client()

        signed = []
        for e in (res.sponsor_transactions or []):
            tx = transaction.Transaction.undictify(msgpack.unpackb(base64.b64decode(e.get('txn')), raw=False))
            signed.append(SPONSOR_SIGNER.sign_transaction(tx))
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
            algod_client_pref = get_algod_client()
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
        # Additional idempotency: if we recently submitted an escrow tx for this trade, short-circuit
        try:
            tr = P2PTrade.objects.filter(id=trade_id).select_related('escrow').first()
            if tr and getattr(tr, 'escrow', None):
                esc = tr.escrow
                if getattr(esc, 'escrow_transaction_hash', ''):
                    # If a submit already occurred (even if not yet confirmed), avoid returning another build
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


def _extract_params(user_txn_dict: Dict) -> Optional[transaction.SuggestedParams]:
    try:
        t = user_txn_dict.get('txn', {})
        gh = t.get('gh')
        if isinstance(gh, bytes):
            import base64
            gh = base64.b64encode(gh).decode()
        return transaction.SuggestedParams(
            fee=t.get('fee', 1000),
            first=t.get('fv'),
            last=t.get('lv'),
            gh=gh,
            gen=t.get('gen'),
            flat_fee=True
        )
    except Exception:
        return None


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

        algod_client = get_algod_client()

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
            SPONSOR_SIGNER.assert_matches_address(getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', None))

            # Rebuild the expected sponsor transactions server-side to avoid blind signing
            seller_addr_from_user = None
            try:
                seller_addr_from_user = algo_encoding.encode_address(axfer_dict['txn'].get('snd')) if axfer_dict.get('txn', {}).get('snd') else None
            except Exception:
                pass

            # Derive asset/token and amount from the signed AXFER to drive the builder
            asset_id = axfer_dict['txn'].get('xaid')
            amount_u = axfer_dict['txn'].get('aamt')
            if not asset_id or not amount_u:
                return cls(success=False, error='AXFER missing asset or amount')
            token_type = None
            try:
                if int(asset_id) == int(getattr(settings, 'ALGORAND_CUSD_ASSET_ID', 0)):
                    token_type = 'CUSD'
                elif int(asset_id) == int(getattr(settings, 'ALGORAND_CONFIO_ASSET_ID', 0)):
                    token_type = 'CONFIO'
            except Exception:
                pass
            if not token_type:
                return cls(success=False, error=f'Unsupported asset_id {asset_id} for trade')

            # Rebuild sponsor txns deterministically
            builder = P2PTradeTransactionBuilder()
            sp = _extract_params(axfer_dict)
            res = builder.build_create_trade(seller_addr_from_user, token_type, int(amount_u), trade_id, params=sp)
            if not res.success:
                return cls(success=False, error=res.error or 'Failed to rebuild sponsor transactions')
            expected = {int(e.get('index')): e.get('txn') for e in (res.sponsor_transactions or [])}

            # Ensure provided sponsor payloads match server-built canonical ones
            try:
                provided = {int((json.loads(s) if isinstance(s, str) else s).get('index')): (json.loads(s) if isinstance(s, str) else s).get('txn') for s in sponsor_transactions or []}
            except Exception:
                provided = {}
            if not expected or expected != provided:
                return cls(success=False, error='Sponsor transactions mismatch – please re-run prepare and retry')

            signed_by_idx: dict[int, transaction.SignedTransaction] = {}
            app_call_txn_dict = None
            for idx, txn_b64 in expected.items():
                b = base64.b64decode(txn_b64)
                unpacked = msgpack.unpackb(b, raw=False)
                txn_core = unpacked if isinstance(unpacked, dict) and 'type' in unpacked else (unpacked or {}).get('txn', {})
                tx = transaction.Transaction.undictify(unpacked)
                stx = SPONSOR_SIGNER.sign_transaction(tx)
                signed_by_idx[idx] = stx
                try:
                    ttype = (txn_core or {}).get('type')
                    if ttype == 'appl' and app_call_txn_dict is None:
                        app_call_txn_dict = txn_core
                except Exception:
                    pass

            # Determine total group size dynamically: sponsor txns + user-signed txns (AXFER + AppCall)
            total_count = len(signed_by_idx) + len(user_signed_dicts)
            
            # --- DEBUG: Verify Group ID Consistency ---
            try:
                client_grp = axfer_dict['txn'].get('grp')
                if client_grp:
                    import base64
                    client_grp_b64 = base64.b64encode(client_grp).decode()
                    logger.info(f'[P2P Submit] Client Group ID: {client_grp_b64}')
                
                # CheckParams
                logger.info(f'[P2P Submit] Extracted Params: first={sp.first} last={sp.last} gh={sp.gh} gen={sp.gen} fee={sp.fee} min_fee={getattr(sp, "min_fee", "N/A")}')

                # Re-calculate group ID from the ORDERED list of txns we are about to submit
                # We need to construct the full list of UNsigned txns to calc group id
                temp_txns = [None] * total_count
                for idx, txn in expected.items():
                    # Sponsor txns
                    b = base64.b64decode(txn)
                    u = msgpack.unpackb(b, raw=False)
                    # Clear group if present to recalculate
                    if 'grp' in u['txn']: del u['txn']['grp']
                    temp_txns[idx] = transaction.Transaction.undictify(u)
                
                # User txns
                for idx, d in enumerate(user_signed_dicts):
                    # We don't know the exact index yet without 'missing', but we know logical order
                    # Wait, 'missing' is calculated below. Let's calculate it here.
                    missing_idxs = sorted([i for i in range(total_count) if i not in signed_by_idx])
                    # Heuristic: lower => AXFER, higher => APPL
                    target_idx = missing_idxs[idx] # user_signed_dicts is [AXFER, APPL] usually? No, order in list depends on client
                    # We verified user_signed_dicts earlier has AXFER and APPL
                    # But the loop above "for s in signed_user_txns" preserves order sent by client
                    # Client sends [AXFER, APPL] ?
                    # Let's rely on axfer_dict and app_dict objects we already identified
                    
                # Actually, let's just grab the sponsor txn (Tx 0) and compare it against what we think it should be
                # If Tx 0 changes, Group ID changes. 
                # We can't easily see Client's Tx 0 (it's not sent).
                # But we can see if User Tx contains the same Group ID as our new calc
                
            except Exception as e:
                logger.error(f'[P2P Debug] Group ID Check Error: {e}')
            # ------------------------------------------

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

            # Do NOT wait for confirmation here. Mark as submitted and return immediately.
            # Celery scan_outbound_confirmations will confirm and update escrow+notifications.
            try:
                trade = P2PTrade.objects.filter(id=trade_id).first()
                if trade and hasattr(trade, 'escrow') and trade.escrow:
                    escrow = trade.escrow
                    if not escrow.escrow_transaction_hash:
                        escrow.escrow_transaction_hash = ref_txid
                        escrow.save(update_fields=['escrow_transaction_hash', 'updated_at'])
            except Exception:
                pass
            return cls(success=True, txid=ref_txid)
        except Exception as e:
            logger.exception('[P2P Submit] send_transactions failed: %r', e)
            # Idempotency: if the trade box exists on-chain after failure, treat as success
            try:
                builder = P2PTradeTransactionBuilder()
                algod_client_pref = get_algod_client()
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
                algod_client_pref = get_algod_client()
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
            SPONSOR_SIGNER.assert_matches_address(getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', None))
            algod_client = get_algod_client()

            # Decode and sign
            signed = []
            for e in (res.sponsor_transactions or []):
                tx = transaction.Transaction.undictify(msgpack.unpackb(base64.b64decode(e.get('txn')), raw=False))
                signed.append(SPONSOR_SIGNER.sign_transaction(tx))
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

        algod_client = get_algod_client()
        # Decode buyer-signed app call
        try:
            user_signed = _b64_to_bytes(signed_user_txn)
            user_dict = msgpack.unpackb(user_signed, raw=False)
            if user_dict.get('txn', {}).get('type') != 'appl':
                return cls(success=False, error='Signed transaction is not an AppCall')
        except Exception as e:
            return cls(success=False, error=f'Invalid signed AppCall: {e}')

        # Rebuild sponsor txn deterministically to avoid blind signing
        try:
            builder = P2PTradeTransactionBuilder()
            # Derive buyer address from signed AppCall sender
            buyer_addr = algo_encoding.encode_address(user_dict['txn'].get('snd')) if user_dict.get('txn', {}).get('snd') else None
            sp = _extract_params(user_dict)
            res = builder.build_mark_paid(buyer_addr, trade_id, payment_ref, params=sp)
            if not res.success:
                return cls(success=False, error=res.error)
            expected = res.sponsor_transactions or []
            if not expected or len(expected) != 1:
                logger.error(f'[P2P MarkPaid] Unexpected sponsor transaction set: len={len(expected)} expected={expected}')
                return cls(success=False, error=f'Unexpected sponsor transaction set: len={len(expected)}')

            # Require client payload to match canonical sponsor txn
            try:
                provided = [json.loads(s) if isinstance(s, str) else s for s in sponsor_transactions or []]
            except Exception:
                provided = []
            if not provided or provided[0].get('txn') != expected[0].get('txn') or int(provided[0].get('index')) != int(expected[0].get('index')):
                return cls(success=False, error='Sponsor transaction mismatch; please re-run prepare')

            b = base64.b64decode(expected[0].get('txn'))
            tx = transaction.Transaction.undictify(msgpack.unpackb(b, raw=False))
            stx0 = SPONSOR_SIGNER.sign_transaction(tx)
            user_stx = transaction.SignedTransaction.undictify(user_dict)
            txid = algod_client.send_transactions([stx0, user_stx])
            # Do not wait; respond immediately. Celery will confirm and extend expiry/notify.
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

        algod_client = get_algod_client()
        # Decode seller-signed app call
        try:
            user_signed = _b64_to_bytes(signed_user_txn)
            user_dict = msgpack.unpackb(user_signed, raw=False)
            if user_dict.get('txn', {}).get('type') != 'appl':
                return cls(success=False, error='Signed transaction is not an AppCall')
        except Exception as e:
            return cls(success=False, error=f'Invalid signed AppCall: {e}')

        # Rebuild sponsor txn deterministically to avoid blind signing
        try:
            builder = P2PTradeTransactionBuilder()
            seller_addr = algo_encoding.encode_address(user_dict['txn'].get('snd')) if user_dict.get('txn', {}).get('snd') else None
            sp = _extract_params(user_dict)
            res = builder.build_confirm_received(seller_addr, trade_id, params=sp)
            if not res.success:
                return cls(success=False, error=res.error)
            expected = res.sponsor_transactions or []
            if not expected or len(expected) != 1:
                logger.error(f'[P2P ConfirmReceived] Unexpected sponsor transaction set: len={len(expected)} expected={expected}')
                return cls(success=False, error=f'Unexpected sponsor transaction set: len={len(expected)}')

            try:
                provided = [json.loads(s) if isinstance(s, str) else s for s in sponsor_transactions or []]
            except Exception:
                provided = []
            if not provided or provided[0].get('txn') != expected[0].get('txn') or int(provided[0].get('index')) != int(expected[0].get('index')):
                return cls(success=False, error='Sponsor transaction mismatch; please re-run prepare')

            b = base64.b64decode(expected[0].get('txn'))
            tx = transaction.Transaction.undictify(msgpack.unpackb(b, raw=False))
            stx0 = SPONSOR_SIGNER.sign_transaction(tx)
            user_stx = transaction.SignedTransaction.undictify(user_dict)
            txid = algod_client.send_transactions([stx0, user_stx])
            # Do not wait for confirmation. Record tx hash for Celery to confirm, respond immediately.
            ref_txid = user_stx.get_txid()
            try:
                trade = P2PTrade.objects.filter(id=trade_id).select_related('escrow').first()
                if trade and getattr(trade, 'escrow', None):
                    escrow = trade.escrow
                    escrow.release_transaction_hash = ref_txid
                    # Hint Celery about the nature of release
                    if not escrow.release_type:
                        escrow.release_type = 'NORMAL'
                    if not escrow.release_amount:
                        escrow.release_amount = escrow.escrow_amount
                    escrow.save(update_fields=['release_transaction_hash', 'release_type', 'release_amount', 'updated_at'])
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
            algod_client_pref = get_algod_client()
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

        algod_client = get_algod_client()
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
            buyer_addr = algo_encoding.encode_address(user_dict['txn'].get('snd')) if user_dict.get('txn', {}).get('snd') else None
            builder = P2PTradeTransactionBuilder()
            # Rebuild the same (buyer-signed) group used during prepare to verify sponsor txn
            # Use params from user txn to ensure validity window matches
            sp = _extract_params(user_dict)
            res = builder.build_accept_trade_user(buyer_addr, trade_id, params=sp)
            if not res.success:
                return cls(success=False, error=res.error)
            expected = res.sponsor_transactions or []
            if not expected or len(expected) != 1:
                logger.error(f'[P2P SubmitAccept] Unexpected sponsor transaction set: len={len(expected)} expected={expected}')
                return cls(success=False, error=f'Unexpected sponsor transaction set: len={len(expected)}')

            try:
                provided = [json.loads(s) if isinstance(s, str) else s for s in sponsor_transactions or []]
            except Exception:
                provided = []
            if not provided or int(provided[0].get('index')) != int(expected[0].get('index')):
                # We relax the strict txn check to allow client to update fee/group_id
                return cls(success=False, error='Sponsor transaction mismatch (index); please re-run prepare')

            b = base64.b64decode(expected[0].get('txn'))
            stx0 = SPONSOR_SIGNER.sign_transaction(transaction.Transaction.undictify(msgpack.unpackb(b, raw=False)))
            user_stx = transaction.SignedTransaction.undictify(user_dict)

            txid = algod_client.send_transactions([stx0, user_stx])
            # Wait for confirmation to avoid race condition with subsequent mark_paid
            try:
                transaction.wait_for_confirmation(algod_client, txid, 4)
            except Exception as e:
                logger.warning(f'[P2P SubmitAccept] Wait confirmation warning: {e}')
            
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
            algod_client_pref = get_algod_client()
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
                env_sponsor_from_mn = SPONSOR_SIGNER.address
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
                    logger.error(f'[P2P Debug] Box content dump: len={len(raw)} raw_b64={_b64.b64encode(raw).decode()}')
                    return cls(success=False, error=f'El intercambio todavía no está ACTIVO en cadena (status={status_hex}). Espera unos segundos e inténtalo de nuevo.')
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
            algod_client_pref = get_algod_client()
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

        algod_client = get_algod_client()
        try:
            user_signed = _b64_to_bytes(signed_user_txn)
            user_dict = msgpack.unpackb(user_signed, raw=False)
            if user_dict.get('txn', {}).get('type') != 'appl':
                return cls(success=False, error='Signed transaction is not an AppCall')
        except Exception as e:
            return cls(success=False, error=f'Invalid signed AppCall: {e}')

        try:
            SPONSOR_SIGNER.assert_matches_address(getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', None))

            builder = P2PTradeTransactionBuilder()
            caller_addr = algo_encoding.encode_address(user_dict['txn'].get('snd')) if user_dict.get('txn', {}).get('snd') else None
            sp = _extract_params(user_dict)
            res = builder.build_cancel_trade(caller_addr, trade_id, params=sp)
            if not res.success:
                return cls(success=False, error=res.error)
            expected = res.sponsor_transactions or []
            if not expected or len(expected) != 1:
                logger.error(f'[P2P Cancel] Unexpected sponsor transaction set: len={len(expected)} expected={expected}')
                return cls(success=False, error=f'Unexpected sponsor transaction set: len={len(expected)}')

            try:
                provided = [json.loads(s) if isinstance(s, str) else s for s in sponsor_transactions or []]
            except Exception:
                provided = []
            if not provided or provided[0].get('txn') != expected[0].get('txn') or int(provided[0].get('index')) != int(expected[0].get('index')):
                return cls(success=False, error='Sponsor transaction mismatch; please re-run prepare')

            b = base64.b64decode(expected[0].get('txn'))
            tx = transaction.Transaction.undictify(msgpack.unpackb(b, raw=False))
            stx0 = SPONSOR_SIGNER.sign_transaction(tx)
            user_stx = transaction.SignedTransaction.undictify(user_dict)
            txid = algod_client.send_transactions([stx0, user_stx])
            # Return immediately; background scanner/celery will confirm and finalize
            ref_txid = user_stx.get_txid()
        except Exception as e:
            return cls(success=False, error=str(e))

        # Optimistic bookkeeping: record release tx hash and system message
        try:
            trade = P2PTrade.objects.filter(id=trade_id).select_related('escrow').first()
            if trade:
                try:
                    escrow = getattr(trade, 'escrow', None)
                    if escrow and escrow.is_escrowed and not escrow.is_released:
                        escrow.release_transaction_hash = ref_txid
                        # Hint to scanner this is a refund to seller
                        if not escrow.release_type:
                            escrow.release_type = 'REFUND'
                        escrow.save(update_fields=['release_transaction_hash', 'release_type', 'updated_at'])
                except Exception:
                    pass

                # System chat message for visibility
                try:
                    from p2p_exchange.models import P2PMessage
                    P2PMessage.objects.create(
                        trade=trade,
                        message='♻️ Recuperación enviada; esperando confirmación en cadena',
                        sender_type='system',
                        message_type='system',
                    )
                except Exception:
                    pass
        except Exception:
            pass

        return cls(success=True, txid=ref_txid)

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

        algod_client = get_algod_client()

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
            builder = P2PTradeTransactionBuilder()
            opener_addr = algo_encoding.encode_address(user_dict['txn'].get('snd')) if user_dict.get('txn', {}).get('snd') else None
            sp = _extract_params(user_dict)
            res = builder.build_open_dispute(opener_addr, trade_id, reason or '', params=sp)
            if not res.success:
                return cls(success=False, error=res.error)
            expected = res.sponsor_transactions or []
            if not expected or len(expected) != 1:
                logger.error(f'[P2P OpenDispute] Unexpected sponsor transaction set: len={len(expected)} expected={expected}')
                return cls(success=False, error=f'Unexpected sponsor transaction set: len={len(expected)}')

            try:
                provided = [json.loads(s) if isinstance(s, str) else s for s in (sponsor_transactions or [])]
            except Exception:
                provided = []
            if not provided or provided[0].get('txn') != expected[0].get('txn') or int(provided[0].get('index')) != int(expected[0].get('index')):
                return cls(success=False, error='Sponsor transaction mismatch; please re-run prepare')

            b = base64.b64decode(expected[0].get('txn'))
            tx = transaction.Transaction.undictify(msgpack.unpackb(b, raw=False))
            stx0 = SPONSOR_SIGNER.sign_transaction(tx)
            user_stx = transaction.SignedTransaction.undictify(user_dict)
            txid = algod_client.send_transactions([stx0, user_stx])
            ref_txid = user_stx.get_txid()

            # Enqueue background confirmation via Celery and return immediately
            try:
                from blockchain.tasks import confirm_p2p_open_dispute
                opener_user_id = getattr(user, 'id', None)
                # Try to capture business context (if any)
                opener_business_id = None
                try:
                    from users.jwt_context import get_jwt_business_context_with_validation
                    jwt_ctx = get_jwt_business_context_with_validation(info, required_permission=None) or {}
                    if jwt_ctx.get('account_type') == 'business':
                        opener_business_id = jwt_ctx.get('business_id')
                except Exception:
                    opener_business_id = None
                confirm_p2p_open_dispute.delay(
                    trade_id=str(trade_id),
                    txid=ref_txid,
                    opener_user_id=opener_user_id,
                    opener_business_id=opener_business_id,
                    reason=(reason or ''),
                )
            except Exception:
                # If enqueue fails, we still return txid; scanner may pick it up later
                pass

            # Optimistic local update so the UI reflects dispute immediately
            try:
                trade = P2PTrade.objects.filter(id=trade_id).select_related('buyer_user', 'seller_user', 'buyer_business', 'seller_business').first()
                if trade and trade.status not in ('DISPUTED', 'CANCELLED', 'COMPLETED'):
                    from django.utils import timezone as dj_tz
                    trade.status = 'DISPUTED'
                    trade.updated_at = dj_tz.now()
                    trade.save(update_fields=['status', 'updated_at'])

                # Ensure dispute record exists for evidence uploads
                if trade:
                    from p2p_exchange.models import P2PDispute
                    exists = False
                    try:
                        _ = trade.dispute_details
                        exists = True
                    except Exception:
                        exists = False
                    if not exists:
                        from users.jwt_context import get_jwt_business_context_with_validation
                        dispute_kwargs = {
                            'trade': trade,
                            'reason': (reason or 'Dispute opened').strip(),
                            'priority': 2,
                            'status': 'UNDER_REVIEW',
                        }
                        try:
                            jwt_context = get_jwt_business_context_with_validation(info, required_permission=None) or {}
                            if jwt_context.get('account_type') == 'business' and jwt_context.get('business_id'):
                                if trade.buyer_business_id == jwt_context.get('business_id'):
                                    dispute_kwargs['initiator_business'] = trade.buyer_business
                                elif trade.seller_business_id == jwt_context.get('business_id'):
                                    dispute_kwargs['initiator_business'] = trade.seller_business
                                else:
                                    dispute_kwargs['initiator_user'] = user
                            else:
                                dispute_kwargs['initiator_user'] = user
                        except Exception:
                            dispute_kwargs['initiator_user'] = user
                        try:
                            P2PDispute.objects.create(**dispute_kwargs)
                        except Exception:
                            pass

                # System message into chat
                try:
                    from p2p_exchange.models import P2PMessage
                    if trade:
                        P2PMessage.objects.create(
                            trade=trade,
                            message='🚩 Disputa enviada a cadena',
                            sender_type='system',
                            message_type='system',
                        )
                except Exception:
                    pass
            except Exception:
                # Non-fatal if local DB bookkeeping fails
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

        algod_client = get_algod_client()

        try:
            user_signed = _b64_to_bytes(signed_user_txn)
            user_dict = msgpack.unpackb(user_signed, raw=False)
            if user_dict.get('txn', {}).get('type') != 'appl':
                return cls(success=False, error='Signed transaction is not an AppCall')
            # Extract admin sender and winner address from txn accounts
            admin_addr = algo_encoding.encode_address(user_dict['txn'].get('snd')) if user_dict.get('txn', {}).get('snd') else None
            winner_addr = None
            try:
                apat = user_dict.get('txn', {}).get('apat') or []
                if len(apat) >= 2:
                    winner_addr = algo_encoding.encode_address(apat[1])
            except Exception:
                winner_addr = None
            if not admin_addr or not winner_addr:
                return cls(success=False, error='Cannot determine admin or winner address from signed transaction')
        except Exception as e:
            return cls(success=False, error=f'Invalid signed AppCall: {e}')

        try:
            builder = P2PTradeTransactionBuilder()
            res = builder.build_resolve_dispute(admin_addr, trade_id, winner_addr)
            if not res.success:
                return cls(success=False, error=res.error)
            expected = res.sponsor_transactions or []
            if not expected or len(expected) != 1:
                return cls(success=False, error='Unexpected sponsor transaction set')

            try:
                provided = [json.loads(s) if isinstance(s, str) else s for s in (sponsor_transactions or [])]
            except Exception:
                provided = []
            if not provided or provided[0].get('txn') != expected[0].get('txn') or int(provided[0].get('index')) != int(expected[0].get('index')):
                return cls(success=False, error='Sponsor transaction mismatch; please re-run prepare')

            b = base64.b64decode(expected[0].get('txn'))
            tx = transaction.Transaction.undictify(msgpack.unpackb(b, raw=False))
            stx0 = SPONSOR_SIGNER.sign_transaction(tx)
            user_stx = transaction.SignedTransaction.undictify(user_dict)
            txid = algod_client.send_transactions([stx0, user_stx])
            ref_txid = user_stx.get_txid()
            # Do not wait for confirmation; record tx and return. Celery will confirm and update state/notifications.
            try:
                trade = P2PTrade.objects.filter(id=trade_id).select_related('escrow').first()
                if trade and getattr(trade, 'escrow', None):
                    escrow = trade.escrow
                    escrow.release_transaction_hash = ref_txid
                    if not escrow.release_type:
                        escrow.release_type = 'DISPUTE_RELEASE'
                    if not escrow.release_amount:
                        escrow.release_amount = escrow.escrow_amount
                    escrow.save(update_fields=['release_transaction_hash', 'release_type', 'release_amount', 'updated_at'])
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

        try:
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

            # Admin sender address (KMS signer)
            admin_addr = SPONSOR_SIGNER.address

            # Build group
            builder = P2PTradeTransactionBuilder()
            res = builder.build_resolve_dispute(admin_addr, trade_id, winner_addr)
            if not res.success:
                return cls(success=False, error=res.error)

            # Sign sponsor txn
            parsed = [json.loads(s) if isinstance(s, str) else s for s in (res.sponsor_transactions or [])]
            if not parsed:
                return cls(success=False, error='Missing sponsor transaction from builder')

            # Undictify and sign
            sponsor_b = base64.b64decode(parsed[0].get('txn'))
            sponsor_tx = transaction.Transaction.undictify(msgpack.unpackb(sponsor_b, raw=False))
            stx0 = SPONSOR_SIGNER.sign_transaction(sponsor_tx)

            # User/admin appcall: res.transactions_to_sign[0]
            if not res.transactions_to_sign:
                return cls(success=False, error='Missing admin AppCall from builder')
            appcall_b64 = (res.transactions_to_sign[0] or {}).get('txn')
            if not appcall_b64:
                return cls(success=False, error='Missing admin AppCall payload')
            appcall_tx = transaction.Transaction.undictify(msgpack.unpackb(base64.b64decode(appcall_b64), raw=False))
            stx1 = SPONSOR_SIGNER.sign_transaction(appcall_tx)

            algod_client = get_algod_client()
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
# Removed HTTP exposure for cancel (recuperar): use WebSocket prepare/submit only
# P2PTradeMutations.cancel_p2p_trade = CancelP2PTrade.Field()
# P2PTradePrepareMutations.prepare_p2p_cancel = PrepareP2PCancel.Field()
P2PTradePrepareMutations.prepare_p2p_open_dispute = PrepareP2POpenDispute.Field()
P2PTradeMutations.submit_p2p_open_dispute = SubmitP2POpenDispute.Field()
P2PTradePrepareMutations.prepare_p2p_resolve_dispute = PrepareP2PResolveDispute.Field()
P2PTradeMutations.submit_p2p_resolve_dispute = SubmitP2PResolveDispute.Field()
P2PTradeMutations.resolve_p2p_dispute_onchain = ResolveP2pDisputeOnchain.Field()
