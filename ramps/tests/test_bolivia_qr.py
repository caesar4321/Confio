from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from ramps import bolivia_qr, bolivia_qr_receive, bolivia_qr_send, ve_send
from ramps.bolivia_qr import BoliviaQrError
from ramps.models import RampTransaction
from users.models import Account, User

ADDRESS = '0x' + 'ab' * 20
RELAY_DEPOSIT = '0x' + 'cd' * 20
PROVIDER_DEPOSIT = '0x' + 'ef' * 20
_ops_alert = mock.patch('config.ops_alerts.send_ops_alert', return_value=True)


def setUpModule():
    _ops_alert.start()


def tearDownModule():
    _ops_alert.stop()


def fake_receive_adapter(**overrides):
    adapter = SimpleNamespace(
        PROVIDER='mesadepagos', ROUTE_AT_CREATION=True,
        quote_receive=lambda bob: {'usdc_units': 14_000_000, 'usd_estimate': '14.0', 'rate': '7.0', 'fee_bob': '0'},
        create_receive=mock.Mock(return_value={'qr_image': 'iVBOR', 'qr_text': '', 'provider_id': 'tx-1',
                                               'expires_at': (timezone.now() + timedelta(minutes=15)).isoformat()}),
        receive_status=mock.Mock(return_value='unpaid'))
    for key, value in overrides.items():
        setattr(adapter, key, value)
    return adapter


ROUTE = {'deposit_address': RELAY_DEPOSIT, 'request_id': 'req-1', 'response': {}, 'deadline': 2_000_000_000,
         'amount_in': '14000000', 'amount_out': '13950000000000000000', 'amount_out_min': '13900000000000000000'}


class GateTests(SimpleTestCase):
    @override_settings(BOLIVIA_QR_RECEIVE_ENABLED=True, BOLIVIA_QR_RECEIVE_MIN_APP_VERSION='5.2.9',
                       BOLIVIA_QR_SEND_ENABLED=False, BOLIVIA_QR_SEND_MIN_APP_VERSION='5.2.9')
    def test_switch_floor_and_koywe_rows(self):
        new, old = {'HTTP_X_CONFIO_VERSION': '5.2.9'}, {'HTTP_X_CONFIO_VERSION': '5.2.8'}
        self.assertTrue(bolivia_qr.offered(bolivia_qr.RECEIVE, new))
        self.assertFalse(bolivia_qr.offered(bolivia_qr.RECEIVE, old))
        self.assertFalse(bolivia_qr.offered(bolivia_qr.SEND, new))  # its own switch is off
        bolivian = SimpleNamespace(is_authenticated=True, phone_country='BO')
        peruvian = SimpleNamespace(is_authenticated=True, phone_country='PE')
        self.assertEqual(bolivia_qr.koywe_replaced(bolivian, new), {'top_up': True, 'withdraw': False})
        self.assertEqual(bolivia_qr.koywe_replaced(bolivian, old), {'top_up': False, 'withdraw': False})
        self.assertEqual(bolivia_qr.koywe_replaced(peruvian, new), {'top_up': False, 'withdraw': False})

    @override_settings(BOLIVIA_QR_SEND_ENABLED=False, BOLIVIA_QR_SEND_MIN_APP_VERSION='5.2.9',
                       BOLIVIA_QR_TEST_USER_IDS='7, 9')
    def test_listed_testers_get_it_before_the_switch(self):
        meta = {'HTTP_X_CONFIO_VERSION': '5.2.9'}
        self.assertTrue(bolivia_qr.offered(bolivia_qr.SEND, meta, SimpleNamespace(pk=9)))
        self.assertFalse(bolivia_qr.offered(bolivia_qr.SEND, meta, SimpleNamespace(pk=8)))
        self.assertFalse(bolivia_qr.offered(bolivia_qr.SEND, {'HTTP_X_CONFIO_VERSION': '5.2.8'}, SimpleNamespace(pk=9)))

    @override_settings(BOLIVIA_QR_RECEIVE_MIN_APP_VERSION='')
    def test_unset_floor_shows_nobody(self):
        self.assertFalse(bolivia_qr.client_supports(bolivia_qr.RECEIVE, {'HTTP_X_CONFIO_VERSION': '9.9.9'}))

    def test_provider_names_never_reach_users(self):
        from ramps.ve_pagomovil import public_provider_name
        for provider in ('stereum', 'mesadepagos'):
            ramp = RampTransaction(provider=provider, country_code='BO', direction='on_ramp')
            self.assertEqual(public_provider_name(ramp), 'QR Bolivia')


