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
    def test_the_app_offers_exactly_the_servers_reasons(self):
        import re
        from pathlib import Path
        source = (Path(__file__).resolve().parents[2] / 'apps/src/services/vePagoMovilTopUp.ts').read_text()
        block = source.split('VE_TOP_UP_CANCEL_REASONS = [', 1)[1].split('] as const', 1)[0]
        self.assertEqual(tuple(re.findall(r"\['(\w+)',", block)), ve_funnel.CANCEL_REASONS)


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
