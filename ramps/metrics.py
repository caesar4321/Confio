"""Public incoming volume, counted once at the customer delivery boundary."""
from decimal import Decimal
from django.db.models import Case, DecimalField, F, Q, Sum, Value, When
from django.db.models.functions import Cast, Coalesce, Greatest, NullIf
from django.db.models.fields.json import KeyTextTransform


def deposited_volume_by_provider():
    from ramps.models import RampTransaction
    from payment_accounts.models import CobreJourney, InfiniaJourney, MoneyFlow

    totals = dict.fromkeys(('koywe', 'guardarian', 'transak', 'infinia', 'cobre'), Decimal(0))
    # Legacy provider mirrors are canonical here; never add Guardarian's raw
    # transaction table or the same payment's deposit/conversion again.
    dollars = DecimalField(max_digits=78, decimal_places=18)
    zero = Value(Decimal(0), output_field=dollars)
    # Preserve the historical on-chain deposit boundary: a proven stablecoin
    # receipt counts before minting. Provider status/quotes alone never do.
    legacy = RampTransaction.objects.filter(direction='on_ramp', status='COMPLETED',
        provider__in=('koywe', 'guardarian', 'transak'))
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
    mirrors = MoneyFlow.objects.filter(Q(infinia_journey__isnull=False) | Q(cobre_journey__isnull=False)).values('legacy_ramp_transaction_id')
    legacy = legacy.exclude(pk__in=mirrors.exclude(legacy_ramp_transaction__isnull=True))
    for row in legacy.values('provider').annotate(total=Sum(contribution)):
        totals[row['provider']] += row['total']
    # Keep the ramp's allocated final_amount above: a single conversion may
    # settle multiple ramps, so summing its full net once per ramp duplicates it.
    incoming_net = Coalesce('wallet_conversion__net_amount_exact', Case(
        When(wallet_conversion__conversion_type='usdt_to_cusd', then=F('wallet_conversion__to_amount')),
        default=zero, output_field=dollars), output_field=dollars)
    totals['infinia'] = InfiniaJourney.objects.filter(
        direction='to_wallet', stage='completed', wallet_conversion__status='COMPLETED',
        wallet_conversion__is_deleted=False,
    ).aggregate(total=Sum(Greatest(incoming_net, zero), output_field=dollars))['total'] or Decimal(0)
    # Bridge units are an integer string. NULL/empty represents no proven
    # output; cast to numeric in SQL rather than materializing every journey.
    units = Coalesce(Cast(NullIf('bridge__actual_out_units', Value('')), dollars), zero)
    totals['cobre'] = CobreJourney.objects.filter(
        direction='to_wallet', stage='completed', bridge__status='delivered',
    ).aggregate(total=Sum(Greatest(units, zero) / Value(Decimal(10**18)),
        output_field=dollars))['total'] or Decimal(0)
    return totals
