"""Month summary ("Tu mes") classification and window rules.

Rows are SimpleNamespace stand-ins for UnifiedTransactionTable rows; the
direction comes from the same row_direction() the history list uses.
"""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from users.cashflow import (
    Movement, Totals, ViewerContext, classify, comparison_window, month_window,
    resolve_timezone,
)

LA_PAZ = ZoneInfo('America/La_Paz')


def row(transaction_type='send', direction='received', amount='10.00', token='USDT', **kw):
    base = dict(
        transaction_type=transaction_type, status='CONFIRMED', token_type=token, amount=amount,
        amount_denomination='TOKEN_UNITS', fee_amount='', transaction_hash='',
        sender_type='user', sender_user_id=None, sender_business_id=None,
        counterparty_user_id=None, counterparty_business_id=None,
        sender_address='', counterparty_address='', from_address='', to_address='',
        sender_display_name='', counterparty_display_name='', transaction_date=None,
        sponsored_batch=None, ramp_transaction=None, conversion=None, local_money_flow=None,
        _user_address='0xviewer', _account_type='personal', _account_business_id=None,
        get_direction_for_address=lambda _a: direction,
    )
    base.update(kw)
    r = SimpleNamespace(**base)
    r.amount_for_direction = lambda d: r.amount
    return r


def ctx(**kw):
    defaults = dict(user=SimpleNamespace(id=1, is_authenticated=True), account=None,
                    account_type='personal', business_id=None, owner_id=1)
    defaults.update(kw)
    return ViewerContext(**defaults)


