import json
from decimal import Decimal
from typing import List, Optional

import graphene
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from graphene_django import DjangoObjectType
from graphql_jwt.decorators import login_required

from send.models import SendTransaction

User = get_user_model()


def _send_unified_receipt(send):
    cache_name = '_detail_unified_receipt'
    if not hasattr(send, cache_name):
        from users.models_unified import UnifiedTransactionTable
        setattr(send, cache_name, UnifiedTransactionTable.objects.filter(
            send_transaction=send, deleted_at__isnull=True,
        ).select_related('send_transaction').first())
    return getattr(send, cache_name)


def _send_prepared_receipt(send):
    """Return the immutable prepare-time gross/fee/net disclosure, if any.

    Finalized model columns still win. This fills the short interval between
    broadcast and event reconciliation without asking the client to apply the
    current contract rate to an older prepared transaction.
    """
    cache_name = '_detail_prepared_receipt'
    if not hasattr(send, cache_name):
        try:
            metadata = json.loads(getattr(send, 'bsc_calls_json', '') or '{}')
            receipt = (metadata.get('receipt') or {}) if isinstance(metadata, dict) else {}
            if not isinstance(receipt, dict):
                receipt = {}
        except (TypeError, ValueError, json.JSONDecodeError):
            receipt = {}
        setattr(send, cache_name, receipt)
    return getattr(send, cache_name)


def is_tip_send(send) -> bool:
    return str(getattr(send, 'idempotency_key', '') or '').startswith('tip-')


def tip_safe_user(send, user, info):
    """A Propina is between Comunidad pseudonyms: the other party's account
    (real name, email, phone) is never exposed through it; only your own."""
    if user is None or not is_tip_send(send):
        return user
    viewer = getattr(getattr(info, 'context', None), 'user', None)
    return user if viewer is not None and getattr(viewer, 'id', None) == user.id else None


class SendTransactionType(DjangoObjectType):
    """GraphQL type for SendTransaction model"""
    fee_amount = graphene.String()
    fee_bps = graphene.Int()
    net_amount = graphene.String()
    to_token = graphene.String()

    class Meta:
        model = SendTransaction
        fields = (
            'id',
            'internal_id',
            'sender_user',
            'recipient_user',
            'amount',
            'token_type',
            'sender_address',
            'recipient_address',
            'memo',
            'status',
            'transaction_hash',
            'error_message',
            'created_at',
            'updated_at',
            'sender_business',
            'recipient_business',
            'sender_type',
            'recipient_type',
            'sender_display_name',
            'recipient_display_name',
            'sender_phone',
            'recipient_phone',
            'idempotency_key',
            'is_invitation',
            'invitation_claimed',
            'invitation_reverted',
            'invitation_expires_at'
        )

    def resolve_sender_user(self, info):
        return tip_safe_user(self, self.sender_user, info)

    # The stored display names are written at prepare, before any money
    # moves: an unsigned send to a stranger must not turn a username into a
    # name (users/name_visibility.can_see_name). Confirmed sends are money
    # moved, so their stored names stand.
    def _display_for(self, info, user, stored, business=None):
        # A Propina stores Comunidad pseudonyms: those stand, always.
        if is_tip_send(self) or self.status == 'CONFIRMED' or user is None or business is not None:
            return stored
        from users.name_visibility import can_see_name
        return stored if can_see_name(info, user) else f'@{user.username}'

    def resolve_sender_display_name(self, info):
        return SendTransactionType._display_for(
            self, info, self.sender_user, self.sender_display_name, self.sender_business)

    def resolve_recipient_display_name(self, info):
        return SendTransactionType._display_for(
            self, info, self.recipient_user, self.recipient_display_name, self.recipient_business)

    def resolve_recipient_user(self, info):
        return tip_safe_user(self, self.recipient_user, info)

    # A Propina names people by their Comunidad pseudonyms only: no wallet
    # address for either side (one can be traced to the other), and both
    # sides are Confío members, never "external".
    # Non-null in the schema: an empty string, never None. The hash goes too
    # (on-chain it names both wallets).
    def resolve_sender_address(self, info):
        return '' if is_tip_send(self) else self.sender_address

    def resolve_recipient_address(self, info):
        return '' if is_tip_send(self) else self.recipient_address

    def resolve_transaction_hash(self, info):
        return '' if is_tip_send(self) else self.transaction_hash

    def resolve_sender_type(self, info):
        return 'user' if is_tip_send(self) else self.sender_type

    def resolve_recipient_type(self, info):
        return 'user' if is_tip_send(self) else self.recipient_type

    def resolve_fee_amount(self, info):
        # net_amount is populated by final event reconciliation. Once present,
        # the finalized fee is authoritative even when it is exactly zero; a
        # truthiness check would incorrectly resurrect an older prepared fee.
        if self.net_amount is not None:
            return str(self.fee_amount or 0)
        prepared = _send_prepared_receipt(self).get('fee')
        if prepared not in (None, ''):
            return str(prepared)
        row = _send_unified_receipt(self)
        if row is None:
            return ''
        from users.graphql_views import UnifiedTransactionType
        return UnifiedTransactionType.resolve_fee_amount(row, info)

    def resolve_fee_bps(self, info):
        from users.graphql_views import _positive_fee_bps

        try:
            fee = Decimal(str(SendTransactionType.resolve_fee_amount(self, info) or 0))
        except Exception:  # malformed legacy rows must not invent a rate
            return None
        if fee <= 0:
            return None
        prepared = _positive_fee_bps(
            _send_prepared_receipt(self).get('fee_bps'))
        if prepared is not None:
            return prepared
        row = _send_unified_receipt(self)
        if row is None:
            return None
        from users.graphql_views import UnifiedTransactionType
        return UnifiedTransactionType.resolve_fee_bps(row, info)

    def resolve_net_amount(self, info):
        if self.net_amount is not None:
            return str(self.net_amount)
        prepared = _send_prepared_receipt(self).get('net')
        if prepared not in (None, ''):
            return str(prepared)
        row = _send_unified_receipt(self)
        if row is None:
            return str(self.amount)
        from users.graphql_views import UnifiedTransactionType
        return UnifiedTransactionType.resolve_net_amount(row, info)

    def resolve_to_token(self, info):
        row = _send_unified_receipt(self)
        if row is None:
            return None
        from users.graphql_views import UnifiedTransactionType
        return UnifiedTransactionType.resolve_to_token(row, info)
    