@override_settings(BOLIVIA_QR_RECEIVE_PROVIDER='mesadepagos')
class ReceiveTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='bo-receive', firebase_uid='bo-receive', phone_country='BO')
        self.account = Account.objects.create(user=self.user, account_type='personal', bsc_address=ADDRESS)
        self.adapter = fake_receive_adapter()
        patches = [
            mock.patch('ramps.bolivia_qr_receive.adapter', return_value=self.adapter),
            mock.patch('ramps.bolivia_qr_receive._route', return_value=dict(ROUTE)),
            mock.patch('ramps.bolivia_qr_receive._polygon_block', return_value=1000),
            mock.patch('security.face_step_up.claim_on_ramp_check', return_value=(True, 7)),
            mock.patch('security.face_step_up.release_on_ramp_check'),
        ]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)

    def create(self):
        return bolivia_qr_receive.create(self.user, self.account, Decimal('100'))

    def test_qr_pays_the_relay_address_for_the_quoted_amount(self):
        ramp = self.create()
        kwargs = self.adapter.create_receive.call_args.kwargs
        self.assertEqual((kwargs['deposit_address'], kwargs['usdc_units']), (RELAY_DEPOSIT, 14_000_000))
        self.assertEqual((ramp.status, bolivia_qr_receive._phase(ramp)), ('PENDING', 'qr_ready'))
        self.assertEqual(bolivia_qr_receive.view(ramp)['qr_image'], 'iVBOR')
        with self.assertRaisesRegex(BoliviaQrError, 'QR activo'):
            self.create()

    def test_face_check_is_given_back_when_no_qr_exists(self):
        self.adapter.create_receive.side_effect = BoliviaQrError('no')
        with self.assertRaises(BoliviaQrError):
            self.create()
        self.mocks[4].assert_called_once_with(7)
        self.assertFalse(bolivia_qr_receive.active_order(self.user))

    def test_without_face_nothing_is_asked_of_the_provider(self):
        self.mocks[3].return_value = (False, None)
        with self.assertRaises(BoliviaQrError) as caught:
            self.create()
        self.assertEqual(caught.exception.next_step, 'face_check')
        self.adapter.create_receive.assert_not_called()

    def test_paid_qr_is_credited_from_the_relay_proof(self):
        ramp = self.create()
        self.adapter.receive_status.return_value = 'paid'
        log = {'transactionHash': '0x' + '11' * 32, 'data': hex(14_000_000), 'removed': False}

        def rpc(chain, method, params):
            if method == 'eth_getBlockByNumber':
                return {'number': hex(1500)}
            if method == 'eth_getLogs':
                return [log]
            raise AssertionError(method)

        def delivered(view):
            view.status, view.actual_out_units, view.destination_tx_hash = 'delivered', str(13_950_000 * 10 ** 12), \
                '0x' + '22' * 32

        with mock.patch('payment_accounts.bridge_chain.rpc', side_effect=rpc), \
                mock.patch('payment_accounts.relay_settlement.reconcile_relay', side_effect=delivered), \
                mock.patch('payment_accounts.relay.RelayClient.status', return_value={'status': 'pending'}), \
                mock.patch('ramps.bsc_provider_hash.attach_after_provider_sync') as attach:
            ramp = bolivia_qr_receive.sync(ramp)
        self.assertEqual((ramp.status, bolivia_qr_receive._phase(ramp)), ('COMPLETED', 'completed'))
        self.assertEqual(ramp.crypto_amount_actual, Decimal('13.95'))
        self.assertEqual(bolivia_qr_receive._section(ramp)['bsc_provider_transfer_tx_hash'], '0x' + '22' * 32)
        attach.assert_called_once()

    def test_a_deposit_of_another_amount_goes_to_review_never_credited(self):
        ramp = self.create()
        self.adapter.receive_status.return_value = 'paid'
        log = {'transactionHash': '0x' + '11' * 32, 'data': hex(13_000_000), 'removed': False}
        with mock.patch('payment_accounts.bridge_chain.rpc', side_effect=lambda c, m, p: (
                {'number': hex(1500)} if m == 'eth_getBlockByNumber' else [log])):
            ramp = bolivia_qr_receive.sync(ramp)
        self.assertEqual((ramp.status, bolivia_qr_receive._phase(ramp)), ('PROCESSING', 'review'))

    def test_a_missing_or_processing_record_never_expires_a_qr(self):
        ramp = self.create()
        past = (timezone.now() - timedelta(hours=2)).isoformat()
        section = dict(ramp.metadata[bolivia_qr_receive.SECTION], expires_at=past)
        RampTransaction.objects.filter(pk=ramp.pk).update(metadata={bolivia_qr_receive.SECTION: section})
        for state in ('unknown', 'processing'):
            self.adapter.receive_status.return_value = state
            ramp = bolivia_qr_receive.sync(ramp)
            self.assertEqual(ramp.status, 'PENDING')
        self.adapter.receive_status.return_value = 'unpaid'
        ramp = bolivia_qr_receive.sync(ramp)
        self.assertEqual((ramp.status, bolivia_qr_receive._phase(ramp)), ('FAILED', 'expired'))

    def test_unpaid_qr_expires_and_cancel_only_hides_it(self):
        ramp = self.create()
        ramp = bolivia_qr_receive.cancel(ramp)
        self.assertEqual(ramp.status, 'PENDING')  # still payable until it expires
        self.adapter.receive_status.return_value = 'expired'
        ramp = bolivia_qr_receive.sync(ramp)
        self.assertEqual((ramp.status, bolivia_qr_receive._phase(ramp)), ('FAILED', 'expired'))

    @override_settings(BOLIVIA_QR_RECEIVE_MAX_USD='10')
    def test_optional_cap(self):
        with self.assertRaisesRegex(BoliviaQrError, 'máximo'):
            self.create()


