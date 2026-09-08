import hashlib
import json
import re
from datetime import date, datetime

from django.db import transaction
from django.utils import timezone

from .models import BillingImportBatch, BillingImportRow, BillingObligation, ObligationSubject


ALLOWED_FIELDS = frozenset({
    'external_id', 'masked_reference', 'obligation_external_id', 'amount_minor',
    'period_start', 'period_end', 'due_at',
})
FORBIDDEN_IDENTITY_FIELDS = frozenset({
    'dni', 'email', 'phone', 'name', 'document_image', 'selfie', 'kyc_profile',
})


def canonical_rows_bytes(rows):
    return json.dumps(rows, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False).encode('utf-8')


def rows_sha256(rows):
    return hashlib.sha256(canonical_rows_bytes(rows)).hexdigest()


def _validate_row(raw):
    if not isinstance(raw, dict):
        return None, 'row_not_object', 'Each row must be a JSON object.'
    unknown = set(raw) - ALLOWED_FIELDS
    if unknown & FORBIDDEN_IDENTITY_FIELDS:
        return None, 'identity_field_forbidden', 'Identity data must use an approved grant.'
    if unknown:
        return None, 'unknown_field', f'Unknown fields: {sorted(unknown)}'
    required = ALLOWED_FIELDS - {'masked_reference'}
    missing = required - set(raw)
    if missing:
        return None, 'missing_field', f'Missing fields: {sorted(missing)}'
    try:
        raw_amount = raw['amount_minor']
        if (isinstance(raw_amount, bool)
                or not isinstance(raw_amount, (int, str))
                or not re.fullmatch(r'[0-9]+', str(raw_amount))):
            raise ValueError('amount must be exact integer minor units')
        amount = int(raw_amount)
        period_start = date.fromisoformat(raw['period_start'])
        period_end = date.fromisoformat(raw['period_end'])
        due_at = datetime.fromisoformat(raw['due_at'].replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None, 'invalid_value', 'Amount, dates, or due_at are invalid.'
    if not 0 < amount <= 2**63 - 1 or period_end < period_start or timezone.is_naive(due_at):
        return None, 'invalid_value', 'Amount must be positive and dates ordered/timezoned.'
    for field in ('external_id', 'masked_reference', 'obligation_external_id'):
        value = raw.get(field, '')
        max_length = 80 if field == 'masked_reference' else 255
        if (not isinstance(value, str) or len(value) > max_length
                or (field != 'masked_reference' and not value.strip())):
            return None, 'invalid_value', f'{field} must be a nonempty bounded string.'
        if value.lstrip().startswith(('=', '+', '-', '@')):
            return None, 'formula_injection', f'{field} begins with an unsafe spreadsheet prefix.'
    return {
        **raw, 'amount_minor': amount,
        'period_start': period_start.isoformat(), 'period_end': period_end.isoformat(),
        'due_at': due_at.isoformat(),
    }, '', ''


@transaction.atomic
def stage_import(*, business, rows, schema_version, generated_at, source_sha256, mode='live'):
    if mode not in ('test', 'live'):
        raise ValueError('invalid import mode')
    if schema_version != 'billing-obligations-v1':
        raise ValueError('unsupported import schema_version')
    rows = list(rows)
    if rows_sha256(rows) != source_sha256:
        raise ValueError('import checksum mismatch')
    batch, created = BillingImportBatch.objects.get_or_create(
        business=business, mode=mode, source_sha256=source_sha256,
        defaults={'schema_version': schema_version, 'generated_at': generated_at,
                  'row_count': len(rows), 'status': 'validating'})
    if not created:
        return batch
    staged = []
    valid_count = 0
    for number, raw in enumerate(rows, start=1):
        normalized, code, detail = _validate_row(raw)
        valid = normalized is not None
        valid_count += int(valid)
        staged.append(BillingImportRow(
            batch=batch, row_number=number, payload=normalized or {},
            status='valid' if valid else 'invalid',
            error_code=code, error_detail=detail))
    BillingImportRow.objects.bulk_create(staged, batch_size=2_000)
    batch.valid_count = valid_count
    batch.invalid_count = len(rows) - valid_count
    batch.status = 'valid' if batch.invalid_count == 0 else 'invalid'
    batch.save(update_fields=('valid_count', 'invalid_count', 'status', 'updated_at'))
    return batch


def promote_import(batch_id, *, chunk_size=2_000):
    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or chunk_size <= 0:
        raise ValueError('chunk_size must be a positive integer')
    promoted = 0
    while True:
        with transaction.atomic():
            batch = BillingImportBatch.objects.select_for_update().get(id=batch_id)
            if batch.invalid_count:
                raise ValueError('an import with invalid rows cannot be promoted')
            rows = list(BillingImportRow.objects.select_for_update(skip_locked=True).filter(
                batch=batch, status='valid').order_by('row_number')[:chunk_size])
            if not rows:
                batch.status = 'completed'
                batch.save(update_fields=('status', 'updated_at'))
                break
            batch.status = 'promoting'
            for row in rows:
                item = row.payload
                subject, _ = ObligationSubject.objects.get_or_create(
                    business=batch.business, mode=batch.mode, external_id=item['external_id'],
                    defaults={'subject_type': 'membership',
                              'masked_reference': item.get('masked_reference', '')})
                obligation, created = BillingObligation.objects.get_or_create(
                    business=batch.business, mode=batch.mode,
                    external_reference=item['obligation_external_id'],
                    defaults={
                        'subject': subject, 'currency': 'PEN',
                        'original_amount_minor': item['amount_minor'],
                        'amount_remaining_minor': item['amount_minor'],
                        'line_items_snapshot': [{
                            'kind': 'institution_import',
                            'amount_minor': item['amount_minor']}],
                        'period_start': item['period_start'], 'period_end': item['period_end'],
                        'issued_at': batch.generated_at, 'due_at': item['due_at'],
                        'status': 'open', 'source_version': batch.schema_version,
                    })
                # A repeated source key is a retry only when it describes
                # the same debt. Never silently credit a different member
                # or accept a changed amount as a successfully imported row.
                if not created and (
                    obligation.subject_id != subject.id
                    or obligation.currency != 'PEN'
                    or obligation.original_amount_minor != item['amount_minor']
                    or obligation.period_start != date.fromisoformat(item['period_start'])
                    or obligation.period_end != date.fromisoformat(item['period_end'])
                    or obligation.due_at != datetime.fromisoformat(item['due_at'])
                ):
                    raise ValueError('obligation external reference conflicts with existing debt')
                row.promoted_subject = subject
                row.promoted_obligation = obligation
                row.status = 'promoted'
                row.save(update_fields=(
                    'promoted_subject', 'promoted_obligation', 'status', 'updated_at'))
                promoted += 1
            batch.promoted_count += len(rows)
            batch.save(update_fields=('status', 'promoted_count', 'updated_at'))
    return promoted