class Query(graphene.ObjectType):
    """GraphQL queries for send transactions"""
    send_transactions = graphene.List(SendTransactionType)
    send_transaction = graphene.Field(SendTransactionType, id=graphene.ID(required=True))
    send_transactions_with_friend = graphene.List(
        SendTransactionType,
        friend_user_id=graphene.ID(required=False),
        friend_phone=graphene.String(required=False),
        limit=graphene.Int()
    )

    @login_required
    def resolve_send_transactions(self, info, **kwargs):
        """Get all send transactions for the current user"""
        from users.jwt_context import get_jwt_business_context_with_validation
        
        user = info.context.user
        jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_context:
            return []
        
        # Get the account
        try:
            from users.models import Account
            
            account_type = jwt_context['account_type']
            account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')
            
            # Determine the account based on JWT context
            if account_type == 'business' and business_id:
                from users.models import Business
                business = Business.objects.get(id=business_id)
                account = Account.objects.get(
                    business=business,
                    account_type='business'
                )
            else:
                account = Account.objects.get(
                    user=user,
                    account_type=account_type,
                    account_index=account_index,
                    deleted_at__isnull=True
                )
                
            # Return transactions for this account (both as sender and recipient)
            return SendTransaction.objects.filter(
                Q(sender_account=account) | Q(recipient_account=account)
            ).order_by('-created_at')
        except Account.DoesNotExist:
            pass
            
        # Fallback to user-based lookup for backwards compatibility
        return SendTransaction.objects.filter(
            Q(sender_user=user) | Q(recipient_user=user)
        ).order_by('-created_at')

    @login_required
    def resolve_send_transaction(self, info, id):
        """Get a specific send transaction by ID (pk or internal_id)"""
        user = info.context.user
        
        # Check if id looks like a UUID
        is_uuid = len(str(id)) >= 32
        
        # Build query filter
        if is_uuid:
            query = Q(internal_id=id)
            # Try to handle case where id is passed as string but is actually PK? 
            # Unlikely for >= 32 chars.
        else:
            # Assume it's a primary key
            query = Q(id=id)

        # Permission filter: User must be sender or recipient
        permission_query = (
            Q(sender_user=user) | 
            Q(recipient_user=user)
        )

        try:
            return SendTransaction.objects.get(
                query & permission_query
            )
        except (SendTransaction.DoesNotExist, ValueError):
            return None

    @login_required
    def resolve_send_transactions_with_friend(self, info, friend_user_id=None, friend_phone=None, limit=None):
        """Get send transactions with a specific friend"""
        user = info.context.user
        from users.jwt_context import get_jwt_business_context_with_validation
        
        jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_context:
            return []
        
        # Get the user's active account
        try:
            from users.models import Account
            
            account_type = jwt_context['account_type']
            account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')
            
            if account_type == 'business' and business_id:
                from users.models import Business
                business = Business.objects.get(id=business_id)
                account = Account.objects.get(
                    business=business,
                    account_type='business'
                )
            else:
                account = Account.objects.get(
                    user=user,
                    account_type=account_type,
                    account_index=account_index,
                    deleted_at__isnull=True
                )
                
        except Account.DoesNotExist:
            return []
        
        # Build query for transactions with friend
        if friend_user_id:
            # Find transactions with specific user
            try:
                friend = User.objects.get(id=friend_user_id)
                friend_accounts = friend.accounts.all()
                
                transactions = SendTransaction.objects.filter(
                    Q(sender_account=account, recipient_account__in=friend_accounts) |
                    Q(sender_account__in=friend_accounts, recipient_account=account)
                ).order_by('-created_at')
                
            except User.DoesNotExist:
                return []
                
        elif friend_phone:
            # Find transactions with phone number
            transactions = SendTransaction.objects.filter(
                Q(sender_account=account, recipient_phone=friend_phone) |
                Q(sender_phone=friend_phone, recipient_account=account)
            ).order_by('-created_at')
        else:
            return []
        
        # Apply limit if provided
        if limit:
            transactions = transactions[:limit]
            
        return transactions


