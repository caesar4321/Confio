from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import graphene
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import TestCase

from ramps import ve_funnel, ve_pagomovil_schema
from ramps.models import RampQuoteView, RampTransaction

User = get_user_model()
QUOTE = {'usd_amount': '50', 'ves_amount': '54614', 'rate': '1086.8', 'estimated_usdt': '47.63',
         'processor_fee_usd': '1.93', 'confio_fee_usd': '0.44', 'min_usd': '1.25'}


def _order(user, status='FAILED', detail='cancelled_by_user', **extra):
    ramp = RampTransaction(provider='vexpay', direction='on_ramp', status=status, status_detail=detail,
                           country_code='VE', actor_user=user, actor_type='user', fiat_currency='VES',
                           crypto_currency='USDT', metadata={'vexpay': {'phase': 'created'}}, **extra)
    ramp.external_id = str(ramp.internal_id)
    ramp.save()
    return ramp


class QuoteViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='ve_quote', firebase_uid='ve_quote', country='VE')

    def test_one_row_per_day_counts_views_and_keeps_first_last_and_largest(self):
        for usd, net in (('10', '9.36'), ('2000', '1913.45'), ('50', '47.63')):
            self.assertTrue(ve_funnel.record_quote_view(self.user, ve_funnel.TOPUP_RAIL, Decimal(usd), net))
        row = RampQuoteView.objects.get(user=self.user)
        self.assertEqual((row.views, row.first_usd, row.last_usd, row.max_usd, row.last_net_usd, row.country),
                         (3, Decimal('10.00'), Decimal('50.00'), Decimal('2000.00'), Decimal('47.63'), 'VE'))

    def test_bad_amounts_are_not_recorded(self):
        for bad in (None, 'abc', Decimal('NaN'), Decimal('-1'), Decimal('1e30')):
            self.assertFalse(ve_funnel.record_quote_view(self.user, ve_funnel.TOPUP_RAIL, bad))
        self.assertFalse(RampQuoteView.objects.exists())

    def test_a_failed_write_neither_raises_nor_poisons_the_callers_transaction(self):
        def failing_sql(*args, **kwargs):
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1/0')

        with mock.patch.object(RampQuoteView.objects, 'get_or_create', side_effect=failing_sql):
            with transaction.atomic():
                self.assertFalse(ve_funnel.record_quote_view(self.user, ve_funnel.TOPUP_RAIL, Decimal('10')))
                self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def _quote(self, user):
        schema = graphene.Schema(query=ve_pagomovil_schema.Query)
        adapter = SimpleNamespace(quote=lambda amount: dict(QUOTE))
        with mock.patch.object(ve_pagomovil_schema.ve_pagomovil, 'enabled', return_value=True), \
                mock.patch.object(ve_pagomovil_schema.ve_pagomovil, 'topup_adapter', return_value=adapter), \
                mock.patch.object(ve_pagomovil_schema.ve_pagomovil, 'optional_limit', return_value=None):
            return schema.execute('{ vePagomovilTopUpQuote(usdAmount: "50") { success estimatedUsdt error } }',
                                  context_value=SimpleNamespace(user=user, META={}))

    def test_the_quote_query_records_the_view(self):
        result = self._quote(self.user)
        self.assertIsNone(result.errors)
        self.assertTrue(result.data['vePagomovilTopUpQuote']['success'])
        row = RampQuoteView.objects.get(user=self.user, rail=ve_funnel.TOPUP_RAIL)
        self.assertEqual((row.views, row.last_usd, row.last_net_usd), (1, Decimal('50.00'), Decimal('47.63')))

    def test_a_refused_quote_records_nothing(self):
        schema = graphene.Schema(query=ve_pagomovil_schema.Query)
        with mock.patch.object(ve_pagomovil_schema.ve_pagomovil, 'enabled', return_value=False):
            result = schema.execute('{ vePagomovilTopUpQuote(usdAmount: "50") { success } }',
                                    context_value=SimpleNamespace(user=self.user, META={}))
        self.assertFalse(result.data['vePagomovilTopUpQuote']['success'])
        self.assertFalse(RampQuoteView.objects.exists())


