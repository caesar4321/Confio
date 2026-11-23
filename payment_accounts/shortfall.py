"""How many dollars a prepared payment is short of, for the words around its card.

Advisory only: nothing here refuses, holds or reorders a payment. The rails
read the chain again when the person signs, and decide there. This reads the
balances the app itself shows (stored rows, at most 5 minutes old), so a
top-up that landed a moment ago may not count yet: it can only make the note
say "te faltan" when the payment would in fact go through, never the other
way round with any confidence. Anything not read is None: no claim at all.

The dollars a payment can spend are the ones the send and bridge paths spend
(send/bsc_flow.py, payment_accounts/bridge_execution.py): Confío Dollar,
Confío Dollar+ at what redeeming it yields (not shares x pPlus, which
over-states it), and wallet USDT not already committed elsewhere.
"""
import logging
from decimal import ROUND_DOWN, ROUND_UP, Decimal

logger = logging.getLogger(__name__)

WEI = Decimal(10) ** 18
CENT = Decimal('0.01')


def dollars_held(account):
    """The account's spendable dollars, or None when any part is unknown."""
    address = (getattr(account, 'bsc_address', '') or '').strip()
    if not address:
        return None
    try:
        from blockchain.bsc_balance_service import BscBalanceService

        raw = BscBalanceService.balances_raw(address)
        cusd, shares, usdt = raw.get('CUSD_BSC'), raw.get('CUSD_PLUS'), raw.get('USDT_BSC')
        if cusd is None or shares is None or usdt is None:
            return None
        from cusd_plus import vault

        # USDT a prepared send or an off-ramp order already counts on is not this payment's.
        free_usdt = max(int(usdt) - int(vault.reserved_usdt_wei(account.user, address)), 0)
        total = (Decimal(cusd) + Decimal(free_usdt)) / WEI
        if shares:
            if not vault.vault_address():
                return None
            out = vault.redeem_gross_usdt_out(int(shares), vault.p_plus_wad(), vault.current_oracle_price_wad())
            # Under the savings' redeem floor a payment cannot use it (infinia_fee_funding.quote_funding).
            if out >= vault.ONDO_MIN_REDEEM_WEI:
                total += Decimal(out) / WEI
        return total
    except Exception:  # noqa: BLE001 - a note is never worth a failed answer
        logger.warning('shortfall: balance not read', exc_info=True)
        return None


def shortfall(account, total_usd):
    """Dollars missing to pay `total_usd` (rounded up to the cent), or None
    when nothing is missing or the balance is not known."""
    try:
        total = Decimal(str(total_usd))
    except Exception:  # noqa: BLE001
        return None
    held = dollars_held(account)
    if held is None or total <= 0:
        return None
    missing = (total - held).quantize(CENT, rounding=ROUND_UP)
    return missing if missing > 0 else None


def usd(value, down=False):
    """US$1,234.50 as the cards write it. `down` for what someone has: never
    a cent more than is there."""
    return f'US${Decimal(value).quantize(CENT, rounding=ROUND_DOWN if down else ROUND_UP):,.2f}'


# The funding paths' refusals for too few dollars (bridge_execution,
# infinia_fee_funding): said to the person in Spanish, with what is missing.
TOO_FEW_DOLLARS = frozenset({
    'Insufficient dollar balance', 'Insufficient dollars for transfer and fees', 'Insufficient USDT for fee conversion',
    'Insufficient cUSD for transfer and fees',
})


def short_of_dollars(account, total_usd):
    """The refusal for a payment the dollars held do not cover: a
    PaymentAccountError (so every caller already shows it), in Spanish, with
    what is missing when it is known. `.missing` carries it (or None)."""
    from .services import PaymentAccountError

    missing = shortfall(account, total_usd)
    error = PaymentAccountError('No tienes saldo suficiente para este pago' + (
        f': te faltan {usd(missing)}. Recarga y vuelve a prepararlo.' if missing else
        '. Recarga y vuelve a prepararlo.'))
    error.missing = missing
    error.short_of_dollars = True
    return error


def is_short_of_dollars(exc):
    """Whether a refusal (or what it was raised from) is short_of_dollars:
    callers re-raise it under their own codes."""
    seen = 0
    while exc is not None and seen < 8:
        if getattr(exc, 'short_of_dollars', False):
            return True
        exc, seen = exc.__cause__ or exc.__context__, seen + 1
    return False


def missing_of(exc):
    """What a short_of_dollars refusal (or what it was raised from) says is missing, or None."""
    seen = 0
    while exc is not None and seen < 8:
        if getattr(exc, 'short_of_dollars', False):
            return getattr(exc, 'missing', None)
        exc, seen = exc.__cause__ or exc.__context__, seen + 1
    return None
