"""Propinas: optional gifts between members, 0% commission.

App Store 3.2.1(vii) is why tips skip in-app purchase, and it holds only
while (a) the gift is completely optional and (b) 100% reaches the
recipient, and (c) it is never tied to receiving content or a service. So:

- the recipient gets exactly the amount: the send must be an internal,
  fee-free dollar send (prepare_bsc_send checks the key against this row
  and refuses any fee);
- a tip unlocks nothing: not a conversation, not a request's state, not
  rank, returns or content (dm_gate rejects "tip for a signal" offers);
- the optional note passes the same DM gate BEFORE any money moves.

Flow: prepare_tip (rules + note review) -> the app runs the normal BSC send
with idempotency key `send_key` (face step-up and signing unchanged) ->
on confirmation the tip shows as a gift bubble in the conversation.
"""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from . import community, dm_gate
from .community import CommunityPostError, ReviewUnavailable
from .models import (
    DirectConversation,
    DirectConversationMember,
    DirectConversationStatus,
    DirectMessage,
    DirectMessageReview,
    Tip,
    TipStatus,
)

logger = logging.getLogger(__name__)

KEY_PREFIX = 'tip-'
MIN_USD = Decimal('0.50')
MAX_USD = Decimal('200')
DAILY_USD = Decimal('500')
NOTE_MAX = 140
# A prepared tip nobody signed stops counting against the daily limit.
PREPARED_TTL = timedelta(hours=1)

NOT_AVAILABLE = 'tip_not_available'
MESSAGES = {
    NOT_AVAILABLE: 'No puedes enviarle una propina a esta persona.',
    'tip_recipient_unverified': 'Esta persona aún no puede recibir propinas.',
    'tip_recipient_no_wallet': 'Esta persona aún no puede recibir propinas. Le avisaremos.',
    'tip_amount': f'La propina va de ${MIN_USD} a ${MAX_USD:.0f}.',
    'tip_daily_limit': f'Puedes enviar hasta ${DAILY_USD:.0f} en propinas por día.',
    'tip_note_too_long': f'La nota supera los {NOTE_MAX} caracteres.',
    'tip_note_unavailable': 'No pudimos revisar tu nota. Inténtalo de nuevo.',
    'tip_key_conflict': 'Cambiaste la propina. Inténtalo de nuevo.',
    'tip_in_flight': 'Tu propina anterior a esta persona aún se está confirmando. Espera un momento.',
    'tip_expired': 'Esta propina venció. Prepárala de nuevo.',
}
# A tip sent but not yet confirmed blocks another to the same person for as
# long as it could still execute (SUBMIT_TTL + EXPIRY_GRACE, below): an
# uncertain first attempt can't turn into two payments.
IN_FLIGHT_WINDOW = timedelta(minutes=70)
# A confirmed tip to the same person this recently asks for confirmation:
# a payment whose answer got lost must not quietly happen twice.
REPEAT_WINDOW = timedelta(minutes=10)


def _error(code: str, message: str | None = None) -> CommunityPostError:
    return CommunityPostError(code, message or MESSAGES[code])


def _wallet(user) -> str:
    from .member_portfolio import personal_wallet

    return personal_wallet(user) or ''


def tip_block(sender, target) -> str | None:
    """Why `sender` can't tip `target` (None: they can). Never depends on
    profile visibility or DM state: a gift is not a conversation."""
    from security.utils import check_user_banned

    if target is None or target.id == sender.id or not target.is_active or target.deleted_at is not None:
        return NOT_AVAILABLE
    if check_user_banned(sender)[0] or check_user_banned(target)[0]:
        return NOT_AVAILABLE
    if community.is_blocked_between(sender.id, target.id):
        return NOT_AVAILABLE
    if not community.is_verified_member(target):
        return 'tip_recipient_unverified'
    if not _wallet(target):
        return 'tip_recipient_no_wallet'
    return None


def _amount(value) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        raise _error('tip_amount')
    if not amount.is_finite() or amount < MIN_USD or amount > MAX_USD:
        raise _error('tip_amount')
    return amount


