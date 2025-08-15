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
from users.jwt_context import get_jwt_business_context_with_validation
from users.models import Account

logger = logging.getLogger(__name__)


class PrepareInviteForPhone(graphene.Mutation):
    class Arguments:
        phone = graphene.String(required=True)
        phone_country = graphene.String(required=False)
        amount = graphene.Float(required=True)
        asset_type = graphene.String(required=False, default_value='CUSD')
        message = graphene.String(required=False)

    success = graphene.Boolean()
    error = graphene.String()
    transactions = graphene.JSONString()
    sponsor_transactions = graphene.JSONString()
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

        return cls(
            success=True,
            transactions=res.transactions_to_sign,
            sponsor_transactions=res.sponsor_transactions,
            group_id=res.group_id,
            invitation_id=res.invitation_id,
        )


class SubmitInviteForPhone(graphene.Mutation):
    class Arguments:
        signed_axfer_b64 = graphene.String(required=True, description='Signed AXFER from inviter (base64 msgpack)')
        sponsor_unsigned = graphene.List(graphene.String, required=True, description='Unsigned sponsor txns from prepare step (base64 msgpack)')

    success = graphene.Boolean()
    error = graphene.String()
    txid = graphene.String()

    @classmethod
    def mutate(cls, root, info, signed_axfer_b64: str, sponsor_unsigned: List[str]):
        user = info.context.user
        if not user.is_authenticated:
            return cls(success=False, error='Not authenticated')

        if len(sponsor_unsigned) != 3:
            return cls(success=False, error='Expected three sponsor transactions: pay0, pay1, app_call')

        algod_client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)

        # Helpers for robust base64 handling
        def _b64_to_bytes(s: str) -> bytes:
            try:
                if not isinstance(s, str):
                    s = str(s)
                ss = s.strip().replace('-', '+').replace('_', '/')
                pad = (-len(ss)) % 4
                if pad:
                    ss += '=' * pad
                return _b64.b64decode(ss)
            except Exception as ee:
                raise ValueError(f'base64 decode failed: {ee}')

        # Allow passing JSON strings accidentally
        if len(sponsor_unsigned) == 1 and isinstance(sponsor_unsigned[0], str):
            try:
                parsed = json.loads(sponsor_unsigned[0])
                if isinstance(parsed, list):
                    sponsor_unsigned = parsed
            except Exception:
                pass

        # Decode transactions
        def _decode_txn(b: bytes):
            try:
                return algo_encoding.msgpack_decode(b)
            except Exception:
                # If there is trailing data, read first object
                try:
                    up = msgpack.Unpacker(raw=False, use_list=False)
                    up.feed(b)
                    first = next(up)
                    packed = msgpack.packb(first, use_bin_type=True)
                    return algo_encoding.msgpack_decode(packed)
                except Exception as ee:
                    raise ee

        try:
            pay0 = _decode_txn(_b64_to_bytes(sponsor_unsigned[0]))
            pay1 = _decode_txn(_b64_to_bytes(sponsor_unsigned[1]))
            app_call = _decode_txn(_b64_to_bytes(sponsor_unsigned[2]))
            user_signed = _b64_to_bytes(signed_axfer_b64)
        except Exception as e:
            return cls(success=False, error=f'Invalid transaction payloads: {e}')

        # Sign sponsor transactions
        sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
        if not sponsor_mn:
            return cls(success=False, error='Server missing ALGORAND_SPONSOR_MNEMONIC')
        sk = mnemonic.to_private_key(sponsor_mn)

        stx_pay0 = pay0.sign(sk)
        stx_pay1 = pay1.sign(sk)
        stx_app = app_call.sign(sk)

        # Submit group
        try:
            txids = algod_client.send_transactions([stx_pay0, stx_pay1, algo_encoding.msgpack_decode(user_signed), stx_app])
            # Wait for confirmation (short timeout)
            transaction.wait_for_confirmation(algod_client, stx_app.get_txid(), 8)
            return cls(success=True, txid=stx_app.get_txid())
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
