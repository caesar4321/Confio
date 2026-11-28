"""Retire the BSC address of every keyed account closed before
Account.soft_delete started doing it.

History is looked up by address, so a closed account's address must stay
reserved to it (users.models.retire_closed_account_address). An address a
live account already holds is skipped (retiring it would refuse raw-address
sends to that live account); another person's live account is reported by
account id, for a person to look at.
"""
import logging
import re

from django.db import migrations
from django.db.models import Count
from django.db.models.functions import Lower

logger = logging.getLogger(__name__)


def retire(apps, schema_editor):
    Account = apps.get_model('users', 'Account')
    RetiredWalletAddress = apps.get_model('users', 'RetiredWalletAddress')
    # _base_manager: never a manager that hides soft-deleted rows.
    accounts = Account._base_manager
    closed = (
        accounts.filter(
            deleted_at__isnull=False,
            account_type__in=('personal', 'business'),
            bsc_address__isnull=False,
        )
        .exclude(bsc_address='')
        .order_by('deleted_at', 'pk')
    )
    retired = already = 0
    held_by_live = []
    retired_by_other = []
    retired_now = set()
    for account in closed.iterator():
        address = account.bsc_address.lower()   # as Lower() compares it below
        row = (RetiredWalletAddress.objects.filter(chain='bsc', address=address)
               .values_list('account_id', 'user_id').first())
        if row is not None:
            if address not in retired_now:
                already += 1
            holder, holder_user = row
            if holder != account.pk and holder_user != account.user_id:
                # Another person's earlier account owns it: this one
                # registered it after that one closed, the same review as
                # held_by_live.
                retired_by_other.append((account.pk, holder, holder_user))
            continue
        # Any live row, smart ones too: retiring an address a live account
        # holds would refuse raw-address sends to that account.
        live = (
            # The partial unique index's own conditions, so it is used (0068's
            # index does not exist yet).
            accounts.annotate(_bsc=Lower('bsc_address'))
            .filter(_bsc=address, deleted_at__isnull=True, bsc_address__isnull=False)
            .exclude(bsc_address='')
            .values_list('pk', 'user_id')
            .first()
        )
        if live is not None:
            if live[1] != account.user_id:   # the same person's live row needs no review
                held_by_live.append((account.pk, live[0]))
            continue
        RetiredWalletAddress.objects.create(
            chain='bsc', address=address, account_id=account.pk, user_id=account.user_id,
        )
        retired_now.add(address)
        retired += 1
    # Registered by the old code while this ran (it cannot see these rows
    # yet): such a live holder would have its raw-address sends refused.
    for address in sorted(retired_now):
        late = (accounts.annotate(_bsc=Lower('bsc_address'))
                .filter(_bsc=address, deleted_at__isnull=True, bsc_address__isnull=False)
                .exclude(bsc_address='').values_list('pk', flat=True).first())
        if late is not None:
            print(f'  registered during this migration: live account={late} (review)')
            logger.warning('live account %s registered a BSC address while 0067 retired it', late)
    # Accounts hard-deleted before (the admin's delete action): no row holds
    # their address any more, but their sponsored trades do. Retired to the
    # person who signed them, so nobody else can register it.
    SponsoredBatch = apps.get_model('blockchain', 'SponsoredBatch')
    held = set(accounts.annotate(_bsc=Lower('bsc_address')).exclude(bsc_address__isnull=True)
               .exclude(bsc_address='').values_list('_bsc', flat=True))
    known = set(RetiredWalletAddress.objects.filter(chain='bsc').values_list('address', flat=True))
    signers = {}
    for address, user_id, n in (SponsoredBatch.objects.annotate(_addr=Lower('user_bsc_address'))
                                .values('_addr', 'user_id').annotate(n=Count('id'))
                                .values_list('_addr', 'user_id', 'n').order_by('_addr', 'user_id')):
        if (address and re.fullmatch(r'0x[0-9a-f]{40}', address)
                and address not in held and address not in known):
            signers.setdefault(address, {})[user_id] = n
    # Retired to whoever signed most (a business's owner, as a rule, not one
    # of its employees); every signer is logged for review.
    orphans = {address: max(counts, key=lambda u: (counts[u], -u)) for address, counts in signers.items()}
    for address, user_id in orphans.items():
        RetiredWalletAddress.objects.create(chain='bsc', address=address, account_id=None, user_id=user_id)
        logger.warning('BSC address of a hard-deleted account retired to user %s (signers %s)',
                       user_id, sorted(signers[address]))
        # For review: if that person still has a live account without an
        # address, it may be this one re-derived (an operator cleared it).
        print(f'  retired a hard-deleted account\'s address: user={user_id} signers={sorted(signers[address])}')
    # An address a live account holds whose trades were signed by people
    # outside that account (its owner, a business's employees): registered
    # after its first account went (closed or hard-deleted). Reported only.
    BusinessEmployee = apps.get_model('users', 'BusinessEmployee')
    holders = {}
    for addr, pk, user_id, business_id in (accounts.annotate(_bsc=Lower('bsc_address'))
                                           .filter(deleted_at__isnull=True, account_type__in=('personal', 'business'))
                                           .exclude(bsc_address__isnull=True).exclude(bsc_address='')
                                           .values_list('_bsc', 'pk', 'user_id', 'business_id')):
        holders[addr] = (pk, user_id, business_id)
    staff = {}
    for business_id, user_id in BusinessEmployee._base_manager.values_list('business_id', 'user_id'):
        staff.setdefault(business_id, set()).add(user_id)
    foreign = {}
    for address, user_id in (SponsoredBatch.objects.annotate(_addr=Lower('user_bsc_address'))
                             .filter(_addr__in=list(holders)).values_list('_addr', 'user_id').distinct()):
        pk, owner_id, business_id = holders[address]
        if user_id != owner_id and user_id not in staff.get(business_id, set()):
            foreign.setdefault(pk, set()).add(user_id)
    print(f'\n  hard-deleted accounts\' BSC addresses with trades: retired={len(orphans)}')
    print(f'  closed-account BSC addresses: retired={retired} already_retired={already} '
          f'held_by_live={len(held_by_live)} retired_by_other={len(retired_by_other)}')
    for closed_pk, live_pk in held_by_live:
        # Someone registered the address after its account closed. Review
        # by hand: whether the live account's key really derives it, its
        # wallet-keyed snapshots (inbox PortfolioDailySnapshot/ValueSnapshot)
        # and what was built from them (teams TeamDailyReturn, awards), plus
        # shares already posted (ContentItem metadata 'activity') and copied
        # plays (teams CopiedPlay) that name the previous account's trades.
        print(f'  held by a live account: closed account={closed_pk} live account={live_pk}')
        logger.warning('closed account %s: BSC address held by live account %s', closed_pk, live_pk)
    print(f'  live accounts holding trades signed by someone else: {len(foreign)}')
    for live_pk, signers in sorted(foreign.items()):
        print(f'  trades of other people: live account={live_pk} signers={sorted(signers)}')
        logger.warning('live account %s holds an address with trades signed by %s', live_pk, sorted(signers))
    for closed_pk, owner_pk, owner_user in retired_by_other:
        print(f'  retired to another account: closed account={closed_pk} retired account={owner_pk} '
              f'user={owner_user}')
        logger.warning('closed account %s: BSC address retired to account %s user %s', closed_pk, owner_pk, owner_user)


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0066_alter_account_account_type'),
        ('blockchain', '0022_gm_asset_profile'),
    ]

    operations = [
        migrations.RunPython(retire, migrations.RunPython.noop),
    ]
