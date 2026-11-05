from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from ramps import koywe_polygon
from ramps.koywe_sync import sync_koywe_ramp_transaction_from_order
from ramps.models import RampTransaction
from users.models import User

ADDRESS = '0x' + 'ab' * 20
RELAY_DEPOSIT = '0x' + 'cd' * 20
KOYWE_POLYGON = '0x' + 'ef' * 20
DELIVERY_HASH = '0x' + '12' * 32
_ops_alert = mock.patch('config.ops_alerts.send_ops_alert', return_value=True)


def setUpModule():
    _ops_alert.start()


def tearDownModule():
    _ops_alert.stop()


ON_ROUTE = {'source': 'POL:USDC', 'destination': 'BSC:USDT', 'deposit_address': RELAY_DEPOSIT,
            'request_id': 'req-1', 'response': {}, 'deadline': 2_000_000_000, 'sender': ADDRESS,
            'recipient': ADDRESS, 'amount_in': '27800000', 'amount_out': '27750000000000000000',
            'amount_out_min': '27700000000000000000', 'polygon_from_block': 100}


class SwitchTests(SimpleTestCase):
    def test_bsc_is_the_default(self):
        self.assertFalse(koywe_polygon.enabled())
        self.assertEqual(koywe_polygon.crypto_symbol(), 'USDT BSC')

    @override_settings(KOYWE_SAVINGS_NETWORK='POLYGON')
    def test_polygon_switch(self):
        self.assertTrue(koywe_polygon.enabled())
        self.assertEqual(koywe_polygon.crypto_symbol(), 'USDC Polygon')


class QuoteTests(SimpleTestCase):
    def test_on_ramp_shows_the_dollars_that_reach_bsc(self):
        quote = {'amount_out': Decimal('27.8'), 'network_fee_amount': Decimal('0.13'),
                 'exchange_rate': Decimal('3.6'), 'token_symbol': 'USDC Polygon'}
        with mock.patch.object(koywe_polygon, 'bridge_ratio', return_value=Decimal('0.998')):
            adjusted = koywe_polygon.adjust_quote(quote, 'ON_RAMP')
        self.assertEqual(adjusted['amount_out'], Decimal('27.744400'))
        # 0.0556 USD of bridge cost at 3.6 PEN per dollar joins the network fee.
        self.assertEqual(adjusted['network_fee_amount'], Decimal('0.33'))
        self.assertEqual(adjusted['token_symbol'], 'USDT BSC')

    def test_off_ramp_pays_fiat_for_what_the_bridge_delivers(self):
        quote = {'amount_in': Decimal('30'), 'amount_out': Decimal('682.93'),
                 'network_fee_amount': Decimal('0'), 'exchange_rate': Decimal('6.9')}
        with mock.patch.object(koywe_polygon, 'bridge_ratio', return_value=Decimal('0.998')):
            adjusted = koywe_polygon.adjust_quote(quote, 'OFF_RAMP')
        self.assertEqual(adjusted['amount_out'], Decimal('681.56'))
        self.assertEqual(adjusted['network_fee_amount'], Decimal('0.060000'))


class OffRampVouchTests(SimpleTestCase):
    def ramp(self, deadline=4_000_000_000):
        route = {'deposit_address': RELAY_DEPOSIT, 'recipient': KOYWE_POLYGON, 'deadline': deadline}
        return SimpleNamespace(pk=1, metadata={koywe_polygon.SECTION: {
            'route': route, 'deposit_address': RELAY_DEPOSIT}})

    def test_an_expired_route_withholds_funding(self):
        details = koywe_polygon.vouch_off_ramp_deposit(
            {'confioDepositAddress': KOYWE_POLYGON}, self.ramp(deadline=1), 'confioDepositAddress')
        self.assertNotIn('confioDepositAddress', details)

    def test_a_polygon_order_without_a_route_is_never_funded_on_bsc(self):
        ramp = SimpleNamespace(pk=1, metadata={koywe_polygon.SECTION: {'phase': 'created'}})
        details = koywe_polygon.vouch_off_ramp_deposit(
            {'confioDepositAddress': KOYWE_POLYGON}, ramp, 'confioDepositAddress')
        self.assertNotIn('confioDepositAddress', details)


    def test_funds_the_relay_address_for_this_order(self):
        details = koywe_polygon.vouch_off_ramp_deposit(
            {'confioDepositAddress': KOYWE_POLYGON.upper().replace('0X', '0x')}, self.ramp(), 'confioDepositAddress')
        self.assertEqual(details['confioDepositAddress'], RELAY_DEPOSIT)

    def test_a_different_koywe_address_withholds_funding(self):
        details = koywe_polygon.vouch_off_ramp_deposit(
            {'confioDepositAddress': '0x' + '99' * 20}, self.ramp(), 'confioDepositAddress')
        self.assertNotIn('confioDepositAddress', details)


class OnRampSettlementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='koywe-polygon', firebase_uid='koywe-polygon')
        self.ramp = RampTransaction.objects.create(
            provider='koywe', direction='on_ramp', status='PENDING', country_code='PE', actor_user=self.user,
            actor_address=ADDRESS, destination='cusd_plus', provider_order_id='order-1',
            metadata={koywe_polygon.SECTION: {'route': ON_ROUTE, 'deposit_address': RELAY_DEPOSIT,
                                              'phase': 'created'}})

    def delivered(self):
        return {'orderId': 'order-1', 'status': 'DELIVERED', 'amountIn': '100', 'amountOut': '27.8',
                'txHash': '0x' + '34' * 32}

    def test_koywe_delivered_waits_for_the_bridge(self):
        sync_koywe_ramp_transaction_from_order(ramp_tx=self.ramp, order_payload=self.delivered())
        self.ramp.refresh_from_db()
        self.assertEqual(self.ramp.status, 'PROCESSING')
        self.assertTrue(self.ramp.status_detail.startswith('bridging'))
        self.assertIsNone(self.ramp.crypto_amount_actual)
        # Shown amounts are Relay's expected USDT, not Koywe's USDC.
        self.assertEqual(self.ramp.crypto_amount_estimated, Decimal('27.75'))
        self.assertEqual(self.ramp.final_amount, Decimal('27.75'))
        self.assertEqual(koywe_polygon.section(self.ramp)['phase'], 'provider_delivered')
        self.assertTrue(koywe_polygon.needs_settlement(self.ramp))

    def test_bridge_delivery_completes_with_the_usdt_that_arrived(self):
        sync_koywe_ramp_transaction_from_order(ramp_tx=self.ramp, order_payload=self.delivered())
        logs = [{'transactionHash': '0x' + '56' * 32, 'data': hex(27_800_000), 'removed': False}]

        def rpc(chain, method, params):
            if method == 'eth_getBlockByNumber':
                return {'number': hex(150)}
            return logs

        def reconcile(view):
            view.status, view.actual_out_units, view.destination_tx_hash = (
                'delivered', str(27_751_000 * 10 ** 12), DELIVERY_HASH)

        with mock.patch('payment_accounts.bridge_chain.rpc', side_effect=rpc), \
             mock.patch('payment_accounts.relay.RelayClient.status', return_value={}), \
             mock.patch('payment_accounts.relay_settlement.reconcile_relay', side_effect=reconcile), \
             mock.patch('ramps.bsc_provider_hash.attach_after_provider_sync'):
            self.ramp.refresh_from_db()
            koywe_polygon.settle(self.ramp)
        self.ramp.refresh_from_db()
        self.assertEqual(self.ramp.status, 'COMPLETED')
        self.assertEqual(self.ramp.crypto_amount_actual, Decimal('27.751'))
        self.assertEqual(self.ramp.metadata['bsc_provider_transfer_tx_hash'], DELIVERY_HASH)

        # A later Koywe webhook keeps the bridge's figures.
        sync_koywe_ramp_transaction_from_order(ramp_tx=self.ramp, order_payload=self.delivered())
        self.ramp.refresh_from_db()
        self.assertEqual(self.ramp.status, 'COMPLETED')
        self.assertEqual(self.ramp.crypto_amount_actual, Decimal('27.751'))

    def test_a_completed_order_never_goes_back_to_review(self):
        koywe_polygon.mark(self.ramp, phase='completed')
        RampTransaction.objects.filter(pk=self.ramp.pk).update(status='COMPLETED')
        koywe_polygon._review(self.ramp, 'late_worker')
        self.ramp.refresh_from_db()
        self.assertEqual(self.ramp.status, 'COMPLETED')
        self.assertEqual(koywe_polygon.section(self.ramp)['phase'], 'completed')

    def test_wrong_deposit_amount_goes_to_review(self):
        sync_koywe_ramp_transaction_from_order(ramp_tx=self.ramp, order_payload=self.delivered())
        logs = [{'transactionHash': '0x' + '56' * 32, 'data': hex(27_000_000), 'removed': False}]

        def rpc(chain, method, params):
            return {'number': hex(150)} if method == 'eth_getBlockByNumber' else logs

        with mock.patch('payment_accounts.bridge_chain.rpc', side_effect=rpc):
            self.ramp.refresh_from_db()
            koywe_polygon.settle(self.ramp)
        self.ramp.refresh_from_db()
        self.assertEqual(self.ramp.status, 'PROCESSING')
        self.assertEqual(koywe_polygon.section(self.ramp)['phase'], 'review')


