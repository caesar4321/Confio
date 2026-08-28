from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import requests
from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase

from ramps import schema as ramps_schema
from ramps import signals as ramps_signals
from ramps.koywe_client import (
    KoyweClient,
    KoyweError,
    KoyweMinimumAmountError,
    KoyweOrderCreationAmbiguousError,
)
from ramps.koywe_sync import (
    build_koywe_instruction_snapshot,
    _merge_koywe_metadata,
    upsert_koywe_ramp_transaction,
)
from ramps.models import RampTransaction
from ramps.tasks import poll_koywe_ramp_transactions
from users.models import Account


User = get_user_model()


class KoyweNotificationTimingUnitTests(SimpleTestCase):
    def _ramp(self, *, reservation_state, provider_recorded=False):
        ramp = SimpleNamespace(
            actor_user_id=1,
            actor_user=SimpleNamespace(id=1),
            actor_business=None,
            direction='on_ramp',
            fiat_amount=Decimal('500'),
            fiat_currency='BRL',
            final_amount=Decimal('94.90'),
            crypto_amount_actual=None,
            crypto_amount_estimated=None,
            final_currency='CUSD+',
            provider='koywe',
            status='PENDING',
            metadata={'wallet_address_reservation_state': reservation_state},
            internal_id='reservation-id',
        )
        ramp._provider_order_just_recorded = provider_recorded
        return ramp

    @mock.patch('ramps.signals.create_notification')
    def test_preorder_reservation_is_silent(self, notify_mock):
        ramps_signals._notify_ramp_status(
            self._ramp(reservation_state='creating_order'),
            created=True,
            previous_status=None,
        )

        notify_mock.assert_not_called()

    @mock.patch('ramps.signals.create_notification')
    def test_pending_notification_waits_for_provider_order(self, notify_mock):
        ramp = self._ramp(
            reservation_state='provider_order_recorded',
            provider_recorded=True,
        )
        ramps_signals._notify_ramp_status(
            ramp,
            created=False,
            previous_status='PENDING',
        )
        ramps_signals._notify_ramp_status(
            ramp,
            created=False,
            previous_status='PENDING',
        )

        notify_mock.assert_called_once()
        self.assertEqual(
            notify_mock.call_args.kwargs['notification_type'],
            'RAMP_PENDING',
        )


class KoyweOrderAmbiguityTests(SimpleTestCase):
    def _client_with_response(self, response):
        client = KoyweClient()
        client.authenticate = mock.Mock(return_value='token')
        client.session = mock.Mock()
        client.session.request.return_value = response
        return client

    def test_transport_failure_during_create_post_is_typed_as_ambiguous(self):
        client = KoyweClient()
        client.authenticate = mock.Mock(return_value='token')
        client.session = mock.Mock()
        client.session.request.side_effect = requests.Timeout('response lost')

        with self.assertRaises(KoyweOrderCreationAmbiguousError):
            client.create_order(
                quote_id='quote-1',
                email='owner@example.com',
                destination_address='0x' + ('1' * 40),
                external_id='confio-ramp-on_ramp-test',
            )

    def test_server_error_after_create_post_is_ambiguous(self):
        response = mock.Mock(ok=False, status_code=503)
        response.json.return_value = {'message': 'temporarily unavailable'}
        client = self._client_with_response(response)

        with self.assertRaises(KoyweOrderCreationAmbiguousError):
            client.create_order(
                quote_id='quote-1',
                external_id='confio-ramp-on_ramp-test',
            )

    def test_malformed_success_after_create_post_is_ambiguous(self):
        response = mock.Mock(ok=True, status_code=200)
        response.json.return_value = {'status': 'WAITING'}
        client = self._client_with_response(response)

        with self.assertRaises(KoyweOrderCreationAmbiguousError):
            client.create_order(
                quote_id='quote-1',
                external_id='confio-ramp-on_ramp-test',
            )

    def test_validation_rejection_after_create_post_remains_definitive(self):
        response = mock.Mock(ok=False, status_code=400)
        response.json.return_value = {'message': 'invalid destinationAddress'}
        client = self._client_with_response(response)

        with self.assertRaises(KoyweError) as raised:
            client.create_order(
                quote_id='quote-1',
                external_id='confio-ramp-on_ramp-test',
            )
        self.assertNotIsInstance(raised.exception, KoyweOrderCreationAmbiguousError)

    def test_conflict_after_create_post_is_ambiguous(self):
        response = mock.Mock(ok=False, status_code=409)
        response.json.return_value = {'message': 'externalId already exists'}
        client = self._client_with_response(response)

        with self.assertRaises(KoyweOrderCreationAmbiguousError):
            client.create_order(
                quote_id='quote-1',
                external_id='confio-ramp-on_ramp-test',
            )

    @mock.patch('ramps.koywe_client.cache.delete')
    def test_auth_rejection_refreshes_token_and_retries_once(self, cache_delete):
        rejected = mock.Mock(ok=False, status_code=400)
        rejected.json.return_value = {'message': 'Check your credentials'}
        accepted = mock.Mock(ok=True, status_code=200)
        accepted.json.return_value = {'items': [{'id': 'wire-br'}]}
        client = KoyweClient()
        client.authenticate = mock.Mock(side_effect=['stale-token', 'fresh-token'])
        client.session = mock.Mock()
        client.session.request.side_effect = [rejected, accepted]

        result = client._request(
            'GET',
            '/rest/payment-providers',
            email='owner@example.com',
        )

        self.assertEqual(result, {'items': [{'id': 'wire-br'}]})
        self.assertEqual(client.authenticate.call_count, 2)
        self.assertEqual(client.session.request.call_count, 2)
        cache_delete.assert_called_once_with('koywe:token:owner@example.com')

    @mock.patch('ramps.koywe_client.cache.delete')
    def test_auth_rejection_is_returned_after_single_retry(self, cache_delete):
        rejected = mock.Mock(ok=False, status_code=401)
        rejected.json.return_value = {'message': 'Check your credentials'}
        client = KoyweClient()
        client.authenticate = mock.Mock(side_effect=['stale-token', 'fresh-token'])
        client.session = mock.Mock()
        client.session.request.side_effect = [rejected, rejected]

        with self.assertRaisesRegex(KoyweError, 'Check your credentials'):
            client._request('GET', '/rest/accounts/test', email='owner@example.com')

        self.assertEqual(client.session.request.call_count, 2)
        cache_delete.assert_called_once()

    @mock.patch('ramps.koywe_client.cache.delete')
    def test_successful_list_response_is_not_treated_as_auth_rejection(self, cache_delete):
        providers = [{'id': 'pix-br', 'code': 'PIX_QR'}]
        response = mock.Mock(ok=True, status_code=200)
        response.json.return_value = providers
        client = self._client_with_response(response)

        result = client._request(
            'GET',
            '/rest/payment-providers',
            email='owner@example.com',
        )

        self.assertEqual(result, providers)
        self.assertEqual(client.authenticate.call_count, 1)
        self.assertEqual(client.session.request.call_count, 1)
        cache_delete.assert_not_called()


class KoyweAddressReservationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            username='koywe-reservation-owner',
            firebase_uid='koywe-reservation-owner-uid',
        )
        self.account = Account.objects.create(
            user=self.user,
            account_type='personal',
            account_index=0,
            bsc_address='0x' + ('1' * 40),
        )
        self.info = SimpleNamespace(
            context=SimpleNamespace(user=self.user, META={}),
        )

    def _mutate_with_error(self, error):
        client = mock.Mock(is_configured=True)
        client.create_ramp_order.side_effect = error
        with mock.patch('ramps.schema.KoyweClient', return_value=client), \
             mock.patch('ramps.schema._employee_ramp_denial', return_value=None), \
             mock.patch('ramps.schema._get_wallet_upgrade_blocker', return_value=None), \
             mock.patch('ramps.schema._resolve_ramp_country_code', return_value='PE'), \
             mock.patch('ramps.schema._get_ramp_account_for_user', return_value=self.account), \
             mock.patch('ramps.schema._get_koywe_auth_email', return_value='owner@example.com'), \
             mock.patch('ramps.schema._store_koywe_auth_email'), \
             mock.patch(
                 'ramps.schema._get_koywe_contact_profile',
                 return_value={'activity': 'EMPLOYEE'},
             ):
            return ramps_schema.CreateRampOrder().mutate(
                self.info,
                direction='ON_RAMP',
                amount='100',
                payment_method_code='WIREPE',
                country_code='PE',
                fiat_currency='PEN',
                destination='cusd_plus',
            )

    def test_definitive_order_rejection_releases_address_reservation(self):
        result = self._mutate_with_error(
            KoyweMinimumAmountError(
                'below minimum', actual='100', minimum='200', currency='PEN'
            )
        )

        self.assertFalse(result.success)
        self.assertFalse(RampTransaction.objects.exists())

    def test_ambiguous_order_post_retains_searchable_address_reservation(self):
        result = self._mutate_with_error(
            KoyweOrderCreationAmbiguousError('timeout after POST')
        )

        self.assertFalse(result.success)
        reservation = RampTransaction.objects.get()
        self.assertEqual(reservation.provider_order_id, '')
        self.assertTrue(reservation.external_id)
        self.assertEqual(
            reservation.metadata['wallet_address_reservation_state'],
            'ambiguous_order_creation',
        )
        self.assertEqual(reservation.metadata['reconcile_key'], reservation.external_id)

    def test_existing_unresolved_reservation_blocks_duplicate_provider_call(self):
        RampTransaction.objects.create(
            provider='koywe',
            direction='on_ramp',
            status='PENDING',
            provider_order_id='',
            external_id='confio-ramp-existing-inflight',
            actor_user=self.user,
            actor_type='user',
            actor_address=self.account.bsc_address,
            destination='cusd_plus',
            metadata={
                'wallet_address_reserved': True,
                'wallet_address_reservation_state': 'creating_order',
            },
        )
        client = mock.Mock(is_configured=True)
        with mock.patch('ramps.schema.KoyweClient', return_value=client), \
             mock.patch('ramps.schema._employee_ramp_denial', return_value=None), \
             mock.patch('ramps.schema._get_wallet_upgrade_blocker', return_value=None), \
             mock.patch('ramps.schema._resolve_ramp_country_code', return_value='BR'), \
             mock.patch('ramps.schema._get_ramp_account_for_user', return_value=self.account), \
             mock.patch('ramps.schema._get_koywe_auth_email', return_value='owner@example.com'), \
             mock.patch('ramps.schema._store_koywe_auth_email'), \
             mock.patch(
                 'ramps.schema._get_koywe_contact_profile',
                 return_value={'activity': 'EMPLOYEE'},
             ):
            result = ramps_schema.CreateRampOrder().mutate(
                self.info,
                direction='ON_RAMP',
                amount='500',
                payment_method_code='PIX',
                country_code='BR',
                fiat_currency='BRL',
                destination='cusd_plus',
            )

        self.assertFalse(result.success)
        self.assertIn('operación de ahorro en proceso', result.error)
        client.create_ramp_order.assert_not_called()
        self.assertEqual(RampTransaction.objects.count(), 1)

    @mock.patch('ramps.signals._notify_ramp_status', side_effect=RuntimeError('push db down'))
    @mock.patch('ramps.signals.sync_unified_transaction_from_ramp')
    def test_notification_failure_does_not_fail_ramp_save(self, _sync_mock, _notify_mock):
        ramp = RampTransaction.objects.create(
            provider='koywe',
            direction='on_ramp',
            status='PENDING',
            provider_order_id='koywe-order-notify-failure',
            external_id='confio-ramp-notify-failure',
            actor_user=self.user,
            actor_type='user',
            actor_address=self.account.bsc_address,
            destination='cusd_plus',
        )

        self.assertIsNotNone(ramp.pk)

    @mock.patch('ramps.signals._notify_ramp_status')
    @mock.patch(
        'ramps.signals.sync_unified_transaction_from_ramp',
        side_effect=RuntimeError('ledger sync down'),
    )
    def test_ledger_sync_failure_does_not_fail_ramp_save(self, _sync_mock, _notify_mock):
        ramp = RampTransaction.objects.create(
            provider='koywe',
            direction='on_ramp',
            status='PENDING',
            provider_order_id='koywe-order-ledger-failure',
            external_id='confio-ramp-ledger-failure',
            actor_user=self.user,
            actor_type='user',
            actor_address=self.account.bsc_address,
            destination='cusd_plus',
        )

        self.assertIsNotNone(ramp.pk)
        _notify_mock.assert_called_once()

    def test_provider_response_reuses_precreated_address_reservation(self):
        reservation = RampTransaction.objects.create(
            provider='koywe',
            direction='on_ramp',
            status='PENDING',
            external_id='confio-ramp-reservation-1',
            actor_type='user',
            actor_address='0x' + ('1' * 40),
            destination='cusd_plus',
            metadata={'wallet_address_reserved': True},
        )

        ramp_tx = upsert_koywe_ramp_transaction(
            actor_user=None,
            actor_business=None,
            actor_type='user',
            actor_display_name='Test User',
            actor_address='0x' + ('1' * 40),
            direction='ON_RAMP',
            destination='cusd_plus',
            country_code='PE',
            fiat_currency='PEN',
            payment_method_code='WIREPE',
            payment_method_display='Transferencia',
            order_id='koywe-order-1',
            external_id='confio-ramp-reservation-1',
            amount_in='100',
            amount_out='25',
            next_action_url=None,
            auth_email='user@example.com',
            order_payload={'status': 'WAITING'},
        )

        self.assertEqual(ramp_tx.pk, reservation.pk)
        self.assertEqual(RampTransaction.objects.count(), 1)
        self.assertEqual(ramp_tx.provider_order_id, 'koywe-order-1')
        self.assertEqual(
            ramp_tx.metadata['wallet_address_reservation_state'],
            'provider_order_recorded',
        )

    @mock.patch('ramps.signals.create_notification')
    def test_reservation_notifies_only_after_provider_order_exists(self, notify_mock):
        reservation = RampTransaction.objects.create(
            provider='koywe',
            direction='on_ramp',
            status='PENDING',
            provider_order_id='',
            external_id='confio-ramp-notification-1',
            actor_user=self.user,
            actor_type='user',
            actor_address=self.account.bsc_address,
            destination='cusd_plus',
            metadata={
                'wallet_address_reserved': True,
                'wallet_address_reservation_state': 'creating_order',
            },
        )

        notify_mock.assert_not_called()

        upsert_koywe_ramp_transaction(
            actor_user=self.user,
            actor_business=None,
            actor_type='user',
            actor_display_name='Test User',
            actor_address=self.account.bsc_address,
            direction='ON_RAMP',
            destination='cusd_plus',
            country_code='BR',
            fiat_currency='BRL',
            payment_method_code='PIX',
            payment_method_display='PIX',
            order_id='koywe-order-notification-1',
            external_id=reservation.external_id,
            amount_in='500',
            amount_out='94.90',
            next_action_url=None,
            auth_email='owner@example.com',
            order_payload={'status': 'WAITING'},
        )

        notify_mock.assert_called_once()
        self.assertEqual(
            notify_mock.call_args.kwargs['notification_type'],
            'RAMP_PENDING',
        )


