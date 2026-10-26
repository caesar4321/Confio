"""Futuros money flow: signing, Relay binding, the exact-batch relay policy,
Hyperliquid action forwarding, reconciliation, sweep reservation, ledgers."""
import copy
import json
import time
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from eth_account import Account
from eth_account.messages import encode_typed_data

from cusd_plus import hl_signing, perps_flow, perps_relay

FIXTURE = json.loads((Path(__file__).parent / 'fixtures' / 'relay_hyperliquid_quotes.json').read_text())
QUOTE_WALLET = '0x1111111111111111111111111111111111111111'
NOW = 1792970000  # 2026-10-25, inside the recorded quotes' deadlines
SDK_KEY = '0x0123456789012345678901234567890123456789012345678901234567890123'
CUSD = '0x' + '22' * 20
VAULT = '0x' + '11' * 20
WAD = 10 ** 18

OPEN_SETTINGS = dict(
    PERPS_ENABLED=True, PERPS_TRADING_ENABLED=True, PERPS_OPEN_ENABLED=True, PERPS_IOS_ENABLED=True,
    PERPS_ALLOWED_USER_IDS='', PERPS_BLOCKED_COUNTRIES='US,CA,GB,BE', PERPS_EXCLUDED_MARKETS='',
    CUSD_PLUS_7702_ENABLED=True, CUSD_PLUS_BATCH_DELEGATE_ADDRESS='0x' + '7a' * 20,
    CUSD_VAULT_ADDRESS=CUSD, CUSD_PLUS_VAULT_ADDRESS=VAULT,
)


class FakeRelay:
    """RelayClient stand-in answering with the recorded quotes."""

    def __init__(self, out=None, back=None):
        self.out = out or copy.deepcopy(FIXTURE['out'])
        self.back = back or copy.deepcopy(FIXTURE['back'])
        self.posted = []

    def _request(self, method, path, *, body=None, params=None):
        self.posted.append((method, path, body, params))
        if path == '/quote/v2':
            return copy.deepcopy(self.out if body['originChainId'] == 56 else self.back)
        if path == '/authorize':
            return {'message': 'ok'}
        raise AssertionError(path)


def _wallet_key():
    return Account.from_key(SDK_KEY)


def _sign_typed(typed: dict) -> dict:
    sig = _wallet_key().sign_message(encode_typed_data(full_message=typed))
    return {'r': hex(sig.r), 's': hex(sig.s), 'v': sig.v}


class SigningTests(SimpleTestCase):
    def test_sdk_vectors(self):
        order = {'type': 'order', 'orders': [{'a': 4, 'b': True, 'p': '1670.1', 's': '0.0147', 'r': False,
                                              't': {'limit': {'tif': 'Ioc'}}}], 'grouping': 'na'}
        self.assertEqual('0x' + hl_signing.action_hash(order, 1677777606040).hex(),
                         '0x0fcbeda5ae3c4950a548021552a4fea2226858c4453571bf3f24ba017eac2908')
        gtc = {'type': 'order', 'orders': [{'a': 1, 'b': True, 'p': '100', 's': '100', 'r': False,
                                            't': {'limit': {'tif': 'Gtc'}}}], 'grouping': 'na'}
        sig = _sign_typed(hl_signing.l1_typed_data(gtc, 0))
        self.assertEqual(sig['r'], '0xd65369825a9df5d80099e513cce430311d7d26ddf477f5b3a33d2806b100d78e')
        self.assertEqual(hl_signing.recover_action_signer(gtc, 0, sig), _wallet_key().address.lower())

    def test_user_signed_recovery_and_refusals(self):
        action = {'type': 'sendAsset', 'signatureChainId': '0xa4b1', 'hyperliquidChain': 'Mainnet',
                  'destination': perps_relay.hl_depository(), 'sourceDex': '', 'destinationDex': '',
                  'token': perps_relay.HL_USDC_TOKEN, 'amount': '20', 'fromSubAccount': '', 'nonce': 5}
        sig = _sign_typed(hl_signing.user_signed_typed_data(action))
        self.assertEqual(hl_signing.recover_action_signer(action, 5, sig), _wallet_key().address.lower())
        tampered = dict(action, amount='21')
        self.assertNotEqual(hl_signing.recover_action_signer(tampered, 5, sig), _wallet_key().address.lower())
        with self.assertRaises(hl_signing.SignatureError):
            hl_signing.recover_action_signer({'type': 'usdSend'}, 5, sig)
        with self.assertRaises(hl_signing.SignatureError):
            hl_signing.recover_action_signer(action, 5, {'r': '0x1', 's': '0x1', 'v': 30})


@mock.patch('cusd_plus.perps_relay.time.time', return_value=NOW)
class RelayBindingTests(SimpleTestCase):
    def test_recorded_quotes_bind_both_directions(self, *_):
        out = perps_relay.quote_open(QUOTE_WALLET, 20 * WAD, client=FakeRelay())
        self.assertEqual(out['depository'], perps_relay.bsc_depository())
        self.assertEqual(out['deposit_data'],
                         perps_relay.deposit_calldata(QUOTE_WALLET, 20 * WAD, out['order_id']))
        back = perps_relay.quote_return(QUOTE_WALLET, 20 * 10 ** 8, client=FakeRelay())
        self.assertEqual(back['send_asset']['destination'], perps_relay.hl_depository())
        self.assertEqual(back['mapping']['id'], back['order_id'])
        self.assertEqual(back['send_asset']['nonce'], back['nonce'])

    def test_the_order_id_is_proven_to_be_these_terms_signed_by_relays_solver(self, *_):
        out = copy.deepcopy(FIXTURE['out'])
        self.assertEqual(perps_relay.order_id(out['protocol']['v2']['orderData']), out['protocol']['v2']['orderId'])
        # Rewrite the payout everywhere it is shown, keeping Relay's real order id: refused.
        out['details']['recipient'] = '0x' + '99' * 20
        out['protocol']['v2']['orderData']['output']['payments'][0]['recipient'] = '0x' + '99' * 20
        with self.assertRaisesRegex(perps_relay.RelayError, 'does not match'):
            perps_relay.authenticate_order(out['protocol']['v2'])
        # A self-made order hashed correctly but not signed by Relay's solver: refused.
        forged = copy.deepcopy(FIXTURE['out']['protocol']['v2'])
        forged['orderData']['output']['payments'][0]['expectedAmount'] = str(10 ** 30)
        forged['orderId'] = perps_relay.order_id(forged['orderData'])
        with self.assertRaisesRegex(perps_relay.RelayError, 'not signed'):
            perps_relay.authenticate_order(forged)

    def test_redirected_recipient_or_extra_calls_are_refused(self, *_):
        for mutate in (
            lambda q: q['details'].__setitem__('recipient', '0x' + '99' * 20),
            lambda q: q['protocol']['v2']['orderData']['output']['payments'][0].__setitem__('recipient', '0x' + '99' * 20),
            lambda q: q['protocol']['v2']['orderData']['output'].__setitem__('calls', [{'to': '0x1'}]),
            lambda q: q['protocol']['v2']['paymentDetails'].__setitem__('depository', '0x' + '98' * 20),
            lambda q: q['details']['currencyOut'].__setitem__('minimumAmount', '1'),
        ):
            quote = copy.deepcopy(FIXTURE['out'])
            mutate(quote)
            with self.assertRaises(perps_relay.RelayError):
                perps_relay.quote_open(QUOTE_WALLET, 20 * WAD, client=FakeRelay(out=quote))

    def test_withdrawal_must_send_to_relay_with_the_mapped_nonce(self, *_):
        for mutate in (
            lambda q: q['steps'][1]['items'][0]['data']['action']['parameters'].__setitem__('destination', '0x' + '99' * 20),
            lambda q: q['steps'][1]['items'][0]['data']['action']['parameters'].__setitem__('nonce', 1),
            lambda q: q['steps'][1]['items'][0]['data']['action']['parameters'].__setitem__('amount', '25.000000'),
            lambda q: q['steps'][0]['items'][0]['data']['sign']['value'].__setitem__('depositor', '0x' + '99' * 20),
        ):
            quote = copy.deepcopy(FIXTURE['back'])
            mutate(quote)
            with self.assertRaises(perps_relay.RelayError):
                perps_relay.quote_return(QUOTE_WALLET, 20 * 10 ** 8, client=FakeRelay(back=quote))


