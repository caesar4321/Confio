"""Automatic incoming conversion, using the same admission and quote boundaries as UI."""
import uuid
from django.db import transaction
from django.utils import timezone
from .models import AutomaticPayin, FinancialAccount, InfiniaJourney, LedgerEntry
from .receiving_rails import sync_verified_rail


def has_unallocated_debit(entry):
    """Ignore only proven spending of another incoming journey's own credit.

    A later debit alone does not consume this receipt: multiple receipts can
    arrive before the first conversion. Unlinked/partial/excess debits still
    require review, rather than assuming a pooled provider balance is safe.
    """
    checked = set()
    for debit in LedgerEntry.objects.filter(financial_account=entry.financial_account,
            direction='debit', occurred_at__gte=entry.occurred_at).select_related('operation'):
        op = debit.operation
        if not op or not op.provider_operation_id:
            return True
        if op.pk in checked:
            continue
        journey = InfiniaJourney.objects.filter(fx_operation=op, direction='to_wallet',
            local_account=entry.financial_account,
            confio_account=entry.financial_account.provider_profile.confio_account).select_related('funding_credit').first()
        if (not journey or not journey.funding_credit_id or journey.funding_credit_id == entry.pk
                or journey.funding_credit.financial_account_id != entry.financial_account_id
                or journey.funding_credit.provider != 'infinia'
                or journey.funding_credit.direction != 'credit'
                or journey.funding_credit.asset != entry.asset
                or op.provider != 'infinia' or op.operation_type != 'conversion'
                or op.money_flow_id != journey.money_flow_id
                or op.destination_account_id != journey.crypto_account_id
                or op.status not in {'settling', 'succeeded'}
                or op.source_account_id != entry.financial_account_id
                or op.source_asset != entry.asset or op.source_amount <= 0
                or op.source_amount > journey.funding_credit.amount):
            return True
        debits = list(LedgerEntry.objects.filter(operation=op, direction='debit'))
        def allocated(item):
            payload = item.provider_data if isinstance(item.provider_data, dict) else {}
            evidence = payload.get('operation')
            return (item.provider == 'infinia' and item.financial_account_id == entry.financial_account_id
                and item.asset == entry.asset and item.amount > 0
                and item.occurred_at >= journey.funding_credit.occurred_at
                and isinstance(evidence, dict) and evidence.get('operation_id') == op.provider_operation_id)
        if not all(allocated(item) for item in debits) or sum(item.amount for item in debits) != op.source_amount:
            return True
        checked.add(op.pk)
    return False


def is_automatic_payin(entry):
    """Screening unknown credits is not authority to convert provider legs."""
    from .payin_admission import is_external_fiat_credit
    if entry.operation_id and entry.operation.operation_type in {'conversion', 'internal_transfer', 'payout'}:
        return False
    payload = entry.provider_data if isinstance(entry.provider_data, dict) else {}
    sender = payload.get('third_party')
    voucher = sender.get('voucher_id') if isinstance(sender, dict) else None
    if isinstance(voucher, str) and voucher.strip():
        from .models import MoneyOperation
        if MoneyOperation.objects.filter(provider='infinia', destination_account=entry.financial_account,
                operation_type__in=['conversion', 'internal_transfer'],
                provider_data__voucher_ids__contains=[voucher]).exists():
            return False
    return is_external_fiat_credit(entry)


def enqueue(entry):
    if not is_automatic_payin(entry):
        return None
    return AutomaticPayin.objects.get_or_create(entry=entry)[0]


def process(pk):
    from .payin_admission import assess
    from .local_money import deposit_quote, _active_pair
    from .infinia_journeys import create_journey, enabled
    enabled()
    # Owner lock is shared with manual creation; no quote creates economic legs.
    # The periodic worker retries unavailable quotes and pending reservations.
    with transaction.atomic():
        row = AutomaticPayin.objects.select_for_update().select_related(
            'entry__financial_account__provider_profile__confio_account').get(pk=pk)
        if row.status != 'pending':
            return row
        entry = row.entry
        account = entry.financial_account
        owner = account.provider_profile.confio_account
        type(owner).objects.select_for_update().get(pk=owner.pk)
        FinancialAccount.objects.select_for_update().get(pk=account.pk)
        existing = InfiniaJourney.objects.filter(funding_credit=entry).first()
        if existing:
            row.status, row.reason = 'started', ''
        elif not is_automatic_payin(entry):
            row.status, row.reason = 'review', 'not_external_payin'
        else:
            from .services import require_unreserved_source
            # A debit can arrive before its conversion completion event. Wait
            # for the existing owner of those funds before evaluating proof;
            # an in-flight receipt must not become a permanent review hold.
            require_unreserved_source('infinia', account, None)
            if has_unallocated_debit(entry):
                row.status, row.reason = 'review', 'subsequent_debit_requires_review'
                row.save(update_fields=['status', 'reason', 'updated_at'])
                return row
            sync_verified_rail(account)
            admission = assess(entry)
            if not admission or not admission.allowed:
                row.reason = admission.reason if admission else 'admission_missing'
            else:
                local, crypto = _active_pair(owner, account.country, account.asset)
                require_unreserved_source('infinia', local, None)
                quote = deposit_quote(owner, entry)
                journey = create_journey(owner=owner, local_account=local, crypto_account=crypto,
                    direction='to_wallet', credit=entry,
                    request_id=uuid.uuid5(entry.internal_id, 'automatic-infinia-payin'),
                    minimum_fx_output=quote['minimum_fx_output'],
                    minimum_wallet_output=quote['minimum_wallet_output'])
                journey.money_flow.metadata = dict(journey.money_flow.metadata,
                    automatic_payin=True, automatic_payin_policy='quoted-minima-v1')
                journey.money_flow.save(update_fields=['metadata'])
                row.status, row.reason = 'started', ''
        row.save(update_fields=['status', 'reason', 'updated_at'])
        return row


def reconcile(limit=50):
    import logging
    logger = logging.getLogger(__name__)
    for pk in AutomaticPayin.objects.filter(status='pending').order_by('updated_at', 'pk').values_list('pk', flat=True)[:limit]:
        try:
            process(pk)
        except Exception:
            # Includes provider outage, active journey, opening fee not settled,
            # unavailable quote or quote outside existing safety limits.
            logger.exception('Automatic pay-in remains pending: %s', pk)
            AutomaticPayin.objects.filter(pk=pk, status='pending').update(reason='waiting_for_safe_quote_or_account')
        finally:
            AutomaticPayin.objects.filter(pk=pk).update(updated_at=timezone.now())
