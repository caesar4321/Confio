"""
Invite & Send GraphQL Mutations

Server builds fully sponsored groups for invite creation.
Client signs only the AXFER; server signs sponsor txns and submits.
"""

from blockchain.algorand_config import get_algod_client

import base64
import graphene
import logging
from typing import List, Optional

from django.conf import settings
from algosdk.v2client import algod
from algosdk import encoding as algo_encoding
from algosdk import mnemonic
from algosdk import transaction
import msgpack
import json
import base64 as _b64

from .invite_send_transaction_builder import InviteSendTransactionBuilder
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer,
    TransactionWithSigner,
    AccountTransactionSigner,
)
from algosdk import transaction as _txn
from send.models import SendTransaction
from django.utils import timezone
from decimal import Decimal
from users.jwt_context import get_jwt_business_context_with_validation
from users.models import Account

logger = logging.getLogger(__name__)


class InviteUserTxnType(graphene.ObjectType):
    txn = graphene.String()
    group_id = graphene.String()
    first = graphene.Int()
    last = graphene.Int()
    gh = graphene.String()
    gen = graphene.String()


class SponsorTxnType(graphene.ObjectType):
    txn = graphene.String()
    index = graphene.Int()


class PrepareInviteForPhone(graphene.Mutation):
    class Arguments:
        phone = graphene.String(required=True)
        phone_country = graphene.String(required=False)
        amount = graphene.Float(required=True)
        asset_type = graphene.String(required=False, default_value='CUSD')
        message = graphene.String(required=False)

    success = graphene.Boolean()
    error = graphene.String()
    user_transaction = graphene.Field(InviteUserTxnType)
    sponsor_transactions = graphene.List(SponsorTxnType)
    group_id = graphene.String()
    invitation_id = graphene.String()

    @classmethod
    def mutate(cls, root, info, phone, amount, phone_country=None, asset_type='CUSD', message=None):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, error='Not authenticated')

        # Resolve sender account from JWT
        jwt_ctx = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_ctx:
            return cls(success=False, error='Invalid JWT context')

        acct = Account.objects.filter(user_id=jwt_ctx['user_id'], account_type=jwt_ctx['account_type'], account_index=jwt_ctx.get('account_index', 0), deleted_at__isnull=True).first()
        if not acct or not acct.algorand_address:
            return cls(success=False, error='User Algorand address not found')

        builder = InviteSendTransactionBuilder()
        asset_type = (asset_type or 'CUSD').upper()
        if asset_type == 'CUSD':
            asset_id = builder.cusd_asset_id
        elif asset_type == 'CONFIO':
            asset_id = builder.confio_asset_id
        else:
            return cls(success=False, error='Unsupported asset type')

        # Normalize phone for DB persistence; do not enforce single-invite per phone on-chain
        client = get_algod_client()
        phone_key_canonical = builder.normalize_phone(phone, phone_country)
        if not phone_key_canonical or ':' not in phone_key_canonical:
            return cls(success=False, error='Proporciona un número en formato internacional (+CC ...) o un país válido para normalizar el teléfono.')

        amount_u = int(amount * 1_000_000)

        # Insufficient balance check for inviter before building
        try:
            client = get_algod_client()
            asset_info = client.asset_info(asset_id)
            decimals = int(asset_info.get('params', {}).get('decimals', 6) or 6)
            acct_info = client.account_asset_info(acct.algorand_address, asset_id)
            current_amount = int(acct_info.get('asset-holding', {}).get('amount', 0))
            if current_amount < amount_u:
                available = current_amount / (10 ** decimals)
                needed = amount_u / (10 ** decimals)
                return cls(success=False, error=f'Saldo insuficiente de {asset_type}. Disponible: {available:.6f}, requerido: {needed:.6f}')
        except Exception:
            # If balance lookup fails, continue; on-chain will enforce at submit
            pass
        # Generate a unique invitation id by adding a short random suffix
        try:
            import secrets
            base_id = builder.make_invitation_id(phone_key_canonical)
            suffix = secrets.token_hex(4)  # 8 chars
            # Ensure both invitation_id and receipt key "r:"+invitation_id fit in Algorand box key (<=64 bytes)
            # => len(invitation_id) must be <= 62
            max_inv_id_len = 62
            trim_len = max_inv_id_len - (1 + len(suffix))
            if trim_len < 1:
                trim_len = 1
            safe_base = base_id[:trim_len]
            unique_id = f"{safe_base}:{suffix}"
        except Exception:
            unique_id = builder.make_invitation_id(phone_key_canonical)

        res = builder.build_create_invitation(
            inviter_address=acct.algorand_address,
            asset_id=asset_id,
            amount=amount_u,
            phone_number=phone,
            phone_country=phone_country,
            message=message or '',
            invitation_id_override=unique_id
        )
        if not res.success:
            return cls(success=False, error=res.error)

        # Build user transaction payload (AXFER at index 2)
        try:
            from algosdk import encoding as algo_encoding
            import msgpack
            # Extract first (and only) user txn
            if not res.transactions_to_sign or len(res.transactions_to_sign) == 0:
                return cls(success=False, error='Builder did not return user transaction')
            user_entry = res.transactions_to_sign[0]
            txn_b64 = user_entry.get('txn')
            # Derive chain params from the txn
            b = _b64.b64decode(txn_b64)
            d = msgpack.unpackb(b, raw=False)
            fv = d.get('fv')
            lv = d.get('lv')
            gh = d.get('gh')  # bytes
            gen = d.get('gen')
            gid = d.get('grp')  # bytes
            user_txn = InviteUserTxnType(
                txn=txn_b64,
                group_id=_b64.b64encode(gid).decode() if gid else '',
                first=fv or 0,
                last=lv or 0,
                gh=_b64.b64encode(gh).decode() if gh else '',
                gen=gen or ''
            )
        except Exception as e:
            return cls(success=False, error=f'Failed to package user txn: {e}')

        # Persist/Upsert an invitation record for admin visibility
        try:
            from algosdk.logic import get_application_address
            app_addr = get_application_address(builder.app_id)
            token = 'CUSD' if asset_id == builder.cusd_asset_id else 'CONFIO'
            stx, _ = SendTransaction.objects.update_or_create(
                idempotency_key=res.invitation_id,
                defaults={
                    'sender_user': user,
                    'sender_type': 'user',
                    'recipient_type': 'external',
                    'sender_display_name': user.get_full_name() or user.username,
                    'recipient_display_name': phone,
                    'sender_address': acct.algorand_address,
                    'recipient_address': app_addr,
                    'recipient_phone': phone,
                    'amount': Decimal(str(amount)),
                    'token_type': token,
                    'memo': message or '',
                    'status': 'PENDING',
                    'is_invitation': True,
                    'invitation_claimed': False,
                    'invitation_reverted': False,
                    'invitation_expires_at': timezone.now() + timezone.timedelta(days=7),
                }
            )
            # Also persist PhoneInvite for easier ops/admin tracking
            try:
                from send.models import PhoneInvite
                # Persist canonical phone key derived by builder (handles ISO or E.164)
                phone_key = phone_key_canonical
                PhoneInvite.objects.update_or_create(
                    invitation_id=res.invitation_id,
                    defaults={
                        'phone_key': phone_key,
                        'phone_country': (phone_country or '')[:2],
                        'phone_number': ''.join(ch for ch in (phone or '') if ch.isdigit()),
                        'inviter_user': user,
                        'send_transaction': stx,
                        'amount': Decimal(str(amount)),
                        'token_type': token,
                        'message': message or '',
                        'status': 'pending',
                        'expires_at': timezone.now() + timezone.timedelta(days=7),
                    }
                )
            except Exception as e:
                logger.warning(f'[InviteSend] Could not persist PhoneInvite: {e}')
        except Exception as e:
            logger.warning(f'[InviteSend] Could not persist SendTransaction invitation: {e}')

        # Notify inviter that invitation was created/sent
        try:
            from notifications.utils import create_notification
            from notifications.models import NotificationType as NotificationTypeChoices
            display_amount = f"{amount} {asset_type}"
            create_notification(
                user=user,
                notification_type=NotificationTypeChoices.SEND_INVITATION_SENT,
                title='Invitación enviada',
                message=f"Tu invitación para {phone} está activa por {display_amount}",
                data={
                    'transaction_type': 'send',
                    'amount': f'-{amount}',
                    'token_type': asset_type,
                    'recipient_phone': phone,
                    'invitation_id': res.invitation_id,
                    'status': 'pending',
                    'isInvitedFriend': True,
                },
                related_object_type='SendTransaction',
                related_object_id=str(stx.id) if 'stx' in locals() and stx else None,
                action_url=f"confio://transaction/{stx.id}" if 'stx' in locals() and stx else None
            )
        except Exception as e:
            logger.warning(f'[InviteSend] Could not create invitation sent notification: {e}')

        return cls(
            success=True,
            user_transaction=user_txn,
            sponsor_transactions=[SponsorTxnType(txn=tx['txn'], index=tx['index']) for tx in (res.sponsor_transactions or [])],
            group_id=res.group_id,
            invitation_id=res.invitation_id,
        )


