"""Hands-off Comprar purchases from the chat, paid by the Cuenta inteligente
(v2 relayPurchase into the escrow's depositFrom): routing
(relay_purchases.route), the chat's cards (assistant/comprar.confirmed),
execution (relay_purchases.run / finish) with the payer-bound
authorization, the owner notice, and the Purchase rule prepare."""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import override_settings
from eth_account import Account as EthAccount

from marketplace import escrow
from marketplace.models import DeliveryAddress, MarketplaceCity, Order, Product, Store
from smart_account import abi, hands_off, relay_purchases
from smart_account.models import SmartAccountRelayTx, SmartAccountRule, SmartRelayPurchase
from smart_account.tests.base import CUSD, SETTINGS, VAULT, WAD, SmartAccountTestCase

IMPL = '0x' + 'b2' * 20
OLD_IMPL = '0x' + 'b1' * 20
ESCROW = '0x' + 'e5' * 20
TX = '0x' + 'cd' * 32
SIGNER_KEY = '0x' + '11' * 32
SIGNER = EthAccount.from_key(SIGNER_KEY).address.lower()
V2 = dict(SETTINGS, SMART_ACCOUNT_V2_IMPLEMENTATION_ADDRESS=IMPL, MARKETPLACE_ESCROW_ADDRESS=ESCROW,
          MARKETPLACE_FEE_BPS=800, BSC_CHAIN_ID=56)
LIMITS = (300 * WAD, 10_000 * WAD, 0)


def local_sign(digest):
    signed = EthAccount._sign_hash(digest, private_key=SIGNER_KEY)
    sig = signed.r.to_bytes(32, 'big') + signed.s.to_bytes(32, 'big') + bytes([signed.v])
    return '0x' + sig.hex(), SIGNER


def recover(digest, sig_hex):
    return EthAccount._recover_hash(digest, signature=bytes.fromhex(sig_hex.removeprefix('0x'))).lower()


