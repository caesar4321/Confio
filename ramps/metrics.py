"""Public Movido counts completed Confío-dollar perimeter conversions once.
Provider delivery totals and fiat payout timing retain their separate ramp
and journey evidence; neither is added to the perimeter total.
"""
from decimal import Decimal
from django.db.models import Case, Count, DecimalField, F, Q, Sum, Value, When
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


def _deposit_sources(providers=LEGACY_PROVIDERS):
    """(queryset, per-row dollar expression, provider) for every deposit
    source. Shared by the volume and the operation count so the two can
    never disagree about what a deposit is. `providers=None` is every ramp
    provider (the admin's per-rail table)."""
    from ramps.models import RampTransaction
    from payment_accounts.models import CobreJourney, InfiniaJourney

    dollars = DOLLARS
    zero = Value(Decimal(0), output_field=dollars)
    # Legacy provider mirrors are canonical here; never add Guardarian's raw
    # transaction table or the same payment's deposit/conversion again.
    # Preserve the historical on-chain deposit boundary: a proven stablecoin
    # receipt counts before minting. Provider status/quotes alone never do.
    legacy = RampTransaction.objects.filter(direction='on_ramp', status='COMPLETED')
    if providers is not None:
        legacy = legacy.filter(provider__in=providers)
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


def _withdrawal_sources(providers=LEGACY_PROVIDERS):
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
        dollar_denominated, direction='off_ramp', status='COMPLETED', crypto_amount_actual__gt=0,
    ).exclude(pk__in=_journey_mirrors())
    if providers is not None:
        legacy = legacy.filter(provider__in=providers)
    sources = [(legacy, 'crypto_amount_actual', 'country_code', 'actor_user_id', 'completed_at')]
    for journey in (InfiniaJourney, CobreJourney):
        sources.append((journey.objects.filter(
            direction='to_bank', stage='completed', money_flow__status='succeeded',
            money_flow__source_asset='USDT_BSC', money_flow__source_amount__gt=0,
        ), 'money_flow__source_amount', 'local_account__country',
            'confio_account__user_id', 'money_flow__completed_at'))
    return sources


def _period_totals(periods):
    """One query's worth of per-period aggregates over annotated
    flow_usd / flow_at. `periods`: [(label, since)], oldest-possible `since`
    for all time."""
    totals = {}
    for index, (_label, since) in enumerate(periods):
        window = Q(flow_at__gte=since, flow_usd__gt=0)
        totals[f'usd{index}'] = Sum('flow_usd', filter=window, output_field=DOLLARS)
        totals[f'n{index}'] = Count('pk', filter=window)
    return totals


def _period_cells(row, periods):
    return [{'usd': row[f'usd{i}'] or Decimal(0), 'count': row[f'n{i}']} for i in range(len(periods))]


