"""A slot that is retried says so once, and says once how it ended: done, or
given up. A monthly rule with no balance is retried up to 3 days (founder,
2026-11-22); every other code and frequency 24 hours; never past the next
calendar slot."""
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from smart_account import automation, notifications, quotes, reconcile
from smart_account.models import (
    SmartAccount, SmartAccountEvent, SmartAccountRule, SmartAccountRuleRun, SmartAccountStandingAuthorization,
)

from .base import VAULT, WAD
from .infinia_base import InfiniaPayoutCase
from .test_tasks import RelayHarness

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)
NO_BALANCE = 'No había saldo suficiente en tu Cuenta inteligente.'


class RetryCase(RelayHarness):
    def setUp(self):
        super().setUp()
        self.offset = timedelta(0)
        self.start = timezone.now().replace(microsecond=0)
        clock = mock.patch('django.utils.timezone.now', side_effect=lambda: self.start + self.offset)
        clock.start()
        self.addCleanup(clock.stop)
        SmartAccount.objects.update(paid_until=self.start + 90 * DAY)
        self.account.refresh_from_db()
        self.chain.views[(self.address, 'status')] = 1
        self.chain.views[(self.address, 'billingStatus')] = 0
        self.notices = []
        for patcher in (
                mock.patch('smart_account.notifications._send',
                           side_effect=lambda user, title, message, **kw: self.notices.append((title, message))),
                mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=True)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.payee = self.make_user('payee')

    def make_rule(self, kind='send', frequency='monthly', balance=0):
        from smart_account import payouts
        self.slot = self.start - timedelta(minutes=3)
        fields, chain_fields = {}, {}
        if kind == 'send':
            fields = dict(payee_address=self.payee.wallet, payee_user=self.payee,
                          standing_authorization=SmartAccountStandingAuthorization.objects.create(
                              kind='send', user=self.owner, payee_address=self.payee.wallet.lower(), rail='',
                              amount_usd=Decimal('25.00'), frequency=frequency, face_action_key='out:' + 'f' * 64,
                              binding_hash=payouts.send_binding_hash(self.address, self.payee.wallet,
                                                                     Decimal('25.00'), frequency)))
            chain_fields = {'payee': self.payee.wallet.lower()}
        elif kind == 'buy':
            fields = dict(token_out='0x' + '73' * 20)
            trading = override_settings(CUSD_PLUS_STOCK_TRADING_ENABLED=True)
            trading.enable()
            self.addCleanup(trading.disable)
            quote = mock.patch('smart_account.quotes.stock_buy_call',
                               return_value={'call': {'data': '0x1234'}, 'min_out': 1})
            self.quote = quote.start()
            self.addCleanup(quote.stop)
            for patcher in (
                    mock.patch('cusd_plus.crypto_catalog.by_address', return_value=None),
                    mock.patch('smart_account.assets.stock_by_address', return_value=('AAPLon', {})),
                    mock.patch('cusd_plus.eligibility.check_stock_buy_eligibility', return_value=True),
                    mock.patch('cusd_plus.complex_products.factor_for_symbol', return_value=None),
                    mock.patch('smart_account.quotes.stock_buy_notional', return_value=Decimal('24.50'))):
                patcher.start()
                self.addCleanup(patcher.stop)
        self.rule = SmartAccountRule.objects.create(
            smart_account=self.account, onchain_id=4, state='onchain', kind=kind, token_in=VAULT,
            amount=Decimal('25.00'), frequency=frequency, next_run_at=self.slot, scheduled_for=self.slot,
            active=True, **fields)
        self.chain.rules[(self.address, 4)] = dict(
            chain_fields, kind=kind, frequency=frequency, active=True, amount_usd_wei=25 * WAD,
            next_run_at=int(self.slot.timestamp()))
        self.balance(balance)

    def balance(self, dollars):
        self.fund(VAULT, self.address, dollars * WAD)

    def tick(self, offset=None):
        if offset is not None:
            self.offset = offset
        return automation.run_rules()

    def executed(self, tx_hash=None):
        """The call mined: RuleExecuted applied as the mirror does."""
        event = SmartAccountEvent.objects.create(
            smart_account=self.account, address=self.address.lower(), name='RuleExecuted', log_index=0,
            tx_hash=tx_hash or SmartAccountRuleRun.objects.get(status='sent').tx_hash, block_number=10,
            block_time=timezone.now(), args={'id': 4, 'amountIn': str(25 * WAD), 'amountOut': str(25 * WAD)})
        reconcile.apply_pending()
        return event

    def run_row(self):
        return SmartAccountRuleRun.objects.get(scheduled_for=self.slot)

    def date(self, when):
        return notifications._date(when)