class BscSendCallType(graphene.ObjectType):
    """One call of the sponsored 7702 send batch (server-built; the client
    signs exactly these and nothing else)."""
    to = graphene.String()
    value_wei = graphene.String()
    data = graphene.String()


class BscSendAuthorizationInput(graphene.InputObjectType):
    """A signed EIP-7702 authorization tuple (first use only)."""
    chain_id = graphene.Int(required=True)
    address = graphene.String(required=True)
    nonce = graphene.String(required=True)
    y_parity = graphene.Int(required=True)
    r = graphene.String(required=True)
    s = graphene.String(required=True)


class PrepareBscSend(graphene.Mutation):
    """Step 1 of a BSC dollar send: resolve the recipient (user id → phone →
    raw 0x address, Algorand-rail priority), pick the funding source and
    call shape server-side, store the exact batch. Returns the calls the
    client must sign as one EIP-712 intent (ConfioBatchDelegate.execute)."""

    class Arguments:
        amount = graphene.Decimal(required=True)
        recipient_user_id = graphene.ID(required=False)
        recipient_phone = graphene.String(required=False)
        recipient_address = graphene.String(required=False)
        memo = graphene.String(required=False)
        idempotency_key = graphene.String(required=False)
        token_type = graphene.String(
            required=False,
            description="Explicit token request: CUSD_PLUS (the token itself) or CONFIO. Absent = dollar-value send (server picks the shape).")

    success = graphene.Boolean()
    error = graphene.String()
    send_id = graphene.String()
    calls = graphene.List(BscSendCallType)
    token_type = graphene.String()
    intent_id = graphene.String()  # bytes32 the client binds into its signature
    gross_amount = graphene.Decimal()
    fee_amount = graphene.Decimal()
    net_amount = graphene.Decimal()
    fee_bps = graphene.Int()

    @login_required
    def mutate(self, info, amount, recipient_user_id=None, recipient_phone=None,
               recipient_address=None, memo='', idempotency_key='', token_type=''):
        from django.conf import settings as dj_settings

        from cusd_plus.schema import _bsc_rate_limited
        from users.jwt_context import get_jwt_business_context_with_validation

        from . import bsc_flow

        user = info.context.user
        if not getattr(dj_settings, 'CUSD_PLUS_7702_ENABLED', False):
            return PrepareBscSend(success=False, error='disabled')
        if _bsc_rate_limited(user.id, 'bsc_send_prepare', 10):
            return PrepareBscSend(success=False, error='rate_limited')

        # Sender context is JWT-derived; business sends need send_funds.
        jwt_ctx = get_jwt_business_context_with_validation(
            info, required_permission='send_funds')
        if not jwt_ctx:
            return PrepareBscSend(success=False, error='permission_denied')

        fee_capable_client = str(
            getattr(info.context, 'META', {}).get(
                'HTTP_X_CONFIO_FEE_CAPABLE', ''
            )
        ).strip() == '1'

        result = bsc_flow.prepare_bsc_send(
            user, jwt_ctx, amount,
            recipient_user_id=recipient_user_id,
            recipient_phone=recipient_phone,
            recipient_address=recipient_address,
            memo=memo or '',
            idempotency_key=idempotency_key or '',
            token=token_type or '',
            fee_capable_client=fee_capable_client,
        )
        if not result.get('success'):
            return PrepareBscSend(success=False, error=result.get('error'))
        return PrepareBscSend(
            success=True,
            send_id=result['send_id'],
            calls=[
                BscSendCallType(to=c['to'], value_wei=c['value'], data=c['data'])
                for c in result['calls']
            ],
            token_type=result['token_type'],
            intent_id=result['intent_id'],
            gross_amount=result.get('gross_amount'),
            fee_amount=result.get('fee_amount'),
            net_amount=result.get('net_amount'),
            fee_bps=result.get('fee_bps', 0),
        )