class ClassifyTests(SimpleTestCase):
    def test_on_ramp_is_top_up_and_off_ramp_is_withdrawal(self):
        on = row('ramp', ramp_transaction=SimpleNamespace(direction='on_ramp', metadata={}))
        off = row('ramp', ramp_transaction=SimpleNamespace(direction='off_ramp', metadata={}))
        self.assertEqual(classify(on, ctx()).kind, 'top_up')
        self.assertEqual(classify(off, ctx()).kind, 'withdrawal')

    def test_on_ramp_usdt_landing_is_not_counted_again_as_income(self):
        landing = row('send', direction='received', sender_type='external',
                      transaction_hash='0xABC', from_address='0xkoywe')
        c = ctx(ramp_arrival_hashes={'0xabc'})
        self.assertIsNone(classify(landing, c))
        # an unrelated external deposit is income (R6/D9)
        other = row('send', direction='received', sender_type='external', transaction_hash='0xdef')
        self.assertEqual(classify(other, c).kind, 'income_person')

    def test_sends_split_people_merchants_and_own_business(self):
        to_person = row('send', direction='sent', counterparty_user_id=7)
        to_merchant = row('send', direction='sent', counterparty_business_id=3)
        to_own_business = row('send', direction='sent', counterparty_business_id=9)
        c = ctx(owned_business_ids={9})
        self.assertEqual(classify(to_person, c).kind, 'p2p_send')
        self.assertEqual(classify(to_merchant, c).kind, 'merchant')
        self.assertEqual(classify(to_own_business, c).kind, 'own_transfer')

    def test_business_account_to_its_owner_is_own_transfer(self):
        r = row('send', direction='sent', counterparty_user_id=1)
        self.assertEqual(classify(r, ctx(account_type='business', business_id=9)).kind, 'own_transfer')

    def test_employee_and_owner_classify_business_rows_identically(self):
        # business 9 owned by user 1; caller is employee user 5
        to_owner = row('send', direction='sent', counterparty_user_id=1)
        to_employee = row('send', direction='sent', counterparty_user_id=5)
        employee = ctx(user=SimpleNamespace(id=5, is_authenticated=True), account_type='business',
                       business_id=9, owner_id=1)
        owner = ctx(account_type='business', business_id=9, owner_id=1)
        for c in (owner, employee):
            self.assertEqual(classify(to_owner, c).kind, 'own_transfer')
            self.assertEqual(classify(to_employee, c).kind, 'p2p_send')

    def test_savings_and_stock_moves_are_net_lines_not_spending(self):
        to_sav = row('conversion', conversion=SimpleNamespace(conversion_type='to_savings', status='COMPLETED'),
                     token='CUSD_PLUS')
        swap = row('conversion', conversion=SimpleNamespace(conversion_type='usdt_to_cusd'))
        buy = row('send', direction='sent', sponsored_batch=SimpleNamespace(kind='stock_buy'))
        self.assertEqual(classify(to_sav, ctx()).kind, 'savings_in')
        self.assertEqual(classify(swap, ctx()).kind, 'conversion')
        self.assertEqual(classify(buy, ctx()).kind, 'investment_in')

    def test_savings_delivered_as_raw_usdt_is_not_savings(self):
        r = row('conversion', conversion=SimpleNamespace(conversion_type='to_savings', status='DELIVERED_USDT'))
        self.assertEqual(classify(r, ctx()).kind, 'conversion')

    def test_document_types_share_one_vocabulary(self):
        from users.cashflow import _doc_family
        self.assertEqual({_doc_family(t) for t in ('national_id', 'DNI', 'C.I.', 'Cédula', 'cc')}, {'national_id'})
        self.assertEqual(_doc_family('Pasaporte'), 'passport')
        self.assertNotEqual(_doc_family('passport'), _doc_family('DNI'))

    def test_unconfirmed_non_usd_and_share_rows_never_count(self):
        self.assertIsNone(classify(row(status='FAILED'), ctx()))
        self.assertIsNone(classify(row(token='CONFIO'), ctx()))
        self.assertIsNone(classify(row(token='CUSD_PLUS', amount_denomination='SHARES'), ctx()))
        self.assertIsNone(classify(row(amount='0'), ctx()))

    def test_recipient_counts_net_of_fee(self):
        r = row('payment', direction='received', amount='100', fee_amount='0.90',
                counterparty_business_id=5, _account_type='business', _account_business_id=5)
        m = classify(r, ctx(account_type='business', business_id=5))
        self.assertEqual((m.kind, m.amount), ('sale', Decimal('99.10')))

    def test_counterparty_key_precedence_business_over_user(self):
        r = row('send', direction='sent', counterparty_business_id=3, counterparty_user_id=7,
                counterparty_display_name='Panadería')
        m = classify(r, ctx())
        self.assertEqual((m.counterparty_key, m.counterparty_name), ('business:3', 'Panadería'))

    def test_local_payin_same_owner_is_top_up_third_party_is_income(self):
        def payin(reason):
            credit = SimpleNamespace(payin_admission=SimpleNamespace(reason=reason),
                                     provider_data={'third_party': {'bank_code': '001', 'account_number': '12 34'}})
            return SimpleNamespace(infinia_journey=SimpleNamespace(funding_credit=credit))
        own = row('local_transfer', sender_type='external', local_money_flow=payin('same_owner'))
        third = row('local_transfer', sender_type='external', local_money_flow=payin('third_party_enabled'))
        self.assertEqual(classify(own, ctx()).kind, 'top_up')
        m = classify(third, ctx())
        self.assertEqual((m.kind, m.counterparty_key), ('income_person', 'bank:001:1234'))

    def test_local_payout_is_withdrawal_only_on_exact_kyc_id_match(self):
        flow = SimpleNamespace(infinia_journey=SimpleNamespace(
            destination_snapshot={'destination_internal_id': 'd1', 'display_label': 'Banco Unión ••12'}))
        out = row('local_transfer', sender_type='user', local_money_flow=flow)
        own = ctx(kyc_document=('CI', '1234567'), destination_ids={'d1': ('CI', '1234567')})
        other = ctx(kyc_document=('CI', '7654321'), destination_ids={'d1': ('CI', '1234567')})
        no_id = ctx(kyc_document=('CI', '1234567'), destination_ids={'d1': ('', '')})
        self.assertEqual(classify(out, own).kind, 'withdrawal')
        # not proven own (different person, or no stored ID): spending (R2, kept 2026-10-04)
        m = classify(out, other)
        self.assertEqual((m.kind, m.counterparty_key, m.counterparty_name),
                         ('p2p_send', 'dest:d1', 'Banco Unión ••12'))
        self.assertEqual(classify(out, no_id).kind, 'p2p_send')

    def test_business_payroll_to_its_owner_is_payroll_paid_not_received(self):
        r = row('payroll', direction='received', sender_business_id=9, counterparty_user_id=1,
                _account_type='business', _account_business_id=9)
        self.assertEqual(classify(r, ctx(account_type='business', business_id=9)).kind, 'payroll_out')
        # the owner's personal view of the same payroll is income
        r2 = row('payroll', sender_business_id=9, counterparty_user_id=1)
        self.assertEqual(classify(r2, ctx()).kind, 'payroll_in')

    def test_invalid_fee_or_amount_fails_the_summary_instead_of_guessing(self):
        from users.cashflow import SummaryUnavailable
        for fee in ('abc', '150', '-1', 'NaN'):
            with self.assertRaises(SummaryUnavailable):
                classify(row('send', direction='received', amount='100', fee_amount=fee), ctx())
        with self.assertRaises(SummaryUnavailable):
            classify(row('send', amount='Infinity'), ctx())

    def test_missing_payin_records_mean_no_evidence_but_other_errors_propagate(self):
        from django.core.exceptions import ObjectDoesNotExist

        class Journey:
            @property
            def funding_credit(self):
                raise ObjectDoesNotExist()
        flow = SimpleNamespace(infinia_journey=Journey())
        r = row('local_transfer', sender_type='external', local_money_flow=flow)
        self.assertEqual(classify(r, ctx()).kind, 'income_person')

        class Broken:
            @property
            def funding_credit(self):
                raise RuntimeError('db down')
        r2 = row('local_transfer', sender_type='external',
                 local_money_flow=SimpleNamespace(infinia_journey=Broken()))
        with self.assertRaises(RuntimeError):
            classify(r2, ctx())


