"""Bind old-app bridge requests to an owned payout estimate before signing.

The stored estimate is a routing hint only. The bridge freezes and validates the actual
fee/destination in its durable quote; review rejects a different destination.
"""
from decimal import Decimal
from django.conf import settings
from .models import FinancialAccount, PaymentBridgeQuote, InfiniaPayoutEstimateBinding
from .services import PaymentAccountError


def _scope(owner, instruction, amount):
    return dict(confio_account_id=owner.pk, funding_instruction_id=instruction.pk,
                amount_units=str(int(Decimal(str(amount)) * 10**18)))


def remember(owner, instruction, amount, destination):
    InfiniaPayoutEstimateBinding.objects.update_or_create(
        **_scope(owner, instruction, amount), defaults={'destination': destination})


def resolve(owner, instruction, amount, request_id):
    if not getattr(settings, 'INFINIA_LEGACY_PAYOUT_FEES_ENABLED', False):
        return None
    if instruction.financial_account.provider != 'infinia':
        return None
    previous = PaymentBridgeQuote.objects.filter(confio_account=owner, request_id=request_id).first()
    if previous:
        # Retries recover the frozen destination, never a newer screen's hint.
        return previous.money_flow.metadata.get('local_destination_id')
    from .infinia_fee_policy import enabled
    countries = FinancialAccount.objects.filter(
        provider_profile__confio_account=owner, provider_profile__provider='infinia',
        status='active').exclude(country='XXX').values_list('country', flat=True)
    if not any(enabled(country) for country in countries):
        return None
    binding = InfiniaPayoutEstimateBinding.objects.filter(
        **_scope(owner, instruction, amount)).select_related('destination').first()
    destination_id = str(binding.destination.internal_id) if binding else None
    if not destination_id:
        raise PaymentAccountError('Abre Enviar a cuenta local y espera la cotización antes de continuar.')
    return destination_id


def predates_rollout(quote):
    from django.utils.dateparse import parse_datetime
    from django.utils import timezone
    raw = getattr(settings, 'INFINIA_FEE_ROLLOUT_AT', '')
    if not raw:
        return False
    cutoff = parse_datetime(raw)
    if cutoff is None or timezone.is_naive(cutoff):
        raise PaymentAccountError('Invalid Infinia fee rollout timestamp')
    return quote.created_at < cutoff


def record_review(flow, destination):
    from django.db import transaction
    with transaction.atomic():
        current = type(flow).objects.select_for_update().get(pk=flow.pk)
        if current.metadata.get('legacy_fee_review_required'):
            if current.metadata.get('local_destination_id') != str(destination.internal_id):
                raise PaymentAccountError('Este envío no corresponde al destinatario.')
            current.metadata = dict(current.metadata, legacy_fee_reviewed=True)
            current.save(update_fields=['metadata', 'updated_at'])


def require_review(flow):
    if flow.metadata.get('legacy_fee_review_required') and not flow.metadata.get('legacy_fee_reviewed'):
        raise PaymentAccountError('Revisa el destinatario y el monto en Enviar a cuenta local antes de confirmar.')