class PricingTests(SimpleTestCase):
    def test_wire_prices_respect_hyperliquid_tick_rules(self):
        self.assertEqual(perps_flow.wire_price(Decimal('2650.123'), 4, up=True), '2650.2')
        self.assertEqual(perps_flow.wire_price(Decimal('98000.4'), 5, up=True), '98001')
        self.assertEqual(perps_flow.wire_price(Decimal('123456.7'), 3, up=False), '123456')
        self.assertEqual(perps_flow.wire_price(Decimal('0.00012345'), 0, up=False), '0.000123')

    def test_book_walk_and_impact(self):
        book = {'levels': [[{'px': '99', 'sz': '1'}, {'px': '98', 'sz': '5'}],
                           [{'px': '101', 'sz': '1'}, {'px': '102', 'sz': '5'}]]}
        avg, mid, _ = perps_flow.walk_book(book, True, Decimal('2'))
        self.assertEqual((avg, mid), (Decimal('101.5'), Decimal('100')))
        self.assertEqual(perps_flow.impact_bps(avg, mid), 150)
        with self.assertRaises(perps_flow.FlowError):
            perps_flow.walk_book(book, True, Decimal('100'))

    def test_liquidation_estimate_is_on_the_losing_side(self):
        long_liq = perps_flow.estimate_liquidation_px(Decimal('100'), Decimal('1'), Decimal('20'), 'long', 20)
        short_liq = perps_flow.estimate_liquidation_px(Decimal('100'), Decimal('1'), Decimal('20'), 'short', 20)
        self.assertTrue(Decimal('75') < long_liq < Decimal('100'))
        self.assertTrue(Decimal('100') < short_liq < Decimal('125'))


def _market(**kw):
    from blockchain.models import PerpMarket
    from django.utils import timezone

    fields = dict(coin='BTC', dex='', asset_id=0, sz_decimals=5, max_leverage=40, collateral='USDC',
                  synced_at=timezone.now())
    fields.update(kw)
    return PerpMarket.objects.create(**fields)


@override_settings(**OPEN_SETTINGS)
@mock.patch('cusd_plus.perps_relay.time.time', return_value=NOW)
@mock.patch('cusd_plus.perps_flow.time.time', return_value=NOW)
class OpenFlowTests(TestCase):
    def setUp(self):
        from users.models import Account, User

        self.user = User.objects.create(username='perpsflow', firebase_uid='perpsflow')
        self.wallet = QUOTE_WALLET
        Account.objects.filter(user=self.user).update(bsc_address=self.wallet)
        self.btc = _market()
        from cusd_plus import perps_risk
        perps_risk.acknowledge(self.user)

    def _prepare(self, margin='20.18', leverage=5, new_account=False):
        from cusd_plus.crypto_policy import DOLLAR
        with mock.patch('cusd_plus.perps_flow.RELAY', create=True), \
                mock.patch('cusd_plus.perps_relay.RelayClient', return_value=FakeRelay()), \
                mock.patch('cusd_plus.perps_flow._dollar_for', return_value=DOLLAR), \
                mock.patch('cusd_plus.perps_flow._new_account', return_value=new_account), \
                mock.patch('cusd_plus.vault.erc20_balance_raw', return_value=100 * WAD), \
                mock.patch('cusd_plus.crypto_policy.expected_exit_usdt',
                           return_value=(int(Decimal('20.18') * WAD), 20 * WAD)), \
                mock.patch('security.geo.phone_country_of', return_value='VE'):
            return perps_flow.prepare_open(self.user, self.wallet, {}, 'BTC', 'long', leverage, margin)

    def test_open_issues_exit_plus_relay_deposit_and_the_relay_accepts_only_it(self, *_):
        from cusd_plus import sponsor_7702

        plan = self._prepare()
        calls = plan['calls']
        self.assertEqual(len(calls), 3)
        # Relay's raw signed quote travels with the plan: the app proves the order itself.
        v2 = plan['relay_quote']['protocol']['v2']
        self.assertEqual(perps_relay.authenticate_order(v2), v2['orderId'])
        self.assertTrue(calls[2]['data'].endswith(v2['orderId'][2:]))
        self.assertEqual(calls[0]['to'], CUSD)
        self.assertEqual(calls[0]['data'][2:10], sponsor_7702.SEL_CUSD_REDEEM)
        self.assertEqual(calls[2]['to'], perps_relay.bsc_depository())
        self.assertEqual(sponsor_7702.classify_calls_kind(calls), 'perps_open')
        self.assertEqual(plan['position'].state, 'quoted')
        self.assertEqual(Decimal(plan['costs']['exit_fee_usd']), Decimal('0.18'))

        sponsor_7702.validate_policy(calls, self.user, self.wallet)  # exact: accepted
        tampered = copy.deepcopy(calls)
        tampered[0]['data'] = tampered[0]['data'][:-40] + '99' * 20  # exit to someone else
        with self.assertRaises(sponsor_7702.PolicyError):
            sponsor_7702.validate_policy(tampered, self.user, self.wallet)
        other = copy.deepcopy(calls[1:])
        with self.assertRaises(sponsor_7702.PolicyError):
            sponsor_7702.validate_policy(other, self.user, self.wallet)  # retry shape on a quoted open

    def test_minimums_one_live_position_per_market_and_gates(self, *_):
        with self.assertRaises(perps_flow.FlowError) as ctx:
            self._prepare(margin='9.99')
        self.assertEqual(ctx.exception.code, 'margin_too_small')
        with self.assertRaises(perps_flow.FlowError) as ctx:
            self._prepare(margin='11.00', new_account=True)
        self.assertEqual(ctx.exception.code, 'margin_too_small', 'first open pays the $1.20 charge')
        with self.assertRaises(perps_flow.FlowError):
            self._prepare(leverage=41)
        plan = self._prepare()
        plan['position'].state = 'open'
        plan['position'].save()
        with self.assertRaises(perps_flow.FlowError) as ctx:
            self._prepare()
        self.assertEqual(ctx.exception.code, 'position_exists')

    def test_requote_cancels_the_unsigned_quote(self, *_):
        first = self._prepare()
        second = self._prepare()
        first['position'].refresh_from_db()
        self.assertEqual(first['position'].state, 'cancelled')
        self.assertEqual(second['position'].state, 'quoted')

    def test_broadcast_and_receipts_move_the_position(self, *_):
        from blockchain.models import SponsoredBatch

        plan = self._prepare()
        batch = SponsoredBatch.objects.create(
            user=self.user, user_bsc_address=self.wallet, kind='perps_open', calls_json=json.dumps(plan['calls']),
            num_calls=len(plan['calls']), gas_limit=1, max_fee_wei=1,
            tx_hash='0x' + 'ab' * 32, status='sent', client_request_id=plan['request_id'])
        perps_flow.link_signed(batch)  # inside the signed row's transaction, before broadcast
        position = plan['position']
        position.refresh_from_db()
        self.assertEqual((position.state, position.open_batch_id), ('bridging', batch.id))
        batch.status = 'noop_failed'
        batch.save()
        perps_flow.on_receipt(batch, None)
        position.refresh_from_db()
        self.assertEqual((position.state, position.open_batch_id), ('quoted', None),
                         'mined but not executed: the unexpired quote can be signed again')
        perps_flow.link_signed(batch)
        batch.status = 'reverted'
        batch.save()
        perps_flow.on_receipt(batch, {'status': '0x0'})
        perps_flow.on_receipt(batch, {'status': '0x0'})  # a second worker changes nothing
        position.refresh_from_db()
        self.assertEqual(position.state, 'failed', 'atomic revert: nothing left the dollars')

    def test_reconcile_bridge_and_reservation(self, *_):
        plan = self._prepare()
        position = plan['position']
        position.state = 'bridging'
        position.save()
        self.assertEqual(perps_flow.reserved_usdt_wei(self.wallet), 20 * WAD, 'a refund can land any second')
        with mock.patch('cusd_plus.perps_relay.status', return_value={'status': 'refund'}), \
                mock.patch('cusd_plus.perps_flow._delivered_usdt', return_value=None):
            perps_flow.reconcile_position(position)
        position.refresh_from_db()
        self.assertEqual(position.state, 'bridging', 'an unreadable refund amount waits, never guesses')
        with mock.patch('cusd_plus.perps_relay.status', return_value={'status': 'refund'}), \
                mock.patch('cusd_plus.perps_flow._delivered_usdt', return_value=20 * WAD):
            perps_flow.reconcile_position(position)
        position.refresh_from_db()
        self.assertEqual(position.state, 'refunded')
        self.assertEqual(perps_flow.reserved_usdt_wei(self.wallet), 20 * WAD, 'a refund is not auto-swept')
        with mock.patch('cusd_plus.vault.usdt_balance_raw', return_value=520 * WAD), \
                mock.patch('cusd_plus.perps_relay.RelayClient', return_value=FakeRelay()):
            retry = perps_flow.prepare_bridge_retry(self.user, position.id)
        self.assertEqual(int(retry['position'].flow['retry']['deposit_wei']), 20 * WAD,
                         'never bridges unrelated USDT beside the refund')
        position.refresh_from_db()
        position.state = 'bridging'
        position.flow = {k: v for k, v in position.flow.items() if k != 'retry'}
        position.save()
        with mock.patch('cusd_plus.perps_relay.status', return_value={'status': 'success', 'txHashes': ['0xab']}), \
                mock.patch('cusd_plus.perps_flow._hl_credit', return_value=Decimal('19.93')):
            perps_flow.reconcile_position(position)
        position.refresh_from_db()
        self.assertEqual(position.state, 'funded')
        self.assertEqual(position.credited_usdc, Decimal('19.93'), 'credited exactly what its Relay order delivered')
        self.assertEqual(perps_flow.reserved_usdt_wei(self.wallet), 0)

    def test_one_live_position_per_member(self, *_):
        from blockchain.models import PerpMarket

        plan = self._prepare()
        plan['position'].state = 'funded'
        plan['position'].save()
        PerpMarket.objects.create(coin='ETH', dex='', asset_id=1, sz_decimals=4, max_leverage=25,
                                  collateral='USDC', synced_at=self.btc.synced_at)
        from cusd_plus.crypto_policy import DOLLAR
        with mock.patch('cusd_plus.perps_relay.RelayClient', return_value=FakeRelay()), \
                mock.patch('cusd_plus.perps_flow._dollar_for', return_value=DOLLAR), \
                mock.patch('cusd_plus.perps_flow._new_account', return_value=False), \
                mock.patch('cusd_plus.vault.erc20_balance_raw', return_value=100 * WAD), \
                mock.patch('cusd_plus.crypto_policy.expected_exit_usdt', return_value=(20 * WAD, 20 * WAD)), \
                mock.patch('security.geo.phone_country_of', return_value='VE'):
            with self.assertRaises(perps_flow.FlowError) as ctx:
                perps_flow.prepare_open(self.user, self.wallet, {}, 'ETH', 'long', 5, '20.18')
        self.assertEqual(ctx.exception.code, 'one_position_at_a_time')


