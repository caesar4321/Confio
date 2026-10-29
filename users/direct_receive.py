"""Who may be paid by a direct personal send.

Sending to a friend is free; charging a customer goes through Cobrar (QR) and
its fee. A seller who has buyers send to their @usuario, a contact or a saved
recipient instead skips that fee, and buyers can send that way on their own,
so a nudge alone does not stop it. Hence a real block, enforced where every
direct send is prepared (send.bsc_flow.prepare_bsc_send, whatever named the
recipient: @usuario, phone, saved recipient, raw address) and where a link
send is claimed.

- Nudge: a personal account paid by NUDGE_PAYERS different people in 30 days
  is asked to use Cobrar; nothing is refused.
- Block: at BLOCK_PAYERS, or when an admin blocks it, direct personal sends
  to the account are refused; it keeps getting paid through Cobrar.
- An admin exemption (family remittances, say) stops the automatic block.

Payroll and Cobrar payments are not direct sends and are never affected.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

logger = logging.getLogger(__name__)

BLOCKED_ERROR = 'recipient_receives_by_qr_only'
BLOCKED_MESSAGE = ('Esta cuenta cobra con QR. Pedile su código de Cobrar para pagarle.')
WINDOW_DAYS = 30


def nudge_payers() -> int:
    return int(getattr(settings, 'DIRECT_RECEIVE_NUDGE_PAYERS', 10))


def block_payers() -> int:
    return int(getattr(settings, 'DIRECT_RECEIVE_BLOCK_PAYERS', 20))


def is_blocked(user) -> bool:
    return bool(user is not None and getattr(user, 'direct_receive_blocked_at', None))


def status(user) -> str:
    """'blocked' | 'nudge' | 'ok' — what Recibir tells the account holder."""
    if is_blocked(user):
        return 'blocked'
    if getattr(user, 'direct_receive_nudged_at', None):
        return 'nudge'
    return 'ok'


def distinct_payers(since=None):
    """{recipient user id: number of different payers} over confirmed direct
    sends to personal accounts (a payer is a user, or a business)."""
    from send.models import SendTransaction
    since = since or timezone.now() - timedelta(days=WINDOW_DAYS)
    rows = (SendTransaction.objects
            .filter(created_at__gte=since, status='CONFIRMED',
                    recipient_user__isnull=False, recipient_business__isnull=True)
            .exclude(sender_user_id=None, sender_business_id=None)
            .values('recipient_user_id')
            .annotate(users=Count('sender_user', distinct=True, filter=Q(sender_business__isnull=True)),
                      businesses=Count('sender_business', distinct=True)))
    return {row['recipient_user_id']: row['users'] + row['businesses'] for row in rows}


def refresh_flags() -> dict:
    """Daily: nudge or block by distinct payers. Never lifts a block (an admin
    does that), never blocks an exempt account, never touches an admin block."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    now = timezone.now()
    nudged = blocked = 0
    for user_id, payers in distinct_payers().items():
        if payers >= block_payers():
            blocked += User.objects.filter(
                pk=user_id, direct_receive_blocked_at__isnull=True, direct_receive_exempt=False,
            ).update(direct_receive_blocked_at=now, direct_receive_block_reason='auto')
        if payers >= nudge_payers():
            nudged += User.objects.filter(pk=user_id, direct_receive_nudged_at__isnull=True).update(
                direct_receive_nudged_at=now)
    if blocked:
        logger.warning('[DIRECT_RECEIVE] auto-blocked %s account(s)', blocked)
    return {'nudged': nudged, 'blocked': blocked}