class SubmitInviteForPhone(graphene.Mutation):
    class Arguments:
        signed_user_txn = graphene.String(required=True, description='Signed AXFER from inviter (base64 msgpack)')
        sponsor_transactions = graphene.List(graphene.JSONString, required=True, description='List of sponsor txns as JSON strings with fields {txn, index}')
        invitation_id = graphene.String(required=True)
        message = graphene.String(required=False)

    success = graphene.Boolean()
    error = graphene.String()
    txid = graphene.String()

    @classmethod
    def mutate(cls, root, info, signed_user_txn: str, sponsor_transactions: list[str], invitation_id: str, message: Optional[str] = ''):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, error='Not authenticated')

        # Safety: on-chain claim now requires the recipient to self-claim; disable server-mediated claim path
        return cls(success=False, error='Claim must be performed directly by the recipient wallet')

        algod_client = get_algod_client()

        # Base64 decode tolerant of urlsafe and missing padding
        def _b64_to_bytes(s: str) -> bytes:
            if not isinstance(s, str):
                raise ValueError('Expected base64 string for transaction payload')
            ss = s.strip().replace('-', '+').replace('_', '/')
            # Add padding if missing
            pad = (-len(ss)) % 4
            if pad:
                ss += '=' * pad
            return _b64.b64decode(ss)
        # Decode signed user axfer and derive chain params and group
        try:
            logger.info('[SubmitInviteForPhone] signed_user_txn len=%s mod4=%s head=%s', len(signed_user_txn or ''), (len(signed_user_txn or '') % 4), (signed_user_txn or '')[:16])
            user_signed = _b64_to_bytes(signed_user_txn)
            logger.info('[SubmitInviteForPhone] Decoded user_signed bytes len=%s', len(user_signed))
            user_dict = msgpack.unpackb(user_signed, raw=False)
            if not isinstance(user_dict, dict) or 'txn' not in user_dict:
                return cls(success=False, error='Invalid signed user transaction payload')
            txn_d = user_dict['txn']
            if txn_d.get('type') != 'axfer':
                return cls(success=False, error='Signed transaction is not an AXFER')
            inviter_snd = txn_d.get('snd')  # bytes
            asset_id = txn_d.get('xaid')
            amount = txn_d.get('aamt')
            fv = txn_d.get('fv')
            lv = txn_d.get('lv')
            gh = txn_d.get('gh')
            gen = txn_d.get('gen')
            grp = txn_d.get('grp')
            if not all([inviter_snd, asset_id, amount, fv, lv, gh, gen, grp]):
                return cls(success=False, error='Signed AXFER missing required fields')
            inviter_addr = algo_encoding.encode_address(inviter_snd)
        except Exception as e:
            return cls(success=False, error=f'Invalid signed AXFER: {e}')

        # Sign sponsor transactions from pre-built payloads provided back by client (no rebuild)
        try:
            # Parse sponsor transactions (list of JSON strings with txn/index)
            if not sponsor_transactions or len(sponsor_transactions) == 0:
                return cls(success=False, error='Missing sponsor transactions')
            parsed = []
            for s in sponsor_transactions:
                try:
                    parsed.append(json.loads(s) if isinstance(s, str) else s)
                except Exception:
                    return cls(success=False, error='Invalid sponsor transaction payload format')

            # Build SignedTransaction objects in their original indices
            sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
            if not sponsor_mn:
                return cls(success=False, error='Server missing ALGORAND_SPONSOR_MNEMONIC')
            sk = mnemonic.to_private_key(sponsor_mn)

            # Strictly validate sponsor txns against expected pattern to avoid blind signing
            builder = InviteSendTransactionBuilder()
            expected_mbr = builder._box_mbr_cost(len(invitation_id.encode()), len((message or '').encode()))
            expected_addr = builder.sponsor_address
            expected_rcv = builder.app_address

            # Debug app global sponsor address
            try:
                app_id = getattr(settings, 'ALGORAND_INVITE_SEND_APP_ID')
                app_info = algod_client.application_info(app_id)
                gstate = app_info.get('params', {}).get('global-state', [])
                def _get_bytes(key: str):
                    import base64 as _b
                    for kv in gstate:
                        if _b.b64decode(kv.get('key')).decode() == key:
                            v = kv.get('value', {})
                            if v.get('type') == 1:  # bytes
                                return v.get('bytes')
                    return None
                sponsor_b64 = _get_bytes('sponsor_address')
                if sponsor_b64:
                    from algosdk.encoding import encode_address
                    onchain_sponsor = encode_address(_b64.b64decode(sponsor_b64))
                    logger.info('[SubmitInviteForPhone] On-chain sponsor_address: %s', onchain_sponsor)
                else:
                    logger.info('[SubmitInviteForPhone] On-chain sponsor_address not set')
            except Exception as e:
                logger.info('[SubmitInviteForPhone] Could not read app global sponsor_address: %s', e)

            # Decode sponsor tx dicts for sanity logging
            try:
                for entry in parsed:
                    idx = entry.get('index')
                    b = _b64.b64decode(entry.get('txn'))
                    txd = msgpack.unpackb(b, raw=False)
                    t = txd.get('type')
                    if t == 'pay':
                        from_addr = algo_encoding.encode_address(txd.get('snd')) if txd.get('snd') else 'na'
                        recv = algo_encoding.encode_address(txd.get('rcv')) if txd.get('rcv') else 'na'
                        amt = txd.get('amt')
                        logger.info('[SubmitInviteForPhone] Sponsor TX idx=%s type=pay from=%s to=%s amt=%s', idx, from_addr, recv, amt)
                    elif t == 'appl':
                        from_addr = algo_encoding.encode_address(txd.get('snd')) if txd.get('snd') else 'na'
                        accs = [algo_encoding.encode_address(a) for a in (txd.get('apat') or [])]
                        logger.info('[SubmitInviteForPhone] Sponsor TX idx=%s type=appl from=%s accounts=%s', idx, from_addr, accs)
            except Exception:
                pass

            signed_by_index: dict[int, transaction.SignedTransaction] = {}
            sponsor_amounts = []
            for entry in parsed:
                b = _b64.b64decode(entry.get('txn'))
                tx_d = msgpack.unpackb(b, raw=False)
                # Validate before signing
                if tx_d.get('type') != 'pay':
                    return cls(success=False, error='Unexpected sponsor txn type (only payment allowed)')
                if tx_d.get('snd') != algo_encoding.decode_address(expected_addr):
                    return cls(success=False, error='Sponsor txn sender mismatch')
                if tx_d.get('rcv') != algo_encoding.decode_address(expected_rcv):
                    return cls(success=False, error='Sponsor txn receiver mismatch')
                if tx_d.get('rekey'):
                    return cls(success=False, error='Sponsor txn must not rekey')
                if tx_d.get('close'):
                    return cls(success=False, error='Sponsor txn must not close out')
                amt = tx_d.get('amt')
                sponsor_amounts.append(int(amt or 0))
                tx = transaction.Transaction.undictify(tx_d)
                stx = tx.sign(sk)
                signed_by_index[int(entry.get('index'))] = stx

            # Expect exactly two sponsor payments: 0-fee bump and MBR funding
            if sorted(sponsor_amounts) != sorted([0, expected_mbr]):
                return cls(success=False, error='Sponsor txn amounts do not match expected pattern (0 and MBR)')

            # Determine user txn index as the missing slot
            all_idx = set(signed_by_index.keys())
            # Our group has 4 txns total
            user_index = next(i for i in range(4) if i not in all_idx)
        except Exception as e:
            return cls(success=False, error=f'Failed to sign sponsor txns: {e}')

        # Submit group (concatenate raw signed bytes explicitly)
        try:
            def _stx_bytes(stx: transaction.SignedTransaction) -> bytes:
                # Use SDK's canonical encoder, then decode to raw bytes
                b64 = algo_encoding.msgpack_encode(stx)
                return _b64.b64decode(b64)

            # Prefer SDK-managed submission with typed SignedTransaction list to avoid encoding mismatches
            try:
                # Rebuild SignedTransaction from previously unpacked dict
                user_stx = transaction.SignedTransaction.undictify(user_dict)
                # Assemble ordered group by index
                ordered: list[transaction.SignedTransaction] = []
                # Log user AXFER summary
                try:
                    txd = user_dict.get('txn', {})
                    from_addr = algo_encoding.encode_address(txd.get('snd')) if txd.get('snd') else 'na'
                    recv = algo_encoding.encode_address(txd.get('arcv')) if txd.get('arcv') else 'na'
                    amt = txd.get('aamt')
                    xaid = txd.get('xaid')
                    logger.info('[SubmitInviteForPhone] User AXFER from=%s to=%s asset=%s amt=%s', from_addr, recv, xaid, amt)
                except Exception:
                    pass
                for i in range(4):
                    if i == user_index:
                        ordered.append(user_stx)
                    else:
                        ordered.append(signed_by_index[i])
                txid = algod_client.send_transactions(ordered)
                logger.info('[SubmitInviteForPhone] send_transactions returned: %s', txid)
            except Exception as e:
                logger.exception('[SubmitInviteForPhone] send_transactions failed: %r', e)
                return cls(success=False, error=str(e))

            # Prefer the ApplicationCall txid for confirmation reference (index 3)
            ref_txid = ordered[3].get_txid()
            try:
                transaction.wait_for_confirmation(algod_client, ref_txid, 8)
            except Exception as e:
                logger.exception('[SubmitInviteForPhone] wait_for_confirmation failed for %s: %r', ref_txid, e)
                return cls(success=False, error=str(e))
            # Update persisted SendTransaction record
            try:
                SendTransaction.objects.filter(idempotency_key=invitation_id).update(
                    status='CONFIRMED',
                    transaction_hash=ref_txid
                )
            except Exception as e:
                logger.warning(f'[InviteSend] Could not update SendTransaction invitation {invitation_id}: {e}')
            return cls(success=True, txid=ref_txid)
        except Exception as e:
            logger.error(f"Invite submit error: {e}")
            return cls(success=False, error=str(e))


