"""Venezuelan Pago Móvil (Pago ASAP) bank payment rules: offer switch,
saved beneficiaries, Face-bound authorization and the unattended run.
Pago ASAP, Relay and the chain are mocked; ramps' proof of a contract-funded
send (ramps.ve_send.CONTRACT_FUNDING, not built yet) is simulated."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.db import connection
from django.test import override_settings
from django.utils import timezone

from smart_account import abi, automation, offer, payouts, reconcile, schema, services
from smart_account.models import (
    SmartAccountPagoMovilDestination, SmartAccountPayout, SmartAccountRule, SmartAccountRuleRun,
    SmartAccountStandingAuthorization,
)

from .base import CUSD, INFINIA_SWITCHES, WAD, SmartAccountTestCase, priced_pagomovil

VE_ON = dict(SMART_ACCOUNT_PAYOUT_RAILS='ve_pagomovil', SMART_ACCOUNT_PAYOUT_VERIFIED_ADAPTERS='pagoasap',
             VE_PAGOMOVIL_SEND_ENABLED=True, PAGOASAP_DEPOSIT_ADDRESS_POLYGON='0x' + '9a' * 20,
             RELAY_API_KEY='fake-relay-key')
DEPOSIT = '0x' + 'de' * 20
TX = '0x' + 'ab' * 32
EXACT = 49_550_000_000_000_000_000          # previewRedeem(50).net at 0.9%


def quote(rate='40', ves='1960.00', usdt='49.55'):
    return {'usd_amount': '50.00', 'usdt_amount': usdt, 'confio_fee_usd': '0.45', 'processor_fee_usd': '0.10',
            'estimated_ves': ves, 'rate': rate}


class PagoMovilBase(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.account = self.make_account(self.owner)
        self.address = self.account.contract_address.lower()
        self.fund(CUSD, self.address, 500 * WAD)
        patches = [
            mock.patch('ramps.ve_send.CONTRACT_FUNDING', True, create=True),
            mock.patch('payment_accounts.services.require_outgoing_face', return_value='face-key-1'),
            mock.patch('security.face_step_up.step_up_applies', return_value=True),
            mock.patch('smart_account.payouts.reference_ves_rate', return_value=Decimal('40')),
            priced_pagomovil(),
        ]
        self.mocks = [p.start() for p in patches]
        self.face_mock = self.mocks[1]
        for p in patches:
            self.addCleanup(p.stop)

    def save(self, user=None, **kw):
        args = dict(phone='0414 1234567', bank_code='0134', id_number='V12345678', holder_name='Ana Pérez')
        args.update(kw)
        return schema.SaveSmartAccountPagoMovilDestination.mutate(None, self.info(user or self.owner), **args)

    def destination(self):
        result = self.save()
        self.assertTrue(result.success, result.error_message)
        return SmartAccountPagoMovilDestination.objects.get(internal_id=result.payout_method.payout_method_id)

    def prepare(self, destination, **kw):
        args = dict(rule_id=None, payout_method_id=str(destination.internal_id), amount_usd='50.00',
                    frequency='monthly')
        args.update(kw)
        return services.prepare_payout_rule(self.viewer(self.owner), **args)


@override_settings(**VE_ON)
class OfferAndDestinationTests(PagoMovilBase):
    def test_offered_only_when_switched_on(self):
        self.assertEqual(offer.payout_rails(), ['ve_pagomovil'])
        self.assertEqual(offer.payout_rail_options(), [
            {'key': 've_pagomovil', 'label': 'Pago Móvil', 'hint': payouts.VE_PAGOMOVIL_HINT}])
        with override_settings(SMART_ACCOUNT_PAYOUT_VERIFIED_ADAPTERS=''):
            self.assertEqual(offer.payout_rails(), [])
        # Infinia's flag never turns on Pago ASAP, nor 'infinia' in the new list Infinia.
        with override_settings(SMART_ACCOUNT_PAYOUT_VERIFIED_ADAPTERS='', SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED=True):
            self.assertEqual(offer.payout_rails(), [])
        with override_settings(SMART_ACCOUNT_PAYOUT_RAILS='mx_clabe', SMART_ACCOUNT_PAYOUT_VERIFIED_ADAPTERS='infinia',
                               **INFINIA_SWITCHES):     # a rail with an adapter, so only the flag keeps it off
            self.assertEqual(offer.payout_rails(), [])
        with override_settings(SMART_ACCOUNT_PAYOUT_RAILS=''):
            self.assertEqual(offer.payout_rails(), [])
        # ramps has not declared it can take a contract-funded send.
        with mock.patch('ramps.ve_send.CONTRACT_FUNDING', False, create=True):
            self.assertEqual(offer.payout_rails(), [])

    def test_qr_still_excluded(self):
        with override_settings(SMART_ACCOUNT_PAYOUT_RAILS='co_qr,br_qr,ve_pagomovil,co_breb,ar_qr,mx_clabe',
                               SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED=True, **INFINIA_SWITCHES):
            # co_breb has no adapter: no flag offers it.
            self.assertEqual(offer.payout_rails(), ['ve_pagomovil', 'mx_clabe'])

    def test_destination_is_saved_validated_encrypted_and_listed(self):
        result = self.save()
        self.assertTrue(result.success)
        self.assertEqual((result.payout_method.rail, result.payout_method.holder_name, result.payout_method.label),
                         ('ve_pagomovil', '', 'Pago Móvil · Banesco · 4567 · C.I. …5678 (escribiste: Ana Pérez)'))
        row = SmartAccountPagoMovilDestination.objects.get()
        self.assertEqual((row.phone, row.bank_code, row.id_number), ('584141234567', '0134', 'V12345678'))
        self.assertEqual(row.label, 'Pago Móvil · Banesco · 4567')
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT phone, id_number FROM {SmartAccountPagoMovilDestination._meta.db_table}')
            raw = cursor.fetchone()
        self.assertNotIn('4141234567', raw[0])
        self.assertNotIn('12345678', raw[1])
        # Same beneficiary again: the same row.
        again = self.save(phone='+58 414-123-4567', id_number='12345678')
        self.assertEqual(again.payout_method.payout_method_id, str(row.internal_id))
        self.assertEqual(SmartAccountPagoMovilDestination.objects.count(), 1)
        for bad in ({'phone': '0212 1234567'}, {'bank_code': '9999'}, {'id_number': 'X1'}, {'holder_name': ' '}):
            refused = self.save(**bad)
            self.assertEqual((refused.success, refused.error_code), (False, 'bad_pagomovil_destination'))
        methods = schema.Query.resolve_smart_account_payout_methods(None, self.info(self.owner))
        self.assertEqual([(m.rail, m.available, m.payout_method_id) for m in methods],
                         [('ve_pagomovil', True, str(row.internal_id))])
        other = self.make_user('other')
        self.assertEqual(schema.Query.resolve_smart_account_payout_methods(None, self.info(other)), [])

    def test_not_saved_while_the_rail_is_off(self):
        with override_settings(SMART_ACCOUNT_PAYOUT_RAILS=''):
            self.assertEqual(self.save().error_code, 'payout_not_available')
        self.assertFalse(SmartAccountPagoMovilDestination.objects.exists())


@override_settings(**VE_ON)
class PrepareTests(PagoMovilBase):
    def test_prepare_claims_face_bound_to_the_beneficiary(self):
        destination = self.destination()
        batch = self.prepare(destination)
        authorization = SmartAccountStandingAuthorization.objects.get()
        self.assertEqual((authorization.rail, authorization.pagomovil_destination, authorization.face_action_key),
                         ('ve_pagomovil', destination, 'face-key-1'))
        self.assertEqual(authorization.reference_fx_rate, Decimal('40'))
        self.assertEqual(authorization.binding_hash,
                         payouts.pagomovil_binding_hash(destination, Decimal('50.00'), 'monthly'))
        namespace, identifier, payload = self.face_mock.call_args[0][1:4]
        self.assertEqual(namespace, 'smart_account_payout_rule')
        self.assertEqual(identifier, payouts.face_identifier(authorization.binding_hash, authorization.pk))
        self.assertEqual((payload['destination'], payload['rail']), (str(destination.internal_id), 've_pagomovil'))
        rule = SmartAccountRule.objects.get()
        self.assertEqual((rule.payout_rail, rule.pagomovil_destination, rule.payout_method, rule.token_in.lower()),
                         ('ve_pagomovil', destination, None, CUSD))
        name, args = abi.decode_call(batch.calls[0]['data'])
        self.assertEqual(name, 'createRule')
        self.assertEqual('0x' + bytes(args[0][5]).hex(), rule.payout_ref)
        self.assertEqual(rule.payout_ref, '0x' + payouts.pagomovil_ref_for(destination).hex())
        # Another phone, bank or cédula is another binding.
        changed = SmartAccountPagoMovilDestination(
            internal_id=destination.internal_id, phone='584149999999', bank_code='0134', id_number='V12345678')
        self.assertNotEqual(payouts.pagomovil_binding_hash(changed, Decimal('50.00'), 'monthly'),
                            authorization.binding_hash)

    def test_no_rule_without_face(self):
        destination = self.destination()
        self.face_mock.return_value = ''
        with self.assertRaises(services.PrepareError) as raised:
            self.prepare(destination)
        self.assertEqual(raised.exception.code, 'face_required')
        self.assertFalse(SmartAccountStandingAuthorization.objects.exists())
        self.assertFalse(SmartAccountRule.all_objects.exists())

    def test_refusals_before_face(self):
        destination = self.destination()
        with mock.patch('smart_account.payouts.reference_ves_rate', side_effect=RuntimeError('down')):
            with self.assertRaises(services.PrepareError) as raised:
                self.prepare(destination)
        self.assertEqual(raised.exception.code, 'payout_quote_unavailable')
        # A cUSD+ account is NOT refused: its exit is exact too
        # (test_plus_payouts.PagoMovilPlusTests).
        self.face_mock.assert_not_called()
        other = self.make_user('other')
        self.make_account(other)
        with self.assertRaises(services.PrepareError) as raised:
            services.prepare_payout_rule(self.viewer(other), None, str(destination.internal_id), '50.00', 'monthly')
        self.assertEqual(raised.exception.code, 'payout_method_not_found')


def per_order(target):
    """What Relay does for a one-time route: an address per order (the first
    is DEPOSIT) and an output that follows the amount deposited."""
    given = []

    def answer(ramp):
        value = dict(target.return_value)
        if given:
            value['deposit_address'] = f'0x{0xde000 + len(given):040x}'
        given.append(ramp.pk)
        deposit = int(ramp.metadata['ve_send']['deposit_wei'])
        # Unless a test quotes its own.
        value['binding'] = dict({'amount_out': str(deposit * 997 // 1000 // 10 ** 12)}, **value['binding'])
        return value
    target.side_effect = answer


def _reserve_without_sender(real):
    """The current ramps reserve has no funding_sender: record it and drop it."""
    seen = {}

    def reserve(**kwargs):
        seen['funding_sender'] = kwargs.pop('funding_sender')
        return real(**kwargs)
    return reserve, seen


class RunBase(PagoMovilBase):
    def setUp(self):
        super().setUp()
        from ramps import pagoasap_send, ve_send
        self.dest = self.destination()
        self.prepare(self.dest)
        self.rule = SmartAccountRule.objects.get()
        self.slot = timezone.now().replace(microsecond=0) - timedelta(minutes=3)
        SmartAccountRule.objects.filter(pk=self.rule.pk).update(
            state='onchain', active=True, onchain_id=1, scheduled_for=self.slot, next_run_at=self.slot)
        self.rule.refresh_from_db()
        self.chain.views[(self.address, 'status')] = 1
        self.chain.views[(self.address, 'billingStatus')] = 0
        self.chain.rules[(self.address, 1)] = {'kind': 'payout', 'active': True, 'frequency': 'monthly',
                                               'amount_usd_wei': 50 * WAD, 'next_run_at': int(self.slot.timestamp())}
        reserve, self.reserved = _reserve_without_sender(ve_send.reserve)
        self.quote = mock.MagicMock(return_value=quote())
        self.target = mock.MagicMock(return_value={
            'deposit_address': DEPOSIT, 'binding': {'provider': 'relay', 'request_id': 'r1', 'response': {},
                                                    'deadline': int(timezone.now().timestamp()) + 900}})
        per_order(self.target)
        self.relay = mock.MagicMock(return_value=(SimpleNamespace(signed_tx_hash=TX), True))
        patches = [
            mock.patch('ramps.ve_send.reserve', side_effect=reserve),
            mock.patch.object(pagoasap_send, 'SHARED_DEPOSIT_TARGET', False),
            mock.patch('ramps.pagoasap_send.quote', self.quote),
            mock.patch('ramps.pagoasap_send.funding_target', self.target),
            # Pago ASAP's preview (test_money_path_audit runs the real check).
            mock.patch('ramps.pagoasap_send.pays_at_floor', return_value=True),
            mock.patch('ramps.ve_send.current_block', return_value=100),
            mock.patch('cusd_plus.cusd_vault.preview_redeem_wei',
                       return_value=SimpleNamespace(net_wei=EXACT)),
            mock.patch('smart_account.relayer.send_relayer_call', self.relay),
            mock.patch('smart_account.relayer.live_tx', return_value=None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_rule(self):
        with mock.patch('smart_account.notifications.rule_run') as told:
            out = automation.run_rules()
        self.told = told
        return out

    def last_run(self):
        return SmartAccountRuleRun.objects.get(rule=self.rule)

    def ramps(self):
        from ramps.models import RampTransaction
        return RampTransaction.objects.filter(provider='pagoasap')


@override_settings(**VE_ON)
class RunTests(RunBase):
    def test_full_run_from_due_slot_to_payout_sent_to_paid(self):
        from ramps import ve_send
        self.assertEqual(self.run_rule()['sent'], 1)
        run = self.last_run()
        self.assertEqual((run.status, run.tx_hash), ('sent', TX))
        calldata = self.relay.call_args[0][1]
        name, args = abi.decode_call(calldata)
        self.assertEqual((name, args[0]), ('executeRule', 1))
        self.assertEqual(bytes(args[1]), abi.payout_rule_data(DEPOSIT, EXACT))
        ramp = self.ramps().get()
        payout = SmartAccountPayout.objects.get()
        self.assertEqual((payout.provider, payout.ramp_id, payout.deposit_address, payout.status),
                         ('pagoasap', ramp.pk, DEPOSIT, 'prepared'))
        # The owner is sender of record; the contract is the funding wallet;
        # the cUSD vault is the sender of the USDT transfer.
        self.assertEqual((ramp.actor_user, ramp.actor_address, ramp.status), (self.owner, self.address, 'PENDING'))
        self.assertEqual(self.reserved['funding_sender'], CUSD)
        section = ve_send._section(ramp)
        self.assertEqual((section['phase'], section['deposit_wei'], section['deposit_address']),
                         ('funding_reported', str(EXACT), DEPOSIT))
        self.assertEqual(section['beneficiary'], {'cedula': 'V12345678', 'phone': '584141234567',
                                                  'bank_code': '0134', 'name': 'Ana Pérez'})

        # PayoutSent mirrored: ramps is told the hash and proves the funding.
        def proved(r, rpc=None):   # what ramps' contract-funding proof does
            return ve_send._mark_funded(r, TX, EXACT)
        event = SimpleNamespace(args={'id': 1, 'destination': DEPOSIT, 'usdtOut': EXACT}, tx_hash=TX)
        with mock.patch('ramps.ve_send.sync', side_effect=proved) as synced:
            for effect in reconcile._payout_sent(self.account, event):
                effect()
        synced.assert_called_once()
        ramp.refresh_from_db()
        self.assertIn(TX, ve_send._section(ramp)['funding_tx_hashes'])
        self.assertEqual((ramp.status, ve_send._section(ramp)['phase']), ('PROCESSING', 'funded'))
        payout.refresh_from_db()
        self.assertEqual((payout.status, payout.usdt_amount), ('funded', str(EXACT)))

        # ramps pays and polls it to completion; the owner hears the bolívares.
        type(ramp).objects.filter(pk=ramp.pk).update(status='COMPLETED', status_detail='delivered',
                                                     fiat_amount=Decimal('1960.00'))
        with mock.patch('smart_account.notifications.payout_delivered') as delivered:
            self.assertEqual(payouts.mirror_ramp_payouts()['updated'], 1)
            payouts.mirror_ramp_payouts()
        delivered.assert_called_once()
        self.assertEqual(delivered.call_args[0][1:], ('1.960,00', 'Bs.'))
        payout.refresh_from_db()
        self.assertEqual((payout.status, payout.fiat_amount), ('paid', Decimal('1960.00')))

    def test_delivered_message_names_the_beneficiary(self):
        from smart_account import notifications
        run = SmartAccountRuleRun.objects.create(rule=self.rule, scheduled_for=self.slot)
        with mock.patch('smart_account.notifications._send') as sent:
            notifications.payout_delivered(run, '1.960,00', 'Bs.')
        # The name was typed: in the label, marked, never as the holder.
        self.assertEqual(sent.call_args[0][2],
                         f'Enviamos Bs. 1.960,00 a {self.dest.label} (escribiste: Ana Pérez).')

    def assert_skipped(self, code):
        run = self.last_run()
        self.assertEqual((run.status, run.error), ('skipped', code))
        self.told.assert_called_once()
        self.relay.assert_not_called()

    def assert_retried(self, code):
        """Today's cost or rate: the slot is asked again inside its 24 hours."""
        run = self.last_run()
        self.assertEqual((run.status, run.error), ('failed', code))
        self.relay.assert_not_called()

    def assert_waiting(self, code):
        """Asked again inside the slot, untold (money-path audit 11)."""
        run = self.last_run()
        self.assertEqual((run.status, run.error), ('pending', code))
        self.told.assert_not_called()
        self.relay.assert_not_called()

    def test_quote_outside_the_rules_limits_skips_without_an_order(self):
        self.quote.return_value = quote(ves='1880.00')          # 47 delivered of 49.55: ~515 bps
        self.run_rule()
        self.assert_retried('bridge_cost_above_limit')
        self.assertFalse(self.ramps().exists())
        SmartAccountRuleRun.objects.all().delete()
        SmartAccountRule.objects.filter(pk=self.rule.pk).update(scheduled_for=self.slot)
        self.quote.return_value = quote(rate='30', ves='1470.00')  # 25% under the reference 40
        self.run_rule()
        self.assert_retried('fx_rate_below_limit')
        self.assertFalse(self.ramps().exists())

    @override_settings(VE_PAGOMOVIL_SEND_MAX_USD='10')
    def test_limit_exceeded_skips(self):
        self.run_rule()
        self.assert_skipped('limit_exceeded')
        self.assertIn('máximo', self.last_run().message)
        self.assertFalse(self.ramps().exists())

    @override_settings(VE_PAGOMOVIL_SEND_USER_DAILY_USD='10')
    def test_a_daily_cap_in_the_pre_check_retries_the_slot(self):
        self.run_rule()
        run = self.last_run()
        self.assertEqual((run.status, run.error), ('pending', 'limit_exceeded'))    # a wait
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.scheduled_for, self.slot)   # not given up
        self.assertFalse(self.ramps().exists())

    def test_a_limit_under_the_reservation_lock_is_decided_like_the_pre_check(self):
        from ramps import ve_send
        real = ve_send.check_limits
        for passing, expected in ((False, ('skipped', 'limit_exceeded')), (True, ('pending', 'limit_exceeded'))):
            SmartAccountRuleRun.objects.all().delete()
            SmartAccountRule.objects.filter(pk=self.rule.pk).update(scheduled_for=self.slot)
            calls = []

            def limits(user, amount, provider='pagoasap', passing=passing):
                calls.append(amount)
                if len(calls) == 2:   # the re-check inside ve_send.reserve
                    raise ve_send.VeSendLimitError('Alcanzaste tu límite.', passing=passing)
                return real(user, amount, provider)
            with mock.patch('ramps.ve_send.check_limits', side_effect=limits):
                self.run_rule()
            run = self.last_run()
            self.assertEqual(len(calls), 2)
            self.assertEqual((run.status, run.error), expected, passing)
            self.assertFalse(self.ramps().exists())

    def test_provider_down_waits(self):
        from ramps.pagoasap_client import PagoAsapError
        self.quote.side_effect = PagoAsapError('boom', status=503)
        self.run_rule()
        self.assert_waiting('provider_unavailable')
        self.assertFalse(self.ramps().exists())

    @override_settings(VE_PAGOMOVIL_SEND_ENABLED=False)
    def test_ve_sends_switched_off_waits(self):
        self.run_rule()
        self.assert_waiting('payouts_disabled')

    def test_bridge_target_failure_closes_the_order(self):
        from ramps.ve_pagomovil import VePagoMovilError
        self.target.side_effect = VePagoMovilError('No pudimos preparar el envío.')
        self.run_rule()
        self.assert_waiting('provider_unavailable')
        ramp = self.ramps().get()
        self.assertEqual((ramp.status, ramp.status_detail), ('FAILED', 'deposit_target_unavailable'))
        self.assertEqual(SmartAccountPayout.objects.get().status, 'cancelled')

    def test_idempotent_per_slot(self):
        self.run_rule()
        self.run_rule()
        self.assertEqual(self.relay.call_count, 1)
        self.assertEqual(self.ramps().count(), 1)
        self.assertEqual(SmartAccountPayout.objects.count(), 1)

    def test_an_interrupted_call_retries_the_same_order_and_address(self):
        self.relay.side_effect = [RuntimeError('the worker died'), (SimpleNamespace(signed_tx_hash=TX), True)]
        self.run_rule()
        self.assertEqual(self.last_run().status, 'pending')
        self.run_rule()
        self.assertEqual(self.last_run().status, 'sent')
        self.assertEqual(self.ramps().count(), 1)
        self.assertEqual(self.target.call_count, 1)
        first, second = (abi.decode_call(c[0][1])[1][1] for c in self.relay.call_args_list)
        self.assertEqual(bytes(first), bytes(second))

    def test_authorization_mismatch_deactivates(self):
        SmartAccountPagoMovilDestination.objects.filter(pk=self.dest.pk).update(bank_code='0102')
        with mock.patch('smart_account.notifications.rule_deactivated'):
            self.run_rule()
        self.assert_skipped('destination_changed')
        self.rule.refresh_from_db()
        self.assertEqual((self.rule.active, self.rule.deactivated_reason), (False, 'destination_changed'))
        self.assertFalse(self.ramps().exists())

    def test_a_deleted_beneficiary_deactivates_in_the_daily_sweep(self):
        self.dest.soft_delete()
        self.rule.refresh_from_db()
        self.assertEqual(payouts.authorization_problem(self.rule), 'destination_deleted')
        with mock.patch('smart_account.notifications.rule_deactivated') as told:
            self.assertEqual(payouts.deactivate_changed_rules(), 1)
        told.assert_called_once()

    def test_not_run_until_ramps_supports_contract_funding(self):
        with mock.patch('ramps.ve_send.CONTRACT_FUNDING', False, create=True):
            self.run_rule()
        self.assert_waiting('payouts_disabled')
        self.assertFalse(self.ramps().exists())

    def test_rule_survives_reconcile_with_its_beneficiary(self):
        """RuleCreated keeps a Pago Móvil rule's off-chain attributes."""
        draft = SmartAccountRule.objects.get()
        data = dict(self.chain.rules[(self.address, 1)], token_in=CUSD, token_out=abi.ZERO_ADDRESS,
                    payee=abi.ZERO_ADDRESS, payout_ref=draft.payout_ref, amount_usd_wei=50 * WAD,
                    next_run_at=int(self.slot.timestamp()))
        self.chain.rules[(self.address, 1)] = data
        rule = reconcile._rule_from_chain(self.account, 1, draft, draft)
        self.assertEqual((rule.active, rule.pagomovil_destination, rule.payout_rail),
                         (True, self.dest, 've_pagomovil'))
        self.assertIsNone(payouts.authorization_problem(rule))


