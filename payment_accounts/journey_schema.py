"""JWT-scoped Infinia journey API; no provider IDs or arbitrary wallet inputs."""
import graphene
from graphene_django import DjangoObjectType
from .models import InfiniaJourney, FinancialAccount, LedgerEntry, PayoutDestination, PaymentBridgeTransfer
from .infinia_journeys import create_journey, attach_return_bridge
from .services import PaymentAccountError


class InfiniaJourneyType(DjangoObjectType):
    stage = graphene.String(required=True)
    wallet_mint_units = graphene.String()
    wallet_mint_request_id = graphene.String()

    def resolve_wallet_mint_request_id(self, info):
        from .activity import mint_request_id
        return mint_request_id(self)
    refund_amount = graphene.String()
    wallet_received_amount = graphene.String()

    def resolve_wallet_received_amount(self, info):
        if self.direction == 'to_wallet' and self.wallet_conversion_id and self.wallet_conversion.status == 'COMPLETED':
            c = self.wallet_conversion
            return str(c.net_amount_exact if c.net_amount_exact is not None else c.to_amount)
        return None

    def resolve_refund_amount(self, info):
        from decimal import Decimal
        if self.direction == 'to_bank' and self.bridge_id and self.bridge.status == 'refunded':
            evidence = self.bridge.binding.get('settlement_evidence', {})
            if evidence.get('token_id') == 'BSC:USDT':
                return str(Decimal(evidence['received_units']) / Decimal(10**18))
        return None
    bridge_id = graphene.UUID()
    bridge_funding_mode = graphene.String()
    bridge_status = graphene.String()
    minimum_fx_output = graphene.String(required=True)
    minimum_wallet_output = graphene.String()
    local_asset = graphene.String(required=True)
    crypto_account_id = graphene.UUID(required=True)
    payout_amount = graphene.String()
    destination_summary = graphene.String(required=True)

    def resolve_stage(self, info):
        from .activity import display_stage
        return display_stage(self)

    def resolve_wallet_mint_units(self, info):
        return self.bridge.actual_out_units if self.direction == 'to_wallet' and self.bridge_id and self.bridge.status == 'delivered' else None

    class Meta:
        model = InfiniaJourney
        convert_choices_to_enum = False
        fields = ('internal_id', 'direction', 'stage', 'failure_code', 'created_at', 'wallet_arrival_units')

    def resolve_bridge_id(self, info):
        return self.bridge.internal_id if self.bridge_id else None

    def resolve_bridge_funding_mode(self, info):
        return self.bridge.funding_mode if self.bridge_id else None

    def resolve_minimum_fx_output(self, info):
        return str(self.minimum_fx_output)

    def resolve_minimum_wallet_output(self, info):
        return str(self.minimum_wallet_output) if self.minimum_wallet_output is not None else None

    def resolve_local_asset(self, info):
        return self.local_account.asset

    def resolve_crypto_account_id(self, info):
        return self.crypto_account.internal_id

    def resolve_destination_summary(self, info):
        return self.destination_snapshot.get('display_label') or ('Destino autorizado ' + self.destination_snapshot.get('destination_internal_id', ''))

    def resolve_payout_amount(self, info):
        return str(self.payout_operation.source_amount) if self.payout_operation_id else None

    def resolve_bridge_status(self, info):
        # 'prepared' means the owner still has to sign it: the send is not funded yet.
        return self.bridge.status if self.bridge_id else None


class InfiniaDepositType(DjangoObjectType):
    automatic_status = graphene.String(required=True)
    held = graphene.Boolean(required=True)
    held_reason = graphene.String(required=True)

    class Meta:
        model = LedgerEntry
        fields = ('internal_id', 'asset', 'amount', 'occurred_at')

    # Graphene passes the LedgerEntry as `self`, so the helper lives at module level.
    def resolve_held(self, info):
        return bool(deposit_admission(self)[1])

    def resolve_held_reason(self, info):
        return deposit_admission(self)[1]

    def resolve_automatic_status(self, info):
        row = getattr(self, 'automatic_payin', None)
        return row.status if row else ''