class TotalsTests(SimpleTestCase):
    def test_only_income_and_spending_count_as_movements(self):
        t = Totals()
        for kind, amt in [('income_person', '50'), ('merchant', '20'), ('top_up', '500'),
                          ('withdrawal', '100'), ('savings_in', '150'), ('savings_out', '30'),
                          ('investment_in', '80'), ('own_transfer', '999')]:
            t.add(Movement(kind=kind, direction='sent', amount=Decimal(amt)))
        self.assertEqual((t.income, t.spending, t.movement_count), (Decimal('50'), Decimal('20'), 2))
        self.assertEqual((t.top_ups, t.withdrawals), (Decimal('500'), Decimal('100')))
        self.assertEqual((t.savings_net, t.investment_net), (Decimal('120'), Decimal('80')))


class WindowTests(SimpleTestCase):
    def test_month_window_is_local_calendar_month(self):
        start, end = month_window(2026, 10, LA_PAZ)
        self.assertEqual((start.isoformat(), end.isoformat()),
                         ('2026-10-01T00:00:00-04:00', '2026-11-01T00:00:00-04:00'))

    def test_current_month_compares_same_period_clamped_to_shorter_month(self):
        now = datetime(2026, 3, 31, 15, 30, tzinfo=LA_PAZ)
        start, end, partial = comparison_window(2026, 3, now, LA_PAZ)
        self.assertTrue(partial)
        self.assertEqual((start.date().isoformat(), end.isoformat()),
                         ('2026-02-01', '2026-02-28T15:30:00-04:00'))

    def test_past_month_compares_full_previous_month(self):
        now = datetime(2026, 10, 4, 9, 0, tzinfo=LA_PAZ)
        start, end, partial = comparison_window(2026, 9, now, LA_PAZ)
        self.assertFalse(partial)
        self.assertEqual((start.date().isoformat(), end.date().isoformat()), ('2026-08-01', '2026-09-01'))

    def test_timezone_prefers_device_then_phone_country_then_utc(self):
        self.assertEqual(str(resolve_timezone('America/Lima', 'BO')), 'America/Lima')
        self.assertEqual(str(resolve_timezone('Not/AZone', 'BO')), 'America/La_Paz')
        self.assertEqual(str(resolve_timezone(None, None)), 'UTC')