class CancelReasonTests(TestCase):
    MUTATION = ('mutation($o: String!, $r: String!) { recordVePagomovilTopUpCancelReason(orderId: $o, reason: $r) '
                '{ success } }')

    def setUp(self):
        self.user = User.objects.create_user(username='ve_cancel', firebase_uid='ve_cancel')
        self.schema = graphene.Schema(query=ve_pagomovil_schema.Query, mutation=ve_pagomovil_schema.Mutation)

    def _send(self, ramp, reason, user=None):
        result = self.schema.execute(self.MUTATION, variable_values={'o': str(ramp.internal_id), 'r': reason},
                                     context_value=SimpleNamespace(user=user or self.user, META={}))
        self.assertIsNone(result.errors)
        ramp.refresh_from_db()
        return result.data['recordVePagomovilTopUpCancelReason']['success']

    def test_keeps_the_first_reason_and_the_provider_section(self):
        ramp = _order(self.user)
        self.assertTrue(self._send(ramp, 'fee'))
        self.assertTrue(self._send(ramp, 'looking'))
        self.assertEqual(ramp.metadata['cancel_reason']['reason'], 'fee')
        self.assertEqual(ramp.metadata['vexpay'], {'phase': 'created'})
        self.assertEqual((ramp.status, ramp.status_detail), ('FAILED', 'cancelled_by_user'))

    def test_unknown_reason_is_refused(self):
        ramp = _order(self.user)
        self.assertFalse(self._send(ramp, 'free text from a client'))
        self.assertNotIn('cancel_reason', ramp.metadata)

    def test_only_an_order_the_person_cancelled(self):
        for status, detail in (('PENDING', 'awaiting_payment'), ('FAILED', 'expired_unpaid'), ('COMPLETED', 'delivered')):
            ramp = _order(self.user, status=status, detail=detail)
            self.assertFalse(self._send(ramp, 'fee'))
            self.assertNotIn('cancel_reason', ramp.metadata)

    def test_someone_elses_order_and_anonymous_are_refused(self):
        ramp = _order(self.user)
        other = User.objects.create_user(username='ve_other', firebase_uid='ve_other')
        self.assertFalse(self._send(ramp, 'fee', user=other))
        self.assertFalse(self._send(ramp, 'fee', user=SimpleNamespace(is_authenticated=False)))
        self.assertNotIn('cancel_reason', ramp.metadata)


class ReasonKeysTests(TestCase):
    def test_the_app_offers_exactly_the_servers_exit_reasons(self):
        import re
        from pathlib import Path
        source = (Path(__file__).resolve().parents[2] / 'apps/src/services/topUpExit.ts').read_text()
        block = source.split('TOP_UP_EXIT_REASONS = [', 1)[1].split('] as const', 1)[0]
        skipped = re.search(r"TOP_UP_EXIT_SKIPPED = '(\w+)'", source).group(1)
        self.assertEqual(tuple(re.findall(r"\['(\w+)',", block)) + (skipped,), ve_funnel.EXIT_REASONS)