class KoyweWebhookReservationRecoveryTests(SimpleTestCase):
    @mock.patch('ramps.views.verify_koywe_webhook_signature', return_value=True)
    @mock.patch('ramps.views.sync_koywe_ramp_transaction_from_order')
    @mock.patch('ramps.views.KoyweClient')
    @mock.patch('ramps.views.RampWebhookEvent.objects.get_or_create')
    @mock.patch('ramps.views.RampTransaction.objects.filter')
    def test_webhook_recovers_ambiguous_reservation_by_external_id(
        self,
        ramp_filter,
        event_get_or_create,
        client_class,
        sync_order,
        _verify_signature,
    ):
        reservation = SimpleNamespace(
            pk=1267,
            status='PENDING',
            provider_order_id='',
            external_id='confio-ramp-lost-create-response',
            actor_user_id=42,
            actor_user=SimpleNamespace(
                ramp_user_address=SimpleNamespace(auth_email='owner@example.com'),
            ),
            metadata={
                'wallet_address_reserved': True,
                'wallet_address_reservation_state': 'ambiguous_order_creation',
            },
        )
        provider_lookup = mock.Mock()
        provider_lookup.first.return_value = None
        external_lookup = mock.Mock()
        external_lookup.order_by.return_value.first.return_value = reservation
        reservation_update = mock.Mock()
        reservation_update.update.return_value = 1
        ramp_filter.side_effect = [
            provider_lookup,
            external_lookup,
            reservation_update,
        ]
        event_get_or_create.return_value = (SimpleNamespace(), True)

        client = client_class.return_value
        client.is_configured = True
        order_result = SimpleNamespace(
            next_action_url=None,
            raw_response={
                'orderId': 'koywe-order-recovered',
                'externalId': reservation.external_id,
                'status': 'REJECTED',
                'amountIn': '499',
                'amountOut': '95.82326',
                'symbolIn': 'BRL',
                'symbolOut': 'USDT BSC',
            },
        )
        client.get_ramp_order_status.return_value = order_result

        request = RequestFactory().post(
            '/api/koywe/webhook/',
            data={
                'eventName': 'payment_expired',
                'orderId': 'koywe-order-recovered',
                'externalId': reservation.external_id,
                'timeStamp': '2026-08-28T06:32:47.936Z',
            },
            content_type='application/json',
        )
        from ramps.views import koywe_webhook

        response = koywe_webhook(request)

        self.assertEqual(response.status_code, 200)
        external_lookup.order_by.assert_called_once_with('created_at')
        self.assertEqual(reservation.provider_order_id, 'koywe-order-recovered')
        self.assertEqual(
            reservation.metadata['wallet_address_reservation_state'],
            'provider_order_recorded',
        )
        reservation_update.update.assert_called_once()
        recovery_update_filter = ramp_filter.call_args_list[2].kwargs
        self.assertEqual(recovery_update_filter['status'], 'PENDING')
        self.assertEqual(
            recovery_update_filter['metadata__wallet_address_reservation_state__in'],
            ('creating_order', 'ambiguous_order_creation'),
        )
        client.get_ramp_order_status.assert_called_once_with(
            order_id='koywe-order-recovered',
            email='owner@example.com',
        )
        sync_order.assert_called_once_with(
            ramp_tx=reservation,
            order_payload=order_result.raw_response,
            next_action_url=None,
        )

    @mock.patch('ramps.views.verify_koywe_webhook_signature', return_value=True)
    @mock.patch('ramps.views.sync_koywe_ramp_transaction_from_order')
    @mock.patch('ramps.views.KoyweClient')
    @mock.patch('ramps.views.RampWebhookEvent.objects.get_or_create')
    @mock.patch('ramps.views.RampTransaction.objects.filter')
    def test_concurrent_recovery_reuses_the_provider_order_winner(
        self,
        ramp_filter,
        event_get_or_create,
        client_class,
        sync_order,
        _verify_signature,
    ):
        reservation = SimpleNamespace(
            pk=1267,
            metadata={'wallet_address_reservation_state': 'ambiguous_order_creation'},
        )
        recovered = SimpleNamespace(
            pk=1267,
            status='PROCESSING',
            provider_order_id='koywe-order-recovered',
            actor_user_id=None,
            metadata={'auth_email': 'owner@example.com'},
        )
        provider_lookup = mock.Mock()
        provider_lookup.first.return_value = None
        external_lookup = mock.Mock()
        external_lookup.order_by.return_value.first.return_value = reservation
        lost_update_race = mock.Mock()
        lost_update_race.update.return_value = 0
        concurrent_winner_lookup = mock.Mock()
        concurrent_winner_lookup.first.return_value = recovered
        ramp_filter.side_effect = [
            provider_lookup,
            external_lookup,
            lost_update_race,
            concurrent_winner_lookup,
        ]
        event_get_or_create.return_value = (SimpleNamespace(), True)

        client = client_class.return_value
        client.is_configured = True
        order_result = SimpleNamespace(
            next_action_url=None,
            raw_response={'status': 'PAYMENT_CREATED'},
        )
        client.get_ramp_order_status.return_value = order_result
        request = RequestFactory().post(
            '/api/koywe/webhook/',
            data={
                'eventName': 'payment_created',
                'orderId': recovered.provider_order_id,
                'externalId': 'confio-ramp-lost-create-response',
            },
            content_type='application/json',
        )
        from ramps.views import koywe_webhook

        response = koywe_webhook(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ramp_filter.call_args_list[3].kwargs,
            {
                'pk': reservation.pk,
                'provider_order_id': recovered.provider_order_id,
            },
        )
        client.get_ramp_order_status.assert_called_once_with(
            order_id=recovered.provider_order_id,
            email='owner@example.com',
        )
        sync_order.assert_called_once_with(
            ramp_tx=recovered,
            order_payload=order_result.raw_response,
            next_action_url=None,
        )

    @mock.patch('ramps.views.verify_koywe_webhook_signature', return_value=True)
    @mock.patch('ramps.views.KoyweClient')
    @mock.patch('ramps.views.RampWebhookEvent.objects.get_or_create')
    @mock.patch('ramps.views.RampTransaction.objects.filter')
    def test_webhook_does_not_recover_without_an_active_matching_reservation(
        self,
        ramp_filter,
        event_get_or_create,
        client_class,
        _verify_signature,
    ):
        provider_lookup = mock.Mock()
        provider_lookup.first.return_value = None
        external_lookup = mock.Mock()
        external_lookup.order_by.return_value.first.return_value = None
        ramp_filter.side_effect = [provider_lookup, external_lookup]
        event_get_or_create.return_value = (SimpleNamespace(), True)

        request = RequestFactory().post(
            '/api/koywe/webhook/',
            data={
                'eventName': 'payment_created',
                'orderId': 'koywe-order-unknown',
                'externalId': 'confio-ramp-not-a-live-reservation',
            },
            content_type='application/json',
        )
        from ramps.views import koywe_webhook

        response = koywe_webhook(request)

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                'ok': True,
                'stored': True,
                'order_id': 'koywe-order-unknown',
            },
        )
        client_class.assert_not_called()
        external_lookup.order_by.assert_called_once_with('created_at')
        recovery_filter = ramp_filter.call_args_list[1].kwargs
        self.assertEqual(recovery_filter['status'], 'PENDING')
        self.assertEqual(
            recovery_filter['metadata__wallet_address_reservation_state__in'],
            ('creating_order', 'ambiguous_order_creation'),
        )


