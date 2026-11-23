"""JWT-scoped Infinia journey API; no provider IDs or arbitrary wallet inputs."""
from decimal import Decimal
from itertools import islice

import graphene
from graphene_django import DjangoObjectType
from .models import InfiniaJourney, FinancialAccount, LedgerEntry, PayoutDestination, PaymentBridgeTransfer
from .infinia_journeys import create_journey, attach_return_bridge
from .services import PaymentAccountError
from .incoming_details import sender_details, incoming_credit


class LocalPaymentSenderType(graphene.ObjectType):
    name = graphene.String(required=True)
    bank_name = graphene.String(required=True)
    bank_code = graphene.String(required=True)
    account_masked = graphene.String(required=True)
    reference = graphene.String(required=True)


class InfiniaJourneyType(DjangoObjectType):
    sender = graphene.Field(LocalPaymentSenderType)
    received_fiat_amount = graphene.String()

    def resolve_sender(self, info):
        return sender_details(incoming_credit(self))

    def resolve_received_fiat_amount(self, info):
        entry = incoming_credit(self)
        return str(entry.amount) if entry else None

    stage = graphene.String(required=True)
    wallet_mint_units = graphene.String()
    wallet_mint_request_id = graphene.String()
    wallet_fee_units = graphene.String()
    wallet_fee_collector = graphene.String()
    wallet_fee_minimum_net_units = graphene.String()

    def resolve_wallet_fee_units(self, info):
        from .infinia_fee_debt import finalize_incoming
        return (finalize_incoming(self) or {}).get('units')

    def resolve_wallet_fee_collector(self, info):
        return self.money_flow.metadata.get('infinia_fee', {}).get('collector') if self.direction == 'to_wallet' else None

    def resolve_wallet_fee_minimum_net_units(self, info):
        from .infinia_fee_debt import finalize_incoming
        return (finalize_incoming(self) or {}).get('minimum_net_units')

    def resolve_wallet_mint_request_id(self, info):
        from .activity import mint_request_id
        return mint_request_id(self)
    refund_amount = graphene.String()
    wallet_received_amount = graphene.String()

    def resolve_wallet_received_amount(self, info):
        from .infinia_fee_collection import wallet_received
        amount = wallet_received(self) if self.direction == 'to_wallet' else None
        return str(amount) if amount is not None else None

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
    sender = graphene.Field(LocalPaymentSenderType)

    def resolve_sender(self, info):
        return sender_details(self)

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
        # An exact local amount the person typed (Pagar). Asked for only by a
        # send in that mode, so an older server fails only that send.
        exact_local_amount = graphene.Decimal()
    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    # Set for a refusal that comes from a prepared payment (payment_intents).
    error_code = graphene.String()
    journey = graphene.Field(InfiniaJourneyType)

    @classmethod
    def mutate(cls, root, info, local_account_id, crypto_account_id, bridge_id=None, credit_id=None, destination_id=None, **kwargs):
        from .schema import _active_account, _public_error, _require_adult
        try:
            if kwargs.get('direction') != 'to_wallet':  # bringing money home stays open
                _require_adult(info)
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
            # A request id that belongs to a prepared payment (payment_intents)
            # may only become the payment its card showed.
            # One transaction: the intent stays locked until its journey exists,
            # and is marked submitted only if the journey was created.
            from django.db import transaction
            from . import payment_intents
            with transaction.atomic():
                intent = payment_intents.journey_guard(
                    owner, kwargs.get('request_id'), direction=kwargs.get('direction'), bridge=bridge,
                    destination=destination, minimum_fx_output=kwargs.get('minimum_fx_output'))
                # After the guard: for a prepared payment the guard's own
                # reading of the charge decides (and says so with a code).
                if is_new_send and destination is not None:
                    from .local_money import require_current_destination
                    require_current_destination(destination)
                # A prepared card's exact amount is the card's, never the client's.
                from .local_money import UPDATE_FOR_FIXED_QR, _exact_amount, is_fixed_amount_qr
                exact = kwargs.pop('exact_local_amount', None)
                if exact is not None:
                    exact = _exact_amount(exact)
                fixed = destination is not None and is_fixed_amount_qr(destination)
                if intent is not None:
                    shown = (intent.params or {}).get('exact_local')
                    if exact is not None and (not shown or exact != Decimal(shown)):
                        raise payment_intents._refuse('changed')
                    if fixed and not intent.amount_exact and is_new_send:
                        # A dollar card shown before fixed-amount QRs were paid
                        # exactly: what it said is not what would be paid. The
                        # card ends (charge_changed), never offered again.
                        raise payment_intents._refuse('charge_changed')
                    exact = shown or None
                elif exact is None and fixed and is_new_send:
                    # A fixed-amount QR is paid only by a build that shows it
                    # as one (a retry of an existing journey returns it as is);
                    # one that cannot be read says so instead.
                    from .local_money import require_exact_for_fixed
                    require_exact_for_fixed(destination, None)
                    raise PaymentAccountError(UPDATE_FOR_FIXED_QR)
                if is_new_send and destination is not None:
                    # A dynamic QR someone already paid ends its card (charge_changed).
                    from .local_money import require_unpaid_qr
                    try:
                        require_unpaid_qr(destination)
                    except PaymentAccountError as exc:
                        raise payment_intents._refuse('charge_changed', str(exc)) from exc
                # The monthly allowance is checked inside create_journey, under the owner lock.
                row = create_journey(owner=owner, local_account=local, crypto_account=crypto,
                                     bridge=bridge, credit=credit, destination=destination,
                                     exact_payout=exact, **kwargs)
                payment_intents.journey_created(intent)
            return cls(success=True, errors=[], journey=row)
        except Exception as exc:
            code = getattr(exc, 'code', '') or ''
            if code in ('charge_changed', 'expired'):
                # The charge no longer reads as the card showed it, or there is
                # no time left to sign or settle it: that card is over.
                try:
                    from . import payment_intents
                    payment_intents.journey_refused(owner, kwargs.get('request_id'), code)
                except Exception:  # noqa: BLE001 - the refusal itself stands
                    pass
            return cls(success=False, errors=[_public_error(exc)], error_code=code)


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


