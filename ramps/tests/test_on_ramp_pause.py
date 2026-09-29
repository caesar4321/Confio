from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from ramps import schema as ramps_schema
from ramps.koywe import on_ramp_paused, on_ramp_rejection_locked
from ramps.models import RampTransaction


class OnRampPauseTests(SimpleTestCase):
    @override_settings(KOYWE_ON_RAMP_PAUSED_COUNTRIES=['CO'])
    def test_paused_country_is_case_insensitive(self):
        self.assertTrue(on_ramp_paused('CO'))
        self.assertTrue(on_ramp_paused('co'))
        self.assertFalse(on_ramp_paused('MX'))
        self.assertFalse(on_ramp_paused(None))

    @override_settings(KOYWE_ON_RAMP_PAUSED_COUNTRIES=[])
    def test_empty_setting_lifts_the_pause(self):
        self.assertFalse(on_ramp_paused('CO'))

    def test_colombia_is_paused_by_default(self):
        self.assertTrue(on_ramp_paused('CO'))
        self.assertFalse(on_ramp_paused('PE'))


def _live_order(user, country):
    info = SimpleNamespace(context=SimpleNamespace(user=user, META={}))
    with mock.patch.object(ramps_schema, '_employee_ramp_denial', return_value=None), \
         mock.patch.object(ramps_schema, '_resolve_ramp_country_code', return_value=country), \
         mock.patch.object(ramps_schema, '_get_ramp_account_for_user',
                           return_value=SimpleNamespace(account_type='personal')), \
         mock.patch.object(ramps_schema, 'KoyweClient') as provider:
        result = ramps_schema.CreateRampOrder().mutate(
            info, direction='ON_RAMP', amount='100000', payment_method_code='PSE')
    return result, provider


class LiveOnRampGuardTests(TestCase):
    """The pause and the rejection lock must hold on the REAL order mutation,
    not only on the availability list the app reads."""

    def setUp(self):
        self.user = get_user_model().objects.create(username='onramp-guard', email='guard@example.com')

    def _rejections(self, n, hours_ago=1):
        for i in range(n):
            tx = RampTransaction.objects.create(
                provider='koywe', direction='on_ramp', status='FAILED', status_detail='rejected',
                actor_user=self.user, country_code='PE')
            RampTransaction.objects.filter(pk=tx.pk).update(
                created_at=timezone.now() - timedelta(hours=hours_ago, minutes=i))

    @override_settings(KOYWE_ON_RAMP_PAUSED_COUNTRIES=['CO'])
    def test_paused_country_refuses_a_live_order(self):
        result, provider = _live_order(self.user, 'CO')
        self.assertFalse(result.success)
        self.assertIn('no están disponibles', result.error)
        provider.assert_not_called()

    def test_rejection_lock_trips_at_the_limit_and_refuses_a_live_order(self):
        self._rejections(4)
        self.assertFalse(on_ramp_rejection_locked(self.user))
        self._rejections(1)
        self.assertTrue(on_ramp_rejection_locked(self.user))
        result, provider = _live_order(self.user, 'PE')
        self.assertFalse(result.success)
        self.assertIn('límite de intentos', result.error)
        provider.assert_not_called()

    def test_rejection_lock_lapses_on_its_own(self):
        self._rejections(5, hours_ago=25)
        self.assertFalse(on_ramp_rejection_locked(self.user))

    @override_settings(FACE_STEP_UP_ENABLED=True)
    def test_live_order_asks_for_the_face_first(self):
        result, provider = _live_order(self.user, 'PE')
        self.assertFalse(result.success)
        self.assertEqual(result.next_step, 'face_check')
        provider.assert_not_called()

    def test_expired_orders_do_not_count(self):
        for _ in range(6):
            RampTransaction.objects.create(
                provider='koywe', direction='on_ramp', status='FAILED', status_detail='provider_expired',
                actor_user=self.user, country_code='PE')
        self.assertFalse(on_ramp_rejection_locked(self.user))
