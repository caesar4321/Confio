"""Public money-movement metrics, each counted once at the customer
delivery boundary: dollars proven to have reached the wallet (deposits) or
proven to have left it for a completed local payout (withdrawals). Internal
conversion/bridge legs are never counted — one withdrawal writes a ramp, a
conversion and a send row, and only the ramp is the customer's movement."""
from decimal import Decimal
from django.db.models import Case, DecimalField, F, Q, Sum, Value, When
from django.db.models.functions import Cast, Coalesce, Greatest, NullIf
from django.db.models.fields.json import KeyTextTransform


DOLLARS = DecimalField(max_digits=78, decimal_places=18)
LEGACY_PROVIDERS = ('koywe', 'guardarian', 'transak')


def _journey_mirrors():
    """Legacy ramp rows already represented by an Infinia/Cobre journey."""
    from payment_accounts.models import MoneyFlow

    mirrors = MoneyFlow.objects.filter(
        Q(infinia_journey__isnull=False) | Q(cobre_journey__isnull=False)
    ).values('legacy_ramp_transaction_id')
    return mirrors.exclude(legacy_ramp_transaction__isnull=True)


def _deposit_sources():
    """(queryset, per-row dollar expression, provider) for every deposit
    source. Shared by the volume and the operation count so the two can
    never disagree about what a deposit is."""
    from ramps.models import RampTransaction
    from payment_accounts.models import CobreJourney, InfiniaJourney

    dollars = DOLLARS
    zero = Value(Decimal(0), output_field=dollars)
    # Legacy provider mirrors are canonical here; never add Guardarian's raw
    # transaction table or the same payment's deposit/conversion again.
    # Preserve the historical on-chain deposit boundary: a proven stablecoin
    # receipt counts before minting. Provider status/quotes alone never do.
    legacy = RampTransaction.objects.filter(direction='on_ramp', status='COMPLETED',
        provider__in=LEGACY_PROVIDERS)
    converted = Q(conversion__status='COMPLETED', conversion__is_deleted=False,
        final_amount__gt=0) & (
        Q(conversion__conversion_type='usdc_to_cusd', final_currency='CUSD')
        | Q(conversion__conversion_type='usdt_to_cusd', final_currency__in=('CUSD', 'CUSD_BSC'))
        | Q(conversion__conversion_type='to_savings', final_currency__in=('CUSD+', 'CUSD_PLUS'))
    )
    verified_usdc = Q(usdc_deposit__status='COMPLETED', usdc_deposit__is_deleted=False,
        usdc_deposit__amount__gt=0)
    # These fields are written together by the USDT scanner after unique
    # provider attribution. Bounds prevent malformed JSON/numeric overflow
    # from breaking the public metric; CAST stays inside the guarded CASE.
    verified_usdt = Q(destination='cusd_plus',
        metadata__bsc_arrival_tx_hash__regex=r'^0x[0-9a-fA-F]{64}$',
        metadata__bsc_arrival_log_index__regex=r'^[0-9]{1,20}$',
        metadata__bsc_arrival_amount__regex=r'^[0-9]{1,38}(\.[0-9]{1,18})?$')
    contribution = Case(
        When(converted, then=F('final_amount')),
        When(verified_usdc, then=F('usdc_deposit__amount')),
        When(verified_usdt, then=Cast(KeyTextTransform('bsc_arrival_amount', 'metadata'), dollars)),
        default=zero, output_field=dollars)
    # Journeys win over any legacy mirrors attached to their MoneyFlow.
    legacy = legacy.exclude(pk__in=_journey_mirrors())
    # Keep the ramp's allocated final_amount above: a single conversion may
    # settle multiple ramps, so summing its full net once per ramp duplicates it.
    incoming_net = Coalesce('wallet_conversion__net_amount_exact', Case(
        When(wallet_conversion__conversion_type='usdt_to_cusd', then=F('wallet_conversion__to_amount')),
        default=zero, output_field=dollars), output_field=dollars)
    infinia = InfiniaJourney.objects.filter(
        direction='to_wallet', stage='completed', wallet_conversion__status='COMPLETED',
        wallet_conversion__is_deleted=False,
    )
    # Bridge units are an integer string. NULL/empty represents no proven
    # output; cast to numeric in SQL rather than materializing every journey.
    units = Coalesce(Cast(NullIf('bridge__actual_out_units', Value('')), dollars), zero)
    cobre = CobreJourney.objects.filter(
        direction='to_wallet', stage='completed', bridge__status='delivered',
    )
    return [
        (legacy, contribution, None),
        (infinia, Greatest(incoming_net, zero), 'infinia'),
        (cobre, Greatest(units, zero) / Value(Decimal(10**18)), 'cobre'),
    ]


def deposited_volume_by_provider():
    """Delivered deposit dollars per provider (admin/monitoring and landing
    stats; the public Movido is measured from conversions instead)."""
    totals = dict.fromkeys(('koywe', 'guardarian', 'transak', 'infinia', 'cobre'), Decimal(0))
    for queryset, amount, provider in _deposit_sources():
        total = Sum(amount, output_field=DOLLARS)
        if provider is None:
            for row in queryset.values('provider').annotate(total=total):
                totals[row['provider']] += row['total'] or Decimal(0)
        else:
            totals[provider] = queryset.aggregate(total=total)['total'] or Decimal(0)
    return totals


