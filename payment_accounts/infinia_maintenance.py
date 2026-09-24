"""Prospective monthly fiat-account invoices, collected by a signed fee batch."""
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .infinia_fees import FeePricingError
from .models import FinancialAccount, InfiniaMaintenanceCharge, InfiniaMaintenanceState


def next_month(period):
    return date(period.year + (period.month == 12), period.month % 12 + 1, 1)


@transaction.atomic
def accrue(owner):
    if not getattr(settings, 'INFINIA_MAINTENANCE_FEES_ENABLED', False):
        return
    from .infinia_fee_policy import enabled
    from .infinia_fees import FIAT_ASSETS
    type(owner).objects.select_for_update().get(pk=owner.pk)
    tier = getattr(settings, 'INFINIA_ACCOUNT_FEE_TIER', 0)
    if type(tier) is not int or not 0 <= tier <= 2:
        raise FeePricingError('Unknown virtual account fee tier')
    rate = Decimal(('0.10', '0.07', '0.05')[tier])
    today = timezone.now().date().replace(day=1)
    accounts = FinancialAccount.objects.filter(provider_profile__confio_account=owner,
        provider_profile__provider='infinia', asset__in=FIAT_ASSETS.values()).exclude(country='XXX').exclude(
        ownership_structure='platform_liquidity').exclude(provider_account_id__isnull=True).exclude(provider_account_id='')
    for account in accounts:
        if not enabled(account.country):
            continue
        active = account.status == 'active'
        state = InfiniaMaintenanceState.objects.filter(account=account).first()
        if state is None:
            if not active:
                continue
            # No retroactive invoices for months before this rollout observed
            # the account. A shared Polygon USDC account never enters this loop.
            state = InfiniaMaintenanceState.objects.create(account=account, next_period=today, monthly_usd=rate)
        if not state.enabled and active:
            state.next_period = today
        if state.enabled or active:
            end = today if active else min(today, account.updated_at.date().replace(day=1))
            while state.next_period <= end:
                InfiniaMaintenanceCharge.objects.get_or_create(account=account, period=state.next_period,
                    defaults={'amount_usd': rate if state.next_period == today else state.monthly_usd})
                state.next_period = next_month(state.next_period)
        state.enabled, state.monthly_usd = active, rate
        state.save(update_fields=['next_period', 'enabled', 'monthly_usd'])


def _release_expired(owner):
    from .models import PaymentBridgeQuote, PaymentBridgeTransfer, InfiniaJourney
    from blockchain.models import SponsoredBatch
    now = timezone.now()
    charges = InfiniaMaintenanceCharge.objects.filter(account__provider_profile__confio_account=owner,
        collected_tx_hash='', reserved_flow__isnull=False)
    from .models import InfiniaFeeDebt
    debts = InfiniaFeeDebt.objects.filter(source_flow__confio_account=owner,
        settled_tx_hash='', reserved_flow__isnull=False)
    flow_ids = set(charges.values_list('reserved_flow_id', flat=True)) | set(debts.values_list('reserved_flow_id', flat=True))
    for flow_id in flow_ids:
        quote = PaymentBridgeQuote.objects.filter(money_flow_id=flow_id).first()
        releasable = False
        if quote:
            bridge = PaymentBridgeTransfer.objects.filter(quote=quote).first()
            if bridge is None:
                releasable = quote.expires_at <= now
            elif not bridge.source_tx_hash and not SponsoredBatch.objects.filter(
                    user=owner.user, client_request_id='bridge:' + str(bridge.internal_id)).exists():
                releasable = bridge.deadline <= int(now.timestamp())
            elif bridge.status == 'failed' and bridge.batch_id:
                releasable = bridge.batch.status in ('reverted', 'noop_failed')
        else:
            journey = InfiniaJourney.objects.filter(money_flow_id=flow_id, stage='failed',
                bridge__status__in=['failed', 'refunded']).first()
            releasable = bool(journey)
        if releasable:
            charges.filter(reserved_flow_id=flow_id).update(reserved_flow=None)
            debts.filter(reserved_flow_id=flow_id).update(reserved_flow=None)


@transaction.atomic
def quoted_charges(owner):
    type(owner).objects.select_for_update().get(pk=owner.pk)
    accrue(owner)
    _release_expired(owner)
    # Previously accrued debt remains due if new accrual is disabled.
    charges = list(InfiniaMaintenanceCharge.objects.filter(account__provider_profile__confio_account=owner,
        reserved_flow__isnull=True, collected_tx_hash='').order_by('period', 'pk'))
    return [row.pk for row in charges], sum((row.amount_usd for row in charges), Decimal(0))


@transaction.atomic
def reserve(snapshot, flow):
    from .infinia_fee_debt import reserve as reserve_debt
    reserve_debt(snapshot, flow)
    ids = snapshot.get('maintenance_ids', []) if snapshot else []
    if not ids:
        return
    count = InfiniaMaintenanceCharge.objects.filter(pk__in=ids,
        account__provider_profile__confio_account=flow.confio_account,
        reserved_flow__isnull=True, collected_tx_hash='').update(reserved_flow=flow)
    if count != len(ids):
        raise FeePricingError('Account fees changed; request a new quote')


def require_reservation(snapshot, flow):
    from .infinia_fee_debt import require_reservation as require_debt
    require_debt(snapshot, flow)
    ids = snapshot.get('maintenance_ids', [])
    if ids and InfiniaMaintenanceCharge.objects.filter(pk__in=ids, reserved_flow=flow).count() != len(ids):
        raise FeePricingError('Account fees changed; request a new quote')


def reconcile(journey, evidence):
    from .infinia_fee_debt import reconcile as reconcile_debt
    reconcile_debt(journey, evidence)
    ids = journey.money_flow.metadata.get('infinia_fee', {}).get('maintenance_ids', [])
    if not ids:
        return
    flow = journey.bridge.quote.money_flow if journey.direction == 'to_bank' else journey.money_flow
    if evidence:
        require_reservation(journey.money_flow.metadata['infinia_fee'], flow)
    InfiniaMaintenanceCharge.objects.filter(pk__in=ids, reserved_flow=flow).update(
        collected_tx_hash=evidence['transaction_hash'] if evidence else '')


from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=FinancialAccount)
def account_billing_changed(sender, instance, **kwargs):
    if kwargs.get('raw') or not getattr(settings, 'INFINIA_MAINTENANCE_FEES_ENABLED', False):
        return
    if instance.provider_profile.provider == 'infinia' and instance.country != 'XXX':
        owner = instance.provider_profile.confio_account
        # Provider synchronization may already hold an account lock. Wait for
        # commit so every billing operation acquires the owner lock first.
        transaction.on_commit(lambda: accrue(owner))
