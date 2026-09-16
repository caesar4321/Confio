"""Read-only operational metrics. A provider leg is not an end-to-end payment."""
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from django.db.models import Case, When, Value, F, Q, Count, Sum, CharField, DecimalField
from django.db.models.functions import Coalesce, Greatest

from .activity import display_stage
from .models import AutomaticPayin, InfiniaJourney


def journeys():
    return InfiniaJourney.objects.select_related(
        'confio_account__user', 'confio_account__business', 'local_account',
        'money_flow', 'funding_credit', 'bridge', 'wallet_conversion', 'payout_operation')


def delivered_usd(journey):
    """Net incoming wallet credit; savings token units are not dollar units."""
    if journey.direction != 'to_wallet' or display_stage(journey) != 'completed':
        return Decimal(0)
    conversion = journey.wallet_conversion
    if not conversion or conversion.is_deleted:
        return Decimal(0)
    amount = conversion.net_amount_exact
    if amount is None and conversion.conversion_type == 'usdt_to_cusd':
        amount = conversion.to_amount
    return max(amount or Decimal(0), Decimal(0))


def dashboard_context(request):
    if not request.user.has_perm('payment_accounts.view_infiniajourney'):
        return {}
    country = request.GET.get('infinia_country', '').strip().upper()
    direction = request.GET.get('infinia_direction', 'all')
    if direction not in ('all', 'to_wallet', 'to_bank'):
        direction = 'all'
    qs = journeys()
    countries = list(qs.order_by('local_account__country').values_list(
        'local_account__country', flat=True).distinct())
    if country:
        qs = qs.filter(local_account__country=country)
    sections = []
    for selected, title in [('to_wallet', 'Infinia incoming payments'), ('to_bank', 'Infinia outgoing payments')]:
        if direction not in ('all', selected):
            continue
        counts = Counter()
        decimal = DecimalField(max_digits=40, decimal_places=18)
        zero = Value(Decimal(0), output_field=decimal)
        selected_qs = qs.filter(direction=selected).annotate(
            reported_stage=Case(
                When(direction='to_bank', bridge__status='refunded', then=Value('refunded')),
                When(Q(direction='to_wallet', stage='completed') &
                     (Q(wallet_conversion__isnull=True) | ~Q(wallet_conversion__status='COMPLETED')),
                     then=Value('awaiting_wallet_conversion')),
                default=F('stage'), output_field=CharField()),
            net_usd=Case(
                When(direction='to_wallet', stage='completed', wallet_conversion__status='COMPLETED',
                     wallet_conversion__is_deleted=False, then=Greatest(Coalesce(
                         F('wallet_conversion__net_amount_exact'),
                         Case(When(wallet_conversion__conversion_type='usdt_to_cusd',
                                   then=F('wallet_conversion__to_amount')), default=zero, output_field=decimal),
                         output_field=decimal), zero)),
                default=zero, output_field=decimal))
        processing = ~Q(reported_stage__in=['completed', 'failed', 'refunded', 'needs_review'])
        for row in selected_qs.order_by().values('reported_stage').annotate(count=Count('pk')):
            counts[row['reported_stage']] = row['count']
            counts['total'] += row['count']
        summary = selected_qs.aggregate(volume=Sum('net_usd'),
            processing=Count('pk', filter=processing),
            stalled=Count('pk', filter=processing & Q(updated_at__lt=timezone.now()-timedelta(hours=1))))
        counts.update({key: summary[key] for key in ('processing', 'stalled')})
        rail = F('local_account__payin_rail') if selected == 'to_wallet' else F('destination_snapshot__destination_account__type')
        breakdown = list(selected_qs.order_by().annotate(country=F('local_account__country'),
            currency=F('local_account__asset'), rail=rail).values('country', 'currency', 'rail').annotate(
                count=Count('pk'), completed=Count('pk', filter=Q(reported_stage='completed')),
                volume=Sum('net_usd'),
                fiat_delivered=Sum('money_flow__target_amount', filter=Q(reported_stage='completed')),
                fiat_known=Count('pk', filter=Q(reported_stage='completed', money_flow__target_amount__isnull=False)),
                fiat_unknown=Count('pk', filter=Q(reported_stage='completed', money_flow__target_amount__isnull=True))
            ).order_by('country', 'currency', 'rail'))
        recent = []
        for j in qs.filter(direction=selected).order_by('-created_at', '-pk')[:10]:
            stage = display_stage(j)
            recent.append({'url': reverse('admin:payment_accounts_infiniajourney_change', args=[j.pk]),
                    'id': str(j.internal_id)[:8], 'account': str(j.confio_account),
                    'amount': j.funding_credit.amount if j.funding_credit_id and selected == 'to_wallet' else j.money_flow.source_amount,
                    'asset': j.local_account.asset if selected == 'to_wallet' else j.money_flow.source_asset,
                    'stage': stage, 'failure': j.failure_code, 'created_at': j.created_at})
        sections.append({'title': title, 'incoming': selected == 'to_wallet', 'counts': dict(counts),
            'volume': summary['volume'] or Decimal(0), 'rate': 100 * counts['completed'] / counts['total'] if counts['total'] else 0,
            'breakdown': breakdown,
            'recent': recent})
    waiting = None
    if request.user.has_perm('payment_accounts.view_automaticpayin'):
        pending = AutomaticPayin.objects.filter(entry__provider='infinia', entry__funded_journey__isnull=True)
        if country:
            pending = pending.filter(entry__financial_account__country=country)
        waiting = pending.count()
    from ramps.metrics import deposited_volume_by_provider
    provider_volumes = deposited_volume_by_provider()
    return {'infinia_sections': sections, 'infinia_countries': countries,
        'deposited_provider_volumes': provider_volumes, 'deposited_all_providers': sum(provider_volumes.values(), Decimal(0)),
        'infinia_country': country, 'infinia_direction': direction, 'infinia_unstarted': waiting}
