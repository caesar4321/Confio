"""
Invite & Send GraphQL Mutations

Server builds fully sponsored groups for invite creation.
Client signs only the AXFER; server signs sponsor txns and submits.
"""

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

        # Prevent duplicate active invitations: check if a box already exists
        try:
            phone_key = builder.normalize_phone(phone, phone_country)
            invitation_id_pre = builder.make_invitation_id(phone_key)
            client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
            # Will raise if not found
            _ = client.application_box_by_name(builder.app_id, invitation_id_pre.encode())
            return cls(success=False, error='Ya existe una invitación activa para este número. Espera a que se reclame o se revoque antes de crear otra.')
        except Exception:
            pass

        amount_u = int(amount * 1_000_000)
        res = builder.build_create_invitation(
            inviter_address=acct.algorand_address,
            asset_id=asset_id,
            amount=amount_u,
            phone_number=phone,
            phone_country=phone_country,
            message=message or ''
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
            SendTransaction.objects.update_or_create(
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
        except Exception as e:
            logger.warning(f'[InviteSend] Could not persist SendTransaction invitation: {e}')

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

        algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)

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
            for entry in parsed:
                b = _b64.b64decode(entry.get('txn'))
                tx_d = msgpack.unpackb(b, raw=False)
                tx = transaction.Transaction.undictify(tx_d)
                stx = tx.sign(sk)
                signed_by_index[int(entry.get('index'))] = stx

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
        phone = graphene.String(required=True)
        phone_country = graphene.String(required=False)
        recipient_address = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()
    txid = graphene.String()

    @classmethod
    def mutate(cls, root, info, phone, recipient_address, phone_country=None):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, error='Not authenticated')

        admin_mn = getattr(settings, 'ALGORAND_ADMIN_MNEMONIC', None)
        if not admin_mn:
            return cls(success=False, error='Server missing ALGORAND_ADMIN_MNEMONIC')

        algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
        builder = InviteSendTransactionBuilder()
        contract = builder.contract
        method = next((m for m in contract.methods if m.name == 'claim_invitation'), None)
        if method is None:
            return cls(success=False, error='ABI method claim_invitation not found')

        # Recreate invitation id from phone
        key = builder.normalize_phone(phone, phone_country)
        invitation_id = builder.make_invitation_id(key)

        params = algod_client.suggested_params()
        min_fee = getattr(params, 'min_fee', 1000) or 1000

        # Build 2-txn group: fee-bump pay0, app call
        from algosdk import account as _acct
        admin_sk = mnemonic.to_private_key(admin_mn)
        admin_addr = _acct.address_from_private_key(admin_sk)
        pay0 = transaction.PaymentTxn(
            sender=admin_addr,
            sp=transaction.SuggestedParams(fee=min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True),
            receiver=admin_addr,
            amt=0
        )

        atc = AtomicTransactionComposer()
        atc.add_transaction(TransactionWithSigner(pay0, AccountTransactionSigner(admin_sk)))
        atc.add_method_call(
            app_id=builder.app_id,
            method=method,
            sender=admin_addr,
            sp=transaction.SuggestedParams(fee=min_fee, first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True),
            signer=AccountTransactionSigner(admin_sk),
            method_args=[invitation_id, recipient_address],
        )

        # Sign and submit
        try:
            res = atc.execute(algod_client, 10)
            return cls(success=True, txid=res.tx_ids[-1] if res.tx_ids else '')
        except Exception as e:
            logger.error(f'Claim invite error: {e}')
            return cls(success=False, error=str(e))


# Expose claim mutation at module level
ClaimInviteForPhoneField = ClaimInviteForPhone.Field()


# Query: invite receipt for current user's phone
class InviteReceiptType(graphene.ObjectType):
    exists = graphene.Boolean()
    status_code = graphene.Int()
    asset_id = graphene.Int()
    amount = graphene.Int()
    timestamp = graphene.Int()


def get_invite_receipt_for_phone(user_phone: str, user_country: str | None):
    builder = InviteSendTransactionBuilder()
    key = builder.normalize_phone(user_phone, user_country)
    invitation_id = builder.make_invitation_id(key)
    name = ('r:' + invitation_id).encode()
    client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
    try:
        box = client.application_box_by_name(builder.app_id, name)
        b = base64.b64decode(box['value']['bytes']) if isinstance(box.get('value'), dict) else base64.b64decode(box.get('value', ''))
        if len(b) < 32:
            return {'exists': False}
        status = int.from_bytes(b[0:8], 'big')
        asset_id = int.from_bytes(b[8:16], 'big')
        amount = int.from_bytes(b[16:24], 'big')
        ts = int.from_bytes(b[24:32], 'big')
        return {'exists': True, 'status_code': status, 'asset_id': asset_id, 'amount': amount, 'timestamp': ts}
    except Exception:
        return {'exists': False}