class SubmitBscSend(graphene.Mutation):
    """Step 2: the sender's signature over the server-stored batch. The
    digest is recomputed from what the SERVER stored — a client cannot
    substitute calldata — then broadcast from the KMS sponsor."""

    class Arguments:
        send_id = graphene.String(required=True)
        nonce = graphene.String(required=True, description="Delegate intent nonce (nonces())")
        deadline = graphene.String(required=True, description="Unix seconds")
        intent_signature = graphene.String(required=True, description="65-byte r‖s‖v hex")
        authorization = BscSendAuthorizationInput(required=False)

    success = graphene.Boolean()
    error = graphene.String()
    authorization_required = graphene.Boolean()
    transaction_hash = graphene.String()
    # What the sponsor SAW on-chain before answering, so the client can skip
    # a poll it would otherwise make from a phone through the relay:
    #   'executed' — the exact BatchExecuted(nonce) landed
    #   'reverted' — mined 0x0; definitive, and safe to retry
    #   'noop'     — mined 0x1 but the delegation never applied; needs a
    #                fresh prepare, NOT a retry of this batch
    #   null       — not observed in the submit budget; client keeps polling
    # Only null means "unknown". Collapsing reverted/noop into one flag would
    # give the two opposite retry semantics the same handling.
    execution = graphene.String(
        description="Sponsor-observed execution: executed | reverted | noop; null=unknown")

    @login_required
    def mutate(self, info, send_id, nonce, deadline, intent_signature, authorization=None):
        from django.conf import settings as dj_settings

        from cusd_plus.schema import _bsc_rate_limited

        from . import bsc_flow

        user = info.context.user
        if not getattr(dj_settings, 'CUSD_PLUS_7702_ENABLED', False):
            return SubmitBscSend(success=False, error='disabled')
        if _bsc_rate_limited(user.id, 'bsc_send_submit', 10):
            return SubmitBscSend(success=False, error='rate_limited')

        send_tx = SendTransaction.objects.filter(
            internal_id=send_id, deleted_at__isnull=True).first()
        if not send_tx:
            return SubmitBscSend(success=False, error='send_not_found')

        result = bsc_flow.submit_bsc_send(
            user, send_tx, nonce, deadline, intent_signature, authorization)
        return SubmitBscSend(
            success=bool(result.get('success')),
            error=result.get('error'),
            authorization_required=bool(result.get('authorization_required')),
            transaction_hash=result.get('transaction_hash'),
            execution=result.get('execution'),
        )


# ═══════════════════ BSC invite escrow (send to non-user) ═══════════════
# Inviter locks cUSD+, cUSD or CONFIO for a phone that isn't a Confío user;
# the server chooses the sender's jurisdiction-appropriate dollar token. The
# KMS sponsor releases (and, if needed, converts) it when they join, or the
# inviter reclaims after 7 days.


