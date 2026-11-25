"""Hands-off chat trades by the Cuenta inteligente (v2 relayTrade):
routing (hands_off.route), the chat's cards (assistant/trades._hands_off),
execution (relay_trades.run / finish) and the policy twin of _check_trade."""
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import override_settings

from smart_account import abi, hands_off, relay_trades
from smart_account.models import SmartAccountRelayTx, SmartAccountRule, SmartRelayTrade
from smart_account.tests.base import SETTINGS, VAULT, WAD, SmartAccountTestCase, new_address

IMPL = '0x' + 'b2' * 20
OLD_IMPL = '0x' + 'b1' * 20
TOKEN = '0x' + '7a' * 20
V2 = dict(SETTINGS, SMART_ACCOUNT_V2_IMPLEMENTATION_ADDRESS=IMPL)
TX = '0x' + 'ab' * 32


class HandsOffBase(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user('ana')
        self.own = self.make_account(self.user)
        self.impl = IMPL
        for target, kwargs in (
                ('smart_account.hands_off.subscribed', {'side_effect': lambda u: self.subscribed}),
                ('smart_account.hands_off.implementation_of', {'side_effect': lambda a: self.impl}),
                ('smart_account.hands_off.trade_paused', {'side_effect': lambda: False}),
                ('smart_account.hands_off.bucket_of', {'side_effect': lambda a, i: (self.used, 0)}),
                ('smart_account.hands_off.biggest_week_of_buys', {'return_value': Decimal('400')})):
            patcher = mock.patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.subscribed, self.used = True, 0

    def add_rule(self, cap=250, token_in=VAULT, token_out=abi.ZERO_ADDRESS):
        rule = SmartAccountRule.objects.create(
            smart_account=self.own, kind='trade', state='onchain', active=True, onchain_id=7, token_in=token_in,
            amount=Decimal(cap), frequency='weekly', epoch=self.own.subscription_epoch)
        self.chain.rules[(self.own.contract_address.lower(), 7)] = {
            'kind': 'trade', 'frequency': 'weekly', 'active': True, 'token_in': token_in, 'token_out': token_out,
            'payee': abi.ZERO_ADDRESS, 'payout_ref': '0x' + '00' * 32, 'amount_usd_wei': cap * WAD,
            'next_run_at': 0}
        return rule

    def route(self, side='buy', amount='20', sell_all=False, personal=''):
        return hands_off.route(self.user, side=side, asset_kind='stock', token=TOKEN,
                               amount=None if amount is None else Decimal(amount), sell_all=sell_all,
                               personal_address=personal)


@override_settings(**V2)
class RouteTests(HandsOffBase):
    def test_dormant_without_the_v2_implementation(self):
        with override_settings(SMART_ACCOUNT_V2_IMPLEMENTATION_ADDRESS=''):
            self.assertEqual(self.route().code, 'off')

    def test_not_subscribed_is_the_paywall(self):
        self.subscribed = False
        self.assertEqual(self.route().code, 'paywall')

    def test_v1_account_is_the_migration_prompt(self):
        self.impl = OLD_IMPL
        self.assertEqual(self.route().code, 'migrate')

    def test_no_trade_rule_is_the_cap_card_preselected_from_history(self):
        route = self.route()
        self.assertEqual(route.code, 'no_rule')
        self.assertEqual(route.suggested, Decimal('1000'))   # 2 x US$400 -> the smallest choice covering it

    def test_bucket_exceeded_offers_raising(self):
        self.add_rule(cap=250)
        self.used = 240 * WAD
        self.fund(VAULT, self.own.contract_address, 500 * WAD)
        route = self.route(amount='20')
        self.assertEqual(route.code, 'cap')
        self.assertEqual(route.room, Decimal('10.00'))
        self.assertGreaterEqual(route.suggested, Decimal('270'))

    def test_neither_wallet_covers_is_the_topup(self):
        self.add_rule()
        personal = self.user.wallet
        self.assertEqual(self.route(personal=personal).code, 'topup')
        self.fund(VAULT, personal, 50 * WAD)
        # After the Koywe top-up lands in the personal wallet: the move into the account, not a second top-up.
        route = self.route(personal=personal)
        self.assertEqual(route.code, 'move')
        self.assertEqual(route.facts['move'], Decimal('40'))

    def test_a_cusd_trade_rule_is_never_used(self):
        from smart_account.tests.base import CUSD
        self.add_rule(token_in=CUSD)
        self.fund(VAULT, self.own.contract_address, 50 * WAD)
        self.assertEqual(self.route().code, 'no_rule')

    def test_account_covers_it_goes_hands_off(self):
        self.add_rule()
        self.fund(VAULT, self.own.contract_address, 50 * WAD)
        self.assertEqual(self.route().code, 'go')

    def test_sell_of_what_only_the_personal_wallet_holds_is_the_signed_card(self):
        self.add_rule()
        self.assertEqual(self.route(side='sell', amount=None, sell_all=True).code, 'personal')
        self.fund(TOKEN, self.own.contract_address, 3 * WAD)
        self.assertEqual(self.route(side='sell', amount=None, sell_all=True).code, 'go')

    def test_a_sell_beyond_the_bucket_offers_raising(self):
        self.add_rule(cap=250)
        self.fund(TOKEN, self.own.contract_address, 3 * WAD)
        self.used = 100 * WAD
        with mock.patch('smart_account.hands_off.sell_value', return_value=Decimal('200')):
            route = self.route(side='sell', amount=None, sell_all=True)
        self.assertEqual(route.code, 'cap')
        self.assertGreaterEqual(route.suggested, Decimal('350'))

    def test_unreadable_chain_is_todays_card(self):
        self.add_rule()
        self.chain.fail.add('balance_of')
        self.assertEqual(self.route().code, 'off')


@override_settings(**V2)
class ChatCardTests(HandsOffBase):
    def belt(self, meta=None):
        from smart_account.context import personal_account
        return SimpleNamespace(viewer=SimpleNamespace(user=self.user, account=personal_account(self.user),
                                                      request_meta=meta or {}))

    def answer(self, code, data=None, **route):
        from assistant import trades
        data = data or {'side': 'buy', 'ticker': 'TSLA', 'sell_all': False, 'amount': '20.00', 'kind': 'stock',
                        'nonce': 'n1'}
        signed = {'type': 'trade', 'ticker': 'TSLA', 'target': 'buy:20.00', 'label': 'x'}
        with mock.patch('smart_account.hands_off.route', return_value=hands_off.Route(code, own=self.own, **route)), \
                mock.patch('smart_account.relay_trades.asset_token', return_value=TOKEN), \
                mock.patch('smart_account.tasks.run_relay_trade.apply_async') as sent, \
                self.captureOnCommitCallbacks(execute=True):
            out = trades._hands_off(self.belt(), data, 'es', signed_card=signed,
                                    diy=trades._diy_screen('stock', 'buy', 'TSLA'))
        return out, sent

    def test_subscriber_sí_makes_one_row_and_a_status_card(self):
        (done, _reply, extra), sent = self.answer('go')
        self.assertTrue(done)
        row = SmartRelayTrade.objects.get(user=self.user)
        self.assertEqual(extra['actions'], [relay_trades.card(row)])
        self.assertEqual(row.status, 'pending')
        sent.assert_called_once()

    def test_double_sí_is_idempotent(self):
        self.answer('go')
        (_done, _reply, extra), sent = self.answer('go')
        self.assertEqual(SmartRelayTrade.objects.filter(user=self.user).count(), 1)
        sent.assert_not_called()
        self.assertEqual(extra['actions'][0]['type'], 'relay_trade')

    def test_not_subscribed_is_paywall_and_hazlo_tu(self):
        (_done, _reply, extra), _sent = self.answer('paywall')
        types = [a['type'] for a in extra['actions']]
        self.assertEqual(types, ['trade_offer', 'trade'])
        self.assertEqual(extra['actions'][0]['trigger'], 'chat_trade')
        self.assertFalse(SmartRelayTrade.objects.exists())

    def test_no_rule_is_the_cap_card_and_waits(self):
        (_done, _reply, extra), sent = self.answer('no_rule', suggested=Decimal('1000'))
        card = extra['actions'][0]
        self.assertEqual((card['type'], card['mode'], card['preselected']), ('trade_cap', 'new', '1000'))
        self.assertEqual(card['choices'], ['250', '1000', '2500'])
        self.assertEqual(SmartRelayTrade.objects.get().status, 'waiting_rule')
        sent.assert_not_called()

    def test_cap_exceeded_offers_raising_never_a_bare_refusal(self):
        (done, reply, extra), _sent = self.answer('cap', cap=Decimal('250'), suggested=Decimal('1000'))
        self.assertTrue(done)
        self.assertEqual(extra['actions'][0]['mode'], 'raise')
        self.assertIn('US$250.00', reply)

    def test_no_balance_offers_the_topup(self):
        (_done, _reply, extra), _sent = self.answer('topup')
        self.assertEqual(extra['actions'][0]['target'], 'topup')
        self.assertEqual(extra['actions'][0]['why'], 'shortfall')

    def test_v1_account_is_the_migration_card(self):
        (_done, _reply, extra), _sent = self.answer('migrate')
        self.assertEqual([a['type'] for a in extra['actions']], ['account_migration', 'trade'])

    def test_off_and_personal_leave_todays_card(self):
        self.assertIsNone(self.answer('off')[0])
        self.assertIsNone(self.answer('personal')[0])

    def test_resume_after_the_cap_card_runs_the_trade(self):
        self.answer('no_rule', suggested=Decimal('250'))
        row = SmartRelayTrade.objects.get()
        with mock.patch('smart_account.tasks.run_relay_trade.apply_async') as sent, \
                self.captureOnCommitCallbacks(execute=True):
            relay_trades.resume(self.user, row.internal_id)
        row.refresh_from_db()
        self.assertEqual(row.status, 'pending')
        sent.assert_called_once()


@override_settings(**V2)
class IosTests(HandsOffBase):
    IOS = {'HTTP_X_CONFIO_PLATFORM': 'ios'}

    def test_gold_and_bitcoin_never_offered_to_ios(self):
        from assistant import trades
        viewer = SimpleNamespace(user=self.user, request_meta=self.IOS)
        with mock.patch('cusd_plus.crypto_risk.surfaces_enabled', return_value=True), \
                mock.patch('cusd_plus.crypto_risk.trading_ready', return_value=True):
            self.assertFalse(trades.crypto_offered(viewer))
            self.assertTrue(trades.crypto_offered(SimpleNamespace(user=self.user, request_meta={
                'HTTP_X_CONFIO_PLATFORM': 'android'})))
        belt = SimpleNamespace(viewer=viewer)
        out = trades._confirmed_crypto(belt, {'side': 'buy', 'ticker': 'BTCB', 'kind': 'crypto'}, 'es')
        self.assertFalse(out[0])

    def test_an_ios_crypto_row_never_executes(self):
        row = SmartRelayTrade.objects.create(user=self.user, smart_account=self.own, nonce='x', side='buy',
                                             asset_kind='crypto', ticker='BTCB', amount_usd=Decimal('20'),
                                             meta=self.IOS)
        with mock.patch('smart_account.relay_trades._reply_state', return_value='shown'), \
                mock.patch('smart_account.relayer.send_relayer_call') as send, \
                mock.patch('assistant.service.post_system_note', return_value=(None, False)):
            relay_trades.run(row.pk)
        send.assert_not_called()
        row.refresh_from_db()
        self.assertEqual((row.status, row.error_code), ('failed', 'ios_no_crypto'))


@override_settings(**V2)
class ExecutionTests(HandsOffBase):
    def setUp(self):
        super().setUp()
        self.rule = self.add_rule(cap=250)
        self.row = SmartRelayTrade.objects.create(user=self.user, smart_account=self.own, nonce='x', side='buy',
                                                  asset_kind='stock', ticker='TSLA', amount_usd=Decimal('20'))
        self.params = {'kind': 'stock_buy', 'venue': '0x' + '51' * 20, 'token_in': VAULT, 'token_out': TOKEN,
                       'max_in': 20 * WAD, 'min_out': 1}
        self.notes = []
        for target, kwargs in (
                ('smart_account.relay_trades._reply_state', {'return_value': 'shown'}),
                ('smart_account.hands_off.route', {'side_effect': lambda *a, **k: hands_off.Route(
                    'go', own=self.own, rule=self.rule)}),
                ('smart_account.hands_off.gap_wait_seconds', {'return_value': 0}),
                ('smart_account.relay_trades.asset_token', {'return_value': TOKEN}),
                ('smart_account.relay_trades.build', {'return_value': {'to': '0x' + '51' * 20, 'value': '0',
                                                                     'data': '0xdeadbeef'}}),
                ('smart_account.services.trade_parameters', {'side_effect': lambda c: dict(self.params)}),
                ('smart_account.relay_policy.check_relay_trade', {'side_effect': lambda *a: dict(self.params)}),
                ('smart_account.relay_trades.schedule_finish', {}),
                ('assistant.service.post_system_note', {'side_effect': lambda u, body, tag, **k: (
                    self.notes.append((body, tag)), (None, True))[1]})):
            patcher = mock.patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def relay_row(self, status='sent'):
        return SmartAccountRelayTx.objects.create(
            smart_account=self.own, kind=abi.RELAY_TRADE_KIND, source_id=str(self.row.internal_id),
            calldata='0x', signed_tx_hash=TX, status=status)

    def test_success_sends_relay_trade_and_posts_after_the_receipt(self):
        def send(own, calldata, kind, source_id, gas, claim):
            self.assertEqual(kind, abi.RELAY_TRADE_KIND)
            rule_id, _venue, data, max_in, _min_out = abi.decode_relay_trade(calldata)
            self.assertEqual((rule_id, data, max_in), (7, bytes.fromhex('deadbeef'), 20 * WAD))
            claim(TX)
            return self.relay_row(), True
        with mock.patch('smart_account.relayer.send_relayer_call', side_effect=send):
            relay_trades.run(self.row.pk)
        self.row.refresh_from_db()
        self.assertEqual((self.row.status, self.row.tx_hash), ('sent', TX))
        self.assertEqual(self.notes, [])          # nothing said before the receipt

        SmartAccountRelayTx.objects.filter(signed_tx_hash=TX).update(status='confirmed')
        data = '0x' + ''.join(f'{v:064x}' for v in (int(VAULT, 16), int(TOKEN, 16), 19 * WAD, 3 * WAD, 19 * WAD))
        log = {'address': self.own.contract_address, 'data': data,
               'topics': [abi.RELAY_TRADED_TOPIC, '0x' + f'{7:064x}', '0x' + '00' * 12 + '51' * 20]}
        with mock.patch('smart_account.chain.receipt', return_value={'logs': [log]}):
            relay_trades.finish(self.row.pk)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'done')
        self.assertEqual(self.row.usd_counted, str(19 * WAD))
        self.assertIn('compré TSLA por US$19', self.notes[0][0])

    def test_simulation_revert_fails_and_says_nothing_moved(self):
        from smart_account.relayer import RelayError
        with mock.patch('smart_account.relayer.send_relayer_call', side_effect=RelayError('simulation_reverted')):
            relay_trades.run(self.row.pk)
        self.row.refresh_from_db()
        self.assertEqual((self.row.status, self.row.error_code), ('failed', 'simulation_reverted'))
        self.assertIn('no se movió nada', self.notes[0][0])

    def test_unknown_broadcast_is_never_assumed_and_the_receipt_decides(self):
        def send(own, calldata, kind, source_id, gas, claim):
            claim(TX)
            self.relay_row('signed')
            raise ConnectionError('node hung up')
        with mock.patch('smart_account.relayer.send_relayer_call', side_effect=send):
            relay_trades.run(self.row.pk)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'unknown')
        self.assertEqual(self.notes, [])
        relay_trades.schedule_finish.assert_called_once_with(self.row.pk)
        with mock.patch('smart_account.relayer.resolve_receipt', return_value='signed'), \
                self.assertRaises(relay_trades.Later):
            relay_trades.finish(self.row.pk)
        SmartAccountRelayTx.objects.filter(signed_tx_hash=TX).update(status='dropped')
        relay_trades.finish(self.row.pk)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'failed')

    def test_bucket_exceeded_at_execution_sends_nothing(self):
        self.used = 240 * WAD
        with mock.patch('smart_account.relayer.send_relayer_call') as send:
            relay_trades.run(self.row.pk)
        send.assert_not_called()
        self.row.refresh_from_db()
        self.assertEqual((self.row.status, self.row.error_code), ('waiting_rule', 'cap'))

    def test_a_sell_counts_in_the_bucket_at_execution(self):
        self.row.side, self.row.amount_usd = 'sell', Decimal('20')
        self.row.save()
        self.params.update(kind='stock_sell', token_in=TOKEN, token_out=VAULT, max_in=WAD, min_out=20 * WAD)
        self.used = 235 * WAD          # 235 + 20 x 1.03 > 250
        with mock.patch('smart_account.relayer.send_relayer_call') as send:
            relay_trades.run(self.row.pk)
        send.assert_not_called()
        self.row.refresh_from_db()
        self.assertEqual((self.row.status, self.row.error_code), ('waiting_rule', 'cap'))

    def test_cap_exceeded_on_chain_is_the_raise_offer(self):
        from smart_account.relayer import RelayError
        err = RelayError('simulation_reverted', 'execution reverted 0x' + abi.selector('CapExceeded()'))
        with mock.patch('smart_account.relayer.send_relayer_call', side_effect=err):
            relay_trades.run(self.row.pk)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'waiting_rule')
        self.assertEqual(self.notes[0][1], f'relay_trade:{self.row.internal_id}:cap')

    def test_below_feed_requotes_once_then_says_the_price_moved(self):
        from smart_account.relayer import RelayError
        err = RelayError('simulation_reverted', 'execution reverted 0x' + abi.selector('BelowFeed()'))
        with mock.patch('smart_account.relayer.send_relayer_call', side_effect=err) as send:
            with self.assertRaises(relay_trades.Later):
                relay_trades.run(self.row.pk)
            relay_trades.run(self.row.pk)
        self.assertEqual(send.call_count, 2)
        self.row.refresh_from_db()
        self.assertEqual((self.row.status, self.row.error_code), ('failed', 'below_feed'))
        self.assertIn('el precio se movió', self.notes[0][0])

    def relay_event(self):
        return SimpleNamespace(tx_hash=TX, log_index=3, args={
            'id': '7', 'tokenIn': VAULT, 'tokenOut': TOKEN, 'amountIn': str(20 * WAD), 'amountOut': str(WAD)})

    def test_every_relay_trade_alerts_the_owner(self):
        self.row.tx_hash = TX
        self.row.save()
        with mock.patch('smart_account.notifications._send') as push, \
                mock.patch('config.ops_alerts.send_ops_alert') as ops, \
                mock.patch('smart_account.relay_trades._asset_name', return_value='TSLA'):
            relay_trades.on_relay_traded(self.own, self.relay_event())
        push.assert_called_once()
        self.assertIn('compró TSLA por US$20', push.call_args.args[2])
        ops.assert_not_called()
        self.assertEqual(self.notes, [])        # the chat trade's own result note tells it

    def test_a_relay_trade_nobody_asked_for_goes_to_ops_too(self):
        with mock.patch('smart_account.notifications._send') as push, \
                mock.patch('config.ops_alerts.send_ops_alert') as ops, \
                mock.patch('smart_account.relay_trades._asset_name', return_value='TSLA'):
            relay_trades.on_relay_traded(self.own, self.relay_event())
        self.assertTrue(push.call_args.kwargs['security'])
        ops.assert_called_once()
        self.assertIn('No lo pediste en el chat', self.notes[0][0])

    def test_a_withdrawn_card_cancels(self):
        with mock.patch('smart_account.relay_trades._reply_state', return_value='withdrawn'), \
                mock.patch('smart_account.relayer.send_relayer_call') as send:
            relay_trades.run(self.row.pk)
        send.assert_not_called()
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'cancelled')

    def test_a_second_run_never_sends_again(self):
        with mock.patch('smart_account.relayer.send_relayer_call',
                        side_effect=lambda *a, **k: (k['claim'](TX), (self.relay_row(), True))[1]) as send:
            relay_trades.run(self.row.pk)
            relay_trades.run(self.row.pk)
        self.assertEqual(send.call_count, 1)


