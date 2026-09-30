from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from ramps.koywe import has_unpaid_koywe_order, lock_koywe_on_ramp_slot, UNPAID_ORDER_MESSAGE
from ramps.koywe import UnpaidKoyweOrderError
from ramps.models import RampTransaction
from ramps.schema import CreateRampOrder


class UnpaidOrderGuardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username='unpaid-guard')

    def order(self, **kwargs):
        return RampTransaction.objects.create(**dict(
            {'provider': 'koywe', 'direction': 'on_ramp', 'actor_user': self.user,
             'status': 'PENDING', 'provider_order_id': 'existing', 'destination': 'cusd_plus'},
            **kwargs))

    def test_unpaid_or_unknown_order_blocks_regardless_of_wallet_or_age(self):
        for provider_id in ('existing', ''):
            with self.subTest(provider_id=provider_id):
                row = self.order(provider_order_id=provider_id, actor_address='old-wallet', country_code='BR')
                RampTransaction.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(days=30))
                self.assertTrue(has_unpaid_koywe_order(self.user))
                with transaction.atomic(), self.assertRaisesMessage(UnpaidKoyweOrderError, UNPAID_ORDER_MESSAGE):
                    lock_koywe_on_ramp_slot(self.user)
                row.delete()

    def test_other_providers_offramps_and_paid_or_terminal_orders_do_not_block(self):
        for overrides in ({'provider': 'guardarian'}, {'direction': 'off_ramp'},
                          {'status': 'PROCESSING'}, {'status': 'COMPLETED'}, {'status': 'FAILED'}):
            row = self.order(**overrides)
            self.assertFalse(has_unpaid_koywe_order(self.user))
            row.delete()

    def test_provider_confirmed_cancellation_releases_slot(self):
        from ramps.koywe_sync import sync_koywe_ramp_transaction_from_order
        row = self.order()
        with mock.patch('ramps.bsc_provider_hash.attach_after_koywe_sync'):
            sync_koywe_ramp_transaction_from_order(ramp_tx=row,
                order_payload={'orderId': 'existing', 'status': 'REJECTED'})
        self.assertFalse(has_unpaid_koywe_order(self.user))

    def test_other_user_does_not_occupy_slot(self):
        other = get_user_model().objects.create(username='unpaid-other', firebase_uid='unpaid-other')
        self.order(actor_user=other)
        self.assertFalse(has_unpaid_koywe_order(self.user))

    def test_poller_reconciles_unpaid_orders_older_than_seven_days(self):
        from ramps.tasks import poll_koywe_ramp_transactions
        row = self.order()
        RampTransaction.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(days=30))
        with mock.patch('ramps.tasks.KoyweClient') as client, \
             mock.patch('ramps.bsc_provider_hash.attach_after_koywe_sync'):
            client.return_value.get_ramp_order_status.return_value = SimpleNamespace(
                raw_response={'orderId': 'existing', 'status': 'REJECTED'}, next_action_url=None)
            poll_koywe_ramp_transactions()
        client.return_value.get_ramp_order_status.assert_called_once_with(order_id='existing', email=None)
        self.assertFalse(has_unpaid_koywe_order(self.user))

    def test_real_mutation_blocks_before_provider_or_face(self):
        self.order()
        info = SimpleNamespace(context=SimpleNamespace(user=self.user, META={}))
        with mock.patch('ramps.schema._employee_ramp_denial', return_value=None), \
             mock.patch('ramps.schema._resolve_ramp_country_code', return_value='PE'), \
             mock.patch('ramps.schema._get_ramp_account_for_user', return_value=SimpleNamespace(account_type='personal')), \
             mock.patch('ramps.schema.KoyweClient') as client, \
             mock.patch('security.face_step_up.missing_face_step_up') as face:
            result = CreateRampOrder().mutate(info, direction='ON_RAMP', amount='100', payment_method_code='WIRE')
        self.assertFalse(result.success)
        self.assertEqual(result.error, UNPAID_ORDER_MESSAGE)
        self.assertEqual(result.next_step, 'resume_order')
        self.assertEqual(result.order_id, 'existing')
        self.assertEqual(result.destination, 'cusd_plus')
        client.assert_not_called()
        face.assert_not_called()


    def test_unknown_creation_has_no_resumable_or_stale_payment_details(self):
        from ramps.schema import _unpaid_order_response
        row = self.order(provider_order_id='', metadata={'next_action_url': 'https://stale.invalid'})
        result = _unpaid_order_response(row)
        self.assertIsNone(result.next_step)
        self.assertIsNone(result.order_id)
        self.assertIsNone(result.payment_details)
        self.assertIsNone(result.next_action_url)


class UnpaidOrderConcurrencyTests(TransactionTestCase):
    def test_only_one_concurrent_request_can_reserve_the_user_slot(self):
        user = get_user_model().objects.create(username='unpaid-concurrent')
        barrier = Barrier(2)

        def reserve(destination):
            try:
                barrier.wait(timeout=10)
                with transaction.atomic():
                    lock_koywe_on_ramp_slot(user)
                    RampTransaction.objects.create(provider='koywe', direction='on_ramp',
                        actor_user=user, status='PENDING', destination=destination)
                return 'reserved'
            except UnpaidKoyweOrderError:
                return 'blocked'
            finally:
                connections['default'].close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, ['cusd', 'cusd_plus']))
        self.assertCountEqual(results, ['reserved', 'blocked'])
        self.assertEqual(RampTransaction.objects.filter(actor_user=user).count(), 1)
