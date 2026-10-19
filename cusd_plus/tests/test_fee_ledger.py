"""The fee ledger: every cUSD fee once, attributed to its source."""
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from eth_abi import encode as abi_encode
from eth_utils import keccak

from cusd_plus import crypto_catalog, fee_ledger
from cusd_plus.crypto_policy import BUY_TYPES, SEL_CRYPTO_BUY

CUSD = '0x' + '77' * 20
WAD = 10 ** 18


def _event(direction='exit', tx='0x' + 'aa' * 32):
    return SimpleNamespace(tx_hash=tx, direction=direction)


def _batch(kind, request_id='', calls=None, crypto_trade=None):
    return SimpleNamespace(kind=kind, client_request_id=request_id, calls_json=json.dumps(calls or []),
                           crypto_trade=crypto_trade)


class ClassifyTests(SimpleTestCase):
    def tag(self, event, batch, ramps=None, payouts=None):
        return fee_ledger.classify(event, batch, ramps or {}, payouts or set(), set())

    def test_investments(self):
        self.assertEqual(self.tag(_event(), _batch('stock_buy')), 'stock')
        self.assertEqual(self.tag(_event('entry'), _batch('stock_sell')), 'stock')
        btc = SimpleNamespace(symbol='BTCB')
        gold = SimpleNamespace(symbol='XAUT')
        eth = SimpleNamespace(symbol='ETH')
        self.assertEqual(self.tag(_event(), _batch('crypto_buy', crypto_trade=btc)), 'bitcoin')
        self.assertEqual(self.tag(_event('entry'), _batch('crypto_sell', crypto_trade=gold)), 'gold')
        self.assertEqual(self.tag(_event(), _batch('crypto_buy', crypto_trade=eth)), 'crypto')

    def test_crypto_without_ledger_row_reads_the_calldata(self):
        xaut = crypto_catalog.by_symbol('XAUT')
        data = '0x' + SEL_CRYPTO_BUY + abi_encode(
            BUY_TYPES, [0, WAD, 1, xaut.route_bytes('buy'), xaut.address, 1, 90]).hex()
        with override_settings(CRYPTO_SWAP_ROUTER_ADDRESS='0x' + '5a' * 20):
            batch = _batch('crypto_buy', calls=[{'to': '0x' + '5a' * 20, 'value': '0', 'data': data}])
            self.assertEqual(self.tag(_event(), batch), 'gold')

    def test_ramps_pay_and_outside_usdt(self):
        tx = '0x' + 'aa' * 32
        self.assertEqual(self.tag(_event('entry'), _batch('mint_cusd', 'local-mint-abc_a0')), 'onramp')
        self.assertEqual(self.tag(_event('entry'), _batch('subscribe'), ramps={tx: 'on_ramp'}), 'onramp')
        self.assertEqual(self.tag(_event('exit'), None, ramps={tx: 'off_ramp'}), 'offramp')
        self.assertEqual(self.tag(_event(), _batch('payment_bridge'), payouts={tx}), 'offramp')
        self.assertEqual(self.tag(_event(), _batch('payment_bridge')), 'pay')
        self.assertEqual(self.tag(_event(), _batch('pay_cusd')), 'pay')
        self.assertEqual(self.tag(_event(), _batch('send_redeem')), 'usdt_out')
        provider = '0x' + 'cc' * 20
        transfer = {'to': '0x55d398326f99059ff775485246999027b3197955', 'value': '0',
                    'data': '0xa9059cbb' + provider[2:].rjust(64, '0') + '00' * 32}
        batch = _batch('redeem', calls=[transfer])
        # Only provider-order evidence makes a raw transfer an off-ramp.
        self.assertEqual(fee_ledger.classify(_event(), batch, {}, set(), {provider}), 'offramp')
        self.assertEqual(fee_ledger.classify(_event(), batch, {}, set(), {'0x' + 'dd' * 20}), 'usdt_out')
        self.assertEqual(self.tag(_event(), _batch('redeem')), 'usdt_out')
        self.assertEqual(self.tag(_event('entry'), None), 'usdt_in')
        self.assertEqual(self.tag(_event('exit'), None), 'usdt_out')