class AbiTests(SmartAccountTestCase):
    def test_relay_trade_roundtrip_and_relayer_target(self):
        from smart_account import relayer
        data = abi.relay_trade_call(3, '0x' + '51' * 20, b'\x01\x02', 5, 4)
        self.assertEqual(abi.decode_relay_trade(data), (3, '0x' + '51' * 20, b'\x01\x02', 5, 4))
        own = SimpleNamespace(contract_address=new_address())
        self.assertEqual(relayer.relay_target(own, data, abi.RELAY_TRADE_KIND), own.contract_address.lower())
        with self.assertRaises(relayer.RelayError):
            relayer.relay_target(own, abi.encode_call('collectFee'), abi.RELAY_TRADE_KIND)

    def test_trade_kind_is_appended_after_card(self):
        self.assertEqual((abi.RULE_KIND_IDS['card'], abi.RULE_KIND_IDS['trade'], abi.RULE_KIND_IDS['purchase']),
                         (3, 4, 5))


@override_settings(**V2)
class MoveAndFaceTests(HandsOffBase):
    def test_move_card_then_resume(self):
        from assistant import trades
        from smart_account.context import personal_account
        belt = SimpleNamespace(viewer=SimpleNamespace(user=self.user, account=personal_account(self.user),
                                                      request_meta={}))
        data = {'side': 'buy', 'ticker': 'TSLA', 'sell_all': False, 'amount': '20.00', 'kind': 'stock',
                'nonce': 'm1'}
        route = hands_off.Route('move', own=self.own, facts={'move': Decimal('40'), 'short': Decimal('20')})
        with mock.patch('smart_account.hands_off.route', return_value=route), \
                mock.patch('smart_account.relay_trades.asset_token', return_value=TOKEN):
            _done, reply, extra = trades._hands_off(belt, data, 'es', signed_card=None, diy=None)
        self.assertEqual(extra['actions'][0]['type'], 'trade_move')
        self.assertIn('US$40', reply)
        row = SmartRelayTrade.objects.get()
        self.assertEqual(row.status, 'waiting_move')
        from smart_account import services
        with mock.patch('smart_account.relay_trades.move_route', return_value=route), \
                mock.patch('smart_account.services.prepare_deposit', side_effect=lambda v, d: d) as deposit:
            out = services.prepare_trade_move(self.viewer(self.user), row.internal_id)
        self.assertEqual(out, [{'asset_key': 'cusd_plus', 'units': str(40 * WAD)}])
        deposit.assert_called_once()

    def test_trade_rule_is_cusd_plus_and_needs_face(self):
        from smart_account import relay_policy, services
        from smart_account.models import SmartAccountPreparedAction
        with mock.patch('smart_account.payouts.claim_face', return_value=('face-key', True)):
            batch = services.prepare_trade_rule(self.viewer(self.user), '1000.00')
        _name, args = abi.decode_call(batch.calls[0]['data'])
        self.assertEqual((args[0][0], args[0][2]), (abi.RULE_TRADE, VAULT))
        action = SmartAccountPreparedAction.objects.get(request_id=batch.request_id)
        draft = SmartAccountRule.all_objects.get(pk=action.payload['rule_pk'])
        self.assertEqual((draft.kind, draft.standing_authorization.kind), ('trade', 'trade'))
        with mock.patch('security.face_step_up.require_face_step_up', return_value='') as face:
            self.assertIsNone(relay_policy.face_refusal(action, self.user))
        self.assertEqual(face.call_args.kwargs['action_key'], 'face-key')
        draft.standing_authorization = None
        draft.save()
        self.assertTrue(relay_policy.face_refusal(action, self.user))