def _incoming_credits(accounts, exclude_ids=None):
    """Money that really arrived from outside, newest first: economic
    provenance is filtered here, before any pagination. A conversion's target
    credit never becomes an incoming payment merely because its operation_id
    is missing."""
    from .payin_admission import is_external_fiat_credit
    from .models import MoneyOperation
    from django.db.models import Q
    entries = LedgerEntry.objects.filter(
        Q(provider_data__operation__type__isnull=True) | Q(provider_data__operation__type__in=['PAYIN', 'CREDIT']),
        provider='infinia', direction='credit', amount__gt=0,
        financial_account__in=accounts,
        provider_data__third_party__type='FIAT',
    ).select_related('financial_account__provider_profile', 'operation', 'automatic_payin').order_by('-occurred_at', '-pk')
    if exclude_ids is not None:
        entries = entries.exclude(pk__in=exclude_ids)
    for entry in entries.iterator(chunk_size=100):
        if entry.operation and entry.operation.operation_type in {'conversion', 'internal_transfer', 'payout'}:
            continue
        voucher = (entry.provider_data.get('third_party') or {}).get('voucher_id')
        if voucher and MoneyOperation.objects.filter(provider='infinia',
                destination_account=entry.financial_account,
                operation_type__in=['conversion', 'internal_transfer'],
                provider_data__voucher_ids__contains=[voucher]).exists():
            continue
        if is_external_fiat_credit(entry):
            yield entry


class JourneyQuery(graphene.ObjectType):
    local_incoming_deposits = graphene.List(graphene.NonNull(InfiniaDepositType), required=True,
        account_id=graphene.UUID(required=True), offset=graphene.Int(default_value=0))

    def resolve_local_incoming_deposits(self, info, account_id, offset=0):
        from .schema import _active_account
        from .activation import visible_accounts
        owner = _active_account(info, permission='view_transactions')
        accounts = visible_accounts(FinancialAccount.objects.filter(provider_profile__confio_account=owner))
        entries = _incoming_credits(accounts.filter(internal_id=account_id))
        return list(islice(entries, max(0, offset), max(0, offset) + 20))

    # Historial reads transactions, and a deposit becomes one only when its
    # journey starts. The ones with no journey (returned, in review, waiting
    # for Confío Face) are listed here or the person sees them nowhere.
    local_deposits_without_transfer = graphene.List(graphene.NonNull(InfiniaDepositType), required=True)

    def resolve_local_deposits_without_transfer(self, info):
        from .schema import _active_account
        from .activation import visible_accounts
        owner = _active_account(info, permission='view_transactions')
        accounts = visible_accounts(FinancialAccount.objects.filter(provider_profile__confio_account=owner))
        # Only a journey that already has its history row covers a deposit:
        # that row is written after commit and can fail until the repair runs.
        journeys = InfiniaJourney.objects.filter(
            funding_credit__isnull=False, money_flow__unified_transaction__isnull=False,
            money_flow__unified_transaction__deleted_at__isnull=True,
        ).values('funding_credit_id')
        return list(islice(_incoming_credits(accounts, exclude_ids=journeys), 500))

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
            'bridge', 'local_account', 'crypto_account', 'payout_operation', 'wallet_conversion', 'funding_credit').first()

    def resolve_infinia_journeys_enabled(self, info):
        from .schema import _active_account
        from django.conf import settings
        _active_account(info, permission='view_balance')
        return getattr(settings, 'INFINIA_JOURNEYS_ENABLED', False) and getattr(settings, 'INFINIA_PAYMENT_ACCOUNTS_ENABLED', False)

    def resolve_my_infinia_journeys(self, info, offset=0, limit=20):
        from .schema import _active_account
        owner = _active_account(info, permission='view_transactions')
        return InfiniaJourney.objects.filter(confio_account=owner).select_related('bridge', 'local_account', 'crypto_account', 'payout_operation', 'wallet_conversion', 'funding_credit').order_by('-created_at')[max(0,offset):max(0,offset)+max(1,min(limit,100))]

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
