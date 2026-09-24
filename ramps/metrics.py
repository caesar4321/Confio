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


def _withdrawal_sources():
    """(queryset, dollar field, country field, user field, completed field)
    for every withdrawal source. Shared by the total, the per-country counts
    and the timing so all three describe the same set of withdrawals.

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


def withdrawn_volume_and_count() -> tuple[Decimal, int]:
    """Dollars that left customer wallets for a completed local payout."""
    total, count = Decimal(0), 0
    for queryset, amount, *_ in _withdrawal_sources():
        row = queryset.aggregate(total=Sum(amount), n=Count('pk'))
        total += row['total'] or Decimal(0)
        count += row['n']
    return total, count


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


def _direct_crypto_sources():
    """Direct USDC transfers to/from outside wallets on Algorand (Sept 2025
    onward) — deposits and withdrawals with NO ramp behind them — that have
    ON-CHAIN PROOF (ramps.DirectTransferProof, written by the
    verify_direct_transfers command after matching the Algorand indexer).

    A COMPLETED USDCDeposit/USDCWithdrawal alone is not evidence (legacy
    mutations completed client-supplied amounts), so unproven rows never
    count. Proof creation already excludes transfers between Confío wallets
    and Dollar+ bridge arrivals. Ramp-linked rows are counted by their ramp.
    The 26 pre-mirror Guardarian purchases (Dec 2025 - Mar 2026) have no ramp
    row and count here, once, as the USDC deposit they delivered.

    BSC-era transfers are deliberately NOT included: external USDT sends mix
    provider deliveries (one sender pays 20 people's Koywe deposits) with
    personal transfers, and there is no reliable way to tell them apart yet.
    """
    from ramps.direct_transfers import PROOF_CUTOFF
    from usdc_transactions.models import USDCDeposit, USDCWithdrawal

    # Historical rows only (see ramps.direct_transfers.PROOF_CUTOFF): wallet
    # ownership on these legacy rows is unverified, so nothing created after
    # the metric went public can count, proof or not.
    common = dict(status='COMPLETED', is_deleted=False, ramp_transaction__isnull=True,
                  direct_proof__isnull=False, created_at__lt=PROOF_CUTOFF)
    return (
        USDCDeposit.objects.filter(**common),
        USDCWithdrawal.objects.filter(**common),
    )


def _proof_still_valid_filter():
    """Read-time guard, so attribution that lands AFTER a proof can never
    double-count before verify_direct_transfers revokes it: a proof is
    ignored when its hash became a Dollar+ bridge arrival, when its
    counterparty turned out to be a Confío address (live, deleted, retired
    or the sponsor), or when a ramp-linked row describes the same transfer
    (same wallet, counterparty and amount, within the proof window).
    Database-only; no indexer."""
    from conversion.models import Conversion
    from ramps.direct_transfers import PROOF_WINDOW, USDC_UNITS, _norm, internal_algorand_addresses
    from usdc_transactions.models import USDCDeposit, USDCWithdrawal

    bridge = set(
        Conversion.objects.filter(conversion_type='from_savings')
        .exclude(bridge_arrival_tx__isnull=True).exclude(bridge_arrival_tx='')
        .values_list('bridge_arrival_tx', flat=True)
    )
    ramp_rows = {}
    for kind, model, other in (('deposit', USDCDeposit, 'source_address'),
                               ('withdrawal', USDCWithdrawal, 'destination_address')):
        for wallet, counterparty, amount, created_at in model.objects.filter(
            ramp_transaction__isnull=False, amount__gt=0,
        ).values_list('actor_address', other, 'amount', 'created_at'):
            key = (kind, _norm(wallet), _norm(counterparty), int(Decimal(amount) * USDC_UNITS))
            ramp_rows.setdefault(key, []).append(created_at)

    internal = internal_algorand_addresses()

    def valid(kind, wallet, counterparty, amount, txid, confirmed_at):
        if txid in bridge or _norm(counterparty) in internal:
            return False
        key = (kind, _norm(wallet), _norm(counterparty), int(Decimal(amount) * USDC_UNITS))
        return not any(abs(created - confirmed_at) <= PROOF_WINDOW for created in ramp_rows.get(key, ()))
    return valid


def fund_flow_breakdown() -> dict:
    """Everything the public "Dinero en movimiento" screen shows, from the
    same operation sets as the Home tile: fiat ramps (the landing page's
    delivered-deposit metric plus completed payouts) and direct crypto
    transfers. Aggregates only: countries are operation COUNTS (never
    dollars, which would expose large holders) and appear only with
    FLOW_COUNTRY_MIN_USERS distinct people. The withdrawal median covers
    fiat payouts only: a crypto transfer is not "a payout to your account".""" 
    from statistics import median

    ops_by_country, users_by_country = {}, {}
    first_at = None

    def record(country, user_id, created_at):
        nonlocal first_at
        if created_at is not None and (first_at is None or created_at < first_at):
            first_at = created_at
        code = _iso2(country)
        if code is None:
            return
        ops_by_country[code] = ops_by_country.get(code, 0) + 1
        if user_id is not None:
            users_by_country.setdefault(code, set()).add(user_id)

    deposits = []
    for queryset, amount, _ in _deposit_sources():
        delivered = queryset.annotate(_delivered=ExpressionWrapper(amount, output_field=DOLLARS)).filter(_delivered__gt=0)
        if queryset.model.__name__ == 'RampTransaction':
            fields = ('_delivered', 'country_code', 'actor_user_id', 'created_at')
        else:
            fields = ('_delivered', 'local_account__country', 'confio_account__user_id', 'created_at')
        deposits += list(delivered.values_list(*fields))
    for dollars, country, user_id, created_at in deposits:
        record(country, user_id, created_at)

    withdrawals = []
    for queryset, amount, country, user, completed in _withdrawal_sources():
        withdrawals += list(queryset.values_list(amount, country, user, 'created_at', completed))
    minutes = []
    for dollars, country, user_id, created_at, completed_at in withdrawals:
        record(country, user_id, created_at)
        if created_at and completed_at and completed_at >= created_at:
            minutes.append((completed_at - created_at).total_seconds() / 60)

    # Direct crypto: the person's phone country (a wallet transfer has no
    # payout country). No timing: they never enter the fiat-payout median.
    crypto_in, crypto_out = _direct_crypto_sources()
    still_valid = _proof_still_valid_filter()
    # The proven on-chain amount, never the row's own (possibly client-set) one.
    fields = ('direct_proof__amount', 'actor_user__phone_country', 'actor_user_id', 'created_at')
    proof = ('actor_address', 'direct_proof__counterparty_address', 'direct_proof__transaction_hash',
             'direct_proof__confirmed_at')
    crypto_deposits = [row[:4] for row in crypto_in.values_list(*fields, *proof)
                       if still_valid('deposit', row[4], row[5], row[0], row[6], row[7])]
    crypto_withdrawals = [row[:4] for row in crypto_out.values_list(*fields, *proof)
                          if still_valid('withdrawal', row[4], row[5], row[0], row[6], row[7])]
    for dollars, country, user_id, created_at in crypto_deposits + crypto_withdrawals:
        record(country, user_id, created_at)

    countries = sorted(
        ((code, n) for code, n in ops_by_country.items()
         if len(users_by_country.get(code, ())) >= FLOW_COUNTRY_MIN_USERS),
        key=lambda row: (-row[1], row[0]),
    )
    all_deposits = [row[0] for row in deposits] + [row[0] for row in crypto_deposits]
    all_withdrawals = [row[0] for row in withdrawals] + [row[0] for row in crypto_withdrawals]
    return {
        'deposited_usd': sum(all_deposits, Decimal(0)),
        'deposit_count': len(all_deposits),
        'withdrawn_usd': sum(all_withdrawals, Decimal(0)),
        'withdrawal_count': len(all_withdrawals),
        'median_withdrawal_minutes': median(minutes) if len(minutes) >= WITHDRAWAL_TIMING_MIN_SAMPLES else None,
        'withdrawal_timing_samples': len(minutes),
        'countries': countries,
        'since': first_at,
    }