class KoyweReservationPollingTests(SimpleTestCase):
    @mock.patch('ramps.tasks.KoyweClient')
    @mock.patch('ramps.tasks.RampTransaction.objects.filter')
    def test_poller_excludes_reservations_without_provider_order(self, filter_mock, client_mock):
        queryset = mock.Mock()
        queryset.exclude.return_value = queryset
        queryset.order_by.return_value = queryset
        queryset.exists.return_value = False
        filter_mock.return_value = queryset
        client_mock.return_value.is_configured = True

        result = poll_koywe_ramp_transactions()

        queryset.exclude.assert_called_once_with(provider_order_id='')
        self.assertEqual(result, 'No pending Koywe ramps')


class KoyweInstructionSnapshotTests(SimpleTestCase):
    def test_build_snapshot_extracts_generic_instruction_fields(self):
        payload = {
            'status': 'WAITING',
            'statusDetails': '',
            'symbolIn': 'ARS',
            'symbolOut': 'USDC Algorand',
            'amountIn': 30000,
            'amountOut': 20.4,
            'paymentMethodId': 'wirear-id',
            'providedAddress': 'Alias 30718280229.KOYWE1\nCBU 0000053600000017871248\nCUIT 30718280229',
            'beneficiaryName': 'Alerce Argentina SRL',
            'bankName': 'Agil Pagos',
            'reference': 'WY7ZEPN6...002Q0M51',
        }

        snapshot = build_koywe_instruction_snapshot(order_payload=payload, next_action_url=None)

        self.assertEqual(snapshot['provider_status'], 'WAITING')
        self.assertEqual(snapshot['fields']['beneficiary_name'], 'Alerce Argentina SRL')
        self.assertEqual(snapshot['fields']['bank_name'], 'Agil Pagos')
        self.assertEqual(snapshot['fields']['reference'], 'WY7ZEPN6...002Q0M51')
        self.assertEqual(snapshot['provided_address'], 'Alias 30718280229.KOYWE1\nCBU 0000053600000017871248\nCUIT 30718280229')
        self.assertTrue(any(row['value'] == '30718280229.KOYWE1' for row in snapshot['address_rows']))

    def test_merge_metadata_preserves_created_snapshots(self):
        original_payload = {
            'status': 'WAITING',
            'providedAddress': 'Alias original.koywe',
        }
        initial = _merge_koywe_metadata(
            existing_metadata=None,
            payment_method_code='WIREAR',
            payment_method_display='WIREAR',
            next_action_url=None,
            auth_email='user@example.com',
            order_payload=original_payload,
        )

        updated_payload = {
            'status': 'REJECTED',
            'providedAddress': 'Alias changed.koywe',
        }
        merged = _merge_koywe_metadata(
            existing_metadata=initial,
            payment_method_code='WIREAR',
            payment_method_display='WIREAR',
            next_action_url='https://provider.example/redirect',
            auth_email='user@example.com',
            order_payload=updated_payload,
        )

        self.assertEqual(
            merged['instruction_snapshot_created']['provided_address'],
            'Alias original.koywe',
        )
        self.assertEqual(
            merged['instruction_snapshot_latest']['provided_address'],
            'Alias changed.koywe',
        )
        self.assertEqual(
            merged['provider_payload_created']['providedAddress'],
            'Alias original.koywe',
        )
        self.assertEqual(
            merged['provider_payload_latest']['providedAddress'],
            'Alias changed.koywe',
        )


