"""IA+ entitlement from a Cuenta inteligente (spec 7.1).

One entitlement source: an AssistantSubscription row marked as coming from
the account, entitled until `paid_until`, renewed on each FeeCollected. It
ends at `paid_until` and is never granted on an inherited account.
"""
from __future__ import annotations

from django.utils import timezone

PLATFORM = 'confio'            # not a store: billed by the account contract
PRODUCT_ID = 'cuenta_inteligente'
KEY_PREFIX = 'smart_account:'


def _key(account) -> str:
    return f'{KEY_PREFIX}{account.pk}'


def sync_account(account) -> bool:
    """Bring the account's entitlement row in line with its mirror. Returns
    whether the owner is entitled through this account now."""
    from assistant.models import AssistantSubscription, SubscriptionStatus
    now = timezone.now()
    row = AssistantSubscription.objects.filter(platform=PLATFORM, store_key=_key(account)).first()
    entitled = (not account.is_inherited and account.inherited_at is None
                and account.subscription_current(now))
    if entitled:
        values = {
            'user': account.owner_user, 'product_id': PRODUCT_ID, 'status': SubscriptionStatus.ACTIVE,
            'expires_at': account.paid_until, 'grace_until': None,
            'auto_renew': account.cancel_requested_at is None, 'environment': 'onchain',
            'superseded_by': '', 'verified_at': now,
        }
        if row is None:
            AssistantSubscription.objects.create(platform=PLATFORM, store_key=_key(account), **values)
        else:
            for name, value in values.items():
                setattr(row, name, value)
            row.save()
        return True
    if row is not None and row.status != SubscriptionStatus.EXPIRED:
        # The row keeps its user (the owner it was granted to): an inherited
        # account never moves the benefit to the new owner.
        row.status = SubscriptionStatus.EXPIRED
        row.grace_until = None
        row.auto_renew = False
        row.save(update_fields=['status', 'grace_until', 'auto_renew', 'updated_at'])
    return False


def sync_user(user) -> None:
    from assistant.models import AssistantSubscription
    from .models import SmartAccount
    keys = AssistantSubscription.objects.filter(
        user=user, platform=PLATFORM, store_key__startswith=KEY_PREFIX).values_list('store_key', flat=True)
    ids = [int(k[len(KEY_PREFIX):]) for k in keys if k[len(KEY_PREFIX):].isdigit()]
    for account in SmartAccount.all_objects.filter(pk__in=ids):
        sync_account(account)


def sync_all() -> int:
    from .models import SmartAccount
    count = 0
    for account in SmartAccount.all_objects.exclude(status='none'):
        sync_account(account)
        count += 1
    return count


def account_grants_plus(user) -> bool:
    """Read-only: does this user's own account entitle them right now?"""
    from .context import own_account
    account = own_account(user)
    return account is not None and account.subscription_current()