@override_settings(**V2)
class PurchaseBase(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        from marketplace.models import MarketplaceCategory
        MarketplaceCategory.objects.update_or_create(key='textiles', defaults={
            'label': 'Textiles', 'group': 'Artesanía', 'is_active': True})
        MarketplaceCity.objects.update_or_create(country_code='BO', city='La Paz', defaults={
            'currency_code': 'BOB', 'is_live': True, 'delivery_estimate': Decimal('15.00')})
        self.user = self.make_user('ana')
        self.user.country = 'BO'
        self.user.save(update_fields=['country'])
        self.own = self.make_account(self.user)
        self.personal = self.own.owner_account
        seller = self.make_user('rosa')
        self.store = Store.objects.create(owner=seller, owner_account=seller.accounts.get(account_type='personal'),
                                          name='Tejidos Rosa', country_code='BO', city='La Paz',
                                          delivery_price_usd=Decimal('5'))
        self.product = Product.objects.create(store=self.store, title='Chompa de alpaca', category='textiles',
                                              price_usd=Decimal('30.00'), stock=3, status='active')
        self.delivery = DeliveryAddress.objects.create(user=self.user, account=self.personal, label='Casa',
                                                       country_code='BO', city='La Paz',
                                                       address='Av. Arce 2345, Sopocachi', phone='+59170000000',
                                                       is_default=True)
        self.impl, self.subscribed, self.used, self.paused, self.escrow_on = IMPL, True, 0, False, True
        for target, kwargs in (
                ('smart_account.hands_off.subscribed', {'side_effect': lambda u: self.subscribed}),
                ('smart_account.hands_off.implementation_of', {'side_effect': lambda a: self.impl}),
                ('smart_account.hands_off.trade_paused', {'side_effect': lambda: self.paused}),
                ('smart_account.hands_off.bucket_of', {'side_effect': lambda a, i: (self.used, 0)}),
                ('marketplace.escrow.deposit_from_enabled', {'side_effect': lambda: self.escrow_on}),
                ('marketplace.escrow.sign_deposit', {'side_effect': local_sign}),
                ('marketplace.escrow.recover_signer', {'side_effect': recover}),
                ('marketplace.escrow.token_limits', {'return_value': LIMITS})):
            patcher = mock.patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def add_rule(self, cap=150, token_in=VAULT, payee=ESCROW):
        rule = SmartAccountRule.objects.create(
            smart_account=self.own, kind='purchase', state='onchain', active=True, onchain_id=9, token_in=token_in,
            payee_address=payee, amount=Decimal(cap), frequency='weekly', epoch=self.own.subscription_epoch)
        self.chain.rules[(self.own.contract_address.lower(), 9)] = {
            'kind': 'purchase', 'frequency': 'weekly', 'active': True, 'token_in': token_in,
            'token_out': abi.ZERO_ADDRESS, 'payee': payee, 'payout_ref': '0x' + '00' * 32,
            'amount_usd_wei': cap * WAD, 'next_run_at': 0}
        return rule

    def route(self, amount='35', personal=''):
        return relay_purchases.route(self.user, amount=Decimal(amount), personal_address=personal)


class RouteTests(PurchaseBase):
    def test_dormant_without_the_v2_implementation(self):
        with override_settings(SMART_ACCOUNT_V2_IMPLEMENTATION_ADDRESS=''):
            self.assertEqual(self.route().code, 'off')

    def test_not_subscribed_is_the_paywall(self):
        self.subscribed = False
        self.assertEqual(self.route().code, 'paywall')

    def test_v1_account_is_the_migration_prompt(self):
        self.impl = OLD_IMPL
        self.assertEqual(self.route().code, 'migrate')

    def test_paused_or_escrow_without_deposit_from_is_off(self):
        self.paused = True
        self.assertEqual(self.route().code, 'off')
        self.paused, self.escrow_on = False, False
        self.assertEqual(self.route().code, 'off')

    def test_no_purchase_rule_is_the_small_cap_card(self):
        route = self.route('35')
        self.assertEqual((route.code, route.suggested), ('no_rule', Decimal('50')))
        self.assertEqual(self.route('120').suggested, Decimal('150'))

    def test_a_rule_paying_anything_but_the_escrow_is_never_used(self):
        self.add_rule(payee='0x' + '99' * 20)
        self.fund(VAULT, self.own.contract_address, 100 * WAD)
        self.assertEqual(self.route().code, 'no_rule')

    def test_over_the_bucket_offers_raising(self):
        self.add_rule(cap=150)
        self.used = 130 * WAD
        self.fund(VAULT, self.own.contract_address, 100 * WAD)
        route = self.route('35')
        self.assertEqual((route.code, route.room), ('cap', Decimal('20.00')))
        self.assertEqual(route.suggested, Decimal('300'))     # 150 + 35: the next small choice

    def test_short_is_topup_then_move_after_it_landed(self):
        self.add_rule()
        self.assertEqual(self.route(personal=self.user.wallet).code, 'topup')
        self.fund(VAULT, self.user.wallet, 100 * WAD)
        route = self.route(personal=self.user.wallet)
        self.assertEqual(route.code, 'move')
        self.assertGreaterEqual(route.facts['move'], route.facts['short'])

    def test_a_cusd_plus_rule_needs_the_unwrap_margin(self):
        self.add_rule()
        self.fund(VAULT, self.own.contract_address, 35 * WAD)
        self.assertNotEqual(self.route('35').code, 'go')
        self.fund(VAULT, self.own.contract_address, 36 * WAD)
        self.assertEqual(self.route('35').code, 'go')

    def test_unreadable_chain_is_off(self):
        self.add_rule()
        self.chain.fail.add('balance_of')
        self.assertEqual(self.route().code, 'off')


class ChatTests(PurchaseBase):
    def belt(self):
        viewer = SimpleNamespace(user=self.user, account=self.personal, account_type='personal',
                                 is_employee=False, request_meta={})
        return SimpleNamespace(viewer=viewer, result=SimpleNamespace(), payments_ready=lambda: True)

    def data(self, **kw):
        return {'side': 'buy', 'product': self.product.pk, 'quantity': 1, 'delivery': self.delivery.pk,
                'amount': '35.00', 'nonce': 'n1', **kw}

    def answer(self, code=None, data=None, **route):
        from assistant import comprar
        patches = [mock.patch('assistant.comprar.offered', return_value=True),
                   mock.patch('smart_account.tasks.run_relay_purchase.apply_async')]
        if code is not None:
            patches.append(mock.patch('smart_account.relay_purchases.route',
                                      return_value=hands_off.Route(code, own=self.own, **route)))
        with patches[0], patches[1] as sent, (patches[2] if code else mock.MagicMock()), \
                self.captureOnCommitCallbacks(execute=True):
            out = comprar.confirmed(self.belt(), data or self.data(), 'es')
        return out, sent

    def test_subscriber_sí_makes_one_row_and_a_status_card(self):
        (done, reply, extra), sent = self.answer('go')
        self.assertTrue(done)
        row = SmartRelayPurchase.objects.get(user=self.user)
        self.assertEqual(extra['actions'], [relay_purchases.card(row)])
        self.assertEqual((row.status, row.amount_usd, row.product_id), ('pending', Decimal('35.00'), self.product.pk))
        self.assertFalse(Order.objects.exists())          # the order is the task's, never the request's
        sent.assert_called_once()
        self.assertIn('Te aviso aquí', reply)

    def test_double_sí_is_one_purchase(self):
        self.answer('go')
        (_done, _reply, extra), sent = self.answer('go')
        self.assertEqual(SmartRelayPurchase.objects.filter(user=self.user).count(), 1)
        sent.assert_not_called()
        self.assertEqual(extra['actions'][0]['type'], 'relay_purchase')

    def test_not_subscribed_is_paywall_and_hazlo_tu(self):
        (_done, _reply, extra), _sent = self.answer('paywall')
        card = extra['actions'][0]
        self.assertEqual((card['type'], card['trigger'], card['destination'], card['ticker']),
                         ('purchase_offer', 'chat_purchase', 'MarketProduct', str(self.product.pk)))
        self.assertFalse(SmartRelayPurchase.objects.exists())

    def test_off_leaves_only_hazlo_tu(self):
        (_done, _reply, extra), _sent = self.answer('off')
        self.assertEqual(extra['actions'][0]['label'], 'Hazlo tú')
        self.assertEqual(extra['actions'][0]['target'], '')

    def test_no_rule_is_the_cap_card_and_waits(self):
        (_done, _reply, extra), sent = self.answer('no_rule', suggested=Decimal('50'))
        self.assertEqual(extra['actions'][0]['type'], 'purchase_cap')
        row = SmartRelayPurchase.objects.get()
        self.assertEqual(row.status, 'waiting_rule')
        sent.assert_not_called()
        status = relay_purchases.status_of(self.user, row.internal_id)
        self.assertEqual((status['mode'], status['choices'], status['preselected']),
                         ('new', ['50', '150', '300'], '50'))

    def test_cap_offers_raising_with_the_cap_today(self):
        self.add_rule(cap=150)
        (done, reply, extra), _sent = self.answer('cap', cap=Decimal('150'))
        self.assertTrue(done)
        self.assertIn('US$150.00', reply)
        status = relay_purchases.status_of(self.user, SmartRelayPurchase.objects.get().internal_id)
        self.assertEqual((status['mode'], status['current_cap'], status['preselected']), ('raise', '150.00', '300'))

    def test_move_and_topup_and_migration(self):
        (_d, _r, extra), _s = self.answer('move', facts={'move': Decimal('40'), 'short': Decimal('20')})
        self.assertEqual(extra['actions'][0]['type'], 'purchase_move')
        self.assertEqual(SmartRelayPurchase.objects.get().status, 'waiting_move')
        (_d, _r, extra), _s = self.answer('topup', data=self.data(nonce='n2'))
        self.assertEqual((extra['actions'][0]['target'], extra['actions'][0]['why']), ('topup', 'shortfall'))
        (_d, _r, extra), _s = self.answer('migrate', data=self.data(nonce='n3'))
        self.assertEqual([a['type'] for a in extra['actions']], ['account_migration', 'purchase_offer'])

    def test_a_changed_price_is_never_bought(self):
        Product.objects.filter(pk=self.product.pk).update(price_usd=Decimal('40'))
        (done, reply, _extra), _sent = self.answer('go')
        self.assertFalse(done)
        self.assertIn('US$45', reply)
        self.assertFalse(SmartRelayPurchase.objects.exists())

    def test_resume_after_the_cap_card_runs_it(self):
        self.answer('no_rule', suggested=Decimal('50'))
        row = SmartRelayPurchase.objects.get()
        with mock.patch('smart_account.tasks.run_relay_purchase.apply_async') as sent, \
                self.captureOnCommitCallbacks(execute=True):
            relay_purchases.resume(self.user, row.internal_id)
        row.refresh_from_db()
        self.assertEqual(row.status, 'pending')
        sent.assert_called_once()

    def test_the_proposal_asks_with_the_total_and_the_place(self):
        from assistant import comprar
        belt = self.belt()
        belt.result = SimpleNamespace(pending_action=None, payment_intent=None, rule_proposal=None, declined=False,
                                      pending_categorization=None, pending_watch=None, writes=[], actions=[])
        belt.saw_web = False
        with mock.patch('assistant.confirm.recent_texts', return_value=['cómprame la chompa de alpaca']):
            out = comprar.propose(belt, 'chompa de alpaca')
        self.assertTrue(out['ok'])
        asked = belt.result.pending_action
        self.assertEqual(asked['kind'], 'purchase')
        self.assertIn('Chompa de alpaca de Tejidos Rosa por US$35 (envío incluido)', asked['question'])
        self.assertIn('Casa, La Paz', asked['question'])
        self.assertEqual(asked['data']['amount'], '35.00')
        with mock.patch('assistant.confirm.recent_texts', return_value=['cómprame un televisor']):
            belt.result.pending_action = None
            self.assertFalse(comprar.propose(belt, 'televisor')['ok'])


class ExecutionTests(PurchaseBase):
    def setUp(self):
        super().setUp()
        self.rule = self.add_rule(cap=150)
        self.fund(VAULT, self.own.contract_address, 100 * WAD)
        self.row = SmartRelayPurchase.objects.create(
            user=self.user, smart_account=self.own, nonce='x', product=self.product, quantity=1,
            delivery_address=self.delivery, amount_usd=Decimal('35.00'), title=self.product.title,
            store_name=self.store.name)
        self.notes = []
        for target, kwargs in (
                ('smart_account.relay_purchases._reply_state', {'return_value': 'shown'}),
                ('smart_account.relay_purchases.schedule_finish', {}),
                ('assistant.service.post_system_note', {'side_effect': lambda u, body, tag, **k: (
                    self.notes.append((body, tag)), (None, True))[1]})):
            patcher = mock.patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def relay_row(self, status='sent'):
        return SmartAccountRelayTx.objects.create(
            smart_account=self.own, kind=abi.RELAY_PURCHASE_KIND, source_id=str(self.row.internal_id),
            calldata='0x', signed_tx_hash=TX, status=status)

    def send_ok(self, own, calldata, kind, source_id, gas, claim):
        self.sent = calldata
        claim(TX)
        return self.relay_row(), True

    def test_success_pays_with_the_payer_bound_signature_and_posts_after_the_receipt(self):
        with mock.patch('smart_account.relayer.send_relayer_call', side_effect=self.send_ok) as send:
            relay_purchases.run(self.row.pk)
        self.assertEqual(send.call_args.args[2], abi.RELAY_PURCHASE_KIND)
        self.row.refresh_from_db()
        order = self.row.order
        self.assertEqual((self.row.status, self.row.tx_hash), ('sent', TX))
        self.assertEqual((order.status, order.deposit_tx_hash), ('depositing', TX))
        # The owner's wallet is the buyer, the account the payer; nothing for a wallet to sign.
        self.assertEqual(order.buyer_address, self.personal.bsc_address.lower())
        self.assertEqual(order.payer_address, self.own.contract_address.lower())
        self.assertEqual(order.deposit_calls, [])
        rule_id, order_id, merchant, amount, fee_bps, deadline, sig = abi.decode_relay_purchase(self.sent)
        self.assertEqual((rule_id, order_id, amount, fee_bps), (9, order.order_id32, 35 * WAD, 800))
        payer_bound = escrow.deposit_from_digest(order.order_id32, order.buyer_address, order.payer_address,
                                                 merchant, CUSD, amount, fee_bps, deadline)
        self.assertEqual(recover(payer_bound, sig.hex()), SIGNER)
        plain = escrow.deposit_digest(order.order_id32, order.buyer_address, merchant, CUSD, amount, fee_bps,
                                      deadline)
        self.assertNotEqual(recover(plain, sig.hex()), SIGNER)    # never the plain deposit digest
        self.assertEqual(self.notes, [])                           # nothing said before the receipt

        SmartAccountRelayTx.objects.filter(signed_tx_hash=TX).update(status='confirmed')
        log = {'address': self.own.contract_address, 'data': '0x' + f'{35 * WAD:064x}' * 2,
               'topics': [abi.RELAY_PURCHASED_TOPIC, '0x' + f'{9:064x}', '0x' + order.order_id32]}
        with mock.patch('smart_account.chain.receipt', return_value={'logs': [log]}), \
                mock.patch('marketplace.escrow.sync_order') as synced:
            relay_purchases.finish(self.row.pk)
        synced.assert_called_once()
        self.row.refresh_from_db()
        self.assertEqual((self.row.status, self.row.usd_counted), ('done', str(35 * WAD)))
        self.assertIn('compré Chompa de alpaca por US$35', self.notes[0][0])
        self.assertEqual(relay_purchases.status_of(self.user, self.row.internal_id)['order'], str(order.public_id))

    def test_a_forged_authorization_is_never_sent(self):
        with mock.patch('marketplace.escrow.recover_signer', return_value='0x' + '66' * 20), \
                mock.patch('smart_account.relayer.send_relayer_call') as send:
            relay_purchases.run(self.row.pk)
        send.assert_not_called()
        self.row.refresh_from_db()
        self.assertEqual((self.row.status, self.row.error_code), ('failed', 'bad_authorization'))
        self.assertEqual(self.row.order.status, 'cancelled')

    def test_unknown_broadcast_is_never_assumed_and_the_receipt_decides(self):
        def send(own, calldata, kind, source_id, gas, claim):
            claim(TX)
            self.relay_row('signed')
            raise ConnectionError('node hung up')
        with mock.patch('smart_account.relayer.send_relayer_call', side_effect=send):
            relay_purchases.run(self.row.pk)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'unknown')
        self.assertEqual(self.notes, [])
        relay_purchases.schedule_finish.assert_called_once_with(self.row.pk)
        with mock.patch('smart_account.relayer.resolve_receipt', return_value='signed'), \
                self.assertRaises(relay_purchases.Later):
            relay_purchases.finish(self.row.pk)
        SmartAccountRelayTx.objects.filter(signed_tx_hash=TX).update(status='dropped')
        relay_purchases.finish(self.row.pk)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'failed')
        self.assertEqual(self.row.order.status, 'cancelled')   # its stock comes back via the keeper
        self.assertIn('no se movió nada', self.notes[0][0])

    def test_bucket_full_at_execution_sends_nothing_and_offers_raising(self):
        self.used = 130 * WAD
        with mock.patch('smart_account.relayer.send_relayer_call') as send:
            relay_purchases.run(self.row.pk)
        send.assert_not_called()
        self.row.refresh_from_db()
        self.assertEqual((self.row.status, self.row.error_code), ('waiting_rule', 'cap'))
        self.assertTrue(self.notes[0][1].startswith(f'relay_purchase:{self.row.internal_id}:cap:'))

    def test_cap_exceeded_in_simulation_is_the_raise_offer(self):
        from smart_account.relayer import RelayError
        err = RelayError('simulation_reverted', 'execution reverted 0x' + abi.selector('CapExceeded()'))
        with mock.patch('smart_account.relayer.send_relayer_call', side_effect=err):
            relay_purchases.run(self.row.pk)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'waiting_rule')
        self.assertTrue(Order.objects.filter(status='cancelled').exists())

    def test_a_second_run_never_sends_again(self):
        with mock.patch('smart_account.relayer.send_relayer_call', side_effect=self.send_ok) as send:
            relay_purchases.run(self.row.pk)
            relay_purchases.run(self.row.pk)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(Order.objects.count(), 1)

    def test_a_withdrawn_card_cancels_before_any_order(self):
        with mock.patch('smart_account.relay_purchases._reply_state', return_value='withdrawn'), \
                mock.patch('smart_account.relayer.send_relayer_call') as send:
            relay_purchases.run(self.row.pk)
        send.assert_not_called()
        self.assertFalse(Order.objects.exists())

    def test_sold_out_says_it_is_unavailable(self):
        Product.objects.filter(pk=self.product.pk).update(stock=0)
        with mock.patch('smart_account.relayer.send_relayer_call') as send:
            relay_purchases.run(self.row.pk)
        send.assert_not_called()
        self.assertIn('ya no está disponible', self.notes[0][0])

    def event(self, tx=TX):
        return SimpleNamespace(tx_hash=tx, log_index=2, args={'id': '9', 'orderId': '0x' + 'ab' * 32,
                                                             'amount': str(35 * WAD), 'usdCounted': str(35 * WAD)})

    def test_every_relay_purchase_notifies_the_owner(self):
        SmartRelayPurchase.objects.filter(pk=self.row.pk).update(tx_hash=TX)
        with mock.patch('smart_account.notifications._send') as push, \
                mock.patch('config.ops_alerts.send_ops_alert') as ops:
            relay_purchases.on_relay_purchased(self.own, self.event())
        push.assert_called_once()
        self.assertIn('por US$35', push.call_args.args[2])
        self.assertFalse(push.call_args.kwargs['security'])
        ops.assert_not_called()
        self.assertEqual(self.notes, [])

    def test_one_nobody_asked_for_alerts_the_owner_and_ops(self):
        with mock.patch('smart_account.notifications._send') as push, \
                mock.patch('config.ops_alerts.send_ops_alert') as ops:
            relay_purchases.on_relay_purchased(self.own, self.event('0x' + '77' * 32))
        self.assertTrue(push.call_args.kwargs['security'])
        ops.assert_called_once()
        self.assertIn('No lo pediste en el chat', self.notes[0][0])