class KoyweClientProviderMergeTests(SimpleTestCase):
    def test_merge_payment_provider_details_promotes_provider_instructions(self):
        client = KoyweClient()
        order = {
            'orderId': 'abc',
            'status': 'WAITING',
        }
        provider = {
            '_id': 'provider-id',
            'name': 'WIREAR',
            'details': 'Alias 30718280229.KOYWE1\nCBU 0000053600000017871248',
            'image': 'https://rampa.koywe.com/paymentProviders/wire-ar.png',
        }

        enriched = client._merge_payment_provider_details(order=order, payment_provider=provider)

        self.assertEqual(enriched['providedAddress'], provider['details'])
        self.assertEqual(enriched['providedAction'], provider['image'])
        self.assertEqual(enriched['paymentMethodId'], 'provider-id')
        self.assertEqual(enriched['paymentMethodDisplay'], 'WIREAR')
        self.assertEqual(enriched['paymentProvider']['details'], provider['details'])


class KoyweExistingAccountProfileTests(SimpleTestCase):
    PAYLOAD = {
        'document': {
            'documentNumber': '1234567890',
            'documentType': 'CED_CIU',
            'country': 'COL',
            'isCompany': False,
        },
        'personalInfo': {
            'names': 'Duende',
            'firstLastname': 'Colombia',
            'activity': 'EMPLOYEE',
            'phoneNumber': '999999999',
            'dob': '1900-01-01',
        },
    }

    def test_unknown_email_reports_the_document_conflict(self):
        client = KoyweClient()

        with mock.patch.object(
            client,
            'get_account',
            side_effect=KoyweError('account not found with email: new@example.com'),
        ), mock.patch.object(client, 'update_account') as update_mock:
            with self.assertRaises(KoyweError) as ctx:
                client._ensure_existing_account_profile(
                    email='new@example.com',
                    country_code='CO',
                    payload=dict(self.PAYLOAD),
                    previous_emails=['old@example.com'],
                )

        update_mock.assert_not_called()
        self.assertIn('ya está registrado', str(ctx.exception))

    def test_failed_migration_does_not_update_the_unknown_email(self):
        client = KoyweClient()
        previous_account = {
            'email': 'old@example.com',
            'document': {
                'documentNumber': '1234567890',
                'documentType': 'CED_CIU',
                'country': 'COL',
            },
        }

        def fake_get_account(*, email):
            if email == 'old@example.com':
                return previous_account
            raise KoyweError(f'account not found with email: {email}')

        with mock.patch.object(client, 'get_account', side_effect=fake_get_account), \
                mock.patch.object(
                    client,
                    'update_account',
                    side_effect=KoyweError('email already in use'),
                ) as update_mock:
            with self.assertRaises(KoyweError) as ctx:
                client._ensure_existing_account_profile(
                    email='new@example.com',
                    country_code='CO',
                    payload=dict(self.PAYLOAD),
                    previous_emails=['old@example.com'],
                )

        # Only the migration attempt on the owning email, never a blind update
        # of the email that has no account.
        self.assertEqual(
            [call.kwargs['email'] for call in update_mock.call_args_list],
            ['old@example.com'],
        )
        self.assertIn('ya está registrado', str(ctx.exception))

    @mock.patch('ramps.koywe_client.cache.set')
    def test_existing_complete_profile_is_read_without_duplicate_post(self, cache_set):
        client = KoyweClient()
        existing = {
            **self.PAYLOAD,
            'address': {
                'addressStreet': 'Rua Um 123',
                'addressCountry': 'BRA',
                'addressZipCode': '01001000',
                'addressCity': 'Sao Paulo',
                'addressState': 'SP',
            },
        }
        payload = {
            **self.PAYLOAD,
            'address': dict(existing['address']),
        }

        with mock.patch.object(
            client, '_build_account_profile_payload', return_value=payload,
        ), mock.patch.object(
            client, 'get_account', return_value=existing,
        ) as get_account, mock.patch.object(
            client, 'update_account',
        ) as update_account, mock.patch.object(client, '_request') as request:
            resolved = client.ensure_account_profile(
                email='owner@example.com',
                country_code='CO',
                contact_profile={
                    'email': 'owner@example.com',
                    'documentNumber': '1234567890',
                    'firstName': 'Test',
                },
            )

        self.assertIsNone(resolved)
        get_account.assert_called_once_with(email='owner@example.com')
        update_account.assert_not_called()
        request.assert_not_called()
        cache_set.assert_called_once()

    def test_profile_lookup_auth_error_does_not_fall_through_to_create(self):
        client = KoyweClient()
        with mock.patch.object(
            client, '_build_account_profile_payload', return_value=self.PAYLOAD,
        ), mock.patch.object(
            client, 'get_account', side_effect=KoyweError('Check your credentials'),
        ), mock.patch.object(client, '_request') as request:
            with self.assertRaisesRegex(KoyweError, 'Check your credentials'):
                client.ensure_account_profile(
                    email='owner@example.com',
                    country_code='CO',
                    contact_profile={
                        'email': 'owner@example.com',
                        'documentNumber': '1234567890',
                        'firstName': 'Test',
                    },
                )

        request.assert_not_called()