class MonthSummaryResolverTests(__import__('django.test', fromlist=['TestCase']).TestCase):
    """End to end over real ledger rows: scoping, window, viewer-side amounts."""

    def setUp(self):
        from users.models import Account, User
        self.user = User.objects.create_user(
            username='tumes-owner', email='tumes@example.com', password='x', firebase_uid='tumes-owner')
        self.friend = User.objects.create_user(
            username='tumes-friend', email='friend@example.com', password='x', firebase_uid='tumes-friend')
        self.account = Account.objects.create(
            user=self.user, account_type='personal', account_index=0,
            algorand_address='T' * 58, bsc_address='0x' + 'ab' * 20)
        self.mine = self.account.bsc_address
        self.other = '0x' + 'cd' * 20

    def _row(self, *, sent, amount, when, status='CONFIRMED', token='USDT', user=None, fee=''):
        from users.models_unified import UnifiedTransactionTable
        owner = user or self.user
        return UnifiedTransactionTable.objects.create(
            transaction_type='send', amount=amount, fee_amount=fee, token_type=token, status=status,
            sender_user=owner if sent else self.friend, sender_type='user',
            counterparty_user=self.friend if sent else owner, counterparty_type='user',
            from_address=self.mine if sent else self.other, to_address=self.other if sent else self.mine,
            sender_display_name='Yo' if sent else 'María', counterparty_display_name='María' if sent else 'Yo',
            transaction_date=when)

    def _resolve(self, jwt=None, tz='UTC', year=None, month=None):
        from types import SimpleNamespace
        from django.utils import timezone
        from users.cashflow_schema import MonthSummaryQuery
        now = timezone.now()
        jwt = jwt or {'account_type': 'personal', 'account_index': 0, 'business_id': None}
        with mock.patch('users.jwt_context.get_jwt_business_context_with_validation', return_value=jwt):
            return MonthSummaryQuery().resolve_month_summary(
                SimpleNamespace(context=SimpleNamespace(user=self.user)),
                year=year or now.year, month=month or now.month, timezone=tz)

    def test_counts_this_month_only_with_viewer_side_amounts(self):
        from datetime import timedelta
        from django.utils import timezone
        now = timezone.now()
        self._row(sent=False, amount='50.00', fee='0.50', when=now)        # received: net 49.50
        self._row(sent=True, amount='20.00', when=now)                     # sent: gross 20
        self._row(sent=True, amount='999.00', when=now, status='FAILED')   # never counts
        self._row(sent=True, amount='5.00', when=now, token='CONFIO')      # not dollars
        from users.cashflow import month_window, previous_month
        py, pm = previous_month(now.year, now.month)
        prev_start, _ = month_window(py, pm, ZoneInfo('UTC'))
        self._row(sent=True, amount='30.00', when=prev_start + timedelta(minutes=1))  # previous month
        stranger = __import__('users.models', fromlist=['User']).User.objects.create_user(
            username='tumes-stranger', email='s@example.com', password='x', firebase_uid='tumes-stranger')
        self._row(sent=True, amount='77.00', when=now, user=stranger)      # someone else's row

        result = self._resolve()
        self.assertEqual((result.current.income_usd, result.current.spending_usd), ('49.50', '20.00'))
        self.assertEqual(result.current.movement_count, 2)
        self.assertEqual(result.timezone, 'UTC')
        self.assertEqual([(c.name, c.received_usd, c.sent_usd) for c in result.counterparties],
                         [('María', '49.50', '20.00')])
        # the 1st of the previous month is inside both comparison windows
        self.assertEqual(result.previous.spending_usd, '30.00')
        self.assertTrue(result.previous_is_partial)

    def test_business_account_month_is_hidden_from_non_owners(self):
        jwt = {'account_type': 'business', 'account_index': 0, 'business_id': 424242}
        self.assertIsNone(self._resolve(jwt=jwt))

    def test_rejects_future_and_invalid_months(self):
        from django.utils import timezone
        now = timezone.now()
        self.assertIsNone(self._resolve(year=now.year + 1, month=1))
        self.assertIsNone(self._resolve(month=13))


class RampLandingAcrossWindowsTests(__import__('django.test', fromlist=['TestCase']).TestCase):
    def test_landing_hashes_come_from_all_on_ramps_not_the_window(self):
        from datetime import timedelta
        from django.utils import timezone
        from users.cashflow import _ramp_arrival_hashes
        from users.models import Account, User
        from users.models_unified import UnifiedTransactionTable
        from ramps.models import RampTransaction
        user = User.objects.create_user(username='ramp-old', email='ro@example.com', password='x', firebase_uid='ramp-old')
        Account.objects.create(user=user, account_type='personal', account_index=0,
                               algorand_address='R' * 58, bsc_address='0x' + 'ef' * 20)
        rt = RampTransaction.objects.create(provider='koywe', direction='on_ramp', status='COMPLETED',
                                            actor_user=user, metadata={'bsc_arrival_tx_hash': '0xABCDEF'})
        UnifiedTransactionTable.objects.create(
            transaction_type='ramp', ramp_transaction=rt, amount='10', token_type='CUSD_PLUS', status='CONFIRMED',
            counterparty_user=user, counterparty_type='user', sender_type='external',
            transaction_date=timezone.now() - timedelta(days=60))
        scope = UnifiedTransactionTable.objects.filter(counterparty_user=user)
        self.assertEqual(_ramp_arrival_hashes(scope), {'0xabcdef'})


