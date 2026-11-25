"""A purchase the account pays (spec decisions 37 to 42, 3.6), end to end on the
real code: smart_account.purchases (standing, the "Compras con Confío IA" rule
and the move batches), agent_tasks.account_pay, payment_accounts.purchase_funding
and the contract-funded bridge and journey workers. Only HTTP (the chains,
Relay, Infinia), the KMS signer, Confío Face, notes and alerts are faked."""
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from eth_abi import encode as abi_encode

from agent_tasks import account_pay, notes, runner
from agent_tasks.models import AgentTask
from payment_accounts import contract_funding, payment_intents, purchase_funding
from payment_accounts.models import InfiniaJourney, PaymentBridgeTransfer, PaymentIntent, PayoutDestination
from smart_account import abi, purchases, relayer
from smart_account.models import SmartAccountCardSpender, SmartAccountRelayTx, SmartAccountRule
from smart_account.tests import infinia_world as w
from smart_account.tests.infinia_base import SETTINGS, InfiniaPayoutSteps

SPENDER = '0x' + '5e' * 20
STORE_CLABE = '646180157000000004'      # fake
ORDER = {'amount': '925.00', 'reference': 'Pedido 4471'}
TOTAL_USD = Decimal('52.00')
WAD = 10 ** 18


def event(address, name, fields, values):
    topics, kinds, plain = [abi.event_topic(name, fields)], [], []
    for (kind, indexed, _arg), value in zip(fields, values):
        if indexed:
            topics.append('0x' + abi_encode([kind], [value]).hex())
        else:
            kinds.append(kind)
            plain.append(value)
    return {'address': address, 'topics': topics, 'removed': False, 'data': '0x' + abi_encode(kinds, plain).hex()}


class PurchaseWorld(w.World):
    """The world, plus the factory's card allowlist, Card rules and the
    purchase spender, behaving as ConfioPurchaseSpender and cardPull do."""

    def __init__(self):
        super().__init__()
        self.card_allowed = True
        self.card_spent = {}
        self.tamper = None          # changes the mined logs of a pull

    def gross(self, out):
        return (out * 10_000 + (10_000 - self.fee_bps) - 1) // (10_000 - self.fee_bps)

    def pull(self, data, sender, *, apply):
        account, rule_id, out, to, ref = abi.decode_purchase_pull(data)
        if sender.lower() != w.SPONSOR:
            raise w.Revert('NotOperator')
        if to in (abi.ZERO_ADDRESS, SPENDER, account, w.SPONSOR):
            raise w.Revert('BadTarget')
        rule = self.rules.get((account, rule_id))
        if rule is None or not rule['active'] or rule.get('kind') != 'card':
            raise w.Revert('BadRule')
        if rule['payee'] != SPENDER:
            raise w.Revert('NotSpender')
        if not self.card_allowed:
            raise w.Revert('SpenderNotAllowed')
        now, gap = int(timezone.now().timestamp()), abi.MIN_GAP_DAYS[rule['frequency']] * 86400
        spent = self.card_spent.get((account, rule_id), 0)
        if now >= rule['next_run_at'] + gap:
            spent = 0
        gross = self.gross(out)
        if spent + gross > rule['amount_usd_wei']:
            raise w.Revert('CapExceeded')
        if self.balances.get((rule['token_in'], account), 0) < gross:
            raise w.Revert('ERC20InsufficientBalance')
        if apply:
            self.card_spent[(account, rule_id)] = spent + gross
            self.balances[(rule['token_in'], account)] -= gross
        return account, rule_id, out, to, ref, gross

    def mine_execute(self, tx_hash, tx):
        if tx['to'].lower() != SPENDER:
            return super().mine_execute(tx_hash, tx)
        try:
            account, rule_id, out, to, ref, gross = self.pull(tx['data'], w.SPONSOR, apply=True)
        except w.Revert:
            receipt = self.mine('BSC', tx_hash, [], status=0)
        else:
            logs = [w.transfer_log(w.USDT, w.CUSD, account, out),
                    w.transfer_log(w.USDT, account, SPENDER, out),
                    event(account, 'CardPulled', abi.ACCOUNT_EVENTS['CardPulled'], [rule_id, SPENDER, out, gross]),
                    w.transfer_log(w.USDT, SPENDER, to, out),
                    event(SPENDER, 'Forwarded', abi.FORWARDED_FIELDS, [account, rule_id, to, out, ref])]
            if self.tamper:
                logs = self.tamper(logs)
            receipt = self.mine('BSC', tx_hash, logs)
        receipt['to'] = SPENDER
        return receipt

    def eth_call(self, chain, call):
        to, data = call['to'].lower(), call['data'].lower()
        sel, args = data[2:10], bytes.fromhex(data[10:])
        enc = lambda types, values: '0x' + abi_encode(types, values).hex()
        if to == w.FACTORY and sel == w.selector('cardSpenderAllowed(address)'):
            return enc(['bool'], [self.card_allowed])
        if to == SPENDER and sel == abi.SEL_PURCHASE_PULL:
            self.pull(data, call.get('from') or '', apply=False)
            return '0x'
        if to in self.accounts and sel == w.selector('cardSpentUsd(uint256)'):
            from eth_abi import decode
            return enc(['uint256'], [self.card_spent.get((to, decode(['uint256'], args)[0]), 0)])
        if to in self.accounts and sel == w.selector('rule(uint256)'):
            from eth_abi import decode
            rule = self.rules[(to, decode(['uint256'], args)[0])]
            if rule.get('kind') == 'card':
                return enc([abi.RULE_ABI], [(
                    abi.RULE_CARD, abi.FREQUENCY_IDS[rule['frequency']], rule['active'], rule['token_in'],
                    abi.ZERO_ADDRESS, rule['payee'], b'\0' * 32, rule['amount_usd_wei'], rule['next_run_at'],
                    rule['epoch'])])
        return super().eth_call(chain, call)