class KoyweEmailSelectionTests(SimpleTestCase):
    def test_previous_emails_do_not_include_duende_test_accounts(self):
        emails = ramps_schema._get_koywe_previous_emails(
            country_code='AR',
            document_number='',
        )

        self.assertNotIn('duende-argentina@koywe-test.com', emails)

    def test_test_user_auth_email_still_uses_duende_override(self):
        user = type('User', (), {
            'username': 'julianm',
            'email': 'julian@example.com',
        })()

        email = ramps_schema._get_koywe_auth_email(user=user, country_code='MX')

        self.assertEqual(email, 'duende-mexico@koywe-test.com')

    def test_colombia_uses_real_stored_email_for_test_user(self):
        user = type('User', (), {
            'username': 'julianm',
            'email': 'julian@example.com',
            'ramp_user_address': SimpleNamespace(auth_email='pse@example.com'),
        })()

        email = ramps_schema._get_koywe_auth_email(user=user, country_code='CO')

        self.assertEqual(email, 'pse@example.com')

    def test_colombia_ignores_stale_duende_delivery_email(self):
        user = type('User', (), {
            'username': 'julianm',
            'email': 'julian@example.com',
            'ramp_user_address': SimpleNamespace(
                auth_email='duende-peru@koywe-test.com',
            ),
        })()

        email = ramps_schema._get_koywe_auth_email(user=user, country_code='CO')

        self.assertEqual(email, 'julian@example.com')

    def test_colombia_profile_migration_includes_duende_account(self):
        user = type('User', (), {
            'username': 'julianm',
        })()

        with mock.patch.object(
            ramps_schema,
            '_get_koywe_previous_emails',
            return_value=['old@example.com'],
        ), mock.patch.object(
            ramps_schema,
            '_get_koywe_test_sibling_emails',
            return_value=[],
        ):
            emails = ramps_schema._get_koywe_profile_previous_emails(
                user=user,
                country_code='CO',
                document_number='1234567890',
                selected_email='pse@example.com',
            )

        self.assertEqual(
            emails,
            ['duende-colombia@koywe-test.com', 'old@example.com'],
        )

    def test_profile_migration_includes_prior_inbox_and_sibling_test_account(self):
        """The shared test identity can only live under one inbox at a time."""
        user = type('User', (), {
            'username': 'julianmoonluna',
        })()

        with mock.patch.object(
            ramps_schema,
            '_get_koywe_previous_emails',
            return_value=['pse@example.com', 'old@example.com'],
        ), mock.patch.object(
            ramps_schema,
            '_get_koywe_test_sibling_emails',
            return_value=['sibling@example.com'],
        ):
            emails = ramps_schema._get_koywe_profile_previous_emails(
                user=user,
                country_code='CO',
                document_number='1234567890',
                selected_email='pse@example.com',
                prior_auth_email='previous@example.com',
            )

        # The email being registered is never its own previous owner.
        self.assertEqual(
            emails,
            [
                'previous@example.com',
                'duende-colombia@koywe-test.com',
                'sibling@example.com',
                'old@example.com',
            ],
        )

    def test_profile_migration_skips_siblings_without_override(self):
        user = type('User', (), {
            'username': 'someoneelse',
        })()

        with mock.patch.object(
            ramps_schema,
            '_get_koywe_previous_emails',
            return_value=['old@example.com'],
        ), mock.patch.object(
            ramps_schema,
            '_get_koywe_test_sibling_emails',
            side_effect=AssertionError('siblings are test-only'),
        ):
            emails = ramps_schema._get_koywe_profile_previous_emails(
                user=user,
                country_code='CO',
                document_number='1234567890',
                selected_email='pse@example.com',
                prior_auth_email='duende-colombia@koywe-test.com',
            )

        # A stale duende inbox is not a real previous owner.
        self.assertEqual(emails, ['old@example.com'])

    @mock.patch.object(ramps_schema, '_get_latest_personal_verification')
    @mock.patch.object(ramps_schema, '_build_effective_ramp_address_snapshot')
    def test_colombia_real_email_keeps_test_identity(
        self,
        effective_address_mock,
        verification_mock,
    ):
        verification_mock.return_value = SimpleNamespace(
            verified_first_name='Real',
            verified_last_name='Person',
            document_number='ARG-DOCUMENT',
            document_type='national_id',
            verified_date_of_birth=None,
        )
        effective_address_mock.return_value = SimpleNamespace(
            address_street='Calle 1',
            address_city='Lima',
            address_neighborhood='',
            address_state='Lima',
            address_zip_code='15001',
            address_country='PER',
            economic_activity='EMPLOYEE',
        )
        user = type('User', (), {
            'username': 'julianm',
            'email': 'julian@example.com',
            'phone_country_code': '+51',
            'phone_number': '999999999',
        })()

        profile = ramps_schema._get_koywe_contact_profile(
            user=user,
            country_code='CO',
            email_override='pse@example.com',
        )

        self.assertEqual(profile['email'], 'pse@example.com')
        self.assertEqual(profile['documentType'], 'CED_CIU')
        self.assertEqual(profile['documentNumber'], '1234567890')
        self.assertEqual(profile['addressCountry'], 'COL')


