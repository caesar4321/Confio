"""Invoice-cost pricing, separate from Infinia's already-applied FX spread.

All amounts are USD/cUSD face values. The billing tier is an explicit operating
setting: transaction-local volume must never guess a month-end invoice tier.
Only separately billed costs are returned: a zero additional blockchain cost
outside Colombia does not mean the route has no blockchain transfer.

This module calculates prices only; it does not collect fees or alter quotes.
"""
from decimal import Decimal, DecimalException, ROUND_UP

def iso_alpha2(value):
    import pycountry
    value = str(value or '').strip().upper()
    country = pycountry.countries.get(**({'alpha_2': value} if len(value) == 2 else {'alpha_3': value}))
    if country is None:
        raise ValueError('Unknown fee country')
    return country.alpha_2

VERSION = 'infinia-invoice-costs-v1'
# Contract processing tariff by negotiated monthly volume tier, lowest first.
PROCESSING = {
    'BR': ('0.10', '0.075', '0.05', '0.03', '0.025', '0.025'),
    'MX': ('0.50', '0.45', '0.40', '0.35', '0.30', '0.25'),
    'PE': ('1', '1', '1', '0.8', '0.6', '0.6'),
    'CL': ('1', '1', '1', '0.8', '0.6', '0.6'),
    'PY': ('1', '1', '1', '0.8', '0.6', '0.6'),
    'US': ('2', '1.8', '1.6', '1.4', '1.2', '1'),
    'GB': ('0.8', '0.7', '0.6', '0.5', '0.45', '0.45'),
    'EU': ('0.8', '0.7', '0.6', '0.5', '0.45', '0.45'),
    'CO:BREB': ('0.5', '0.5', '0.5', '0.4', '0.3', '0.25'),
    'CO:ACH': ('2', '1.8', '1.6', '1.4', '1.2', '1'),
    'BO:instant': ('3.2', '2.8', '2.4', '2', '1.6', '1.2'),
}


class FeePricingError(ValueError):
    pass


def transaction_cost(*, country, rail, blockchain_transfers=None, tier=0,
                     bolivia_mode=None, argentina_itf_usd=None,
                     other_blockchain_cost_usd=None):
    """Return a reproducible invoice-cost snapshot, never a second FX charge.

    ``blockchain_transfers`` counts actual provider blockchain legs, not chain
    hops in a third-party bridge. Colombia's tariff applies in both directions.
    Outside Colombia, gas is already included in the transaction (confirmed
    by the account operator); do not add it again. Infinia also deducts
    applicable Argentina ITF automatically from the transaction value.
    This invoice calculator must never collect that tax a second time.
    """
    if type(tier) is not int or not 0 <= tier < 6:
        raise FeePricingError('Unknown processing tier')
    if type(blockchain_transfers) is not int or blockchain_transfers <= 0:
        raise FeePricingError('An explicit positive blockchain leg count is required')
    try:
        country = str(country or '').strip().upper()
        country = 'EU' if country == 'EU' else iso_alpha2(country)
    except (ValueError, TypeError) as exc:
        raise FeePricingError('Unknown fee country') from exc
    rail = str(rail).strip().upper().replace('-', '')
    if country != 'BO' and bolivia_mode is not None:
        raise FeePricingError('Bolivia processing mode supplied for another country')
    if argentina_itf_usd is not None:
        raise FeePricingError('ITF is deducted automatically; do not charge it again')
    key = f'CO:{rail}' if country == 'CO' else country
    if country == 'BO':
        if bolivia_mode not in (None, 'instant'):
            raise FeePricingError('Only immediate conversion is supported')
        key = 'BO:instant'
    if other_blockchain_cost_usd is not None:
        raise FeePricingError('Gas is already included; do not charge it again')
    itf = Decimal('0')
    if country == 'AR':
        processing = Decimal(('0.5', '0.4', '0.3', '0.2', '0.1', '0.05')[tier])
    else:
        if key not in PROCESSING:
            raise FeePricingError('No processing tariff for country/rail')
        processing = Decimal(PROCESSING[key][tier])
    try:
        blockchain = Decimal('0.75') * blockchain_transfers if country == 'CO' else Decimal('0')
        total = (processing + blockchain + itf).quantize(Decimal('0.000001'), rounding=ROUND_UP)
    except DecimalException as exc:
        raise FeePricingError('Fee amount exceeds supported precision') from exc
    return {'version': VERSION, 'country': country, 'rail': rail, 'tier': tier,
            'processing_usd': str(processing), 'blockchain_usd': str(blockchain), 'itf_usd': str(itf),
            'blockchain_transfers': blockchain_transfers, 'total_usd': str(total),
            **({'itf_collection': 'provider_automatic'} if country == 'AR' else {})}


def virtual_account_cost(*, account_count, enabled_account_months=0, new_accounts=0):
    """Provider cost, not an extra charge on top of an already-paid opening."""
    for value in (account_count, enabled_account_months, new_accounts):
        if type(value) is not int or value < 0:
            raise FeePricingError('Invalid account count')
    # The contract's "100,000+" overlaps the preceding inclusive tier. Do not
    # silently pick a price at that single ambiguous boundary.
    if account_count == 100000:
        raise FeePricingError('Confirm account tier at 100000 accounts')
    creation, maintenance = ('1', '0.10') if account_count <= 10000 else (
        ('0.85', '0.07') if account_count < 100000 else ('0.70', '0.05'))
    return {'creation_usd': str(Decimal(creation) * new_accounts),
            'maintenance_usd': str(Decimal(maintenance) * enabled_account_months)}


# These are complete economic routes, not just the final payout operation.
# BSC->Polygon bridge hops do not create two Infinia blockchain charges: only
# the crypto credit to, or withdrawal from, Infinia is the provider's leg.
FIAT_ASSETS = {
    'BR': 'BRL', 'MX': 'MXN', 'CO': 'COP', 'PE': 'PEN', 'CL': 'CLP',
    'PY': 'PYG', 'AR': 'ARS', 'BO': 'BOB', 'US': 'USD', 'GB': 'GBP', 'EU': 'EUR',
}


def route_cost(*, country, rail, assets, **tariff_options):
    """Price a complete server-known route. Never accept a client leg count.

    Confio immediately converts USDT to local fiat or local fiat to USDT.
    Every supported route therefore includes one Infinia blockchain leg.
    Fiat-only and incomplete routes are unsupported, not cheaper routes.
    """
    normalized = str(country or '').strip().upper()
    try:
        normalized = 'EU' if normalized == 'EU' else iso_alpha2(normalized)
    except ValueError as exc:
        raise FeePricingError('Unknown fee country') from exc
    fiat = FIAT_ASSETS.get(normalized)
    if not fiat or not isinstance(assets, (tuple, list)):
        raise FeePricingError('A supported complete payment route is required')
    route = tuple(assets)
    routes = {
        ('BSC:USDT', 'POL:USDC', fiat): ('to_bank', 1),
        (fiat, 'POL:USDC', 'BSC:USDT'): ('to_wallet', 1),
    }
    try:
        direction, legs = routes[route]
    except (KeyError, TypeError) as exc:
        raise FeePricingError('Unsupported or incomplete payment route') from exc
    if 'blockchain_transfers' in tariff_options:
        raise FeePricingError('Blockchain charges are derived from the route')
    result = transaction_cost(country=normalized, rail=rail,
                              blockchain_transfers=legs, **tariff_options)
    return dict(result, direction=direction, route=list(route))