class CategoryLabelTests(__import__('django.test', fromlist=['TestCase']).TestCase):
    """Chips + labels end to end (T3): scoping, permissions, rule vs override,
    retroactive rules (R20), skip/dismiss limits (D11), summary categories."""

    def setUp(self):
        from django.utils import timezone
        from users.models import Account, User
        from users.models_unified import UnifiedTransactionTable
        self.user = User.objects.create_user(username='cat-owner', email='co@example.com', password='x', firebase_uid='cat-owner')
        self.friend = User.objects.create_user(username='cat-friend', email='cf@example.com', password='x', firebase_uid='cat-friend')
        self.account = Account.objects.create(user=self.user, account_type='personal', account_index=0,
                                              algorand_address='C' * 58, bsc_address='0x' + '11' * 20)
        self.other = '0x' + '22' * 20

        def pay(amount, when=None):
            return UnifiedTransactionTable.objects.create(
                transaction_type='send', amount=amount, token_type='USDT', status='CONFIRMED',
                sender_user=self.user, sender_type='user', counterparty_user=self.friend, counterparty_type='user',
                from_address=self.account.bsc_address, to_address=self.other,
                counterparty_display_name='Doña Rosa', transaction_date=when or timezone.now())
        self.pay = pay
        self.jwt = {'account_type': 'personal', 'account_index': 0, 'business_id': None}

    def _info(self):
        from types import SimpleNamespace
        return SimpleNamespace(context=SimpleNamespace(user=self.user))

    def _call(self, fn, **kw):
        with mock.patch('users.jwt_context.get_jwt_business_context_with_validation', return_value=self.jwt):
            return fn(**kw)

    def _prompt(self, row):
        from users.cashflow_schema import CategoryPromptQuery
        return self._call(CategoryPromptQuery().resolve_category_prompt, info=self._info(), movement_id=row.pk)

    def _categorize(self, row, category, apply_to):
        from users.cashflow_schema import CategorizeMovement
        return self._call(CategorizeMovement.mutate, root=None, info=self._info(), category=category,
                          apply_to=apply_to, movement_id=row.pk)

    def _record(self, row, outcome):
        from users.cashflow_schema import RecordCategoryPrompt
        return self._call(RecordCategoryPrompt.mutate, root=None, info=self._info(), outcome=outcome, movement_id=row.pk)

    def _summary(self):
        from django.utils import timezone
        from users.cashflow_schema import MonthSummaryQuery
        now = timezone.now()
        return self._call(MonthSummaryQuery().resolve_month_summary, info=self._info(),
                          year=now.year, month=now.month, timezone='UTC')

    def test_counterparty_rule_labels_past_and_future_payments(self):
        first, second = self.pay('10.00'), self.pay('5.00')
        self.assertTrue(self._prompt(first).should_ask)
        self.assertTrue(self._categorize(first, 'food', 'counterparty').success)
        later = self.pay('7.00')
        # every payment to her is now food, including the older and the later one
        for row in (first, second, later):
            p = self._prompt(row)
            self.assertEqual((p.should_ask, p.category), (False, 'food'))
        cats = {c.category: c.amount_usd for c in self._summary().current.spending_by_category}
        self.assertEqual(cats, {'food': '22.00'})

    def test_single_payment_override_wins_over_the_rule(self):
        a, b = self.pay('10.00'), self.pay('4.00')
        self._categorize(a, 'food', 'counterparty')
        self._categorize(b, 'family', 'movement')
        cats = [(c.category, c.amount_usd) for c in self._summary().current.spending_by_category]
        self.assertEqual(cats, [('food', '10.00'), ('family', '4.00')])

    def test_uncategorized_is_listed_last(self):
        from users.models import User
        self.pay('3.00')
        stranger = User.objects.create_user(username='cat-x', email='x@example.com', password='x', firebase_uid='cat-x')
        from users.models_unified import UnifiedTransactionTable
        from django.utils import timezone
        big = UnifiedTransactionTable.objects.create(
            transaction_type='send', amount='50.00', token_type='USDT', status='CONFIRMED',
            sender_user=self.user, sender_type='user', counterparty_user=stranger, counterparty_type='user',
            from_address=self.account.bsc_address, to_address='0x' + '33' * 20, transaction_date=timezone.now())
        self._categorize(big, 'home', 'counterparty')
        cats = [c.category for c in self._summary().current.spending_by_category]
        self.assertEqual(cats, ['home', 'uncategorized'])

    def test_two_skips_or_three_dismisses_stop_the_prompt(self):
        r = self.pay('1.00')
        self._record(r, 'skipped')
        self.assertTrue(self._prompt(r).should_ask)
        self._record(r, 'skipped')
        self.assertFalse(self._prompt(r).should_ask)
        r2 = self.pay('1.00')
        from users.models_cashflow import CounterpartyPromptState
        CounterpartyPromptState.objects.all().delete()
        for _ in range(2):
            self._record(r2, 'dismissed')
        self.assertTrue(self._prompt(r2).should_ask)
        self._record(r2, 'dismissed')
        self.assertFalse(self._prompt(r2).should_ask)

    def test_cannot_label_someone_elses_movement_or_income(self):
        from django.utils import timezone
        from users.models_unified import UnifiedTransactionTable
        theirs = UnifiedTransactionTable.objects.create(
            transaction_type='send', amount='9.00', token_type='USDT', status='CONFIRMED',
            sender_user=self.friend, sender_type='user', counterparty_user=None, counterparty_type='external',
            from_address=self.other, to_address='0x' + '44' * 20, transaction_date=timezone.now())
        self.assertEqual(self._categorize(theirs, 'food', 'counterparty').error, 'not_found')
        income = UnifiedTransactionTable.objects.create(
            transaction_type='send', amount='9.00', token_type='USDT', status='CONFIRMED',
            sender_user=self.friend, sender_type='user', counterparty_user=self.user, counterparty_type='user',
            from_address=self.other, to_address=self.account.bsc_address, transaction_date=timezone.now())
        self.assertEqual(self._categorize(income, 'food', 'counterparty').error, 'not_found')
        self.assertFalse(self._prompt(income).should_ask)

    def test_pending_payment_can_be_labeled_but_failed_cannot(self):
        pending = self.pay('2.00')
        pending.status = 'SUBMITTED'
        pending.save(update_fields=['status'])
        self.assertTrue(self._prompt(pending).should_ask)
        failed = self.pay('2.00')
        failed.status = 'FAILED'
        failed.save(update_fields=['status'])
        self.assertFalse(self._prompt(failed).should_ask)

    def test_invalid_input_and_denied_permission(self):
        r = self.pay('1.00')
        self.assertEqual(self._categorize(r, 'groceries', 'counterparty').error, 'invalid_input')
        self.assertEqual(self._categorize(r, 'food', 'everything').error, 'invalid_input')
        self.jwt = None  # get_jwt_business_context_with_validation denied (e.g. cashier lacks view_analytics)
        self.assertEqual(self._categorize(r, 'food', 'counterparty').error, 'not_allowed')
        self.assertFalse(self._prompt(r).should_ask)

    def test_labels_are_per_account_not_per_user(self):
        from users.models import Account
        from users.models_cashflow import CounterpartyRule
        r = self.pay('1.00')
        self._categorize(r, 'food', 'counterparty')
        self.assertEqual(list(CounterpartyRule.objects.values_list('account_id', 'counterparty_key', 'category')),
                         [(self.account.id, f'user:{self.friend.id}', 'food')])
        self.assertEqual(Account.objects.filter(user=self.user).count(), 1)


