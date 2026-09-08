"""JWT-scoped Cobre journey API; no provider IDs or arbitrary wallet inputs."""
import graphene
from graphene_django import DjangoObjectType
from .models import CobreJourney, FinancialAccount, LedgerEntry, PayoutDestination, PaymentBridgeTransfer
from .cobre_journeys import create_journey, attach_return_bridge
from .services import PaymentAccountError


class CobreJourneyType(DjangoObjectType):
    bridge_id = graphene.UUID()
    minimum_fx_output = graphene.String(required=True)
    local_asset = graphene.String(required=True)
    crypto_account_id = graphene.UUID(required=True)
    payout_amount = graphene.String()
    destination_summary = graphene.String(required=True)

    class Meta:
        model = CobreJourney
        convert_choices_to_enum = False
        fields = ('internal_id', 'direction', 'stage', 'failure_code', 'created_at', 'wallet_arrival_units')

    def resolve_bridge_id(self, info):
        return self.bridge.internal_id if self.bridge_id else None

    def resolve_minimum_fx_output(self, info):
        return str(self.minimum_fx_output)

    def resolve_local_asset(self, info):
        return self.local_account.asset

    def resolve_crypto_account_id(self, info):
        return self.crypto_account.internal_id

    def resolve_destination_summary(self, info):
        return self.destination_snapshot.get('display_label') or ('Destino autorizado ' + self.destination_snapshot.get('destination_internal_id', ''))

    def resolve_payout_amount(self, info):
        return str(self.payout_operation.source_amount) if self.payout_operation_id else None


class CobreDepositType(DjangoObjectType):
    class Meta:
        model = LedgerEntry
        fields = ('internal_id', 'asset', 'amount', 'occurred_at')


class CreateCobreJourney(graphene.Mutation):
    class Arguments:
        direction = graphene.String(required=True)
        request_id = graphene.UUID(required=True)
        local_account_id = graphene.UUID(required=True)
        crypto_account_id = graphene.UUID(required=True)
        copco_account_id = graphene.UUID(required=True)
        minimum_fx_output = graphene.Decimal(required=True)
        bridge_id = graphene.UUID()
        credit_id = graphene.UUID()
        destination_id = graphene.UUID()
    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    journey = graphene.Field(CobreJourneyType)

    @classmethod
    def mutate(cls, root, info, local_account_id, crypto_account_id, copco_account_id, bridge_id=None, credit_id=None, destination_id=None, **kwargs):
        from .schema import _active_account, _public_error
        try:
            owner = _active_account(info, permission='send_funds', owner_only=True)
            accounts = FinancialAccount.objects.filter(provider_profile__confio_account=owner).select_related('provider_profile')
            local = accounts.get(internal_id=local_account_id)
            crypto = accounts.get(internal_id=crypto_account_id)
            copco = accounts.get(internal_id=copco_account_id)
            bridge = PaymentBridgeTransfer.objects.get(internal_id=bridge_id, quote__confio_account=owner) if bridge_id else None
            credit = LedgerEntry.objects.get(internal_id=credit_id, financial_account__provider_profile__confio_account=owner) if credit_id else None
            destination = PayoutDestination.objects.get(internal_id=destination_id, confio_account=owner) if destination_id else None
            row = create_journey(owner=owner, local_account=local, crypto_account=crypto, copco_account=copco,
                                 bridge=bridge, credit=credit, destination=destination, **kwargs)
            return cls(success=True, errors=[], journey=row)
        except Exception as exc:
            return cls(success=False, errors=[_public_error(exc)])


class AttachCobreReturnBridge(graphene.Mutation):
    class Arguments:
        journey_id = graphene.UUID(required=True)
        bridge_id = graphene.UUID(required=True)
    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    journey = graphene.Field(CobreJourneyType)

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


class CobreJourneyQuery(graphene.ObjectType):
    my_cobre_journeys = graphene.List(graphene.NonNull(CobreJourneyType), required=True,
        offset=graphene.Int(default_value=0), limit=graphene.Int(default_value=20))
    cobre_journey_deposits = graphene.List(graphene.NonNull(CobreDepositType), required=True,
        account_id=graphene.UUID(required=True), offset=graphene.Int(default_value=0))
    cobre_journeys_enabled = graphene.Boolean(required=True)

    def resolve_cobre_journeys_enabled(self, info):
        from .schema import _active_account
        from django.conf import settings
        _active_account(info, permission='view_balance')
        return getattr(settings, 'COBRE_JOURNEYS_ENABLED', False) and getattr(settings, 'COBRE_PAYMENT_ACCOUNTS_ENABLED', False)

    def resolve_my_cobre_journeys(self, info, offset=0, limit=20):
        from .schema import _active_account
        owner = _active_account(info, permission='view_transactions')
        return CobreJourney.objects.filter(confio_account=owner).select_related('bridge', 'local_account', 'crypto_account', 'payout_operation').order_by('-created_at')[max(0,offset):max(0,offset)+max(1,min(limit,100))]

    def resolve_cobre_journey_deposits(self, info, account_id, offset=0):
        from .schema import _active_account
        owner = _active_account(info, permission='view_transactions')
        from django.db.models import Q
        from .cobre_journeys import DEPOSITS
        return LedgerEntry.objects.filter(
            Q(provider_data__content__type__in=DEPOSITS) | Q(provider_data__type__in=DEPOSITS),
            provider='cobre', direction='credit', amount__gt=0,
            financial_account__internal_id=account_id, financial_account__provider_profile__confio_account=owner,
            cobre_funded_journey__isnull=True).order_by('-occurred_at')[max(0,offset):max(0,offset)+20]


class CobreJourneyMutation(graphene.ObjectType):
    create_cobre_journey = CreateCobreJourney.Field()
    attach_cobre_return_bridge = AttachCobreReturnBridge.Field()