def _sent_today(sender, *, committed_only=False, exclude_id=None) -> Decimal:
    """Tips in the last 24 h: sent or confirmed, plus (when preparing) the
    still-valid prepared ones reserving their share."""
    from django.db.models import Q

    now = timezone.now()
    # Sent tips count from when their send was bound, which is within
    # SUBMIT_TTL of the last moment it can still leave (tip_submit_error).
    committed = (Q(status__in=[TipStatus.SENT, TipStatus.CONFIRMED],
                   send_transaction__created_at__gte=now - timedelta(hours=24))
                 # An unsigned send past its window can never leave: it frees its share.
                 & ~_expired_unsigned())
    reserved = Q(status=TipStatus.PREPARED, created_at__gte=now - PREPARED_TTL)
    qs = Tip.objects.filter(sender=sender).filter(committed if committed_only else committed | reserved)
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    return qs.aggregate(total=Sum('amount'))['total'] or Decimal('0')


def prepare_tip(sender, business, recipient_id, amount, note: str = '', client_key: str = '',
                allow_repeat: bool = False) -> Tip:
    """Check the rules and review the note; no money moves here. Returns the
    tip whose send_key the app passes as the send's idempotency key."""
    from users.models import User

    if business is not None:
        raise _error(NOT_AVAILABLE, 'Las propinas se envían desde tu cuenta personal.')
    client_key = (client_key or '').strip()[:64] or uuid.uuid4().hex
    amount = _amount(amount)
    note = ' '.join((note or '').split())
    existing = Tip.objects.filter(sender=sender, client_key=client_key).first()
    if existing is not None:
        # A retry returns the same tip; a key reused for a different tip is refused.
        if str(existing.recipient_id) != str(recipient_id) or existing.amount != amount or existing.note != note:
            raise _error('tip_key_conflict')
        return existing
    try:
        target = User.objects.filter(id=int(recipient_id)).first()
    except (TypeError, ValueError):
        target = None
    block = tip_block(sender, target)
    if block:
        raise _error(block)
    if Tip.objects.filter(sender=sender, recipient=target, status=TipStatus.SENT,
                          updated_at__gte=timezone.now() - IN_FLIGHT_WINDOW).exists():
        raise _error('tip_in_flight')
    recent = Tip.objects.filter(sender=sender, recipient=target, status=TipStatus.CONFIRMED,
                                updated_at__gte=timezone.now() - REPEAT_WINDOW).order_by('-updated_at').first()
    if recent is not None and not allow_repeat:
        raise _error('tip_recent', f'Ya le enviaste una propina de ${recent.amount} hace unos minutos.')
    # Cheap checks before the paid note review: a throttle, and the limit.
    if not community.take_upload_ticket(sender, 'tip'):
        raise _error('tip_rate_limited', 'Demasiados intentos seguidos. Espera un rato.')
    if _sent_today(sender) + amount > DAILY_USD:
        raise _error('tip_daily_limit')
    if len(note) > NOTE_MAX:
        raise _error('tip_note_too_long')
    if note:
        refused = dm_gate.prefilter(note)
        if refused:
            raise _error('tip_note_rejected', refused)
        try:
            verdict, _, _ = dm_gate.review(note)
        except ReviewUnavailable:
            raise _error('tip_note_unavailable')
        if verdict['decision'] != 'approve':
            raise _error('tip_note_rejected', verdict.get('reason') or 'Tu nota no cumple las normas.')
    with transaction.atomic():
        User.objects.select_for_update().filter(pk=sender.pk).first()
        if _sent_today(sender) + amount > DAILY_USD:
            raise _error('tip_daily_limit')
        try:
            with transaction.atomic():
                return Tip.objects.create(sender=sender, recipient=target, amount=amount, note=note,
                                          client_key=client_key, send_key=f'{KEY_PREFIX}{uuid.uuid4().hex}',
                                          repeat_confirmed=bool(allow_repeat))
        except IntegrityError:
            return Tip.objects.get(sender=sender, client_key=client_key)


# ── hooks from the send flow (send/bsc_flow.py, send/tasks.py) ───────────────