class NoticePerTransitionTests(RetryCase):
    def skip_skip_funded_success(self, kind):
        self.make_rule(kind)
        self.tick()
        self.tick(5 * HOUR)
        self.balance(500)
        self.assertEqual(self.tick(8 * HOUR)['sent'], 1)
        self.executed()
        self.assertEqual(len(self.notices), 2, self.notices)
        (pending, why), (done, how) = self.notices
        self.assertIn('está pendiente', pending)
        self.assertEqual(why, f'{NO_BALANCE} Agrega saldo: lo reintentamos hasta el '
                              f'{self.date(self.slot + 3 * DAY)}.')
        self.assertIn('se realizó', done)
        self.assertNotIn('no se', done)
        self.rule.refresh_from_db()
        self.assertIn(self.date(self.rule.scheduled_for), how)      # the real next date
        self.assertEqual(self.run_row().status, 'ok')

    def test_a_send_skip_skip_funded_success_is_two_notices(self):
        self.skip_skip_funded_success('send')

    def test_a_buy_skip_skip_funded_success_is_two_notices(self):
        self.skip_skip_funded_success('buy')

    def test_skip_to_expiry_is_two_notices(self):
        self.make_rule()
        self.tick()
        for day in (1, 2):
            self.tick(day * DAY)
        self.tick(3 * DAY)
        self.tick(3 * DAY + HOUR)
        self.assertEqual(len(self.notices), 2, self.notices)
        self.rule.refresh_from_db()
        title, body = self.notices[1]
        self.assertIn('no se realizó', title)
        self.assertNotIn('hoy', title)
        self.assertEqual(body, f'{NO_BALANCE} No hicimos este envío; el próximo intento es el '
                               f'{self.date(self.rule.scheduled_for)}.')
        self.assertEqual(self.run_row().message, body)
        self.assertGreater(self.rule.scheduled_for, self.start + 20 * DAY)

    def test_a_late_weekly_run_says_the_date_it_moved_to(self):
        self.make_rule('buy', 'weekly')
        self.tick()
        self.balance(500)
        self.assertEqual(self.tick(20 * HOUR)['sent'], 1)
        self.executed()
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.scheduled_for, self.start + 20 * HOUR + 7 * DAY)
        self.assertEqual(len(self.notices), 2, self.notices)
        self.assertTrue(self.notices[1][1].endswith(f'Próxima fecha: {self.date(self.rule.scheduled_for)}.'))

    def test_failed_then_success_is_two_notices(self):
        self.make_rule(balance=500)
        self.simulate_error = 'execution reverted'
        self.tick()
        self.tick(HOUR)
        self.simulate_error = None
        self.assertEqual(self.tick(2 * HOUR)['sent'], 1)
        self.executed()
        self.assertEqual(len(self.notices), 2, self.notices)
        self.assertIn('está pendiente', self.notices[0][0])
        self.assertIn(f'lo reintentamos hasta el {self.date(self.slot + DAY)}.', self.notices[0][1])
        self.assertIn('se realizó', self.notices[1][0])

    def test_failed_to_expiry_is_told_for_a_send_too(self):
        self.make_rule(balance=500)
        self.simulate_error = 'execution reverted'
        self.tick()
        self.tick(DAY)
        self.assertEqual(len(self.notices), 2, self.notices)
        self.assertIn('No hicimos este envío; el próximo intento es el', self.notices[1][1])

    def test_a_plain_success_is_one_notice_and_the_event_again_is_silent(self):
        self.make_rule(balance=500)
        self.tick()
        event = self.executed()
        self.assertEqual(len(self.notices), 1, self.notices)
        SmartAccountEvent.objects.filter(pk=event.pk).update(applied_at=None)
        reconcile.apply_pending()
        self.assertEqual(len(self.notices), 1, self.notices)

    def test_given_up_and_then_mined_after_all_is_announced(self):
        self.make_rule()
        self.tick()
        self.tick(3 * DAY + HOUR)
        tx_hash = '0x' + 'ab' * 32
        SmartAccountRuleRun.objects.update(tx_hash=tx_hash)
        self.executed(tx_hash)
        self.assertEqual(len(self.notices), 3, self.notices)
        self.assertIn('se realizó', self.notices[2][0])

    def test_a_truly_final_skip_says_not_done_and_is_not_retried(self):
        self.make_rule('buy', balance=500)
        with mock.patch('smart_account.assets.stock_by_address', return_value=None):
            self.tick()
            self.tick(HOUR)
        self.assertEqual(len(self.notices), 1, self.notices)
        self.assertIn('no se realizó', self.notices[0][0])
        self.assertNotIn('reintentamos', self.notices[0][1])

    def test_a_final_refusal_after_a_retry_is_told(self):
        self.make_rule('buy')
        self.tick()
        self.balance(500)
        with mock.patch('smart_account.assets.stock_by_address', return_value=None):
            self.tick(HOUR)
        self.assertEqual(len(self.notices), 2, self.notices)
        self.assertIn('el próximo intento es el', self.notices[1][1])

    def test_a_reverted_call_says_until_when(self):
        from smart_account.models import SmartAccountRelayTx
        self.make_rule(balance=500)
        self.tick()
        SmartAccountRelayTx.objects.update(status='reverted')
        automation.on_relay_tx_final(SmartAccountRelayTx.objects.get())
        self.assertIn(f'lo reintentamos hasta el {self.date(self.slot + DAY)}.', self.run_row().message)

    def test_the_date_is_the_owners_own(self):
        late = datetime(2027, 3, 4, 2, 0, tzinfo=dt_timezone.utc)
        self.owner.country = 'VE'
        self.assertEqual(notifications._date(late, self.owner), '03/03/2027')
        self.assertEqual(notifications._date(late), '04/03/2027')


