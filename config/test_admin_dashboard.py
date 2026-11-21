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

    def test_today_trades_tile_sums_stocks_crypto_and_futures(self):
        stats = lambda v: {'total_volume': Decimal(v), 'confirmed': 1}  # noqa: E731
        flow = lambda v: {'label': '', 'cells': [{'usd': Decimal(v), 'count': 1, 'users': 1}]}  # noqa: E731
        with chain_reads(), \
                mock.patch('cusd_plus.metrics.get_stock_trade_stats', return_value=stats('199')), \
                mock.patch('cusd_plus.metrics.get_crypto_trade_stats', return_value=stats('50')), \
                mock.patch('cusd_plus.metrics.futures_flows_by_period',
                           return_value=[flow('30'), flow('5'), flow('20')]):
            money = sections.today_money(sections.Window.current())
        self.assertEqual(money['futures_flow_24h'], Decimal('55'))
        self.assertEqual(money['trades_24h_volume'], Decimal('304'))

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
        self.assertIn('admin/dash/_presale.html', pages['ops'])
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
                                  'Futures margin in', 'Futures margin added', 'Futures dollars back'])
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


class ActivationTests(TestCase):
    def setUp(self):
        cache.clear()

    def member(self, name, *, days_ago=1, country='BO'):
        from datetime import timedelta
        from django.utils import timezone

        return get_user_model().objects.create(
            username=name, firebase_uid=f'activation-{name}', country=country,
            onboarded_at=timezone.now() - timedelta(days=days_ago))

    def test_cohort_counts_a_deposit_that_never_converted_as_funded(self):
        from datetime import timedelta
        from django.utils import timezone
        from config import admin_dashboard_growth as growth

        funded, idle = self.member('funded'), self.member('idle', country='AR')
        venezuelan = self.member('venezuelan', country='VE')
        at = timezone.now() - timedelta(hours=3)
        with mock.patch('ramps.metrics.deposit_events', return_value=[(funded.pk, at), (venezuelan.pk, at)]):
            result = growth.activation(sections.Window.current())['activation']
        week = result['cohorts'][0]
        self.assertEqual((week['all']['signups'], week['all']['funded']), (3, 2))
        self.assertEqual(result['focus_countries'], ('BO', 'VE'))
        self.assertEqual([(r['signups'], r['funded']) for r in week['focus']], [(1, 1), (1, 1)])
        self.assertEqual((week['rest']['signups'], week['rest']['funded']), (1, 0))
        self.assertEqual(result['funded_30d'], 2)
        self.assertAlmostEqual(result['funded_pct'], 200 / 3)
        self.assertIsNotNone(idle)

    def test_retention_only_counts_days_the_table_can_measure(self):
        from datetime import date, timedelta
        from django.utils import timezone
        from config import admin_dashboard_growth as growth
        from users.activity_tracking import ACTIVITY_DAY_TZ
        from users.models_analytics import UserActivityDay

        back = self.member('back', days_ago=2)
        self.member('gone', days_ago=2)
        joined = timezone.localtime(back.onboarded_at, ACTIVITY_DAY_TZ).date()
        UserActivityDay.objects.create(user=back, day=joined + timedelta(days=1), first_seen_at=timezone.now())
        w = sections.Window.current()
        with mock.patch.object(growth, 'ACTIVITY_RELIABLE_SINCE', date(2000, 1, 1)):
            d1 = growth.retention(w)['retention']['d1']
        self.assertEqual((d1['back'], d1['eligible']), (1, 2))
        with mock.patch.object(growth, 'ACTIVITY_RELIABLE_SINCE', timezone.now().date() + timedelta(days=30)):
            self.assertEqual(growth.retention(w)['retention']['d1']['eligible'], 0)

    def test_one_unknown_part_makes_customer_assets_unknown(self):
        known = mock.Mock(circulating_cusd=Decimal('10'), circulating_cusd_plus=Decimal('5'))
        self.assertEqual(sections._customer_assets(known, known, {'value_usd': 2}), Decimal('17'))
        self.assertIsNone(sections._customer_assets(known, known, None))
        blind = mock.Mock(circulating_cusd=None, circulating_cusd_plus=Decimal('5'))
        self.assertIsNone(sections._customer_assets(blind, known, {'value_usd': 2}))

    def test_chart_marks_the_day_activity_became_reliable(self):
        from datetime import date

        rows = [{'date': date(2026, 10, 28), 'dau': 1, 'wau': 1, 'mau': 1},
                {'date': date(2026, 10, 29), 'dau': 1, 'wau': 1, 'mau': 1}]
        self.assertEqual([r['reliable'] for r in sections.trend_chart(rows)], [False, True])

    def test_signup_completion_follows_one_cohort(self):
        from datetime import timedelta
        from django.utils import timezone

        old = self.member('old-account', days_ago=1)
        User = get_user_model()
        User.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=60))
        User.objects.create(username='started', firebase_uid='activation-started')
        context = sections.users_core(sections.Window.current())
        # The old account finishing now is a signup but not this cohort's rate.
        self.assertEqual(context['new_users_last_7_days'], 1)
        self.assertEqual(context['finished_signups_last_7_days'], 0)
        self.assertEqual(context['signup_completion_last_7_days'], 0)


    def test_journey_rails_need_the_infinia_view_permission(self):
        from config import admin_dashboard_growth as growth
        from payment_accounts.models import InfiniaJourney

        allowed = mock.Mock(user=mock.Mock(has_perm=lambda perm: True))
        denied = mock.Mock(user=mock.Mock(has_perm=lambda perm: False))
        with mock.patch.object(InfiniaJourney, 'objects') as journeys:
            growth.deposit_health(sections.Window.current(), denied)
            journeys.filter.assert_not_called()
            journeys.filter.return_value.order_by.return_value.aggregate.return_value = {
                'total': 0, 'completed': 0, 'failed': 0}
            growth.deposit_health(sections.Window.current(), allowed)
            journeys.filter.assert_called()

    def test_retention_activity_counts_only_real_members(self):
        from django.utils import timezone
        from config import admin_dashboard_growth as growth
        from users.activity_tracking import ACTIVITY_DAY_TZ
        from users.models_analytics import UserActivityDay

        real, robot = self.member('real-one'), self.member('robot-one')
        get_user_model().objects.filter(pk=robot.pk).update(is_platform_test_account=True)
        today = timezone.localtime(timezone.now(), ACTIVITY_DAY_TZ).date()
        for user in (real, robot):
            UserActivityDay.objects.create(user=user, day=today, first_seen_at=timezone.now())
        self.assertEqual(growth.retention(sections.Window.current())['retention']['active_7d'], 1)