class InviteSendMutations(graphene.ObjectType):
    prepare_invite_for_phone = PrepareInviteForPhone.Field()
    submit_invite_for_phone = SubmitInviteForPhone.Field()


class ClaimInviteForPhone(graphene.Mutation):
    class Arguments:
        recipient_address = graphene.String(required=True)
        # Backward-compatible: phone and phone_country are optional now
        phone = graphene.String(required=False)
        phone_country = graphene.String(required=False)
        # New optional argument: allow direct claim by invitation id
        invitation_id = graphene.String(required=False)

    success = graphene.Boolean()
    error = graphene.String()
    txid = graphene.String()

    @classmethod
    def mutate(cls, root, info, recipient_address, phone=None, phone_country=None, invitation_id=None):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, error='Not authenticated')

        # Contract requires Txn.sender == app.state.admin for claim_invitation.
        # Use admin mnemonic; only fall back to sponsor if sponsor == admin on-chain.
        admin_mn = getattr(settings, 'ALGORAND_ADMIN_MNEMONIC', None)
        sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
        algod_client = get_algod_client()
        builder = InviteSendTransactionBuilder()
        contract = builder.contract
        method = next((m for m in contract.methods if m.name == 'claim_invitation'), None)
        if method is None:
            return cls(success=False, error='ABI method claim_invitation not found')

        # Read on-chain admin and sponsor addresses for validation
        onchain_admin_addr = None
        onchain_sponsor_addr = None
        try:
            app_info = algod_client.application_info(builder.app_id)
            gstate = app_info.get('params', {}).get('global-state', [])
            import base64 as _b
            from algosdk.encoding import encode_address
            def _get_bytes(key: str):
                for kv in gstate:
                    try:
                        if _b.b64decode(kv.get('key')).decode() == key:
                            v = kv.get('value', {})
                            if v.get('type') == 1:
                                return _b.b64decode(v.get('bytes'))
                    except Exception:
                        continue
                return None
            admin_b = _get_bytes('admin')
            sponsor_b = _get_bytes('sponsor_address')
            if admin_b:
                onchain_admin_addr = encode_address(admin_b)
            if sponsor_b:
                onchain_sponsor_addr = encode_address(sponsor_b)
            logger.info('[ClaimInviteForPhone] On-chain admin=%s sponsor=%s', onchain_admin_addr, onchain_sponsor_addr)
        except Exception as e:
            logger.warning('[ClaimInviteForPhone] Could not read app globals: %s', e)

        # Choose operator key with strict validation
        operator_mn = None
        operator_label = 'none'
        operator_addr = None
        try:
            from algosdk import account as _acct
            if admin_mn:
                admin_sk = mnemonic.to_private_key(admin_mn)
                operator_addr = _acct.address_from_private_key(admin_sk)
                operator_mn = admin_mn
                operator_label = 'admin'
                if onchain_admin_addr and operator_addr != onchain_admin_addr:
                    logger.warning('[ClaimInviteForPhone] Provided ALGORAND_ADMIN_MNEMONIC address %s does not match on-chain admin %s', operator_addr, onchain_admin_addr)
            elif sponsor_mn:
                # Only use sponsor if it matches on-chain admin (some envs set admin==sponsor)
                sponsor_sk = mnemonic.to_private_key(sponsor_mn)
                sponsor_addr = _acct.address_from_private_key(sponsor_sk)
                if onchain_admin_addr and sponsor_addr != onchain_admin_addr:
                    err = 'Server missing ALGORAND_ADMIN_MNEMONIC. Contract admin is %s; set this mnemonic to enable claiming.' % (onchain_admin_addr or 'unknown')
                    logger.warning('[ClaimInviteForPhone] %s', err)
                    return cls(success=False, error=err)
                operator_mn = sponsor_mn
                operator_label = 'sponsor'
                operator_addr = sponsor_addr
            else:
                logger.warning('[ClaimInviteForPhone] Missing ALGORAND_ADMIN_MNEMONIC and ALGORAND_SPONSOR_MNEMONIC; cannot claim invitation')
                return cls(success=False, error='Server missing admin mnemonic for claiming invitation')
        except Exception as e:
            logger.exception('[ClaimInviteForPhone] Failed to derive operator key: %s', e)
            return cls(success=False, error='Failed to derive operator key for claim')

        # Determine the invitation id to claim
        if not invitation_id:
            # If phone provided, derive from normalized phone (legacy behavior)
            if phone:
                canonical_key = builder.normalize_phone(phone, phone_country)
                if not canonical_key or ':' not in canonical_key:
                    return cls(success=False, error='Proporciona un número en formato internacional (+CC ...) o un país válido para normalizar el teléfono.')
                invitation_id = builder.make_invitation_id(canonical_key)
            else:
                # Resolve invitation for current user's phone strictly via PhoneInvite pending row.
                try:
                    from users.phone_utils import normalize_phone as _norm
                    u = info.context.user
                    user_phone = getattr(u, 'phone_number', None)
                    user_country = getattr(u, 'phone_country', None)
                    phone_key = _norm(user_phone or '', user_country or '')
                    if not phone_key or ':' not in phone_key:
                        return cls(success=False, error='No se pudo resolver tu número de teléfono para reclamar la invitación.')
                    from send.models import PhoneInvite
                    # Support legacy phone_key that duplicated calling code in digits
                    try:
                        cc, local = phone_key.split(':', 1)
                        alt_phone_key = f"{cc}:{cc}{local}"
                    except Exception:
                        alt_phone_key = phone_key
                    inv = PhoneInvite.objects.filter(
                        phone_key=phone_key,
                        status='pending',
                        deleted_at__isnull=True
                    ).order_by('-created_at').first()
                    if not inv:
                        return cls(success=False, error='No se encontró una invitación activa para tu número.')
                    invitation_id = inv.invitation_id
                except Exception as e:
                    logger.exception('[ClaimInviteForPhone] Failed resolving PhoneInvite for user phone: %s', e)
                    return cls(success=False, error='Error interno al resolver la invitación')

        logger.info('[ClaimInviteForPhone] Resolving invitation_id=%s for recipient=%s', invitation_id, recipient_address)
        # Pre-validate invitation id length: receipt key 'r:' + id must be <= 64 bytes
        try:
            if len(invitation_id.encode()) > 62:  # 'r:' adds 2 bytes
                return cls(success=False, error='Invitación inválida: ID demasiado largo para reclamar. Pide al remitente recrearla.')
        except Exception:
            pass
        # Validate invitation exists on-chain
        try:
            _ = algod_client.application_box_by_name(builder.app_id, invitation_id.encode())
        except Exception:
            return cls(success=False, error='No se encontró una invitación activa para este número. Pide al remitente que la cree nuevamente e inténtalo de nuevo.')

        # If receipt box already exists, treat as already-claimed and return success (idempotent)
        try:
            _ = algod_client.application_box_by_name(builder.app_id, ('r:' + invitation_id).encode())
            logger.info('[ClaimInviteForPhone] Receipt box already exists for %s - treating as already claimed', invitation_id)
            # Best-effort DB update for PhoneInvite
            try:
                from send.models import PhoneInvite
                inv = PhoneInvite.objects.filter(invitation_id=invitation_id).first()
                if inv and inv.status != 'claimed':
                    inv.status = 'claimed'
                    inv.claimed_by = user
                    inv.claimed_at = timezone.now()
                    inv.save(update_fields=['status', 'claimed_by', 'claimed_at', 'updated_at'])
            except Exception:
                pass
            return cls(success=True, txid='')
        except Exception:
            pass

        # Pre-check: ensure claim is valid and recipient is opted in to the invitation's asset to avoid TEAL assert
        asset_id_int = None
        inviter_addr_decoded = None
        try:
            box = algod_client.application_box_by_name(builder.app_id, invitation_id.encode())
            import base64 as _b
            raw = _b.b64decode(box['value']['bytes']) if isinstance(box.get('value'), dict) else _b.b64decode(box.get('value', ''))
            # raw layout: inviter(32) | amount(8) | asset_id(8) | created_at(8) | expires_at(8) | flags...
            if len(raw) >= 48:
                # Disallow self-claim: recipient cannot be the original inviter
                try:
                    from algosdk import encoding as _enc
                    inviter_addr = _enc.encode_address(raw[0:32])
                    inviter_addr_decoded = inviter_addr
                    if inviter_addr == recipient_address:
                        return cls(success=False, error='No puedes reclamar una invitación a la misma dirección que la que la envió. Inicia sesión con la cuenta del invitado.')
                except Exception:
                    pass
                asset_id_bytes = raw[40:48]
                asset_id_int = int.from_bytes(asset_id_bytes, 'big')
                try:
                    algod_client.account_asset_info(recipient_address, asset_id_int)
                except Exception:
                    return cls(success=False, error=f'Recipient address must opt in to asset {asset_id_int} before claiming. Please complete asset opt-in and retry.')
        except Exception:
            # If pre-check fails, proceed and let on-chain logic handle; but clearer error helps when available
            pass

        params = algod_client.suggested_params()
        min_fee = getattr(params, 'min_fee', 1000) or 1000

        # Build 2-txn group: fee-bump pay0 (from sponsor), app call (from admin)
        from algosdk import account as _acct
        admin_sk = mnemonic.to_private_key(operator_mn)
        admin_addr = _acct.address_from_private_key(admin_sk)
        logger.info('[ClaimInviteForPhone] Using %s address %s for claim', operator_label, admin_addr)

        # Choose fee-bump payer: on-chain sponsor if available, else configured sponsor, else admin
        fee_payer_addr = onchain_sponsor_addr or getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', None) or admin_addr
        fee_payer_sk = None
        if fee_payer_addr == admin_addr:
            fee_payer_sk = admin_sk
        else:
            if not sponsor_mn:
                logger.warning('[ClaimInviteForPhone] Missing sponsor mnemonic; falling back to admin to pay fee')
                fee_payer_sk = admin_sk
                fee_payer_addr = admin_addr
            else:
                fee_payer_sk = mnemonic.to_private_key(sponsor_mn)
                payer_check = _acct.address_from_private_key(fee_payer_sk)
                if payer_check != fee_payer_addr:
                    logger.warning('[ClaimInviteForPhone] Configured sponsor mnemonic/address mismatch; using mnemonic-derived address %s', payer_check)
                    fee_payer_addr = payer_check

        # Increase fee-bump budget to cover inner transactions in the app call
        # Use a generous multiplier to avoid underpayment across networks
        pay0 = transaction.PaymentTxn(
            sender=fee_payer_addr,
            sp=transaction.SuggestedParams(fee=min_fee * 5, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True),
            receiver=fee_payer_addr,
            amt=0
        )

        atc = AtomicTransactionComposer()
        atc.add_transaction(TransactionWithSigner(pay0, AccountTransactionSigner(fee_payer_sk)))
        # Include required box references: invitation box and receipt box
        # Build explicit BoxReference objects to avoid SDK tuple ambiguity
        # Index 0 refers to the current application (no ForeignApps needed)
        boxes = [
            _txn.BoxReference(0, invitation_id.encode()),
            _txn.BoxReference(0, ('r:' + invitation_id).encode()),
        ]
        # Include foreign asset reference for AssetHolding lookups
        foreign_assets = []
        if asset_id_int:
            foreign_assets = [asset_id_int]

        # Build accounts array including recipient (for AssetHolding) and inviter (for refund inner txn in some AVM patterns)
        accounts_list = [recipient_address]
        if inviter_addr_decoded and inviter_addr_decoded != recipient_address:
            accounts_list.append(inviter_addr_decoded)

        atc.add_method_call(
            app_id=builder.app_id,
            method=method,
            sender=admin_addr,
            sp=transaction.SuggestedParams(fee=0, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True),
            signer=AccountTransactionSigner(admin_sk),
            method_args=[invitation_id, recipient_address],
            accounts=accounts_list,
            foreign_assets=foreign_assets,
            boxes=boxes,
        )

        # Sign and submit
        try:
            res = atc.execute(algod_client, 10)
            txid = res.tx_ids[-1] if res.tx_ids else ''
            # Update PhoneInvite as claimed
            try:
                from send.models import PhoneInvite, SendTransaction
                from notifications.utils import create_notification
                from notifications.models import NotificationType as NotificationTypeChoices
                inv = PhoneInvite.objects.filter(invitation_id=invitation_id).select_related('send_transaction', 'inviter_user').first()
                if inv:
                    inv.status = 'claimed'
                    inv.claimed_by = user
                    inv.claimed_at = timezone.now()
                    inv.claimed_txid = txid
                    inv.save(update_fields=['status', 'claimed_by', 'claimed_at', 'claimed_txid', 'updated_at'])

                    # Update related SendTransaction so it appears in both parties' activities
                    stx = inv.send_transaction
                    if stx:
                        # Set recipient as the claimer and mark invitation claimed
                        stx.recipient_user = user
                        stx.recipient_type = 'user'
                        stx.recipient_display_name = user.get_full_name() or user.username
                        stx.recipient_address = recipient_address
                        stx.invitation_claimed = True
                        # Keep existing status/transaction_hash (original invite submit tx)
                        stx.save(update_fields=['recipient_user', 'recipient_type', 'recipient_display_name', 'recipient_address', 'invitation_claimed', 'updated_at'])

                        # Create notifications for inviter and invitee
                        inviter = inv.inviter_user
                        display_amount = f"{inv.amount} {inv.token_type}"
                        # Notify inviter: their invite was claimed
                        if inviter:
                            try:
                                create_notification(
                                    user=inviter,
                                    notification_type=NotificationTypeChoices.SEND_INVITATION_CLAIMED,
                                    title='Invitación reclamada',
                                    message=f"Tu invitación a {inv.phone_number} fue reclamada. Se enviaron {display_amount}.",
                                    data={
                                        'transaction_type': 'send',
                                        'amount': f'-{inv.amount}',
                                        'token_type': inv.token_type,
                                        'invitation_id': inv.invitation_id,
                                        'recipient_phone': inv.phone_number,
                                        'recipient_address': recipient_address,
                                        'status': 'confirmed',
                                        'isInvitedFriend': True,
                                        'txid': txid,
                                    },
                                    related_object_type='SendTransaction',
                                    related_object_id=str(stx.id),
                                    action_url=f"confio://transaction/{stx.id}"
                                )
                            except Exception:
                                logger.exception('[InviteSend] Failed to create inviter notification')

                        # Notify invitee: received funds via invitation
                        try:
                            sender_name = inviter.get_full_name() or inviter.username if inviter else 'Un amigo'
                            create_notification(
                                user=user,
                                notification_type=NotificationTypeChoices.INVITE_RECEIVED,
                                title='Invitación recibida',
                                message=f"Recibiste {display_amount} de {sender_name}",
                                data={
                                    'transaction_type': 'send',
                                    'amount': f'+{inv.amount}',
                                    'token_type': inv.token_type,
                                    'invitation_id': inv.invitation_id,
                                    'sender_name': sender_name,
                                    'sender_address': stx.sender_address if stx else '',
                                    'status': 'confirmed',
                                    'isInvitedFriend': True,
                                    'txid': txid,
                                },
                                related_object_type='SendTransaction',
                                related_object_id=str(stx.id) if stx else None,
                                action_url=f"confio://transaction/{stx.id}" if stx else None
                            )
                        except Exception:
                            logger.exception('[InviteSend] Failed to create invitee notification')
            except Exception as e:
                logger.warning(f'[InviteSend] Could not update PhoneInvite claim: {e}')
            return cls(success=True, txid=txid)
        except Exception as e:
            # Map common TEAL errors to friendlier messages
            msg = str(e)
            logger.error(f'Claim invite error: {e}')
            friendly = None
            if 'logic eval error' in msg and 'assert' in msg:
                friendly = 'No se pudo reclamar la invitación. Verifica que no haya sido reclamada previamente, que no esté expirada y que tu dirección esté opt-in al activo.'
            return cls(success=False, error=friendly or msg)