class MonthMovementsTests(CategoryLabelTests):
    """monthMovements lists add up to the summary number they were opened from."""

    def _movements(self, filter_by, value=None):
        from django.utils import timezone
        from users.cashflow_schema import MonthSummaryQuery
        now = timezone.now()
        return self._call(MonthSummaryQuery().resolve_month_movements, info=self._info(), year=now.year,
                          month=now.month, timezone='UTC', filter_by=filter_by, value=value)

    def test_lists_match_their_totals(self):
        from decimal import Decimal
        a, b = self.pay('10.00'), self.pay('4.00')
        self._categorize(a, 'food', 'movement')
        spending = self._movements('spending')
        self.assertEqual(sum(Decimal(m.amount_usd) for m in spending), Decimal('14.00'))
        self.assertEqual([m.amount_usd for m in self._movements('category', 'food')], ['10.00'])
        uncategorized = self._movements('uncategorized')
        self.assertEqual([(m.amount_usd, m.counterparty_name) for m in uncategorized], [('4.00', 'Doña Rosa')])
        self.assertEqual(len(self._movements('counterparty', f'user:{self.friend.id}')), 2)
        self.assertEqual(self._movements('nonsense'), [])
        # each item carries the id the chips/edit flow use
        self.assertEqual({int(m.id) for m in spending}, {a.pk, b.pk})

    def test_employees_get_no_movements(self):
        self.jwt = {'account_type': 'business', 'account_index': 0, 'business_id': 777}
        self.pay('1.00')
        self.assertEqual(self._movements('spending'), [])

    def _receive(self, amount):
        from django.utils import timezone
        from users.models_unified import UnifiedTransactionTable
        return UnifiedTransactionTable.objects.create(
            transaction_type='send', amount=amount, token_type='USDT', status='CONFIRMED',
            sender_user=self.friend, sender_type='user', counterparty_user=self.user, counterparty_type='user',
            from_address=self.other, to_address=self.account.bsc_address,
            sender_display_name='Doña Rosa', transaction_date=timezone.now())

    def test_sub_cent_amounts_still_add_up_to_the_summary(self):
        from decimal import Decimal
        for _ in range(6):
            self.pay('0.991')
        listed = sum(Decimal(m.amount_usd) for m in self._movements('spending'))
        self.assertEqual(Decimal(self._summary().current.spending_usd), listed)

    def test_see_all_people_includes_incoming_and_outgoing(self):
        self.pay('3.00')
        self._receive('5.00')
        self.assertEqual(sorted(m.direction for m in self._movements('counterparties')), ['received', 'sent'])
        self.assertEqual(self._movements('spending')[0].direction, 'sent')

    def test_own_money_rows_open_only_their_bucket(self):
        self.pay('3.00')
        self.assertEqual(self._movements('own_money', 'savings'), [])
        self.assertEqual(self._movements('own_money', 'nonsense'), [])

    def _external_deposit(self, amount, address):
        from django.utils import timezone
        from users.models_unified import UnifiedTransactionTable
        return UnifiedTransactionTable.objects.create(
            transaction_type='send', amount=amount, token_type='USDT', status='CONFIRMED',
            sender_type='external', from_address=address, to_address=self.account.bsc_address,
            counterparty_user=self.user, counterparty_type='user',
            sender_display_name='Depósito externo', transaction_date=timezone.now())

    def test_unknown_wallets_merge_into_one_line_before_the_top_five(self):
        from decimal import Decimal
        for i in range(6):
            self._external_deposit('10.00', '0x' + f'{i + 1:02x}' * 20)
        people = self._summary().counterparties
        external = [p for p in people if p.key == 'external']
        self.assertEqual(len(external), 1)
        self.assertEqual(external[0].name, 'Depósitos externos (6)')
        self.assertEqual(Decimal(external[0].received_usd), Decimal('60.00'))
        listed = self._movements('counterparty', 'external')
        self.assertEqual(len(listed), 6)

    def test_a_single_unknown_wallet_keeps_its_own_key(self):
        self._external_deposit('5.00', '0x' + '07' * 20)
        keys = [p.key for p in self._summary().counterparties]
        self.assertTrue(any(k.startswith('addr:') for k in keys))
        self.assertNotIn('external', keys)

    def test_unnamed_outgoing_wallets_are_never_called_deposits(self):
        from django.utils import timezone
        from users.models_unified import UnifiedTransactionTable
        for i, amount in enumerate(('20.00', '30.00')):
            UnifiedTransactionTable.objects.create(
                transaction_type='send', amount=amount, token_type='USDT', status='CONFIRMED',
                sender_user=self.user, sender_type='user', from_address=self.account.bsc_address,
                to_address='0x' + f'{i + 0x40:02x}' * 20, transaction_date=timezone.now())
        names = [p.name for p in self._summary().counterparties if p.key == 'external']
        self.assertEqual(names, ['Billeteras externas (2)'])

    def test_new_categories_are_accepted_and_summarized(self):
        a = self.pay('25.00')
        result = self._categorize(a, 'health', 'movement')
        self.assertTrue(getattr(result, 'success', True))
        cats = [(c.category, c.amount_usd) for c in self._summary().current.spending_by_category]
        self.assertIn(('health', '25.00'), cats)


