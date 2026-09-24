"""Public money-movement metrics, each counted once at the customer
delivery boundary: dollars proven to have reached the wallet (deposits) or
proven to have left it for a completed local payout (withdrawals). Internal
conversion/bridge legs are never counted — one withdrawal writes a ramp, a
conversion and a send row, and only the ramp is the customer's movement."""
from decimal import Decimal
from django.db.models import Case, Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value, When
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


def _deposit_aggregates():
    """[(provider, dollars, operations)] with each pair from ONE query, so a
    deposit completing mid-read can never land in the count but not the
    volume (or vice versa) — the two are cached and shown together."""
    rows = []
    for queryset, amount, provider in _deposit_sources():
        delivered = queryset.annotate(_delivered=ExpressionWrapper(amount, output_field=DOLLARS))
        totals = dict(total=Sum('_delivered'), n=Count('pk', filter=Q(_delivered__gt=0)))
        if provider is None:
            rows += [(r['provider'], r['total'] or Decimal(0), r['n'])
                     for r in delivered.values('provider').annotate(**totals)]
        else:
            r = delivered.aggregate(**totals)
            rows.append((provider, r['total'] or Decimal(0), r['n']))
    return rows


def deposited_volume_by_provider():
    totals = dict.fromkeys(('koywe', 'guardarian', 'transak', 'infinia', 'cobre'), Decimal(0))
    for provider, dollars, _ in _deposit_aggregates():
        totals[provider] += dollars
    return totals


def deposit_operation_count() -> int:
    """Deposits that delivered a positive, proven dollar amount."""
    return sum(n for _, _, n in _deposit_aggregates())


def deposit_volume_and_count() -> tuple[Decimal, int]:
    rows = _deposit_aggregates()
    return sum((dollars for _, dollars, _ in rows), Decimal(0)), sum(n for _, _, n in rows)


def withdrawn_volume_and_count() -> tuple[Decimal, int]:
    """Dollars that left customer wallets for a completed local payout.

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
    row = legacy.aggregate(total=Sum('crypto_amount_actual'), n=Count('id'))
    total, count = row['total'] or Decimal(0), row['n']
    for journey in (InfiniaJourney, CobreJourney):
        row = journey.objects.filter(
            direction='to_bank', stage='completed', money_flow__status='succeeded',
            money_flow__source_asset='USDT_BSC', money_flow__source_amount__gt=0,
        ).aggregate(total=Sum('money_flow__source_amount'), n=Count('id'))
        total += row['total'] or Decimal(0)
        count += row['n']
    return total, count
