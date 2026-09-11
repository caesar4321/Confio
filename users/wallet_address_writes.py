"""Serialize legacy registration writes against sign-in reconciliation."""
from django.db import transaction

from .models import Account, RetiredWalletAddress


class WalletRegistrationChanged(ValueError):
    pass


def persist_legacy_wallet_fields(account, **changes):
    """Compare the caller's snapshot under lock, then save only wallet fields.

    RPC work may happen before this call, but cannot authorize a write against
    a newer wallet generation. Reconciliation alone may reactivate BSC history.
    """
    fields = ('algorand_address', 'bsc_address', 'is_keyless_migrated')
    if not changes or set(changes) - set(fields):
        raise ValueError('Unsupported wallet update')
    expected = tuple(getattr(account, field) for field in fields)
    with transaction.atomic():
        current = Account.objects.select_for_update().get(pk=account.pk)
        if tuple(getattr(current, field) for field in fields) != expected:
            raise WalletRegistrationChanged('La billetera cambió. Inicia sesión de nuevo.')
        algo = changes.get('algorand_address')
        if algo and algo != current.algorand_address:
            if (current.bsc_address and current.is_keyless_migrated
                    and not current.algorand_address):
                raise WalletRegistrationChanged('Esta cuenta ya usa su billetera BSC.')
            if RetiredWalletAddress.objects.filter(
                chain='algorand', address=algo.upper(),
            ).exists():
                raise WalletRegistrationChanged('Esta dirección de billetera fue retirada.')
        bsc = changes.get('bsc_address')
        if bsc:
            if (current.bsc_address
                    and current.bsc_address.lower() != bsc.lower()):
                raise WalletRegistrationChanged('La billetera cambió. Inicia sesión de nuevo.')
            if RetiredWalletAddress.objects.filter(
                chain='bsc', address=bsc.lower(),
            ).exclude(account=current).exists():
                raise WalletRegistrationChanged('Esta dirección pertenece a otra cuenta.')
        for field, value in changes.items():
            setattr(current, field, value)
        current.save(update_fields=list(changes))
    for field, value in changes.items():
        setattr(account, field, value)