class ProviderHashTests(SimpleTestCase):
    def test_only_the_relay_bsc_hash_counts_for_polygon_orders(self):
        from ramps.signals import find_provider_tx_hash
        polygon_hash = '0x' + '34' * 32
        metadata = {'provider_payload_latest': {'txHash': polygon_hash}, koywe_polygon.SECTION: {'phase': 'x'}}
        self.assertIsNone(find_provider_tx_hash(metadata))
        metadata['bsc_provider_transfer_tx_hash'] = DELIVERY_HASH
        self.assertEqual(find_provider_tx_hash(metadata), DELIVERY_HASH)
        self.assertEqual(find_provider_tx_hash({'provider_payload_latest': {'txHash': polygon_hash}}), polygon_hash)


class SponsorExpiryTests(TestCase):
    @override_settings(KOYWE_SAVINGS_NETWORK='POLYGON')
    def test_sponsor_refuses_a_payment_into_an_expired_route(self):
        user = User.objects.create_user(username='koywe-polygon-off', firebase_uid='koywe-polygon-off')
        ramp = RampTransaction.objects.create(
            provider='koywe', direction='off_ramp', status='PENDING', actor_user=user, actor_address=ADDRESS,
            destination='cusd_plus', provider_order_id='order-2',
            metadata={koywe_polygon.SECTION: {'deposit_address': RELAY_DEPOSIT, 'route': {
                'deposit_address': RELAY_DEPOSIT, 'recipient': KOYWE_POLYGON, 'deadline': 1}}})
        self.assertTrue(koywe_polygon.expired_deposit_address(RELAY_DEPOSIT.upper().replace('0X', '0x')))
        koywe_polygon.mark(ramp, route={'deposit_address': RELAY_DEPOSIT, 'recipient': KOYWE_POLYGON,
                                        'deadline': 4_000_000_000})
        self.assertFalse(koywe_polygon.expired_deposit_address(RELAY_DEPOSIT))
        self.assertFalse(koywe_polygon.expired_deposit_address('0x' + '77' * 20))


class AlertRetryTests(TestCase):
    def test_an_undelivered_refund_alert_is_retried(self):
        user = User.objects.create_user(username='koywe-polygon-alert', firebase_uid='koywe-polygon-alert')
        ramp = RampTransaction.objects.create(
            provider='koywe', direction='off_ramp', status='FAILED', actor_user=user, actor_address=ADDRESS,
            destination='cusd_plus', provider_order_id='order-3',
            metadata={koywe_polygon.SECTION: {'deposit_address': RELAY_DEPOSIT, 'route': {
                'deposit_address': RELAY_DEPOSIT, 'request_id': 'req-9'}}})
        relay = mock.Mock()
        relay.return_value.status.return_value = {'status': 'refund'}
        with mock.patch('payment_accounts.relay.RelayClient', relay), \
             mock.patch('config.ops_alerts.send_ops_alert', side_effect=[False, True]) as alert:
            self.assertIn(ramp.pk, [r.pk for r in koywe_polygon.open_off_ramps()])
            koywe_polygon.check_off_ramp(ramp)
            ramp.refresh_from_db()
            self.assertIn(ramp.pk, [r.pk for r in koywe_polygon.open_off_ramps()])
            koywe_polygon.check_off_ramp(ramp)
        self.assertEqual(alert.call_count, 2)
        self.assertEqual(relay.return_value.status.call_count, 1)
        self.assertNotIn(ramp.pk, [r.pk for r in koywe_polygon.open_off_ramps()])