class RuleTests(PurchaseBase):
    def test_purchase_rule_pays_only_the_escrow_and_needs_face(self):
        with mock.patch('smart_account.payouts.claim_face', return_value=('face-key', True)), \
                mock.patch('smart_account.services._register', side_effect=lambda *a, **k: (a, k)) as register:
            relay_purchases.prepare_purchase_rule(self.viewer(self.user), '50.00')
        args, kwargs = register.call_args
        name, decoded = abi.decode_call(args[2][0]['data'])
        self.assertEqual(name, 'createRule')
        kind, _freq, token_in, _out, payee, _ref, amount, _first = decoded[0]
        self.assertEqual((kind, token_in.lower(), payee.lower(), amount), (abi.RULE_PURCHASE, VAULT, ESCROW, 50 * WAD))
        draft = SmartAccountRule.all_objects.get(pk=kwargs['payload']['rule_pk'])
        self.assertEqual((draft.kind, draft.standing_authorization.kind), ('purchase', 'purchase'))

    def test_purchase_caps_stay_small(self):
        from smart_account.services import PrepareError
        with self.assertRaises(PrepareError):
            relay_purchases.prepare_purchase_rule(self.viewer(self.user), '1500.00')

    def test_a_v1_account_must_migrate_first(self):
        from smart_account.services import PrepareError
        self.impl = OLD_IMPL
        with self.assertRaises(PrepareError) as raised:
            relay_purchases.prepare_purchase_rule(self.viewer(self.user), '50.00')
        self.assertEqual(raised.exception.code, 'needs_migration')


