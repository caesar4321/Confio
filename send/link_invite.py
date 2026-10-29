"""Link sends: the first send to a contact (spec phoneless-signup #6/#7).

The sender's app makes a one-time key, escrows the money under it through the
ordinary BSC invite flow (send/invite_bsc_flow.py, kind='link'), and opens the
contact's WhatsApp chat with a link carrying the key after '#'. Whoever opens
the link in Confío signs "pay me" with that key and the sponsor releases the
escrow to them. The server only ever sees the key's address.

A link is bearer money, so it is small: LINK_MAX_USD a link, DAILY_MAX_USD a
day per sender. Once a contact has claimed and the sender confirmed the
account (SavedRecipient), later sends to that number go direct, without
limits beyond the usual send rules.
"""
import logging
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

LINK_MAX_USD = Decimal('10')
DAILY_MAX_USD = Decimal('100')
STALE_PREPARE = timedelta(minutes=30)
SUBMIT_DEADLINE_MAX = timedelta(minutes=30)  # invite_bsc_flow.submit_create accepts deadlines up to now+1800s
SAVE_WINDOW = timedelta(days=30)
LEGACY_ACTIVE_DAYS = 180
ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
# Counted toward the sender's daily link total ('draft' only while fresh).
COUNTED_STATUSES = ('creating', 'pending', 'claiming', 'claimed')


def stale_link_prepare(invite) -> bool:
    return invite.status == 'draft' and invite.created_at < timezone.now() - STALE_PREPARE


def _phone_key(phone: str) -> str:
    from users.phone_utils import phone_lookup_key
    return phone_lookup_key(phone) or ''


def links_today_usd(sender) -> Decimal:
    from .models import PhoneInvite
    now = timezone.now()
    # A link is submitted up to STALE_PREPARE after its prepare and its batch
    # may mine up to 30 minutes after that (the submit deadline), so the window
    # reaches that much further back: a link funded late still counts 24 hours.
    rows = PhoneInvite.objects.filter(
        inviter_user=sender, kind='link',
        created_at__gte=now - timedelta(hours=24) - STALE_PREPARE - SUBMIT_DEADLINE_MAX,
        deleted_at__isnull=True)
    total = Decimal('0')
    for invite in rows.only('amount', 'status', 'created_at'):
        if invite.status in COUNTED_STATUSES or (invite.status == 'draft' and not stale_link_prepare(invite)):
            total += invite.amount
    return total


def prepare_link(sender, jwt_ctx, phone: str, amount, token_type: str, claim_key_address: str) -> dict:
    from . import invite_bsc_flow
    if not getattr(settings, 'LINK_INVITE_ENABLED', False):
        return {'success': False, 'error': 'link_invite_disabled'}
    if not ADDRESS_RE.match(claim_key_address or ''):
        return {'success': False, 'error': 'bad_claim_key'}
    # The limits are dollars: a link carries a dollar token only.
    if (token_type or '').upper() not in ('CUSD_PLUS', 'CUSD'):
        return {'success': False, 'error': 'link_token_not_supported'}
    phone_key = _phone_key(phone)
    if not phone_key or ':' not in phone_key:
        return {'success': False, 'error': 'bad_phone'}
    try:
        amount_usd = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        return {'success': False, 'error': 'invalid_amount'}
    if amount_usd <= 0:
        return {'success': False, 'error': 'invalid_amount'}
    if amount_usd > LINK_MAX_USD:
        return {'success': False, 'error': 'link_amount_over_limit'}
    from .models import PhoneInvite
    with transaction.atomic():
        type(sender).objects.select_for_update().filter(pk=sender.pk).first()
        # One open link per contact. A submit whose answer was lost is already
        # 'creating' or 'pending' on chain: a retry must re-share that link,
        # not escrow a second one under a new key.
        open_link = PhoneInvite.objects.filter(
            inviter_user=sender, kind='link', phone_key=phone_key, deleted_at__isnull=True,
            status__in=('creating', 'pending', 'claiming')).order_by('-created_at').first()
        if open_link:
            return {'success': False, 'error': 'link_already_pending', 'public_ref': str(open_link.public_ref)}
        if links_today_usd(sender) + amount_usd > DAILY_MAX_USD:
            return {'success': False, 'error': 'link_daily_limit'}
        return invite_bsc_flow.prepare_create(
            sender, jwt_ctx, phone_key, token_type, amount_usd,
            phone_display=phone, link_claim_address=claim_key_address)


