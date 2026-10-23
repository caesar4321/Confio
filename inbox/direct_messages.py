"""Mensajes: private conversations between two Comunidad members.

Rules (spec caesar4321/Confio#6, children #3–#4):

- Only identity-verified members who accepted the community rules send.
  Anyone can receive unless they turned DMs off (existing chats continue).
- Portfolios are reciprocal: a member whose own profile is hidden can reply
  in existing chats but can't start new ones.
- The first message to someone who doesn't follow you is a REQUEST: it
  lands in their Solicitudes. They accept it (or reply) to make it ACTIVE,
  or delete it (DECLINED: the sender's further messages go nowhere). Until
  then the sender can send REQUEST_CAP messages.
- Limits per sender: NEW_CONVERSATIONS_PER_DAY, MESSAGES_PER_DAY, MAX_CHARS.
- Every message is stored PENDING and only APPROVED ones are delivered or
  pushed (dm_gate: deterministic prefilter, then Luna→Sol). A prefilter hit
  is REJECTED at once; a review that can't decide becomes FAILED. The sender
  sees their own in every state, with the reason; the recipient never sees
  anything else.
- A block (CommunityBlock) in either direction hides the conversation both
  ways and stops delivery. Distinct verified reporters reaching
  REPORT_SUSPEND_THRESHOLD within REPORT_WINDOW suspend the sender's DMs.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from . import community, dm_gate
from .community import CommunityPostError, ReviewUnavailable
from .models import (
    CommunityFollow,
    CommunityProfileSettings,
    DirectConversation,
    DirectConversationMember,
    DirectConversationStatus as Status,
    DirectMessage,
    DirectMessageReport,
    DirectMessageReview as Review,
)

logger = logging.getLogger(__name__)

MAX_CHARS = 1000
NEW_CONVERSATIONS_PER_DAY = 20
MESSAGES_PER_DAY = 300
REQUEST_CAP = 3
REPORT_SUSPEND_THRESHOLD = 3
REPORT_WINDOW = timedelta(days=7)
MAX_REVIEW_ATTEMPTS = community.MAX_REVIEW_ATTEMPTS
STUCK_AFTER = timedelta(minutes=5)
PAGE_SIZE = 30

# Codes the app maps (with the message as fallback copy).
NOT_AVAILABLE = 'not_available'
IDENTITY_REQUIRED = 'identity_required'
RULES_REQUIRED = 'rules_required'
PROFILE_HIDDEN = 'portfolio_must_be_public'
DMS_DISABLED = 'dms_disabled'
REQUEST_LIMIT = 'request_cap'
RATE_LIMITED = 'rate_limited'
SUSPENDED = 'suspended'

MESSAGES = {
    NOT_AVAILABLE: 'No puedes escribirle a esta persona.',
    IDENTITY_REQUIRED: 'Verifica tu identidad para enviar mensajes.',
    RULES_REQUIRED: 'Acepta las normas de la comunidad para enviar mensajes.',
    PROFILE_HIDDEN: 'Haz público tu portafolio para escribirle a otros inversores.',
    DMS_DISABLED: 'Esta persona no recibe mensajes nuevos.',
    REQUEST_LIMIT: 'Espera a que acepte tu solicitud para seguir escribiendo.',
    RATE_LIMITED: 'Llegaste al límite de mensajes de hoy. Vuelve mañana.',
    SUSPENDED: 'Tus mensajes están pausados por reportes de otros miembros.',
}

FAILED_REASON = 'No pudimos revisar tu mensaje. Inténtalo de nuevo.'


def _error(code: str) -> CommunityPostError:
    return CommunityPostError(code, MESSAGES[code])


def _pair(a_id: int, b_id: int) -> tuple[int, int]:
    return (a_id, b_id) if a_id < b_id else (b_id, a_id)


def conversation_between(a_id, b_id):
    low, high = _pair(a_id, b_id)
    return DirectConversation.objects.filter(user_a_id=low, user_b_id=high).first()


def dms_enabled(user) -> bool:
    value = CommunityProfileSettings.objects.filter(user=user).values_list('dms_enabled', flat=True).first()
    return True if value is None else bool(value)


def set_dms_enabled(user, enabled: bool) -> bool:
    CommunityProfileSettings.objects.update_or_create(user=user, defaults={'dms_enabled': bool(enabled)})
    return bool(enabled)


def is_suspended(user) -> bool:
    """Reports from distinct verified members on this sender's messages."""
    since = timezone.now() - REPORT_WINDOW
    reporters = set(
        DirectMessageReport.objects.filter(message__sender=user, created_at__gte=since)
        .values_list('reporter_id', flat=True)
    )
    if len(reporters) < REPORT_SUSPEND_THRESHOLD:
        return False
    return community.personally_verified_count(reporters) >= REPORT_SUSPEND_THRESHOLD


