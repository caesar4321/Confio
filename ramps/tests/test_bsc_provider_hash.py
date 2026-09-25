from decimal import Decimal
from unittest import mock

from django.test import TestCase

from ramps.bsc_provider_hash import TRANSFER_TOPIC, USDT_BSC, attach_after_koywe_sync, attach_arrival
from ramps.metrics import deposited_volume_by_provider
from ramps.models import RampTransaction

WALLET = '0x' + '11' * 20
KOYWE_WALLET = '0x' + 'a0' * 20  # any sender: the hash Koywe reports is the evidence
TX = '0x' + 'ab' * 32


def topic(address):
    return '0x' + address[2:].rjust(64, '0')


def transfer_log(amount, to=WALLET, index=7):
    return {'address': USDT_BSC, 'logIndex': hex(index),
            'topics': [TRANSFER_TOPIC, topic(KOYWE_WALLET), topic(to)],
            'data': hex(int(Decimal(amount) * 10 ** 18))}


def receipt(*logs, status='0x1'):
    return {'status': status, 'logs': list(logs) or [transfer_log('96.023865')]}


class ProviderHashArrivalTests(TestCase):
    def ramp(self, tx_hash=TX, amount='96.023865', **overrides):
        metadata = {'provider_payload_latest': {'status': 'DELIVERED', 'txHash': tx_hash}} if tx_hash else {}
        values = dict(provider='koywe', direction='on_ramp', status='COMPLETED', destination='cusd_plus',
                      final_currency='USDT BSC', final_amount=Decimal(amount),
                      crypto_amount_estimated=Decimal(amount), actor_address=WALLET, metadata=metadata)
        values.update(overrides)
        return RampTransaction.objects.bulk_create([RampTransaction(**values)])[0]

    @mock.patch('ramps.signals.create_notification')
    @mock.patch('ramps.signals.emit_event')
    def test_reported_hash_verified_on_chain_is_recorded_silently(self, emit, notify):
        ramp = self.ramp()
        self.assertEqual(sum(deposited_volume_by_provider().values()), 0)
        rpc = mock.Mock(return_value=receipt())
        self.assertEqual(attach_arrival(ramp, rpc), 'verified')
        rpc.assert_called_once_with('eth_getTransactionReceipt', [TX])
        ramp.refresh_from_db()
        self.assertEqual((ramp.metadata['bsc_arrival_tx_hash'], ramp.metadata['bsc_arrival_log_index']), (TX, 7))
        self.assertEqual(ramp.metadata['bsc_arrival_source'], 'provider_hash')
        self.assertEqual(deposited_volume_by_provider()['koywe'], Decimal('96.023865'))
        notify.assert_not_called()
        emit.assert_not_called()

    def test_on_chain_amount_is_recorded_within_tolerance(self):
        ramp = self.ramp(amount='100')
        self.assertEqual(attach_arrival(ramp, mock.Mock(return_value=receipt(transfer_log('98.5')))), 'verified')
        ramp.refresh_from_db()
        self.assertEqual(ramp.metadata['bsc_arrival_amount'], '98.500000')

    def test_no_hash_means_no_proof(self):
        rpc = mock.Mock()
        self.assertEqual(attach_arrival(self.ramp(tx_hash=None), rpc), 'no_provider_hash')
        rpc.assert_not_called()

    def test_a_hash_proves_one_ramp_only(self):
        first = self.ramp()
        attach_arrival(first, mock.Mock(return_value=receipt()))
        second = self.ramp()
        self.assertEqual(attach_arrival(second, mock.Mock(return_value=receipt())), 'hash_claimed_by_another_ramp')

    def test_chain_must_confirm_delivery_to_the_wallet(self):
        cases = {
            'failed tx': receipt(status='0x0'),
            'other wallet': receipt(transfer_log('96.023865', to='0x' + '22' * 20)),
            'amount off': receipt(transfer_log('50')),
            'ambiguous': receipt(transfer_log('96.023865', index=1), transfer_log('96.023865', index=2)),
            'no receipt': None,
        }
        for label, rpc_receipt in cases.items():
            with self.subTest(label):
                RampTransaction.objects.all().delete()
                ramp = self.ramp()
                self.assertEqual(attach_arrival(ramp, mock.Mock(return_value=rpc_receipt)), 'chain_mismatch')
                self.assertFalse(RampTransaction.objects.filter(metadata__has_key='bsc_arrival_tx_hash').exists())

    def test_dry_run_writes_nothing(self):
        ramp = self.ramp()
        self.assertEqual(attach_arrival(ramp, mock.Mock(return_value=receipt()), apply=False), 'verified')
        self.assertFalse(RampTransaction.objects.filter(metadata__has_key='bsc_arrival_tx_hash').exists())

    def test_one_batch_transaction_can_prove_two_wallets(self):
        other_wallet = '0x' + '33' * 20
        first = self.ramp()
        second = self.ramp(actor_address=other_wallet)
        batch = receipt(transfer_log('96.023865', to=WALLET, index=1),
                        transfer_log('96.023865', to=other_wallet, index=2))
        self.assertEqual(attach_arrival(first, mock.Mock(return_value=batch)), 'verified')
        self.assertEqual(attach_arrival(second, mock.Mock(return_value=batch)), 'verified')
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual((first.metadata['bsc_arrival_log_index'], second.metadata['bsc_arrival_log_index']), (1, 2))

    def test_live_hook_attaches_and_never_breaks_a_sync(self):
        ramp = self.ramp()
        with mock.patch('cusd_plus.tasks._rpc', return_value=receipt()):
            attach_after_koywe_sync(ramp)
        self.assertTrue(RampTransaction.objects.filter(pk=ramp.pk, metadata__has_key='bsc_arrival_tx_hash').exists())
        other = self.ramp(tx_hash='0x' + 'cd' * 32)
        with mock.patch('cusd_plus.tasks._rpc', side_effect=RuntimeError('rpc down')):
            attach_after_koywe_sync(other)  # must not raise
        self.assertFalse(RampTransaction.objects.filter(pk=other.pk, metadata__has_key='bsc_arrival_tx_hash').exists())

    def test_live_hook_ignores_other_ramps(self):
        with mock.patch('cusd_plus.tasks._rpc') as rpc:
            attach_after_koywe_sync(self.ramp(status='PROCESSING'))
            attach_after_koywe_sync(self.ramp(destination='cusd'))
            attach_after_koywe_sync(self.ramp(provider='guardarian'))
        rpc.assert_not_called()