@override_settings(**V2)
class MigrationTests(HandsOffBase):
    def setUp(self):
        super().setUp()
        self.impl = OLD_IMPL
        self.held = [SimpleNamespace(address=VAULT, units=30 * WAD), SimpleNamespace(address=TOKEN, units=2 * WAD)]
        patcher = mock.patch('smart_account.assets.assets_of', side_effect=lambda a: list(self.held))
        patcher.start()
        self.addCleanup(patcher.stop)
        SmartAccountRule.objects.create(
            smart_account=self.own, kind='buy', state='onchain', active=True, onchain_id=3, token_in=VAULT,
            token_out=TOKEN, amount=Decimal('25'), frequency='weekly', epoch=self.own.subscription_epoch)
        SmartAccountRule.objects.create(
            smart_account=self.own, kind='send', state='onchain', active=True, onchain_id=4, token_in=VAULT,
            amount=Decimal('5'), frequency='weekly', epoch=self.own.subscription_epoch)

    def prepare(self):
        from smart_account import services
        from smart_account.models import SmartAccountPreparedAction
        with mock.patch('smart_account.payouts.claim_face', return_value=('mig-key', True)):
            batch = services.prepare_migration(self.viewer(self.user), '1000.00')
        return batch, SmartAccountPreparedAction.objects.get(request_id=batch.request_id)

    def names(self, calls):
        out = []
        for c in calls:
            if c['data'][2:10] == abi.SEL_MIGRATE:
                out.append('migrate')
            elif c['data'][2:10] == abi.SEL_TRANSFER:
                out.append('transfer')
            else:
                out.append(abi.decode_call(c['data'])[0])
        return out

    def test_end_to_end_prepare_validate_face_and_mirror(self):
        from smart_account import reconcile, relay_policy
        from smart_account.models import SmartAccount, SmartAccountEvent
        batch, action = self.prepare()
        signer = self.user.wallet
        new = self.chain.predict_address_at(signer, 1).lower()
        self.assertEqual(self.names(batch.calls), ['cancelSubscription', 'migrate', 'withdrawAll', 'transfer',
                                                   'transfer', 'createRule', 'createRule'])
        self.assertEqual(action.payload['new_account'], new)
        self.assertIn('Tus envíos, pagos y tarjeta se vuelven a crear desde la nueva cuenta.', batch.summary)
        # The relay accepts exactly this batch, and asks this batch's Face.
        self.assertEqual(relay_policy.validate_batch(batch.calls, self.user, signer, batch.request_id), action)
        with mock.patch('security.face_step_up.require_face_step_up', return_value='') as face:
            self.assertIsNone(relay_policy.face_refusal(action, self.user))
        self.assertEqual(face.call_args.kwargs['action_key'], 'mig-key')
        # Mined: AccountCreated + AccountMigrated in one transaction move the person to the new account.
        tx = '0x' + 'cd' * 32
        factory = SETTINGS['SMART_ACCOUNT_FACTORY_ADDRESS']
        common = dict(address=factory, block_number=10, block_hash='0x' + '00' * 32, tx_hash=tx)
        from django.utils import timezone
        created = SmartAccountEvent.objects.create(name='AccountCreated', log_index=1, block_time=timezone.now(),
                                                   args={'owner': signer, 'account': new}, **common)
        migrated = SmartAccountEvent.objects.create(
            name='AccountMigrated', log_index=2, block_time=timezone.now(),
            args={'owner': signer, 'from': self.own.contract_address.lower(), 'to': new, 'generation': '1'}, **common)
        reconcile.apply_event(created)
        with mock.patch('assistant.service.post_system_note', return_value=(None, True)) as note:
            for effect in reconcile.apply_event(migrated):
                effect()
        from smart_account.context import own_account
        self.assertEqual(own_account(self.user).contract_address.lower(), new)
        self.assertIsNotNone(SmartAccount.all_objects.get(pk=self.own.pk).deleted_at)
        self.assertEqual(own_account(self.user).account.account_index, 0)
        note.assert_called_once()

    def test_a_tampered_migration_is_refused(self):
        from cusd_plus.sponsor_7702 import PolicyError
        from smart_account import relay_policy
        batch, action = self.prepare()
        thief = new_address()
        bad = [dict(c) for c in batch.calls]
        bad[3] = abi.transfer_call(VAULT, thief, 30 * WAD)
        with self.assertRaises(PolicyError):
            relay_policy._check_migration(action, bad, self.user, self.user.wallet)
        no_trade = [c for c in batch.calls][:-1]
        with self.assertRaises(PolicyError):
            relay_policy._check_migration(action, no_trade, self.user, self.user.wallet)

    def test_a_v2_account_is_not_migrated_again(self):
        from smart_account import services
        self.impl = IMPL
        with self.assertRaises(services.PrepareError) as raised:
            services.prepare_migration(self.viewer(self.user))
        self.assertEqual(raised.exception.code, 'already_current')