@override_settings(**SETTINGS, SMART_ACCOUNT_PURCHASE_SPENDER_ADDRESS=SPENDER, BSC_SPONSOR_ADDRESS=w.SPONSOR,
                   SMART_ACCOUNT_CARD_RULES_ENABLED=True)
class PurchasePaidByTheAccountTests(InfiniaPayoutSteps, TestCase):

    def setUp(self):
        with mock.patch.object(w, 'World', PurchaseWorld):
            super().setUp()
        self.posted = mock.Mock(return_value=1)
        patcher = mock.patch('agent_tasks.notes.post', self.posted)
        patcher.start()
        self.addCleanup(patcher.stop)
        SmartAccountCardSpender.objects.create(address=SPENDER, allowed=True, label=purchases.RULE_LABEL)

    # ── fixtures ───────────────────────────────────────────────────────

    def switch_on(self, cap='200.00'):
        """The owner signs "Compras con Confío IA" (with Face) and it is mined."""
        faced = self.face.call_count
        batch = self.step(purchases.prepare_purchase_rule, self.viewer(), cap)
        self.assertGreater(self.face.call_count, faced, 'signed without Face')
        _name, args = abi.decode_call(batch.calls[0]['data'])
        kind, frequency, token_in, _out, payee, _ref, amount_wei, _first = args[0]
        self.assertEqual((kind, abi.FREQUENCY_KEYS[frequency], payee.lower(), amount_wei),
                         (abi.RULE_CARD, 'monthly', SPENDER, int(Decimal(cap) * WAD)))
        start = timezone.now().replace(microsecond=0) - timedelta(minutes=1)
        rule = SmartAccountRule.objects.get(state='draft', kind='card')
        SmartAccountRule.objects.filter(pk=rule.pk).update(state='onchain', active=True, onchain_id=2,
                                                           next_run_at=start)
        self.world.rules[(self.contract, 2)] = {
            'kind': 'card', 'active': True, 'frequency': 'monthly', 'token_in': token_in.lower(),
            'payee': payee.lower(), 'payout_ref': '0x' + '00' * 32, 'amount_usd_wei': int(amount_wei),
            'next_run_at': int(start.timestamp()), 'epoch': 0}
        return SmartAccountRule.objects.get(pk=rule.pk)

    def order(self, *, amount=ORDER['amount'], total_usd=TOTAL_USD, pressed=True):
        """What after_checkout holds right before the card: the approved order,
        the store's CLABE read off its page, and the intent priced for it."""
        store_order = dict(ORDER, amount=amount)
        destination = PayoutDestination.objects.create(
            confio_account=self.personal, provider='infinia', kind='bank_account', status='active',
            holder_name='', country='MEX', asset='MXN', label=f'CLABE · {STORE_CLABE}',
            details={'type': 'CLABE', 'clabe': STORE_CLABE, 'reference': store_order['reference']},
            provider_data={'method_id': 'mx_clabe', 'fixed_charge': True, 'store_order': store_order,
                           'validation': {'id': '', 'status': 'DISABLED', 'holder_name': '',
                                          'checked_at': timezone.now().isoformat()}})
        intent = PaymentIntent(
            confio_account=self.personal, user=self.user, created_by='assistant', source='agent_checkout',
            rail_method_id='mx_clabe', family='local_transfer', provider='infinia', destination=destination,
            params={'store_order': store_order}, payee_name='Cuenta de la tienda', payee_level='store_checkout',
            payee_account=STORE_CLABE, institution='STP', amount_exact=True, amount_local=Decimal(amount),
            minimum_local=Decimal(amount), currency='MXN', total_usd=total_usd, fee_usd=Decimal('0.00'),
            estimated_return_usd=Decimal('0.00'), rate=Decimal('17.7884'),
            expires_at=timezone.now() + timedelta(minutes=5))
        intent.display_hash = payment_intents.display_hash(intent)
        intent.save()
        self.task = AgentTask.objects.create(
            account=self.personal, user=self.user, goal='audífonos', site='tienda.example.mx', country='MX',
            state='awaiting_code', lease=uuid.uuid4(), lease_until=timezone.now() + timedelta(minutes=3),
            checkout_at=timezone.now(), phase='ordered',
            order={'item': 'Audífonos', 'total': f'${amount}', 'amount': amount, 'pressed': pressed,
                   'pressed_at': ['x']})
        return intent

    def pay(self, intent, **kwargs):
        step = runner.Step(AgentTask.objects.get(pk=self.task.pk), self.task.lease)
        kwargs.setdefault('code', STORE_CLABE)
        kwargs.setdefault('extra', {'amount_local': intent.amount_local, 'reference': ORDER['reference']})
        return self.step(account_pay.pay, step, intent, **kwargs)

    def assert_held(self, intent, code):
        """Never the personal wallet's card: the purchase waits for the account, with nothing a card can pay."""
        task = AgentTask.objects.get(pk=self.task.pk)
        self.assertEqual((task.state, task.reason, task.payment_intent_id), ('needs_person', 'account_wait', None))
        self.assertEqual(task.order['account_wait']['code'], code)
        held = task.order['pay_hold']
        self.assertEqual((held['code'], held['extra']['amount_local'], held['extra']['reference']),
                         (STORE_CLABE, intent.amount_local and str(intent.amount_local), ORDER['reference']))
        self.assertEqual(task.wait_until, account_pay.deadline(held))
        # A one-time CLABE is not paid again after AGENT_TASKS_ACCOUNT_WAIT_CLABE_HOURS (24), not the 48 h wait.
        self.assertAlmostEqual((task.wait_until - timezone.now()).total_seconds(), 24 * 3600, delta=60)
        intent.refresh_from_db()
        self.assertEqual((intent.state, intent.bridge_id), ('cancelled', None))
        return task

    def purchase_bridge(self):
        return PaymentBridgeTransfer.objects.select_related('quote__money_flow').get(
            funding_mode='contract', quote__request_id=self.intent.request_id)

    # ── the account pays ───────────────────────────────────────────────

    def test_the_account_pays_exactly_the_approved_order_with_no_signature(self):
        rule = self.switch_on()
        self.intent = intent = self.order()
        faced = self.face.call_count
        self.assertTrue(self.pay(intent))
        self.assertEqual(self.face.call_count, faced, 'no Face per purchase (decision 38)')

        task = AgentTask.objects.get(pk=self.task.pk)
        self.assertEqual((task.state, task.reason, task.payment_intent_id), ('payment_ready', 'account', intent.pk))
        intent.refresh_from_db()
        bridge = self.purchase_bridge()
        self.assertEqual((intent.state, intent.bridge_id), ('submitted', bridge.pk))
        self.assertEqual(bridge.quote.source_address, self.contract, 'a refund returns to the account')
        self.assertEqual(int(bridge.quote.amount_units), int(TOTAL_USD * WAD))
        relay_row = SmartAccountRelayTx.objects.get(kind=abi.PURCHASE_KIND)
        self.assertEqual(relay_row.source_id, str(bridge.internal_id))
        account, rule_id, out, to, ref = abi.decode_purchase_pull(relay_row.calldata)
        self.assertEqual((account, rule_id, out, to), (self.contract, rule.onchain_id, int(TOTAL_USD * WAD),
                                                       bridge.deposit_address.lower()))
        self.assertEqual(ref, purchases.ref_for(intent.request_id))
        # The spender held nothing; the deposit got exactly the pull.
        self.assertEqual(self.world.deposits_to(bridge.deposit_address)[-1][1:],
                         (int(TOTAL_USD * WAD), w.word_address(SPENDER)))
        text = self.posted.call_args.args[1]
        self.assertIn('Cuenta inteligente', text)
        self.assertIn('US$52.48', text, 'the dollars paid, the 0.9% exit included')
        self.assertEqual(payment_intents.status(intent)[0], 'paying')

        # Proven by the pull's own receipt, then the ordinary journey.
        self.bridges()
        bridge.refresh_from_db()
        self.assertEqual(bridge.source_tx_hash, relay_row.signed_tx_hash)
        self.assertEqual((bridge.binding[contract_funding.KEY]['proof']['rule_id'], bridge.status),
                         (2, 'bridging'))
        tx_hash, units = self.world.relay_fills(next(o for o in self.world.orders
                                                     if o['deposit'] == bridge.deposit_address))
        self.bridges()
        self.credit_usdc(tx_hash, units)
        self.bridges()
        self.journeys()
        self.credit_conversion()
        self.journeys()
        self.workers()
        sent = self.world.payouts[-1]
        self.assertEqual(len(self.world.payouts), 1)
        self.assertIn(STORE_CLABE, str(sent))
        self.assertEqual(Decimal(str(sent['amount'])), Decimal(ORDER['amount']), 'exactly the approved pesos')
        journey = InfiniaJourney.objects.get(bridge=bridge)
        self.assertEqual(journey.stage, 'completed')
        intent.refresh_from_db()
        self.assertEqual(payment_intents.status(intent)[0], 'paid')

    def test_the_cap_counts_the_gross_and_a_purchase_over_it_waits_for_a_higher_cap(self):
        self.switch_on(cap='60.00')
        self.intent = first = self.order()
        self.assertTrue(self.pay(first))
        gross = self.world.card_spent[(self.contract, 2)]
        self.assertEqual(gross, self.world.gross(int(TOTAL_USD * WAD)))
        AgentTask.objects.filter(pk=self.task.pk).update(state='stopped')
        second = self.order(amount='180.00', total_usd=Decimal('10.10'))
        found = account_pay.standing(self.task, second)
        self.assertEqual(found.code, 'cap')
        self.assertEqual(found.room, Decimal('7.52'))
        self.assertIn('te quedan US$7.52 de US$60.00', account_pay.situation_text(self.task, found))
        self.assertTrue(self.pay(second))
        task = self.assert_held(second, 'cap')
        # Spent 52.48, this one 10.20 with its exit fee: the cap offered fits both, in whole steps.
        self.assertEqual(task.order['account_wait']['amount_usd'], '200.00')
        self.assertEqual(account_pay.raised_cap(mock.Mock(cap=Decimal('300'), room=Decimal('10'),
                                                          gross=Decimal('45'))), Decimal('350.00'))
        self.assertIn('Ya lo hice: pagar', self.posted.call_args.args[1])
        self.assertEqual(SmartAccountRelayTx.objects.filter(kind=abi.PURCHASE_KIND).count(), 1)

    def test_only_without_a_spender_is_it_the_card_and_nothing_else_ever_is(self):
        self.intent = intent = self.order()
        with override_settings(SMART_ACCOUNT_PURCHASE_SPENDER_ADDRESS=''):
            self.assertEqual(account_pay.standing(self.task, intent).code, 'off')
            self.assertFalse(self.pay(intent), 'before the spender exists: the person\'s card, as before')
        intent.refresh_from_db()
        self.assertEqual(intent.state, 'quoted')
        # Purchases not switched on: it waits for "Activar compras", never the card.
        self.assertEqual(account_pay.standing(self.task, intent).code, 'no_rule')
        self.assertTrue(self.pay(intent))
        task = self.assert_held(intent, 'no_rule')
        self.assertEqual(task.order['account_wait']['amount_usd'], '200.00')
        # An order the person did not approve is never paid, by anything.
        self.switch_on()
        AgentTask.objects.filter(pk=self.task.pk).update(state='stopped')
        other = self.order()
        AgentTask.objects.filter(pk=self.task.pk).update(order={**self.task.order, 'unapproved': True})
        self.assertTrue(self.pay(other))
        task = AgentTask.objects.get(pk=self.task.pk)
        self.assertEqual((task.state, task.order['pay_hold']['tries']), ('awaiting_code', 1))
        other.refresh_from_db()
        self.assertEqual(other.state, 'cancelled')
        self.assertFalse(PaymentBridgeTransfer.objects.exists())
        self.assertFalse(SmartAccountRelayTx.objects.filter(kind=abi.PURCHASE_KIND).exists())

    def test_short_account_moves_from_the_personal_wallet_first(self):
        self.switch_on()
        self.world.balances[(w.CUSD, self.contract)] = 10 * WAD
        self.world.balances[(w.CUSD, self.wallet)] = 500 * WAD
        self.intent = intent = self.order()
        found = account_pay.standing(self.task, intent)
        self.assertEqual(found.code, 'move')
        least, offered = purchases.move_offer(found.short, found.personal)
        self.assertEqual(least, Decimal('42.48'))
        self.assertGreater(offered, least, 'more than this purchase is offered (decision 39)')
        self.assertTrue(self.pay(intent))
        task = self.assert_held(intent, 'move')
        self.assertEqual(Decimal(task.order['account_wait']['amount_usd']), offered)
        self.assertIn(f'Mueve US${offered:,.2f}', task.order['account_wait']['text'])
        batch = self.step(purchases.prepare_move_for_purchase, self.viewer(), offered)
        self.assertEqual(batch.kind, 'smart_deposit')
        self.assertEqual(batch.calls[0], abi.transfer_call(w.CUSD, self.contract, int(offered * WAD)))
        self.world.balances[(w.CUSD, self.wallet)] = 0
        self.assertEqual(account_pay.standing(self.task, intent).code, 'topup')

    def test_a_simulated_refusal_reserves_nothing(self):
        self.switch_on()
        self.intent = intent = self.order()
        self.world.card_allowed = False      # the Safe cut the spender after the mirror said yes
        self.assertEqual(account_pay.standing(self.task, intent).code, 'off')
        self.world.card_allowed = True
        with mock.patch.object(PurchaseWorld, 'pull', side_effect=w.Revert('CapExceeded')):
            self.assertTrue(self.pay(intent))
        self.assertFalse(PaymentBridgeTransfer.objects.exists())
        intent.refresh_from_db()
        self.assertEqual(intent.state, 'cancelled', 'no card can pay it')
        task = AgentTask.objects.get(pk=self.task.pk)
        self.assertEqual((task.state, task.order['pay_hold']['tries']), ('awaiting_code', 1), 'tried again later')

    def test_an_unread_chain_is_tried_a_few_times_then_an_honest_stop(self):
        self.switch_on()
        for attempt in range(account_pay.OFF_RETRIES + 1):
            self.intent = intent = self.order() if attempt == 0 else self.again()
            self.world.card_allowed = False          # 'off': the factory said no or could not be read
            held = (AgentTask.objects.get(pk=self.task.pk).order or {}).get('pay_hold')
            self.assertTrue(self.pay(intent, held=held))
            intent.refresh_from_db()
            self.assertEqual(intent.state, 'cancelled')
        task = AgentTask.objects.get(pk=self.task.pk)
        self.assertEqual((task.state, task.reason), ('stopped', 'unpaid'))
        self.assertIn('no salió dinero', self.posted.call_args.args[1])
        self.assertFalse(PaymentBridgeTransfer.objects.exists())

    def again(self, amount=ORDER['amount']):
        """Another intent priced for the same task's order, as pay_held prepares it."""
        task = AgentTask.objects.get(pk=self.task.pk)
        intent = PaymentIntent.objects.filter(source='agent_checkout').latest('pk')
        destination = PayoutDestination.objects.get(pk=intent.destination_id)
        destination.pk = None
        destination.internal_id = uuid.uuid4()
        destination.save()
        fresh = PaymentIntent.objects.get(pk=intent.pk)
        fresh.pk, fresh.internal_id, fresh.request_id = None, uuid.uuid4(), uuid.uuid4()
        fresh.state, fresh.bridge, fresh.destination = 'quoted', None, destination
        fresh.expires_at = timezone.now() + timedelta(minutes=5)
        fresh.display_hash = payment_intents.display_hash(fresh)
        fresh.save()
        AgentTask.objects.filter(pk=task.pk).update(state='awaiting_code', reason='', wait_until=None,
                                                    lease=self.task.lease)
        return fresh

    def test_a_held_purchase_is_paid_by_the_account_once_the_person_switched_it_on(self):
        from agent_tasks import service
        self.intent = intent = self.order()
        self.assertTrue(self.pay(intent))
        task = self.assert_held(intent, 'no_rule')
        # The card's one action is the ordinary rule batch, amount from the task (prepareAgentAccountWait).
        figures, _ = service.account_wait(self.personal, self.user, task.internal_id)
        self.assertEqual((figures['code'], figures['amount_usd']), ('no_rule', '200.00'))
        self.switch_on()
        # The sweep notices before any tap: the account pays now.
        self.assertTrue(service.account_changed(task))
        self.step(service.resume_payment, self.personal, self.user, task.internal_id)
        task = AgentTask.objects.get(pk=self.task.pk)
        self.assertEqual((task.state, task.order['pay_hold']['asked']), ('awaiting_code', True))
        AgentTask.objects.filter(pk=task.pk).update(lease=self.task.lease)
        fresh = {}

        def prepare(account, user, code, **kwargs):
            self.assertEqual((account, user, code, kwargs['source']), (self.personal, self.user, STORE_CLABE,
                                                                       'agent_checkout'))
            self.assertEqual((kwargs['request']['amount_local'], kwargs['request']['reference']),
                             (ORDER['amount'], ORDER['reference']))
            fresh['intent'] = self.again()
            return fresh['intent']
        step = runner.Step(AgentTask.objects.select_related('account', 'user').get(pk=self.task.pk), self.task.lease)
        with mock.patch('payment_accounts.payment_intents.prepare', side_effect=prepare), \
                mock.patch('agent_tasks.service.pay_mode', return_value=('confio', '')):
            self.step(step.pay_held)
        task = AgentTask.objects.get(pk=self.task.pk)
        self.assertEqual((task.state, task.reason, task.payment_intent_id),
                         ('payment_ready', 'account', fresh['intent'].pk))
        self.assertEqual(SmartAccountRelayTx.objects.filter(kind=abi.PURCHASE_KIND).count(), 1)
        from agent_tasks.schema import task_type
        self.assertIn('Tu Cuenta inteligente está pagando', task_type(task).message)
        self.assertIn('US$52.48', task_type(task).message)

    def test_a_held_purchase_past_its_wait_stops_with_nothing_paid(self):
        from agent_tasks import service
        self.intent = intent = self.order()
        self.assertTrue(self.pay(intent))
        task = self.assert_held(intent, 'no_rule')
        AgentTask.objects.filter(pk=task.pk).update(wait_until=timezone.now() - timedelta(seconds=1))
        with mock.patch.object(service, 'worker_alive', return_value=True):
            service._sweep()
        task = AgentTask.objects.get(pk=task.pk)
        self.assertEqual((task.state, task.reason), ('stopped', 'account_timeout'))
        self.assertIn('quedó hecho', self.posted.call_args.args[1])
        from agent_tasks.schema import task_type
        self.assertIn('sin pagar', task_type(task).message)
        self.assertFalse(PaymentBridgeTransfer.objects.exists())

    def test_a_cancelled_task_never_sends_the_pull(self):
        self.switch_on()
        self.intent = intent = self.order()
        real = purchase_funding.persist

        def cancelled_meanwhile(*args, **kwargs):
            out = real(*args, **kwargs)
            AgentTask.objects.filter(pk=self.task.pk).update(state='cancelled')
            return out
        with mock.patch.object(purchase_funding, 'persist', side_effect=cancelled_meanwhile):
            with self.assertRaises(runner.Lost):
                self.pay(intent)
        self.assertFalse(SmartAccountRelayTx.objects.filter(kind=abi.PURCHASE_KIND).exists())
        bridge = self.purchase_bridge()
        self.assertEqual(bridge.status, 'expired')
        intent.refresh_from_db()
        self.assertEqual(intent.state, 'expired')
        self.assertEqual(self.world.deposits_to(bridge.deposit_address), [])

    def test_a_pull_not_sent_after_the_order_was_reserved_is_said_honestly(self):
        self.switch_on()
        self.intent = intent = self.order()
        with mock.patch('smart_account.relayer.send_relayer_call',
                        side_effect=relayer.RelayError('sponsor_busy')):
            self.assertTrue(self.pay(intent))
        task = AgentTask.objects.get(pk=self.task.pk)
        self.assertEqual((task.state, task.reason), ('stopped', 'unpaid'))
        self.assertIn('no salió dinero', self.posted.call_args.args[1])
        self.assertEqual(self.purchase_bridge().status, 'expired')

    def test_a_pull_that_paid_anything_else_is_never_converted_or_paid(self):
        self.switch_on()
        self.intent = intent = self.order()
        other = '0x' + '0d' * 20

        def elsewhere(logs):
            logs[-1] = event(SPENDER, 'Forwarded', abi.FORWARDED_FIELDS,
                             [self.contract, 2, other, int(TOTAL_USD * WAD), purchases.ref_for(intent.request_id)])
            return logs
        self.world.tamper = elsewhere
        self.assertTrue(self.pay(intent))
        self.bridges()
        bridge = self.purchase_bridge()
        self.assertEqual((bridge.status, bridge.failure_code, bridge.source_tx_hash),
                         ('needs_review', 'source_transfer_mismatch', ''))
        self.assertIn('forwarded_mismatch', self.alert_text())
        self.journeys()
        self.assertEqual(self.world.payouts, [])
        self.assertEqual(self.world.transfers, [])

    def test_a_reverted_pull_closes_the_order_and_frees_the_accounts(self):
        self.switch_on()
        self.intent = intent = self.order()
        self.world.hold_broadcast = True
        self.assertTrue(self.pay(intent))
        self.world.balances[(w.CUSD, self.contract)] = 0     # spent elsewhere before it was mined
        self.assertEqual(len(self.world.mine_held()), 1)
        self.bridges()
        bridge = self.purchase_bridge()
        self.assertEqual((bridge.status, bridge.source_tx_hash), ('expired', ''))
        self.assertTrue(bridge.binding[contract_funding.KEY]['pull']['reverted'])
        self.assertEqual(InfiniaJourney.objects.get(bridge=bridge).stage, 'failed')
        self.assertEqual(payment_intents.status(PaymentIntent.objects.get(pk=intent.pk))[0], 'expired')
        # Never "está pagando" forever: the task ends, and the person is told no money left.
        task = AgentTask.objects.get(pk=self.task.pk)
        self.assertEqual((task.state, task.reason), ('stopped', 'unpaid'))
        self.assertIn('no salió dinero', self.posted.call_args.args[1])

    def test_a_reorged_pull_may_land_again_and_only_a_dropped_one_closes_the_order(self):
        self.switch_on()
        self.intent = intent = self.order()
        self.world.hold_broadcast = True
        self.assertTrue(self.pay(intent))
        row = SmartAccountRelayTx.objects.get(kind=abi.PURCHASE_KIND)
        SmartAccountRelayTx.objects.filter(pk=row.pk).update(status='reorged')
        unused = mock.patch('payment_accounts.purchase_funding._nonce_taken', return_value=False)
        unused.start()
        self.addCleanup(unused.stop)
        self.assertTrue(purchase_funding.may_land(self.purchase_bridge()), 'its nonce is unused: it can be mined')
        self.bridges()
        self.assertEqual(self.purchase_bridge().status, 'submitted')
        self.assertEqual(AgentTask.objects.get(pk=self.task.pk).state, 'payment_ready')
        SmartAccountRelayTx.objects.filter(pk=row.pk).update(status='dropped')
        self.bridges()
        self.assertEqual(self.purchase_bridge().status, 'expired')
        task = AgentTask.objects.get(pk=self.task.pk)
        self.assertEqual((task.state, task.reason), ('stopped', 'unpaid'))
        self.assertIn('no salió dinero', self.posted.call_args.args[1])
        intent.refresh_from_db()
        self.assertEqual(intent.state, 'expired')

    def test_a_reorged_pull_whose_nonce_another_transaction_took_never_holds_the_account(self):
        self.switch_on()
        self.intent = intent = self.order()
        self.world.hold_broadcast = True
        self.assertTrue(self.pay(intent))
        row = SmartAccountRelayTx.objects.get(kind=abi.PURCHASE_KIND)
        SmartAccountRelayTx.objects.filter(pk=row.pk).update(status='reorged')
        with mock.patch('payment_accounts.purchase_funding._nonce_taken', return_value=True):
            self.assertFalse(purchase_funding.may_land(self.purchase_bridge()))
        with mock.patch('payment_accounts.purchase_funding._nonce_taken', return_value=False):
            self.assertTrue(purchase_funding.may_land(self.purchase_bridge()))

    def lock_lost_after_the_claim(self, then_status=None):
        """The relay row and the claim committed, then the nonce lock was not this call's any more."""
        real = relayer.send_relayer_call

        def lost(*args, **kwargs):
            row, _created = real(*args, **kwargs)
            if then_status:
                SmartAccountRelayTx.objects.filter(pk=row.pk).update(status=then_status)
            raise relayer.RelayError('sponsor_lock_lost')
        return mock.patch('smart_account.relayer.send_relayer_call', side_effect=lost)

    def test_a_lock_lost_after_the_claim_follows_the_pull_and_ends_the_task_if_it_never_lands(self):
        self.switch_on()
        self.intent = intent = self.order()
        self.world.hold_broadcast = True
        with self.lock_lost_after_the_claim():
            self.assertTrue(self.pay(intent))    # never Lost, never silent
        task = AgentTask.objects.get(pk=self.task.pk)
        self.assertEqual((task.state, task.reason), ('payment_ready', 'account'))
        # Never broadcast: nothing is said yet (no "paying" that a "not paid" would contradict).
        self.assertFalse(any('está pagando' in str(call.args[1]) for call in self.posted.call_args_list))
        self.assertEqual(self.purchase_bridge().status, 'submitted', 'followed by its hash')
        SmartAccountRelayTx.objects.filter(kind=abi.PURCHASE_KIND).update(status='dropped')
        self.bridges()
        task = AgentTask.objects.get(pk=self.task.pk)
        self.assertEqual((task.state, task.reason), ('stopped', 'unpaid'))
        self.assertIn('no salió dinero', self.posted.call_args.args[1])

    def test_a_lock_lost_after_the_claim_with_a_dropped_pull_ends_the_paid_task_at_once(self):
        self.switch_on()
        self.intent = intent = self.order()
        self.world.hold_broadcast = True
        with self.lock_lost_after_the_claim(then_status='dropped'):
            self.assertTrue(self.pay(intent))
        task = AgentTask.objects.get(pk=self.task.pk)
        self.assertEqual((task.state, task.reason), ('stopped', 'unpaid'))
        self.assertIn('no salió dinero', self.posted.call_args.args[1])
        self.assertEqual(self.purchase_bridge().status, 'expired')
        intent.refresh_from_db()
        self.assertEqual(intent.state, 'expired')

    def test_a_lapsed_account_waits_to_be_renewed(self):
        from smart_account.models import SmartAccount
        self.switch_on()
        self.intent = intent = self.order()
        SmartAccount.objects.filter(contract_address__iexact=self.contract).update(billing_status='past_due')
        self.assertEqual(account_pay.standing(self.task, intent).why, 'account')
        self.assertTrue(self.pay(intent))
        task = self.assert_held(intent, 'renew')
        self.assertIn('Ponla al día', task.order['account_wait']['text'])

    def test_a_spender_ops_must_allow_alerts_once_and_stops_with_nothing_paid(self):
        self.switch_on()
        self.intent = intent = self.order()
        SmartAccountCardSpender.objects.filter(address=SPENDER).delete()
        with mock.patch('config.ops_alerts.send_ops_alert') as alerted:
            self.assertTrue(self.pay(intent))
        alerted.assert_called_once()
        self.assertEqual(alerted.call_args.kwargs['dedupe_key'], 'purchase_spender_gap:spender_mirror')
        task = AgentTask.objects.get(pk=self.task.pk)
        self.assertEqual((task.state, task.reason), ('stopped', 'unpaid'))
        self.assertIn('Ahora no puedo pagar compras desde tu Cuenta inteligente', self.posted.call_args.args[1])
        intent.refresh_from_db()
        self.assertEqual(intent.state, 'cancelled')
        self.assertFalse(PaymentBridgeTransfer.objects.exists())