class RecurringCircleTests(SimpleTestCase):
    """Habitual-payment day math on the 31-day month circle (insights §5)."""

    def test_wraparound_days_are_close_and_center_late_in_the_month(self):
        from users.cashflow import _circular_median, _circular_spread
        self.assertEqual(_circular_spread([28, 2]), 5)
        self.assertEqual(_circular_median([28, 2]), 30)        # never the linear 15th
        self.assertEqual(_circular_median([30, 1, 2]), 1)

    def test_far_apart_days_are_not_one_habit(self):
        from users.cashflow import _circular_spread
        self.assertEqual(_circular_spread([1, 20]), 12)
        self.assertEqual(_circular_spread([5, 5]), 0)


class MonthInsightsResolverTests(MonthSummaryResolverTests):
    """End to end over real ledger rows for monthInsights."""

    def _pay(self, who, amount, year, month, day, status='CONFIRMED'):
        from users.models_unified import UnifiedTransactionTable
        when = datetime(year, month, day, 15, 0, tzinfo=ZoneInfo('UTC'))
        return UnifiedTransactionTable.objects.create(
            transaction_type='send', amount=amount, fee_amount='', token_type='USDT', status=status,
            sender_user=self.user, sender_type='user', counterparty_user=who, counterparty_type='user',
            from_address=self.mine, to_address='0x' + format(who.id, '040x'),
            sender_display_name='Yo', counterparty_display_name=who.username, transaction_date=when)

    def _person(self, name):
        from users.models import User
        return User.objects.create_user(username=name, email=f'{name}@example.com', password='x', firebase_uid=name)

    def _insights(self, year, month, jwt=None):
        from types import SimpleNamespace
        from users.cashflow_schema import MonthSummaryQuery
        jwt = jwt or {'account_type': 'personal', 'account_index': 0, 'business_id': None}
        with mock.patch('users.jwt_context.get_jwt_business_context_with_validation', return_value=jwt):
            return MonthSummaryQuery().resolve_month_insights(
                SimpleNamespace(context=SimpleNamespace(user=self.user)), year=year, month=month, timezone='UTC')

    def test_detects_habits_and_skips_noise(self):
        karen, wilber, ana, beto, carla = (self._person(n) for n in ('karen', 'wilber', 'ana', 'beto', 'carla'))
        # Viewed month: July 2026 → looks at April, May, June.
        for m, d, amt in ((4, 5, '100.00'), (5, 6, '95.00'), (6, 4, '105.00')):
            self._pay(karen, amt, 2026, m, d)                    # habit: every month ~day 5
        self._pay(wilber, '35.00', 2026, 6, 12)                  # once: not a habit
        self._pay(ana, '50.00', 2026, 5, 10); self._pay(ana, '120.00', 2026, 6, 10)   # amounts too different
        self._pay(beto, '40.00', 2026, 5, 1); self._pay(beto, '40.00', 2026, 6, 20)   # days too far apart
        self._pay(carla, '0.50', 2026, 5, 3); self._pay(carla, '0.50', 2026, 6, 3)    # under US$1
        self._pay(karen, '60.00', 2026, 5, 20, status='FAILED')  # failed rows never count

        result = self._insights(2026, 7)
        self.assertEqual([(r.name, r.expected_day, r.expected_amount_usd) for r in result.recurring],
                         [('karen', 5, '100.00')])
        # Full June Salió (Karen 105 + Wilber 35 + Ana 120 + Beto 40 + Carla 0.50)
        self.assertEqual(result.previous_month_spending_usd, '300.50')

    def test_rent_split_in_two_payments_is_one_monthly_sum(self):
        landlord = self._person('landlord')
        self._pay(landlord, '100.00', 2026, 5, 28)
        self._pay(landlord, '50.00', 2026, 6, 30); self._pay(landlord, '50.00', 2026, 6, 31 - 1)
        result = self._insights(2026, 7)
        self.assertEqual([(r.expected_day, r.expected_amount_usd) for r in result.recurring], [(29, '100.00')])

    def test_wraparound_day_is_clamped_to_the_viewed_month(self):
        landlord = self._person('landlord2')
        self._pay(landlord, '80.00', 2026, 3, 31)
        self._pay(landlord, '80.00', 2026, 4, 2)
        self._pay(landlord, '80.00', 2026, 5, 30)
        result = self._insights(2026, 6)                         # June has 30 days
        self.assertEqual([r.expected_day for r in result.recurring], [30])

    def test_employees_and_bad_monetary_rows(self):
        jwt = {'account_type': 'business', 'account_index': 0, 'business_id': 424242}
        self.assertIsNone(self._insights(2026, 7, jwt=jwt))
        karen = self._person('karen-bad')
        self._pay(karen, 'not-a-number', 2026, 6, 5)
        from graphql import GraphQLError
        with self.assertRaises(GraphQLError):                    # never "no habits" from unreadable data
            self._insights(2026, 7)