def tip_for_send(user, idempotency_key, recipient_user, recipient_business, amount_usd, token_request,
                 sender_business):
    """(tip, error) for a send whose key claims to be a tip. Any mismatch
    refuses the send: the key can't smuggle a different payment."""
    tip = Tip.objects.select_related('recipient').filter(sender=user, send_key=idempotency_key).first()
    if tip is None or tip.status != TipStatus.PREPARED:
        return None, 'tip_not_found'
    if timezone.now() - tip.created_at > PREPARED_TTL:
        return None, 'tip_expired'
    if (sender_business is not None or recipient_business is not None or recipient_user is None
            or recipient_user.id != tip.recipient_id or token_request
            or Decimal(amount_usd) != tip.amount):
        return None, 'tip_mismatch'
    if tip_block(user, recipient_user):
        return None, 'tip_not_available'
    return tip, None


def link_send(tip, send_tx) -> str | None:
    """Called inside prepare_bsc_send's transaction, right after the send
    row: the authoritative moment the tip spends its share of the daily
    limit. Returns an error code (the caller rolls the send back) or None."""
    from users.models import User

    User.objects.select_for_update().filter(pk=tip.sender_id).first()
    row = Tip.objects.select_for_update().filter(id=tip.id).first()
    if row is None or row.status != TipStatus.PREPARED:
        return 'tip_not_found'
    if timezone.now() - row.created_at > PREPARED_TTL:
        return 'tip_expired'
    if _sent_today(row.sender, committed_only=True, exclude_id=row.id) + row.amount > DAILY_USD:
        return 'tip_daily_limit'
    if Tip.objects.filter(sender_id=row.sender_id, recipient_id=row.recipient_id, status=TipStatus.SENT,
                          updated_at__gte=timezone.now() - IN_FLIGHT_WINDOW).exclude(id=row.id).exists():
        return 'tip_in_flight'
    # Prepared in parallel before an earlier one confirmed: still needs the
    # sender's "send another" confirmation.
    if not row.repeat_confirmed and Tip.objects.filter(
            sender_id=row.sender_id, recipient_id=row.recipient_id, status=TipStatus.CONFIRMED,
            updated_at__gte=timezone.now() - REPEAT_WINDOW).exclude(id=row.id).exists():
        return 'tip_recent'
    row.send_transaction = send_tx
    row.status = TipStatus.SENT
    row.save(update_fields=['send_transaction', 'status', 'updated_at'])
    return None


# A bound tip send must be signed within this long of being prepared.
SUBMIT_TTL = timedelta(hours=1)
# Expiry only after this extra grace, and never with a sponsored batch on
# record: a submit that passed the check just in time is still broadcasting.
EXPIRY_GRACE = timedelta(minutes=10)


def _expired_unsigned():
    """Q for SENT tips whose send can never leave any more."""
    from django.db.models import Exists, OuterRef, Q

    from blockchain.models import SponsoredBatch
    from send.kinds import BSC_SEND_KINDS

    batches = SponsoredBatch.objects.filter(kind__in=BSC_SEND_KINDS, source_id=OuterRef('send_transaction_id'))
    no_hash = Q(send_transaction__transaction_hash='') | Q(send_transaction__transaction_hash__isnull=True)
    return (Q(status=TipStatus.SENT, send_transaction__status='PENDING',
              send_transaction__created_at__lt=timezone.now() - SUBMIT_TTL - EXPIRY_GRACE)
            & no_hash & ~Q(Exists(batches)))


def tip_submit_error(send_tx) -> str | None:
    """Re-checked at submit: the tip is still bound to this send, the send
    is fresh enough to stay inside the window its limit was counted in, and
    the recipient can still be tipped (a block since preparing wins)."""
    tip = Tip.objects.select_related('sender', 'recipient').filter(send_transaction=send_tx).first()
    if tip is None or tip.status != TipStatus.SENT:
        return 'tip_not_found'
    if timezone.now() - send_tx.created_at > SUBMIT_TTL:
        return 'tip_expired'
    block = tip_block(tip.sender, tip.recipient)
    if block:
        return 'tip_not_available'
    # Another tip to the same person went out meanwhile (another device, a
    # retry): this one needs the sender's "send another" confirmation too.
    if not tip.repeat_confirmed:
        others = Tip.objects.filter(sender_id=tip.sender_id, recipient_id=tip.recipient_id).exclude(id=tip.id)
        if (others.filter(status=TipStatus.CONFIRMED, updated_at__gte=timezone.now() - REPEAT_WINDOW).exists()
                or others.filter(status=TipStatus.SENT,
                                 send_transaction__status__in=['SUBMITTED', 'CONFIRMED']).exists()):
            return 'tip_recent'
    return None


