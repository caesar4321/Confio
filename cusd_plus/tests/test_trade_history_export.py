"""tradeHistoryCsv: a member's own confirmed trades as CSV (cusd_plus/trade_export.py)."""
import csv
import io
import json
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings
from eth_abi import encode as abi_encode

from cusd_plus import sponsor_7702, trade_export

ROUTER = '0x' + '88' * 20
STOCK = '0x' + '99' * 20
WALLET = '0x' + '44' * 20
OTHER_WALLET = '0x' + '45' * 20
BIZ_WALLET = '0x' + '46' * 20
SMART = '0x' + 'b2' * 20
T0 = datetime(2026, 11, 1, 12, 0, 0, tzinfo=dt_timezone.utc)
WAD = 10 ** 18

QUERY = '{ tradeHistoryCsv(product: "%s") { success error message filename contentType csv rowCount capped } }'


def _stock_calldata(side):
    """A v2 (perimeter-fee) router call: 2 shares at US$300 (as test_sponsor_7702)."""
    quote = (56, 123, b'\x44' * 32, STOCK, 300 * WAD, 2 * WAD, int(time.time()) + 300, side, b'\x00' * 32)
    if side == 0:
        types = [sponsor_7702.GM_QUOTE_ABI, 'bytes', 'uint256', 'uint256', 'uint256', 'uint256']
        values = [quote, b'\x55' * 65, 602 * WAD, 600 * WAD, 600 * WAD, 90]
        selector = sponsor_7702.SEL_STOCK_BUY
    else:
        types = [sponsor_7702.GM_QUOTE_ABI, 'bytes', 'uint256', 'uint256', 'uint256']
        values = [quote, b'\x55' * 65, 594 * WAD, 588 * WAD, 90]
        selector = sponsor_7702.SEL_STOCK_SELL
    return json.dumps([{'to': ROUTER, 'value': '0', 'data': '0x' + selector + abi_encode(types, values).hex()}])


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def _header(text):
    return text.splitlines()[0].split(',')