def claim_message(invite, recipient_address: str) -> str:
    from .invite_bsc_flow import _escrow
    return ('Confio link claim\n'
            f'chain:{int(getattr(settings, "BSC_CHAIN_ID", 56))}\n'
            f'escrow:{_escrow()}\n'
            f'invite:0x{invite.invitation_id}\n'
            f'recipient:{recipient_address.lower()}')


def _personal_address(user) -> str:
    account = user.accounts.filter(account_type='personal', account_index=0, deleted_at__isnull=True).first()
    return ((getattr(account, 'bsc_address', None) or '') or '').lower()


def _find(public_ref):
    from .models import PhoneInvite
    try:
        return PhoneInvite.objects.select_related('inviter_user').get(
            public_ref=public_ref, kind='link', rail='bsc', deleted_at__isnull=True)
    except (PhoneInvite.DoesNotExist, ValueError, Exception):  # noqa: BLE001 — a malformed ref is "not found"
        return None


def short_name(user) -> str:
    from users.name_visibility import short_name as _short_name
    return _short_name(user)


def link_summary(public_ref, viewer=None) -> dict | None:
    invite = _find(public_ref)
    if invite is None or invite.inviter_user is None:
        return None
    from security.identity_status import is_identity_verified
    sender = invite.inviter_user
    is_mine = viewer is not None and viewer.pk == invite.inviter_user_id
    recipient_address = _personal_address(viewer) if viewer is not None and not is_mine else ''
    return {
        'sender_username': sender.username, 'sender_name': short_name(sender),
        'sender_verified': is_identity_verified(sender),
        'amount': invite.amount, 'token_type': invite.token_type,
        'status': invite.status, 'expires_at': invite.expires_at,
        'is_mine': is_mine,
        'claim_message': claim_message(invite, recipient_address) if recipient_address else '',
    }


def claim_link(user, public_ref, signature: str) -> dict:
    """The caller's personal account receives the link's money if `signature`
    is the link key's signature over claim_message(invite, that account)."""
    from eth_account import Account as EthAccount
    from eth_account.messages import encode_defunct
    from .invite_bsc_flow import claim_for_recipient

    invite = _find(public_ref)
    if invite is None:
        return {'success': False, 'error': 'link_not_found'}
    if invite.status in ('claiming', 'claimed'):
        return {'success': invite.claimed_by_id == user.pk, 'status': invite.status,
                'error': None if invite.claimed_by_id == user.pk else 'link_already_claimed'}
    if invite.status != 'pending':
        return {'success': False, 'status': invite.status, 'error': 'link_not_claimable'}
    if invite.inviter_user_id == user.pk:
        return {'success': False, 'error': 'link_is_yours'}
    if invite.expires_at and invite.expires_at <= timezone.now():
        return {'success': False, 'error': 'link_expired'}
    recipient_address = _personal_address(user)
    if not recipient_address:
        return {'success': False, 'error': 'missing_bsc_address'}
    try:
        signer = EthAccount.recover_message(
            encode_defunct(text=claim_message(invite, recipient_address)), signature=signature)
    except Exception:  # noqa: BLE001 — any malformed signature is simply wrong
        return {'success': False, 'error': 'bad_signature'}
    if signer.lower() != (invite.claim_key_address or '').lower():
        return {'success': False, 'error': 'bad_signature'}
    result = claim_for_recipient(invite, user, via_link=True, expected_recipient_address=recipient_address)
    if result.get('success'):
        return {'success': True, 'status': 'claiming', 'transaction_hash': result.get('transaction_hash')}
    return {'success': False, 'error': result.get('error')}


# ── Who a contact number reaches, for this sender ─────────────────────────

def _legacy_holder(phone_key: str, sender):
    """The one active, non-reviewer account holding this OTP-verified number
    and seen in the last LEGACY_ACTIVE_DAYS (carriers recycle numbers)."""
    from django.contrib.auth import get_user_model
    from users.review_numbers import is_shared_reviewer_phone_key
    if not phone_key or is_shared_reviewer_phone_key(phone_key):
        return None
    since = timezone.now() - timedelta(days=LEGACY_ACTIVE_DAYS)
    matches = list(get_user_model().objects.filter(
        phone_key=phone_key, is_active=True, last_activity_at__gte=since)[:2])
    if len(matches) != 1 or matches[0].pk == sender.pk:
        return None
    return matches[0]


