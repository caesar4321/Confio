import hashlib
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from payment_accounts.models import (
    FinancialAccount,
    FundingInstruction,
    LedgerEntry,
    MoneyFlow,
    MoneyOperation,
    ProviderProfile,
    ProviderWebhookEvent,
)
from payment_accounts.providers import get_provider
from payment_accounts.providers.common import account_status, operation_status
from payment_accounts.services import (
    _apply_account_result,
    _apply_profile_result,
    _sync_flow_status,
    apply_operation_result,
)
from payment_accounts.providers.common import ProviderResult


@transaction.atomic
def store_webhook(*, provider, raw_body, headers):
    adapter = get_provider(provider)
    normalized = adapter.normalize_webhook(raw_body, headers)
    event_id = normalized['event_id']
    if not event_id:
        raise ValueError('Webhook has no idempotency/event id')
    event, created = ProviderWebhookEvent.objects.get_or_create(
        provider=provider,
        event_id=event_id,
        defaults={
            'event_type': normalized['event_type'],
            'raw_body': raw_body.decode('utf-8'),
            'payload': normalized['payload'],
            'signature': headers.get('event-signature')
            or headers.get('X-Infinia-Signature', ''),
            'event_timestamp': headers.get('event-timestamp', ''),
        },
    )
    return event, created


def process_webhook_event(event):
    with transaction.atomic():
        locked = ProviderWebhookEvent.objects.select_for_update().get(pk=event.pk)
        if locked.status in {'processed', 'ignored'}:
            return
        locked.status = 'processing'
        locked.attempts += 1
        locked.save(update_fields=['status', 'attempts'])
    try:
        with transaction.atomic():
            locked = ProviderWebhookEvent.objects.select_for_update().get(pk=event.pk)
            _process_locked_webhook_event(locked)
    except Exception as exc:
        ProviderWebhookEvent.objects.filter(pk=event.pk).update(
            status='failed', last_error=str(exc)
        )
        raise


def _process_locked_webhook_event(event):
    adapter = get_provider(event.provider)
    headers = {
        'event': event.event_type,
        'event-timestamp': event.event_timestamp,
        'X-Idempotency-Key': event.event_id,
    }
    normalized = adapter.normalize_webhook(event.raw_body.encode('utf-8'), headers)
    payload = normalized['payload']
    operation = None
    if normalized.get('operation_resource_id'):
        operation = MoneyOperation.objects.filter(
            provider=event.provider,
            provider_operation_id=normalized['operation_resource_id'],
        ).first()
    if not operation and normalized.get('external_id'):
        operation = MoneyOperation.objects.filter(
            provider=event.provider,
            idempotency_key=normalized['external_id'],
        ).first()
    operation_event = any(
        token in event.event_type.lower()
        for token in ('money_movement', 'payout', 'payin', 'payment', 'internal_transfer')
    )
    if not operation and operation_event and normalized.get('resource_id'):
        operation = MoneyOperation.objects.filter(
            provider=event.provider,
            provider_operation_id=normalized['resource_id'],
        ).first()
    if operation and normalized.get('status') is not None:
        status_payload = (
            payload.get('content') or payload
            if event.provider == 'cobre'
            else payload
        )
        status, raw_status = operation_status(status_payload)
        if (
            event.provider == 'infinia'
            and operation.operation_type in {'internal_transfer', 'conversion'}
            and raw_status == 'COMPLETED'
        ):
            status = 'settling'
        operation = apply_operation_result(
            operation,
            ProviderResult(
                normalized.get('operation_resource_id')
                or normalized.get('resource_id')
                or operation.provider_operation_id,
                status,
                raw_status,
                payload,
            ),
        )

    account = None
    account_id = normalized.get('account_id')
    if account_id:
        account = FinancialAccount.objects.filter(provider_account_id=account_id).first()
    if account and event.event_type.lower() in {
        'account', 'account.updated', 'account_status', 'account.status_updated'
    }:
        status_payload = payload.get('content') or payload
        status, raw_status = account_status(status_payload)
        _apply_account_result(
            account, ProviderResult(account_id, status, raw_status, status_payload)
        )
    if 'owner' in event.event_type.lower() and normalized.get('resource_id'):
        profile = ProviderProfile.objects.filter(
            provider=event.provider,
            provider_owner_id=normalized['resource_id'],
        ).first()
        if profile:
            status, raw_status = account_status(payload)
            _apply_profile_result(
                profile,
                ProviderResult(normalized['resource_id'], status, raw_status, payload),
            )
    if 'key' in event.event_type.lower() and normalized.get('resource_id'):
        instruction = FundingInstruction.objects.filter(
            financial_account__provider_profile__provider=event.provider,
            provider_resource_id=normalized['resource_id'],
        ).first()
        if instruction:
            content = payload.get('content') or payload
            raw_status = str(
                content.get('status')
                or (content.get('connectivity') or {}).get('status')
                or ''
            ).upper()
            canonical = {
                'PROCESSING': 'pending',
                'REGISTERED': 'active',
                'UNREGISTERED': 'closed',
                'DISABLED': 'closed',
                'FAILED': 'failed',
            }.get(raw_status, instruction.status)
            if instruction.status == 'active' and canonical == 'pending':
                canonical = 'active'
            instruction.status = canonical
            instruction.display_value = str(
                content.get('key_value') or instruction.display_value
            )
            instruction.instruction_data = payload
            instruction.save(update_fields=[
                'status', 'display_value', 'instruction_data', 'updated_at'
            ])
    _record_ledger_entry(event, normalized, account, operation)
    event.status = 'processed'
    event.processed_at = timezone.now()
    event.last_error = ''
    event.save(update_fields=['status', 'processed_at', 'last_error'])