class SendSizingTests(SimpleTestCase):
    def test_debit_covers_the_bridge_minimum_with_cushion(self):
        quotes = iter([(9_990_000, 9_800_000), (10_100_000, 10_060_000)])
        with mock.patch('ramps.bolivia_qr_send._relay_min_out', side_effect=lambda w, r: next(quotes)), \
                mock.patch('ramps.ve_send.confio_amounts', side_effect=lambda g: (None, int(g * 10 ** 18))):
            sizing = bolivia_qr_send.size_funding(10_000_000, ADDRESS)
        self.assertGreaterEqual(sizing['bridge_minimum_units'], 10_040_000)
        self.assertGreaterEqual(sizing['usdt_wei'], 10 * 10 ** 18)

    def test_too_small_to_cross(self):
        with mock.patch('ramps.bolivia_qr_send._relay_min_out', return_value=(10, 1)):
            with self.assertRaisesRegex(BoliviaQrError, 'muy pequeño'):
                bolivia_qr_send.size_funding(10_000, ADDRESS)


class SendFundingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='bo-send', firebase_uid='bo-send')
        self.ramp = RampTransaction.objects.create(
            provider='mesadepagos', direction='off_ramp', status='PENDING', country_code='BO', actor_user=self.user,
            actor_address=ADDRESS, destination='cusd_plus', metadata={ve_send.SECTION: {
                'phase': 'awaiting_funding', 'deposit_wei': str(15 * 10 ** 18),
                'provider_payment': {'deposit_address': PROVIDER_DEPOSIT, 'usdc_units': 14_440_000,
                                     'expires_at': 2_000_000_000},
                'beneficiary': {'holder_name': 'Tienda', 'bob': '100.00'}}})

    def build(self, out_min):
        return {'amountOut': str(out_min + 200_000), 'amountOutMin': str(out_min),
                'relay': {'request_id': 'r', 'response': {}, 'deadline': 2_000_000_000}}

    def target(self, accepts, out_min):
        impl = SimpleNamespace(PAYMENT_AT_CREATION=True, environment=lambda: 'prod|abc')
        section = dict(self.ramp.metadata[ve_send.SECTION])
        section['provider_payment'] = dict(section['provider_payment'], environment='prod|abc',
                                           **({} if 'expires_at' not in section['provider_payment'] else {}))
        RampTransaction.objects.filter(pk=self.ramp.pk).update(metadata={ve_send.SECTION: section})
        self.ramp.refresh_from_db()
        with mock.patch('ramps.bolivia_qr_send.adapter', return_value=impl), \
                mock.patch('payment_accounts.relay.RelayClient.routes', return_value=[{}]), \
                mock.patch('payment_accounts.relay.RelayClient.build', return_value=self.build(out_min)), \
                mock.patch('payment_accounts.bridge_binding.deposit_call', return_value=(RELAY_DEPOSIT, {})):
            return bolivia_qr_send.relay_target(self.ramp, accepts)

    def test_real_dollars_never_fund_a_sandbox_provider(self):
        with self.assertRaisesRegex(BoliviaQrError, 'modo de prueba'):
            self.target(False, 14_500_000)

    def test_an_expired_provider_payment_is_never_funded(self):
        import time
        section = dict(self.ramp.metadata[ve_send.SECTION])
        section['provider_payment'] = dict(section['provider_payment'], expires_at=int(time.time()) + 60)
        RampTransaction.objects.filter(pk=self.ramp.pk).update(metadata={ve_send.SECTION: section})
        self.ramp.refresh_from_db()
        with self.assertRaisesRegex(BoliviaQrError, 'venció'):
            self.target(True, 14_500_000)
        self.ramp.refresh_from_db()
        self.assertEqual(self.ramp.status, 'FAILED')

    def test_surplus_stays_at_the_provider_and_is_recorded(self):
        section = dict(self.ramp.metadata[ve_send.SECTION])
        section.update(funding_tx_hash='0x' + '33' * 32, deposit_address=RELAY_DEPOSIT, bridge={
            'request_id': 'r', 'response': {}, 'deadline': 2_000_000_000, 'recipient': PROVIDER_DEPOSIT,
            'amount_out_min': '14500000', 'needed_units': '14440000'})
        RampTransaction.objects.filter(pk=self.ramp.pk).update(metadata={ve_send.SECTION: section})
        self.ramp.refresh_from_db()

        def delivered(view):
            view.status, view.actual_out_units, view.destination_tx_hash = 'delivered', '14600000', '0x' + '44' * 32

        with mock.patch('payment_accounts.relay_settlement.reconcile_relay', side_effect=delivered):
            result = bolivia_qr_send.settle(self.ramp)
        self.assertEqual(result.kind, 'delivered')
        self.ramp.refresh_from_db()
        self.assertEqual(ve_send._section(self.ramp)['provider_surplus_units'], '160000')

    def test_refused_when_the_minimum_no_longer_covers_the_payment(self):
        with self.assertRaisesRegex(BoliviaQrError, 'precio cambió'):
            self.target(True, 14_000_000)

    def test_a_payment_from_another_environment_never_receives_real_dollars(self):
        section = dict(self.ramp.metadata[ve_send.SECTION])
        section['provider_payment'] = dict(section['provider_payment'], environment='sandbox|old')
        RampTransaction.objects.filter(pk=self.ramp.pk).update(metadata={ve_send.SECTION: section})
        self.ramp.refresh_from_db()
        impl = SimpleNamespace(PAYMENT_AT_CREATION=True, environment=lambda: 'prod|abc')
        with mock.patch('ramps.bolivia_qr_send.adapter', return_value=impl):
            with self.assertRaises(BoliviaQrError):
                bolivia_qr_send.relay_target(self.ramp, True)
        self.ramp.refresh_from_db()
        self.assertEqual(self.ramp.status, 'FAILED')

    def test_target_bridges_to_the_provider_address(self):
        target = self.target(True, 14_500_000)
        self.assertEqual((target['deposit_address'], target['binding']['recipient']), (RELAY_DEPOSIT, PROVIDER_DEPOSIT))
        self.assertEqual(target['binding']['needed_units'], '14440000')

    def test_inflight_payouts_are_counted_per_provider(self):
        other = RampTransaction.objects.create(
            provider='pagoasap', direction='off_ramp', status='PROCESSING', country_code='VE', actor_user=self.user,
            metadata={ve_send.SECTION: {'phase': 'paying'}})
        same = RampTransaction.objects.create(
            provider='mesadepagos', direction='off_ramp', status='PROCESSING', country_code='BO',
            actor_user=self.user, metadata={ve_send.SECTION: {'phase': 'paying'}})
        self.assertEqual([r.pk for r in ve_send._inflight(self.ramp)], [same.pk])
        self.assertNotIn(other.pk, [r.pk for r in ve_send._inflight(self.ramp)])


