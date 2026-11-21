"""Confío IA+ operates the Cuenta inteligente (spec decision 34): rule
proposals, target allocation kept by new buys only, the monthly review and
owner-set alerts. No real LLM or provider is called."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.utils import timezone

from smart_account import assistant_ops as ops, services, watches
from smart_account.assets import Asset
from smart_account.models import (
    SmartAccountCharge, SmartAccountEvent, SmartAccountRule, SmartAccountRuleRun, SmartAccountTargetAllocation,
    SmartAccountWatch,
)

from .base import BUILD, SmartAccountTestCase, VAULT

UTC = ZoneInfo('UTC')
BUYABLE = [
    {'asset_key': 'stock:SPYon', 'kind': 'stock', 'symbol': 'SPY', 'name': 'SPDR S&P 500 ETF'},
    {'asset_key': 'stock:TSLAon', 'kind': 'stock', 'symbol': 'TSLA', 'name': 'Tesla'},
    {'asset_key': 'crypto:BTCB', 'kind': 'crypto', 'symbol': 'BTC', 'name': 'Bitcoin'},
]


def _resolve(key):
    if key.startswith('stock:'):
        return 'stock', key[6:], '0x' + '77' * 20, 18
    if key.startswith('crypto:'):
        return 'crypto', key[7:], '0x' + '88' * 20, 18
    return None


def holding(key, value):
    kind, symbol = ('stock', key[6:]) if key.startswith('stock:') else ('crypto', key[7:])
    return Asset(key, kind, symbol, symbol, '0x' + '99' * 20, 1, 18, Decimal(value), True)


class OpsBase(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        for target, kwargs in [
            ('smart_account.services.buyable_assets', {'side_effect': lambda viewer, search='': list(BUYABLE)}),
            ('smart_account.quotes.min_stock_rule_amount', {'return_value': Decimal('2.00')}),
            ('smart_account.assets.resolve_asset_key', {'side_effect': _resolve}),
        ]:
            patcher = mock.patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.owner = self.make_user('ana')
        self.account = self.make_account(self.owner)
        from smart_account import entitlements
        entitlements.sync_account(self.account)

    def buy_rule(self, key, amount, onchain_id, frequency='monthly'):
        return SmartAccountRule.objects.create(
            smart_account=self.account, onchain_id=onchain_id, state='onchain', kind='buy', token_in=VAULT,
            asset_key=key, amount=Decimal(amount), frequency=frequency, active=True)

    def holdings(self, values):
        patcher = mock.patch('smart_account.assets.assets_of',
                             return_value=[holding(k, v) for k, v in values.items()])
        patcher.start()
        self.addCleanup(patcher.stop)


class SplitMathTests(OpsBase):
    W = {'stock:SPYon': 7000, 'crypto:BTCB': 3000}

    def test_split_adds_up_to_the_total(self):
        out = ops.split_amounts(Decimal('33.33'), self.W)
        self.assertEqual(sum(out.values()), Decimal('33.33'))
        self.assertEqual(out['crypto:BTCB'], Decimal('9.99'))

    def test_drift_split_steers_new_money_to_the_underweight_asset_and_never_sells(self):
        held = {'stock:SPYon': Decimal('900'), 'crypto:BTCB': Decimal('100')}  # 90/10 vs 70/30
        mins = {'stock:SPYon': Decimal('2'), 'crypto:BTCB': Decimal('1')}
        out = ops.drift_split(Decimal('100'), self.W, held, mins)
        self.assertEqual(sum(out.values()), Decimal('100'))
        self.assertEqual(out['stock:SPYon'], Decimal('2'))     # overweight keeps only its minimum
        self.assertEqual(out['crypto:BTCB'], Decimal('98'))
        self.assertTrue(all(v > 0 for v in out.values()))

    def test_drift_split_refuses_when_minimums_exceed_the_total(self):
        self.assertIsNone(ops.drift_split(Decimal('2.50'), self.W, {}, {'stock:SPYon': Decimal('2'),
                                                                        'crypto:BTCB': Decimal('1')}))

    def test_tiny_total_cannot_move_a_large_position(self):
        held = {'stock:SPYon': Decimal('90000'), 'crypto:BTCB': Decimal('10000')}
        mins = {'stock:SPYon': Decimal('2'), 'crypto:BTCB': Decimal('1')}
        periods = ops.periods_to_target(Decimal('10'), self.W, held,
                                        lambda h: ops.drift_split(Decimal('10'), self.W, h, mins), Decimal('5'))
        self.assertIsNone(periods)


class ProposeRuleTests(OpsBase):
    def propose(self, said, **kw):
        return ops.propose_rule(self.owner, said=said, meta=BUILD, tz=UTC, **kw)

    def test_buy_rule_with_day_of_month(self):
        now = timezone.datetime(2026, 11, 21, 12, tzinfo=UTC)
        out = self.propose('compra $10 de bitcoin cada mes el día 1', action='create', kind='buy', asset='bitcoin',
                           amount_usd='10', frequency='monthly', day_of_month=1, now=now)
        (step,) = out['steps']
        self.assertEqual((step['action'], step['kind'], step['asset_key'], step['amount_usd']),
                         ('create', 'buy', 'crypto:BTCB', '10.00'))
        self.assertTrue(step['first_run_at'].startswith('2026-12-01T10:00'))
        self.assertIn('nunca vende', step['sentence'])

    def test_amount_and_asset_must_be_the_owners_words(self):
        with self.assertRaises(ops.OpsRefused) as ctx:
            self.propose('quiero invertir en bitcoin', action='create', kind='buy', asset='bitcoin',
                         amount_usd='50', frequency='monthly')
        self.assertEqual(ctx.exception.code, 'not_said')
        with self.assertRaises(ops.OpsRefused) as ctx:
            self.propose('invierte 50 cada mes en algo bueno', action='create', kind='buy', asset='SPY',
                         amount_usd='50', frequency='monthly')
        self.assertEqual(ctx.exception.code, 'not_said')

    def test_stock_minimum_and_bad_days(self):
        with self.assertRaises(ops.OpsRefused):
            self.propose('compra 1 de SPY cada mes', action='create', kind='buy', asset='SPY', amount_usd='1',
                         frequency='monthly')
        with self.assertRaises(ops.OpsRefused):
            self.propose('compra 10 de SPY cada mes el 31', action='create', kind='buy', asset='SPY',
                         amount_usd='10', frequency='monthly', day_of_month=31)
        with self.assertRaises(ops.OpsRefused):
            self.propose('compra 10 de SPY cada mes los lunes', action='create', kind='buy', asset='SPY',
                         amount_usd='10', frequency='monthly', weekday=0)

    def test_send_rule_to_a_confio_user(self):
        mom = self.make_user('mama')
        out = self.propose('manda $50 a @mama el día 1', action='create', kind='send', payee='@mama',
                           amount_usd='50', frequency='monthly', day_of_month=1)
        self.assertEqual(out['steps'][0]['payee_handle'], 'mama')
        with self.assertRaises(ops.OpsRefused):
            self.propose('manda 50 a @ana', action='create', kind='send', payee='@ana', amount_usd='50',
                         frequency='monthly')
        self.assertTrue(mom.pk)

    def test_cancel_is_the_pause(self):
        rule = self.buy_rule('stock:SPYon', '10', 1)
        out = self.propose('pausa mi regla de SPY', action='cancel', rule_id=str(rule.internal_id))
        self.assertEqual(out['steps'][0]['action'], 'cancel')
        self.assertIn('se crea de nuevo', out['steps'][0]['sentence'])

    def test_no_account_no_proposal(self):
        other = self.make_user('beto')
        with self.assertRaises(ops.OpsRefused):
            ops.propose_rule(other, said='compra 10 de SPY', action='create', kind='buy', asset='SPY',
                             amount_usd='10', frequency='monthly', tz=UTC)


class TargetAllocationTests(OpsBase):
    def set_target(self, said='mantén 70/30 entre SPY y bitcoin con 100 cada mes', **kw):
        args = dict(action='set', assets=[{'asset': 'SPY', 'percent': 70}, {'asset': 'bitcoin', 'percent': 30}],
                    total_usd='100', frequency='monthly')
        args.update(kw)
        return ops.propose_target_allocation(self.owner, said=said, meta=BUILD, tz=UTC, **args)

    def test_assistant_never_chooses_the_ratio(self):
        with self.assertRaises(ops.OpsRefused) as ctx:
            self.set_target(said='repárteme 100 al mes entre SPY y bitcoin como te parezca')
        self.assertEqual(ctx.exception.code, 'not_said')
        self.assertFalse(SmartAccountTargetAllocation.objects.exists())

    def test_percentages_must_add_to_100(self):
        with self.assertRaises(ops.OpsRefused):
            self.set_target(said='70 y 20 entre SPY y bitcoin con 100',
                            assets=[{'asset': 'SPY', 'percent': 70}, {'asset': 'bitcoin', 'percent': 20}])

    def test_set_saves_and_proposes_one_buy_rule_per_asset(self):
        existing = self.buy_rule('stock:SPYon', '50', 1)
        out = self.set_target()
        row = SmartAccountTargetAllocation.objects.get()
        self.assertEqual(row.total_usd, Decimal('100'))
        steps = {s['asset_key']: s for s in out['steps']}
        self.assertEqual(steps['stock:SPYon']['action'], 'update')
        self.assertEqual(steps['stock:SPYon']['rule_id'], str(existing.internal_id))
        self.assertEqual(steps['stock:SPYon']['amount_usd'], '70.00')
        self.assertEqual(steps['crypto:BTCB']['action'], 'create')
        self.assertEqual(steps['crypto:BTCB']['amount_usd'], '30.00')
        self.assertTrue(all(s['kind'] == 'buy' for s in out['steps']))

    def test_drift_proposes_new_buys_only(self):
        self.set_target()
        self.buy_rule('stock:SPYon', '70', 1)
        self.buy_rule('crypto:BTCB', '30', 2)
        self.holdings({'stock:SPYon': '900', 'crypto:BTCB': '100'})
        out = ops.propose_target_allocation(self.owner, said='¿cómo vuelvo a mi objetivo?', action='next_split',
                                            tz=UTC, meta=BUILD)
        self.assertTrue(out['nunca_vende'])
        self.assertTrue(out['steps'])
        self.assertTrue(all(s['action'] in ('update', 'create') and s['kind'] == 'buy' for s in out['steps']))
        total = sum(Decimal(s['amount_usd']) for s in out['steps'])
        self.assertEqual(total, Decimal('100'))
        by_key = {s['asset_key']: Decimal(s['amount_usd']) for s in out['steps']}
        self.assertGreater(by_key['crypto:BTCB'], Decimal('30'))

    def test_within_threshold_nothing_to_do(self):
        self.set_target()
        self.holdings({'stock:SPYon': '710', 'crypto:BTCB': '290'})
        out = ops.propose_target_allocation(self.owner, said='revisa mi objetivo', action='next_split', tz=UTC)
        self.assertEqual(out['steps'], [])

    def test_too_small_to_move_says_so(self):
        self.set_target(said='70/30 entre SPY y bitcoin con 10 cada mes', total_usd='10')
        self.holdings({'stock:SPYon': '90000', 'crypto:BTCB': '10000'})
        out = ops.propose_target_allocation(self.owner, said='x', action='next_split', tz=UTC)
        self.assertIn('más de 5 años', out['texto'])


class ReviewAndNotesTests(OpsBase):
    def test_review_counts_runs_and_reasons(self):
        rule = self.buy_rule('stock:SPYon', '10', 1)
        now = timezone.now()
        SmartAccountRuleRun.objects.create(rule=rule, scheduled_for=now - timedelta(minutes=5), status='ok')
        SmartAccountRuleRun.objects.create(rule=rule, scheduled_for=now - timedelta(minutes=4), status='skipped',
                                           message='No alcanzó el saldo.')
        event = SmartAccountEvent.objects.create(smart_account=self.account, address=self.account.contract_address,
                                                 tx_hash='0x' + '1' * 64, log_index=0, name='FeeCollected',
                                                 block_number=1, block_time=now)
        SmartAccountCharge.objects.create(smart_account=self.account, event=event, plan='monthly', period_start=now,
                                          period_end=now, fee_usd=Decimal('14.99'), tx_hash=event.tx_hash,
                                          charged_at=now)
        self.holdings({})
        data = ops.review(self.owner, tz=UTC)
        self.assertEqual(data['cobros_del_plan'][0]['monto_usd'], '14.99')
        (row,) = data['reglas']
        self.assertEqual(row['ejecutadas'], 1)
        self.assertEqual(row['omitidas'][0]['motivo'], 'No alcanzó el saldo.')

    def test_monthly_note_once_per_month_and_only_for_subscribers(self):
        self.holdings({})
        with mock.patch('smart_account.assistant_ops.review', wraps=ops.review):
            first = ops.post_monthly_notes()
            second = ops.post_monthly_notes()
        self.assertEqual(first['posted'], 1)
        self.assertEqual(second['posted'], 0)
        from inbox.models import SupportMessage
        note = SupportMessage.objects.get(metadata__system_note=True)
        self.assertIn('Resumen de tu Cuenta inteligente', note.body)
        self.assertNotIn('compra', note.body.split('\n')[0].lower())

    def test_monthly_task_is_gated_by_the_flag(self):
        from django.test import override_settings
        from smart_account import tasks
        with override_settings(SMART_ACCOUNT_ENABLED=False):
            self.assertEqual(tasks.monthly_review_notes(), {'skipped': 'disabled'})
            self.assertEqual(tasks.evaluate_watches(), {'skipped': 'disabled'})


class FirstRunTests(OpsBase):
    def test_requested_first_run_bounds(self):
        now = timezone.now()
        with self.assertRaises(services.PrepareError):
            services.requested_first_run((now - timedelta(days=1)).isoformat(), 'monthly', now=now)
        with self.assertRaises(services.PrepareError):
            services.requested_first_run((now + timedelta(days=90)).isoformat(), 'monthly', now=now)
        with self.assertRaises(services.PrepareError):
            services.requested_first_run((now + timedelta(days=2)).isoformat(), 'daily', now=now)
        self.assertEqual(services.requested_first_run(None, 'monthly', floor=123), 123)

    def test_an_edit_never_runs_earlier_than_the_current_slot(self):
        now = timezone.now()
        floor = int((now + timedelta(days=10)).timestamp())
        got = services.requested_first_run((now + timedelta(days=2)).isoformat(), 'weekly', floor=floor, now=now)
        self.assertGreaterEqual(got, floor)
        self.assertEqual((got - int((now + timedelta(days=2)).timestamp())) % (7 * 86400), 0)


class WatchTests(OpsBase):
    def setUp(self):
        super().setUp()
        self.prices = {'stock:TSLAon': Decimal('200')}
        patcher = mock.patch('smart_account.watches.asset_price',
                             side_effect=lambda key, cache=None: self.prices.get(key))
        patcher.start()
        self.addCleanup(patcher.stop)

    def draft(self, said='avísame si TSLA baja 5% y prepárame una compra de 100', **kw):
        args = dict(kind='asset_price_drop_pct', asset='TSLA', threshold='5', action_asset='TSLA',
                    action_amount_usd='100')
        args.update(kw)
        return watches.propose(self.owner, said=said, meta=BUILD, **args)

    def test_level_must_be_the_owners(self):
        with self.assertRaises(ops.OpsRefused) as ctx:
            self.draft(said='avísame cuando TSLA esté barata', threshold='5')
        self.assertEqual(ctx.exception.code, 'not_said')

    def test_trigger_once_per_cooldown_with_a_signable_buy(self):
        watch = watches.save(self.owner, self.draft())
        self.assertEqual(watch.reference_price, Decimal('200'))
        self.prices['stock:TSLAon'] = Decimal('189')
        out = watches.evaluate()
        self.assertEqual(out['triggered'], 1)
        self.assertEqual(watches.evaluate()['triggered'], 0)   # cooldown
        from inbox.models import SupportMessage
        note = SupportMessage.objects.get(metadata__system_note=True)
        self.assertEqual(note.metadata['actions'][0]['target'], 'smart_account_rule')
        step = note.metadata['rule_proposal']['steps'][0]
        self.assertEqual((step['action'], step['kind'], step['amount_usd']), ('create', 'buy', '100.00'))
        self.assertIn('No se ejecuta sin tu firma', note.body)
        # Nothing was prepared or put on chain.
        self.assertFalse(SmartAccountRule.objects.exists())

    def test_not_triggered_above_the_level(self):
        watches.save(self.owner, self.draft())
        self.prices['stock:TSLAon'] = Decimal('195')
        self.assertEqual(watches.evaluate()['triggered'], 0)

    def test_at_most_ten(self):
        for _ in range(watches.MAX_ACTIVE):
            watches.save(self.owner, self.draft())
        with self.assertRaises(ops.OpsRefused):
            self.draft()

    def test_delete_is_owner_only(self):
        watch = watches.save(self.owner, self.draft())
        other = self.make_user('carla')
        self.assertFalse(watches.delete(other, watch.internal_id))
        self.assertTrue(watches.delete(self.owner, watch.internal_id))
        self.assertFalse(SmartAccountWatch.objects.filter(active=True).exists())


class EngineToolTests(OpsBase):
    def belt(self, user, account_type='personal', owner=True):
        from assistant.engine import Toolbelt, TurnResult, Viewer
        from users.models import Account
        viewer = Viewer(user=user, account=Account.objects.filter(user=user, account_type='personal').first(),
                        account_type=account_type, business_id=1 if account_type == 'business' else None,
                        is_business_owner=owner, tz=UTC, request_meta=dict(BUILD))
        belt = Toolbelt(viewer, TurnResult(reply=''), analyses_left=0)
        return belt

    def names(self, belt):
        return {s['name'] for s in belt.specs()}

    def test_tools_only_for_subscribers_never_employees(self):
        self.assertIn('propose_smart_account_rule', self.names(self.belt(self.owner)))
        self.assertNotIn('propose_smart_account_rule', self.names(self.belt(self.owner, 'business', owner=False)))
        free = self.make_user('libre')
        self.assertNotIn('smart_account_rules', self.names(self.belt(free)))
        self.assertIn('herramienta desconocida', str(self.belt(free).call('smart_account_rules', {})))

    def test_one_proposal_per_reply_with_one_chip(self):
        belt = self.belt(self.owner)
        belt.last_user_message = 'compra 10 de SPY cada mes'
        args = dict(action='create', kind='buy', rule_id=None, payee=None, payout_method_id=None, asset='SPY',
                    amount_usd='10', frequency='monthly', weekday=None, day_of_month=None, start_date=None)
        first = belt.call('propose_smart_account_rule', args)
        self.assertTrue(first['pendiente_de_firma'])
        second = belt.call('propose_smart_account_rule', args)
        self.assertTrue(second['_denied'])
        chips = [a for a in belt.result.actions if a.get('target') == 'smart_account_rule']
        self.assertEqual(len(chips), 1)
        self.assertEqual(chips[0]['destination'], 'cuenta_inteligente')
        self.assertEqual(belt.result.rule_proposal['steps'][0]['asset_key'], 'stock:SPYon')

    def test_proposal_query_is_owner_only(self):
        from assistant.schema import Query
        from inbox.models import SupportMessage
        from inbox.schema import get_or_create_support_conversation
        from smart_account import context
        conv = get_or_create_support_conversation(self.owner, context.personal_account(self.owner), None)
        message = SupportMessage.objects.create(
            conversation=conv, sender_type='AGENT', message_type='TEXT', body='x',
            metadata={'ai': True, 'rule_proposal': {'created_at': timezone.now().isoformat(), 'steps': [
                {'action': 'create', 'kind': 'buy', 'asset_key': 'stock:SPYon', 'amount_usd': '10.00',
                 'frequency': 'monthly', 'sentence': 's'}]}})
        resolve = Query.resolve_assistant_rule_proposal.__wrapped__
        mine = resolve(None, self.info(self.owner), str(message.pk))
        self.assertEqual(mine.steps[0].asset_key, 'stock:SPYon')
        self.assertFalse(mine.expired)
        other = self.make_user('zed')
        self.assertIsNone(resolve(None, self.info(other), str(message.pk)))


class WatchConfirmationTests(WatchTests):
    def test_saved_only_on_the_owners_yes_to_that_message(self):
        from assistant import service
        from inbox.models import SupportMessage
        from inbox.schema import get_or_create_support_conversation
        from smart_account import context
        conv = get_or_create_support_conversation(self.owner, context.personal_account(self.owner), None)
        draft = self.draft()
        reply = SupportMessage.objects.create(conversation=conv, sender_type='AGENT', message_type='TEXT',
                                              body='¿Guardo esta alerta?', metadata={'ai': True})
        viewer = mock.Mock(user=self.owner)
        service._store_pending_watch(conv, viewer, draft, reply)
        pending = service.take_pending_watch(conv)
        self.assertIsNone(service.take_pending_watch(conv))  # one message consumes it
        no = SupportMessage.objects.create(conversation=conv, sender_type='USER', message_type='TEXT', body='no')
        self.assertIsNone(service.confirm_pending_watch(conv, viewer, 'no', pending, no))
        self.assertFalse(SmartAccountWatch.objects.exists())
        yes = SupportMessage.objects.create(conversation=conv, sender_type='USER', message_type='TEXT', body='sí')
        saved, text = service.confirm_pending_watch(conv, viewer, 'sí', pending, yes)
        self.assertEqual(saved, 1)
        self.assertIn('nada se compra ni se vende sin tu firma', text)
        self.assertEqual(SmartAccountWatch.objects.count(), 1)


class PayeeMustBeSaidTests(OpsBase):
    """The payee or destination of a proposed rule is in the owner's own
    words this turn, or already one the owner pays by rule."""

    def propose(self, said, **kw):
        args = dict(action='create', kind='send', amount_usd='50', frequency='monthly')
        args.update(kw)
        return ops.propose_rule(self.owner, said=said, meta=BUILD, tz=UTC, **args)

    def setUp(self):
        super().setUp()
        self.payee = self.make_user('jperez')
        type(self.payee).objects.filter(pk=self.payee.pk).update(first_name='Juana', last_name='Pérez Rivas')
        self.payee.refresh_from_db()

    def test_handle_said(self):
        self.assertEqual(self.propose('manda 50 a @jperez cada mes', payee='@jperez')['steps'][0]['payee_handle'],
                         'jperez')

    def test_full_name_said(self):
        for said in ('manda 50 a juana perez rivas cada mes', 'manda 50 a Juana Pérez Rivas, cada mes'):
            self.assertEqual(self.propose(said, payee='jperez')['steps'][0]['payee_handle'], 'jperez', said)

    def test_a_single_name_part_or_a_partial_name_is_refused(self):
        for said in ('manda 50 a Juana cada mes', 'envíale 50 a Pérez', 'manda 50 a juana perez cada mes',
                     'manda 50 a rivas, juana y perez'):
            with self.assertRaises(ops.OpsRefused) as ctx:
                self.propose(said, payee='jperez')
            self.assertEqual(ctx.exception.code, 'not_said', said)

    def test_attacker_named_like_a_relative_is_refused(self):
        # A stranger picks the username @mama, or the display name
        # "Mamá Semana": neither matches "envíale a mi mamá cada semana".
        handle = self.make_user('mama')
        named = self.make_user('xk_9921')
        type(named).objects.filter(pk=named.pk).update(first_name='Mamá', last_name='Semana')
        for payee in ('@mama', '@xk_9921'):
            for said in ('envíale 50 a mi mamá cada semana', 'envíale 50 a mi mama cada semana'):
                with self.assertRaises(ops.OpsRefused) as ctx:
                    self.propose(said, payee=payee, frequency='weekly')
                self.assertEqual(ctx.exception.code, 'not_said', (payee, said))
        # The exact @usuario still works, and the proposal names it.
        out = self.propose('envíale 50 a @mama cada semana', payee='@mama', frequency='weekly')
        self.assertIn('@mama', out['steps'][0]['sentence'])
        self.assertTrue(handle.pk)

    def test_bare_username_needs_its_at_unless_it_cannot_be_a_word(self):
        with self.assertRaises(ops.OpsRefused):
            self.propose('manda 50 a jperez cada mes', payee='jperez')
        odd = self.make_user('jp_88')
        self.assertEqual(self.propose('manda 50 a jp_88 cada mes', payee='jp_88')['steps'][0]['payee_handle'],
                         'jp_88')
        with self.assertRaises(ops.OpsRefused):
            self.propose('manda 50 a @jp_888 cada mes', payee='jp_88')
        self.assertTrue(odd.pk)
        digits = self.make_user('5551234')
        with self.assertRaises(ops.OpsRefused):
            self.propose('manda 50 a 5551234 cada mes', payee='5551234')
        self.assertEqual(self.propose('manda 50 a @5551234 cada mes', payee='@5551234')['steps'][0]['payee_handle'],
                         '5551234')
        self.assertTrue(digits.pk)

    def test_send_sentence_always_names_the_handle(self):
        out = self.propose('manda 50 a juana perez rivas cada mes', payee='jperez')
        self.assertIn('Juana Pérez Rivas (@jperez)', out['steps'][0]['sentence'])

    def _with_phone(self, user, country, local):
        type(user).objects.filter(pk=user.pk).update(phone_country=country, phone_number=local)
        user.refresh_from_db()
        return user

    def assert_said(self, country, local, saids, payee='@jperez'):
        self._with_phone(self.payee, country, local)
        with mock.patch('smart_account.services.resolve_handle', return_value=self.payee):
            for said in saids:
                out = self.propose(said, payee=payee)
                self.assertEqual(out['steps'][0]['payee_handle'], 'jperez', (country, said))

    def assert_refused(self, country, local, saids, payee='@jperez', person=None):
        person = self._with_phone(person or self.payee, country, local)
        with mock.patch('smart_account.services.resolve_handle', return_value=person):
            for said in saids:
                with self.assertRaises(ops.OpsRefused, msg=(country, said)) as ctx:
                    self.propose(said, payee=payee)
                self.assertEqual(ctx.exception.code, 'not_said', (country, said))

    def test_the_full_phone_is_accepted_as_people_write_it(self):
        self.assert_said('VE', '4141234567', (
            'manda 50 al 0414 1234567 cada mes', 'manda 50 al 0414-123-4567', 'manda 50 al 04141234567',
            'manda 50 al +58 414 1234567 cada mes', 'manda 50 al +58 0414 1234567 cada mes',
            'manda 50 al +58 0414-123-4567 cada mes', 'manda 50 al 0058 414 1234567 cada mes',
            'manda 50 al 0058 0414 1234567 cada mes', 'manda 50 al (0414) 123.45.67 cada mes',
            'manda 50 al 0414\u20131234567 cada mes', 'manda 50 al 0414\u00a0123\u00a04567 cada mes'))
        self.assert_said('VE', '04141234567', ('manda 50 al +58 414 1234567 cada mes',))
        self.assert_said('CO', '3001234567', ('manda 50 al +57 300 123 4567 cada mes',
                                              'manda 50 al 300 1234567 cada mes'))
        self.assert_said('BO', '71234567', ('manda 50 al +591 7123 4567 cada mes', 'manda 50 al 71234567 cada mes',
                                            'manda 50 al 7123 4567 cada mes'))
        self.assert_said('MX', '5512345678', ('manda 50 al +52 1 55 1234 5678 cada mes',
                                              'manda 50 al +52 55 1234 5678 cada mes',
                                              'manda 50 al 55 1234 5678 cada mes'))
        self.assert_said('AR', '1112345678', ('manda 50 al +54 9 11 1234 5678 cada mes',
                                              'manda 50 al 011 15 1234-5678 cada mes',
                                              'manda 50 al 11 1234 5678 cada mes'))
        # A stored number that kept its mobile 9 matches the same forms.
        self.assert_said('AR', '91112345678', ('manda 50 al +54 9 11 1234 5678 cada mes',
                                               'manda 50 al 11 1234 5678 cada mes'))
        self.assert_said('PE', '912345678', ('manda 50 al +51 912 345 678 cada mes', 'manda 50 al 912345678 cada mes'))

    def test_username_passed_and_only_the_phone_said(self):
        # The model looked the owner's number up and passed @jperez: the
        # number is compared with Juana's stored phone, not the handle.
        self._with_phone(self.payee, 'VE', '4141234567')
        out = self.propose('manda 50 al +58 0414-123-4567 cada mes', payee='@jperez')
        self.assertEqual(out['steps'][0]['payee_handle'], 'jperez')

    def test_an_amount_written_next_to_the_phone_does_not_hide_it(self):
        # "20 0414 1234567" joins into one number; each run of groups that
        # ends it is also read, so the phone after the amount is found.
        self._with_phone(self.payee, 'VE', '4141234567')
        out = self.propose('envía 20 0414 1234567 cada mes', payee='@jperez', amount_usd='20')
        self.assertEqual(out['steps'][0]['payee_handle'], 'jperez')

    def test_a_tail_of_the_phone_is_never_enough(self):
        self.assert_refused('VE', '4141234567', (
            'manda 50 al que termina en 1234567', 'manda 50 al 1234567 cada mes', 'manda 50 al 414 1234 cada mes',
            'envía 20 0414 123456 cada mes'), payee='+584141234567')

    def test_digits_are_never_joined_across_numbers(self):
        self.assert_refused('VE', '4141234567', ('manda 50 y 123 a 4567 el 4141', 'manda 50, 41412 y luego 34567'),
                            payee='+584141234567')

    def test_another_number_whose_last_digits_match_is_refused(self):
        # However the two parts are separated, "0412 ... 1234567" is not
        # 0414 1234567, and its last group is no tail of it either.
        self.assert_refused('VE', '4141234567', tuple(
            f'manda 50 al 0412{sep}1234567 cada mes'
            for sep in (' ', ' - ', '\u2013', '\u2014', '\u2011', '\u2212', '/', '_', ',', '.', '-')))

    def test_extra_leading_digits_or_a_wrong_calling_code_are_refused(self):
        self.assert_refused('VE', '4141234567', (
            'manda 50 al +1 414 123 4567 cada mes', 'manda 50 al +57 4141234567 cada mes',
            'manda 50 al +59 1414 1234567 cada mes', 'manda 50 al 0057 414 1234567 cada mes',
            'manda 50 al 14141234567 cada mes',
            'manda 50 al +58 0414-765-4321 cada mes', 'manda 50 al +57 300 999 8877 cada mes'))

    def test_a_calling_code_written_without_plus_is_never_dropped(self):
        self.assert_refused('VE', '4141234567', (
            'manda 50 al 1 414 123 4567 cada mes', 'manda 50 al 1-414-123-4567 cada mes',
            'manda 50 al 1.414.123.4567 cada mes', 'manda 50 al 1 (414) 123-4567 cada mes',
            'manda 50 al (1) 414 123 4567 cada mes', 'manda 50 al + 1 414 123 4567 cada mes',
            'manda 50 al ＋1 414 123 4567 cada mes', 'envía 20 00 1 414 123 4567 cada mes',
            'manda 50 al 57 414 123 4567 cada mes'))
        self.assert_refused('CO', '3001234567', ('manda 50 al 1 300 123 4567 cada mes',))
        self.assert_refused('BO', '71234567', ('manda 50 al 6 71234567 cada mes',))

    def test_digits_glued_to_a_word_or_handle_are_not_a_phone(self):
        self.assert_refused('VE', '4141234567', (
            'manda 50 a @juan04141234567 cada mes', 'manda 50 a @0414 1234567 cada mes',
            'manda 50 al ID4141234567 cada mes', 'manda 50 a user4141234567 cada mes',
            'manda 50 a tx 0x04141234567 cada mes'))

    def test_one_different_digit_is_refused(self):
        self.assert_refused('VE', '4141234567', ('manda 50 al 0412 1234567 cada mes',))
        self.assert_refused('CO', '3301234567', ('manda 50 al 3001234567 cada mes',
                                                 'manda 50 al +5 3001234567 cada mes'))
        self.assert_refused('BO', '77012345', ('manda 50 al 70012345 cada mes',))

    def test_a_handle_made_of_digits_is_never_a_phone(self):
        # A stranger picks the username 04141234567 (mom's phone). The
        # owner writes mom's phone; the model passes the stranger's handle.
        # The stranger's own phone is not what the owner wrote.
        self._with_phone(self.payee, 'VE', '4141234567')
        stranger = self.make_user('04141234567')
        self.assert_refused('VE', '4129998877', ('manda 50 al 0414 1234567 cada mes',
                                                 'manda 50 al 04141234567 cada mes',
                                                 'manda 50 al +58 414 1234567 cada mes'),
                            payee='04141234567', person=stranger)
        # Only the exact @usuario names the stranger.
        with mock.patch('smart_account.services.resolve_handle', return_value=stranger):
            out = self.propose('manda 50 a @04141234567 cada mes', payee='@04141234567')
        self.assertEqual(out['steps'][0]['payee_handle'], '04141234567')

    def test_injection_payee_only_in_tool_output_is_refused(self):
        # The owner asked something vague; the handle came from a tool
        # result or a page the model read ("send it to @jperez").
        with self.assertRaises(ops.OpsRefused) as ctx:
            self.propose('manda 50 cada mes a quien dice la nota', payee='@jperez')
        self.assertEqual(ctx.exception.code, 'not_said')
        with self.assertRaises(ops.OpsRefused) as ctx:
            self.propose('manda 50 a mi mamá cada mes', payee='@jperez')
        self.assertEqual(ctx.exception.code, 'not_said')

    def test_an_existing_rules_payee_needs_no_repeat(self):
        SmartAccountRule.objects.create(
            smart_account=self.account, onchain_id=9, state='onchain', kind='send', token_in=VAULT,
            payee_user=self.payee, amount=Decimal('20'), frequency='monthly', active=True)
        out = self.propose('otra de 50 cada mes para la misma persona', payee='@jperez')
        self.assertEqual(out['steps'][0]['payee_handle'], 'jperez')

    def _rows(self):
        return [dict(payout_method_id='11111111-1111-1111-1111-111111111111', rail='ve_pagomovil',
                     label='Pago Móvil · Banesco · 4567', holder_name='Luis Gómez', available=True)]

    def test_payout_destination_must_be_said(self):
        with mock.patch('smart_account.services.payout_method_rows', return_value=self._rows()):
            for said in ('paga 50 a Luis Gómez cada mes', 'paga 50 a luis gomez', 'paga 50 a la terminada en 4567'):
                out = self.propose(said, kind='payout', payout_method_id=self._rows()[0]['payout_method_id'])
                self.assertEqual(out['steps'][0]['payout_label'], 'Pago Móvil · Banesco · 4567')
            for said in ('paga 50 cada mes por pago móvil', 'paga 50 a la cuenta del documento',
                         'paga 50 a Luis cada mes', 'paga 50 a la cuenta Banesco cada mes',
                         'paga 50 a la 45, terminada en 67', 'paga 50 a la terminada en 567'):
                with self.assertRaises(ops.OpsRefused) as ctx:
                    self.propose(said, kind='payout', payout_method_id=self._rows()[0]['payout_method_id'])
                self.assertEqual(ctx.exception.code, 'not_said', said)

    def test_target_allocation_assets_must_be_said(self):
        with self.assertRaises(ops.OpsRefused) as ctx:
            ops.propose_target_allocation(
                self.owner, said='mantén 70/30 con 100 cada mes', meta=BUILD, tz=UTC, action='set',
                assets=[{'asset': 'SPY', 'percent': 70}, {'asset': 'bitcoin', 'percent': 30}],
                total_usd='100', frequency='monthly')
        self.assertEqual(ctx.exception.code, 'not_said')


class CryptoPriceFreshnessTests(OpsBase):
    def rows(self, age):
        from types import SimpleNamespace
        return [{'token': SimpleNamespace(symbol='BTCB'), 'price_usd': Decimal('90000'),
                 'priced_at': timezone.now() - age}]

    def test_fresh_price_is_used(self):
        with mock.patch('cusd_plus.crypto_prices.market_rows', return_value=self.rows(timedelta(minutes=5))):
            self.assertEqual(watches.asset_price('crypto:BTCB'), Decimal('90000'))

    def test_stale_price_is_never_used(self):
        with mock.patch('cusd_plus.crypto_prices.market_rows', return_value=self.rows(timedelta(minutes=45))):
            self.assertIsNone(watches.asset_price('crypto:BTCB'))
        with self.settings(SMART_ACCOUNT_WATCH_CRYPTO_MAX_AGE_MINUTES=60), \
                mock.patch('cusd_plus.crypto_prices.market_rows', return_value=self.rows(timedelta(minutes=45))):
            self.assertEqual(watches.asset_price('crypto:BTCB'), Decimal('90000'))