@override_settings(CUSD_PLUS_STOCK_ROUTER_ADDRESS=ROUTER, CUSD_PLUS_STOCK_TRADING_ENABLED=False)
class TradeHistoryExportTests(TestCase):
    def setUp(self):
        from users.models import Account, User

        self.user = User.objects.create(username='exporter', firebase_uid='exporter')
        self.other = User.objects.create(username='stranger', firebase_uid='stranger')
        self.account = Account.objects.create(user=self.user, account_type='personal', account_index=0,
                                              bsc_address=WALLET)
        Account.objects.create(user=self.other, account_type='personal', account_index=0, bsc_address=OTHER_WALLET)
        self.ctx = {'user_id': self.user.id, 'account_type': 'personal', 'account_index': 0, 'business_id': None}
        self.tx = 0
        for target, value in (('cusd_plus.gm_holdings.registry', {'NVDAon': {'address': STOCK, 'decimals': 18}}),
                              ('cusd_plus.gm_holdings._fallback_registry', {}),
                              ('cusd_plus.crypto_policy.live_fee_bps', 90)):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    # ── helpers ──
    def _execute(self, product, user=None, ctx='default'):
        from config.schema import schema

        context = SimpleNamespace(user=user or self.user, META={})
        jwt = mock.patch('users.jwt_context.get_jwt_business_context_with_validation',
                         return_value=self.ctx if ctx == 'default' else ctx)
        with jwt as patched:
            result = schema.execute(QUERY % product, context_value=context)
        self.assertIsNone(result.errors)
        for call in patched.call_args_list:
            self.assertFalse(call.kwargs.get('allow_smart'), 'a smart context must stay refused')
        return result.data['tradeHistoryCsv']

    def _hash(self):
        self.tx += 1
        return '0x' + format(self.tx, '064x')

    def _batch(self, kind, *, wallet=WALLET, user=None, status='confirmed', calls='[]', at=T0, block=100):
        from blockchain.models import SponsoredBatch

        return SponsoredBatch.objects.create(
            user=user or self.user, user_bsc_address=wallet, kind=kind, num_calls=1, calls_json=calls,
            tx_hash=self._hash(), status=status, gas_limit=1, max_fee_wei=1, created_at=at, block_number=block)

    def _settle(self, batch, amount, status='CONFIRMED'):
        from users.models_unified import UnifiedTransactionTable

        return UnifiedTransactionTable.objects.create(
            sponsored_batch=batch, transaction_type='send', amount=amount, token_type='CUSD_PLUS',
            amount_denomination='USD_VALUE', status=status, transaction_hash=batch.tx_hash,
            sender_user=self.user, sender_type='user', transaction_date=batch.created_at)

    def _fee(self, batch, direction, gross, fee, log_index=0):
        from conversion.models import CusdFeeEvent

        CusdFeeEvent.objects.create(tx_hash=batch.tx_hash, log_index=log_index, block_number=batch.block_number,
                                    direction=direction, event_type='x', gross_wei=gross, fee_wei=fee,
                                    net_wei=gross - fee, fee_bps=90)

    def _market(self, coin='BTC', dex=''):
        from blockchain.models import PerpMarket

        return PerpMarket.objects.get_or_create(coin=coin, defaults=dict(
            dex=dex, asset_id=0, sz_decimals=5, max_leverage=40, collateral='USDC', synced_at=T0))[0]

    def _position(self, state, *, user=None, wallet=WALLET, opened=True, batch_status='confirmed', **fields):
        from blockchain.models import PerpPosition

        open_batch = self._batch('perps_open', wallet=wallet, user=user, status=batch_status)
        return PerpPosition.objects.create(
            user=user or self.user, wallet=wallet, market=self._market(), side='long', leverage=5,
            margin_usd=Decimal('50'), state=state, open_batch=open_batch,
            opened_at=T0 if opened else None, **fields)

    # ── Futuros ──
    def test_futuros_columns_exact_values_and_exclusions(self):
        from blockchain.models import PerpMarginChange

        done = self._position(
            'done', entry_avg_px=Decimal('95000.5'), size=Decimal('0.00263'), close_avg_px=Decimal('96000'),
            closed_at=T0 + timedelta(hours=2), realized_pnl=Decimal('2.62737'), funding=Decimal('-0.0123'),
            venue_fees=Decimal('0.2245'), returned_usd=Decimal('59.1'), done_at=T0 + timedelta(hours=3),
            flow={'size_initial': '0.00263'})
        PerpMarginChange.objects.create(position=done, direction='add', amount_usd=Decimal('10'), state='open')
        PerpMarginChange.objects.create(position=done, direction='add', amount_usd=Decimal('5'), state='failed')
        # The open one (one live position per wallet; `done` is terminal).
        live = self._position('open', entry_avg_px=Decimal('94000'), size=Decimal('0.001'))
        live.opened_at = T0 + timedelta(days=1)
        live.save(update_fields=['opened_at'])
        # Never trades: a quote, a failed open, a refund before the open, an unconfirmed open batch.
        self._position('quoted', opened=False)
        self._position('failed', opened=False)
        self._position('done', opened=False, returned_usd=Decimal('49'), done_at=T0)  # refunded, never opened
        self._position('done', batch_status='reverted')
        # Someone else's position.
        self._position('done', user=self.other, wallet=OTHER_WALLET)

        out = self._execute('futuros')
        self.assertTrue(out['success'])
        self.assertEqual(_header(out['csv']), trade_export.FUTUROS_COLUMNS)
        self.assertEqual(out['contentType'], 'text/csv; charset=utf-8')
        self.assertTrue(out['filename'].startswith('confio_futuros_trades_'))
        rows = _rows(out['csv'])
        self.assertEqual([r['position_id'] for r in rows], [str(live.id), str(done.id)], 'newest first')
        self.assertEqual((out['rowCount'], out['capped']), (2, False))

        opened = rows[0]
        self.assertEqual((opened['status'], opened['entry_price'], opened['size']), ('open', '94000', '0.001'))
        self.assertEqual((opened['closed_at'], opened['funding_usd'], opened['result_usd']), ('', '', ''))

        row = rows[1]
        self.assertEqual(row['market'], 'BTC')
        self.assertEqual(row['asset_class'], 'crypto')
        self.assertEqual((row['side'], row['leverage'], row['status']), ('long', '5', 'closed'))
        self.assertEqual((row['margin_usd'], row['margin_added_usd'], row['margin_adds']), ('50', '10', '1'))
        self.assertEqual(row['put_in_usd'], '60')
        self.assertEqual((row['entry_price'], row['size'], row['close_price']), ('95000.5', '0.00263', '96000'))
        self.assertEqual(row['opened_at'], '2026-11-01T12:00:00+00:00')
        self.assertEqual(row['closed_at'], '2026-11-01T14:00:00+00:00')
        self.assertEqual((row['realized_pnl_usd'], row['funding_usd'], row['venue_fees_usd']),
                         ('2.62737', '-0.0123', '0.2245'))
        self.assertEqual((row['returned_usd'], row['result_usd'], row['liquidation']), ('59.1', '-0.9', ''))
        self.assertEqual(row['returned_at'], '2026-11-01T15:00:00+00:00')

    def test_futuros_liquidation_is_marked(self):
        self._position('done', liquidation='book', realized_pnl=Decimal('-50'), returned_usd=Decimal('0'),
                       closed_at=T0, done_at=T0)
        row = _rows(self._execute('futuros')['csv'])[0]
        self.assertEqual((row['status'], row['liquidation'], row['returned_usd'], row['result_usd']),
                         ('liquidated', 'book', '0', '-50'))

    def test_futuros_is_personal_only(self):
        from users.models import Account, Business

        biz = Business.objects.create(name='Bodega', category='other')
        Account.objects.create(user=self.user, business=biz, account_type='business', account_index=0,
                               bsc_address=BIZ_WALLET)
        out = self._execute('futuros', ctx={'account_type': 'business', 'business_id': biz.id, 'account_index': 0})
        self.assertEqual((out['success'], out['error']), (False, 'personal_only'))
        self.assertIn('cuenta personal', out['message'])

    # ── stocks ──
    def test_stocks_columns_exact_values_fee_and_exclusions(self):
        buy = self._batch('stock_buy', calls=_stock_calldata(0), at=T0)
        self._settle(buy, '605.4')
        self._fee(buy, 'exit', 6054 * WAD // 10, 54 * WAD // 10)          # gross 605.4 = usd: fee 5.4
        sell = self._batch('stock_sell', calls=_stock_calldata(1), at=T0 + timedelta(hours=1), block=101)
        self._settle(sell, '594.6')
        self._fee(sell, 'entry', 600 * WAD, 54 * WAD // 10)                # net 594.6 = usd: fee 5.4
        unmatched = self._batch('stock_buy', calls=_stock_calldata(0), at=T0 - timedelta(hours=1))
        self._settle(unmatched, '601.8')
        self._fee(unmatched, 'exit', 700 * WAD, WAD)                       # does not reconcile: blank
        # Excluded: not final, reverted; another member's trade.
        self._settle(self._batch('stock_buy', status='sent', calls=_stock_calldata(0)), '605.4')
        self._batch('stock_sell', status='reverted', calls=_stock_calldata(1))
        self._batch('stock_buy', wallet=OTHER_WALLET, user=self.other, calls=_stock_calldata(0))

        out = self._execute('stocks')
        self.assertEqual(_header(out['csv']), trade_export.STOCK_COLUMNS)
        rows = _rows(out['csv'])
        self.assertEqual([r['trade_id'] for r in rows],
                         [f'batch-{sell.id}', f'batch-{buy.id}', f'batch-{unmatched.id}'])
        s, b, u = rows
        self.assertEqual((b['account'], b['side'], b['ticker'], b['symbol']), ('personal', 'buy', 'NVDA', 'NVDAon'))
        self.assertEqual((b['shares'], b['quote_price_usd'], b['usd'], b['fee_usd']), ('2', '300', '605.4', '5.4'))
        self.assertEqual((b['tx_hash'], b['block_number'], b['executed_at']),
                         (buy.tx_hash, '100', '2026-11-01T12:00:00+00:00'))
        self.assertEqual((s['side'], s['shares'], s['usd'], s['fee_usd']), ('sell', '2', '594.6', '5.4'))
        self.assertEqual((u['usd'], u['fee_usd']), ('601.8', ''))

    def test_stocks_include_own_cuenta_inteligente_trades_only(self):
        from inbox.models import SmartAccountTrade
        from smart_account.models import SmartAccount, SmartAccountEvent

        SmartAccount.all_objects.create(owner_user=self.user, owner_account=self.account,
                                        contract_address=SMART, status='active')
        when = T0 + timedelta(days=2)
        event = SmartAccountEvent.objects.create(address=SMART, tx_hash='0x' + 'cd' * 32, log_index=3,
                                                 name='Traded', block_number=555, block_time=when, args={})
        trade = SmartAccountTrade.objects.create(event=event, address=SMART, symbol='NVDAon', kind='stock_buy',
                                                 units=Decimal('0.5'), usd=Decimal('150.25'), traded_at=when,
                                                 block_number=555)
        unreadable = SmartAccountEvent.objects.create(address=SMART, tx_hash='0x' + 'ce' * 32, log_index=0,
                                                      name='Traded', block_number=556, block_time=when, args={})
        SmartAccountTrade.objects.create(event=unreadable, address=SMART, symbol='?a1', kind='stock_buy',
                                         units=0, usd=None, traded_at=when, block_number=556)
        rows = _rows(self._execute('stocks')['csv'])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], {
            'trade_id': f'smart-{trade.id}', 'account': 'smart', 'executed_at': '2026-11-03T12:00:00+00:00',
            'side': 'buy', 'ticker': 'NVDA', 'symbol': 'NVDAon', 'shares': '0.5', 'quote_price_usd': '',
            'usd': '150.25', 'fee_usd': '', 'tx_hash': '0x' + 'cd' * 32, 'block_number': '555'})
        # Another member never sees it.
        from users.models import Account
        other = Account.objects.get(user=self.other)
        self.assertIsNotNone(other)
        out = self._execute('stocks', user=self.other,
                            ctx={'account_type': 'personal', 'account_index': 0, 'business_id': None})
        self.assertEqual(_rows(out['csv']), [])

    def test_business_owner_exports_business_wallet_employee_never(self):
        from users.models import Account, Business
        from users.models_employee import BusinessEmployee

        biz = Business.objects.create(name='Bodega', category='other')
        Account.objects.create(user=self.user, business=biz, account_type='business', account_index=0,
                               bsc_address=BIZ_WALLET)
        biz_buy = self._batch('stock_buy', wallet=BIZ_WALLET, calls=_stock_calldata(0))
        self._settle(biz_buy, '605.4')
        self._settle(self._batch('stock_buy', calls=_stock_calldata(0)), '605.4')   # personal: not in it
        ctx = {'account_type': 'business', 'business_id': biz.id, 'account_index': 0}
        rows = _rows(self._execute('stocks', ctx=ctx)['csv'])
        self.assertEqual([(r['trade_id'], r['account']) for r in rows], [(f'batch-{biz_buy.id}', 'business')])

        BusinessEmployee.objects.create(user=self.other, business=biz, role='admin')
        out = self._execute('stocks', user=self.other, ctx=ctx)
        self.assertEqual((out['success'], out['error'], out['csv']), (False, 'owner_only', None))
        out = self._execute('crypto', user=self.other, ctx=ctx)
        self.assertEqual(out['error'], 'owner_only')

    def test_smart_context_and_anonymous_are_refused(self):
        # get_jwt_business_context_with_validation answers None for a smart
        # context unless allow_smart=True (never passed: asserted in _execute).
        out = self._execute('stocks', ctx=None)
        self.assertEqual((out['success'], out['error']), (False, 'account_not_supported'))
        self.assertIn('cuenta personal', out['message'])
        from django.contrib.auth.models import AnonymousUser
        out = self._execute('stocks', user=AnonymousUser())
        self.assertEqual(out['error'], 'auth_required')
        self.assertEqual(self._execute('options')['error'], 'bad_product')

    def test_no_geo_gate(self):
        """A member in a blocked country still gets their past trades."""
        self._settle(self._batch('stock_buy', calls=_stock_calldata(0)), '605.4')
        with mock.patch('security.geo.country_of', return_value='US'):
            out = self._execute('stocks')
        self.assertEqual(out['rowCount'], 1)

    # ── crypto ──
    def test_crypto_columns_exact_values_and_exclusions(self):
        from blockchain.models import CryptoTrade

        buy = self._batch('crypto_buy', at=T0)
        CryptoTrade.objects.create(batch=buy, wallet=WALLET, symbol='BTCB', kind='crypto_buy',
                                   units=Decimal('0.000523411'), usd=Decimal('50.45'), traded_at=T0)
        self._settle(buy, '50.45')
        self._fee(buy, 'exit', 5045 * WAD // 100, 45 * WAD // 100)
        sell = self._batch('crypto_sell', at=T0 + timedelta(minutes=5))
        CryptoTrade.objects.create(batch=sell, wallet=WALLET, symbol='XAUT', kind='crypto_sell',
                                   units=Decimal('0.01'), usd=Decimal('39.64'), traded_at=sell.created_at)
        legacy = self._batch('crypto_buy', at=T0 - timedelta(days=1))   # no CryptoTrade: no units
        self._settle(legacy, '20')
        failed = self._batch('crypto_buy', status='noop_failed')
        CryptoTrade.objects.create(batch=failed, wallet=WALLET, symbol='BTCB', kind='crypto_buy',
                                   units=Decimal('1'), usd=Decimal('1'), traded_at=T0)
        other = self._batch('crypto_buy', wallet=OTHER_WALLET, user=self.other)
        CryptoTrade.objects.create(batch=other, wallet=OTHER_WALLET, symbol='BTCB', kind='crypto_buy',
                                   units=Decimal('1'), usd=Decimal('1'), traded_at=T0)

        out = self._execute('crypto')
        self.assertEqual(_header(out['csv']), trade_export.CRYPTO_COLUMNS)
        rows = _rows(out['csv'])
        self.assertEqual([r['trade_id'] for r in rows],
                         [f'batch-{sell.id}', f'batch-{buy.id}', f'batch-{legacy.id}'])
        s, b, legacy_row = rows
        self.assertEqual((b['side'], b['symbol'], b['ticker'], b['category']), ('buy', 'BTCB', 'BTC', 'crypto'))
        self.assertEqual((b['units'], b['usd'], b['fee_usd'], b['tx_hash']),
                         ('0.000523411', '50.45', '0.45', buy.tx_hash))
        self.assertEqual((s['side'], s['symbol'], s['category'], s['units'], s['usd'], s['fee_usd']),
                         ('sell', 'XAUT', 'metal', '0.01', '39.64', ''))
        self.assertEqual((legacy_row['units'], legacy_row['usd'], legacy_row['symbol']), ('', '20', ''))

    # ── shape ──
    def test_empty_exports_have_the_header(self):
        for product, columns in (('futuros', trade_export.FUTUROS_COLUMNS), ('stocks', trade_export.STOCK_COLUMNS),
                                 ('crypto', trade_export.CRYPTO_COLUMNS)):
            out = self._execute(product)
            self.assertTrue(out['success'], product)
            self.assertEqual(out['csv'], ','.join(columns) + '\n')
            self.assertEqual((out['rowCount'], out['capped']), (0, False))

    def test_row_cap_keeps_the_newest(self):
        from blockchain.models import CryptoTrade

        batches = []
        for i in range(4):
            batch = self._batch('crypto_buy', at=T0 + timedelta(minutes=i))
            CryptoTrade.objects.create(batch=batch, wallet=WALLET, symbol='BTCB', kind='crypto_buy',
                                       units=Decimal('1'), usd=Decimal(i + 1), traded_at=batch.created_at)
            batches.append(batch)
        with mock.patch.object(trade_export, 'MAX_ROWS', 3):
            out = self._execute('crypto')
        self.assertTrue(out['capped'])
        self.assertEqual(out['rowCount'], 3)
        self.assertEqual([r['usd'] for r in _rows(out['csv'])], ['4', '3', '2'])
        rows, capped = trade_export.futuros_rows(self.user, WALLET, limit=3)
        self.assertEqual((rows, capped), ([], False))

    # ── audit fixes ──
    def test_address_alone_is_not_ownership(self):
        """A batch on this wallet's address signed by someone else (an address
        re-registered after its account was deleted) is never exported."""
        from blockchain.models import CryptoTrade

        foreign = self._batch('stock_buy', user=self.other, calls=_stock_calldata(0))
        self._settle(foreign, '605.4')
        foreign_swap = self._batch('crypto_buy', user=self.other)
        CryptoTrade.objects.create(batch=foreign_swap, wallet=WALLET, symbol='BTCB', kind='crypto_buy',
                                   units=Decimal('1'), usd=Decimal('1'), traded_at=T0)
        own = self._batch('stock_buy', calls=_stock_calldata(0))
        self._settle(own, '605.4')
        self.assertEqual([r['trade_id'] for r in _rows(self._execute('stocks')['csv'])], [f'batch-{own.id}'])
        self.assertEqual(_rows(self._execute('crypto')['csv']), [])

    def test_business_batches_signed_by_owner_or_its_employees_only(self):
        from users.models import Account, Business, User
        from users.models_employee import BusinessEmployee

        biz = Business.objects.create(name='Bodega', category='other')
        Account.objects.create(user=self.user, business=biz, account_type='business', account_index=0,
                               bsc_address=BIZ_WALLET)
        cashier = User.objects.create(username='cashier', firebase_uid='cashier')
        employee = BusinessEmployee.objects.create(user=cashier, business=biz, role='cashier')
        by_owner = self._batch('stock_buy', wallet=BIZ_WALLET, calls=_stock_calldata(0))
        by_cashier = self._batch('stock_sell', wallet=BIZ_WALLET, user=cashier, calls=_stock_calldata(1),
                                 at=T0 + timedelta(hours=1))
        self._batch('stock_buy', wallet=BIZ_WALLET, user=self.other, calls=_stock_calldata(0))
        employee.soft_delete()   # a past employee's trades stay the business's
        ctx = {'account_type': 'business', 'business_id': biz.id, 'account_index': 0}
        rows = _rows(self._execute('stocks', ctx=ctx)['csv'])
        self.assertEqual([r['trade_id'] for r in rows], [f'batch-{by_cashier.id}', f'batch-{by_owner.id}'])

    def test_checksum_stored_address_is_found(self):
        from eth_utils import to_checksum_address

        batch = self._batch('stock_buy', wallet=to_checksum_address(WALLET), calls=_stock_calldata(0))
        self._settle(batch, '605.4')
        self.assertEqual(self._execute('stocks')['rowCount'], 1)

    def test_text_cells_cannot_be_formulas(self):
        from inbox.models import SmartAccountTrade
        from smart_account.models import SmartAccount, SmartAccountEvent

        SmartAccount.all_objects.create(owner_user=self.user, owner_account=self.account,
                                        contract_address=SMART, status='active')
        for i, symbol in enumerate(('=HYPERLINK("x")', '+1', '-1', '@SUM(A1)', '\tX', 'OKon')):
            event = SmartAccountEvent.objects.create(address=SMART, tx_hash='0x' + format(i, '064x'), log_index=0,
                                                     name='Traded', block_number=10 + i, block_time=T0, args={})
            SmartAccountTrade.objects.create(event=event, address=SMART, symbol=symbol, kind='stock_sell',
                                             units=Decimal('-0.5'), usd=Decimal('-3'), traded_at=T0 + timedelta(i),
                                             block_number=10 + i)
        rows = _rows(self._execute('stocks')['csv'])
        self.assertEqual([r['symbol'] for r in reversed(rows)],
                         ["'=HYPERLINK(\"x\")", "'+1", "'-1", "'@SUM(A1)", "'\tX", 'OKon'])
        self.assertEqual(rows[0]['ticker'], 'OK')
        self.assertEqual((rows[0]['shares'], rows[0]['usd']), ('-0.5', '-3'), 'numbers untouched')

    def test_malformed_stored_size_is_blank_not_a_failed_export(self):
        position = self._position('done', size=Decimal('0.002'), flow={'size_initial': 'abc'},
                                  returned_usd=Decimal('50'), done_at=T0)
        out = self._execute('futuros')
        self.assertTrue(out['success'])
        row = _rows(out['csv'])[0]
        self.assertEqual((row['position_id'], row['size']), (str(position.id), ''))
        negative = self._position('done', flow={'size_initial': '-0.003'}, returned_usd=Decimal('50'), done_at=T0)
        rows = {r['position_id']: r for r in _rows(self._execute('futuros')['csv'])}
        self.assertEqual(rows[str(negative.id)]['size'], '0.003')

    def test_number_formatting(self):
        self.assertEqual(trade_export._num(Decimal('123456789012345678901234567890.123456789012345678')),
                         '123456789012345678901234567890.123456789012345678')
        self.assertEqual(trade_export._num(Decimal('1E-7')), '0.0000001')
        self.assertEqual(trade_export._num(Decimal('1200.500000000000000000')), '1200.5')
        self.assertEqual(trade_export._num(Decimal('0E-18')), '0')
        self.assertEqual(trade_export._num(None), '')