class PrepareBscInvite(graphene.Mutation):
    class Arguments:
        phone = graphene.String(required=True)
        phone_country = graphene.String(required=False)
        amount = graphene.Decimal(required=True)
        token_type = graphene.String(
            required=True,
            description="CUSD_PLUS, CUSD or CONFIO. Dollar representation is normalized server-side.",
        )

    success = graphene.Boolean()
    error = graphene.String()
    invite_id = graphene.String()
    calls = graphene.List(BscSendCallType)
    intent_id = graphene.String()  # bytes32 the client binds into its signature

    @login_required
    def mutate(self, info, phone, amount, token_type, phone_country=None):
        from django.conf import settings as dj_settings
        from users.jwt_context import get_jwt_business_context_with_validation
        from blockchain.invite_send_transaction_builder import InviteSendTransactionBuilder
        from . import invite_bsc_flow

        if not getattr(dj_settings, 'CUSD_PLUS_7702_ENABLED', False):
            return PrepareBscInvite(success=False, error='disabled')
        jwt_ctx = get_jwt_business_context_with_validation(info, required_permission='send_funds')
        if not jwt_ctx:
            return PrepareBscInvite(success=False, error='permission_denied')
        phone_key = InviteSendTransactionBuilder.normalize_phone(phone, phone_country)
        result = invite_bsc_flow.prepare_create(
            info.context.user, jwt_ctx, phone_key, token_type, amount,
            phone_display=phone)
        if not result.get('success'):
            return PrepareBscInvite(success=False, error=result.get('error'))
        return PrepareBscInvite(
            success=True, invite_id=result['invite_id'],
            calls=[BscSendCallType(to=c['to'], value_wei=c['value'], data=c['data'])
                   for c in result['calls']],
            intent_id=result['intent_id'])


class SubmitBscInvite(graphene.Mutation):
    class Arguments:
        invite_id = graphene.String(required=True)
        nonce = graphene.String(required=True)
        deadline = graphene.String(required=True)
        intent_signature = graphene.String(required=True)
        authorization = BscSendAuthorizationInput(required=False)

    success = graphene.Boolean()
    error = graphene.String()
    authorization_required = graphene.Boolean()
    transaction_hash = graphene.String()

    @login_required
    def mutate(self, info, invite_id, nonce, deadline, intent_signature, authorization=None):
        from .models import PhoneInvite
        from . import invite_bsc_flow

        # 'draft' — prepared, nothing broadcast. submit_create then CASes it to
        # 'creating', so only one caller can ever broadcast for this invite.
        invite = PhoneInvite.objects.filter(
            invitation_id=invite_id.replace('0x', ''), inviter_user=info.context.user,
            status='draft', deleted_at__isnull=True).first()
        if not invite:
            return SubmitBscInvite(success=False, error='invite_not_found')
        result = invite_bsc_flow.submit_create(
            info.context.user, invite, nonce, deadline, intent_signature, authorization)
        return SubmitBscInvite(
            success=result.get('success', False), error=result.get('error'),
            authorization_required=bool(result.get('authorization_required')),
            transaction_hash=result.get('transaction_hash'))


class SubmitBscReclaimInvite(graphene.Mutation):
    class Arguments:
        invite_id = graphene.String(required=True)
        nonce = graphene.String(required=True)
        deadline = graphene.String(required=True)
        intent_signature = graphene.String(required=True)
        authorization = BscSendAuthorizationInput(required=False)

    success = graphene.Boolean()
    error = graphene.String()
    authorization_required = graphene.Boolean()
    transaction_hash = graphene.String()
    calls = graphene.List(BscSendCallType)

    @login_required
    def mutate(self, info, invite_id, nonce, deadline, intent_signature, authorization=None):
        from .models import PhoneInvite
        from . import invite_bsc_flow

        invite = PhoneInvite.objects.filter(
            invitation_id=invite_id.replace('0x', ''), inviter_user=info.context.user,
            status='pending', deleted_at__isnull=True).first()
        if not invite:
            return SubmitBscReclaimInvite(success=False, error='invite_not_found')
        result = invite_bsc_flow.submit_reclaim(
            info.context.user, invite, nonce, deadline, intent_signature, authorization)
        return SubmitBscReclaimInvite(
            success=result.get('success', False), error=result.get('error'),
            authorization_required=bool(result.get('authorization_required')),
            transaction_hash=result.get('transaction_hash'))