@override_settings(CUSD_VAULT_ADDRESS=CUSD)
class RecordAndSummaryTests(TestCase):
    def _log(self, sig, fee, index, block=100, topics=()):
        return {'address': CUSD, 'topics': ['0x' + keccak(text=sig).hex(), *topics],
                'data': '0x' + abi_encode(['uint256'] * 4, [100 * WAD, fee, 100 * WAD - fee, 90]).hex(),
                'logIndex': hex(index), 'blockNumber': hex(block)}

    def test_records_once_and_sums_by_source(self):
        from blockchain.models import SponsoredBatch
        from conversion.models import CusdFeeEvent
        from users.models import User

        now = datetime.now(dt_timezone.utc)
        exit_sig = 'SavingsExitSettled(address,uint256,uint256,uint256,uint256)'
        entry_sig = 'MintedWithFee(address,address,uint256,uint256,uint256,uint256)'
        stock_tx, outside_tx = '0x' + '01' * 32, '0x' + '02' * 32
        times = {100: now - timedelta(days=1), 200: now - timedelta(days=60)}
        self.assertEqual(fee_ledger.record_fee_events(stock_tx, [self._log(exit_sig, 9 * 10 ** 17, 3)], times), 1)
        # Replays (scanner + backfill) never double count.
        self.assertEqual(fee_ledger.record_fee_events(stock_tx, [self._log(exit_sig, 9 * 10 ** 17, 3)], times), 0)
        fee_ledger.record_fee_events(outside_tx, [self._log(entry_sig, 45 * 10 ** 16, 1, block=200)], times)
        self.assertEqual(CusdFeeEvent.objects.count(), 2)

        user = User.objects.create(username='feeledger', firebase_uid='feeledger')
        SponsoredBatch.objects.create(user=user, user_bsc_address='0x' + '44' * 20, kind='stock_buy',
                                      num_calls=2, calls_json='[]', tx_hash=stock_tx.upper().replace('0X', '0x'),
                                      status='confirmed', gas_limit=1, max_fee_wei=1)
        result = fee_ledger.summary(now=now)
        rows = {r['key']: r for r in result['rows']}
        self.assertEqual(rows['stock']['fee_usd'], Decimal('0.9'))
        self.assertEqual(rows['stock']['fee_usd_30d'], Decimal('0.9'))
        self.assertEqual(rows['usdt_in']['fee_usd'], Decimal('0.45'))
        self.assertEqual(rows['usdt_in']['fee_usd_30d'], Decimal('0'), 'older than 30 days')
        self.assertEqual(result['total']['fee_usd'], Decimal('1.35'))
        self.assertEqual(result['total']['count'], 2)


class TimestampTests(SimpleTestCase):
    def test_null_block_is_unknown_not_epoch(self):
        self.assertIsNone(fee_ledger.block_time(lambda m, p: None, 5, {}))
        self.assertIsNone(fee_ledger.block_time(lambda m, p: {'timestamp': '0x0'}, 6, {}))
        when = fee_ledger.block_time(lambda m, p: {'timestamp': hex(1_700_000_000)}, 7, {})
        self.assertEqual(when.year, 2023)


@override_settings(CUSD_VAULT_ADDRESS=CUSD)
class TimestampRepairTests(TestCase):
    def test_replay_repairs_a_missing_time(self):
        from conversion.models import CusdFeeEvent

        log = RecordAndSummaryTests._log(None, 'SavingsExitSettled(address,uint256,uint256,uint256,uint256)',
                                         10 ** 16, 1)
        fee_ledger.record_fee_events('0x' + '09' * 32, [log], {})
        self.assertIsNone(CusdFeeEvent.objects.get().block_time)
        when = datetime.now(dt_timezone.utc)
        fee_ledger.record_fee_events('0x' + '09' * 32, [log], {100: when})
        self.assertEqual(CusdFeeEvent.objects.get().block_time, when)


class ProviderAddressTests(TestCase):
    def test_every_documented_koywe_field_counts_but_not_provider_metadata(self):
        from ramps.models import RampTransaction

        for i, details in enumerate([
            {'walletAddress': '0x' + '01' * 20},
            {'address': '0x' + '02' * 20},
            {'providedAddress': '0x' + '03' * 20},
            {'providedAddress': '0x' + '04' * 20, 'providedAddressFromProviderDetails': True},
            {'depositAddress': '0x' + '05' * 20},
        ]):
            RampTransaction.objects.create(provider='koywe', direction='off_ramp', provider_order_id=f'o{i}',
                                           metadata={'payment_details': details})
        found = fee_ledger._provider_deposit_addresses()
        self.assertEqual(found, {'0x' + n * 20 for n in ('01', '02', '03', '05')})


@override_settings(CUSD_VAULT_ADDRESS=CUSD)
class BackfillFromConversionsTests(TestCase):
    def test_replays_receipts_of_reconciled_conversions(self):
        from io import StringIO

        from django.core.management import call_command

        from conversion.models import Conversion, CusdFeeEvent

        tx = '0x' + '0e' * 32
        Conversion.objects.create(conversion_type='usdt_to_cusd', from_amount=100, to_amount=99,
                                  to_transaction_hash=tx, contract_event_index=4, status='COMPLETED')
        log = RecordAndSummaryTests._log(None, 'MintedWithFee(address,address,uint256,uint256,uint256,uint256)',
                                         9 * 10 ** 17, 4)
        log['address'] = CUSD
        other = dict(log, address='0x' + '99' * 20, logIndex='0x5')  # not the vault: ignored

        def rpc(method, params, timeout=15):
            if method == 'eth_getTransactionReceipt':
                return {'status': '0x1', 'blockNumber': hex(100), 'logs': [log, other]}
            return {'timestamp': hex(1_760_000_000)}

        with mock.patch('cusd_plus.tasks._rpc', side_effect=rpc), mock.patch('time.sleep'):
            out = StringIO()
            call_command('backfill_cusd_fee_ledger', '--from-conversions', '--apply', stdout=out)
        self.assertIn('stored 1 new ledger rows', out.getvalue())
        event = CusdFeeEvent.objects.get()
        self.assertEqual((event.tx_hash, event.log_index, event.direction), (tx, 4, 'entry'))
        self.assertIsNotNone(event.block_time)
