"""Server-only Cuenta inteligente mutations reachable from a smart-context
JWT: deleting an alert and saving a Pago Móvil destination. Both act on the
JWT user's own rows only; an inherited smart_N viewer never reaches the
previous owner's rows."""
from decimal import Decimal
from types import SimpleNamespace

from django.test import override_settings
from graphql import GraphQLError

from smart_account import context, schema
from smart_account.models import SmartAccountPagoMovilDestination, SmartAccountWatch

from .base import SmartAccountTestCase

VE_ON = dict(SMART_ACCOUNT_PAYOUT_RAILS='ve_pagomovil', SMART_ACCOUNT_PAYOUT_VERIFIED_ADAPTERS='pagoasap',
             VE_PAGOMOVIL_SEND_ENABLED=True, PAGOASAP_DEPOSIT_ADDRESS_POLYGON='0x' + '9a' * 20,
             RELAY_API_KEY='fake-relay-key')


def _resolve_info(field_name, ctx):
    return SimpleNamespace(
        path=SimpleNamespace(prev=None),
        operation=SimpleNamespace(operation=SimpleNamespace(value='mutation')),
        field_name=field_name, context=ctx)


class SmartContextAllowlistTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.account = self.make_account(self.owner)

    def watch(self, account, user):
        return SmartAccountWatch.objects.create(
            smart_account=account, user=user, kind='fx_rate_above', currency='VES', threshold=Decimal('50'))

    def test_gate_lets_both_server_only_mutations_through_a_smart_jwt(self):
        gate = context.SmartContextGateMiddleware()
        for index in (0, 1):
            smart = self.info(self.owner, 'smart', index).context
            for name in ('deleteSmartAccountWatch', 'saveSmartAccountPagoMovilDestination'):
                self.assertEqual(gate.resolve(lambda *a, **k: 'ran', None, _resolve_info(name, smart)), 'ran')
        # Still refused: the assistant (it has no smart-context viewer).
        smart = self.info(self.owner, 'smart', 0).context
        for name in ('askAssistant', 'updateAssistantProfile'):
            with self.assertRaises(GraphQLError):
                gate.resolve(lambda *a, **k: 'ran', None, _resolve_info(name, smart))

    def test_owner_deletes_own_alert_from_the_smart_context(self):
        watch = self.watch(self.account, self.owner)
        result = schema.DeleteSmartAccountWatch.mutate(None, self.info(self.owner, 'smart', 0), str(watch.internal_id))
        self.assertTrue(result.success, result.error_code)
        self.assertFalse(SmartAccountWatch.objects.filter(pk=watch.pk, active=True).exists())

    def test_inherited_context_never_touches_the_previous_owners_alerts(self):
        heir = self.make_user('heir')
        self.make_account(heir)
        inherited = self.make_account(heir, status='inherited', index=1, inherited_from_user=self.owner)
        theirs = self.watch(inherited, self.owner)   # set by the previous owner, kept as theirs
        result = schema.DeleteSmartAccountWatch.mutate(None, self.info(heir, 'smart', 1), str(theirs.internal_id))
        self.assertEqual((result.success, result.error_code), (False, 'not_found'))
        self.assertTrue(SmartAccountWatch.objects.filter(pk=theirs.pk, active=True).exists())
        # Another user's alert from smart_0 too.
        mine = self.watch(self.account, self.owner)
        result = schema.DeleteSmartAccountWatch.mutate(None, self.info(heir, 'smart', 0), str(mine.internal_id))
        self.assertFalse(result.success)

    @override_settings(**VE_ON)
    def test_pago_movil_destination_is_saved_for_the_jwt_user_from_a_smart_context(self):
        result = schema.SaveSmartAccountPagoMovilDestination.mutate(
            None, self.info(self.owner, 'smart', 0), phone='0414 1234567', bank_code='0134',
            id_number='V12345678', holder_name='Ana Pérez')
        self.assertTrue(result.success, result.error_message)
        self.assertEqual(result.payout_method.rail, 've_pagomovil')
        row = SmartAccountPagoMovilDestination.objects.get()
        self.assertEqual(row.user_id, self.owner.pk)