def _ch_state(withdrawable='19.9', positions=()):
    return {'withdrawable': withdrawable, 'assetPositions': [{'type': 'oneWay', 'position': p} for p in positions]}


BOOK = {'levels': [[{'px': '99990', 'sz': '5'}], [{'px': '100010', 'sz': '5'}]]}


@override_settings(**OPEN_SETTINGS)
class HyperliquidActionTests(TestCase):
    def setUp(self):
        from blockchain.models import PerpPosition
        from users.models import User

        self.user = User.objects.create(username='perpshl', firebase_uid='perpshl')
        self.wallet = _wallet_key().address.lower()
        self.btc = _market()
        self.position = PerpPosition.objects.create(
            user=self.user, wallet=self.wallet, market=self.btc, side='long', leverage=5,
            margin_usd=Decimal('20'), state='funded', flow={'done_abstraction': 1},
            credited_usdc=Decimal('19.9'))
        # The live book is re-read before an open goes out: never the network in tests.
        book = mock.patch('cusd_plus.hyperliquid.l2_book', return_value=BOOK)
        self.book = book.start()
        self.addCleanup(book.stop)
        ctxs = mock.patch('cusd_plus.hyperliquid.meta_and_asset_ctxs',
                          return_value=({'universe': [{'name': 'BTC'}]}, [{'markPx': '100000'}]))
        ctxs.start()
        self.addCleanup(ctxs.stop)
        # Never the network: every info read answers from fixtures.
        def venue(body, **_):
            kind = body.get('type')
            if kind == 'activeAssetData':
                return {'leverage': {'type': 'cross', 'value': 20}}
            if kind == 'clearinghouseState':
                return _ch_state()
            if kind == 'orderStatus':
                return {'status': 'unknownOid'}
            if kind == 'userRole':
                return {'role': 'user'}
            if kind == 'userAbstraction':
                return 'disabled'
            if kind == 'frontendOpenOrders':
                return []
            return []
        info = mock.patch('cusd_plus.hyperliquid.info', side_effect=venue)
        info.start()
        self.addCleanup(info.stop)
        # The open policy as it is now: on by default here, switched off below.
        gate = mock.patch('cusd_plus.perps_risk.open_gate', return_value=None)
        self.gate = gate.start()
        self.addCleanup(gate.stop)

    def _plan(self):
        with mock.patch('cusd_plus.hyperliquid.user_abstraction', return_value='disabled'), \
                mock.patch('cusd_plus.hyperliquid.clearinghouse_state', return_value=_ch_state()), \
                mock.patch('cusd_plus.hyperliquid.l2_book', return_value=BOOK):
            return perps_flow.open_plan(self.user, self.position.id)

    def _signed(self, action, nonce):
        typed = (hl_signing.l1_typed_data(action, nonce) if action['type'] in hl_signing.L1_TYPES
                 else hl_signing.user_signed_typed_data(action))
        return _sign_typed(typed)

    def test_open_plan_sizes_from_credited_margin(self):
        plan = self._plan()
        purposes = [s['purpose'] for s in plan['steps']]
        self.assertEqual(purposes, ['leverage', 'open_order'])
        order = plan['steps'][1]['action']['orders'][0]
        self.assertEqual((order['a'], order['b'], order['r']), (0, True, False))
        # Margined at the mark (+ slippage) with the taker fee from the same balance:
        # 19.9 × (1 − 20 bps) / (100500 / 5 + 100500 × 0.045%) → 0.00098
        self.assertEqual(order['s'], '0.00098')
        self.assertEqual(plan['steps'][0]['action'], {'type': 'updateLeverage', 'asset': 0, 'isCross': False,
                                                      'leverage': 5})

    def test_abstraction_first_then_replan(self):
        with mock.patch('cusd_plus.hyperliquid.user_abstraction', return_value='default'):
            self.position.flow = {}
            self.position.save()
            plan = perps_flow.open_plan(self.user, self.position.id)
        self.assertTrue(plan['replan'])
        self.assertEqual([s['purpose'] for s in plan['steps']], ['abstraction'])

    def test_submit_forwards_only_the_signed_plan(self):
        plan = self._plan()
        leverage_action = plan['steps'][0]['action']
        order_action = plan['steps'][1]['action']
        nonce = perps_flow._now_ms()
        with self.assertRaises(perps_flow.FlowError) as ctx:
            perps_flow.submit_action(self.user, self.position.id, 'open_order', json.dumps(order_action),
                                     nonce, self._signed(order_action, nonce))
        self.assertEqual(ctx.exception.code, 'step_out_of_order', 'isolated leverage first')
        with mock.patch('cusd_plus.hyperliquid.exchange', return_value={'status': 'ok', 'response': {'type': 'default'}}):
            perps_flow.submit_action(self.user, self.position.id, 'leverage', json.dumps(leverage_action),
                                     nonce, self._signed(leverage_action, nonce))
            with self.assertRaises(perps_flow.FlowError) as ctx:
                perps_flow.submit_action(self.user, self.position.id, 'leverage', json.dumps(leverage_action),
                                         nonce + 1, self._signed(leverage_action, nonce + 1))
            self.assertEqual(ctx.exception.code, 'step_out_of_order', 'a consumed step cannot be replayed')
        fill = {'status': 'ok', 'response': {'type': 'order', 'data': {'statuses': [
            {'filled': {'oid': 7, 'avgPx': '100010', 'totalSz': '0.00099'}}]}}}
        with mock.patch('cusd_plus.hyperliquid.exchange', return_value=fill) as forwarded:
            perps_flow.submit_action(self.user, self.position.id, 'open_order', json.dumps(order_action),
                                     nonce, self._signed(order_action, nonce))
        self.position.refresh_from_db()
        self.assertEqual((self.position.state, self.position.entry_oid), ('open', 7))
        self.assertIsNone(forwarded.call_args.args[0]['vaultAddress'])

        other = copy.deepcopy(order_action)
        other['orders'][0]['s'] = '1'
        self.position.refresh_from_db()
        self.position.state = 'funded'
        plan_state = self.position.flow['open_plan']
        plan_state['consumed'] = [0]
        self.position.save()
        with self.assertRaises(perps_flow.FlowError) as ctx:
            perps_flow.submit_action(self.user, self.position.id, 'open_order', json.dumps(other),
                                     nonce, self._signed(other, nonce))
        self.assertEqual(ctx.exception.code, 'action_mismatch')
        stranger = Account.create()
        sig = stranger.sign_message(encode_typed_data(full_message=hl_signing.l1_typed_data(order_action, nonce)))
        with self.assertRaises(perps_flow.FlowError) as ctx:
            perps_flow.submit_action(self.user, self.position.id, 'open_order', json.dumps(order_action), nonce,
                                     {'r': hex(sig.r), 's': hex(sig.s), 'v': sig.v})
        self.assertEqual(ctx.exception.code, 'bad_signature')

    def test_closed_on_the_venue_settles_from_fills_and_notifies_only_when_away(self):
        self.position.state = 'open'
        self.position.save()
        now_ms = perps_flow._now_ms() + 1000
        fills = [{'coin': 'BTC', 'dir': 'Close Long', 'closedPnl': '3.5', 'fee': '0.04', 'px': '101000',
                  'sz': '0.00099', 'time': now_ms}]
        funding = [{'delta': {'type': 'funding', 'coin': 'BTC', 'usdc': '-0.01'}}]
        with mock.patch('cusd_plus.hyperliquid.clearinghouse_state', return_value=_ch_state('23.3')), \
                mock.patch('cusd_plus.hyperliquid.user_fills_by_time', return_value=fills), \
                mock.patch('cusd_plus.hyperliquid.user_funding', return_value=funding), \
                mock.patch('notifications.utils.create_notification') as notify:
            perps_flow.reconcile_position(self.position)
        self.position.refresh_from_db()
        self.assertEqual(self.position.state, 'closed')
        self.assertEqual(self.position.realized_pnl, Decimal('3.5'))
        notify.assert_called_once()
        self.assertEqual(notify.call_args.kwargs['notification_type'], 'PERPS_POSITION_UPDATE')

    @mock.patch('cusd_plus.perps_relay.time.time', return_value=NOW)
    @mock.patch('cusd_plus.perps_flow.time.time', return_value=NOW)
    def test_return_needs_both_member_signatures_then_lands_and_enters(self, *_):
        self.position.state = 'closed'
        self.position.credited_usdc = Decimal('20')
        self.position.save()
        # A genuine Relay quote for this wallet (rewriting another's would break its order id).
        relay = FakeRelay(back=copy.deepcopy(FIXTURE['back_sdk_wallet']))
        with mock.patch('cusd_plus.perps_relay.RelayClient', return_value=relay), \
                mock.patch('cusd_plus.hyperliquid.clearinghouse_state', return_value=_ch_state('20.0000009')):
            plan = perps_flow.return_plan(self.user, self.position.id)
        mapping_sig = _sign_typed(plan['mapping_typed'])
        nonce = plan['relay']['nonce']
        send_sig = self._signed(plan['send_action'], nonce)
        with mock.patch('cusd_plus.perps_relay.RelayClient', return_value=relay), \
                mock.patch('cusd_plus.hyperliquid.exchange', return_value={'status': 'ok'}) as forwarded:
            with self.assertRaises(perps_flow.FlowError):
                perps_flow.submit_return(self.user, self.position.id, send_sig, send_sig)
            perps_flow.submit_return(self.user, self.position.id, mapping_sig, send_sig)
        self.position.refresh_from_db()
        self.assertEqual(self.position.state, 'returning')
        self.assertEqual(relay.posted[-1][1], '/authorize', 'Relay authorized before the transfer')
        self.assertEqual(forwarded.call_args.args[0]['action']['destination'], perps_relay.hl_depository())

        with mock.patch('cusd_plus.perps_relay.status', return_value={'status': 'success', 'txHashes': []}):
            perps_flow.reconcile_position(self.position)
        self.position.refresh_from_db()
        self.assertEqual(self.position.state, 'returning', 'never lands on an estimate while the receipt can still be read')
        with mock.patch('cusd_plus.perps_relay.status', return_value={'status': 'success', 'txHashes': ['0x1']}), \
                mock.patch('cusd_plus.perps_flow._delivered_usdt', return_value=int(Decimal('19.95') * WAD)):
            perps_flow.reconcile_position(self.position)
        self.position.refresh_from_db()
        self.assertEqual(self.position.state, 'landed')
        self.assertEqual(int(self.position.flow['landed_wei']), int(Decimal('19.95') * WAD), 'the exact delivery')
        self.assertGreater(perps_flow.reserved_usdt_wei(self.wallet), 0, 'landed proceeds wait for their entry')

        from cusd_plus.crypto_policy import DOLLAR
        with mock.patch('cusd_plus.vault.usdt_balance_raw', return_value=19 * WAD), \
                mock.patch('cusd_plus.eligibility.check_savings_mint_eligibility', return_value=False), \
                mock.patch('cusd_plus.cusd_vault.preview_mint_wei',
                           return_value=SimpleNamespace(net_wei=int(Decimal('18.829') * WAD))):
            entry = perps_flow.entry_plan(self.user, {}, self.position.id)
        self.assertEqual(entry['dollar'], DOLLAR)
        self.assertTrue(entry['request_id'].startswith('perps-ret-'))
        self.assertEqual(perps_flow.return_kind('mint_cusd', entry['calls'], entry['request_id'], self.user),
                         'perps_return')
        from cusd_plus.sponsor_7702 import PolicyError
        with self.assertRaises(PolicyError):
            perps_flow.return_kind('mint_cusd', entry['calls'][:1], entry['request_id'], self.user)
        self.assertEqual(perps_flow.return_kind('mint_cusd', entry['calls'], '', self.user), 'mint_cusd')

    def test_dollar_plus_entry_floor_is_usdy_after_the_fee(self):
        # Prod 2026-10-26: the floor was in cUSD+ shares (above any possible
        # USDY out) and the vault reverted every entry.
        from cusd_plus.crypto_policy import DOLLAR_PLUS
        self.position.state = 'landed'
        self.position.flow = {**self.position.flow, 'landed_wei': str(int(Decimal('10.6178') * WAD))}
        self.position.save()
        oracle, net = int(Decimal('1.12') * WAD), int(Decimal('10.522') * WAD)
        with mock.patch('cusd_plus.vault.usdt_balance_raw', return_value=11 * WAD), \
                mock.patch('cusd_plus.eligibility.check_savings_mint_eligibility', return_value=True), \
                mock.patch('cusd_plus.vault.is_safe_mint_amount', return_value=True), \
                mock.patch('cusd_plus.vault.vault_address', return_value='0x' + '3c' * 20), \
                mock.patch('cusd_plus.vault.p_plus_wad', return_value=int(Decimal('1.02') * WAD)), \
                mock.patch('cusd_plus.vault.current_oracle_price_wad', return_value=oracle), \
                mock.patch('cusd_plus.cusd_vault.preview_mint_wei', return_value=SimpleNamespace(net_wei=net)):
            entry = perps_flow.entry_plan(self.user, {}, self.position.id)
        self.assertEqual(entry['dollar'], DOLLAR_PLUS)
        floor = int(entry['calls'][1]['data'][10 + 64:10 + 128], 16)
        self.assertEqual(floor, (net * WAD // oracle) * 9950 // 10000)
        self.assertLess(floor, net * WAD // oracle, 'always below what the mint delivers')

    def test_an_unsent_entry_is_reissued_once_its_prices_are_old(self):
        self.position.state = 'landed'
        self.position.flow = {**self.position.flow, 'landed_wei': str(19 * WAD),
                              'entry': {'calls': [], 'request_id': 'perps-ret-old', 'dollar': 0}}
        self.position.save()
        with mock.patch('cusd_plus.vault.usdt_balance_raw', return_value=19 * WAD), \
                mock.patch('cusd_plus.eligibility.check_savings_mint_eligibility', return_value=False), \
                mock.patch('cusd_plus.cusd_vault.preview_mint_wei',
                           return_value=SimpleNamespace(net_wei=int(Decimal('18.829') * WAD))):
            entry = perps_flow.entry_plan(self.user, {}, self.position.id)
            again = perps_flow.entry_plan(self.user, {}, self.position.id)
        self.assertNotEqual(entry['request_id'], 'perps-ret-old')
        self.assertEqual(again['request_id'], entry['request_id'], 'fresh: kept while its prices hold')


    @mock.patch('cusd_plus.perps_relay.time.time', return_value=NOW)
    @mock.patch('cusd_plus.perps_flow.time.time', return_value=NOW)
    def test_failed_return_retries_after_a_normal_trade_and_excludes_opens(self, *_):
        """A closed trade's filled cloid is history, not a live position
        (Codex r6 P1); a pending open step blocks the return under the lock."""
        self.position.state = 'return_failed'
        self.position.credited_usdc = Decimal('20')
        self.position.flow = {**self.position.flow, 'open_cloids': ['0x' + '11' * 16]}
        self.position.save()
        # A genuine Relay quote for this wallet (rewriting another's would break its order id).
        relay = FakeRelay(back=copy.deepcopy(FIXTURE['back_sdk_wallet']))
        with mock.patch('cusd_plus.perps_relay.RelayClient', return_value=relay), \
                mock.patch('cusd_plus.perps_flow._order_status', return_value={'status': 'filled'}), \
                mock.patch('cusd_plus.hyperliquid.clearinghouse_state', return_value=_ch_state('20.0000009')):
            plan = perps_flow.return_plan(self.user, self.position.id)
        self.assertTrue(plan['send_action'])
        self.position.refresh_from_db()
        self.position.state = 'funded'  # an open step on the wire while the return is signed
        self.position.flow = {**self.position.flow,
                              'open_plan': {'claims': {'0': {'status': 'sending'}}, 'issued_ms': NOW * 1000,
                                            'steps': [{'purpose': 'open_order', 'action': {}}]}}
        self.position.save()
        mapping_sig = _sign_typed(plan['mapping_typed'])
        send_sig = self._signed(plan['send_action'], plan['relay']['nonce'])
        with mock.patch('cusd_plus.perps_relay.RelayClient', return_value=relay), \
                mock.patch('cusd_plus.hyperliquid.clearinghouse_state', return_value=_ch_state('20.0000009')), \
                mock.patch('cusd_plus.hyperliquid.exchange', return_value={'status': 'ok'}) as forwarded:
            with self.assertRaisesRegex(perps_flow.FlowError, 'step_in_flight'):
                perps_flow.submit_return(self.user, self.position.id, mapping_sig, send_sig)
        forwarded.assert_not_called()

    def test_opening_follows_the_open_policy_as_it_is_now(self):
        plan = self._plan()
        order = next(st['action'] for st in plan['steps'] if st['purpose'] == 'open_order')
        self.gate.return_value = 'trade_not_available'  # ops switched opens off after funding
        with self.assertRaisesRegex(perps_flow.FlowError, 'trade_not_available'):
            self._plan()
        nonce = perps_flow._now_ms()
        with mock.patch('cusd_plus.hyperliquid.exchange') as forwarded:
            with self.assertRaisesRegex(perps_flow.FlowError, 'trade_not_available'):
                perps_flow.submit_action(self.user, self.position.id, 'open_order', json.dumps(order), nonce,
                                         self._signed(order, nonce))
        forwarded.assert_not_called()

    def test_partial_closes_either_side_of_midnight_stay_two_events(self):
        self.position.state, self.position.size = 'open', Decimal(2)
        self.position.save()
        t1 = int(datetime(2026, 10, 24, 23, 59, tzinfo=dt_timezone.utc).timestamp() * 1000)
        t2 = int(datetime(2026, 10, 25, 0, 1, tzinfo=dt_timezone.utc).timestamp() * 1000)
        since = int(self.position.created_at.timestamp() * 1000)
        fills = [
            {'coin': 'BTC', 'time': since + 1, 'dir': 'Open Long', 'side': 'B', 'sz': '2', 'startPosition': '0',
             'closedPnl': '0'},
            {'coin': 'BTC', 'time': max(t1, since + 2), 'dir': 'Close Long', 'side': 'A', 'sz': '0.5',
             'startPosition': '2', 'closedPnl': '5'},
            {'coin': 'BTC', 'time': max(t2, since + 3), 'dir': 'Close Long', 'side': 'A', 'sz': '1',
             'startPosition': '1.5', 'closedPnl': '7'},
        ]
        with mock.patch('cusd_plus.hyperliquid.user_fills_by_time', return_value=fills):
            perps_flow._track_size(self.position, {'szi': '0.5'})
        self.position.refresh_from_db()
        events = self.position.flow['size_events']
        # The opening fill is an event too (a limit entry may fill in parts).
        self.assertEqual([(e['size'], e['realized']) for e in events], [('2', '0'), ('1.5', '5'), ('0.5', '12')])
        self.assertEqual(self.position.size, Decimal('0.5'))

    def test_a_lost_open_never_recorded_is_released_but_an_unreadable_one_is_kept(self):
        cloid = '0x' + '22' * 16
        old = perps_flow._now_ms() - perps_flow.PLAN_TTL_MS - 1000
        flow = {**self.position.flow, 'open_plan': {
            'issued_ms': old, 'steps': [{'purpose': 'leverage', 'action': {}}, {'purpose': 'open_order', 'action': {}}],
            'claims': {'0': {'status': 'unconfirmed', 'at': old}}}}
        self.position.flow = flow
        self.position.save()
        self.assertTrue(perps_flow._open_in_flight(self.position), 'a dex transfer may still move the money')
        perps_flow._release_lost_open(self.position)  # a stale setup step: safe to plan again
        self.position.refresh_from_db()
        self.assertFalse(perps_flow._open_in_flight(self.position))
        flow = self.position.flow
        flow['open_plan']['claims']['1'] = {'status': 'unconfirmed', 'at': old, 'cloid': cloid}
        self.position.flow = flow
        self.position.save()
        self.assertTrue(perps_flow._open_in_flight(self.position))
        with mock.patch('cusd_plus.hyperliquid.info', side_effect=perps_flow.hyperliquid.HyperliquidError('down')):
            with self.assertRaises(perps_flow.hyperliquid.HyperliquidError):
                perps_flow._release_lost_open(self.position)
        self.position.refresh_from_db()
        self.assertTrue(perps_flow._open_in_flight(self.position), 'unknown is not a no')
        with mock.patch('cusd_plus.hyperliquid.info', return_value={'status': 'unknownOid'}):
            perps_flow._release_lost_open(self.position)
        self.position.refresh_from_db()
        self.assertFalse(perps_flow._open_in_flight(self.position))

    def test_saving_protection_replaces_the_live_triggers(self):
        self.position.state, self.position.size = 'open', Decimal('0.001')
        self.position.save()
        live = {'coin': 'BTC', 'szi': '0.001', 'entryPx': '100000', 'leverage': {'type': 'isolated', 'value': 5}}
        old_stop = {'coin': 'BTC', 'oid': 77, 'isTrigger': True, 'reduceOnly': True, 'orderType': 'Stop Market',
                    'triggerPx': '90000'}
        with mock.patch('cusd_plus.hyperliquid.clearinghouse_state', return_value=_ch_state(positions=[live])), \
                mock.patch('cusd_plus.hyperliquid.frontend_open_orders', return_value=[old_stop]):
            plan = perps_flow.tpsl_plan(self.user, self.position.id, None, '80000')
        self.assertEqual([st['purpose'] for st in plan['steps']], ['tpsl', 'tpsl_cancel'], 'new first, old after')
        self.assertEqual(plan['steps'][1]['action'], {'type': 'cancel', 'cancels': [{'a': self.btc.asset_id, 'o': 77}]})
        # A stop above the entry (locking profit) is fine once the market is higher.
        self.book.return_value = {'levels': [[{'px': '119990', 'sz': '5'}], [{'px': '120010', 'sz': '5'}]]}
        with mock.patch('cusd_plus.hyperliquid.clearinghouse_state', return_value=_ch_state(positions=[live])), \
                mock.patch('cusd_plus.hyperliquid.frontend_open_orders', return_value=[]):
            plan = perps_flow.tpsl_plan(self.user, self.position.id, None, '110000')
            with self.assertRaisesRegex(perps_flow.FlowError, 'bad_trigger_side'):
                perps_flow.tpsl_plan(self.user, self.position.id, '105000', None)  # TP below the market

    def test_a_stale_open_is_refused_when_the_book_thinned(self):
        plan = self._plan()
        order = next(st['action'] for st in plan['steps'] if st['purpose'] == 'open_order')
        nonce = perps_flow._now_ms()
        thin = copy.deepcopy(BOOK)
        thin['levels'][0 if order['orders'][0]['b'] is False else 1] = [
            {'px': lvl['px'], 'sz': str(Decimal(lvl['sz']) / 1000), 'n': 1}
            for lvl in BOOK['levels'][0 if order['orders'][0]['b'] is False else 1]]
        self.book.return_value = thin
        with mock.patch('cusd_plus.hyperliquid.exchange') as forwarded:
            with self.assertRaises(perps_flow.FlowError):
                perps_flow.submit_action(self.user, self.position.id, 'open_order', json.dumps(order), nonce,
                                         self._signed(order, nonce))
        forwarded.assert_not_called()

    def test_a_quoted_return_blocks_open_steps_under_the_lock(self):
        flow = {**self.position.flow, 'return_relay': {'deadline': int(time.time()) + 600}}
        self.position.flow = flow
        self.position.save()
        with self.assertRaisesRegex(perps_flow.FlowError, 'return_in_progress'):
            perps_flow._claim_step(self.position.pk, 'open_order', {'type': 'order'}, 1, ('funded',))
        self.position.state = 'returning'
        self.position.save()
        with self.assertRaisesRegex(perps_flow.FlowError, 'bad_state'):
            perps_flow._claim_step(self.position.pk, 'close_order', {'type': 'order'}, 1, ('open',))


class LedgerTests(SimpleTestCase):
    def test_venue_markers_near_midnight_keep_their_own_time(self):
        from inbox import portfolio_returns
        from cusd_plus.stock_month import Trade

        late = datetime(2026, 10, 24, 23, 45, tzinfo=dt_timezone.utc)
        mark = Trade(symbol='PERP:BTC', kind='perps_mark', units=Decimal(1), usd=Decimal(0), when=late)
        prices = mock.Mock()
        with mock.patch('cusd_plus.stock_month.confirmed_trades', return_value=[]), \
                mock.patch('cusd_plus.crypto_month.confirmed_trades', return_value=[]), \
                mock.patch('cusd_plus.perps_portfolio.episodes', return_value=[]), \
                mock.patch('cusd_plus.perps_portfolio.ledger_trades', return_value=[mark]):
            ledger = portfolio_returns.load_ledger('0xabc', prices)
        self.assertEqual(ledger.perps_rows[0].when, late)
        prices.block_time.assert_not_called()


    def test_fee_ledger_tags_perps(self):
        from cusd_plus import fee_ledger

        self.assertIn('perps', fee_ledger.SOURCES)
        event = SimpleNamespace(tx_hash='0x1', direction='exit')
        for kind in ('perps_open', 'perps_return'):
            self.assertEqual(fee_ledger.classify(event, SimpleNamespace(kind=kind, client_request_id=''), {}, set()),
                             'perps')


class PaginationTests(SimpleTestCase):
    def test_history_reads_every_page_and_never_returns_a_truncated_one(self):
        from cusd_plus import hyperliquid

        full = [{'time': 1000 + i, 'tid': i} for i in range(hyperliquid.PAGE_LIMIT)]
        tail = [{'time': 1000 + hyperliquid.PAGE_LIMIT - 1, 'tid': hyperliquid.PAGE_LIMIT - 1},
                {'time': 5000, 'tid': 9999}]
        pages = iter([full, tail])
        with mock.patch('cusd_plus.hyperliquid.info', side_effect=lambda body, session=None: next(pages)):
            rows = hyperliquid.user_fills_by_time('0x' + '1' * 40, 0)
        self.assertEqual(len(rows), hyperliquid.PAGE_LIMIT + 1, 'overlapping row counted once')
        endless = [{'time': 1, 'tid': i} for i in range(hyperliquid.PAGE_LIMIT)]
        import itertools
        counter = itertools.count()
        with mock.patch('cusd_plus.hyperliquid.info',
                        side_effect=lambda body, session=None: [dict(r, tid=next(counter)) for r in endless]):
            with self.assertRaises(hyperliquid.HyperliquidError):
                hyperliquid.user_funding('0x' + '1' * 40, 0)


class PendingTopupValuationTests(SimpleTestCase):
    def test_a_top_up_on_its_way_keeps_its_value_until_applied(self):
        """Codex r7 P2: $100 flat + $100 top-up before midnight, applied
        after it: midnight equity is $200, never a fictitious loss."""
        from cusd_plus.perps_portfolio import Episode, equity_at

        t0 = datetime(2026, 10, 24, 12, tzinfo=dt_timezone.utc)
        sent = datetime(2026, 10, 24, 23, 0, tzinfo=dt_timezone.utc)
        applied = datetime(2026, 10, 25, 8, 0, tzinfo=dt_timezone.utc)
        midnight = datetime(2026, 10, 25, 0, 0, tzinfo=dt_timezone.utc)
        ep = Episode(
            position_id=1, coin='BTC', ticker='BTC', side='long', leverage=2, state='open',
            put_in=[(t0, Decimal(100), 1), (sent, Decimal(100), 2)], returned=None, credited=Decimal(200),
            entry_px=Decimal(100), size_signed=Decimal(2), closed_at=None, settled_equity=None, liquidated=False,
            credit_events=[(applied, Decimal(100))], credited_initial=Decimal(100), filled_at=t0,
            pending_topups=[(sent, applied, Decimal(100), False, True)])
        price = lambda coin: Decimal(100)  # noqa: E731 — flat market
        self.assertEqual(equity_at(ep, midnight, price), Decimal(200))
        self.assertEqual(equity_at(ep, applied, price), Decimal(200))
        self.assertEqual(equity_at(ep, sent - (applied - sent), price), Decimal(100))

    def test_closed_while_a_top_up_bridges_keeps_it_without_double_counting(self):
        from cusd_plus.perps_portfolio import Episode, equity_at

        t0 = datetime(2026, 10, 24, 12, tzinfo=dt_timezone.utc)
        sent = datetime(2026, 10, 24, 20, tzinfo=dt_timezone.utc)
        closed = datetime(2026, 10, 24, 21, tzinfo=dt_timezone.utc)
        midnight = datetime(2026, 10, 25, tzinfo=dt_timezone.utc)
        ep = Episode(
            position_id=1, coin='BTC', ticker='BTC', side='long', leverage=2, state='closed',
            put_in=[(t0, Decimal(100), 1), (sent, Decimal(100), 2), (sent, Decimal(50), 3)], returned=None,
            credited=Decimal(100), entry_px=Decimal(100), size_signed=Decimal(2), closed_at=closed,
            settled_equity=Decimal(100), liquidated=False, filled_at=t0,
            pending_topups=[(sent, None, Decimal(100), False, False), (sent, None, Decimal(50), True, False)])
        # $100 settled + the $50 that arrived unapplied + $100 still bridging, each dated by its batch.
        self.assertEqual(equity_at(ep, midnight, lambda coin: Decimal(100)), Decimal(250))
        self.assertEqual(equity_at(ep, sent - (closed - sent), lambda coin: Decimal(100)), Decimal(100))


class LateAcknowledgementTests(SimpleTestCase):
    def test_a_top_up_acknowledged_after_the_close_is_not_counted_twice(self):
        """Codex r41: settled equity already holds an applied top-up."""
        from cusd_plus.perps_portfolio import Episode, equity_at

        t0 = datetime(2026, 10, 24, 12, tzinfo=dt_timezone.utc)
        sent = datetime(2026, 10, 24, 23, 50, tzinfo=dt_timezone.utc)
        closed = datetime(2026, 10, 24, 23, 59, 59, tzinfo=dt_timezone.utc)
        acked = datetime(2026, 10, 25, 0, 0, 3, tzinfo=dt_timezone.utc)
        midnight = datetime(2026, 10, 25, tzinfo=dt_timezone.utc)
        ep = Episode(
            position_id=1, coin='BTC', ticker='BTC', side='long', leverage=2, state='closed',
            put_in=[(t0, Decimal(100), 1), (sent, Decimal(100), 2)], returned=None, credited=Decimal(200),
            entry_px=Decimal(100), size_signed=Decimal(2), closed_at=closed, settled_equity=Decimal(200),
            liquidated=False, filled_at=t0, pending_topups=[(sent, acked, Decimal(100), False, True)])
        self.assertEqual(equity_at(ep, midnight, lambda coin: Decimal(100)), Decimal(200))


class RepostTests(SimpleTestCase):
    def test_a_re_posted_action_is_applied_once_and_ambiguity_is_never_a_release(self):
        cases = [({'status': 'ok'}, 'ok'),
                 ({'status': 'err', 'response': 'Nonce already used'}, 'used'),
                 ({'status': 'err', 'response': 'Invalid nonce: too old'}, 'nonce'),
                 ({'status': 'err', 'response': 'Insufficient margin'}, 'rejected')]
        for body, want in cases:
            with mock.patch('cusd_plus.hyperliquid.exchange', return_value=body):
                self.assertEqual(perps_flow._repost({'action': {}}), want, body)
        with mock.patch('cusd_plus.hyperliquid.exchange', side_effect=perps_flow.hyperliquid.HyperliquidError('x')):
            self.assertEqual(perps_flow._repost({'action': {}}), 'unknown')
        with mock.patch('cusd_plus.hyperliquid.exchange', return_value=cases[2][0]):
            self.assertEqual(perps_flow._send_return(1, {}), 'rejected')


@override_settings(**OPEN_SETTINGS)
class LimitOrderTests(TestCase):
    """Limit entries rest on the book with the money on the venue; take-profit
    and stop-loss chosen at the order ride the entry (normalTpsl)."""

    setUp = HyperliquidActionTests.setUp
    _signed = HyperliquidActionTests._signed

    def _intent(self, **kw):
        self.position.flow = {**self.position.flow, 'order': perps_flow.order_intent(**kw)}
        self.position.save()

    def _plan(self, **kw):
        with mock.patch('cusd_plus.hyperliquid.user_abstraction', return_value='disabled'), \
                mock.patch('cusd_plus.hyperliquid.clearinghouse_state', return_value=_ch_state()):
            return perps_flow.open_plan(self.user, self.position.id, **kw)

    def test_a_limit_entry_rests_at_the_members_price_with_its_protection(self):
        self._intent(order_type='limit', limit_px='95000.37', take_profit_px='110000', stop_loss_px='90000')
        plan = self._plan()
        action = plan['steps'][-1]['action']
        entry, *children = action['orders']
        self.assertEqual(action['grouping'], 'normalTpsl')
        self.assertEqual(entry['t'], {'limit': {'tif': 'Gtc'}})
        self.assertLessEqual(Decimal(entry['p']), Decimal('95000.37'), 'a buy never pays more than chosen')
        self.assertEqual([c['t']['trigger']['tpsl'] for c in children], ['tp', 'sl'])
        self.assertTrue(all(c['r'] and not c['b'] and c['s'] == entry['s'] for c in children))
        self.assertEqual(plan['impact_bps'], 0, 'a resting order takes nothing from the book')

    def test_protection_on_the_wrong_side_is_refused_before_money_moves(self):
        with mock.patch('cusd_plus.hyperliquid.l2_book', return_value=BOOK):
            with self.assertRaises(perps_flow.FlowError) as ctx:
                perps_flow._check_intent(self.btc, 'long', perps_flow.order_intent('market', None, '90000', None))
            self.assertEqual(ctx.exception.code, 'bad_trigger_side')
            with self.assertRaises(perps_flow.FlowError) as ctx:
                perps_flow._check_intent(self.btc, 'long', perps_flow.order_intent('limit', '20000'))
            self.assertEqual(ctx.exception.code, 'limit_too_far')

    def test_the_market_moved_past_a_stop_the_member_opens_without_it(self):
        self._intent(order_type='market', stop_loss_px='100500')  # now above the market for a long
        with self.assertRaises(perps_flow.FlowError) as ctx:
            self._plan()
        self.assertEqual(ctx.exception.code, 'bad_trigger_side')
        plan = self._plan(drop_protection=True)
        self.assertEqual(plan['steps'][-1]['action']['grouping'], 'na')
        self.position.refresh_from_db()
        self.assertIsNone(self.position.flow['order']['sl'])

    def _rest(self):
        self._intent(order_type='limit', limit_px='95000')
        plan = self._plan()
        leverage, order = plan['steps'][0]['action'], plan['steps'][1]['action']
        nonce = perps_flow._now_ms()
        resting = {'status': 'ok', 'response': {'type': 'order', 'data': {'statuses': [{'resting': {'oid': 9}}]}}}
        with mock.patch('cusd_plus.hyperliquid.exchange', return_value={'status': 'ok', 'response': {'type': 'default'}}):
            perps_flow.submit_action(self.user, self.position.id, 'leverage', json.dumps(leverage), nonce,
                                     self._signed(leverage, nonce))
        with mock.patch('cusd_plus.hyperliquid.exchange', return_value=resting):
            perps_flow.submit_action(self.user, self.position.id, 'open_order', json.dumps(order), nonce,
                                     self._signed(order, nonce))
        self.position.refresh_from_db()
        return order

    def test_a_resting_entry_keeps_the_money_funded_and_waits(self):
        from cusd_plus.perps_schema import _next_action

        order = self._rest()
        self.assertEqual(self.position.state, 'funded')
        self.assertEqual(self.position.flow['resting']['oid'], 9)
        self.assertEqual(self.position.flow['resting']['cloid'], order['orders'][0]['c'])
        self.assertEqual(_next_action(self.position), 'wait_fill')

    def test_the_way_home_cancels_the_resting_entry_first(self):
        self._rest()
        waiting = [{'coin': 'BTC', 'oid': 9, 'reduceOnly': False, 'isTrigger': False},
                   # Its protection is never cancelled on the way home (Hyperliquid drops it with the entry).
                   {'coin': 'BTC', 'oid': 10, 'reduceOnly': True, 'isTrigger': True}]
        with mock.patch('cusd_plus.hyperliquid.frontend_open_orders', return_value=waiting):
            plan = perps_flow.return_plan(self.user, self.position.id)
            self.assertEqual(plan['steps'][0]['purpose'], 'return_cancel')
            self.assertEqual(plan['steps'][0]['action'], {'type': 'cancel', 'cancels': [{'a': 0, 'o': 9}]})
            # Never money out while the order could still fill.
            with self.assertRaises(perps_flow.FlowError) as ctx:
                perps_flow._guard_not_live(self.position)
            self.assertEqual(ctx.exception.code, 'order_resting')
        cancel = plan['steps'][0]['action']
        nonce = perps_flow._now_ms()
        refused = {'status': 'ok', 'response': {'type': 'cancel', 'data': {'statuses': [{'error': 'Rate limited'}]}}}
        with mock.patch('cusd_plus.hyperliquid.exchange', return_value=refused):
            with self.assertRaises(perps_flow.FlowError) as ctx:
                perps_flow.submit_action(self.user, self.position.id, 'return_cancel', json.dumps(cancel), nonce,
                                         self._signed(cancel, nonce))
        self.assertEqual(ctx.exception.code, 'cancel_rejected')
        self.position.refresh_from_db()
        self.assertEqual(self.position.flow['resting']['oid'], 9, 'a refused cancel leaves the order followed')
        done = {'status': 'ok', 'response': {'type': 'cancel', 'data': {'statuses': ['success']}}}
        with mock.patch('cusd_plus.hyperliquid.exchange', return_value=done):
            perps_flow.submit_action(self.user, self.position.id, 'return_cancel', json.dumps(cancel), nonce + 1,
                                     self._signed(cancel, nonce + 1))
        self.position.refresh_from_db()
        self.assertIsNone(self.position.flow['resting'])

    def test_a_fill_while_away_opens_the_position_and_tells_the_member(self):
        self._rest()
        live = {'coin': 'BTC', 'szi': '0.00098', 'entryPx': '95000'}
        fills = [{'coin': 'BTC', 'oid': 9, 'sz': '0.00098', 'px': '95000', 'time': perps_flow._now_ms(),
                  'dir': 'Open Long', 'closedPnl': '0', 'fee': '0.01'}]
        status = {'status': 'filled', 'order': {'oid': 9, 'origSz': '0.00098', 'sz': '0'}}
        with mock.patch('cusd_plus.hyperliquid.clearinghouse_state', return_value=_ch_state(positions=[live])), \
                mock.patch('cusd_plus.perps_flow._order_status', return_value=status), \
                mock.patch('cusd_plus.hyperliquid.user_fills_by_time', return_value=fills), \
                mock.patch('notifications.utils.create_notification') as notify:
            perps_flow.reconcile_position(self.position)
        self.position.refresh_from_db()
        self.assertEqual(self.position.state, 'open')
        self.assertEqual(self.position.entry_avg_px, Decimal('95000'))
        self.assertEqual(notify.call_args.kwargs['data']['event'], 'filled')

    def test_an_entry_the_venue_cancelled_frees_the_money(self):
        self._rest()
        gone = {'status': 'canceled', 'order': {'oid': 9, 'origSz': '0.00098', 'sz': '0.00098'}}
        with mock.patch('cusd_plus.perps_flow._order_status', return_value=gone):
            perps_flow.reconcile_position(self.position)
        self.position.refresh_from_db()
        self.assertEqual(self.position.state, 'funded')
        self.assertIsNone(self.position.flow['resting'])

    def test_a_close_cancels_the_unfilled_rest_before_closing(self):
        self.position.state = 'open'
        self.position.save()
        live = {'coin': 'BTC', 'szi': '0.0005', 'entryPx': '95000'}
        orders = [{'coin': 'BTC', 'oid': 9, 'reduceOnly': False, 'isTrigger': False},
                  {'coin': 'BTC', 'oid': 10, 'reduceOnly': True, 'isTrigger': True}]
        with mock.patch('cusd_plus.hyperliquid.clearinghouse_state', return_value=_ch_state(positions=[live])), \
                mock.patch('cusd_plus.hyperliquid.frontend_open_orders', return_value=orders):
            plan = perps_flow.close_plan(self.user, self.position.id)
        # The rest is cancelled alone first; the close is sized once nothing can still fill.
        self.assertEqual([s['purpose'] for s in plan['steps']], ['close_cancel'])
        self.assertTrue(plan['replan'])
        self.assertEqual(plan['steps'][0]['action']['cancels'], [{'a': 0, 'o': 9}], 'never the protection')


@override_settings(**OPEN_SETTINGS)
class LimitEdgeTests(TestCase):
    setUp = HyperliquidActionTests.setUp

    def test_flat_with_an_entry_still_waiting_stays_open_and_closing_cancels_it(self):
        self.position.state = 'open'
        self.position.size = Decimal('0.0005')
        self.position.save()
        rest = [{'coin': 'BTC', 'oid': 9, 'reduceOnly': False, 'isTrigger': False}]
        with mock.patch('cusd_plus.hyperliquid.frontend_open_orders', return_value=rest):
            perps_flow.reconcile_position(self.position)       # flat: protection closed the filled part
            self.position.refresh_from_db()
            self.assertEqual(self.position.state, 'open', 'its rest may still fill: never closed underneath it')
            plan = perps_flow.close_plan(self.user, self.position.id)
        self.assertEqual([s['purpose'] for s in plan['steps']], ['close_cancel'])

    def test_no_second_entry_while_one_rests(self):
        self.position.flow = {**self.position.flow, 'resting': {'oid': 9, 'cloid': '0x' + '11' * 16}}
        self.position.save()
        with self.assertRaises(perps_flow.FlowError) as ctx:
            perps_flow._store_plan(self.position, 'open_plan', [])
        self.assertEqual(ctx.exception.code, 'order_resting')

    def test_a_crossing_limit_is_judged_only_on_what_it_can_take(self):
        book = {'levels': [[{'px': '99', 'sz': '5'}], [{'px': '101', 'sz': '0.1'}, {'px': '150', 'sz': '50'}]]}
        avg, mid = perps_flow._limit_walk(book, True, Decimal('1'), Decimal('102'))
        self.assertEqual(avg, Decimal('101'), 'never the $150 level beyond its price')
        self.assertIsNone(perps_flow._limit_walk(book, True, Decimal('1'), Decimal('100')), 'rests whole')

    def test_a_lost_cancel_answer_is_settled_from_the_venue(self):
        self.position.flow = {**self.position.flow, 'return_plan': {
            'steps': [{'purpose': 'return_cancel', 'action': {'type': 'cancel', 'cancels': [{'a': 0, 'o': 9}]}}],
            'consumed': [], 'issued_ms': 1, 'claims': {'0': {'status': 'unconfirmed', 'at': 1}}}}
        self.position.save()
        gone = {'status': 'order', 'order': {'status': 'canceled', 'order': {'oid': 9}}}
        with mock.patch('cusd_plus.hyperliquid.info', return_value=gone):
            perps_flow._settle_lost_cancel(self.position)
        self.position.refresh_from_db()
        self.assertFalse(perps_flow._pending_claim(self.position, 'return_plan'), 'never blocks opening again')
