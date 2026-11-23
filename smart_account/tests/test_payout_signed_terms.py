"""executeRule pays the rule as the contract stores it when mined, and the
bridge fills whatever arrives. Money converts or pays only while the executed
rule is the one the owner signed for that order: amount, payoutRef and
authorization, on CLABE / Pix and on Pago Móvil. Fake values only."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from blockchain.models import SponsoredBatch
from payment_accounts import contract_funding, infinia_journeys
from payment_accounts.infinia_bridge import live_journeys
from payment_accounts.models import InfiniaJourney
from smart_account import abi, automation, reconcile
from smart_account.models import (
    SmartAccountEvent, SmartAccountPagoMovilDestination, SmartAccountPayout, SmartAccountPreparedAction,
    SmartAccountRule, SmartAccountRuleRun, SmartAccountStandingAuthorization,
)

from . import infinia_world as w
from .base import CUSD, WAD
from .infinia_base import InfiniaPayoutCase
from .test_pagomovil_payouts import DEPOSIT, TX, VE_ON, RunBase, quote

OTHER_REF = '0x' + '4d' * 32
PARKED = 'contract_funding_terms_changed'


class InfiniaSignedTermsTests(InfiniaPayoutCase):
    amount = '100.00'

    def broadcast_then_update(self, *, amount_usd=None, payout_ref=None, mirror_between=False):
        self.make_rule()
        self.world.hold_broadcast = True
        self.assertEqual(self.run_rules()['sent'], 1)
        self.update_on_chain(amount_usd=amount_usd, payout_ref=payout_ref)
        if mirror_between:
            self.mirror_chain()         # the update is known before the payment
        self.world.mine_held()
        self.mirror_chain()

    def assert_parked(self, reason, *, delivered=True):
        self.bridges()
        bridge = self.bridge()
        self.assertTrue(bridge.source_tx_hash, 'bound, so it is tracked')
        self.assertEqual(bridge.binding['contract_funding']['terms_changed'], reason)
        self.assertEqual((self.journey().stage, self.journey().failure_code), ('needs_review', PARKED))
        if delivered:
            order = self.world.orders[-1]
            received = self.world.deposit_of(order)[1]
            tx_hash, units = self.world.relay_fills(order, out=received * 99 // 100 // 10 ** 12)
            self.bridges()
            self.credit_usdc(tx_hash, units)
        for _ in range(3):
            self.run_rules()
            self.workers()
        self.assertEqual((self.world.transfers, self.world.payouts), ([], []))
        self.assertEqual((self.payout().status, self.journey().stage), ('review', 'needs_review'))
        if delivered:
            self.assertEqual(self.bridge().status, 'delivered')
            self.assertIsNotNone(self.bridge().provider_credit_id)
        self.assertIn('no es lo que firmó', self.alert_text())

    def test_a_raised_amount_and_another_recipient_mirrored_with_the_payment_never_pay(self):
        self.broadcast_then_update(amount_usd='2000', payout_ref=OTHER_REF)
        self.assertGreater(int(self.payout().usdt_amount), 1900 * w.WAD)
        self.assert_parked('amount_above_signed')

    def test_a_raised_amount_mirrored_before_the_payment_never_pays(self):
        self.broadcast_then_update(amount_usd='2000', payout_ref=OTHER_REF, mirror_between=True)
        self.assert_parked('amount_above_signed')

    def test_a_raise_small_enough_to_look_like_a_fee_drop_never_pays(self):
        # 99.60 USDT still is under the US$100 signed: the authorization is not the one executed.
        self.broadcast_then_update(amount_usd='100.50')
        self.assertLess(int(self.payout().usdt_amount), 100 * w.WAD)
        self.assert_parked('authorization_changed')

    def test_another_recipient_at_the_same_amount_never_pays(self):
        self.broadcast_then_update(payout_ref=OTHER_REF)
        self.assert_parked('payout_ref_changed')

    def test_the_same_terms_signed_again_before_the_payment_never_pay(self):
        self.broadcast_then_update(mirror_between=True)
        self.assert_parked('authorization_changed')

    def test_a_cusd_plus_rule_switched_to_cusd_and_raised_never_pays(self):
        self.token = w.VAULT
        self.world.balances[(w.VAULT, self.contract)] = 100_000 * w.WAD
        self.world.balances[(w.CUSD, self.contract)] = 0
        self.make_rule()
        self.assertEqual(self.rule.token_in.lower(), w.VAULT)
        self.world.hold_broadcast = True
        self.assertEqual(self.run_rules()['sent'], 1)
        self.world.rules[(self.contract, 1)]['token_in'] = w.CUSD
        self.update_on_chain(amount_usd='2000')
        # The contract's abi.decode ignores the third word a cUSD rule does not use.
        real = self.world.execute_rule

        def lenient(account, calldata):
            name, args = abi.decode_call(calldata)
            cut = abi.encode_call(name, args[0], bytes(args[1])[:64], args[2], args[3])
            return real(account, cut)
        with mock.patch.object(self.world, 'execute_rule', side_effect=lenient):
            self.world.mine_held()
        self.mirror_chain()
        self.assert_parked('amount_above_signed')

    def test_a_parked_payment_does_not_hold_the_owners_own_sends(self):
        self.broadcast_then_update(payout_ref=OTHER_REF)
        self.assert_parked('payout_ref_changed')
        self.assertFalse(live_journeys(InfiniaJourney.objects.filter(confio_account=self.personal)).exists())
        contract_funding.require_free(self.personal, self.local, self.crypto)
        from payment_accounts import bridge_execution
        from payment_accounts.bridge import quote_provider_funding
        self.world.balances[(w.USDT, self.wallet)] = 100 * w.WAD
        manual = bridge_execution.prepare_bridge(self.personal, quote_provider_funding(
            confio_account=self.personal, funding_instruction_id=self.instruction.internal_id, amount='20',
            request_id='7c1b1f0e-0000-4000-8000-000000000001',
            destination_id=self.destination.internal_id).internal_id)
        self.assertTrue(infinia_journeys.create_journey(
            owner=self.personal, local_account=self.local, crypto_account=self.crypto,
            request_id='7c1b1f0e-0000-4000-8000-000000000002', minimum_fx_output='1', direction='to_bank',
            bridge=manual, destination=self.destination))

    def test_a_parked_payment_relay_returns_is_seen_back_at_the_contract(self):
        self.broadcast_then_update(amount_usd='2000')
        self.bridges()
        self.world.relay_refunds()
        self.workers()
        self.assertEqual((self.bridge().status, self.payout().status), ('refunded', 'refunded'))
        self.assertEqual(self.world.payouts, [])

    def test_an_update_after_the_payment_does_not_park_it(self):
        self.make_rule()
        self.send_run()
        self.update_on_chain(amount_usd='2000', payout_ref=OTHER_REF)
        self.mirror_chain()
        self.assertEqual(self.to_paid().status, 'paid')

    def test_an_update_after_the_payment_mirrored_with_it_does_not_park_it(self):
        self.make_rule()
        self.assertEqual(self.run_rules()['sent'], 1)       # mined, not mirrored
        self.update_on_chain(amount_usd='2000', payout_ref=OTHER_REF)
        self.mirror_chain()
        self.assertEqual(self.to_paid().status, 'paid')
        self.assertEqual(len(self.world.payouts), 1)

    def test_an_ordinary_revoke_after_a_valid_payment_does_not_park_it(self):
        self.make_rule()
        self.send_run()
        SmartAccountStandingAuthorization.objects.update(revoked_at=timezone.now(), revoked_reason='rule_cancelled')
        SmartAccountRule.objects.update(active=False, state='cancelled')
        self.assertEqual(self.to_paid().status, 'paid')

    def test_a_vault_fee_drop_still_pays(self):
        self.make_rule()
        self.world.hold_broadcast = True
        self.run_rules()
        self.world.fee_bps = 0      # all of the signed amount, never more
        self.world.mine_held()
        self.mirror_chain()
        self.assertEqual(self.to_paid().status, 'paid')

    def test_the_journey_worker_checks_again_before_converting(self):
        # A bridge bound by a worker that did not check (an older version).
        self.broadcast_then_update(payout_ref=OTHER_REF)
        with mock.patch('payment_accounts.contract_funding.signed_terms_problem', return_value=''):
            self.deliver()
        self.assertEqual(self.journey().stage, 'awaiting_credit')
        self.journeys()
        self.assertEqual((self.journey().failure_code, self.world.transfers), (PARKED, []))

    def test_no_event_is_no_proof(self):
        # Not mirrored yet (an event-scan outage): nothing converts or pays,
        # and nothing is parked for it (audit round 4, P3-1).
        self.make_rule()
        self.send_run()
        SmartAccountEvent.objects.filter(name='PayoutSent').update(name='Other')
        self.bridges()
        self.deliver()
        self.journeys()
        self.assertEqual((self.journey().stage, self.journey().failure_code, self.world.transfers),
                         ('awaiting_credit', '', []))


class ReadAgainBeforeSigningTests(InfiniaPayoutCase):
    amount = '100.00'

    def assert_nothing_signed(self, out):
        self.assertEqual(out['waiting'], 1)
        self.assertEqual((self.world.signed, self.last_run().status, self.last_run().error),
                         ({}, 'pending', 'rule_changed'))

    def test_any_difference_from_what_was_read_aborts(self):
        changes = {'amount_usd_wei': 2000 * w.WAD, 'payout_ref': OTHER_REF, 'token_in': w.VAULT,
                   'frequency': 'weekly', 'next_run_at': 1, 'active': False, 'epoch': 9}
        self.make_rule()
        original = dict(self.world.rules[(self.contract, 1)])
        from smart_account import relayer
        real = relayer.simulate
        for field, value in changes.items():
            with self.subTest(field=field):
                def changed_after_simulation(*args):
                    real(*args)
                    self.world.rules[(self.contract, 1)][field] = value
                with mock.patch('smart_account.relayer.simulate', side_effect=changed_after_simulation), \
                        mock.patch('smart_account.notifications.rule_run') as told:
                    self.assert_nothing_signed(self.run_rules())
                told.assert_not_called()
                self.world.rules[(self.contract, 1)].update(original)
        self.send_run()     # and unchanged, the same order pays

    def test_an_unreadable_rule_is_not_signed(self):
        self.make_rule()
        from smart_account import chain, relayer
        real_simulate, real_read = relayer.simulate, chain.account_rule
        broken = []

        def simulate(*args):
            real_simulate(*args)
            broken.append(True)

        def read(*args):
            if broken:
                raise RuntimeError('rpc')
            return real_read(*args)
        with mock.patch('smart_account.relayer.simulate', side_effect=simulate), \
                mock.patch('smart_account.chain.account_rule', side_effect=read):
            self.assertEqual(self.run_rules()['waiting'], 1)
        self.assertEqual((self.world.signed, self.last_run().error), ({}, 'rule_unreadable'))

    def test_the_owners_update_still_on_the_wire_aborts(self):
        self.make_rule()
        batch = SponsoredBatch.objects.create(
            user=self.user, user_bsc_address=self.wallet, kind='smart_rule', num_calls=1, calls_json='[]',
            tx_hash='0x' + '8b' * 32, gas_limit=1, max_fee_wei='1', status='sent')
        action = SmartAccountPreparedAction.objects.create(
            request_id='fake-update', user=self.user, signer_address=self.wallet, target_address=self.contract,
            smart_account=self.account, kind='smart_rule', calls=[], calls_hash='f' * 64,
            payload={'replaces_pk': self.rule.pk}, expires_at=timezone.now() + timedelta(minutes=10),
            consumed=True, sponsored_batch=batch)
        self.assert_nothing_signed(self.run_rules())
        SmartAccountPreparedAction.objects.filter(pk=action.pk).update(payload={'replaces_pk': self.rule.pk + 999})
        self.send_run()

    def test_an_update_the_mirror_has_not_seen_waits_even_at_the_same_terms(self):
        self.make_rule()
        self.update_on_chain()
        self.assertEqual(self.run_rules()['waiting'], 1)
        self.assertEqual((self.last_run().error, self.world.signed), ('rule_mirror_behind', {}))

    def test_an_authorization_revoked_while_signing_aborts(self):
        self.make_rule()
        from smart_account import relayer
        real = relayer.simulate

        def revoked(*args):
            real(*args)
            SmartAccountStandingAuthorization.objects.update(revoked_at=timezone.now())
        with mock.patch('smart_account.relayer.simulate', side_effect=revoked):
            self.assertEqual(self.run_rules()['waiting'], 1)
        from smart_account.models import SmartAccountRelayTx
        self.assertFalse(SmartAccountRelayTx.objects.exists())
        self.assertEqual(self.world.count('BSC', 'eth_sendRawTransaction'), 0)


HUNDRED_NET = 99_100_000_000_000_000_000        # previewRedeem(100).net at 0.9%


@override_settings(**VE_ON)
class PagoMovilSignedTermsTests(RunBase):
    """The same invariant on the live Pago Móvil path: 100 -> 2,000 and a
    changed beneficiary."""

    def prepare(self, destination, **kwargs):
        kwargs.setdefault('amount_usd', '100.00')
        return super().prepare(destination, **kwargs)

    def setUp(self):
        from ramps import ve_send
        real = ve_send.reserve
        super().setUp()
        self.chain.rules[(self.address, 1)]['amount_usd_wei'] = 100 * WAD
        self.quote.return_value = dict(quote(ves='3920.00', usdt='99.10'), usd_amount='100.00')
        for patcher in (
                mock.patch('ramps.ve_send.reserve', side_effect=real),
                mock.patch('cusd_plus.cusd_vault.preview_redeem_wei',
                           return_value=SimpleNamespace(net_wei=HUNDRED_NET))):
            patcher.start()
            self.addCleanup(patcher.stop)
        alert = mock.patch('config.ops_alerts.send_ops_alert', return_value=True)
        self.alert = alert.start()
        self.addCleanup(alert.stop)
        self.block = 100

    def event(self, name, args, tx_hash, *, applied=True):
        self.block += 1
        return SmartAccountEvent.objects.create(
            smart_account=self.account, address=self.address, tx_hash=tx_hash, log_index=1, name=name, args=args,
            block_number=self.block, block_time=timezone.now(), applied_at=timezone.now() if applied else None)

    def updated(self, *, applied=True):
        return self.event('RuleUpdated', {'id': '1'}, f'0x{self.block + 1:064x}', applied=applied)

    def new_ref(self):
        from smart_account import payouts
        other = SmartAccountPagoMovilDestination.objects.create(
            user=self.owner, phone='584120000000', bank_code='0102', id_number='V00000001',
            holder_name='Otra Persona', label='Pago Móvil · 0000')
        return '0x' + payouts.pagomovil_ref_for(other).hex()

    def paid_onchain(self, *, units=HUNDRED_NET, ref=None):
        """PayoutSent mirrored, then ramps' own proof from the receipt."""
        from ramps import ve_send
        event = self.event('PayoutSent', {'id': '1', 'payoutRef': ref or self.rule.payout_ref, 'destination': DEPOSIT,
                                          'tokenIn': CUSD, 'amountIn': str(units), 'usdtOut': str(units)}, TX)
        log = {'address': ve_send.USDT_BSC, 'data': hex(units),
               'topics': [ve_send.TRANSFER_TOPIC, '0x' + '0' * 24 + CUSD[2:], '0x' + '0' * 24 + DEPOSIT[2:]]}

        def rpc(method, params):
            if method == 'eth_getBlockByNumber':
                return {'number': hex(10 ** 6)} if params[0] == 'finalized' else {'hash': '0xb1'}
            if method == 'eth_getTransactionReceipt':
                return {'status': '0x1', 'blockNumber': '0x64', 'blockHash': '0xb1', 'logs': [log]}
            raise AssertionError(f'no {method}')
        with mock.patch('ramps.ve_send._rpc_default', return_value=rpc), \
                self.captureOnCommitCallbacks(execute=True):
            for effect in reconcile._payout_sent(self.account, event):
                effect()
        return self.ramps().get()

    def assert_never_paid(self, ramp, reason):
        from ramps import ve_send
        section = ve_send._section(ramp)
        self.assertEqual((ramp.status, ramp.status_detail, section['phase'], section['funding_terms_problem']),
                         ('PROCESSING', f'needs_review:{PARKED}', 'payout_review', reason))
        self.assertEqual(section['funding_tx_hash'], TX)        # tracked
        self.assertEqual(SmartAccountPayout.objects.get().status, 'review')
        self.assertTrue(any(PARKED in str(c.args[0]) for c in self.alert.call_args_list))
        with mock.patch('ramps.pagoasap_send.settle') as settle, \
                mock.patch('ramps.pagoasap_send.payout_terms') as terms, \
                mock.patch('ramps.pagoasap_send.dispatch') as dispatch:
            ve_send.sync(ramp)
            for mocked in (settle, terms, dispatch):
                mocked.assert_not_called()
            # Nor when ops sends it back to settle: parked again before pricing.
            settle.return_value = ve_send.Settlement('delivered', credited_usd='98.00', evidence='0x' + '5c' * 32)
            ve_send.retry_payout(ramp, operator='ops', reviewed_key='', reviewed_revision=0, confirmed_unpaid=True)
            ve_send.sync(ramp)
            parked = ve_send.sync(ramp)
            terms.assert_not_called()
            dispatch.assert_not_called()
        self.assertEqual((parked.status_detail, ve_send._phase(parked)), (f'needs_review:{PARKED}', 'payout_review'))

    def test_100_to_2000_and_a_changed_beneficiary_never_pays(self):
        self.assertEqual(self.run_rule()['sent'], 1)
        self.updated()
        ramp = self.paid_onchain(units=1982 * WAD, ref=self.new_ref())
        self.assertEqual(ramp.metadata['ve_send']['beneficiary']['phone'], '584141234567')   # the old one
        self.assertEqual(ramp.metadata['ve_send']['funded_wei'], str(1982 * WAD))
        self.assert_never_paid(ramp, 'amount_above_signed')

    def test_100_to_2000_not_mirrored_yet_never_pays(self):
        self.run_rule()
        self.updated(applied=False)
        self.assert_never_paid(self.paid_onchain(units=1982 * WAD), 'amount_above_signed')

    def test_a_changed_beneficiary_at_the_same_amount_never_pays(self):
        self.run_rule()
        self.updated()
        self.assert_never_paid(self.paid_onchain(ref=self.new_ref()), 'payout_ref_changed')

    def test_the_same_terms_signed_again_never_pay(self):
        self.run_rule()
        self.updated()
        self.assert_never_paid(self.paid_onchain(), 'authorization_changed')

    def test_a_valid_payment_is_funded_and_a_later_update_does_not_park_it(self):
        self.event('RuleCreated', {'id': '1', 'kind': '1'}, '0x' + '1c' * 32)
        self.run_rule()
        ramp = self.paid_onchain()
        self.updated()
        SmartAccountStandingAuthorization.objects.update(revoked_at=timezone.now())
        self.assertEqual((ramp.status, ramp.metadata['ve_send']['phase']), ('PROCESSING', 'funded'))
        from ramps import ve_send
        self.assertEqual(ve_send._terms_problem(ramp, TX, HUNDRED_NET), '')

    def test_a_fee_drop_still_funds_it(self):
        self.run_rule()
        ramp = self.paid_onchain(units=100 * WAD)
        self.assertEqual(ramp.metadata['ve_send']['phase'], 'funded')

    def legacy_order(self):
        self.run_rule()
        ramp = self.ramps().get()
        ramp.metadata['ve_send'].pop('funding_terms')
        ramp.save(update_fields=['metadata'])

    def test_an_order_made_before_terms_were_recorded_still_pays_when_unchanged(self):
        self.legacy_order()
        self.assertEqual(self.paid_onchain().metadata['ve_send']['phase'], 'funded')

    def test_an_order_made_before_terms_were_recorded_is_checked_too(self):
        self.legacy_order()
        self.updated()
        self.assert_never_paid(self.paid_onchain(ref=self.new_ref()), 'payout_ref_changed')

    def test_an_order_made_before_terms_were_recorded_sees_an_update(self):
        self.legacy_order()
        self.updated()
        self.assert_never_paid(self.paid_onchain(), 'authorization_changed')

    def test_a_send_funded_before_the_check_is_stopped_before_its_payout(self):
        from ramps import ve_send
        self.run_rule()
        with mock.patch('ramps.ve_send._terms_problem', return_value=''):
            ramp = self.paid_onchain(units=1982 * WAD, ref=self.new_ref())
        self.assertEqual(ramp.metadata['ve_send']['phase'], 'funded')
        ve_send._update(ramp.pk, phase='settled', credited_usd='99.00')
        with mock.patch('ramps.pagoasap_send.payout_terms') as terms:
            parked = ve_send.sync(ramp)
        terms.assert_not_called()
        self.assertEqual(parked.status_detail, f'needs_review:{PARKED}')

    def test_the_provider_adapter_never_prices_over_the_signed_gross(self):
        from ramps import pagoasap_send, ve_send
        self.run_rule()
        ramp = ve_send._update(self.ramps().get().pk, credited_usd='1980.00')
        with mock.patch('ramps.pagoasap_send._client') as client:
            self.assertEqual(pagoasap_send.payout_terms(ramp, []), {'review': PARKED})
        client.assert_not_called()

    def test_a_retry_after_the_beneficiary_changed_never_reuses_the_old_order(self):
        from notifications.models import Notification
        self.relay.side_effect = [RuntimeError('the worker died'), (SimpleNamespace(signed_tx_hash=TX), True)]
        self.run_rule()
        first = self.ramps().get()
        other = self.save(phone='0412 0000000', bank_code='0102', id_number='V00000001', holder_name='Otra Persona')
        destination = SmartAccountPagoMovilDestination.objects.get(internal_id=other.payout_method.payout_method_id)
        self.prepare(destination)
        draft = SmartAccountRule.objects.get(state='draft')
        fields = dict(pagomovil_destination=draft.pagomovil_destination, payout_ref=draft.payout_ref,
                      standing_authorization=draft.standing_authorization)
        SmartAccountRule.all_objects.filter(pk=draft.pk).delete()
        SmartAccountRule.objects.filter(pk=self.rule.pk).update(**fields)       # the update, mirrored
        self.updated()
        Notification.objects.filter(user=self.owner).delete()
        self.assertEqual(self.run_rule()['sent'], 1)
        first.refresh_from_db()
        self.assertEqual((first.status, first.status_detail), ('FAILED', 'payout_not_sent'))
        second = SmartAccountPayout.objects.get().ramp
        self.assertNotEqual(second.pk, first.pk)
        section = second.metadata['ve_send']
        self.assertEqual(section['beneficiary']['phone'], '584120000000')
        self.assertEqual((section['funding_terms']['attempt'], section['funding_terms']['replaces']),
                         (2, str(first.internal_id)))
        # A slot's fresh order is no new withdrawal, nor a failed one, to the owner.
        self.assertFalse(Notification.objects.filter(
            user=self.owner, notification_type__in=('RAMP_FAILED', 'RAMP_PENDING')).exists())

    @override_settings(VE_PAGOMOVIL_SEND_USER_DAILY_USD='150')
    def test_a_parked_payment_does_not_count_against_the_owners_sends_forever(self):
        from ramps import ve_send
        self.run_rule()
        self.updated()
        ramp = self.paid_onchain()
        with self.assertRaises(ve_send.VeSendLimitError):
            ve_send.check_limits(self.owner, Decimal('100'))
        type(ramp).objects.filter(pk=ramp.pk).update(created_at=timezone.now() - timedelta(days=2))
        ve_send.check_limits(self.owner, Decimal('100'))