def _record_ledger_entry(event, normalized, account, operation):
    payload = normalized['payload']
    content = payload.get('content') or payload
    amount = content.get('amount')
    if not account or amount is None:
        return
    if event.provider == 'cobre':
        amount = Decimal(str(amount)) / Decimal('100')
    else:
        amount = Decimal(str(amount))
    direction = 'credit'
    operation_payload = content.get('operation') or {}
    transaction_type = str(
        operation_payload.get('type') or content.get('type') or ''
    ).lower()
    if amount < 0 or transaction_type in {'debit', 'outgoing', 'payout'}:
        direction = 'debit'
    amount = abs(amount)
    entry_id = str(
        content.get('transaction_id') or content.get('id') or normalized['resource_id'] or event.event_id
    )
    balance = content.get('current_balance', content.get('balance'))
    if balance is not None:
        balance = Decimal(str(balance))
        if event.provider == 'cobre':
            balance /= Decimal('100')
    occurred_at = (
        parse_datetime(str(
            content.get('created_at')
            or content.get('occurred_at')
            or content.get('transaction_date')
            or content.get('date')
            or ''
        ))
        or timezone.now()
    )
    entry, created = LedgerEntry.objects.get_or_create(
        provider=event.provider,
        provider_entry_id=entry_id,
        defaults={
            'financial_account': account,
            'operation': operation,
            'direction': direction,
            'asset': str(content.get('currency') or account.asset).upper(),
            'amount': amount,
            'balance_after': balance,
            'occurred_at': occurred_at,
            'provider_data': payload,
        },
    )
    if not created and operation and not entry.operation_id:
        entry.operation = operation
        entry.save(update_fields=['operation'])
    if created and not operation:
        operation = _create_unsolicited_operation(
            event=event,
            account=account,
            entry=entry,
            direction=direction,
            amount=amount,
            asset=str(content.get('currency') or account.asset).upper(),
            payload=payload,
        )
        entry.operation = operation
        entry.save(update_fields=['operation'])
    if balance is not None and (
        not account.balance_updated_at or occurred_at >= account.balance_updated_at
    ):
        account.current_balance = balance
        account.available_balance = balance
        account.balance_updated_at = occurred_at
        account.save(
            update_fields=[
                'current_balance', 'available_balance', 'balance_updated_at', 'updated_at'
            ]
        )
    if (
        operation
        and operation.destination_account_id == account.id
        and direction == 'credit'
        and operation.status == 'settling'
    ):
        operation.status = 'succeeded'
        operation.settled_at = timezone.now()
        operation.save(update_fields=['status', 'settled_at', 'updated_at'])
        _sync_flow_status(operation.money_flow)


def _create_unsolicited_operation(*, event, account, entry, direction, amount, asset, payload):
    """Surface provider-originated credits/debits in the canonical customer flow."""
    digest = hashlib.sha256(
        f'{event.provider}:{entry.provider_entry_id}'.encode('utf-8')
    ).hexdigest()
    is_credit = direction == 'credit'
    status = 'succeeded' if is_credit else 'needs_review'
    completed_at = timezone.now() if is_credit else None
    flow = MoneyFlow.objects.create(
        confio_account=account.provider_profile.confio_account,
        kind='fund' if is_credit else 'withdraw',
        status=status,
        source_asset=asset,
        source_amount=amount,
        target_asset=asset,
        target_amount=amount,
        gross_amount=amount,
        net_amount=amount,
        completed_at=completed_at,
        metadata={'provider_entry_id': entry.provider_entry_id, 'unsolicited': True},
    )
    return MoneyOperation.objects.create(
        money_flow=flow,
        provider=event.provider,
        operation_type='deposit' if is_credit else 'payout',
        source_account=None if is_credit else account,
        destination_account=account if is_credit else None,
        idempotency_key=f'ledger-{digest}',
        status=status,
        source_asset=asset,
        source_amount=amount,
        target_asset=asset,
        target_amount=amount,
        provider_data=payload,
        settled_at=completed_at,
    )