class ReclaimInviteCalls(graphene.Mutation):
    """Return the reclaim call the inviter must sign (client fetches, signs,
    then calls submitBscReclaimInvite)."""
    class Arguments:
        invite_id = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()
    calls = graphene.List(BscSendCallType)
    intent_id = graphene.String()  # bytes32 the client binds into its signature

    @login_required
    def mutate(self, info, invite_id):
        from cusd_plus import sponsor_7702
        from .models import PhoneInvite
        from . import invite_bsc_flow

        invite = PhoneInvite.objects.filter(
            invitation_id=invite_id.replace('0x', ''), inviter_user=info.context.user,
            status='pending', deleted_at__isnull=True).first()
        if not invite:
            return ReclaimInviteCalls(success=False, error='invite_not_found')
        calls = invite_bsc_flow.build_reclaim_calls('0x' + invite.invitation_id)
        return ReclaimInviteCalls(
            success=True,
            calls=[BscSendCallType(to=c['to'], value_wei=c['value'], data=c['data']) for c in calls],
            intent_id=sponsor_7702.intent_id_hex('invite_reclaim', invite.pk))


class LinkRecipientUserType(graphene.ObjectType):
    user_id = graphene.ID()
    username = graphene.String()
    display_name = graphene.String()
    identity_verified = graphene.Boolean()
    receives_by_qr_only = graphene.Boolean()


class RecipientForPhoneType(graphene.ObjectType):
    # SAVED: confirmed earlier for this sender; LEGACY: an OTP-verified holder;
    # NONE: send a link (send/link_invite.py).
    kind = graphene.String()
    user = graphene.Field(LinkRecipientUserType)
    # CLAIMED: the link this sender should confirm (saveRecipient(publicRef)).
    public_ref = graphene.String()


class LinkInviteType(graphene.ObjectType):
    sender_username = graphene.String()
    sender_name = graphene.String()
    sender_verified = graphene.Boolean()
    amount = graphene.Decimal()
    token_type = graphene.String()
    status = graphene.String()
    expires_at = graphene.DateTime()
    is_mine = graphene.Boolean()
    # What the link key signs to send the money to the viewer's own personal
    # account; empty when the viewer cannot claim (own link, no BSC address).
    claim_message = graphene.String()


def _link_user(user, viewer):
    if user is None:
        return None
    from security.identity_status import is_identity_verified
    from users.direct_receive import is_blocked
    from users.name_visibility import display_name_for
    # A number can be guessed: it shows a name only to someone who has moved
    # money with that person (users/name_visibility.py).
    return LinkRecipientUserType(
        user_id=user.pk, username=user.username, display_name=display_name_for(viewer, user),
        identity_verified=is_identity_verified(user), receives_by_qr_only=is_blocked(user))


class SendPeopleType(graphene.ObjectType):
    """Enviar's people list: Recientes, plus the numbers to tag in the
    phone's own contact list (it is never uploaded)."""
    recent = graphene.List(LinkRecipientUserType)
    saved_phone_keys = graphene.List(graphene.String)


class LinkInviteQuery(graphene.ObjectType):
    send_people = graphene.Field(SendPeopleType)
    resolve_recipient_for_phone = graphene.Field(RecipientForPhoneType, phone=graphene.String(required=True))

    @login_required
    def resolve_send_people(self, info):
        from .link_invite import recent_people, saved_phone_keys
        viewer = info.context.user
        return SendPeopleType(recent=[_link_user(u, viewer) for u in recent_people(viewer)],
                              saved_phone_keys=saved_phone_keys(viewer))
    link_invite = graphene.Field(LinkInviteType, public_ref=graphene.String(required=True))

    @login_required
    def resolve_resolve_recipient_for_phone(self, info, phone):
        from graphql import GraphQLError
        from users.name_visibility import take_lookup_quota
        from .link_invite import resolve
        if not take_lookup_quota(info.context.user, 'recipient_phone', 1, 30, 60):
            raise GraphQLError('Demasiadas búsquedas. Probá de nuevo en un minuto.')
        result = resolve(info.context.user, phone)
        return RecipientForPhoneType(kind=result['kind'], user=_link_user(result['user'], info.context.user),
                                     public_ref=result.get('public_ref'))

    @login_required
    def resolve_link_invite(self, info, public_ref):
        from .link_invite import link_summary
        summary = link_summary(public_ref, viewer=info.context.user)
        return LinkInviteType(**summary) if summary else None


