"""Card rules (decision 35): mirror, pulls, spenders, prepare, relay policy,
automation, GraphQL, assistant read tools and admin."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from smart_account import abi, assistant_ops, automation, cards, reconcile, relay_policy, services
from smart_account.models import (
    SmartAccount, SmartAccountCardPause, SmartAccountCardPull, SmartAccountCardSpender, SmartAccountEvent,
    SmartAccountPreparedAction, SmartAccountRule, SmartAccountStandingAuthorization,
)

from .base import FACTORY, VAULT, WAD, SmartAccountTestCase, new_address

SPENDER = '0x' + 'ca' * 20


class CardTestCase(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.contract = new_address()
        self.block = 5000
        self.index = 0
        self.now = timezone.now().replace(microsecond=0)
        self.allowed_on_chain = True
        self.spent_on_chain = 0
        for p in (mock.patch('smart_account.chain.card_spender_allowed', side_effect=lambda s: self.allowed_on_chain),
                  mock.patch('smart_account.chain.card_spent_usd_wei', side_effect=lambda a, i: self.spent_on_chain)):
            p.start()
            self.addCleanup(p.stop)

    def emit(self, name, args, *, address=None, tx=None, when=None):
        self.index += 1
        return SmartAccountEvent.objects.create(
            address=(address or self.contract).lower(), tx_hash=tx or ('0x' + format(self.index, 'x').rjust(64, '0')),
            log_index=self.index, name=name, args=args, block_number=self.block + self.index,
            block_time=when or self.now)

    def apply(self):
        out = reconcile.apply_pending()
        self.assertEqual(out['failed'], 0)
        return out

    def subscribe(self):
        paid_until = int((self.now + timedelta(days=365)).timestamp())
        self.emit('AccountCreated', {'owner': self.owner.wallet, 'account': self.contract}, address=FACTORY, tx='0xaa')
        self.emit('Subscribed', {'plan': '2', 'feeUsd': str(14999 * 10 ** 16), 'paidUntil': str(paid_until)},
                  tx='0xaa')
        self.apply()
        return SmartAccount.objects.get(contract_address=self.contract)

    def allow_spender(self, label='Tarjeta Confío'):
        self.emit('CardSpenderSet', {'spender': SPENDER, 'allowed': True}, address=FACTORY)
        self.apply()
        SmartAccountCardSpender.objects.filter(address=SPENDER).update(label=label)

    def chain_rule(self, account, rule_id=0, *, amount=100, frequency='weekly', next_run_at=None, active=True,
                   payee=SPENDER):
        self.chain.rules[(account.contract_address, rule_id)] = {
            'kind': 'card', 'frequency': frequency, 'active': active, 'token_in': VAULT,
            'token_out': abi.ZERO_ADDRESS, 'payee': payee, 'payout_ref': '0x' + '00' * 32,
            'amount_usd_wei': amount * WAD, 'next_run_at': int((next_run_at or self.now).timestamp())}

    def signed(self, batch, tx):
        from blockchain.models import SponsoredBatch
        sponsored = SponsoredBatch.objects.create(
            user=self.owner, user_bsc_address=self.owner.wallet, kind='smart_rule', num_calls=1,
            calls_json='[]', tx_hash=tx, gas_limit=1, max_fee_wei='1', status='confirmed')
        SmartAccountPreparedAction.objects.filter(request_id=batch.request_id).update(
            consumed=True, sponsored_batch=sponsored)

    def card_rule(self, account, *, amount=100, frequency='weekly'):
        """A Card rule prepared through Confío and mined."""
        self.allow_spender()
        with self.settings(SMART_ACCOUNT_CARD_RULES_ENABLED=True):
            batch = services.prepare_card_rule(self.viewer(self.owner), None, SPENDER, str(amount), frequency)
        self.signed(batch, '0xc1')
        self.chain_rule(account, amount=amount, frequency=frequency)
        self.emit('RuleCreated', {'id': '0', 'kind': '3'}, tx='0xc1')
        self.apply()
        return SmartAccountRule.objects.get(kind='card', state='onchain')

    def pull(self, usdt, gross, *, when=None, rule_id='0', spender=SPENDER):
        self.emit('CardPulled', {'id': rule_id, 'spender': spender, 'usdtOut': str(int(usdt * WAD)),
                                 'usdSpent': str(int(gross * WAD))}, when=when)
        self.apply()


class CardMirrorTests(CardTestCase):
    def test_spender_and_pause_events_mirror_in_order(self):
        self.emit('CardSpenderSet', {'spender': SPENDER, 'allowed': True}, address=FACTORY)
        self.emit('CardPausedSet', {'paused': True}, address=FACTORY)
        self.apply()
        row = SmartAccountCardSpender.objects.get(address=SPENDER)
        self.assertTrue(row.allowed)
        self.assertTrue(SmartAccountCardPause.is_paused())
        self.assertIsNone(cards.allowed_spender(SPENDER))  # paused
        self.emit('CardPausedSet', {'paused': False}, address=FACTORY)
        self.emit('CardSpenderSet', {'spender': SPENDER, 'allowed': False}, address=FACTORY)
        self.apply()
        self.assertFalse(SmartAccountCardPause.is_paused())
        self.assertFalse(SmartAccountCardSpender.objects.get(address=SPENDER).allowed)

    def test_an_older_spender_event_never_moves_the_flag_back(self):
        old = self.emit('CardSpenderSet', {'spender': SPENDER, 'allowed': True}, address=FACTORY)
        new = self.emit('CardSpenderSet', {'spender': SPENDER, 'allowed': False}, address=FACTORY)
        self.apply()
        reconcile._card_spender_set(old)  # a replay of the older event
        self.assertFalse(SmartAccountCardSpender.objects.get(address=SPENDER).allowed)
        self.assertEqual(SmartAccountCardSpender.objects.get().set_block, new.block_number)

    def test_card_rule_created_through_confio_is_mirrored_with_its_authorization(self):
        account = self.subscribe()
        rule = self.card_rule(account)
        self.assertEqual((rule.kind, rule.active, rule.payee_address, rule.amount), ('card', True, SPENDER,
                                                                                       Decimal('100.00')))
        self.assertIsNone(rule.scheduled_for)
        self.assertEqual(rule.next_run_at, self.now)
        self.assertEqual(rule.card_spent_usd, 0)
        self.assertEqual(rule.standing_authorization.kind, 'card')
        self.ops_alert_mock.assert_not_called()

    def test_period_start_comes_from_the_signed_first_run_not_the_chain_now(self):
        account = self.subscribe()
        self.allow_spender()
        later = self.now + timedelta(days=3)
        with self.settings(SMART_ACCOUNT_CARD_RULES_ENABLED=True):
            batch = services.prepare_card_rule(self.viewer(self.owner), None, SPENDER, '50', 'weekly',
                                               first_run_at=later.isoformat())
        self.signed(batch, '0xc2')
        # The chain already moved nextRunAt on (a later pull rolled it).
        self.chain_rule(account, amount=50, next_run_at=later + timedelta(days=14))
        self.emit('RuleCreated', {'id': '0', 'kind': '3'}, tx='0xc2')
        self.apply()
        self.assertEqual(SmartAccountRule.objects.get(kind='card', state='onchain').next_run_at, later)

    def test_first_period_start_without_a_prepared_action(self):
        block = self.now
        week = 7 * 86400
        ts = int(block.timestamp())
        self.assertEqual(cards.first_period_start(block, ts, 'weekly'), block)
        self.assertEqual(cards.first_period_start(block, ts + 2 * week, 'weekly'), block)  # rolled since
        self.assertEqual(cards.first_period_start(block, ts + 3600, 'weekly'),
                         block + timedelta(hours=1))  # a future first run

    def test_a_card_rule_nobody_authorized_stays_active_and_alerts(self):
        account = self.subscribe()
        self.chain_rule(account)
        self.emit('RuleCreated', {'id': '0', 'kind': '3'})
        self.apply()
        rule = SmartAccountRule.objects.get(kind='card')
        self.assertTrue(rule.active)  # the chain lets the spender pull: the owner must see it
        self.assertIsNone(rule.standing_authorization)
        self.assertTrue(any('sin autorización' in str(c) for c in self.ops_alert_mock.call_args_list))

    def test_pulls_count_against_the_period_reset_at_the_boundary_and_notify(self):
        account = self.subscribe()
        rule = self.card_rule(account, amount=100)
        with mock.patch('smart_account.notifications._send') as send:
            self.pull(Decimal('19.82'), Decimal('20'), when=self.now + timedelta(days=1))
            self.pull(Decimal('29.73'), Decimal('30'), when=self.now + timedelta(days=2))
        rule.refresh_from_db()
        self.assertEqual(rule.card_spent_usd, Decimal('50'))
        self.assertEqual(rule.next_run_at, self.now)
        pulls = list(SmartAccountCardPull.objects.order_by('block_number'))
        self.assertEqual([p.spent_in_period for p in pulls], [Decimal('20'), Decimal('50')])
        self.assertEqual(send.call_count, 2)
        title, body = send.call_args[0][1], send.call_args[0][2]
        self.assertEqual(title, 'Tu tarjeta usó US$30.00')
        self.assertIn('Tarjeta Confío usó US$30.00 de tu Cuenta inteligente', body)
        self.assertIn('Te quedan US$50.00', body)
        self.assertEqual(send.call_args[1]['kind'], 'card_pulled')
        # Two periods later: missed periods skipped, the count restarts.
        self.pull(Decimal('9.91'), Decimal('10'), when=self.now + timedelta(days=15))
        rule.refresh_from_db()
        self.assertEqual(rule.next_run_at, self.now + timedelta(days=14))
        self.assertEqual(rule.card_spent_usd, Decimal('10'))
        start, end, spent = cards.current_period(rule, now=self.now + timedelta(days=22))
        self.assertEqual((start, spent), (self.now + timedelta(days=21), Decimal(0)))  # stale count

    def test_a_pull_is_recorded_once(self):
        account = self.subscribe()
        self.card_rule(account)
        self.pull(Decimal('9.91'), Decimal('10'))
        event = SmartAccountEvent.objects.get(name='CardPulled')
        self.assertEqual(reconcile._card_pulled(account, event), [])
        self.assertEqual(SmartAccountCardPull.objects.count(), 1)

    def test_update_keeps_the_count_and_restarts_the_period(self):
        account = self.subscribe()
        rule = self.card_rule(account, amount=100)
        self.pull(Decimal('39.64'), Decimal('40'), when=self.now + timedelta(days=1))
        moved = self.now + timedelta(days=2)
        self.chain_rule(account, amount=80, next_run_at=moved)
        self.emit('RuleUpdated', {'id': '0'}, when=moved)
        self.apply()
        rule.refresh_from_db()
        self.assertEqual((rule.amount, rule.card_spent_usd, rule.next_run_at), (Decimal('80.00'), Decimal('40'), moved))

    def test_a_pull_without_a_mirrored_card_rule_is_recorded_and_alerted(self):
        self.subscribe()
        self.pull(Decimal('9.91'), Decimal('10'), rule_id='7')
        pull = SmartAccountCardPull.objects.get()
        self.assertIsNone(pull.rule)
        self.assertEqual(pull.onchain_rule_id, 7)
        self.assertTrue(any('CardPulled' in str(c) for c in self.ops_alert_mock.call_args_list))

    def test_cancel_and_inheritance_stop_a_card_rule(self):
        account = self.subscribe()
        rule = self.card_rule(account)
        self.emit('RuleCancelled', {'id': '0'})
        self.apply()
        rule.refresh_from_db()
        self.assertEqual((rule.state, rule.active), ('cancelled', False))
        self.assertIsNotNone(rule.standing_authorization.revoked_at)


class CardAutomationTests(CardTestCase):
    def test_the_relayer_never_runs_a_card_rule(self):
        account = self.subscribe()
        rule = self.card_rule(account)
        SmartAccountRule.objects.filter(pk=rule.pk).update(scheduled_for=self.now - timedelta(days=1),
                                                           next_run_at=self.now - timedelta(days=1))
        self.assertNotIn(rule.pk, [r.pk for r in automation.due_rules()])
        with mock.patch('smart_account.relayer.send_relayer_call') as send:
            automation._run_rule(rule, {'sent': 0, 'skipped': 0, 'waiting': 0, 'errors': 0})
        send.assert_not_called()
        self.assertFalse(rule.runs.exists())

    def test_rule_run_notification_never_crashes_on_another_kind(self):
        from smart_account import notifications
        from smart_account.models import SmartAccountRuleRun
        account = self.subscribe()
        rule = self.card_rule(account)
        run = SmartAccountRuleRun.objects.create(rule=rule, scheduled_for=self.now, status='skipped')
        with mock.patch('smart_account.notifications._send') as send:
            notifications.rule_run(run)
        self.assertIn('regla automática', send.call_args[0][1])


class CardPrepareTests(CardTestCase):
    def test_off_by_default(self):
        self.subscribe()
        self.allow_spender()
        with self.assertRaises(services.PrepareError) as ctx:
            services.prepare_card_rule(self.viewer(self.owner), None, SPENDER, '100', 'weekly')
        self.assertEqual(ctx.exception.code, 'card_not_available')

    @override_settings(SMART_ACCOUNT_CARD_RULES_ENABLED=True)
    def test_spender_must_be_allowed_in_the_mirror_and_on_chain(self):
        self.subscribe()
        viewer = self.viewer(self.owner)
        with self.assertRaises(services.PrepareError) as ctx:
            services.prepare_card_rule(viewer, None, SPENDER, '100', 'weekly')
        self.assertEqual(ctx.exception.code, 'card_spender_not_allowed')
        self.allow_spender()
        self.allowed_on_chain = False
        with self.assertRaises(services.PrepareError) as ctx:
            services.prepare_card_rule(viewer, None, SPENDER, '100', 'weekly')
        self.assertEqual(ctx.exception.code, 'card_spender_not_allowed')
        self.allowed_on_chain = True
        SmartAccountCardPause.objects.create(pk=1, paused=True)
        with self.assertRaises(services.PrepareError) as ctx:
            services.prepare_card_rule(viewer, None, SPENDER, '100', 'weekly')
        self.assertEqual(ctx.exception.code, 'card_spender_not_allowed')
        self.assertFalse(SmartAccountStandingAuthorization.objects.exists())

    @override_settings(SMART_ACCOUNT_CARD_RULES_ENABLED=True)
    def test_prepare_encodes_a_card_rule_for_the_owner_to_sign(self):
        account = self.subscribe()
        self.allow_spender()
        batch = services.prepare_card_rule(self.viewer(self.owner), None, SPENDER.upper().replace('0X', '0x'),
                                           '100', 'monthly')
        name, args = abi.decode_call(batch.calls[0]['data'])
        self.assertEqual(name, 'createRule')
        self.assertEqual((args[0][0], args[0][4].lower(), args[0][6]), (abi.RULE_CARD, SPENDER, 100 * WAD))
        self.assertEqual(batch.calls[0]['to'], account.contract_address)
        self.assertIn('cada 28 días', batch.summary[0])
        draft = SmartAccountRule.objects.get(state='draft')
        self.assertEqual((draft.kind, draft.standing_authorization.kind), ('card', 'card'))

    @override_settings(SMART_ACCOUNT_CARD_RULES_ENABLED=True)
    def test_a_card_rule_cannot_be_edited_as_another_kind_but_can_be_stopped(self):
        account = self.subscribe()
        rule = self.card_rule(account)
        with self.assertRaises(services.PrepareError) as ctx:
            services.prepare_buy_rule(self.viewer(self.owner), str(rule.internal_id), 'stock:SPYon', '10', 'weekly')
        self.assertEqual(ctx.exception.code, 'rule_kind_mismatch')
        batch = services.prepare_cancel_rule(self.viewer(self.owner), str(rule.internal_id))
        self.assertEqual(abi.decode_call(batch.calls[0]['data'])[0], 'cancelRule')

    def test_stopping_does_not_need_the_switch(self):
        account = self.subscribe()
        rule = self.card_rule(account)
        batch = services.prepare_cancel_rule(self.viewer(self.owner), str(rule.internal_id))
        self.assertEqual(batch.kind, 'smart_rule_cancel')


class CardRelayPolicyTests(CardTestCase):
    def card_calls(self, account):
        rule = abi.rule_input('card', 'weekly', VAULT, payee=SPENDER, amount_usd_wei=100 * WAD)
        return [abi.call(account.contract_address, abi.encode_call('createRule', rule))]

    def test_card_create_is_refused_while_off_or_not_allowed(self):
        from cusd_plus.sponsor_7702 import PolicyError
        account = self.subscribe()
        calls = self.card_calls(account)
        with self.assertRaises(PolicyError) as ctx:
            relay_policy._check_card_rule(calls, account.contract_address)
        self.assertEqual(ctx.exception.code, 'card_not_available')
        with self.settings(SMART_ACCOUNT_CARD_RULES_ENABLED=True):
            with self.assertRaises(PolicyError) as ctx:
                relay_policy._check_card_rule(calls, account.contract_address)
            self.assertEqual(ctx.exception.code, 'card_spender_not_allowed')
            self.allow_spender()
            relay_policy._check_card_rule(calls, account.contract_address)  # passes
            self.allowed_on_chain = False
            with self.assertRaises(PolicyError):
                relay_policy._check_card_rule(calls, account.contract_address)

    def test_other_rules_are_untouched(self):
        account = self.subscribe()
        rule = abi.rule_input('buy', 'weekly', VAULT, token_out='0x' + '77' * 20, amount_usd_wei=10 * WAD)
        relay_policy._check_card_rule([abi.call(account.contract_address, abi.encode_call('createRule', rule))],
                                      account.contract_address)

    @override_settings(SMART_ACCOUNT_CARD_RULES_ENABLED=True)
    def test_face_is_checked_for_a_card_rule(self):
        account = self.subscribe()
        self.allow_spender()
        batch = services.prepare_card_rule(self.viewer(self.owner), None, SPENDER, '100', 'weekly')
        action = SmartAccountPreparedAction.objects.get(request_id=batch.request_id)
        draft = SmartAccountRule.objects.get(state='draft')
        self.assertIsNone(relay_policy.face_refusal(action, self.owner))
        SmartAccountStandingAuthorization.objects.filter(pk=draft.standing_authorization_id).update(
            revoked_at=timezone.now())
        self.assertTrue(relay_policy.face_refusal(action, self.owner))


class CardReadTests(CardTestCase):
    def test_graphql_lists_card_rules_with_this_periods_room(self):
        from smart_account.schema import Query, _rule_type
        account = self.subscribe()
        rule = self.card_rule(account, amount=100)
        self.pull(Decimal('24.77'), Decimal('25'), when=self.now + timedelta(hours=1))
        rule.refresh_from_db()
        row = _rule_type(rule)
        self.assertEqual((row.kind, row.next_run_at, row.payee_name), ('card', None, 'Tarjeta Confío'))
        out = Query().resolve_smart_account_card_rules(self.info(self.owner))
        self.assertEqual(len(out), 1)
        card = out[0]
        self.assertEqual((card.cap_usd, card.spent_usd, card.remaining_usd, card.period_days),
                         ('100.00', '25.00', '75.00', 7))
        self.assertEqual(card.period_end, self.now + timedelta(days=7))
        self.assertEqual([(p.usd_spent, p.usdt_out) for p in card.recent_pulls], [('25.00', '24.77')])

    def test_mutation_is_its_own_field_and_allowed_in_the_smart_context(self):
        from smart_account.context import ALLOWED_MUTATIONS
        from smart_account.schema import Mutation
        self.assertIn('prepare_smart_account_card_rule', Mutation._meta.fields)
        self.assertIn('prepareSmartAccountCardRule', ALLOWED_MUTATIONS)

    def test_assistant_describes_card_rules_and_never_proposes_one(self):
        account = self.subscribe()
        rule = self.card_rule(account, amount=100)
        self.pull(Decimal('9.91'), Decimal('10'), when=self.now + timedelta(hours=1))
        with mock.patch('smart_account.services.payout_method_rows', return_value=[]):
            snapshot = assistant_ops.rules_snapshot(self.owner)
        card = next(r for r in snapshot['reglas'] if r['tipo'] == 'card')
        self.assertIsNone(card['proxima_ejecucion'])
        self.assertEqual((card['tarjeta'], card['usado_este_periodo_usd'], card['disponible_este_periodo_usd']),
                         ('Tarjeta Confío', '10.00', '90.00'))
        with self.assertRaises(assistant_ops.OpsRefused):
            assistant_ops.propose_rule(self.owner, amount_given=True, said='sube mi tarjeta a 200', action='update',
                                       rule_id=str(rule.internal_id), amount_usd='200')
        with self.assertRaises(assistant_ops.OpsRefused):
            assistant_ops.propose_rule(self.owner, amount_given=True, said='tarjeta de 50 cada semana', action='create', kind='card',
                                       amount_usd='50', frequency='weekly')
        stop = assistant_ops.propose_rule(self.owner, amount_given=True, said='detén mi tarjeta', action='cancel',
                                          rule_id=str(rule.internal_id))
        self.assertEqual(stop['steps'][0]['kind'], 'card')
        self.assertIn('Tarjeta Confío', stop['steps'][0]['sentence'])

    def test_monthly_review_counts_card_pulls(self):
        account = self.subscribe()
        self.card_rule(account)
        self.pull(Decimal('9.91'), Decimal('10'), when=self.now)
        data = assistant_ops.review(self.owner, now=self.now)
        self.assertEqual((data['pagos_con_tarjeta']['cantidad'], data['pagos_con_tarjeta']['total_usd']), (1, '10.00'))
        card_rule = next(r for r in data['reglas'] if r['tipo'] == 'card')
        self.assertEqual(card_rule['tarjeta'], 'Tarjeta Confío')

    def test_admin_registers_card_models_on_the_custom_site(self):
        from config.admin_dashboard import confio_admin_site
        for model in (SmartAccountCardSpender, SmartAccountCardPause, SmartAccountCardPull):
            self.assertIn(model, confio_admin_site._registry)
        spender_admin = confio_admin_site._registry[SmartAccountCardSpender]
        self.assertNotIn('label', spender_admin.readonly_fields)
        self.assertIn('allowed', spender_admin.readonly_fields)
        self.assertFalse(spender_admin.has_add_permission(None))
