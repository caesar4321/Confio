"""Who may see whose name.

@usuario is public (Comunidad, investor profiles, Liga) and a phone number can
be guessed, so neither may be a key to someone's real name. A lookup by
either shows the handle, the avatar and the verified check; the name appears
only between two people who have already moved money with each other (a
confirmed send either way, or a link one of them sent and the other claimed).
"""
from django.core.cache import cache
from django.db.models import Q


def paid_each_other(viewer, user_ids) -> set:
    """The subset of `user_ids` that `viewer` has paid or been paid by."""
    from send.models import PhoneInvite, SendTransaction
    ids = {int(i) for i in user_ids if i is not None}
    if viewer is None or not ids:
        return set()
    known = set()
    for sender_id, recipient_id in SendTransaction.objects.filter(
        Q(sender_user=viewer, recipient_user_id__in=ids) | Q(recipient_user=viewer, sender_user_id__in=ids),
        status='CONFIRMED', deleted_at__isnull=True,
    ).exclude(idempotency_key__startswith='tip-').values_list('sender_user_id', 'recipient_user_id'):
        known.add(recipient_id if sender_id == viewer.pk else sender_id)
    for inviter_id, claimer_id in PhoneInvite.objects.filter(
        Q(inviter_user=viewer, claimed_by_id__in=ids) | Q(claimed_by=viewer, inviter_user_id__in=ids),
        status='claimed', deleted_at__isnull=True,
    ).values_list('inviter_user_id', 'claimed_by_id'):
        known.add(claimer_id if inviter_id == viewer.pk else inviter_id)
    return known & ids


def _business_peer_ids(viewer) -> set:
    """The owner and the employees who ACCEPTED an invitation, for each
    business the viewer owns or joined that way. Consent is the point: an
    owner could add anyone by phone (addBusinessEmployee, removed) or as a payroll
    recipient, and neither may reveal that person's name."""
    from users.models import Account
    from users.models_employee import EmployeeInvitation
    owned = set(Account.objects.filter(
        user=viewer, account_type='business', business__isnull=False, deleted_at__isnull=True,
    ).values_list('business_id', flat=True))
    joined = set(EmployeeInvitation.objects.filter(
        accepted_by=viewer, status='accepted', deleted_at__isnull=True,
    ).values_list('business_id', flat=True))
    business_ids = owned | joined
    if not business_ids:
        return set()
    ids = set(Account.objects.filter(
        business_id__in=business_ids, account_type='business', deleted_at__isnull=True,
    ).values_list('user_id', flat=True))
    ids |= set(EmployeeInvitation.objects.filter(
        business_id__in=business_ids, status='accepted', accepted_by__isnull=False, deleted_at__isnull=True,
    ).values_list('accepted_by_id', flat=True))
    return ids


def _counterparty_ids(viewer) -> set:
    """Everyone the viewer has moved money with: confirmed sends either way,
    claimed links either way, completed P2P trades, confirmed payments either way. order_by() is
    cleared so DISTINCT runs on the pair alone: one row per counterparty, not
    one per transaction."""
    from payments.models import PaymentTransaction
    from send.models import PhoneInvite, SendTransaction
    ids = set()
    # A Propina is between Comunidad pseudonyms: it never counts.
    for a, b in SendTransaction.objects.filter(
        Q(sender_user=viewer) | Q(recipient_user=viewer), status='CONFIRMED', deleted_at__isnull=True,
    ).exclude(idempotency_key__startswith='tip-').order_by().values_list('sender_user_id', 'recipient_user_id').distinct():
        ids.update((a, b))
    for a, b in PhoneInvite.objects.filter(
        Q(inviter_user=viewer) | Q(claimed_by=viewer), status='claimed', deleted_at__isnull=True,
    ).order_by().values_list('inviter_user_id', 'claimed_by_id').distinct():
        ids.update((a, b))
    from p2p_exchange.models import P2PTrade
    for a, b in P2PTrade.objects.filter(
        Q(buyer_user=viewer) | Q(seller_user=viewer), status='COMPLETED',
    ).order_by().values_list('buyer_user_id', 'seller_user_id').distinct():
        ids.update((a, b))
    for a, b in PaymentTransaction.objects.filter(
        Q(payer_user=viewer) | Q(merchant_account_user=viewer), status='CONFIRMED',
    ).order_by().values_list('payer_user_id', 'merchant_account_user_id').distinct():
        ids.update((a, b))
    ids.discard(None)
    return ids


def can_see_name(info, target) -> bool:
    """The one rule for GraphQL: a person's name goes to themselves, to staff,
    to anyone who has moved money with them, and within a business between
    its owner and the employees who accepted an invitation. Computed once per request (lists cost one pass, not one
    query per row)."""
    if target is None:
        return False
    viewer = getattr(getattr(info, 'context', None), 'user', None)
    if viewer is None or not getattr(viewer, 'is_authenticated', False):
        return False
    if viewer.pk == target.pk or getattr(viewer, 'is_staff', False):
        return True
    known = getattr(info.context, '_name_visible_ids', None)
    if known is None:
        known = _counterparty_ids(viewer) | _business_peer_ids(viewer)
        try:
            info.context._name_visible_ids = known
        except AttributeError:
            pass
    return target.pk in known


def short_name(user) -> str:
    """First name and last initial (verified ones when the person passed KYC)."""
    from security.identity_status import current_document
    doc = current_document(user)
    first = ((getattr(doc, 'verified_first_name', '') if doc else '') or user.first_name or '').strip().split(' ')[0]
    last = ((getattr(doc, 'verified_last_name', '') if doc else '') or user.last_name or '').strip()
    return (f'{first} {last[:1]}.' if first and last else first).strip()


def display_name_for(viewer, target) -> str:
    """What `viewer` may call `target`: the short name once they have paid
    each other, the @usuario otherwise."""
    if viewer is not None and (viewer.pk == target.pk or target.pk in paid_each_other(viewer, [target.pk])):
        return short_name(target) or f'@{target.username}'
    return f'@{target.username}'


def take_lookup_quota(viewer, bucket: str, cost: int, limit: int, window_seconds: int) -> bool:
    """Count `cost` lookups against the viewer's `bucket`; False once over.

    add + incr, both atomic in Redis: concurrent requests each get their own
    running total, so a burst cannot all read the same remaining allowance.
    A refused request still counts (it was asked)."""
    key = f'lookup_quota:{bucket}:{viewer.pk}'
    cache.add(key, 0, window_seconds)
    try:
        used = cache.incr(key, cost)
    except ValueError:  # expired between add and incr
        cache.add(key, 0, window_seconds)
        used = cache.incr(key, cost)
    return used <= limit
