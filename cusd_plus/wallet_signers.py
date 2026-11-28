"""Who may have signed a wallet's trades, for reads that find them by address.

An address alone is not proof of ownership: the account that holds it today
may not be the one that traded from it (an address registered again after
its account closed, say). Address-keyed ledgers keep only the batches signed
by the people of the keyed account that holds the address now, or last held
it (its retired row), the same rule the trade export applies
(trade_export._signer_ids).
"""


def address_signer_ids(address: str) -> frozenset:
    """User ids of the personal/business account holding `address`: its
    user, plus for a business the owner and its employees (past ones
    included). The live account when one holds it; else the account its
    retired row names (a closed account, or one whose wallet moved in
    reconciliation; or just its person, when its account row is gone); else
    the latest closed keyed row that held it. So a closed account's own
    history still reads as its own. Empty when no keyed row holds it and no
    retired row names a person."""
    from django.db.models.functions import Lower

    from users.models import Account, RetiredWalletAddress

    from .trade_export import _signer_ids

    address = (address or '').strip().lower()
    if not address:
        return frozenset()
    # Lower() and the partial index's own conditions (Account.objects adds
    # deleted_at IS NULL): matches uniq_account_bsc_address_ci.
    account = (Account.objects.annotate(_bsc=Lower('bsc_address'))
               .filter(_bsc=address, bsc_address__isnull=False, account_type__in=('personal', 'business'))
               .exclude(bsc_address='').select_related('user').first())
    if account is None:
        retired = (RetiredWalletAddress.objects.filter(chain=RetiredWalletAddress.CHAIN_BSC, address=address)
                   .select_related('account__user').first())
        account = retired.account if retired is not None else None
        if account is not None and account.account_type not in ('personal', 'business'):
            account = None   # a contract's row: not a signer set; the closed-row lookup below
        elif account is None and retired is not None and retired.user_id:
            # Its account row is gone; its person is known (a hard-deleted
            # business's employees no longer are).
            return frozenset({retired.user_id})
    if account is None:
        # Closed without retiring (a queryset update, an admin edit): the
        # latest closed keyed row still reads its own history.
        account = (Account.all_objects.annotate(_bsc=Lower('bsc_address'))
                   .filter(_bsc=address, deleted_at__isnull=False, account_type__in=('personal', 'business'))
                   .select_related('user').order_by('-deleted_at', '-pk').first())
    if account is None or account.account_type not in ('personal', 'business'):
        return frozenset()
    return frozenset(_signer_ids(account.user, account))