# Expose claim mutation at module level
ClaimInviteForPhoneField = ClaimInviteForPhone.Field()


# Query: invite receipt for current user's phone
class InviteReceiptType(graphene.ObjectType):
    exists = graphene.Boolean()
    status_code = graphene.Int()
    # Use String to avoid GraphQL Int overflow for large ASA IDs
    asset_id = graphene.String()
    amount = graphene.Int()
    timestamp = graphene.Int()

def get_invite_receipt_for_phone(user_phone: str, user_country: str | None):
    """Resolve latest invitation for this phone from DB, then check its on-chain receipt box.

    This allows multiple invitations per phone over time (unique IDs), while keeping
    a simple client API keyed by phone.
    """
    builder = InviteSendTransactionBuilder()
    client = get_algod_client()
    try:
        from users.phone_utils import normalize_phone as _norm
        from send.models import PhoneInvite
        phone_key = _norm(user_phone or '', user_country or '')
        if not phone_key or ':' not in phone_key:
            return {'exists': False}
        inv = PhoneInvite.objects.filter(phone_key=phone_key, deleted_at__isnull=True).order_by('-created_at').first()
        if not inv:
            return {'exists': False}
        name = ('r:' + inv.invitation_id).encode()
        try:
            box = client.application_box_by_name(builder.app_id, name)
            b = base64.b64decode(box['value']['bytes']) if isinstance(box.get('value'), dict) else base64.b64decode(box.get('value', ''))
            if len(b) < 32:
                return {'exists': False}
            status = int.from_bytes(b[0:8], 'big')
            asset_id = int.from_bytes(b[8:16], 'big')
            amount = int.from_bytes(b[16:24], 'big')
            ts = int.from_bytes(b[24:32], 'big')
            return {'exists': True, 'status_code': status, 'asset_id': str(asset_id), 'amount': amount, 'timestamp': ts}
        except Exception:
            return {'exists': False}
    except Exception:
        return {'exists': False}