def _withdrawal_sources():
    """(queryset, dollar field, country field, user field, completed field)
    for every completed fiat payout — the sample behind the public
    withdrawal-time median.

    Legacy ramps count their actual (never quoted) USDC/USDT amount; journeys
    count the dollar-denominated source of a succeeded payout. A payout whose
    source isn't dollars is skipped rather than converted with a guessed rate.
    """
    from ramps.models import RampTransaction
    from payment_accounts.models import CobreJourney, InfiniaJourney

    # Only dollar stablecoins are 1:1 with USD. Guardarian can sell ALGO, BTC
    # or ETH and stores their NATIVE amount in crypto_amount_actual; those are
    # skipped rather than priced (prod values: "USDC Algorand", "USDT BSC").
    dollar_denominated = Q(crypto_currency__istartswith='USDC') | Q(crypto_currency__istartswith='USDT')
    legacy = RampTransaction.objects.filter(
        dollar_denominated,
        direction='off_ramp', status='COMPLETED', provider__in=LEGACY_PROVIDERS,
        crypto_amount_actual__gt=0,
    ).exclude(pk__in=_journey_mirrors())
    sources = [(legacy, 'crypto_amount_actual', 'country_code', 'actor_user_id', 'completed_at')]
    for journey in (InfiniaJourney, CobreJourney):
        sources.append((journey.objects.filter(
            direction='to_bank', stage='completed', money_flow__status='succeeded',
            money_flow__source_asset='USDT_BSC', money_flow__source_amount__gt=0,
        ), 'money_flow__source_amount', 'local_account__country',
            'confio_account__user_id', 'money_flow__completed_at'))
    return sources


# Same privacy floor as the Usuarios-by-country screen: a country with fewer
# people could let its operation count be traced to individuals.
FLOW_COUNTRY_MIN_USERS = 5
# A median of a handful of withdrawals is an anecdote, not a typical time.
WITHDRAWAL_TIMING_MIN_SAMPLES = 10


def _iso2(value):
    from payment_accounts.providers.common import iso_alpha2
    try:
        code = iso_alpha2(value)
    except (ValueError, LookupError):
        return None
    return None if code == 'XX' else code


# Money crossing the Confío-dollar perimeter, read from conversions: every
# dollar that enters is converted from USDC/USDT into cUSD/cUSD+, and every
# dollar that leaves is converted back first — whatever the provider or
# channel (ramps, Infinia/Cobre journeys, direct crypto on Algorand or BSC).
# Rows since 2026-09-01 carry perimeter_direction; older ones are classified
# by type. usdc_to_algo (USDC -> ALGO) never crosses the perimeter.
ENTRY_CONVERSIONS = ('usdc_to_cusd', 'usdt_to_cusd', 'to_savings')
EXIT_CONVERSIONS = ('cusd_to_usdc', 'cusd_to_usdt', 'from_savings')


def _perimeter_conversions():
    """(entries, exits): completed, non-deleted conversions that cross the
    perimeter. cUSD <-> cUSD+ ('internal') is a move inside Confío and is the
    only exclusion. Known limit: USDT that arrived and stayed raw (never
    converted) during the early BSC period is not counted."""
    from conversion.models import Conversion

    live = Conversion.objects.filter(status='COMPLETED', is_deleted=False).exclude(perimeter_direction='internal')
    entries = live.filter(Q(perimeter_direction='entry')
                          | Q(perimeter_direction='', conversion_type__in=ENTRY_CONVERSIONS))
    exits = live.filter(Q(perimeter_direction='exit')
                        | Q(perimeter_direction='', conversion_type__in=EXIT_CONVERSIONS))
    return entries, exits


def fund_flow_breakdown() -> dict:
    """Everything the public "Dinero en movimiento" screen and the Home
    "Movido" tile show. Volume is measured at the perimeter (see above):
    entries at the USDC/USDT amount that came in (from_amount), exits at the
    amount that went out (to_amount, after fees). Countries are operation
    COUNTS by the person's phone country (never dollars, which would expose
    large holders), shown only with FLOW_COUNTRY_MIN_USERS distinct people.
    The withdrawal-time median comes from completed fiat payouts: a
    conversion does not tell when money reached a bank account."""
    from statistics import median

    ops_by_country, users_by_country = {}, {}
    first_at = None
    entries, exits = _perimeter_conversions()
    fields = ('actor_user__phone_country', 'actor_user_id', 'actor_business_id', 'created_at')
    entry_rows = list(entries.values_list('from_amount', *fields))
    exit_rows = list(exits.values_list('to_amount', *fields))
    for _, country, user_id, business_id, created_at in entry_rows + exit_rows:
        if created_at is not None and (first_at is None or created_at < first_at):
            first_at = created_at
        code = _iso2(country)
        if code is None:
            continue
        ops_by_country[code] = ops_by_country.get(code, 0) + 1
        users_by_country.setdefault(code, set()).add(('user', user_id) if user_id else ('business', business_id))

    minutes = []
    for queryset, *_, completed in _withdrawal_sources():
        for created_at, completed_at in queryset.values_list('created_at', completed):
            if created_at and completed_at and completed_at >= created_at:
                minutes.append((completed_at - created_at).total_seconds() / 60)

    countries = sorted(
        ((code, n) for code, n in ops_by_country.items()
         if len(users_by_country.get(code, ())) >= FLOW_COUNTRY_MIN_USERS),
        key=lambda row: (-row[1], row[0]),
    )
    return {
        'deposited_usd': sum((Decimal(row[0] or 0) for row in entry_rows), Decimal(0)),
        'deposit_count': len(entry_rows),
        'withdrawn_usd': sum((Decimal(row[0] or 0) for row in exit_rows), Decimal(0)),
        'withdrawal_count': len(exit_rows),
        'median_withdrawal_minutes': median(minutes) if len(minutes) >= WITHDRAWAL_TIMING_MIN_SAMPLES else None,
        'withdrawal_timing_samples': len(minutes),
        'countries': countries,
        'since': first_at,
    }