class SmartAccountSectionTests(TestCase):
    """Cuenta inteligente on the Community page: empty, populated, linked."""

    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_superuser(
            username='smart-dash-admin', email='smart-dash@example.test', password=None)
        self.admin.is_verified = lambda: True
        self._addr = iter(range(1, 10_000))

    def address(self):
        return '0x' + format(next(self._addr), '040x')

    def page(self):
        request = RequestFactory().get(reverse('confio_admin:dash_community'))
        request.user = self.admin
        request.session = SessionStore()
        view = next(u.callback for u in confio_admin_site.get_urls() if getattr(u, 'name', None) == 'dash_community')
        return view(request).content.decode()

    def open_link(self, url):
        """A changelist link resolves and its filters are valid (an invalid
        filter redirects to ?e=1 instead of listing)."""
        from urllib.parse import parse_qsl, urlsplit
        from django.urls import resolve

        parts = urlsplit(url)
        request = RequestFactory().get(parts.path, dict(parse_qsl(parts.query)))
        request.user = self.admin
        request.session = SessionStore()
        match = resolve(parts.path)
        return match.func(request, *match.args, **match.kwargs)

    def member(self, name):
        from users.models import Account

        user = get_user_model().objects.create(username=name, firebase_uid=f'smart-dash-{name}')
        Account.objects.create(user=user, account_type='personal', account_index=0, bsc_address=self.address())
        return user

    def smart(self, user, status='active', plan='annual', billing='current', **fields):
        from users.models import Account
        from smart_account.models import SmartAccount

        contract = self.address()
        row = Account.objects.create(user=user, account_type='smart', account_index=0, bsc_address=contract)
        return SmartAccount.objects.create(
            owner_user=user, owner_account=Account.objects.get(user=user, account_type='personal'), account=row,
            contract_address=contract, status=status, billing_status=billing,
            plan='' if status == 'inherited' else plan, **fields)

    def event(self, account, name, *, applied=True, minutes_ago=0, **args):
        from smart_account.models import SmartAccountEvent

        now = timezone.now()
        event = SmartAccountEvent.objects.create(
            smart_account=account, address=account.contract_address, tx_hash='0x' + format(next(self._addr), '064x'),
            log_index=0, name=name, args=args, block_number=next(self._addr),
            block_time=now - timezone.timedelta(minutes=minutes_ago), applied_at=now if applied else None)
        SmartAccountEvent.objects.filter(pk=event.pk).update(created_at=now - timezone.timedelta(minutes=minutes_ago))
        return event

    def test_feature_off_and_empty_tables_render(self):
        from config.admin_dashboard_smart_account import smart_account

        with self.settings(SMART_ACCOUNT_ENABLED=False, SMART_ACCOUNT_FACTORY_ADDRESS='',
                           SMART_ACCOUNT_PAYOUT_RAILS='', SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED=False):
            data = smart_account(sections.Window.current())['smart_account']
            html = self.page()
        self.assertFalse(data['feature']['enabled'])
        self.assertEqual(data['accounts']['subscribers'], 0)
        self.assertEqual(data['revenue']['window']['usd'], Decimal('0'))
        self.assertFalse(data['ops']['needs_action'])
        self.assertIsNone(data['ops']['oldest_unapplied'])
        self.assertIn('Cuenta inteligente', html)
        self.assertIn('Factory not set', html)
        self.assertIn('No payout rail offered', html)
        self.assertIn('never scanned', html)
        self.assertIn('Cuenta inteligente funnel (30d)', html)

    def test_a_failed_build_renders_as_unavailable(self):
        with mock.patch('config.admin_dashboard_smart_account._build', side_effect=RuntimeError('db')):
            html = self.page()
        self.assertIn('Cuenta inteligente figures are unavailable', html)

    def test_populated_section_counts_and_links(self):
        from config.admin_dashboard_smart_account import smart_account
        from smart_account.models import (
            SmartAccountBeneficiary, SmartAccountCharge, SmartAccountClaim, SmartAccountForcedSale,
            SmartAccountRelayTx, SmartAccountRule, SmartAccountRuleRun)

        now = timezone.now()
        ana, ben, cai, dan = (self.member(n) for n in ('ana', 'ben', 'cai', 'dan'))
        annual = self.smart(ana)
        monthly = self.smart(ben, status='cancel_pending', plan='monthly', billing='notice')
        self.smart(cai, status='expired')
        self.smart(dan, status='inherited')
        subscribed = self.event(annual, 'Subscribed')
        self.event(monthly, 'SubscriptionCancelled')
        fee = self.event(monthly, 'FeeCollected')
        SmartAccountCharge.objects.create(
            smart_account=annual, event=subscribed, plan='annual', period_start=now, period_end=now,
            fee_usd=Decimal('149.99'), paid_with='cusd', tx_hash=subscribed.tx_hash, charged_at=now)
        SmartAccountCharge.objects.create(
            smart_account=monthly, event=fee, plan='monthly', period_start=now, period_end=now,
            fee_usd=Decimal('14.99'), paid_with='sale', tx_hash=fee.tx_hash,
            charged_at=now - timezone.timedelta(days=20))
        SmartAccountForcedSale.objects.create(smart_account=monthly, period_end=now, status='succeeded',
                                              dollars_out=str(1499 * 10 ** 16))
        SmartAccountForcedSale.objects.create(smart_account=annual, period_end=now, status='failed')
        rule = SmartAccountRule.objects.create(smart_account=annual, kind='send', token_in=self.address(),
                                               amount=Decimal('10'), frequency='weekly', active=True, state='onchain')
        SmartAccountRule.objects.create(smart_account=annual, kind='buy', token_in=self.address(),
                                        amount=Decimal('5'), frequency='daily', active=False, state='cancelled')
        for hours, status, error in ((1, 'ok', ''), (2, 'skipped', 'insufficient_balance'),
                                     (3, 'skipped', 'insufficient_balance'), (4, 'failed', 'transaction dropped')):
            SmartAccountRuleRun.objects.create(rule=rule, scheduled_for=now - timezone.timedelta(hours=hours),
                                               status=status, error=error)
        designation = SmartAccountBeneficiary.objects.create(
            smart_account=annual, beneficiary_user=ben, beneficiary_address=self.address(),
            challenge_window_seconds=86400, state='active')
        SmartAccountBeneficiary.objects.create(
            smart_account=monthly, beneficiary_user=ana, beneficiary_address=self.address(),
            challenge_window_seconds=86400, state='pending_acceptance')
        soon = now + timezone.timedelta(days=3)
        SmartAccountClaim.objects.create(beneficiary_row=designation, initiated_at=now, executable_at=soon,
                                         initiated_tx='0x01')
        SmartAccountClaim.objects.create(beneficiary_row=designation, initiated_at=now,
                                         executable_at=now - timezone.timedelta(hours=1), initiated_tx='0x02')
        SmartAccountClaim.objects.create(beneficiary_row=designation, initiated_at=now, executable_at=now,
                                         initiated_tx='0x03', state='cancelled', cancelled_at=now)
        stuck = SmartAccountRelayTx.objects.create(smart_account=annual, kind='collect', source_id='p1',
                                                   calldata='0x', signed_tx_hash='0xaa', status='sent')
        SmartAccountRelayTx.objects.filter(pk=stuck.pk).update(created_at=now - timezone.timedelta(minutes=40))
        SmartAccountRelayTx.objects.create(smart_account=annual, kind='collect', source_id='p2',
                                           calldata='0x', signed_tx_hash='0xbb', status='dropped')
        SmartAccountRelayTx.objects.create(smart_account=annual, kind='collect', source_id='p3',
                                           calldata='0x', signed_tx_hash='0xcc', status='sent')  # fresh
        self.event(monthly, 'Withdrawn', applied=False, minutes_ago=90)
        self.event(monthly, 'Traded', applied=False, minutes_ago=5)

        with self.settings(SMART_ACCOUNT_ENABLED=True, SMART_ACCOUNT_FACTORY_ADDRESS='0x' + 'fa' * 20,
                           SMART_ACCOUNT_BENEFICIARY_ENABLED=True, SMART_ACCOUNT_PAYOUT_RAILS='bogus_rail',
                           SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED=False, SMART_ACCOUNT_ALLOWED_USER_IDS='1,2'):
            data = smart_account(sections.Window.current())['smart_account']
            html = self.page()

        accounts = data['accounts']
        self.assertEqual({r['label']: r['n'] for r in accounts['rows']}['Active'], 1)
        self.assertEqual(accounts['own'], 3)
        self.assertEqual(accounts['subscribers'], 2)
        self.assertEqual({r['label']: r['n'] for r in accounts['plans']}, {'Annual': 1, 'Monthly': 1})
        self.assertEqual({r['label']: r['n'] for r in accounts['billing']}['Notice running'], 1)
        self.assertEqual((accounts['new_subscriptions'], accounts['cancellations']), (1, 1))
        revenue = data['revenue']
        self.assertEqual((revenue['window']['n'], revenue['window']['usd']), (1, Decimal('149.99')))
        self.assertEqual((revenue['rolling_30']['n'], revenue['rolling_30']['usd']), (2, Decimal('164.98')))
        by_paid = {r['label']: (r['window']['n'], r['rolling_30']['n']) for r in revenue['paid_with']}
        self.assertEqual(by_paid['cUSD'], (1, 1))
        self.assertEqual(by_paid['Paid by forced sale'], (0, 1))
        forced = revenue['forced']
        self.assertEqual((forced['n'], forced['succeeded'], forced['failed'], forced['dollars']),
                         (2, 1, 1, Decimal('14.99')))
        automation = data['automation']
        self.assertEqual(automation['rules_total'], 1)
        self.assertEqual({r['label']: r['n'] for r in automation['runs']},
                         {'Pending': 0, 'Sent': 0, 'Executed': 1, 'Skipped': 2, 'Failed': 1})
        self.assertEqual(automation['skip_reasons'], [('insufficient_balance', 2)])
        self.assertEqual(automation['fail_reasons'], [('transaction dropped', 1)])
        beneficiaries = data['beneficiaries']
        self.assertEqual({r['label']: r['n'] for r in beneficiaries['rows']}['Accepted'], 1)
        claims = beneficiaries['claims']
        self.assertEqual((claims['waiting'], claims['executable'], claims['cancelled'], claims['executed']),
                         (1, 1, 1, 0))
        self.assertEqual(claims['soonest'], soon)
        ops = data['ops']
        self.assertEqual((ops['stuck_relay'], ops['bad_relay'], ops['unapplied'], ops['unapplied_old']),
                         (1, 1, 2, 1))
        self.assertEqual(ops['blocked_accounts'], 1)
        self.assertGreaterEqual(ops['oldest_unapplied_minutes'], 89)
        self.assertEqual(ops['failed_sales'], 1)
        self.assertTrue(ops['needs_action'])
        feature = data['feature']
        self.assertEqual((feature['enabled'], feature['canary'], feature['rails_offered']), (True, 2, []))
        self.assertEqual(feature['rails_configured'], ['bogus_rail'])
        self.assertIn('not final after 15 min', html)
        self.assertIn('Next executable'.lower(), html.lower())

        urls = [r['url'] for group in (accounts['rows'], accounts['plans'], accounts['billing'],
                                       revenue['paid_with'], automation['rules'], automation['runs'],
                                       beneficiaries['rows']) for r in group]
        urls += [accounts['all_url'], accounts['events_url'], revenue['window']['url'], forced['url'],
                 forced['failed_url'], claims['pending_url'], claims['cancelled_url'], claims['executed_url'],
                 ops['stuck_relay_url'], ops['bad_relay_url'], ops['unapplied_url']]
        self.assertNotIn(None, urls)
        for url in urls:
            with self.subTest(url=url):
                response = self.open_link(url)
                self.assertEqual(response.status_code, 200)
        # The filtered lists hold the rows the counts describe.
        response = self.open_link(ops['stuck_relay_url'])
        self.assertEqual(response.context_data['cl'].result_count, 1)
        response = self.open_link(ops['unapplied_url'])
        self.assertEqual(response.context_data['cl'].result_count, 2)

    def test_funnel_counts_people_per_stage_without_preview_users(self):
        from config import admin_dashboard_growth as growth
        from users.models_analytics import FunnelEvent

        real, staff = self.member('real'), self.member('staff')
        for user, stage, plan in ((real, 'subscribe_opened', ''), (real, 'subscribe_opened', ''),
                                  (real, 'subscribed', 'annual'), (staff, 'subscribed', 'monthly')):
            FunnelEvent.objects.create(event_name='smart_account_funnel', user=user,
                                       properties={'stage': stage, 'plan': plan})
        old = FunnelEvent.objects.create(event_name='smart_account_funnel', user=real,
                                         properties={'stage': 'cancelled', 'plan': 'annual'})
        FunnelEvent.objects.filter(pk=old.pk).update(created_at=timezone.now() - timezone.timedelta(days=40))
        with self.settings(PAID_OFFER_PREVIEW_USER_IDS=str(staff.pk)):
            rows = {r['stage']: r for r in growth.demand(sections.Window.current())['demand_smart_funnel']}
        self.assertEqual([r for r in rows], [key for key, _label in growth.SMART_FUNNEL_STAGES])
        self.assertEqual(rows['subscribe_opened']['people'], 1)
        self.assertEqual((rows['subscribed']['people'], rows['subscribed']['annual'],
                          rows['subscribed']['monthly']), (1, 1, 0))
        self.assertEqual(rows['cancelled']['people'], 0)