def _sender_block(sender) -> str | None:
    if community.author_block(sender):
        return IDENTITY_REQUIRED if not community.is_verified_member(sender) else NOT_AVAILABLE
    if not community.has_accepted_rules(sender):
        return RULES_REQUIRED
    if is_suspended(sender):
        return SUSPENDED
    return None


def _recipient(user_id):
    from users.models import User

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    return User.objects.filter(id=user_id, deleted_at__isnull=True, is_active=True).first()


def send_block(sender, target) -> str | None:
    """Why `sender` can't write to `target` right now (None: they can).
    The profile's Mensaje button and send_message share this."""
    if target is None or target.id == sender.id:
        return NOT_AVAILABLE
    block = _sender_block(sender)
    if block:
        return block
    # Anyone can receive (verified or not); a banned or removed account can't.
    if community.is_blocked_between(sender.id, target.id) or community.author_block(target) == community.BLOCK_BANNED:
        return NOT_AVAILABLE
    conversation = conversation_between(sender.id, target.id)
    if conversation is not None:
        if conversation.status == Status.ACTIVE:
            return None
        if conversation.requested_by_id == target.id:
            return None                    # replying to their request accepts it
        # The requester sees a declined request exactly like an unanswered one.
    # Starting (or continuing an unanswered request): the new-contact rules.
    if community.portfolio_hidden(sender):
        return PROFILE_HIDDEN
    if conversation is None and not dms_enabled(target):
        return DMS_DISABLED
    return None


def _lock_users(*user_ids):
    """Row locks in id order: the sender's counters, and the pair's first
    contact when two people write to each other at once (never a deadlock)."""
    from users.models import User

    for user_id in sorted({u for u in user_ids if u}):
        User.objects.select_for_update().filter(pk=user_id).first()


def send_message(sender, business, body: str, *, recipient_id=None, conversation_id=None,
                 client_key: str = '', kind: str = DirectMessage.KIND_TEXT) -> DirectMessage:
    """Store the message (PENDING, or REJECTED by the prefilter) and queue
    its review. Raises CommunityPostError with a code from MESSAGES."""
    if business is not None:
        raise CommunityPostError(NOT_AVAILABLE, 'Los mensajes se envían desde tu cuenta personal.')
    body = (body or '').strip()
    client_key = (client_key or '').strip()[:64]
    if not body and kind == DirectMessage.KIND_TEXT:
        raise CommunityPostError('empty', 'Escribe tu mensaje.')
    if len(body) > MAX_CHARS:
        raise CommunityPostError('too_long', f'Tu mensaje supera los {MAX_CHARS} caracteres.')
    if client_key:
        existing = DirectMessage.objects.filter(sender=sender, client_key=client_key).first()
        if existing is not None:
            return existing

    # Who the other person is, before locking both of them.
    if conversation_id is not None:
        pair = DirectConversation.objects.filter(id=conversation_id).values_list('user_a_id', 'user_b_id').first()
        if pair is None or sender.id not in pair:
            raise _error(NOT_AVAILABLE)
        other_id = pair[1] if pair[0] == sender.id else pair[0]
    else:
        target = _recipient(recipient_id)
        other_id = target.id if target is not None else None

    with transaction.atomic():
        _lock_users(sender.pk, other_id)
        if client_key:
            # A retry that raced the first attempt: same message, never a cap error.
            existing = DirectMessage.objects.filter(sender=sender, client_key=client_key).first()
            if existing is not None:
                return existing
        target = _recipient(other_id)
        conversation = None
        if target is not None:
            low, high = _pair(sender.id, target.id)
            conversation = DirectConversation.objects.select_for_update().filter(
                user_a_id=low, user_b_id=high).first()
        if conversation_id is not None and (conversation is None or conversation.id != int(conversation_id)):
            raise _error(NOT_AVAILABLE)
        block = send_block(sender, target)
        if block:
            raise _error(block)

        now = timezone.now()
        since = now - timedelta(hours=24)
        if DirectMessage.objects.filter(sender=sender, created_at__gte=since).count() >= MESSAGES_PER_DAY:
            raise _error(RATE_LIMITED)
        if conversation is None:
            started = DirectConversation.objects.filter(requested_by=sender, created_at__gte=since).count()
            if started >= NEW_CONVERSATIONS_PER_DAY:
                raise _error(RATE_LIMITED)
            low, high = _pair(sender.id, target.id)
            follows_back = CommunityFollow.objects.filter(follower=target, followed=sender).exists()
            conversation = DirectConversation.objects.create(
                user_a_id=low, user_b_id=high, requested_by=sender,
                status=Status.ACTIVE if follows_back else Status.REQUEST,
            )
            DirectConversationMember.objects.bulk_create([
                DirectConversationMember(conversation=conversation, user_id=low),
                DirectConversationMember(conversation=conversation, user_id=high),
            ])
        elif conversation.status in (Status.REQUEST, Status.DECLINED):
            # Declined behaves exactly like unanswered for the sender: the
            # cap can't reveal that the recipient deleted the request.
            if conversation.requested_by_id == sender.id:
                sent = conversation.messages.filter(sender=sender).exclude(
                    review_status__in=[Review.REJECTED, Review.FAILED]).count()
                if sent >= REQUEST_CAP:
                    raise _error(REQUEST_LIMIT)
            else:
                # The recipient writing back accepts it, and also reopens a
                # request they had deleted earlier.
                conversation.status = Status.ACTIVE
                conversation.save(update_fields=['status', 'updated_at'])

        # Writing again brings a deleted chat back to the sender's own list.
        DirectConversationMember.objects.filter(conversation=conversation, user=sender, hidden=True).update(hidden=False)
        refused = dm_gate.prefilter(body) if body else None
        try:
            with transaction.atomic():
                message = DirectMessage.objects.create(
                    conversation=conversation, sender=sender, body=body, kind=kind, client_key=client_key,
                    review_status=Review.REJECTED if refused else Review.PENDING,
                    category='contact_info' if refused else '',
                    reason=refused or '',
                    decided_by_model='prefilter' if refused else '',
                )
        except IntegrityError:
            # Same client key raced in from a retry: hand back the first one.
            return DirectMessage.objects.get(sender=sender, client_key=client_key)
        if not refused:
            transaction.on_commit(lambda: enqueue_review(message.id))
    return message