class PurchaseAbiTests(TestCase):
    def test_pull_to_round_trips_and_only_for_its_own_account(self):
        account, deposit = '0x' + '22' * 20, '0x' + '33' * 20
        data = abi.purchase_pull_call(account, 7, 5 * WAD, deposit, purchases.ref_for(uuid.UUID(int=9)))
        self.assertEqual(abi.decode_purchase_pull(data)[:4], (account, 7, 5 * WAD, deposit))
        with self.assertRaises(ValueError):
            abi.decode_purchase_pull(data + '00')
        with override_settings(SMART_ACCOUNT_PURCHASE_SPENDER_ADDRESS=SPENDER):
            own = mock.Mock(contract_address=account)
            self.assertEqual(relayer.relay_target(own, data, abi.PURCHASE_KIND), SPENDER)
            with self.assertRaises(relayer.RelayError):
                relayer.relay_target(mock.Mock(contract_address='0x' + '44' * 20), data, abi.PURCHASE_KIND)
            with self.assertRaises(relayer.RelayError):
                relayer.relay_target(own, abi.encode_call('collectFee'), abi.PURCHASE_KIND)
        with override_settings(SMART_ACCOUNT_PURCHASE_SPENDER_ADDRESS=''):
            with self.assertRaises(relayer.RelayError):
                relayer.relay_target(mock.Mock(contract_address=account), data, abi.PURCHASE_KIND)

    def test_gross_is_the_contracts(self):
        # ConfioSmartAccount.Card.t.sol: 99.1 out at 90 bps is a gross of exactly 100.
        self.assertEqual(purchases.gross_wei(99_100_000_000_000_000_000, 90), 100 * WAD)
        self.assertEqual(purchases.gross_wei(9_910_000_000_000_000_000, 90), 10 * WAD)

    def test_forwarded_decodes(self):
        account, deposit = '0x' + '22' * 20, '0x' + '33' * 20
        ref = purchases.ref_for(uuid.UUID(int=5))
        log = event(SPENDER, 'Forwarded', abi.FORWARDED_FIELDS, [account, 3, deposit, 11, ref])
        self.assertEqual(abi.decode_forwarded(log), {'account': account, 'ruleId': '3', 'to': deposit,
                                                    'usdtOut': '11', 'ref': '0x' + ref.hex()})
        self.assertIsNone(abi.decode_forwarded({'topics': ['0x' + '00' * 32], 'data': '0x'}))

    def test_notes_are_new_keys_with_their_figures(self):
        for text in (*notes.ACCOUNT_PAY.values(), notes.PAID_BY_ACCOUNT, notes.ACCOUNT_NOT_PAID,
                     notes.ACCOUNT_WAIT_TAIL, notes.ACCOUNT_STILL, notes.ACCOUNT_WAIT_PUSH,
                     notes.ACCOUNT_WAIT_EXPIRED, notes.ACCOUNT_UNREAD, notes.ACCOUNT_PAUSED):
            notes.say(text, mock.Mock(country='MX', site='tienda.example.mx'))
