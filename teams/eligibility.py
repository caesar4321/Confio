"""Who counts, in bulk: the league and team pages ask about many members at
once, so these are a fixed handful of queries however many people."""
from __future__ import annotations

from django.db.models.functions import Lower
from django.utils import timezone


def eligible_user_ids(user_ids) -> set:
    """Active, not banned, identity-verified, investor profile public: the
    people whose investment data may be shown or ranked (reciprocity)."""
    from inbox.models import CommunityProfileSettings
    from security.identity_status import verified_user_ids
    from security.models import UserBan
    from users.models import User

    ids = {int(u) for u in user_ids if u}
    if not ids:
        return set()
    active = set(User.objects.filter(id__in=ids, is_active=True, deleted_at__isnull=True).values_list('id', flat=True))
    banned = set(UserBan.objects.filter(user_id__in=active, deleted_at__isnull=True)
                 .exclude(ban_type='temporary', expires_at__lt=timezone.now()).values_list('user_id', flat=True))
    hidden = set(CommunityProfileSettings.objects.filter(user_id__in=active, portfolio_hidden=True)
                 .values_list('user_id', flat=True))
    verified = set(verified_user_ids(active))
    return (active & verified) - banned - hidden


def canonical_wallets(user_ids) -> dict:
    """{user_id: wallet}: each member's one personal wallet (lowest account
    index), the same one their profile shows. Other wallets never count."""
    from users.models import Account

    out = {}
    rows = (Account.objects.filter(user_id__in={int(u) for u in user_ids if u}, account_type='personal',
                                   deleted_at__isnull=True)
            .exclude(bsc_address__isnull=True).exclude(bsc_address='')
            .annotate(addr=Lower('bsc_address')).order_by('user_id', 'account_index')
            .values_list('user_id', 'addr'))
    for user_id, addr in rows:
        out.setdefault(user_id, addr)
    return out
