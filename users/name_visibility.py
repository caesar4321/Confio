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
    ).values_list('sender_user_id', 'recipient_user_id'):
        known.add(recipient_id if sender_id == viewer.pk else sender_id)
    for inviter_id, claimer_id in PhoneInvite.objects.filter(
        Q(inviter_user=viewer, claimed_by_id__in=ids) | Q(claimed_by=viewer, inviter_user_id__in=ids),
        status='claimed', deleted_at__isnull=True,
    ).values_list('inviter_user_id', 'claimed_by_id'):
        known.add(claimer_id if inviter_id == viewer.pk else inviter_id)
    return known & ids


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