def deposit_admission(entry):
    """(allowed, reason) for one credit. Read-only: the admin action and
    journey creation own persistence."""
    from .payin_admission import decision, is_external_fiat_credit
    automatic = getattr(entry, 'automatic_payin', None)
    if automatic and automatic.status == 'review':
        return False, automatic.reason
    if not is_external_fiat_credit(entry):
        return True, ''
    allowed, reason, _, _ = decision(entry)
    return allowed, '' if allowed else reason


class CreateInfiniaJourney(graphene.Mutation):
    class Arguments:
        direction = graphene.String(required=True)
        request_id = graphene.UUID(required=True)
        local_account_id = graphene.UUID(required=True)
        crypto_account_id = graphene.UUID(required=True)
        minimum_fx_output = graphene.Decimal(required=True)
        minimum_wallet_output = graphene.Decimal()
        bridge_id = graphene.UUID()
        credit_id = graphene.UUID()
        destination_id = graphene.UUID()
    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    journey = graphene.Field(InfiniaJourneyType)

    @classmethod
    def mutate(cls, root, info, local_account_id, crypto_account_id, bridge_id=None, credit_id=None, destination_id=None, **kwargs):
        from .schema import _active_account, _public_error
        try:
            owner = _active_account(info, permission='send_funds', owner_only=True)
            accounts = FinancialAccount.objects.filter(provider_profile__confio_account=owner).select_related('provider_profile')
            local = accounts.get(internal_id=local_account_id)
            crypto = accounts.get(internal_id=crypto_account_id)
            bridge = PaymentBridgeTransfer.objects.get(internal_id=bridge_id, quote__confio_account=owner) if bridge_id else None
            credit = LedgerEntry.objects.get(internal_id=credit_id, financial_account__provider_profile__confio_account=owner) if credit_id else None
            destination = PayoutDestination.objects.get(internal_id=destination_id, confio_account=owner) if destination_id else None
            from .breb_location import require_for_country
            require_for_country(owner, local.country, info.context.META)
            is_new_send = kwargs.get('direction') == 'to_bank' and not InfiniaJourney.objects.filter(
                confio_account=owner, request_id=kwargs.get('request_id')).exists()
            if is_new_send and destination is not None:
                from .local_money import require_current_destination
                require_current_destination(destination)
            # The monthly allowance is checked inside create_journey, under the owner lock.
            row = create_journey(owner=owner, local_account=local, crypto_account=crypto,
                                 bridge=bridge, credit=credit, destination=destination, **kwargs)
            return cls(success=True, errors=[], journey=row)
        except Exception as exc:
            return cls(success=False, errors=[_public_error(exc)])


class AttachInfiniaReturnBridge(graphene.Mutation):
    class Arguments:
        journey_id = graphene.UUID(required=True)
        bridge_id = graphene.UUID(required=True)
    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    journey = graphene.Field(InfiniaJourneyType)

    @classmethod
    def mutate(cls, root, info, journey_id, bridge_id):
        from .schema import _active_account, _public_error
        try:
            owner = _active_account(info, permission='send_funds', owner_only=True)
            bridge = PaymentBridgeTransfer.objects.get(internal_id=bridge_id, quote__confio_account=owner)
            row = attach_return_bridge(owner=owner, journey_id=journey_id, bridge=bridge)
            return cls(success=True, errors=[], journey=row)
        except Exception as exc:
            return cls(success=False, errors=[_public_error(exc)])


