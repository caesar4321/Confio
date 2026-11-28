import copy
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from p2p_exchange.models import P2PPaymentMethod
from ramps import koywe
from ramps.models import RampPaymentMethod


def _writes(ctx):
    """Row saves and inserts. The bulk switch-off of dropped methods is filtered
    to rows still active, so on an unchanged catalog it matches nothing."""
    sqls = [q['sql'] for q in ctx.captured_queries]
    return [s for s in sqls if s.lstrip().upper().startswith('INSERT')
            or (s.lstrip().upper().startswith('UPDATE') and 'SET "is_active" = false' not in s)]


class CatalogSyncWritesOnlyChangesTests(TestCase):
    def setUp(self):
        koywe.sync_country_payment_methods('CO')

    def test_first_sync_creates_every_method_active(self):
        codes = {m['code'] for m in koywe.COUNTRY_METHODS['CO']['methods']}
        rows = RampPaymentMethod.objects.filter(country_code='CO')
        self.assertEqual(set(rows.values_list('code', flat=True)), codes)
        self.assertTrue(all(rows.values_list('is_active', flat=True)))

    def test_repeat_sync_writes_nothing(self):
        before = dict(RampPaymentMethod.objects.filter(country_code='CO').values_list('code', 'updated_at'))
        with CaptureQueriesContext(connection) as ctx:
            koywe.sync_country_payment_methods('CO')
        self.assertEqual(_writes(ctx), [])
        after = dict(RampPaymentMethod.objects.filter(country_code='CO').values_list('code', 'updated_at'))
        self.assertEqual(before, after)

    def test_admin_switch_off_survives_a_sync(self):
        RampPaymentMethod.objects.filter(country_code='CO', code='NEQUI').update(is_active=False)
        P2PPaymentMethod.objects.filter(country_code='CO', name='nequi').update(is_active=False)
        koywe.sync_country_payment_methods('CO')
        self.assertFalse(RampPaymentMethod.objects.get(country_code='CO', code='NEQUI').is_active)
        self.assertFalse(P2PPaymentMethod.objects.get(country_code='CO', name='nequi').is_active)

    def test_catalog_change_writes_only_that_row(self):
        config = copy.deepcopy(koywe.COUNTRY_METHODS['CO'])
        target = next(m for m in config['methods'] if m['code'] == 'BREB')
        target['display_name'] = 'Bre-B nuevo'
        untouched = RampPaymentMethod.objects.get(country_code='CO', code='NEQUI').updated_at
        with mock.patch.dict(koywe.COUNTRY_METHODS, {'CO': config}):
            koywe.sync_country_payment_methods('CO')
        self.assertEqual(RampPaymentMethod.objects.get(country_code='CO', code='BREB').display_name, 'Bre-B nuevo')
        self.assertEqual(RampPaymentMethod.objects.get(country_code='CO', code='NEQUI').updated_at, untouched)

    def test_method_dropped_from_catalog_is_switched_off(self):
        config = copy.deepcopy(koywe.COUNTRY_METHODS['CO'])
        config['methods'] = [m for m in config['methods'] if m['code'] != 'BREB']
        with mock.patch.dict(koywe.COUNTRY_METHODS, {'CO': config}):
            koywe.sync_country_payment_methods('CO')
        self.assertFalse(RampPaymentMethod.objects.get(country_code='CO', code='BREB').is_active)
