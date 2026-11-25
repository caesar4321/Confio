"""Every address whose holdings are one person's portfolio: the personal
wallet and each Cuenta inteligente they own, every generation (a migrated
old account stays in: its trades explain units it moved to the new one, and
whatever it still holds is theirs).

Portfolio, Rentabilidad and the Liga keep their rows keyed by the personal
wallet (the person's anchor: PortfolioDailySnapshot, PortfolioValueSnapshot,
teams/league.py all read it as "the member"); the values stored under it are
the person's whole sleeve across these addresses. Moving stocks or dollars
between them (a deposit into the account, a withdrawal back, a migration)
changes neither the summed holdings nor the joint ledger: internal, never a
deposit, withdrawal, gain or return.

An inherited account (status 'inherited', withdraw-only) is not the heir's
own portfolio: what they move out of it arrives as units from outside.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def account_addresses(user) -> list[str]:
    """The person's own Cuenta inteligente contracts, oldest first (deleted
    rows included: a migrated generation)."""
    from smart_account.models import SmartAccount

    if user is None:
        return []
    rows = (SmartAccount.all_objects.filter(owner_user=user).exclude(status='inherited')
            .order_by('created_at', 'id').values_list('contract_address', flat=True))
    out = []
    for address in rows:
        address = (address or '').lower()
        if address and address not in out:
            out.append(address)
    return out


def wallets_of(user) -> list[str]:
    """[personal wallet, *account contracts]; [] without a personal wallet
    (the anchor every stored row is keyed by)."""
    from .member_portfolio import personal_wallet

    anchor = personal_wallet(user)
    if not anchor:
        return []
    return [anchor] + [a for a in account_addresses(user) if a != anchor]


def addresses_for(anchor: str) -> list[str]:
    """Every address of the person whose personal wallet is `anchor`
    (anchor first); just [anchor] for an address that is no personal wallet."""
    from users.models import Account

    anchor = (anchor or '').lower()
    if not anchor:
        return []
    account = (Account.objects.filter(bsc_address__iexact=anchor, account_type='personal', deleted_at__isnull=True)
               .select_related('user').first())
    if account is None or account.user is None:
        return [anchor]
    from .member_portfolio import personal_wallet

    if personal_wallet(account.user) != anchor:
        return [anchor]          # a second personal wallet: never the person's whole sleeve twice
    return [anchor] + [a for a in account_addresses(account.user) if a != anchor]