def enqueue_review(message_id: int):
    from .tasks import review_direct_message_task

    review_direct_message_task.delay(message_id)


def run_review(message_id: int) -> str:
    """One review attempt. Raises ReviewUnavailable (with .claim) to retry."""
    with transaction.atomic():
        message = DirectMessage.objects.select_for_update().filter(id=message_id).first()
        if message is None or message.review_status != Review.PENDING:
            return message.review_status if message else 'missing'
        if message.attempts >= MAX_REVIEW_ATTEMPTS:
            _fail(message, 'Out of review attempts')
            return message.review_status
        message.attempts += 1
        claim = community.new_claim()
        message.claim_token = claim
        message.save(update_fields=['attempts', 'claim_token', 'updated_at'])
        body = message.body
    try:
        verdict, escalated, verdicts = dm_gate.review(body)
    except ReviewUnavailable as exc:
        exc.claim = claim
        raise
    return _finalize(message_id, claim, verdict, escalated=escalated, verdicts=verdicts)


def _fail(message, error=''):
    message.review_status = Review.FAILED
    message.reason = FAILED_REASON
    message.verdicts = list(message.verdicts or []) + [{'error': str(error)[:200]}]
    message.save(update_fields=['review_status', 'reason', 'verdicts', 'updated_at'])


def mark_failed(message_id: int, error: str = '', *, claim=None, stale_before=None) -> bool:
    with transaction.atomic():
        message = DirectMessage.objects.select_for_update().filter(id=message_id).first()
        if message is None or message.review_status != Review.PENDING:
            return False
        if claim is not None and message.claim_token != claim:
            return False
        if stale_before is not None and message.updated_at >= stale_before:
            return False
        _fail(message, error)
    return True


