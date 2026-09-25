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
