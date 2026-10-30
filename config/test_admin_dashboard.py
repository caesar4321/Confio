import dataclasses
from decimal import Decimal
from contextlib import ExitStack
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from config import admin_dashboard_sections as sections
from config.admin_dashboard import confio_admin_site
from cusd_plus import metrics

UNAVAILABLE_BSC = metrics._cusd_bsc_unavailable(wired=True, address='0xcusd', source='unavailable')
UNAVAILABLE_PLUS = metrics._unavailable(True, '0xplus', 'unavailable')


def chain_reads(bsc=UNAVAILABLE_BSC, plus=UNAVAILABLE_PLUS):
    """No RPC in tests: every chain read the pages make, stubbed."""
    stack = ExitStack()
    for target, value in (
        ('cusd_plus.metrics.get_cusd_bsc_platform_metrics', bsc),
        ('cusd_plus.metrics.get_cusd_plus_platform_metrics', plus),
        ('cusd_plus.metrics.get_stock_router_metrics', {}),
        ('cusd_plus.gm_tvl.snapshot', None),
        ('ramps.metrics.public_fund_flow_snapshot', None),
        ('blockchain.cusd_metrics.get_cusd_platform_metrics', mock.Mock(
            circulating_cusd=None, tvl_cusd=None, source='unavailable', as_of=None)),
    ):
        stack.enter_context(mock.patch(target, return_value=value))
    return stack


class DashboardPagesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_superuser(
            username='dash-admin', email='dash@example.test', password=None)
        self.user.is_verified = lambda: True

    def staff(self, *perms):
        request = RequestFactory().get('/')
        request.user = mock.Mock(has_perm=lambda perm: perm in perms)
        return request

    def get(self, name, **query):
        request = RequestFactory().get(reverse(f'confio_admin:{name}'), query)
        request.user = self.user
        request.session = SessionStore()
        view = next(u.callback for u in confio_admin_site.get_urls() if getattr(u, 'name', None) == name)
        return view(request)

    def test_every_page_renders_with_its_tabs(self):
        pages = ['dashboard'] + [f'dash_{key}' for key, *_ in confio_admin_site.DASH_PAGES if key != 'today']
        with chain_reads():
            for name in pages:
                with self.subTest(page=name):
                    response = self.get(name)
                    self.assertEqual(response.status_code, 200)
                    html = response.content.decode()
                    for _key, label, *_ in confio_admin_site.DASH_PAGES:
                        self.assertIn(label.replace('&', '&amp;'), html)
                    self.assertNotIn('nav-sidebar', html)

    def test_model_index_is_still_reachable(self):
        response = self.get('app_list_index')
        response.render()
        self.assertEqual(response.status_code, 200)

    def test_today_reports_unknown_collateral_instead_of_passing(self):
        # "Could not read the vault" must surface, never read as healthy.
        with chain_reads():
            titles = [item['title'] for item in sections.needs_attention(sections.Window.current(), self.staff())]
        self.assertIn('cUSD (BSC): chain read unavailable', titles)
        self.assertIn('cUSD+: chain read unavailable', titles)

    def test_undercollateralised_vault_is_critical_and_listed_first(self):
        short = dataclasses.replace(UNAVAILABLE_PLUS, source='bsc', backing_ratio_bps=9_800)
        with chain_reads(plus=short):
            items = sections.needs_attention(sections.Window.current(), self.staff())
        self.assertEqual(items[0]['level'], sections.CRITICAL)
        self.assertEqual(items[0]['title'], 'cUSD+ is undercollateralised')
        self.assertIn('98.00%', items[0]['detail'])

    def test_unconfigured_vault_is_not_an_alert(self):
        unwired = dataclasses.replace(UNAVAILABLE_BSC, wired=False, source='unconfigured')
        with chain_reads(bsc=unwired):
            titles = [item['title'] for item in sections.needs_attention(sections.Window.current(), self.staff())]
        self.assertFalse([t for t in titles if t.startswith('cUSD (BSC)')])

    def test_chain_reads_are_cached_until_refresh(self):
        healthy = dataclasses.replace(UNAVAILABLE_BSC, source='bsc', backing_ratio_bps=10_000)
        with mock.patch('cusd_plus.metrics.get_cusd_bsc_platform_metrics', return_value=healthy) as read:
            sections.cusd_bsc(sections.Window.current())
            sections.cusd_bsc(sections.Window.current())
            self.assertEqual(read.call_count, 1)
            sections.cusd_bsc(sections.Window.current(), refresh=True)
            self.assertEqual(read.call_count, 2)
        # Every rebuild skips the helper's own 30s cache.
        self.assertEqual(read.call_args_list, [mock.call(use_cache=False)] * 2)

    def test_pages_carry_metrics_their_partials_borrow(self):
        # cUSD+ shows the shared cUSD fee; Money's fee table shows the router fee.
        with chain_reads():
            w = sections.Window.current()
            self.assertIn('cusd_bsc_metrics', sections.cusd_plus(w))
            self.assertIn('stock_router_metrics', sections.cusd_bsc(w))

    def test_failed_chain_read_is_retried_not_cached(self):
        with mock.patch('cusd_plus.metrics.get_cusd_bsc_platform_metrics', return_value=UNAVAILABLE_BSC) as read:
            sections.cusd_bsc(sections.Window.current())
            sections.cusd_bsc(sections.Window.current())
        self.assertEqual(read.call_count, 2)

    def test_unreadable_pause_flag_is_reported(self):
        partial = dataclasses.replace(UNAVAILABLE_BSC, source='bsc', backing_ratio_bps=10_000, paused=None)
        with chain_reads(bsc=partial):
            titles = [i['title'] for i in sections.needs_attention(sections.Window.current(), self.staff())]
        self.assertIn('cUSD (BSC): pause state unreadable', titles)

    def test_infinia_counts_need_the_infinia_view_permission(self):
        with chain_reads(), \
                mock.patch('payment_accounts.monitoring.stalled_count', return_value=2) as stalled, \
                mock.patch('payment_accounts.monitoring.needs_review_count', return_value=1):
            hidden = [i['title'] for i in sections.needs_attention(sections.Window.current(), self.staff())]
            stalled.assert_not_called()
            shown = [i['title'] for i in sections.needs_attention(
                sections.Window.current(), self.staff('payment_accounts.view_infiniajourney'))]
        self.assertFalse([t for t in hidden if t.startswith('Infinia')])
        self.assertIn('Infinia transfers not moving for over an hour', shown)
        self.assertIn('Infinia transfers halted for review', shown)

    def test_failed_refresh_drops_the_older_healthy_read(self):
        healthy = dataclasses.replace(UNAVAILABLE_BSC, source='bsc', backing_ratio_bps=10_000)
        # Three separate page loads, each with its own window.
        with mock.patch('cusd_plus.metrics.get_cusd_bsc_platform_metrics', return_value=healthy):
            sections.cusd_bsc(sections.Window.current())
        with mock.patch('cusd_plus.metrics.get_cusd_bsc_platform_metrics', return_value=UNAVAILABLE_BSC):
            sections.cusd_bsc(sections.Window.current(), refresh=True)
        with mock.patch('cusd_plus.metrics.get_cusd_bsc_platform_metrics', return_value=UNAVAILABLE_BSC) as read:
            self.assertEqual(sections.cusd_bsc(sections.Window.current())['cusd_bsc_metrics'].source, 'unavailable')
        read.assert_called_once()

    def test_one_page_shows_one_read_per_vault_even_on_refresh(self):
        # Alerts and tiles on Today must describe the same chain read.
        w = sections.Window.current()
        with chain_reads(), mock.patch(
                'cusd_plus.metrics.get_cusd_bsc_platform_metrics', return_value=UNAVAILABLE_BSC) as read:
            sections.needs_attention(w, self.staff(), refresh=True)
            sections.today_money(w, refresh=True)
        read.assert_called_once()

    def test_failed_fee_ledger_reads_unavailable_not_empty(self):
        from django.template.loader import render_to_string

        html = render_to_string('admin/dash/today.html', {'fee_ledger': None, 'dash_tabs': []})
        self.assertIn('unavailable', html)
        self.assertNotIn('none yet', html)

    def _rollup_titles(self):
        with chain_reads():
            return [i['title'] for i in sections.needs_attention(sections.Window.current(), self.staff())
                    if i['title'].startswith('Funnel rollup missing')]

    def test_empty_day_is_not_a_missing_rollup(self):
        from datetime import timedelta
        from django.utils import timezone
        from users.models_analytics import FunnelEvent

        # Only an older event: the rollup's target day had nothing to roll up.
        event = FunnelEvent.objects.create(event_name='signup_completed')
        FunnelEvent.objects.filter(pk=event.pk).update(created_at=timezone.now() - timedelta(days=5))
        self.assertEqual(self._rollup_titles(), [])

    def test_day_with_events_and_no_rollup_is_flagged(self):
        from datetime import timedelta, timezone as dt_timezone
        from django.utils import timezone
        from users.models_analytics import FunnelEvent

        now = timezone.now()
        target = (now - timedelta(days=1, hours=4, minutes=30)).astimezone(dt_timezone.utc).date()
        event = FunnelEvent.objects.create(event_name='signup_completed')
        FunnelEvent.objects.filter(pk=event.pk).update(
            created_at=timezone.datetime.combine(target, timezone.datetime.min.time(), dt_timezone.utc)
            + timedelta(hours=12))
        self.assertEqual(self._rollup_titles(), [f'Funnel rollup missing for {target}'])

    def test_fresh_sponsored_batch_is_not_unresolved(self):
        from datetime import timedelta
        from django.utils import timezone
        from blockchain.models import SponsoredBatch

        with mock.patch.object(SponsoredBatch.objects, 'filter', wraps=SponsoredBatch.objects.filter) as flt:
            with chain_reads():
                sections.needs_attention(sections.Window.current(), self.staff())
        kwargs = [c.kwargs for c in flt.call_args_list if 'created_at__lt' in c.kwargs]
        self.assertEqual(len(kwargs), 1)
        self.assertLess(kwargs[0]['created_at__lt'], timezone.now() - timedelta(minutes=14))

    def test_crypto_trades_are_counted_apart_from_stocks(self):
        from blockchain.models import SponsoredBatch
        from cusd_plus.metrics import get_crypto_trade_stats, get_stock_trade_stats

        fields = {f.name for f in SponsoredBatch._meta.fields}
        self.assertIn('kind', fields)
        with mock.patch.object(SponsoredBatch.objects, 'filter', wraps=SponsoredBatch.objects.filter) as flt:
            get_crypto_trade_stats()
            get_stock_trade_stats()
        kinds = [c.kwargs.get('kind__in') for c in flt.call_args_list if 'kind__in' in c.kwargs]
        self.assertEqual(kinds, [('crypto_buy', 'crypto_sell'), ('stock_buy', 'stock_sell')])

    def test_today_trades_tile_sums_stocks_and_crypto(self):
        stats = lambda v: {'total_volume': Decimal(v), 'confirmed': 1}  # noqa: E731
        with chain_reads(), \
                mock.patch('cusd_plus.metrics.get_stock_trade_stats', return_value=stats('199')), \
                mock.patch('cusd_plus.metrics.get_crypto_trade_stats', return_value=stats('50')):
            money = sections.today_money(sections.Window.current())
        self.assertEqual(money['trades_24h_volume'], Decimal('249'))

    def test_only_didit_in_review_documents_need_attention(self):
        from security.models import IdentityVerification

        with mock.patch.object(IdentityVerification.all_documents, 'filter',
                               wraps=IdentityVerification.all_documents.filter) as flt:
            with chain_reads():
                sections.needs_attention(sections.Window.current(), self.staff())
        self.assertIn(mock.call(sections.DIDIT_IN_REVIEW), flt.call_args_list)
        self.assertNotIn(mock.call(status='pending'), flt.call_args_list)

    def test_presale_is_live_and_only_phases_are_archived(self):
        pages = {key: partials for key, _l, _b, partials, _o in confio_admin_site.DASH_PAGES}
        self.assertIn('admin/dash/_presale.html', pages['presale'])
        self.assertIn('admin/dash/_presale_phases.html', pages['archive'])
        self.assertNotIn('admin/dash/_presale.html', pages['archive'])

    def test_unsigned_presale_checkout_is_not_a_stuck_purchase(self):
        from datetime import timedelta
        from django.utils import timezone
        from presale.models import PresalePhase, PresalePurchase

        phase = PresalePhase.objects.create(phase_number=99, name='t', price_per_token=Decimal('0.2'),
                                            goal_amount=Decimal('1'), max_per_user=Decimal('1000'),
                                            min_purchase=Decimal('1'), status='active')
        from presale.bsc_flow import BSC_FUNDING_SOURCES

        purchase = PresalePurchase.objects.create(
            user=self.user, phase=phase, cusd_amount=Decimal('10'), confio_amount=Decimal('50'),
            price_per_token=Decimal('0.2'), status='processing', funding_source=sorted(BSC_FUNDING_SOURCES)[0])
        PresalePurchase.objects.filter(pk=purchase.pk).update(created_at=timezone.now() - timedelta(hours=3))
        w = sections.Window.current()
        self.assertEqual(sections.presale_awaiting_reconciliation(w), 0)
        self.assertEqual(sections.presale(w)['presale_pipeline']['abandoned_checkouts'], 1)
        PresalePurchase.objects.filter(pk=purchase.pk).update(transaction_hash='0xabc')
        self.assertEqual(sections.presale_awaiting_reconciliation(w), 1)
        # Never both: a submitted purchase is not an abandoned checkout.
        self.assertEqual(sections.presale(w)['presale_pipeline']['abandoned_checkouts'], 0)

    def test_confio_price_reports_its_source(self):
        from presale import price_utils

        cache.clear()
        with self.settings(BSC_PRESALE_VAULT_ADDRESS='0xvault'), \
                mock.patch('cusd_plus.tasks._rpc', side_effect=RuntimeError('rpc down')):
            price, source = price_utils.get_confio_price_with_source()
            self.assertIn(source, ('phase', 'floor'))
            cache.set(price_utils.LAST_KNOWN_KEY, '0.31', 60)
            self.assertEqual(price_utils.get_confio_price_with_source(), (Decimal('0.31'), 'last_known'))
            self.assertEqual(price_utils.get_confio_current_price(), Decimal('0.31'))
        cache.set(price_utils.CACHE_KEY, '0.32', 60)
        self.assertEqual(price_utils.get_confio_price_with_source(), (Decimal('0.32'), 'live'))

    def test_presale_on_without_active_phase_is_critical(self):
        from presale.models import PresalePhase, PresaleSettings

        settings_row = PresaleSettings.get_settings()
        settings_row.is_presale_active = True
        settings_row.save()
        PresalePhase.objects.filter(status='active').update(status='paused')
        with chain_reads(), mock.patch('presale.price_utils.get_confio_price_with_source',
                                       return_value=(Decimal('0.2'), 'floor')):
            items = sections.needs_attention(sections.Window.current(), self.staff())
        titles = {i['title']: i['level'] for i in items}
        self.assertEqual(titles.get('Presale is on but no phase is active'), sections.CRITICAL)
        self.assertEqual(titles.get('CONFIO price is not the live curve'), sections.WARNING)

    def test_top_countries_survive_the_gap_between_snapshot_jobs(self):
        # 03:00 UTC writes DailyMetrics, 03:15 CountryMetrics: in between the
        # newest daily date has no country rows yet.
        from datetime import date
        from users.models_analytics import CountryMetrics

        # Only yesterday's country rows exist; no date is taken from DailyMetrics.
        CountryMetrics.objects.create(date=date(2026, 10, 19), country_code='VE', mau=5, wau=3, dau=1,
                                      total_users=9, new_users_today=0)
        rows = sections.top_countries(8)
        self.assertEqual([r['country_code'] for r in rows], ['VE'])
        self.assertEqual(sections.today_growth(sections.Window.current())['top_countries_metrics'], rows)

    def test_comprar_page_shows_status_and_what_needs_action(self):
        from marketplace.models import MarketplaceCity, MarketplacePartnerAgreement
        MarketplaceCity.objects.update_or_create(
            country_code='BO', city='La Paz', defaults={'currency_code': 'BOB', 'is_live': True})
        uncapped = (2**128 - 1, 2**128 - 1, 0)
        with self.settings(MARKETPLACE_ESCROW_ADDRESS='0x' + 'e5' * 20,
                           CUSD_VAULT_ADDRESS='0x' + 'c0' * 20), \
                mock.patch('marketplace.escrow.token_limits', return_value=uncapped):
            html = self.get('dash_comprar').content.decode()
        self.assertIn('cUSD accepted · no caps', html)
        self.assertIn('La Paz, BO', html)
        self.assertIn('No active partner agreement', html)
        MarketplacePartnerAgreement.objects.create(
            partner_name='Jason', country_code='BO', share_bps=5000, started_at=timezone.now())
        with self.settings(MARKETPLACE_ESCROW_ADDRESS='0x' + 'e5' * 20,
                           CUSD_VAULT_ADDRESS='0x' + 'c0' * 20), \
                mock.patch('marketplace.escrow.token_limits', side_effect=RuntimeError('rpc down')):
            html = self.get('dash_comprar').content.decode()
        self.assertNotIn('No active partner agreement', html)
        self.assertIn('Jason BO 50% of fee', html)
        self.assertIn('cUSD limits unreadable', html)  # a failed read is unknown, never "off"

    def test_rails_table_needs_the_infinia_view_permission(self):
        self.assertEqual(sections.rails_by_period(sections.Window.current(), self.staff()), {})

    def test_rails_by_period_splits_providers_and_windows(self):
        from datetime import timedelta
        from django.utils import timezone
        from ramps.metrics import rail_flows_by_period
        from ramps.models import RampTransaction

        base = dict(actor_user=self.user, direction='off_ramp', status='COMPLETED',
                    crypto_currency='USDT BSC', crypto_amount_actual=Decimal('10'))
        now = timezone.now()
        fresh = RampTransaction.objects.create(provider='vexpay', **base)
        old = RampTransaction.objects.create(provider='koywe', **base)
        RampTransaction.objects.filter(pk=fresh.pk).update(completed_at=now - timedelta(hours=2))
        RampTransaction.objects.filter(pk=old.pk).update(completed_at=now - timedelta(days=10))
        w = sections.Window.current()
        rows = {r['label']: r['cells'] for r in rail_flows_by_period(w.periods())['withdrawals']}
        # A rail outside the public deposit figure's provider list still shows.
        self.assertEqual([c['usd'] for c in rows['VEXPay']], [Decimal('10')] * 4)
        self.assertEqual([c['count'] for c in rows['Koywe']], [0, 0, 1, 1])

    def test_ves_sends_count_their_verified_funding(self):
        # ve_send never sets crypto_amount_actual; an unfunded row proves nothing.
        from django.utils import timezone
        from ramps.metrics import rail_flows_by_period
        from ramps.models import RampTransaction

        base = dict(provider='pagoasap', actor_user=self.user, direction='off_ramp', status='COMPLETED',
                    completed_at=timezone.now())
        RampTransaction.objects.create(metadata={'ve_send': {'funded_wei': str(25 * 10**18)}}, **base)
        RampTransaction.objects.create(metadata={'ve_send': {}}, **base)
        rows = {r['label']: r['cells'] for r in
                rail_flows_by_period(sections.Window.current().periods())['withdrawals']}
        self.assertEqual(rows['Pago ASAP'][0]['usd'], Decimal('25'))
        self.assertEqual(rows['Pago ASAP'][0]['count'], 1)

    def test_investing_table_lists_every_product(self):
        table = sections.investing_by_period(sections.Window.current())['period_table']
        labels = [r['label'] for r in table['groups'][0]['rows']]
        self.assertEqual(labels, ['Stocks buys', 'Stocks sells', 'Crypto & gold buys', 'Crypto & gold sells',
                                  'Futures margin in', 'Futures dollars back'])
        self.assertTrue(all(len(r['cells']) == 4 for r in table['groups'][0]['rows']))

    def test_arrival_without_a_link_pairs_by_person_amount_and_time(self):
        from datetime import timedelta
        from django.utils import timezone
        from ramps.metrics import tie_to_conversions

        now = timezone.now()
        arrivals = [{'user': 1, 'usd': Decimal('100'), 'at': now},   # became conversion 10
                    {'user': 2, 'usd': Decimal('50'), 'at': now}]    # stayed USDT
        conversions = [{'id': 10, 'user': 1, 'usd': Decimal('99.5'), 'at': now + timedelta(hours=1)},
                       {'id': 11, 'user': 2, 'usd': Decimal('80'), 'at': now + timedelta(hours=1)},  # direct
                       {'id': 12, 'user': 1, 'usd': Decimal('100'), 'at': now + timedelta(days=30)}]  # too late
        tied, unpaired = tie_to_conversions(arrivals, conversions)
        self.assertEqual(tied, {10})
        self.assertEqual([r['user'] for r in unpaired], [2])

    def test_every_rail_is_listed_before_its_first_operation(self):
        from ramps.metrics import rail_flows_by_period

        flows = rail_flows_by_period(sections.Window.current().periods())
        for group in ('deposits', 'withdrawals'):
            labels = [r['label'] for r in flows[group]]
            self.assertIn('Pago ASAP', labels)
            self.assertIn('Mesa de pagos', labels)
        self.assertEqual(len(flows['direct_in']), 4)

    def test_two_businesses_never_share_a_pairing_bucket(self):
        from django.utils import timezone
        from ramps.metrics import tie_to_conversions

        now = timezone.now()
        tied, unpaired = tie_to_conversions(
            [{'user': ('business', 1), 'usd': Decimal('100'), 'at': now}],
            [{'id': 5, 'user': ('business', 2), 'usd': Decimal('100'), 'at': now}])
        self.assertEqual(tied, set())
        self.assertEqual(len(unpaired), 1)

    def test_pairing_does_not_depend_on_query_order(self):
        from datetime import timedelta
        from django.utils import timezone
        from ramps.metrics import tie_to_conversions

        now = timezone.now()
        arrivals = [{'user': 1, 'usd': Decimal('100'), 'at': now},
                    {'user': 1, 'usd': Decimal('100'), 'at': now + timedelta(days=6)}]
        early = {'id': 1, 'user': 1, 'usd': Decimal('100'), 'at': now + timedelta(days=1)}
        late = {'id': 2, 'user': 1, 'usd': Decimal('100'), 'at': now + timedelta(days=6)}
        tied, unpaired = tie_to_conversions(arrivals, [late, early])
        self.assertEqual(tied, {1, 2})
        self.assertEqual(unpaired, [])