def _unsaved_claim(sender, phone_key: str, after=None):
    """The newest link to this number claimed within SAVE_WINDOW (and after
    any "forget"), by an active account other than the sender."""
    from .models import PhoneInvite
    rows = PhoneInvite.objects.filter(
        inviter_user=sender, phone_key=phone_key, kind='link', status='claimed', deleted_at__isnull=True,
        claimed_by__isnull=False, claimed_by__is_active=True,
        claimed_at__gte=timezone.now() - SAVE_WINDOW,
    ).exclude(claimed_by=sender).select_related('claimed_by')
    if after is not None:
        rows = rows.filter(claimed_at__gt=after)
    return rows.order_by('-claimed_at').first()


def resolve(sender, phone: str) -> dict:
    """{'kind': 'SAVED'|'CLAIMED'|'LEGACY'|'NONE', 'user': User|None, 'public_ref'?}"""
    from .models import RecipientRevocation, SavedRecipient
    phone_key = _phone_key(phone)
    if not phone_key:
        return {'kind': 'NONE', 'user': None}
    saved = SavedRecipient.objects.filter(
        sender_user=sender, phone_key=phone_key, deleted_at__isnull=True).select_related('recipient_user').first()
    if saved and saved.recipient_user.is_active:
        return {'kind': 'SAVED', 'user': saved.recipient_user}
    revocation = RecipientRevocation.objects.filter(sender_user=sender, phone_key=phone_key).first()
    claimed = _unsaved_claim(sender, phone_key, after=revocation.revoked_at if revocation else None)
    if claimed:
        # The contact opened a link: the sender confirms that account before
        # it becomes where this number's money goes (save_from_link).
        return {'kind': 'CLAIMED', 'user': claimed.claimed_by, 'public_ref': str(claimed.public_ref)}
    if revocation:
        return {'kind': 'NONE', 'user': None}
    holder = _legacy_holder(phone_key, sender)
    if holder:
        return {'kind': 'LEGACY', 'user': holder}
    return {'kind': 'NONE', 'user': None}


def _replace_saved(sender, phone_key, recipient, source, basis_at) -> bool:
    from .models import RecipientRevocation, SavedRecipient
    active = SavedRecipient.objects.filter(sender_user=sender, phone_key=phone_key, deleted_at__isnull=True).first()
    if active and active.basis_at > basis_at:
        return False
    if active:
        active.soft_delete()
    SavedRecipient.objects.create(sender_user=sender, phone_key=phone_key, recipient_user=recipient,
                                  source=source, basis_at=basis_at)
    RecipientRevocation.objects.filter(sender_user=sender, phone_key=phone_key).delete()
    return True


def save_from_link(sender, public_ref) -> dict:
    invite = _find(public_ref)
    if invite is None or invite.inviter_user_id != sender.pk:
        return {'success': False, 'error': 'link_not_found'}
    if invite.status != 'claimed' or not invite.claimed_by_id or not invite.claimed_at:
        return {'success': False, 'error': 'link_not_claimed'}
    if invite.claimed_at < timezone.now() - SAVE_WINDOW:
        return {'success': False, 'error': 'link_save_expired'}
    from .models import RecipientRevocation
    with transaction.atomic():
        type(sender).objects.select_for_update().filter(pk=sender.pk).first()
        # A save that arrives after "forget" for a claim before it would undo
        # the sender's no: only a claim made after the forget can be saved.
        revocation = RecipientRevocation.objects.filter(sender_user=sender, phone_key=invite.phone_key).first()
        if revocation and invite.claimed_at <= revocation.revoked_at:
            return {'success': False, 'error': 'forgotten'}
        if not _replace_saved(sender, invite.phone_key, invite.claimed_by, 'link_claim', invite.claimed_at):
            return {'success': False, 'error': 'stale'}
    return {'success': True}