def unresolved_sent_ids(limit=200):
    """Tips whose send already settled but the hook never ran (worker died,
    transient error): the sweeper finishes them. Tips whose send was never
    signed in time are failed here (the send can't leave any more)."""
    for tip_id in Tip.objects.filter(_expired_unsigned()).values_list('id', flat=True)[:limit]:
        Tip.objects.filter(_expired_unsigned(), id=tip_id).update(status=TipStatus.FAILED, updated_at=timezone.now())
    return list(Tip.objects.filter(status=TipStatus.SENT, send_transaction__status__in=['CONFIRMED', 'FAILED'])
                .values_list('id', flat=True)[:limit])


def resolve(tip_id: int) -> None:
    tip = Tip.objects.select_related('send_transaction').filter(id=tip_id).first()
    if tip is not None and tip.send_transaction is not None:
        on_send_resolved(tip.send_transaction)


def on_send_resolved(send_tx) -> None:
    """The send confirmed or failed. Never raises into the money path."""
    try:
        tip = Tip.objects.filter(send_transaction=send_tx).first()
        if tip is None:
            return
        if send_tx.status == 'CONFIRMED':
            _deliver(tip.id)
        elif send_tx.status == 'FAILED':
            Tip.objects.filter(id=tip.id, status=TipStatus.SENT).update(
                status=TipStatus.FAILED, updated_at=timezone.now())
    except Exception:  # noqa: BLE001
        logger.exception('tip hook failed', extra={'send_id': getattr(send_tx, 'id', None)})


def _deliver(tip_id: int) -> None:
    """The gift bubble in their conversation. A tip never changes a
    request's state and never opens one for someone with DMs off or a
    block in place (the money still arrived; SEND_RECEIVED already told them)."""
    from . import direct_messages as dm

    with transaction.atomic():
        tip = Tip.objects.select_for_update().get(id=tip_id)
        if tip.status != TipStatus.SENT:
            return
        tip.status = TipStatus.CONFIRMED
        # The money arrived either way; the note follows messaging's own
        # rules (a block, a ban or a report suspension keeps it out).
        if not dm.deliverable(tip.sender, tip.recipient_id):
            tip.save(update_fields=['status', 'updated_at'])
            return
        dm._lock_users(tip.sender_id, tip.recipient_id)
        conversation = dm.conversation_between(tip.sender_id, tip.recipient_id)
        if conversation is None:
            if not dm.dms_enabled(tip.recipient):
                tip.save(update_fields=['status', 'updated_at'])
                return
            low, high = dm._pair(tip.sender_id, tip.recipient_id)
            conversation = DirectConversation.objects.create(
                user_a_id=low, user_b_id=high, requested_by_id=tip.sender_id,
                status=DirectConversationStatus.REQUEST)
            DirectConversationMember.objects.bulk_create([
                DirectConversationMember(conversation=conversation, user_id=low),
                DirectConversationMember(conversation=conversation, user_id=high),
            ])
        now = timezone.now()
        message = DirectMessage.objects.create(
            conversation=conversation, sender_id=tip.sender_id, body=tip.note, kind=DirectMessage.KIND_TIP,
            tip_amount=tip.amount, unified_transaction=None,
            review_status=DirectMessageReview.APPROVED, decided_by_model='tip-note-review',
            delivered_at=now,
        )
        if conversation.status != DirectConversationStatus.DECLINED:
            conversation.last_message_at = now
            conversation.save(update_fields=['last_message_at', 'updated_at'])
            DirectConversationMember.objects.filter(conversation=conversation, user_id=tip.recipient_id,
                                                    hidden=True).update(hidden=False)
        DirectConversationMember.objects.filter(conversation=conversation, user_id=tip.sender_id,
                                                hidden=True).update(hidden=False)
        tip.message = message
        tip.save(update_fields=['status', 'message', 'updated_at'])


def received_total(user) -> Decimal:
    """What this member received in tips (shown on their own profile only)."""
    return (Tip.objects.filter(recipient=user, status=TipStatus.CONFIRMED)
            .aggregate(total=Sum('amount'))['total'] or Decimal('0'))