class LimitViewTests(TestCase):
    """Bolivia, 2026-11: most people typed under Koywe's 350 BOB and left; a
    refused amount is a look at the price too, and must be askable."""

    def setUp(self):
        self.user = User.objects.create_user(username='limit_view', firebase_uid='limit_view', country='BO')

    def test_a_fiat_only_refusal_then_a_price_fills_the_dollar_amounts(self):
        self.assertTrue(ve_funnel.record_quote_view(self.user, 'koywe_bo_topup', None, fiat_amount=Decimal('100'),
                                                    fiat_currency='bob', outside_limits=True))
        row = RampQuoteView.objects.get(user=self.user)
        self.assertEqual((row.views, row.last_outside_limits, row.first_usd, row.max_usd, row.last_fiat_amount,
                          row.fiat_currency),
                         (1, True, None, None, Decimal('100.00'), 'BOB'))
        ve_funnel.record_quote_view(self.user, 'koywe_bo_topup', Decimal('30.76'), Decimal('29'),
                                    fiat_amount=Decimal('350'), fiat_currency='BOB')
        row.refresh_from_db()
        self.assertFalse(row.last_outside_limits)  # the price they typed up to was accepted
        ve_funnel.record_quote_view(self.user, 'koywe_bo_topup', None, fiat_amount=Decimal('200'),
                                    fiat_currency='BOB', outside_limits=True)
        row.refresh_from_db()
        self.assertEqual((row.views, row.last_outside_limits, row.first_usd, row.last_usd, row.max_usd,
                          row.last_net_usd, row.last_fiat_amount),
                         (3, True, Decimal('30.76'), Decimal('30.76'), Decimal('30.76'), Decimal('29.00'),
                          Decimal('200.00')))

    def test_nothing_to_count_is_not_recorded(self):
        self.assertFalse(ve_funnel.record_quote_view(self.user, 'koywe_bo_topup', None, fiat_amount='abc'))
        self.assertFalse(RampQuoteView.objects.exists())

    def test_koywe_below_minimum_top_up_is_a_limit_view_but_a_withdrawal_is_not(self):
        from ramps import schema
        from ramps.koywe_client import KoyweMinimumAmountError
        info = SimpleNamespace(context=SimpleNamespace(user=self.user))
        client = mock.Mock(is_configured=True)
        client.get_ramp_quote.side_effect = KoyweMinimumAmountError('min', currency='BOB', actual='100', minimum='350')
        for direction in ('ON_RAMP', 'OFF_RAMP'):
            with mock.patch.object(schema, '_resolve_ramp_country_code', return_value='BO'), \
                    mock.patch.object(schema, 'KoyweClient', return_value=client), \
                    mock.patch.object(schema, '_validate_koywe_on_ramp_quote_limits'), \
                    mock.patch.object(schema, '_get_koywe_auth_email', return_value=None), \
                    mock.patch('users.funnel.emit_once'):
                with self.assertRaises(Exception):
                    schema.Query().resolve_ramp_quote(info, direction=direction, amount='100', country_code='BO',
                                                      fiat_currency='BOB', payment_method_code='QRI-BO')
        row = RampQuoteView.objects.get(user=self.user)
        self.assertEqual((row.rail, row.views, row.last_outside_limits, row.last_fiat_amount, row.first_usd),
                         ('koywe_bo_topup', 1, True, Decimal('100.00'), None))

    def test_ve_below_minimum_is_a_limit_view(self):
        def below(amount):
            raise ve_pagomovil_schema.ve_pagomovil.BelowMinimumError('Mínimo US$1.25')
        schema = graphene.Schema(query=ve_pagomovil_schema.Query)
        with mock.patch.object(ve_pagomovil_schema.ve_pagomovil, 'enabled', return_value=True), \
                mock.patch.object(ve_pagomovil_schema.ve_pagomovil, 'topup_adapter',
                                  return_value=SimpleNamespace(quote=below)):
            schema.execute('{ vePagomovilTopUpQuote(usdAmount: "1") { success } }',
                           context_value=SimpleNamespace(user=self.user, META={}))
        row = RampQuoteView.objects.get(user=self.user)
        self.assertEqual((row.rail, row.last_outside_limits, row.last_usd), (ve_funnel.TOPUP_RAIL, True, Decimal('1.00')))


