import graphene
from graphene_django import DjangoObjectType
from send.models import SendTransaction
from django.contrib.auth import get_user_model
from graphql_jwt.decorators import login_required
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from decimal import Decimal
from typing import List, Optional

User = get_user_model()

class SendTransactionType(DjangoObjectType):
    """GraphQL type for SendTransaction model"""
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

        result = bsc_flow.prepare_bsc_send(
            user, jwt_ctx, amount,
            recipient_user_id=recipient_user_id,
            recipient_phone=recipient_phone,
            recipient_address=recipient_address,
            memo=memo or '',
            idempotency_key=idempotency_key or '',
            token=token_type or '',
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
# Inviter locks cUSD+/CONFIO for a phone that isn't a Confío user; the KMS
# sponsor releases it when they join (auto-claim in the verification flow),
# or the inviter reclaims after 7 days. send/invite_bsc_flow.py + the
# ConfioInviteEscrow contract.


class PrepareBscInvite(graphene.Mutation):
    class Arguments:
        phone = graphene.String(required=True)
        phone_country = graphene.String(required=False)
        amount = graphene.Decimal(required=True)
        token_type = graphene.String(required=True, description="CUSD_PLUS or CONFIO")

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
            info.context.user, jwt_ctx, phone_key, token_type, amount)
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

        invite = PhoneInvite.objects.filter(
            invitation_id=invite_id.replace('0x', ''), status='pending',
            deleted_at__isnull=True).first()
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


class Mutation(graphene.ObjectType):
    """GraphQL mutations for send transactions"""
    # Algorand sends live in blockchain/mutations.py; BSC sends (Phase 2,
    # cUSD phase-out) live here on the sponsored 7702 rail.
    prepare_bsc_send = PrepareBscSend.Field()
    submit_bsc_send = SubmitBscSend.Field()
    prepare_bsc_invite = PrepareBscInvite.Field()
    submit_bsc_invite = SubmitBscInvite.Field()
    reclaim_invite_calls = ReclaimInviteCalls.Field()
    submit_bsc_reclaim_invite = SubmitBscReclaimInvite.Field()