class PrepareLinkInvite(graphene.Mutation):
    """First send to a contact: escrow under a one-time key (send/link_invite.py).
    Submitted with submitBscInvite, like any invite."""

    class Arguments:
        phone = graphene.String(required=True)
        amount = graphene.Decimal(required=True)
        token_type = graphene.String(required=True)
        claim_key_address = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()
    invite_id = graphene.String()
    public_ref = graphene.String()
    calls = graphene.List(BscSendCallType)
    intent_id = graphene.String()

    @login_required
    def mutate(self, info, phone, amount, token_type, claim_key_address):
        from django.conf import settings as dj_settings
        from users.jwt_context import get_jwt_business_context_with_validation
        from .link_invite import prepare_link

        if not getattr(dj_settings, 'CUSD_PLUS_7702_ENABLED', False):
            return PrepareLinkInvite(success=False, error='disabled')
        jwt_ctx = get_jwt_business_context_with_validation(info, required_permission='send_funds')
        if not jwt_ctx:
            return PrepareLinkInvite(success=False, error='permission_denied')
        result = prepare_link(info.context.user, jwt_ctx, phone, amount, token_type, claim_key_address)
        if not result.get('success'):
            return PrepareLinkInvite(success=False, error=result.get('error'), public_ref=result.get('public_ref'))
        return PrepareLinkInvite(
            success=True, invite_id=result['invite_id'], public_ref=result.get('public_ref'),
            calls=[BscSendCallType(to=c['to'], value_wei=c['value'], data=c['data']) for c in result['calls']],
            intent_id=result['intent_id'])


class ClaimLinkInvite(graphene.Mutation):
    """Receive a link: the money goes to the caller's own personal account
    (from the JWT), proven by the link key's signature."""

    class Arguments:
        public_ref = graphene.String(required=True)
        signature = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()
    status = graphene.String()
    transaction_hash = graphene.String()

    @login_required
    def mutate(self, info, public_ref, signature):
        from .link_invite import claim_link
        result = claim_link(info.context.user, public_ref, signature)
        return ClaimLinkInvite(success=result.get('success'), error=result.get('error'),
                               status=result.get('status'), transaction_hash=result.get('transaction_hash'))


class SaveRecipient(graphene.Mutation):
    """Remember a contact's account: from a claimed link (public_ref) or after
    a first direct send to a legacy verified number (phone)."""

    class Arguments:
        public_ref = graphene.String(required=False)
        phone = graphene.String(required=False)
        # With phone: the account the send went to (save_legacy refuses another).
        recipient_user_id = graphene.ID(required=False)

    success = graphene.Boolean()
    error = graphene.String()

    @login_required
    def mutate(self, info, public_ref=None, phone=None, recipient_user_id=None):
        from .link_invite import save_from_link, save_legacy
        if public_ref:
            result = save_from_link(info.context.user, public_ref)
        elif phone:
            result = save_legacy(info.context.user, phone, recipient_user_id)
        else:
            result = {'success': False, 'error': 'nothing_to_save'}
        return SaveRecipient(success=result['success'], error=result.get('error'))


class ForgetRecipient(graphene.Mutation):
    """'Olvidar esta cuenta': the next send to this number goes by link again."""

    class Arguments:
        phone = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()

    @login_required
    def mutate(self, info, phone):
        from .link_invite import forget
        result = forget(info.context.user, phone)
        return ForgetRecipient(success=result['success'], error=result.get('error'))


class Mutation(graphene.ObjectType):
    """GraphQL mutations for send transactions"""
    # Algorand sends live in blockchain/mutations.py; BSC sends (Phase 2,
    # cUSD phase-out) live here on the sponsored 7702 rail.
    prepare_bsc_send = PrepareBscSend.Field()
    submit_bsc_send = SubmitBscSend.Field()
    prepare_bsc_invite = PrepareBscInvite.Field()
    submit_bsc_invite = SubmitBscInvite.Field()
    prepare_link_invite = PrepareLinkInvite.Field()
    claim_link_invite = ClaimLinkInvite.Field()
    save_recipient = SaveRecipient.Field()
    forget_recipient = ForgetRecipient.Field()
    reclaim_invite_calls = ReclaimInviteCalls.Field()
    submit_bsc_reclaim_invite = SubmitBscReclaimInvite.Field()