class RetryWindowTests(RetryCase):
    def test_monthly_funded_on_day_two_runs(self):
        self.make_rule('buy')
        self.tick()
        self.tick(DAY + HOUR)
        self.assertEqual(self.run_row().status, 'skipped')
        self.balance(500)
        self.assertEqual(self.tick(2 * DAY)['sent'], 1)

    def funded_on_day_two_is_too_late(self, frequency):
        self.make_rule('buy', frequency)
        self.tick()
        self.assertIn(f'hasta el {self.date(self.slot + DAY)}.', self.notices[0][1])
        self.balance(500)
        self.assertEqual(self.tick(2 * DAY)['sent'], 0)
        self.tick(2 * DAY + HOUR)
        self.assertEqual((self.signed, len(self.notices)), ([], 2))     # pending, then one given up
        self.rule.refresh_from_db()
        self.assertEqual(self.notices[1][1], f'{NO_BALANCE} No hicimos esta compra; el próximo intento es el '
                                             f'{self.date(self.rule.scheduled_for)}.')

    def test_the_next_date_shown_while_retrying_is_not_in_the_past(self):
        from smart_account import assistant_ops, schema
        self.make_rule()
        self.tick()
        self.offset = 2 * DAY
        self.rule.refresh_from_db()
        now = timezone.now()
        self.assertEqual(schema._rule_type(self.rule).next_run_at, now)
        (row,) = assistant_ops.rules_snapshot(self.owner, tz=dt_timezone.utc)['reglas']
        self.assertEqual(row['proxima_ejecucion'], assistant_ops._local(now, dt_timezone.utc))

    def test_weekly_funded_on_day_two_does_not_run(self):
        self.funded_on_day_two_is_too_late('weekly')

    def test_biweekly_funded_on_day_two_does_not_run(self):
        self.funded_on_day_two_is_too_late('biweekly')

    def test_monthly_on_day_four_gives_up_and_tells_once(self):
        self.make_rule()
        self.tick()
        self.balance(500)           # no pass between the deadline and the funding
        self.assertEqual(self.tick(4 * DAY)['sent'], 0)
        self.tick(4 * DAY + HOUR)
        self.assertEqual((self.signed, len(self.notices)), ([], 2))
        self.assertIn('No hicimos este envío', self.notices[1][1])

    def test_daily_is_capped_at_the_next_slot(self):
        self.make_rule(frequency='daily')
        self.tick()
        self.assertIn(f'hasta el {self.date(self.slot + DAY)}.', self.notices[0][1])
        self.balance(500)
        self.tick(DAY)
        self.assertEqual(self.signed, [])               # the old slot never runs into the next one
        self.assertEqual(len(self.notices), 2, self.notices)
        self.assertIn('No hicimos este envío', self.notices[1][1])
        self.assertEqual(self.run_row().status, 'skipped')
        self.assertEqual(self.tick()['sent'], 1)        # which runs on its own

    def test_another_code_still_ends_at_24_hours(self):
        self.make_rule(balance=500)
        self.holds[self.owner.pk] = 'held'
        self.tick()
        self.assertIn(f'hasta el {self.date(self.slot + DAY)}.', self.notices[0][1])
        self.tick(DAY)
        self.rule.refresh_from_db()
        self.assertGreater(self.rule.scheduled_for, self.start + 20 * DAY)
        self.assertEqual(len(self.notices), 2, self.notices)

    def test_the_gates_are_asked_again_on_the_late_attempt(self):
        self.make_rule()
        self.tick()
        self.balance(500)
        self.holds[self.owner.pk] = 'held'
        self.assertEqual(self.tick(2 * DAY)['sent'], 0)
        self.assertEqual((self.signed, self.run_row().error, len(self.notices)), ([], 'identity_hold', 2))

    def test_funded_in_time_waits_for_the_market_to_open(self):
        self.make_rule('buy', 'weekly')
        self.tick()
        self.balance(500)
        self.quote.side_effect = quotes.QuoteUnavailable('market_closed', retry_later=True)
        self.assertEqual(self.tick(5 * HOUR)['waiting'], 1)
        self.assertIn('cuando abra', self.run_row().message)    # no date that passes meanwhile
        self.assertEqual(self.tick(2 * DAY)['waiting'], 1)      # spec 7.5: the next open session
        self.quote.side_effect = None
        self.assertEqual(self.tick(2 * DAY + HOUR)['sent'], 1)
        self.executed()
        self.assertEqual(len(self.notices), 2, self.notices)

    def test_a_wait_after_no_balance_keeps_the_promised_days(self):
        self.make_rule('buy')
        self.tick()
        self.balance(500)
        self.quote.side_effect = quotes.QuoteUnavailable('share_price_unavailable', retry_later=True)
        self.assertEqual(self.tick(2 * DAY)['waiting'], 1)
        self.assertNotIn('Agrega saldo', self.run_row().message)
        self.assertEqual(self.tick(3 * DAY + HOUR)['waiting'], 0)
        self.assertEqual(len(self.notices), 2, self.notices)

    def test_one_function_of_code_frequency_and_slot(self):
        slot = self.start
        for code, frequency, days in (('insufficient_balance', 'monthly', 3), ('insufficient_balance', 'biweekly', 1),
                                      ('insufficient_balance', 'weekly', 1), ('insufficient_balance', 'daily', 1),
                                      ('identity_hold', 'monthly', 1), ('quote_failed', 'daily', 1)):
            self.assertEqual(automation.retry_deadline(code, frequency, slot), slot + days * DAY, (code, frequency))