class JourneyQuery(graphene.ObjectType):
    local_incoming_deposits = graphene.List(graphene.NonNull(InfiniaDepositType), required=True,
        account_id=graphene.UUID(required=True), offset=graphene.Int(default_value=0))

    def resolve_local_incoming_deposits(self, info, account_id, offset=0):
        from .schema import _active_account
        from .activation import visible_accounts
        from .payin_admission import is_external_fiat_credit
        from .models import MoneyOperation
        from django.db.models import Q
        owner = _active_account(info, permission='view_transactions')
        accounts = visible_accounts(FinancialAccount.objects.filter(provider_profile__confio_account=owner))
        entries = LedgerEntry.objects.filter(
            Q(provider_data__operation__type__isnull=True) | Q(provider_data__operation__type__in=['PAYIN', 'CREDIT']),
            provider='infinia', direction='credit', amount__gt=0,
            financial_account__in=accounts, financial_account__internal_id=account_id,
            provider_data__third_party__type='FIAT',
        ).select_related('financial_account__provider_profile', 'operation', 'automatic_payin').order_by('-occurred_at', '-pk')
        result, skip = [], max(0, offset)
        # Filter economic provenance BEFORE pagination. Completed incoming
        # receipts remain visible; a conversion's target credit never becomes
        # a new incoming payment merely because its operation_id is missing.
        for entry in entries.iterator(chunk_size=100):
            if entry.operation and entry.operation.operation_type in {'conversion', 'internal_transfer', 'payout'}:
                continue
            voucher = (entry.provider_data.get('third_party') or {}).get('voucher_id')
            if voucher and MoneyOperation.objects.filter(provider='infinia',
                    destination_account=entry.financial_account,
                    operation_type__in=['conversion', 'internal_transfer'],
                    provider_data__voucher_ids__contains=[voucher]).exists():
                continue
            if not is_external_fiat_credit(entry):
                continue
            if skip:
                skip -= 1
                continue
            result.append(entry)
            if len(result) == 20:
                break
        return result

    local_transfer_mints = graphene.List(graphene.NonNull(InfiniaJourneyType), required=True)

    def resolve_local_transfer_mints(self, info):
        from .schema import _active_account
        from django.db.models import Q
        owner = _active_account(info, permission='send_funds', owner_only=True)
        return InfiniaJourney.objects.filter(confio_account=owner, direction='to_wallet',
            bridge__status='delivered').filter(Q(wallet_conversion__isnull=True) | Q(wallet_conversion__status='FAILED')).select_related('bridge', 'wallet_conversion', 'confio_account__user').order_by('created_at')[:50]
    my_infinia_journeys = graphene.List(graphene.NonNull(InfiniaJourneyType), required=True,
        offset=graphene.Int(default_value=0), limit=graphene.Int(default_value=20))
    infinia_journey_deposits = graphene.List(graphene.NonNull(InfiniaDepositType), required=True,
        account_id=graphene.UUID(required=True), offset=graphene.Int(default_value=0))
    infinia_journeys_enabled = graphene.Boolean(required=True)
    infinia_journey = graphene.Field(InfiniaJourneyType, internal_id=graphene.UUID(required=True))

    def resolve_infinia_journey(self, info, internal_id):
        from .schema import _active_account
        owner = _active_account(info, permission='view_transactions')
        return InfiniaJourney.objects.filter(confio_account=owner, internal_id=internal_id).select_related(
            'bridge', 'local_account', 'crypto_account', 'payout_operation', 'wallet_conversion').first()

    def resolve_infinia_journeys_enabled(self, info):
        from .schema import _active_account
        from django.conf import settings
        _active_account(info, permission='view_balance')
        return getattr(settings, 'INFINIA_JOURNEYS_ENABLED', False) and getattr(settings, 'INFINIA_PAYMENT_ACCOUNTS_ENABLED', False)

    def resolve_my_infinia_journeys(self, info, offset=0, limit=20):
        from .schema import _active_account
        owner = _active_account(info, permission='view_transactions')
        return InfiniaJourney.objects.filter(confio_account=owner).select_related('bridge', 'local_account', 'crypto_account', 'payout_operation', 'wallet_conversion').order_by('-created_at')[max(0,offset):max(0,offset)+max(1,min(limit,100))]

    def resolve_infinia_journey_deposits(self, info, account_id, offset=0):
        from .schema import _active_account
        owner = _active_account(info, permission='view_transactions')
        from .activation import visible_accounts
        allowed = visible_accounts(FinancialAccount.objects.filter(provider_profile__confio_account=owner))
        from django.db.models import Q
        return LedgerEntry.objects.filter(
            Q(provider_data__operation__type__isnull=True) | Q(provider_data__operation__type__in=['PAYIN', 'CREDIT']),
            financial_account__in=allowed,
            provider='infinia', direction='credit', amount__gt=0,
            financial_account__internal_id=account_id, financial_account__provider_profile__confio_account=owner,
            funded_journey__isnull=True).select_related('automatic_payin').order_by('-occurred_at')[max(0,offset):max(0,offset)+20]


class JourneyMutation(graphene.ObjectType):
    create_infinia_journey = CreateInfiniaJourney.Field()
    attach_infinia_return_bridge = AttachInfiniaReturnBridge.Field()