def _has_indexer():
    import importlib.util
    return importlib.util.find_spec('inbox.account_trades') is not None


@unittest.skipUnless(_has_indexer(), 'the portfolio builder (inbox/account_trades.py) is not in this tree')
@override_settings(**V2)
class IndexerTests(HandsOffBase):
    def test_stored_trades_are_indexed_after_commit(self):
        from django.utils import timezone
        from smart_account import reconcile
        address = self.own.contract_address.lower()
        word = lambda v: f'{v:064x}'  # noqa: E731
        traded = {'address': address, 'blockNumber': hex(5), 'logIndex': hex(0), 'transactionHash': TX,
                  'topics': [abi.event_topic('Traded', abi.ACCOUNT_EVENTS['Traded']), '0x' + word(int(TOKEN, 16)),
                             '0x' + word(int(VAULT, 16)), '0x' + word(int(TOKEN, 16))],
                  'data': '0x' + word(10) + word(20)}
        relay = {'address': address, 'blockNumber': hex(5), 'logIndex': hex(1), 'transactionHash': TX,
                 'topics': [abi.RELAY_TRADED_TOPIC, '0x' + word(7), '0x' + word(int(TOKEN, 16))],
                 'data': '0x' + word(int(VAULT, 16)) + word(int(TOKEN, 16)) + word(10) + word(20) + word(10)}
        with mock.patch('smart_account.chain.block_time', return_value=(timezone.now(), '0x' + '00' * 32)), \
                mock.patch('inbox.account_trades.index_events', return_value=2) as index, \
                self.captureOnCommitCallbacks(execute=True):
            reconcile._store_logs([traded, relay], '0x' + 'fa' * 20, {address: self.own}, {})
        events = index.call_args.args[0]
        self.assertEqual(sorted(e.name for e in events), ['RelayTraded', 'Traded'])
        self.assertTrue(index.call_args.kwargs['allow_rpc'])


class ServedCardTests(SmartAccountTestCase):
    def test_hands_off_cards_serve_the_request(self):
        from datetime import timedelta
        from django.utils import timezone
        from assistant.engine import payment_texts
        now = timezone.now()
        for kind in ('relay_trade', 'trade_cap', 'trade_move', 'trade_offer', 'account_migration'):
            history = [SimpleNamespace(sender_type='USER', body='compra 20 de tesla', metadata={},
                                       created_at=now - timedelta(minutes=2)),
                       SimpleNamespace(sender_type='AGENT', body='ok', metadata={'actions': [{'type': kind}]},
                                       created_at=now - timedelta(minutes=1)),
                       SimpleNamespace(sender_type='USER', body='gracias', metadata={}, created_at=now)]
            self.assertEqual(payment_texts(history), ['gracias'], kind)