class ProviderHashLifecycleTests(TestCase):
    """The hook inside a real Koywe sync, and its interplay with the scanner
    and the conversion link."""

    ramp = ProviderHashArrivalTests.ramp

    def sync(self, ramp, **payload):
        from ramps.koywe_sync import sync_koywe_ramp_transaction_from_order
        order = {'status': 'DELIVERED', 'orderId': ramp.provider_order_id or 'order-1',
                 'amountIn': '1500', 'amountOut': str(ramp.crypto_amount_estimated), 'txHash': TX}
        order.update(payload)
        with mock.patch('ramps.signals.create_notification'), mock.patch('ramps.signals.emit_event'):
            return sync_koywe_ramp_transaction_from_order(ramp_tx=ramp, order_payload=order)

    def test_a_koywe_sync_carrying_the_hash_attaches_the_arrival(self):
        ramp = self.ramp(tx_hash=None, provider_order_id='order-1')
        with mock.patch('cusd_plus.tasks._rpc', return_value=receipt()) as rpc:
            self.sync(ramp)
        rpc.assert_called_once_with('eth_getTransactionReceipt', [TX])
        ramp.refresh_from_db()
        self.assertEqual(ramp.metadata['bsc_arrival_tx_hash'], TX)

    def test_scanner_after_the_hook_recognises_the_same_arrival(self):
        from ramps.signals import attribute_bsc_ramp_arrival
        ramp = self.ramp()
        attach_arrival(ramp, mock.Mock(return_value=receipt()))
        matched = attribute_bsc_ramp_arrival(actor_address=WALLET, amount=Decimal('96.023865'),
                                             tx_hash=TX.upper().replace('0X', '0x'), log_index=7,
                                             sender_address=KOYWE_WALLET)
        # Not None: the scanner must file it as this ramp's arrival, never as
        # an external deposit with its own receipt and push.
        self.assertEqual(matched.pk, ramp.pk)

    def test_scanner_recognises_an_arrival_even_after_its_conversion_linked(self):
        from conversion.models import Conversion
        from ramps.signals import attribute_bsc_ramp_arrival
        ramp = self.ramp()
        attach_arrival(ramp, mock.Mock(return_value=receipt()))
        conversion = Conversion.objects.bulk_create([Conversion(
            conversion_type='to_savings', status='COMPLETED', actor_type='user', actor_address=WALLET,
            from_amount=Decimal('96.023865'), to_amount=Decimal('96.0'))])[0]
        RampTransaction.objects.filter(pk=ramp.pk).update(conversion=conversion)  # linked before the scan
        matched = attribute_bsc_ramp_arrival(actor_address=WALLET, amount=Decimal('96.023865'),
                                             tx_hash=TX, log_index=7, sender_address=KOYWE_WALLET)
        self.assertEqual(matched.pk, ramp.pk)

    def test_relink_never_runs_the_signal_fallbacks(self):
        ramp = self.ramp()
        with mock.patch('cusd_plus.tasks._rpc', return_value=receipt()), \
             mock.patch('ramps.signals.handle_ramp_conversion_link') as handler, \
             mock.patch('ramps.signals.link_attributed_bsc_ramps', return_value=False) as attributed:
            from conversion.models import Conversion
            Conversion.objects.bulk_create([Conversion(
                conversion_type='usdt_to_cusd', status='COMPLETED', actor_type='user', actor_address=WALLET,
                from_amount=Decimal('5'), to_amount=Decimal('5'))])
            attach_after_koywe_sync(ramp)
        handler.assert_not_called()
        attributed.assert_called_once()

    def test_scanner_never_hands_one_wallets_ramp_to_another_in_a_batch(self):
        from ramps.signals import attribute_bsc_ramp_arrival
        other_wallet = '0x' + '33' * 20
        ramp = self.ramp()
        batch = receipt(transfer_log('96.023865', to=WALLET, index=1),
                        transfer_log('50', to=other_wallet, index=2))
        attach_arrival(ramp, mock.Mock(return_value=batch))
        # The same tx's other log, to another wallet, is not this ramp's arrival.
        self.assertIsNone(attribute_bsc_ramp_arrival(actor_address=other_wallet, amount=Decimal('50'),
                                                     tx_hash=TX, log_index=2, sender_address=KOYWE_WALLET))
        mine = attribute_bsc_ramp_arrival(actor_address=WALLET, amount=Decimal('96.023865'),
                                          tx_hash=TX, log_index=1, sender_address=KOYWE_WALLET)
        self.assertEqual(mine.pk, ramp.pk)

    def test_a_failed_verification_is_not_retried_for_the_same_hash(self):
        ramp = self.ramp()
        with mock.patch('cusd_plus.tasks._rpc', return_value=receipt(status='0x0')) as rpc:
            attach_after_koywe_sync(ramp)
            ramp.refresh_from_db()
            attach_after_koywe_sync(ramp)
        self.assertEqual(rpc.call_count, 1)
        self.assertEqual(ramp.metadata['bsc_arrival_check'],
                         {'checked_hash': TX, 'outcome': 'chain_mismatch'})
        # Our own failed guess is never read back as a provider-reported hash.
        from ramps.signals import find_provider_tx_hash
        self.assertEqual(find_provider_tx_hash({'bsc_arrival_check': ramp.metadata['bsc_arrival_check']}), None)
        # A new hash from Koywe is tried again.
        ramp.metadata['provider_payload_latest']['txHash'] = '0x' + 'ef' * 32
        RampTransaction.objects.filter(pk=ramp.pk).update(metadata=ramp.metadata)
        ramp.refresh_from_db()
        with mock.patch('cusd_plus.tasks._rpc', return_value=receipt()) as rpc:
            attach_after_koywe_sync(ramp)
        rpc.assert_called_once()

    def test_dry_run_reports_one_ramp_per_transfer(self):
        first, second = self.ramp(), self.ramp()
        seen = set()
        rpc = mock.Mock(return_value=receipt())
        outcomes = [attach_arrival(r, rpc, apply=False, seen=seen) for r in (first, second)]
        self.assertEqual(outcomes, ['verified', 'hash_claimed_by_another_ramp'])

    def test_conversion_completed_before_the_hash_is_linked_afterwards(self):
        from conversion.models import Conversion
        ramp = self.ramp()
        conversion = Conversion.objects.bulk_create([Conversion(
            conversion_type='to_savings', status='COMPLETED', actor_type='user', actor_address=WALLET,
            from_amount=Decimal('96.023865'), to_amount=Decimal('96.0'),
            net_amount_exact=Decimal('96.0'), gross_amount_exact=Decimal('96.023865'))])[0]
        with mock.patch('cusd_plus.tasks._rpc', return_value=receipt()):
            attach_after_koywe_sync(ramp)
        ramp.refresh_from_db()
        self.assertEqual(ramp.conversion_id, conversion.pk)

    def test_latest_provider_payload_wins_over_the_first_snapshot(self):
        from ramps.signals import find_provider_tx_hash
        stale, fresh = '0x' + '01' * 32, '0x' + '02' * 32
        metadata = {'provider_payload_created': {'txHash': stale},
                    'provider_payload_latest': {'txHash': fresh}}
        self.assertEqual(find_provider_tx_hash(metadata), fresh)