class AbiTests(SmartAccountTestCase):
    def test_relay_purchase_roundtrip_target_and_event(self):
        from smart_account import relayer
        data = abi.relay_purchase_call(9, 'ab' * 32, '0x' + '61' * 20, 5 * WAD, 800, 1_900_000_000, b'\x01' * 65)
        self.assertEqual(abi.decode_relay_purchase(data),
                         (9, 'ab' * 32, '0x' + '61' * 20, 5 * WAD, 800, 1_900_000_000, b'\x01' * 65))
        own = SimpleNamespace(contract_address='0x' + '7c' * 20)
        self.assertEqual(relayer.relay_target(own, data, abi.RELAY_PURCHASE_KIND), own.contract_address)
        with self.assertRaises(relayer.RelayError):
            relayer.relay_target(own, abi.relay_trade_call(1, '0x' + '51' * 20, b'', 1, 1), abi.RELAY_PURCHASE_KIND)
        log = {'topics': [abi.RELAY_PURCHASED_TOPIC, '0x' + f'{9:064x}', '0x' + 'ab' * 32],
               'data': '0x' + f'{5 * WAD:064x}' * 2}
        self.assertEqual(abi.decode_log(log), ('RelayPurchased', {'id': '9', 'orderId': '0x' + 'ab' * 32,
                                                                 'amount': str(5 * WAD), 'usdCounted': str(5 * WAD)}))
        self.assertEqual(abi.selector('relayPurchase(uint256,bytes32,address,uint256,uint16,uint256,bytes)'),
                         abi.SEL_RELAY_PURCHASE)