class MonthlyDayTests(RetryCase):
    def next_after(self, first, slot, executed, signed=True):
        self.make_rule()
        if signed:
            SmartAccountEvent.objects.create(
                smart_account=self.account, address=self.address.lower(), name='RuleCreated', log_index=0,
                tx_hash='0x' + 'cd' * 32, block_number=1, block_time=first - HOUR, applied_at=first, args={'id': 4})
        for when in {first, slot}:
            SmartAccountRuleRun.objects.create(rule=self.rule, scheduled_for=when)
        self.rule.scheduled_for, self.rule.next_run_at = slot, executed + 28 * DAY
        self.offset = executed - self.start
        automation.schedule_next(self.rule)
        return self.rule.scheduled_for

    @staticmethod
    def at(month, day):
        return datetime(2027, month, day, 15, 0, tzinfo=dt_timezone.utc)

    def test_the_gap_moves_february_and_the_day_returns(self):
        # Due on the 5th, paid on 8 Feb: 8 Mar at the earliest, then the 5th again.
        self.assertEqual(self.next_after(self.at(1, 5), self.at(3, 8), self.at(3, 8)), self.at(4, 5))

    def test_the_contracts_gap_still_wins(self):
        self.assertEqual(self.next_after(self.at(1, 5), self.at(2, 5), self.at(2, 8)), self.at(3, 8))

    def test_a_slot_pushed_into_the_next_month_does_not_lose_that_month(self):
        self.assertEqual(self.next_after(self.at(1, 30), self.at(3, 2), self.at(3, 2)), self.at(3, 30))

    def test_the_last_day_is_not_lost_to_february(self):
        self.assertEqual(self.next_after(self.at(1, 31), self.at(2, 28), self.at(2, 28)), self.at(3, 31))

    def test_a_rule_without_its_event_keeps_the_slot_it_has(self):
        self.assertEqual(self.next_after(self.at(1, 5), self.at(3, 8), self.at(3, 8), signed=False), self.at(4, 8))


class PayoutNoticeTests(InfiniaPayoutCase):
    def test_skipped_then_paid_is_the_pending_notice_and_the_delivery_notice(self):
        rule = self.make_rule()
        self.world.balances[(rule.token_in.lower(), self.contract)] = 0
        with mock.patch('smart_account.notifications.rule_run') as told, \
                mock.patch('smart_account.notifications.payout_delivered') as delivered:
            self.run_rules()
            self.advance(2 * 86400)
            self.world.balances[(rule.token_in.lower(), self.contract)] = 100_000 * WAD
            self.send_run()
            told.assert_called_once()
            self.assertEqual(self.to_paid().status, 'paid')
        told.assert_called_once()
        delivered.assert_called_once()

    def test_a_payout_given_up_for_balance_is_told_again(self):
        rule = self.make_rule()
        self.world.balances[(rule.token_in.lower(), self.contract)] = 0
        with mock.patch('smart_account.notifications.rule_run') as told:
            self.run_rules()
            self.advance(3 * 86400)
            self.run_rules()
        self.assertEqual(told.call_count, 2)
        self.assertIn('No hicimos este pago; el próximo intento es el', told.call_args.args[0].message)
