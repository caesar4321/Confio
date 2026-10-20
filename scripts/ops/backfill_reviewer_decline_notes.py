"""Give Console-declined verifications the note the reviewer wrote (reviews[].comment).

Before reviewer_decline_comment, a Console decline left rejected_reason empty and
the app showed generic copy. Dry run by default; APPLY=1 saves the note and
re-sends the rejection push ("Toca para ver el motivo") when the row is still
the user's latest attempt of its kind.

Run on prod (after deploying the change):
    ssh confio-prod 'cd /opt/confio && myvenv/bin/python manage.py shell' < scripts/ops/backfill_reviewer_decline_notes.py
    ssh confio-prod 'cd /opt/confio && APPLY=1 myvenv/bin/python manage.py shell' < scripts/ops/backfill_reviewer_decline_notes.py
"""
import os
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from security.didit import _didit_request, _notify_verification_status_change, reviewer_decline_comment
from security.models import IdentityVerification

APPLY = os.environ.get('APPLY') == '1'
SINCE = timezone.now() - timedelta(days=60)

rows = (IdentityVerification.all_documents
        .filter(status='rejected', updated_at__gte=SINCE)
        .filter(Q(rejected_reason__isnull=True) | Q(rejected_reason=''))
        .exclude(risk_factors__didit__session_id=None)
        .select_related('user').order_by('updated_at'))
print(f"{'APPLY' if APPLY else 'DRY RUN'}: {rows.count()} rejected without a reason since {SINCE:%Y-%m-%d}")

updated = notified = 0
for v in rows:
    session_id = v.risk_factors['didit']['session_id']
    try:
        decision = _didit_request('GET', f'/v3/session/{session_id}/decision/')
    except Exception as exc:
        print(f'  {v.pk}: decision fetch failed ({type(exc).__name__})')
        continue
    if str(decision.get('status') or '').lower() != 'declined':
        continue
    note = reviewer_decline_comment(decision)
    if not note:
        continue
    factors = v.risk_factors or {}
    # Personal and each business keep separate histories: only a newer attempt
    # of the same account supersedes this one.
    later = IdentityVerification.all_documents.filter(
        user=v.user, is_additional_document=v.is_additional_document, created_at__gt=v.created_at)
    if factors.get('account_type') == 'business':
        later = later.filter(risk_factors__account_type='business',
                             risk_factors__business_id=str(factors.get('business_id')))
    else:
        later = later.filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'))
    newer = later.exists()
    print(f'  {v.pk} user={v.user_id} newer_attempt={newer} note={note[:80]!r}')
    if not APPLY:
        continue
    v.rejected_reason = note
    v.save(update_fields=['rejected_reason', 'updated_at'])
    updated += 1
    if not newer and not v.is_additional_document:
        _notify_verification_status_change(
            verification=v,
            account_type=factors.get('account_type') or 'personal',
            business_id=factors.get('business_id'),
            previous_status='pending',
            new_status='rejected',
        )
        notified += 1

print(f'updated={updated} notified={notified}')