class SendCreateTests(TestCase):
    def test_never_charges_more_than_the_approved_debit(self):
        terms = {'preview': {'holder_name': 'X'}, 'bob_amount': '100.00', 'usd_amount': '14.60', 'usdt_amount': '14.5',
                 'confio_fee_usd': '0.1', 'rate': '7', 'usdc_units': '14440000'}
        with mock.patch('ramps.bolivia_qr_send.quote', return_value=terms), \
                mock.patch('ramps.bolivia_qr_send.adapter', return_value=SimpleNamespace()), \
                mock.patch('ramps.ve_send.reserve') as reserve:
            for approved in ('14.59', None):
                with self.assertRaisesRegex(BoliviaQrError, 'precio cambió'):
                    bolivia_qr_send.create(None, None, 'qr', None, max_usd=approved)
        reserve.assert_not_called()


class MesaDePagosTests(SimpleTestCase):
    def test_qr_text_renders_to_a_decodable_png(self):
        import base64
        from ramps.mesadepagos_client import qr_png_base64
        raw = base64.b64decode(qr_png_base64('0002010102120000'))
        self.assertTrue(raw.startswith(b'\x89PNG'))

    def test_decode_maps_provider_fields(self):
        from ramps import bolivia_qr_mesadepagos as mdp
        client = mock.Mock()
        client.validate_qr.return_value = {'code': 200, 'details': {
            'titularDestino': 'Tienda Sol', 'cuentaDestino': '1234567890', 'nombreBancoDestino': 'BNB',
            'codigoBancoDestino': '1014', 'moneda': 'BOB', 'monto': '35.50', 'ciNitDestino': '123'}}
        with mock.patch.object(mdp, '_client', return_value=client):
            preview = mdp.decode('qr')
        self.assertEqual((preview['holder_name'], preview['account_last4'], preview['amount'], preview['fixed_amount']),
                         ('Tienda Sol', '7890', '35.50', True))

    def test_payout_outcomes(self):
        from ramps import bolivia_qr_mesadepagos as mdp
        ramp = RampTransaction(external_id='abc', metadata={})
        for status, kind in (('completed_transaction', 'paid'), ('reject_transaction', 'failed'),
                             ('processing_transaction', 'pending')):
            client = mock.Mock()
            client.find.return_value = {'status': status, 'transactionId': 't1', 'amountFiat': '100'}
            with mock.patch.object(mdp, '_client', return_value=client):
                self.assertEqual(mdp.poll(ramp).kind, kind)


class StereumTests(SimpleTestCase):
    def test_transfer_outcomes(self):
        from ramps import bolivia_qr_stereum as st
        self.assertEqual(st._transfer_outcome({'status': 'VERIFICADO', 'id': 'x'}).kind, 'paid')
        self.assertEqual(st._transfer_outcome({'status': 'PENDIENTE', 'id': 'x'}).kind, 'pending')
        self.assertEqual(st._transfer_outcome({'status': 'ERROR', 'id': 'x'}).kind, 'failed')
        self.assertEqual(st._transfer_outcome({}).kind, 'unknown')

    @override_settings(STEREUM_ENV='production', STEREUM_API_KEY='k')
    def test_production_refuses_test_network_resources(self):
        from ramps.stereum_client import StereumError, StereumLiveClient
        client = StereumLiveClient()
        with self.assertRaises(StereumError):
            client.check({'on_main_net': 'false'})
        self.assertEqual(client.check({'on_main_net': True}), {'on_main_net': True})

    @override_settings(STEREUM_ENV='production')
    def test_the_test_console_never_reaches_production(self):
        from ramps.stereum_client import StereumClient, StereumError
        with self.assertRaises(StereumError):
            StereumClient()
