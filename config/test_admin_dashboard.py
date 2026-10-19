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
            titles = [item['title'] for item in sections.needs_attention(sections.Window.current())]
        self.assertIn('cUSD (BSC): chain read unavailable', titles)
        self.assertIn('cUSD+: chain read unavailable', titles)

    def test_undercollateralised_vault_is_critical_and_listed_first(self):
        short = dataclasses.replace(UNAVAILABLE_PLUS, source='bsc', backing_ratio_bps=9_800)
        with chain_reads(plus=short):
            items = sections.needs_attention(sections.Window.current())
        self.assertEqual(items[0]['level'], sections.CRITICAL)
        self.assertEqual(items[0]['title'], 'cUSD+ is undercollateralised')
        self.assertIn('98.00%', items[0]['detail'])

    def test_unconfigured_vault_is_not_an_alert(self):
        unwired = dataclasses.replace(UNAVAILABLE_BSC, wired=False, source='unconfigured')
        with chain_reads(bsc=unwired):
            titles = [item['title'] for item in sections.needs_attention(sections.Window.current())]
        self.assertFalse([t for t in titles if t.startswith('cUSD (BSC)')])

    def test_chain_reads_are_cached_until_refresh(self):
        healthy = dataclasses.replace(UNAVAILABLE_BSC, source='bsc', backing_ratio_bps=10_000)
        with mock.patch('cusd_plus.metrics.get_cusd_bsc_platform_metrics', return_value=healthy) as read:
            sections.cusd_bsc(sections.Window.current())
            sections.cusd_bsc(sections.Window.current())
            self.assertEqual(read.call_count, 1)
            sections.cusd_bsc(sections.Window.current(), refresh=True)
            self.assertEqual(read.call_count, 2)

    def test_failed_chain_read_is_retried_not_cached(self):
        with mock.patch('cusd_plus.metrics.get_cusd_bsc_platform_metrics', return_value=UNAVAILABLE_BSC) as read:
            sections.cusd_bsc(sections.Window.current())
            sections.cusd_bsc(sections.Window.current())
        self.assertEqual(read.call_count, 2)
