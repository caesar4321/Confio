"""Stored BSC balances (blockchain/bsc_balance_service.py) and stored stock
holdings (gm_holdings StockHoldings rows): Postgres + Redis, the cUSD-a way."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from blockchain import bsc_balance_service as svc
from blockchain.bsc_balance_service import BscBalanceService, parties_from_receipt
from blockchain.models import Balance, StockHoldings
from users.models import Account

CUSD = '0x' + '1' * 40
CONFIO = '0x' + '2' * 40
USDT = '0x' + '3' * 40
VAULT = '0x' + '4' * 40
WALLET = '0x' + 'a' * 40
OTHER = '0x' + 'b' * 40
STRANGER = '0x' + 'c' * 40
WAD = 10 ** 18

TOKEN_SETTINGS = dict(CUSD_VAULT_ADDRESS=CUSD, BSC_CONFIO_TOKEN_ADDRESS=CONFIO,
                      CUSD_PLUS_USDT_BSC=USDT, CUSD_PLUS_VAULT_ADDRESS=VAULT)
CHAIN = {'CUSD_BSC': 5 * WAD, 'CONFIO_BSC': 7 * WAD, 'USDT_BSC': 2 * WAD, 'CUSD_PLUS': 3 * WAD}


def _user():
    uid = uuid4().hex
    return get_user_model().objects.create(username=f'bal-{uid[:20]}', firebase_uid=uid)


def _word(addr):
    return '0x' + '0' * 24 + addr[2:]


@override_settings(**TOKEN_SETTINGS)
class BscBalanceServiceTests(TestCase):
    def setUp(self):
        cache.clear()
        user = _user()
        self.account = Account.objects.create(user=user, account_type='personal', account_index=0,
                                              bsc_address=WALLET.upper().replace('0X', '0x'))

    def _read(self, chain=CHAIN):
        with mock.patch.object(svc, 'read_chain', return_value=(dict(chain), 100)) as read:
            out = BscBalanceService.balances_raw(WALLET)
        return out, read

    def test_first_read_goes_to_chain_and_stores_every_token(self):
        out, read = self._read()
        self.assertEqual(out, CHAIN)
        read.assert_called_once()
        rows = {r.token: r for r in Balance.objects.filter(account=self.account)}
        self.assertEqual(set(rows), set(CHAIN))
        self.assertEqual(rows['CUSD_BSC'].amount, Decimal('5'))
        self.assertEqual(rows['CUSD_BSC'].address, WALLET)
        self.assertFalse(any(r.is_stale for r in rows.values()))

    def test_fresh_rows_are_served_without_the_chain_even_when_redis_is_empty(self):
        self._read()
        cache.clear()
        out, read = self._read({})
        self.assertEqual(out, CHAIN)
        read.assert_not_called()

    def test_rows_older_than_five_minutes_are_reread(self):
        self._read()
        cache.clear()
        Balance.objects.filter(account=self.account).update(
            last_synced=timezone.now() - timedelta(minutes=6))
        _, read = self._read({**CHAIN, 'USDT_BSC': 9 * WAD})
        read.assert_called_once()
        self.assertEqual(Balance.objects.get(account=self.account, token='USDT_BSC').amount, Decimal('9'))

    def test_mark_stale_sends_the_next_read_to_the_chain(self):
        self._read()
        BscBalanceService.mark_stale(WALLET)
        self.assertTrue(all(Balance.objects.filter(account=self.account).values_list('is_stale', flat=True)))
        out, read = self._read({**CHAIN, 'CUSD_BSC': 1 * WAD})
        read.assert_called_once()
        self.assertEqual(out['CUSD_BSC'], 1 * WAD)
        self.assertFalse(Balance.objects.get(account=self.account, token='CUSD_BSC').is_stale)

    def test_a_chain_failure_serves_the_stored_rows_never_a_false_zero(self):
        self._read()
        BscBalanceService.mark_stale(WALLET)
        with mock.patch.object(svc, 'read_chain', side_effect=RuntimeError('node down')):
            out = BscBalanceService.balances_raw(WALLET)
        self.assertEqual(out, CHAIN)

    def test_no_row_and_no_chain_is_unknown_not_zero(self):
        with mock.patch.object(svc, 'read_chain', side_effect=RuntimeError('node down')):
            out = BscBalanceService.balances_raw(WALLET)
        self.assertEqual(out, {})

    def test_a_token_that_did_not_answer_keeps_its_row_and_stays_out_of_redis(self):
        self._read()
        BscBalanceService.mark_stale(WALLET)
        partial = {k: v for k, v in CHAIN.items() if k != 'CONFIO_BSC'}
        out, _ = self._read({**partial, 'CUSD_BSC': 8 * WAD})
        self.assertEqual(out['CONFIO_BSC'], 7 * WAD)          # last stored
        self.assertEqual(out['CUSD_BSC'], 8 * WAD)
        _, read = self._read()
        read.assert_called_once()                              # CONFIO is still stale: re-read

    def test_a_transaction_during_the_read_leaves_the_rows_stale(self):
        def read_then_tx(*_a, **_k):
            BscBalanceService.mark_stale(WALLET)             # broadcast while the read was out
            return dict(CHAIN), 100
        with mock.patch.object(svc, 'read_chain', side_effect=read_then_tx):
            BscBalanceService.balances_raw(WALLET)
        self.assertTrue(all(Balance.objects.filter(account=self.account).values_list('is_stale', flat=True)))
        _, read = self._read()
        read.assert_called_once()

    def test_rows_from_a_replaced_wallet_never_stand_for_the_new_one(self):
        self._read()
        self.account.bsc_address = OTHER
        self.account.save(update_fields=['bsc_address'])
        cache.clear()
        with mock.patch.object(svc, 'read_chain', return_value=({**CHAIN, 'CUSD_BSC': 0}, 100)) as read:
            out = BscBalanceService.balances_raw(OTHER)
        read.assert_called_once()
        self.assertEqual(out['CUSD_BSC'], 0)

    def test_an_address_no_account_owns_is_read_but_never_stored(self):
        with mock.patch.object(svc, 'read_chain', return_value=(dict(CHAIN), 100)):
            out = BscBalanceService.balances_raw(STRANGER)
        self.assertEqual(out, CHAIN)
        self.assertFalse(Balance.objects.filter(address=STRANGER).exists())

    def test_amounts_round_trip_exactly(self):
        raw = 123456789012345678901234567  # 27 digits: beyond float and default Decimal precision
        self.assertEqual(svc.to_raw(svc.to_amount(raw)), raw)

    def test_position_usd_is_stored_shares_times_live_price(self):
        from cusd_plus import vault
        self._read()
        with mock.patch.object(vault, 'p_plus_wad', return_value=int(1.05 * WAD)):
            self.assertAlmostEqual(vault.position_usd(WALLET), 3.15, places=9)
        with mock.patch.object(vault, 'p_plus_wad', side_effect=RuntimeError('node down')):
            self.assertAlmostEqual(vault.position_usd(WALLET), 3.15, places=9)   # last price

    def test_display_usdt_reads_the_stored_row_and_fresh_reads_the_chain(self):
        from cusd_plus import vault
        self._read()
        self.assertEqual(vault.usdt_balance_raw(WALLET), 2 * WAD)
        with mock.patch.object(vault, 'erc20_balance_raw', return_value=11) as live:
            self.assertEqual(vault.usdt_balance_raw(WALLET, fresh=True), 11)
        live.assert_called_once()

    def test_confirmation_marks_every_token_party_in_the_receipt_stale(self):
        from cusd_plus.tasks import _mark_receipt_balances_stale
        user = _user()
        recipient = Account.objects.create(user=user, account_type='personal', account_index=0, bsc_address=OTHER)
        self._read()
        with mock.patch.object(svc, 'read_chain', return_value=(dict(CHAIN), 100)):
            BscBalanceService.balances_raw(OTHER)
        receipt = {'logs': [
            {'address': CUSD, 'topics': [svc.TRANSFER_TOPIC, _word(WALLET), _word(OTHER)], 'data': '0x1'},
        ]}
        _mark_receipt_balances_stale(WALLET, receipt)
        self.assertTrue(Balance.objects.filter(account=recipient, is_stale=True).exists())
        self.assertTrue(Balance.objects.filter(account=self.account, is_stale=True).exists())

    def test_a_transaction_marked_while_fresh_rows_are_read_never_gets_cached(self):
        self._read()
        cache.clear()
        real = svc.to_raw

        def mark_mid_read(amount):
            BscBalanceService.mark_stale(WALLET)       # after the SELECT, before the Redis write
            return real(amount)
        with mock.patch.object(svc, 'to_raw', side_effect=mark_mid_read):
            BscBalanceService.balances_raw(WALLET)
        self.assertIsNone(cache.get(svc._cache_key(self.account.id, WALLET)))
        _, read = self._read()
        read.assert_called_once()

    def test_rows_marked_stale_after_the_select_never_leave_a_redis_copy(self):
        self._read()
        cache.clear()
        real_set = cache.set

        def set_then_mark(*args, **kwargs):
            real_set(*args, **kwargs)
            if str(args[0]).startswith('bsc_bal:'):
                # A stale-marking whose generation bump preceded our read and
                # whose UPDATE lands only now (the reviewer's race (a)).
                from blockchain.models import Balance as B
                B.objects.filter(account=self.account).update(is_stale=True)
        with mock.patch.object(svc.cache, 'set', side_effect=set_then_mark):
            BscBalanceService.balances_raw(WALLET)
        self.assertIsNone(cache.get(svc._cache_key(self.account.id, WALLET)))

    def test_a_read_from_a_node_behind_the_last_confirmed_transaction_is_never_stored(self):
        self._read()
        BscBalanceService.mark_stale(WALLET, min_block=200)
        with mock.patch.object(svc, 'read_chain', return_value=({**CHAIN, 'CUSD_BSC': 1}, 199)):
            out = BscBalanceService.balances_raw(WALLET)
        self.assertEqual(out['CUSD_BSC'], 1)                       # shown to this caller
        self.assertTrue(Balance.objects.get(account=self.account, token='CUSD_BSC').is_stale)
        with mock.patch.object(svc, 'read_chain', return_value=({**CHAIN, 'CUSD_BSC': 2}, 200)):
            BscBalanceService.balances_raw(WALLET)
        row = Balance.objects.get(account=self.account, token='CUSD_BSC')
        self.assertEqual((svc.to_raw(row.amount), row.is_stale), (2, False))

    def test_a_receipt_moving_stock_tokens_raises_the_holdings_floor(self):
        from cusd_plus.tasks import _mark_receipt_balances_stale
        gm_token = '0x' + '5' * 40
        receipt = {'blockNumber': hex(300),
                   'logs': [{'address': gm_token, 'topics': [svc.TRANSFER_TOPIC, _word(WALLET), _word(STRANGER)]}]}
        with mock.patch('cusd_plus.gm_holdings.registry', return_value={'TSLAon': {'address': gm_token}}):
            _mark_receipt_balances_stale('', receipt)
        self.assertEqual(cache.get(f'gm_hold_floor:{WALLET}'), 300)
        self.assertIsNone(cache.get(svc._floor_key(WALLET)))       # a stock-only move: cUSD/USDT untouched

    def test_a_redis_outage_still_lands_the_durable_stale_marks(self):
        from cusd_plus import gm_holdings
        self._read()
        StockHoldings.objects.create(bsc_address=WALLET, held={'TSLAon': 1.0}, blocks={}, scanned_at=timezone.now())
        with mock.patch.object(svc.cache, 'set', side_effect=ConnectionError('redis down')), \
                self.assertRaises(ConnectionError):
            BscBalanceService.mark_stale(WALLET, min_block=50)
        self.assertTrue(all(Balance.objects.filter(account=self.account).values_list('is_stale', flat=True)))
        with mock.patch.object(gm_holdings.cache, 'set', side_effect=ConnectionError('redis down')), \
                mock.patch.object(gm_holdings, '_raise_floor', side_effect=ConnectionError('redis down')), \
                self.assertRaises(ConnectionError):
            gm_holdings.invalidate_holdings(WALLET, min_block=50)
        self.assertTrue(StockHoldings.objects.get(bsc_address=WALLET).is_stale)

    def test_the_floor_only_rises(self):
        BscBalanceService.mark_stale(WALLET, min_block=105)
        BscBalanceService.mark_stale(WALLET, min_block=100)
        self.assertEqual(cache.get(svc._floor_key(WALLET)), 105)

    def test_the_floor_raise_is_one_atomic_redis_script_when_redis_is_the_cache(self):
        client = mock.Mock()
        with mock.patch('django_redis.get_redis_connection', return_value=client):
            svc.raise_floor('bsc_bal_floor:x', 120, 600)
        script, nkeys, redis_key, block, ttl = client.eval.call_args.args
        self.assertIn("redis.call('SET'", script)
        self.assertEqual((nkeys, block, ttl), (1, 120, 600))
        self.assertTrue(redis_key.endswith('bsc_bal_floor:x'))

    def test_a_mined_relay_marks_the_signer_and_its_recipient_stale(self):
        from cusd_plus import tasks
        user = _user()
        recipient = Account.objects.create(user=user, account_type='personal', account_index=0, bsc_address=OTHER)
        self._read()
        with mock.patch.object(svc, 'read_chain', return_value=(dict(CHAIN), 100)):
            BscBalanceService.balances_raw(OTHER)
        receipt = {'logs': [{'address': USDT, 'topics': [svc.TRANSFER_TOPIC, _word(WALLET), _word(OTHER)]}]}
        with mock.patch.object(tasks, '_rpc', return_value=receipt):
            tasks.mark_relay_balances_stale.run(WALLET, '0x' + 'f' * 64)
        self.assertTrue(all(Balance.objects.filter(account=recipient).values_list('is_stale', flat=True)))
        self.assertTrue(all(Balance.objects.filter(account=self.account).values_list('is_stale', flat=True)))

    def test_a_receipt_moving_a_stock_token_marks_the_stored_holdings_stale(self):
        from cusd_plus.tasks import _mark_receipt_balances_stale
        gm_token = '0x' + '5' * 40
        StockHoldings.objects.create(bsc_address=WALLET, held={'TSLAon': 1.0}, blocks={}, scanned_at=timezone.now())
        receipt = {'logs': [{'address': gm_token, 'topics': [svc.TRANSFER_TOPIC, _word(WALLET), _word(STRANGER)]}]}
        with mock.patch('cusd_plus.gm_holdings.registry', return_value={'TSLAon': {'address': gm_token}}):
            _mark_receipt_balances_stale('', receipt)
        self.assertTrue(StockHoldings.objects.get(bsc_address=WALLET).is_stale)

    def test_receipt_parties_are_watched_token_transfers_only(self):
        receipt = {'logs': [
            {'address': CUSD.upper().replace('0X', '0x'), 'topics': [svc.TRANSFER_TOPIC, _word(WALLET), _word(OTHER)]},
            {'address': VAULT, 'topics': [svc.TRANSFER_TOPIC, _word(svc.ZERO_ADDRESS), _word(WALLET)]},  # mint
            {'address': STRANGER, 'topics': [svc.TRANSFER_TOPIC, _word(WALLET), _word(STRANGER)]},       # unwatched token
            {'address': CUSD, 'topics': ['0x' + 'e' * 64, _word(STRANGER), _word(STRANGER)]},           # not a Transfer
        ]}
        self.assertEqual(parties_from_receipt(receipt), {WALLET, OTHER})


class StoredStockHoldingsTests(TestCase):
    """Tu mes reads the stored complete scan at any age; the stocks screen
    re-reads it past five minutes; the wallet's own trades mark it stale."""

    def setUp(self):
        cache.clear()
        self.registry = {'TSLAon': {'address': '0x' + '5' * 40, 'decimals': 18},
                         'AAPLon': {'address': '0x' + '6' * 40, 'decimals': 18}}
        patches = [
            mock.patch('cusd_plus.gm_holdings.registry_entry', return_value=(self.registry, True)),
            mock.patch('cusd_plus.gm_holdings.registry', return_value=self.registry),
            mock.patch('cusd_plus.gm_holdings._fallback_registry', return_value={}),
            mock.patch('cusd_plus.gm_holdings._wallet_in_flight', return_value=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _scan(self, held):
        def fake(_addr, _reg, *, failures=None, blocks=None, **_k):
            if blocks is not None:
                blocks.update({s: 100 for s in self.registry})
            return dict(held)
        return mock.patch('cusd_plus.gm_holdings._scan', side_effect=fake)

    def _row(self, held, age=timedelta(0), stale=False):
        StockHoldings.objects.create(bsc_address=WALLET, held=held, blocks={'TSLAon': 90},
                                     scanned_at=timezone.now() - age, is_stale=stale)

    def test_tu_mes_reads_an_old_row_without_scanning(self):
        from cusd_plus.gm_holdings import complete_holdings
        self._row({'TSLAon': 2.0}, age=timedelta(days=3))
        with self._scan({}) as scan:
            self.assertEqual(complete_holdings(WALLET), ({'TSLAon': 2.0}, {'TSLAon': 90}))
        scan.assert_not_called()

    def test_tu_mes_scans_and_stores_when_there_is_no_row(self):
        from cusd_plus.gm_holdings import complete_holdings
        with self._scan({'AAPLon': 1.5}) as scan:
            held, blocks = complete_holdings(WALLET)
        scan.assert_called_once()
        self.assertEqual(held, {'AAPLon': 1.5})
        row = StockHoldings.objects.get(bsc_address=WALLET)
        self.assertEqual(row.held, {'AAPLon': 1.5})
        self.assertEqual(row.blocks, {'TSLAon': 100, 'AAPLon': 100})
        self.assertFalse(row.is_stale)

    def test_a_stale_row_is_rescanned(self):
        from cusd_plus.gm_holdings import complete_holdings
        self._row({'TSLAon': 2.0}, stale=True)
        with self._scan({'TSLAon': 3.0}) as scan:
            held, _ = complete_holdings(WALLET)
        scan.assert_called_once()
        self.assertEqual(held, {'TSLAon': 3.0})

    def test_the_stocks_screen_rereads_a_row_older_than_five_minutes(self):
        from cusd_plus.gm_holdings import holdings_units
        self._row({'TSLAon': 2.0}, age=timedelta(minutes=2))
        with self._scan({'TSLAon': 9.0}) as scan:
            self.assertEqual(holdings_units(WALLET), {'TSLAon': 2.0})
        scan.assert_not_called()
        StockHoldings.objects.filter(bsc_address=WALLET).update(scanned_at=timezone.now() - timedelta(minutes=6))
        with self._scan({'TSLAon': 2.0, 'AAPLon': 4.0}) as scan:          # a transfer in
            self.assertEqual(holdings_units(WALLET), {'TSLAon': 2.0, 'AAPLon': 4.0})
        scan.assert_called_once()
        self.assertEqual(StockHoldings.objects.get(bsc_address=WALLET).held,      # Tu mes sees it now
                         {'TSLAon': 2.0, 'AAPLon': 4.0})

    def test_a_trade_marks_the_row_stale_at_broadcast_and_at_confirmation(self):
        from cusd_plus.gm_holdings import drop_fresh_holdings, invalidate_holdings
        self._row({'TSLAon': 2.0})
        drop_fresh_holdings(WALLET)
        self.assertTrue(StockHoldings.objects.get(bsc_address=WALLET).is_stale)
        StockHoldings.objects.update(is_stale=False)
        invalidate_holdings(WALLET, min_block=120)
        self.assertTrue(StockHoldings.objects.get(bsc_address=WALLET).is_stale)

    def test_a_trade_confirming_mid_scan_never_leaves_a_fresh_pre_trade_row(self):
        from cusd_plus import gm_holdings
        calls = {'n': 0}

        def fake(_addr, _reg, *, failures=None, blocks=None, **_k):
            calls['n'] += 1
            if blocks is not None:
                blocks.update({s: 200 for s in self.registry})
            if calls['n'] == 1:
                gm_holdings.invalidate_holdings(WALLET)          # the trade lands during the first scan
                return {'TSLAon': 1.0}
            return {'TSLAon': 2.0}
        with mock.patch('cusd_plus.gm_holdings._scan', side_effect=fake):
            held, _ = gm_holdings.complete_holdings(WALLET)
        self.assertEqual(held, {'TSLAon': 2.0})
        row = StockHoldings.objects.get(bsc_address=WALLET)
        self.assertEqual(row.held, {'TSLAon': 2.0})
        self.assertFalse(row.is_stale)

    def test_a_trade_broadcast_after_the_in_flight_check_leaves_the_row_stale(self):
        from cusd_plus import gm_holdings
        answers = iter([False, True])        # the check before the write, then after it
        with mock.patch('cusd_plus.gm_holdings._wallet_in_flight', side_effect=lambda _k: next(answers)), \
                self._scan({'TSLAon': 1.0}):
            held, _ = gm_holdings.complete_holdings(WALLET)
        self.assertEqual(held, {'TSLAon': 1.0})                  # usable by this caller
        self.assertTrue(StockHoldings.objects.get(bsc_address=WALLET).is_stale)
        self.assertIsNone(cache.get(f'gm_hold:{WALLET}'))

    def test_a_cache_failure_after_the_write_never_leaves_a_fresh_row(self):
        from cusd_plus import gm_holdings
        with mock.patch('cusd_plus.gm_holdings._store', side_effect=ConnectionError('redis down')), \
                self._scan({'TSLAon': 1.0}), self.assertRaises(ConnectionError):
            gm_holdings.complete_holdings(WALLET)
        self.assertTrue(StockHoldings.objects.get(bsc_address=WALLET).is_stale)

    def test_a_failed_complete_scan_is_not_retried_on_every_list_read(self):
        from cusd_plus import gm_holdings
        with mock.patch('cusd_plus.gm_holdings._complete_holdings', return_value=None) as complete, \
                self._scan({'TSLAon': 1.0}):
            self.assertEqual(gm_holdings.holdings_units(WALLET), {'TSLAon': 1.0})   # the list scan answers
            cache.delete(f'gm_hold:{WALLET}')
            gm_holdings.holdings_units(WALLET)
        complete.assert_called_once()
