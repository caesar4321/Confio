import dataclasses
from contextlib import ExitStack
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import reverse

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
