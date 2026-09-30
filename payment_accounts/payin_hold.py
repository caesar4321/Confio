"""Hold personal pay-ins until Confío Face (docs/plans/infinia-payin-face-hold.md).

Once USDT lands in the non-custodial wallet, the emergency exit can move it
without Confío, so the last point Confío decides where incoming money goes is
the automatic local-currency → wallet conversion. A personal account's
admitted pay-in waits there until its person passes Confío Face; one passed
check releases the whole queue. Unconfirmed for 24 hours, it goes back to the
payer. Business accounts are never held.

Return path: Infinia's native deposit refund. It returns the whole movement to
the payer on the same rail and needs no payer account details, which our
Colombian and Brazilian pay-ins do not carry completely. A partial return with
Confío's fee deducted (Mexico, CLABE payout) needs a Confío-owned MXN account
to receive the deduction; none exists yet, so every return is a full refund.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import AutomaticPayin

logger = logging.getLogger(__name__)

RETURN_AFTER = timedelta(hours=24)
# Infinia can turn a SUCCESS refund into FAILED later; keep watching this long.
RETURN_WATCH = timedelta(days=3)
ACTIVE_HOLD = 'awaiting_face'


def _owner(row):
    return row.entry.financial_account.provider_profile.confio_account


def is_personal(owner) -> bool:
    return getattr(owner, 'account_type', None) == 'personal'


def needs_face(owner) -> bool:
    """True when this owner's pay-ins must wait for a face right now.

    Same audience as every other Confío Face gate (step_up_applies: KYC'd
    people while enforcement is on). Only a recent passed ``payin_release``
    check opens the window; it is not spent, so money arriving within the
    window is released too — the 24-hour return caps what can be batched.
    """
    from security.face_step_up import WITHDRAWAL_WINDOW, step_up_applies
    from security.models import FaceCheck
    if not is_personal(owner) or not step_up_applies(owner.user):
        return False
    return not FaceCheck.objects.filter(
        user=owner.user, status='passed', purpose='payin_release',
        completed_at__gte=timezone.now() - WITHDRAWAL_WINDOW,
    ).exists()


def received_at(row):
    return row.entry.occurred_at or row.created_at


def returns_at(row):
    return received_at(row) + RETURN_AFTER


def hold(row, owner) -> None:
    """Park an admitted pay-in (caller holds the row lock and saves it)."""
    first_time = row.awaiting_since is None
    row.status, row.reason = ACTIVE_HOLD, 'awaiting_face'
    row.awaiting_since = row.awaiting_since or timezone.now()
    if first_time:
        entry = row.entry
        transaction.on_commit(lambda: _notify_waiting(owner, entry))


def _format_amount(amount, asset) -> str:
    whole = f'{amount:,.2f}'.rstrip('0').rstrip('.')
    return f"{whole.replace(',', '_').replace('.', ',').replace('_', '.')} {asset}"


def _notify_waiting(owner, entry) -> None:
    amount = _format_amount(entry.amount, entry.asset)
    try:
        from notifications.utils import create_notification
        create_notification(
            user=owner.user, account=owner, notification_type='LOCAL_TRANSFER_UPDATED',
            title='Tienes dinero por recibir',
            message=f'Tienes {amount} por recibir. Confirma con tu rostro para recibirlo.',
            data={'kind': 'payin_awaiting_face', 'entry_id': str(entry.internal_id)},
            action_url='confio://pending-incoming',
        )
    except Exception:
        logger.exception('Could not notify held pay-in %s', entry.pk)


def release_for(owner) -> list:
    """Release every held pay-in of a personal account whose person just
    passed Confío Face. Returns the rows after processing."""
    from .auto_payin import process
    if not is_personal(owner) or needs_face(owner):
        return []
    with transaction.atomic():
        rows = list(AutomaticPayin.objects.select_for_update().filter(
            status=ACTIVE_HOLD,
            entry__financial_account__provider_profile__confio_account=owner,
        ).order_by('pk'))
        now = timezone.now()
        for row in rows:
            # Back to the normal queue with durable consent: process() converts
            # it now, and a failure retried later (reconcile) never re-holds it.
            row.status, row.reason, row.released_at = 'pending', 'released_by_face', now
            row.save(update_fields=['status', 'reason', 'released_at', 'updated_at'])
    released = []
    for row in rows:
        try:
            released.append(process(row.pk))
        except Exception:
            logger.exception('Released pay-in %s stays pending for reconcile', row.pk)
            row.refresh_from_db()
            released.append(row)
    return released


def release_open_windows(limit=50) -> None:
    """Release the queues of people who passed a ``payin_release`` check
    (starting from the checks, so a long queue of unconfirmed holds can never
    crowd them out). With enforcement off, every hold drains to the normal
    automatic conversion."""
    from security.face_step_up import WITHDRAWAL_WINDOW, step_up_enabled
    from security.models import FaceCheck
    if not step_up_enabled():
        AutomaticPayin.objects.filter(status=ACTIVE_HOLD).update(
            status='pending', reason='face_enforcement_off', released_at=timezone.now(), updated_at=timezone.now())
        return
    users = FaceCheck.objects.filter(
        status='passed', purpose='payin_release',
        completed_at__gte=timezone.now() - WITHDRAWAL_WINDOW,
    ).values('user_id')
    owners = {}
    for row in AutomaticPayin.objects.filter(
            status=ACTIVE_HOLD,
            entry__financial_account__provider_profile__confio_account__user_id__in=users,
    ).select_related('entry__financial_account__provider_profile__confio_account__user')[:limit]:
        owner = _owner(row)
        owners[owner.pk] = owner
    for owner in owners.values():
        release_for(owner)


def require_conversion_allowed(owner, credit) -> None:
    """The one gate every conversion of a deposit credit passes (manual and
    automatic journeys alike, from create_journey under the owner lock).

    Locks the credit's automatic row, which the 24h return also locks, so a
    credit is either converted or refunded, never both.
    """
    from security.face_step_up import FACE_STEP_UP_MESSAGE
    from .services import PaymentAccountError
    row = AutomaticPayin.objects.select_for_update().filter(entry=credit).first()
    if row and row.status in ('returning', 'returned', 'return_failed'):
        raise PaymentAccountError('Este depósito se está devolviendo al remitente.')
    if needs_face(owner) and not (row and row.released_at):
        raise PaymentAccountError(FACE_STEP_UP_MESSAGE)


def is_own_refund_debit(debit) -> bool:
    """True when Infinia named this debit as the movement of one of our
    refunds (``debit_movement_id``), so the allocation check never mistakes it
    for unexplained spending. Provider correlation only: matching by amount
    could hide an unrelated reversal of the same size."""
    movement = str(debit.provider_entry_id or '')
    return bool(movement) and AutomaticPayin.objects.filter(
        entry__financial_account_id=debit.financial_account_id,
        status__in=['returning', 'returned', 'return_failed'],
        return_details__debit_movement_id=movement,
    ).exists()


def refund_debit_unnamed(financial_account_id) -> bool:
    """A refund on this account whose debit Infinia has not named yet.

    Its debit can post before the refund response names it; until sync_returns
    records the name, an unexplained debit may be ours, so conversions wait for
    the next reconcile instead of being sent to review. Bounded to refunds in
    flight or succeeded within the last hour.
    """
    from django.db.models import Q
    recent = timezone.now() - timedelta(hours=1)
    return (AutomaticPayin.objects
            .filter(entry__financial_account_id=financial_account_id)
            .filter(Q(status='returning') | Q(status='returned', returned_at__gte=recent))
            .exclude(return_details__has_key='debit_movement_id')
            .exists())


def record_open_consent(pk) -> None:
    """A pay-in arriving while its person's face window is open keeps that
    consent even if its conversion must wait (another journey, quote outage)
    past the window. Saved on its own, before any retryable work."""
    row = (AutomaticPayin.objects.select_related('entry__financial_account__provider_profile__confio_account')
           .filter(pk=pk, status='pending', released_at__isnull=True).first())
    if not row:
        return
    from security.face_step_up import step_up_applies
    owner = _owner(row)
    if is_personal(owner) and step_up_applies(owner.user) and not needs_face(owner):
        AutomaticPayin.objects.filter(pk=pk, status='pending', released_at__isnull=True).update(
            released_at=timezone.now(), updated_at=timezone.now())


def _refund_key(row) -> str:
    return f'confio-payin-return-{row.entry.internal_id}'


def start_expired_returns(limit=50) -> None:
    """Move held pay-ins past 24 hours to ``returning`` and ask Infinia to refund."""
    from security.face_step_up import step_up_enabled
    from .models import InfiniaJourney
    if not step_up_enabled():
        return  # holds drain through release_open_windows instead
    cutoff = timezone.now() - RETURN_AFTER
    pks = list(AutomaticPayin.objects.filter(status=ACTIVE_HOLD, released_at__isnull=True,
                                             entry__occurred_at__lte=cutoff)
               .values_list('pk', flat=True)[:limit])
    for pk in pks:
        with transaction.atomic():
            row = AutomaticPayin.objects.select_for_update().select_related('entry').get(pk=pk)
            # Locked: a face pass that released it first wins.
            if row.status != ACTIVE_HOLD or row.released_at or received_at(row) > cutoff:
                continue
            if InfiniaJourney.objects.filter(funding_credit=row.entry).exists():
                # Converted by any path: nothing left to return.
                row.status, row.reason = 'started', ''
                row.save(update_fields=['status', 'reason', 'updated_at'])
                continue
            row.status, row.reason = 'returning', 'unconfirmed_24h'
            row.return_method = 'provider_refund'
            row.return_idempotency_key = _refund_key(row)
            row.return_details = {
                'received': str(row.entry.amount), 'asset': row.entry.asset,
                'returned': str(row.entry.amount), 'deduction': '0',
            }
            row.save()
        _submit_refund(pk)


def _submit_refund(pk) -> None:
    from .clients import InfiniaClient, ProviderAPIError
    row = AutomaticPayin.objects.select_related('entry').get(pk=pk)
    try:
        # Same idempotency key on every attempt: a retry never refunds twice.
        data = InfiniaClient().refund_deposit(
            movement_id=row.entry.provider_entry_id,
            idempotency_key=row.return_idempotency_key,
            description='Devolucion Confio',
        )
    except (ProviderAPIError, ValueError) as exc:
        code = getattr(exc, 'status_code', None)
        if isinstance(exc, ValueError) or (code and 400 <= code < 500 and code not in (408, 409, 429)):
            # Rejected outright (no refund was created): stop retrying and
            # surface it for an operator instead of "Devolviendo" forever.
            logger.error('Pay-in refund REJECTED: automatic_payin=%s status=%s %s', pk, code, exc)
            _apply_refund_status(pk, {'status': 'FAILED', 'failure_reason': f'rejected {code or ""}: {exc}'})
            return
        logger.exception('Pay-in refund submission failed (will retry): %s', pk)
        return
    except Exception:
        logger.exception('Pay-in refund submission failed (will retry): %s', pk)
        return
    _apply_refund_status(pk, data)


def _apply_refund_status(pk, data) -> None:
    if not isinstance(data, dict):
        return
    status = str(data.get('status') or '').upper()
    with transaction.atomic():
        row = AutomaticPayin.objects.select_for_update().get(pk=pk)
        if row.status == 'return_failed':
            return  # FAILED is final: a stale SUCCESS read must not undo it
        if data.get('id'):
            row.return_provider_id = str(data['id'])
        details = dict(row.return_details or {}, provider_status=status)
        # Infinia's own correlation is authoritative over an amount-based claim.
        for key in ('debit_movement_id', 'bounce_movement_id'):
            if data.get(key):
                details[key] = str(data[key])
        if status == 'SUCCESS':
            row.status = 'returned'
            row.returned_at = row.returned_at or timezone.now()
        elif status == 'FAILED':
            row.status, row.reason = 'return_failed', 'provider_refund_failed'
            details['failure_reason'] = str(data.get('failure_reason') or '')[:200]
            logger.error('Pay-in refund FAILED: automatic_payin=%s reason=%s', pk, details['failure_reason'])
        row.return_details = details
        row.save()


def sync_returns(limit=50) -> None:
    """Poll refunds in flight, and recently 'returned' ones that can still fail."""
    from django.db.models import Q
    from .clients import InfiniaClient
    now = timezone.now()
    watch_from = now - RETURN_WATCH
    # Every check saves the row, so updated_at paces it: once a minute while
    # in flight, every 15 minutes while a SUCCESS can still turn FAILED.
    rows = AutomaticPayin.objects.filter(
        Q(status='returning', updated_at__lte=now - timedelta(minutes=1))
        | Q(status='returned', returned_at__gte=watch_from, updated_at__lte=now - timedelta(minutes=15))
    ).order_by('updated_at')[:limit]
    client = InfiniaClient()
    for row in rows:
        try:
            found = client.find_deposit_refund(row.return_idempotency_key)
        except Exception:
            logger.exception('Pay-in refund lookup failed: %s', row.pk)
            continue
        if found is None and row.status == 'returning':
            _submit_refund(row.pk)  # never reached Infinia: submit again, same key
        elif found is not None:
            _apply_refund_status(row.pk, found)


def serialize(row) -> dict:
    """The GraphQL shape in the spec; the only place states are mapped."""
    entry = row.entry
    third_party = (entry.provider_data or {}).get('third_party') if isinstance(entry.provider_data, dict) else None
    payer = (third_party or {}).get('full_name') if isinstance(third_party, dict) else None
    journey = getattr(entry, 'funded_journey', None)
    # Released but not yet converted: the journey takes over once 'started'.
    state = 'releasing' if row.status in ('pending', 'started') else row.status
    details = row.return_details or {}
    return {
        'id': str(entry.internal_id),
        'state': state,
        'amount': str(entry.amount),
        'asset': entry.asset,
        'country': entry.financial_account.country,
        'payer_name': (payer or '').strip() or None,
        'received_at': received_at(row),
        'returns_at': returns_at(row),
        'return_amount': details.get('returned', str(entry.amount)),
        'return_deduction': details.get('deduction', '0'),
        'journey_id': str(journey.internal_id) if journey else None,
    }


def visible_for(owner):
    """Held, releasing, returning, plus returns from the last 7 days. A converted
    pay-in leaves this list; its journey shows on the transfer status screen."""
    from django.db.models import Q
    recent = timezone.now() - timedelta(days=7)
    return (AutomaticPayin.objects
            .filter(entry__financial_account__provider_profile__confio_account=owner)
            # Held at some point, or consented inside an open window: either way
            # the person's money, shown until a journey takes over.
            .filter(Q(awaiting_since__isnull=False) | Q(released_at__isnull=False))
            .filter(Q(status__in=[ACTIVE_HOLD, 'pending', 'returning', 'review'])
                    | Q(status__in=['returned', 'return_failed'], updated_at__gte=recent))
            .select_related('entry__financial_account')
            .order_by('-pk'))