def _finalize(message_id, claim, verdict, *, escalated, verdicts) -> str:
    with transaction.atomic():
        # Only the message row: locking the joined sender would invert the
        # order send_message takes (users, then the conversation).
        message = DirectMessage.objects.select_for_update(of=('self',)).select_related(
            'conversation', 'sender').get(id=message_id)
        if message.review_status != Review.PENDING or message.claim_token != claim:
            return message.review_status
        conversation = DirectConversation.objects.select_for_update().get(id=message.conversation_id)
        recipient_id = conversation.other_id(message.sender_id)
        if verdict['decision'] == 'approve' and not deliverable(message.sender, recipient_id):
            verdict = {'decision': 'reject', 'category': 'ineligible', 'confidence': 1.0,
                       'reason': MESSAGES[NOT_AVAILABLE], 'model': 'eligibility-check'}
            verdicts = [*verdicts, verdict]
        message.verdicts = list(message.verdicts or []) + list(verdicts)
        message.escalated = escalated
        message.decided_by_model = verdict.get('model', '')
        message.category = verdict.get('category', '')
        if verdict['decision'] == 'approve':
            now = timezone.now()
            message.review_status = Review.APPROVED
            message.reason = ''
            message.delivered_at = now
            conversation.last_message_at = now
            conversation.save(update_fields=['last_message_at', 'updated_at'])
            if conversation.status != Status.DECLINED:
                # A chat the recipient deleted comes back with a new message.
                DirectConversationMember.objects.filter(
                    conversation=conversation, user_id=recipient_id, hidden=True).update(hidden=False)
                transaction.on_commit(lambda: notify_recipient(message_id))
        else:
            message.review_status = Review.REJECTED
            message.reason = str(verdict.get('reason') or '')[:280] or 'Tu mensaje no cumple las normas de la comunidad.'
        message.save()
        return message.review_status


def deliverable(sender, recipient_id) -> bool:
    """Re-checked at approval and again at push: a ban, a block or a report
    suspension since the message was written means it never goes out."""
    return not (community.author_block(sender)
                or community.is_blocked_between(sender.id, recipient_id)
                or is_suspended(sender))


def stuck_ids():
    cutoff = timezone.now() - STUCK_AFTER
    stuck = DirectMessage.objects.filter(review_status=Review.PENDING, updated_at__lt=cutoff)
    retry = list(stuck.filter(attempts__lt=MAX_REVIEW_ATTEMPTS).values_list('id', flat=True)[:200])
    exhausted = list(stuck.filter(attempts__gte=MAX_REVIEW_ATTEMPTS).values_list('id', flat=True)[:200])
    return retry, exhausted, cutoff


# ── delivery ─────────────────────────────────────────────────────────────────

PUSH_TYPE = 'COMMUNITY_DIRECT_MESSAGE'


def chat_link(conversation_id) -> str:
    return f'confio://community/chat/{conversation_id}'


def notify_recipient(message_id: int):
    """Push only (no row in the notifications list: a chat would flood it).
    Respects the recipient's push switch."""
    from notifications.fcm_service import send_batch_notifications
    from notifications.models import FCMDeviceToken, NotificationPreference

    message = DirectMessage.objects.select_related('conversation', 'sender').filter(
        id=message_id, review_status=Review.APPROVED).first()
    if message is None:
        return False
    conversation = message.conversation
    if conversation.status == Status.DECLINED:
        return False
    recipient_id = conversation.other_id(message.sender_id)
    if not deliverable(message.sender, recipient_id):
        return False
    from users.models import User

    recipient = User.objects.filter(id=recipient_id).first()
    if recipient is None:
        return False
    try:
        if not recipient.notification_preferences.push_enabled:
            return False
    except NotificationPreference.DoesNotExist:
        pass
    tokens = list(FCMDeviceToken.objects.filter(user=recipient, is_active=True).values_list('token', 'id'))
    if not tokens:
        return False
    handle = community.author_handle(message.sender)
    if conversation.status == Status.REQUEST:
        title, body = 'Nueva solicitud de mensaje', f'{handle} quiere escribirte'
    elif message.kind == DirectMessage.KIND_TIP:
        title, body = f'{handle} te envió una propina', message.body[:120] or 'Toca para verla.'
    else:
        title, body = handle, message.body[:120]
    data = {
        'notification_type': PUSH_TYPE,
        'action_url': chat_link(conversation.id),
        'account_context': 'personal',
        'account_type': 'personal',
        'account_index': '0',
        'conversation_id': str(conversation.id),
    }
    try:
        send_batch_notifications(tokens=tokens, title=title, body=body, data=data, channel_id='community')
    except Exception:
        logger.exception('DM push failed', extra={'message_id': message_id})
        return False
    return True


# ── reading ──────────────────────────────────────────────────────────────────

def member_of(user, conversation_id):
    """The member row, if this user is in the conversation."""
    return DirectConversationMember.objects.select_related('conversation').filter(
        conversation_id=conversation_id, user=user).first()


def visible_messages(conversation, user, cleared_at=None):
    """What `user` may see: every approved message, plus their own in any state."""
    qs = conversation.messages.filter(Q(review_status=Review.APPROVED) | Q(sender=user))
    if conversation.status == Status.DECLINED and conversation.requested_by_id != user.id:
        # A declined request shows the recipient nothing new.
        qs = qs.filter(sender=user)
    if cleared_at is not None:
        # What arrived after they deleted the chat, by when it ARRIVED: a
        # message approved later shows even if it was written before.
        qs = qs.filter(Q(delivered_at__gt=cleared_at, review_status=Review.APPROVED) & ~Q(sender=user)
                       | Q(sender=user, created_at__gt=cleared_at))
    return qs


