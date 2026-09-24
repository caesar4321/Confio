"""Frozen fee instructions for new local journeys; existing work retains its terms."""
from decimal import Decimal

from django.conf import settings

from .infinia_fees import FeePricingError, iso_alpha2, route_cost


def enabled(country):
    # No retroactive charges on old journeys.
    countries = getattr(settings, 'INFINIA_PASS_THROUGH_FEE_COUNTRIES', ())
    if isinstance(countries, str):
        countries = countries.split(',')
    countries = {value.strip().upper() for value in countries if value.strip()}
    if not countries:
        return False
    country = str(country or '').strip().upper()
    normalized = 'EU' if country == 'EU' else iso_alpha2(country)
    return normalized in countries


def price(local, direction, *, destination=None):
    if local.provider != 'infinia' or not enabled(local.country):
        return None
    if direction == 'to_wallet' and not getattr(settings, 'INFINIA_INCOMING_FEE_COLLECTION_ENABLED', True):
        return None
    # Applicable Argentina ITF is already deducted by the banks. Only the
    # separately invoiced processing fee belongs in our collector transfer.
    rail = local.asset
    if local.asset == 'COP':
        if direction == 'to_bank':
            kind = (destination.details or {}).get('type') if destination else None
            rail = {'BREB_KEY': 'BREB', 'ACCOUNT_COLOMBIA': 'ACH'}.get(kind)
        else:
            rail = local.payin_rail
        if rail not in ('BREB', 'ACH'):
            raise FeePricingError('A verified Colombian payment rail is required')
    assets = ['BSC:USDT', 'POL:USDC', local.asset]
    if direction == 'to_wallet':
        assets.reverse()
    elif direction != 'to_bank':
        raise FeePricingError('Unsupported fee direction')
    tariff = route_cost(country=local.country, rail=rail, assets=assets,
                        tier=getattr(settings, 'INFINIA_PROCESSING_FEE_TIER', 0))
    from .infinia_maintenance import quoted_charges
    ids, maintenance = quoted_charges(local.provider_profile.confio_account)
    tariff = dict(tariff, maintenance_ids=ids, maintenance_usd=str(maintenance),
                  total_usd=str(Decimal(tariff['total_usd']) + maintenance))
    from .infinia_fee_debt import quoted
    ids, debt = quoted(local.provider_profile.confio_account)
    tariff = dict(tariff, debt_ids=ids, debt_usd=str(debt),
                  total_usd=str(Decimal(tariff['total_usd']) + debt))
    return dict(tariff, local_account_id=str(local.internal_id),
                units=str(int(Decimal(tariff['total_usd']) * 10**18)))


def freeze(local, direction, *, destination=None):
    snapshot = price(local, direction, destination=destination)
    if snapshot is None:
        return None
    from .activation import collector
    return dict(snapshot, collector=collector(), token=settings.CUSD_VAULT_ADDRESS.lower())