@override_settings(**VE_ON)
class ReviewFixRunTests(RunBase):
    """Review fixes: payout orders never block (or are blocked by) the owner's
    own sends; a slot that ends unsent closes its order; PayoutSent revives a
    cancelled payout; usdtOut vs the order's deposit."""

    def setUp(self):
        from ramps import ve_send
        real = ve_send.reserve
        super().setUp()
        # The real ramps reserve, funding_sender included.
        patcher = mock.patch('ramps.ve_send.reserve', side_effect=real)
        patcher.start()
        self.addCleanup(patcher.stop)
        alert = mock.patch('config.ops_alerts.send_ops_alert', return_value=True)
        self.alert = alert.start()
        self.addCleanup(alert.stop)

    def _other_ramp(self, *, contract: bool, **kw):
        from ramps import ve_send
        from ramps.models import RampTransaction
        section = {'phase': 'funding_reported', 'gross_usd': '50.00', 'deposit_wei': str(EXACT),
                   'deposit_address': '0x' + 'd7' * 20, 'created_block': 90,     # its own route
                   'funding_started_at': timezone.now().isoformat()}
        if contract:
            section['funding_sender'] = CUSD
        ramp = RampTransaction(provider='pagoasap', direction='off_ramp', status='PENDING', country_code='VE',
                               actor_user=self.owner, actor_address=self.address if contract else '0x' + '33' * 20,
                               destination='cusd_plus', fiat_currency='VES', crypto_currency='USDT',
                               final_currency='USDT', metadata={ve_send.SECTION: section}, **kw)
        ramp.external_id = str(ramp.internal_id)
        ramp.save()
        return ramp

    def test_the_owners_own_pending_send_does_not_block_the_payout(self):
        self._other_ramp(contract=False)
        self.assertEqual(self.run_rule()['sent'], 1)
        self.assertEqual(self.last_run().status, 'sent')

    def test_an_identical_open_payout_order_is_retried_within_the_slot(self):
        other = self._other_ramp(contract=True)
        self.run_rule()
        run = self.last_run()
        self.assertEqual((run.status, run.error), ('pending', 'send_refused'))      # a wait
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.scheduled_for, self.slot)   # not given up
        self.relay.assert_not_called()
        type(other).objects.filter(pk=other.pk).update(status='FAILED', status_detail='payout_not_sent')
        self.run_rule()
        self.assertEqual(self.last_run().status, 'sent')

    def _expire_slot(self):
        slot = timezone.now().replace(microsecond=0) - timedelta(hours=25)
        SmartAccountRule.objects.filter(pk=self.rule.pk).update(scheduled_for=slot, next_run_at=slot)
        self.chain.rules[(self.address, 1)]['next_run_at'] = int(slot.timestamp())
        self.slot = slot

    def test_a_slot_given_up_unsent_closes_its_order_at_once(self):
        from smart_account import relayer
        self._expire_slot()
        self.relay.side_effect = relayer.RelayError('simulation_reverted')
        self.run_rule()
        ramp = self.ramps().get()
        self.assertEqual((ramp.status, ramp.status_detail), ('FAILED', 'payout_not_sent'))
        self.assertEqual(SmartAccountPayout.objects.get().status, 'cancelled')

    def test_a_live_relay_tx_keeps_the_order_open(self):
        from smart_account import relayer
        from smart_account.models import SmartAccountRelayTx
        self._expire_slot()
        self.relay.side_effect = relayer.RelayError('nonce')
        with mock.patch.object(SmartAccountRelayTx.objects, 'filter') as rows:
            # Live once the order exists (with one already live, plan_run opens none).
            rows.return_value.exists.side_effect = lambda: self.ramps().exists()
            self.run_rule()
        self.assertEqual(self.ramps().get().status, 'PENDING')

    def test_payout_sent_after_cancel_revives_the_payout_and_follows_the_ramp(self):
        from ramps import ve_send
        from smart_account import relayer
        self._expire_slot()
        self.relay.side_effect = relayer.RelayError('nonce')
        self.run_rule()
        payout = SmartAccountPayout.objects.get()
        self.assertEqual(payout.status, 'cancelled')
        # The call landed after all (e.g. a reorged broadcast came back).
        SmartAccountRuleRun.objects.filter(pk=self.last_run().pk).update(tx_hash=TX)
        log = {'address': ve_send.USDT_BSC, 'transactionHash': TX, 'data': hex(EXACT),
               'topics': [ve_send.TRANSFER_TOPIC, '0x' + '0' * 24 + CUSD[2:], '0x' + '0' * 24 + DEPOSIT[2:]]}

        def rpc(method, params):
            if method == 'eth_getBlockByNumber':
                return {'number': hex(10 ** 6)} if params[0] == 'finalized' else {'hash': '0xb1'}
            if method == 'eth_getTransactionReceipt':
                return {'status': '0x1', 'blockNumber': '0x64', 'blockHash': '0xb1', 'logs': [log]}
            raise AssertionError(f'no {method}: contract funding is never scanned')
        event = SimpleNamespace(args={'id': 1, 'destination': DEPOSIT, 'usdtOut': EXACT}, tx_hash=TX)
        with mock.patch('ramps.ve_send._rpc_default', return_value=rpc), \
                mock.patch('smart_account.notifications.payout_resumed') as resumed:
            for effect in reconcile._payout_sent(self.account, event):
                effect()
        resumed.assert_called_once()
        ramp = self.ramps().get()
        self.assertEqual((ramp.status, ramp.status_detail), ('PROCESSING', 'needs_review:late_funding'))
        payout.refresh_from_db()
        self.assertEqual(payout.status, 'review')
        # Ops pays it; the mirror follows and the owner hears the bolívares.
        type(ramp).objects.filter(pk=ramp.pk).update(status='COMPLETED', status_detail='delivered',
                                                     fiat_amount=Decimal('1960.00'))
        with mock.patch('smart_account.notifications.payout_delivered') as delivered:
            payouts.mirror_ramp_payouts()
        delivered.assert_called_once()
        payout.refresh_from_db()
        self.assertEqual(payout.status, 'paid')

    def test_unmatched_payout_sent_falls_back_to_the_payout_paying_that_destination(self):
        self.run_rule()
        run = self.last_run()
        payout = SmartAccountPayout.objects.get()
        other_tx = '0x' + 'e1' * 32   # the relayer's hash was lost
        self.assertNotEqual(run.tx_hash.lower(), other_tx)
        SmartAccountRuleRun.objects.filter(pk=run.pk).update(tx_hash='')
        event = SimpleNamespace(args={'id': 1, 'destination': DEPOSIT.upper().replace('0X', '0x'),
                                      'usdtOut': EXACT}, tx_hash=other_tx)
        with mock.patch('ramps.ve_send.report_funding', side_effect=lambda ramp, *a, **k: ramp) as report, \
                mock.patch('ramps.ve_send.sync', side_effect=lambda ramp, **k: ramp):
            effects = reconcile._payout_sent(self.account, event)
            self.assertTrue(effects)
            for effect in effects:
                effect()
        run.refresh_from_db()
        payout.refresh_from_db()
        self.assertEqual(run.tx_hash, other_tx)
        self.assertEqual((payout.status, payout.usdt_amount), ('onchain_sent', str(EXACT)))
        # ramps is told through the payout path, the only one a contract-funded
        # order accepts a hash from.
        self.assertEqual(report.call_args.args[1], other_tx)
        self.assertIs(report.call_args.kwargs.get('by_payout'), True)
        self.assertFalse(any('sin pago que le corresponda' in c.args[0] for c in self.alert.call_args_list))

    def _second_payout(self, *, run_hash, status='prepared'):
        """B: another slot's payout to the same Relay route (Relay may reuse
        one route per source)."""
        first = SmartAccountPayout.objects.get()
        run = SmartAccountRuleRun.objects.create(
            rule=first.rule_run.rule, scheduled_for=first.rule_run.scheduled_for + timedelta(days=7),
            status='sent', tx_hash=run_hash)
        return SmartAccountPayout.objects.create(
            rule_run=run, provider=first.provider, rail=first.rail, deposit_address=first.deposit_address,
            status=status)

    def test_a_late_payout_sent_never_lands_on_a_payout_holding_another_hash(self):
        # A was given up with its hash lost; B is prepared and submitted
        # (HB). A's PayoutSent (HA) arrives late: it belongs to A, never B.
        self.run_rule()
        a = SmartAccountPayout.objects.get()
        SmartAccountPayout.objects.filter(pk=a.pk).update(status='cancelled')
        SmartAccountRuleRun.objects.filter(pk=a.rule_run_id).update(tx_hash='')
        hb, ha = '0x' + 'b2' * 32, '0x' + 'a1' * 32
        b = self._second_payout(run_hash=hb)
        event = SimpleNamespace(args={'id': 1, 'destination': DEPOSIT, 'usdtOut': EXACT}, tx_hash=ha)
        self.assertEqual(reconcile._unmatched_payout(self.account, a.rule_run.rule, event).pk, a.pk)
        self.assertEqual(SmartAccountRuleRun.objects.get(pk=b.rule_run_id).tx_hash, hb)
        self.assertEqual(SmartAccountRuleRun.objects.get(pk=a.rule_run_id).tx_hash, ha)

    def test_a_payout_sent_whose_candidates_all_hold_other_hashes_alerts_ops(self):
        self.run_rule()
        a = SmartAccountPayout.objects.get()
        ha_old, hb, ha = a.rule_run.tx_hash, '0x' + 'b2' * 32, '0x' + 'a1' * 32
        self.assertTrue(ha_old)
        b = self._second_payout(run_hash=hb)
        event = SimpleNamespace(args={'id': 1, 'destination': DEPOSIT, 'usdtOut': EXACT}, tx_hash=ha)
        with self.captureOnCommitCallbacks(execute=True):       # the alert waits for the commit
            self.assertIsNone(reconcile._unmatched_payout(self.account, a.rule_run.rule, event))
        self.assertEqual(SmartAccountRuleRun.objects.get(pk=b.rule_run_id).tx_hash, hb)
        self.assertEqual(SmartAccountRuleRun.objects.get(pk=a.rule_run_id).tx_hash, ha_old)
        texts = [c.args[0] for c in self.alert.call_args_list]
        self.assertTrue(any('sin pago que le corresponda' in t for t in texts), texts)

    def test_unmatched_payout_sent_with_no_payout_for_it_alerts_ops(self):
        self.run_rule()
        payout = SmartAccountPayout.objects.get()
        status = payout.status
        event = SimpleNamespace(args={'id': 1, 'destination': '0x' + '4c' * 20, 'usdtOut': EXACT},
                                tx_hash='0x' + 'e2' * 32)
        with mock.patch('smart_account.payouts.after_payout_sent') as after, \
                self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(reconcile._payout_sent(self.account, event), [])
        after.assert_not_called()
        texts = [c.args[0] for c in self.alert.call_args_list]
        self.assertTrue(any('sin pago que le corresponda' in t for t in texts), texts)
        payout.refresh_from_db()
        self.assertEqual(payout.status, status)

    def test_usdt_out_different_from_the_orders_deposit_alerts_ops(self):
        self.run_rule()
        run = self.last_run()
        for usdt_out, alerted in ((EXACT, False), (EXACT + 7, True)):
            self.alert.reset_mock()
            event = SimpleNamespace(args={'id': 1, 'destination': DEPOSIT, 'usdtOut': usdt_out}, tx_hash=run.tx_hash)
            with mock.patch('smart_account.payouts.after_payout_sent'), \
                    self.captureOnCommitCallbacks(execute=True):
                reconcile._payout_sent(self.account, event)
            texts = [c.args[0] for c in self.alert.call_args_list]
            self.assertEqual(any('no coincide con el depósito' in t for t in texts), alerted, texts)