def is_incoming_request(conversation, user) -> bool:
    return conversation.status == Status.REQUEST and conversation.requested_by_id != user.id


def conversations(user, folder: str):
    """(conversation, member) pairs, newest first. 'requests' = incoming
    requests; 'inbox' = everything else the member can see."""
    blocked = community.block_relation_ids(user)
    members = (DirectConversationMember.objects.filter(user=user, hidden=False)
               .select_related('conversation', 'conversation__user_a', 'conversation__user_b'))
    out = []
    for member in members:
        conversation = member.conversation
        other_id = conversation.other_id(user.id)
        if other_id in blocked:
            continue
        incoming = conversation.requested_by_id != user.id
        if conversation.status == Status.DECLINED and incoming:
            continue
        if incoming and conversation.last_message_at is None:
            continue                       # nothing approved has reached them yet
        if (folder == 'requests') != is_incoming_request(conversation, user):
            continue
        out.append((conversation, member))
    out.sort(key=lambda pair: pair[0].last_message_at or pair[0].created_at, reverse=True)
    return out


def unread_count(conversation, member) -> int:
    qs = conversation.messages.filter(review_status=Review.APPROVED).exclude(sender_id=member.user_id)
    if member.last_read_at:
        qs = qs.filter(delivered_at__gt=member.last_read_at)
    if member.cleared_at:
        qs = qs.filter(delivered_at__gt=member.cleared_at)
    return qs.count()


def unread_summary(user) -> tuple[int, int]:
    """(unread messages in Mensajes, incoming requests) for the badge."""
    unread = sum(unread_count(c, m) for c, m in conversations(user, 'inbox'))
    return unread, len(conversations(user, 'requests'))


# ── member actions ───────────────────────────────────────────────────────────

def accept_request(user, conversation_id) -> DirectConversation:
    with transaction.atomic():
        member = member_of(user, conversation_id)
        if member is None:
            raise _error(NOT_AVAILABLE)
        conversation = DirectConversation.objects.select_for_update().get(id=conversation_id)
        if is_incoming_request(conversation, user):
            conversation.status = Status.ACTIVE
            conversation.save(update_fields=['status', 'updated_at'])
    return conversation


def delete_conversation(user, conversation_id) -> bool:
    """Hide it from my list (and clear what I saw). An incoming request
    deleted this way is DECLINED: the sender is never told."""
    with transaction.atomic():
        # Conversation first, then the member: the order _finalize takes them.
        conversation = DirectConversation.objects.select_for_update().filter(id=conversation_id).first()
        member = DirectConversationMember.objects.select_for_update().filter(
            conversation_id=conversation_id, user=user).first() if conversation else None
        if member is None:
            return False
        if is_incoming_request(conversation, user):
            conversation.status = Status.DECLINED
            conversation.save(update_fields=['status', 'updated_at'])
        member.hidden = True
        member.cleared_at = timezone.now()
        member.save(update_fields=['hidden', 'cleared_at'])
    return True


def mark_read(user, conversation_id, up_to=None) -> bool:
    """Read up to `up_to` (the time of the page the app actually showed),
    never later than now and never backwards."""
    now = timezone.now()
    mark = min(up_to, now) if up_to else now
    with transaction.atomic():
        member = DirectConversationMember.objects.select_for_update().filter(
            conversation_id=conversation_id, user=user).first()
        if member is None:
            return False
        if member.last_read_at is None or mark > member.last_read_at:
            member.last_read_at = mark
            member.save(update_fields=['last_read_at'])
    return True


def report_message(user, message_id, reason: str = '') -> None:
    message = DirectMessage.objects.select_related('conversation').filter(
        id=message_id, review_status=Review.APPROVED).first()
    if message is None or message.sender_id == user.id or user.id not in (
            message.conversation.user_a_id, message.conversation.user_b_id):
        raise _error(NOT_AVAILABLE)
    DirectMessageReport.objects.get_or_create(message=message, reporter=user, defaults={'reason': (reason or '')[:280]})


def reported_senders(limit=50):
    """Admin queue helper: senders with the most distinct reporters lately."""
    since = timezone.now() - REPORT_WINDOW
    return list(DirectMessageReport.objects.filter(created_at__gte=since)
                .values('message__sender_id').annotate(n=Count('reporter', distinct=True))
                .order_by('-n')[:limit])