class KoyweAccountProfileTests(SimpleTestCase):
    def test_chile_rut_format_difference_satisfies_existing_profile(self):
        client = KoyweClient()
        existing = {
            'document': {
                'documentNumber': '123456785',
                'documentType': 'RUT',
                'country': 'CHL',
            },
            'personalInfo': {
                'names': 'Juan',
                'firstLastname': 'Perez',
                'phoneNumber': '56912345678',
                'dob': '1980-01-01',
            },
            'address': {
                'addressStreet': 'Apoquindo 123',
                'addressCountry': 'CHL',
                'addressZipCode': '7550000',
                'addressCity': 'Santiago',
                'addressState': 'RM',
            },
        }
        payload = {
            'document': {
                'documentNumber': '12345678-5',
                'documentType': 'RUT',
                'country': 'CHL',
            },
            'personalInfo': {
                'names': 'Juan',
                'firstLastname': 'Perez',
                'phoneNumber': '56912345678',
                'dob': '1980-01-01',
            },
            'address': {
                'addressStreet': 'Apoquindo 123',
                'addressCountry': 'CHL',
                'addressZipCode': '7550000',
                'addressCity': 'Santiago',
                'addressState': 'RM',
            },
        }

        self.assertTrue(client._account_profile_satisfies_payload(existing, payload))

    def test_chile_rut_format_difference_does_not_request_document_update(self):
        client = KoyweClient()
        payload = client._build_migration_payload(
            existing={
                'document': {
                    'documentNumber': '123456785',
                    'documentType': 'RUT',
                    'country': 'CHL',
                },
            },
            target_payload={
                'document': {
                    'documentNumber': '12345678-5',
                    'documentType': 'RUT',
                    'country': 'CHL',
                },
            },
            country_code='CL',
            current_email='user@example.com',
            new_email=None,
        )

        self.assertNotIn('updateDocumentNumber', payload)
        self.assertEqual(payload['document']['documentNumber'], '123456785')


class KoyweQuoteLimitPreflightTests(SimpleTestCase):
    def test_on_ramp_preflight_rejects_below_cached_minimum(self):
        client = type('Client', (), {
            'get_public_ramp_limits': lambda self, *, fiat_symbol: {
                'on_ramp_min_amount': Decimal('24000'),
                'on_ramp_max_amount': Decimal('8500000'),
            },
        })()

        with self.assertRaises(ramps_schema.KoyweMinimumAmountError) as ctx:
            ramps_schema._validate_koywe_on_ramp_quote_limits(
                client=client,
                amount=Decimal('25'),
                fiat_symbol='ARS',
            )

        self.assertEqual(ctx.exception.minimum, '24000')
        self.assertEqual(ctx.exception.actual, '25')

    def test_on_ramp_preflight_allows_amount_inside_limits(self):
        client = type('Client', (), {
            'get_public_ramp_limits': lambda self, *, fiat_symbol: {
                'on_ramp_min_amount': Decimal('24000'),
                'on_ramp_max_amount': Decimal('8500000'),
            },
        })()

        ramps_schema._validate_koywe_on_ramp_quote_limits(
            client=client,
            amount=Decimal('25000'),
            fiat_symbol='ARS',
        )