class BoliviaQrQuoteViewTests(TestCase):
    """QR Bolivia is Bolivia's own top-up: its prices are top-up views too."""

    def setUp(self):
        self.user = User.objects.create_user(username='bo_qr_view', firebase_uid='bo_qr_view', country='BO')

    def _quote(self, bob, terms=None, maximum=None):
        from ramps import bolivia_qr, bolivia_qr_receive, bolivia_qr_schema
        schema = graphene.Schema(query=bolivia_qr_schema.Query)
        impl = SimpleNamespace(quote_receive=lambda amount: terms or {
            'usdc_units': '0', 'usd_estimate': '14.367816', 'rate': '6.96', 'fee_bob': '0'})
        with mock.patch.object(bolivia_qr, 'offered', return_value=True), \
                mock.patch.object(bolivia_qr, 'provider_name', return_value='mesadepagos'), \
                mock.patch.object(bolivia_qr, 'optional_limit', return_value=maximum), \
                mock.patch.object(bolivia_qr_receive, 'adapter', return_value=impl):
            return schema.execute('query($b: String!) { boliviaQrReceiveQuote(bobAmount: $b) { success error } }',
                                  variable_values={'b': bob}, context_value=SimpleNamespace(user=self.user, META={}))

    def test_a_priced_qr_and_a_refusal_for_the_maximum_are_top_up_views(self):
        self.assertTrue(self._quote('100').data['boliviaQrReceiveQuote']['success'])
        self.assertFalse(self._quote('100000', terms={'usdc_units': '0', 'usd_estimate': '14367.81', 'rate': '6.96',
                                                     'fee_bob': '0'}, maximum=Decimal('2000'))
                         .data['boliviaQrReceiveQuote']['success'])
        row = RampQuoteView.objects.get(user=self.user)
        self.assertEqual((row.rail, row.views, row.last_outside_limits, row.last_usd, row.last_fiat_amount,
                          row.fiat_currency),
                         ('bo_qr_topup', 2, True, Decimal('14367.81'), Decimal('100000.00'), 'BOB'))
        self.assertEqual(row.max_usd, Decimal('14367.81'))


class ExitReasonTests(TestCase):
    MUTATION = 'mutation($r: String!) { recordTopUpExitReason(reason: $r) { success } }'

    def setUp(self):
        from ramps import schema
        self.user = User.objects.create_user(username='exit_reason', firebase_uid='exit_reason', country='BO')
        self.schema = graphene.Schema(query=schema.Query, mutation=schema.Mutation)

    def _send(self, reason, user=None):
        result = self.schema.execute(self.MUTATION, variable_values={'r': reason},
                                     context_value=SimpleNamespace(user=user or self.user, META={}))
        self.assertIsNone(result.errors)
        return result.data['recordTopUpExitReason']['success']

    def _view(self, rail, minutes_ago=1):
        from datetime import timedelta
        from django.utils import timezone
        ve_funnel.record_quote_view(self.user, rail, Decimal('30'))
        RampQuoteView.objects.filter(user=self.user, rail=rail).update(
            last_seen_at=timezone.now() - timedelta(minutes=minutes_ago))

    def test_lands_on_the_latest_top_up_view_and_the_first_answer_stays(self):
        self._view('ve_pagomovil_topup', minutes_ago=30)
        self._view('koywe_bo_topup', minutes_ago=1)
        self.assertTrue(self._send('no_money'))
        self.assertTrue(self._send('looking'))
        latest = RampQuoteView.objects.get(rail='koywe_bo_topup')
        self.assertEqual(latest.exit_reason, 'no_money')
        self.assertIsNotNone(latest.exit_reason_at)
        self.assertEqual(RampQuoteView.objects.get(rail='ve_pagomovil_topup').exit_reason, '')

    def test_a_skip_gives_way_to_a_real_answer_but_not_the_reverse(self):
        self._view('koywe_bo_topup')
        self.assertTrue(self._send('skipped'))
        self.assertTrue(self._send('loan'))
        self.assertTrue(self._send('skipped'))
        self.assertEqual(RampQuoteView.objects.get().exit_reason, 'loan')

    def test_an_order_after_the_price_is_not_leaving_it_but_an_earlier_one_does_not_count(self):
        from datetime import timedelta
        from django.utils import timezone
        earlier = _order(self.user, status='PENDING', detail='awaiting_payment')
        RampTransaction.objects.filter(pk=earlier.pk).update(created_at=timezone.now() - timedelta(minutes=5))
        self._view('koywe_bo_topup')  # the price, 1 minute ago: after that order
        self.assertTrue(self._send('no_money'))
        RampQuoteView.objects.update(exit_reason='')
        _order(self.user, status='FAILED', detail='face_check_unavailable')  # after it, but never taken
        self.assertTrue(self._send('trust'))
        RampQuoteView.objects.update(exit_reason='')
        _order(self.user, status='PENDING', detail='awaiting_payment')  # after it, and taken
        self.assertFalse(self._send('no_money'))
        self.assertEqual(RampQuoteView.objects.get().exit_reason, '')

    def test_no_recent_top_up_view_unknown_reason_or_anonymous_saves_nothing(self):
        self.assertFalse(self._send('looking'))
        self._view('koywe_bo_topup', minutes_ago=121)
        self._view('koywe_bo_offramp')
        self.assertFalse(self._send('looking'))
        self._view('koywe_bo_topup')
        self.assertFalse(self._send('free text'))
        self.assertFalse(self._send('looking', user=SimpleNamespace(is_authenticated=False)))
        self.assertFalse(RampQuoteView.objects.exclude(exit_reason='').exists())