def rail_flows_by_period(periods) -> dict:
    """Delivered deposits and completed payouts per provider, and the
    perimeter (Movido) totals, for each period. Provider rows include every
    ramp provider, unlike the public deposit figure; deposits are net of the
    fee, Movido deposits gross, so providers are a subset, never a sum of it.
    Dated by completion, falling back to creation."""
    from ramps.models import RampTransaction

    labels = dict(RampTransaction.PROVIDER_CHOICES)

    def provider_rows(sources):
        rows = {}
        for queryset, amount, date_field, provider in sources:
            annotated = queryset.order_by().annotate(
                flow_usd=amount, flow_at=Coalesce(date_field, 'created_at'))
            if provider is None:
                for row in annotated.values('provider').annotate(**_period_totals(periods)):
                    rows[row['provider']] = _period_cells(row, periods)
            else:
                rows[provider] = _period_cells(annotated.aggregate(**_period_totals(periods)), periods)
        return sorted(
            ({'label': labels.get(key, key.title()), 'cells': cells} for key, cells in rows.items()),
            key=lambda row: (-row['cells'][-1]['usd'], row['label']))

    deposit_dates = {None: 'completed_at', 'infinia': 'money_flow__completed_at', 'cobre': 'money_flow__completed_at'}
    deposits = provider_rows(
        (queryset, amount, deposit_dates[provider], provider)
        for queryset, amount, provider in _deposit_sources(providers=None))
    payouts = provider_rows(
        (queryset, F(amount), completed, provider)
        for (queryset, amount, _country, _user, completed), provider
        in zip(_withdrawal_sources(providers=None), (None, 'infinia', 'cobre')))

    entries, exits = _perimeter_conversions()
    movido_in = entries.order_by().annotate(
        flow_usd=Coalesce('gross_amount_exact', 'from_amount', output_field=DOLLARS),
        flow_at=F('created_at')).aggregate(**_period_totals(periods))
    movido_out = exits.order_by().annotate(
        flow_usd=Coalesce('net_amount_exact', 'to_amount', output_field=DOLLARS),
        flow_at=F('created_at')).aggregate(**_period_totals(periods))
    return {
        'deposits': deposits,
        'withdrawals': payouts,
        'movido_in': _period_cells(movido_in, periods),
        'movido_out': _period_cells(movido_out, periods),
    }


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
    entries at the USDC/USDT amount that came in, exits at the amount that
    went out after fees. Prefer the exact ledger, falling back to historical
    from_amount/to_amount projections. Countries are operation
    COUNTS by the person's phone country (never dollars, which would expose
    large holders), shown only with FLOW_COUNTRY_MIN_USERS distinct people.
    The withdrawal-time median comes from completed fiat payouts: a
    conversion does not tell when money reached a bank account."""
    from statistics import median

    ops_by_country, users_by_country = {}, {}
    first_at = None
    entries, exits = _perimeter_conversions()
    # The residence country; the phone country only for accounts the
    # backfill has not reached yet (security.geo.country_of does the same).
    fields = (Coalesce(NullIf('actor_user__country', Value('')), 'actor_user__phone_country'),
              'actor_user_id', 'actor_business_id', 'created_at')
    entry_rows = list(entries.values_list(
        Coalesce('gross_amount_exact', 'from_amount', output_field=DOLLARS), *fields))
    exit_rows = list(exits.values_list(
        Coalesce('net_amount_exact', 'to_amount', output_field=DOLLARS), *fields))
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


def public_fund_flow_snapshot() -> dict:
    """The exact "Movido" figures the website and app show (fundFlowStats),
    cached 10 minutes under the key the public resolver always used. The
    admin dashboard reads this same snapshot, so the two can never drift.

    Perimeter deposits + withdrawals of Confío dollars (ramps, outside USDT,
    sends to outside wallets, Pay). Stock, Bitcoin and gold trades are
    investments, not deposits or withdrawals, and are not counted here.
    """
    from django.core.cache import cache

    cached = cache.get('fund_flow_stats_v4')
    if cached:
        return cached
    from users.country_codes import COUNTRY_CODES
    from users.country_names_es import COUNTRY_NAMES_ES

    # One snapshot for the tile and the screen: the total, the split, the
    # countries and the timing all come from the same operation sets.
    flow = fund_flow_breakdown()
    iso_to_en = {row[2]: row[0] for row in COUNTRY_CODES}
    data = {
        'deposited_usd': float(flow['deposited_usd']),
        'withdrawn_usd': float(flow['withdrawn_usd']),
        'total_usd': float(flow['deposited_usd'] + flow['withdrawn_usd']),
        'deposit_count': flow['deposit_count'],
        'withdrawal_count': flow['withdrawal_count'],
        'operation_count': flow['deposit_count'] + flow['withdrawal_count'],
        'median_withdrawal_minutes': flow['median_withdrawal_minutes'],
        'withdrawal_timing_samples': flow['withdrawal_timing_samples'],
        'since': flow['since'].isoformat() if flow['since'] else None,
        'countries': [
            {'country_iso': code,
             'country_name': COUNTRY_NAMES_ES.get(code) or iso_to_en.get(code) or code,
             'operation_count': n}
            for code, n in flow['countries']
        ],
    }
    cache.set('fund_flow_stats_v4', data, 600)
    return data