def save_legacy(sender, phone: str, recipient_user_id=None) -> dict:
    """Keep the legacy holder the sender just paid. `recipient_user_id` is
    the account the send went to: if the number now resolves to someone else,
    nothing is saved (never a silent substitution)."""
    phone_key = _phone_key(phone)
    with transaction.atomic():
        type(sender).objects.select_for_update().filter(pk=sender.pk).first()
        from .models import RecipientRevocation
        if RecipientRevocation.objects.filter(sender_user=sender, phone_key=phone_key).exists():
            return {'success': False, 'error': 'revoked'}
        # It only fills an empty slot: a save arriving late from an old legacy
        # send never replaces a recipient the sender has confirmed since.
        from .models import SavedRecipient
        if SavedRecipient.objects.filter(sender_user=sender, phone_key=phone_key, deleted_at__isnull=True).exists():
            return {'success': False, 'error': 'already_saved'}
        holder = _legacy_holder(phone_key, sender)
        if not holder:
            return {'success': False, 'error': 'not_legacy'}
        if str(holder.pk) != str(recipient_user_id or ''):
            return {'success': False, 'error': 'recipient_changed'}
        _replace_saved(sender, phone_key, holder, 'legacy_phone', timezone.now())
    return {'success': True}


def forget(sender, phone: str) -> dict:
    from .models import RecipientRevocation, SavedRecipient
    phone_key = _phone_key(phone)
    if not phone_key:
        return {'success': False, 'error': 'bad_phone'}
    with transaction.atomic():
        type(sender).objects.select_for_update().filter(pk=sender.pk).first()
        SavedRecipient.objects.filter(sender_user=sender, phone_key=phone_key, deleted_at__isnull=True).update(
            deleted_at=timezone.now())
        # A second "forget" moves the cut-off, so claims before it stay forgotten.
        RecipientRevocation.objects.update_or_create(
            sender_user=sender, phone_key=phone_key, defaults={'revoked_at': timezone.now()})
    return {'success': True}


# ── Enviar's people list ──────────────────────────────────────────────────

def recent_people(sender, limit: int = 20) -> list:
    """People the sender has moved money with (confirmed sends either way,
    claimed links either way; never a Propina, which is pseudonymous), newest first. Exactly the people whose names
    the sender may see (users/name_visibility.py)."""
    from django.contrib.auth import get_user_model
    from django.db.models import Max, Q
    from .models import PhoneInvite, SendTransaction
    last = {}

    def note(user_id, at):
        if user_id and user_id != sender.pk and (user_id not in last or at > last[user_id]):
            last[user_id] = at

    for row in SendTransaction.objects.filter(
        sender_user=sender, recipient_user__isnull=False, recipient_business__isnull=True,
        status='CONFIRMED', deleted_at__isnull=True,
    ).exclude(idempotency_key__startswith='tip-').order_by().values('recipient_user_id').annotate(at=Max('created_at')):
        note(row['recipient_user_id'], row['at'])
    for row in SendTransaction.objects.filter(
        recipient_user=sender, sender_user__isnull=False, sender_business__isnull=True,
        status='CONFIRMED', deleted_at__isnull=True,
    ).exclude(idempotency_key__startswith='tip-').order_by().values('sender_user_id').annotate(at=Max('created_at')):
        note(row['sender_user_id'], row['at'])
    for row in PhoneInvite.objects.filter(
        Q(inviter_user=sender) | Q(claimed_by=sender), status='claimed', claimed_at__isnull=False,
        deleted_at__isnull=True,
    ).order_by().values('inviter_user_id', 'claimed_by_id', 'claimed_at'):
        note(row['claimed_by_id'] if row['inviter_user_id'] == sender.pk else row['inviter_user_id'],
             row['claimed_at'])
    ids = [uid for uid, _ in sorted(last.items(), key=lambda item: item[1], reverse=True)[:limit]]
    users = {u.pk: u for u in get_user_model().objects.filter(pk__in=ids, is_active=True)}
    return [users[uid] for uid in ids if uid in users]


def saved_phone_keys(sender) -> list:
    """Numbers the sender confirmed (SavedRecipient): the app tags these
    contacts locally. The sender gave Confío each of them already."""
    from .models import SavedRecipient
    return list(SavedRecipient.objects.filter(
        sender_user=sender, deleted_at__isnull=True, recipient_user__is_active=True,
    ).values_list('phone_key', flat=True))