class KoyweTopUpQuoteViewTests(TestCase):
    """Bolivia, 2026-11-13: 55 of 79 verified signups never started a top-up,
    and the funnel event kept only the first keystroke of the day."""

    def setUp(self):
        self.user = User.objects.create_user(username='bo_quote', firebase_uid='bo_quote', country='BO')

    def _quote(self, amount, direction='ON_RAMP', user=None):
        from ramps import schema
        info = SimpleNamespace(context=SimpleNamespace(user=user or self.user))
        client = mock.Mock(is_configured=True)
        client.get_ramp_quote.return_value = dict(
            direction=direction, amount_in=str(amount), amount_out=str((Decimal(amount) / Decimal('11.38')).quantize(Decimal('0.01'))),
            exchange_rate=Decimal('11.38'), fee_amount='6.13', fee_currency='BOB', network_fee_amount='0.13',
            network_fee_currency='BOB', rate_display='', total_change_display='', token_symbol='USDT',
            network_symbol='BSC', network_display='BSC', asset_note='')
        with mock.patch.object(schema, '_resolve_ramp_country_code', return_value='BO'), \
                mock.patch.object(schema, 'KoyweClient', return_value=client), \
                mock.patch.object(schema, '_validate_koywe_on_ramp_quote_limits'), \
                mock.patch.object(schema, '_get_koywe_auth_email', return_value=None), \
                mock.patch('users.funnel.emit_once'):
            return schema.Query().resolve_ramp_quote(info, direction=direction, amount=str(amount), country_code='BO',
                                                     fiat_currency='BOB', payment_method_code='QRI-BO')

    def test_quotes_count_in_dollars_at_the_quotes_rate(self):
        self._quote('350')
        self._quote('1138')
        self._quote('569')
        row = RampQuoteView.objects.get(user=self.user)
        self.assertEqual((row.rail, row.views, row.first_usd, row.last_usd, row.max_usd, row.last_net_usd, row.country),
                         ('koywe_bo_topup', 3, Decimal('30.76'), Decimal('50.00'), Decimal('100.00'), Decimal('50.00'), 'BO'))

    def test_withdrawal_quotes_and_anonymous_quotes_are_not_top_up_views(self):
        self._quote('100', direction='OFF_RAMP')
        self._quote('350', user=SimpleNamespace(is_authenticated=False))
        self.assertFalse(RampQuoteView.objects.exists())

    def test_an_unusable_rate_or_amount_records_nothing_and_never_raises(self):
        from ramps import schema
        schema._record_koywe_top_up_view(self.user, 'BO', '1E+999999', Decimal('0.0001'), None)
        schema._record_koywe_top_up_view(self.user, 'BO', 'abc', Decimal('11.38'), None)
        schema._record_koywe_top_up_view(self.user, 'BO', Decimal('350'), None, Decimal('30'))
        schema._record_koywe_top_up_view(self.user, 'BO', Decimal('350'), '0', Decimal('30'))
        self.assertFalse(RampQuoteView.objects.exists())
