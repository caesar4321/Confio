"""The trailing cancelClaim() on personal-wallet domain flows (spec 6.4):
payments, presale, invite create, Comprar (marketplace) and the payment
bridge. Accepted when it is ONE call, LAST, to the signer's OWN account;
refused when second, not last, or to another account. Signature and
broadcast always carry every call."""
import json
import time
from types import SimpleNamespace
from unittest import mock

from django.test import override_settings

from cusd_plus import sponsor_7702
from cusd_plus.sponsor_7702 import PolicyError
from smart_account import abi

from .base import CUSD, WAD
from .test_review_fixes import _ClaimPending, _word

ZERO = '0x' + '00' * 20


def _digest(calls, *args):
    return json.dumps(calls, sort_keys=True).encode()


class _FlowHarness(_ClaimPending):
    def setUp(self):
        super().setUp()
        self.recipient = '0x' + '7e' * 20
        self.transfer = {'to': CUSD, 'value': '0',
                         'data': '0x' + sponsor_7702.SEL_TRANSFER + _word(self.recipient) + _word(5 * WAD)}
        stranger = self.make_user('stranger')
        self.foreign = abi.call(self.make_account(stranger).contract_address, abi.encode_call('cancelClaim'))
        self.validated, self.broadcasts = [], []

    def signing(self, signed_calls, signer):
        """The signature recovers to `signer` only over exactly `signed_calls`."""
        expected = _digest(signed_calls)
        return [
            mock.patch('cusd_plus.sponsor_7702.intent_digest', side_effect=_digest),
            mock.patch('cusd_plus.sponsor_7702.recover_intent_signer',
                       side_effect=lambda d, s: signer if d == expected else ZERO),
            mock.patch('cusd_plus.sponsor_7702.is_delegated', return_value=True),
            mock.patch('cusd_plus.sponsor_7702.send_sponsored_batch', side_effect=self._broadcast),
        ]

    def _broadcast(self, user, addr, calls, *args, **kwargs):
        self.broadcasts.append(list(calls))
        raise PolicyError('reached_broadcast')

    def record(self, *args, **kwargs):
        self.validated.append(list(args[0]))

    def run_with(self, patches, fn):
        for p in patches:
            p.start()
        try:
            return fn()
        finally:
            for p in patches:
                p.stop()

    def refused_variants(self, base):
        return (base + [self.foreign], base + [self.cancel, self.cancel], [self.cancel] + base)


# ── payments ────────────────────────────────────────────────────────────

class PaymentCancelClaimTests(_FlowHarness):
    def _submit(self, calls):
        from payments import bsc_flow
        invoice = SimpleNamespace(status='PENDING', settlement_chain='BSC', internal_id='inv', is_expired=False)
        payment_tx = SimpleNamespace(
            id=77, pk=77, payer_user_id=self.owner.pk, status='PENDING_BLOCKCHAIN', invoice=invoice,
            payer_address=self.owner.wallet, merchant_address=self.recipient, payer_account_id=1,
            internal_id='pay', blockchain_data={'kind': 'pay_usdt', 'bsc_calls': calls})
        self.broadcasts.clear(); self.validated.clear()
        patches = self.signing(calls, self.owner.wallet) + [
            mock.patch('payments.bsc_flow._invoice_terms_unchanged', return_value=True),
            mock.patch('payments.bsc_flow._payer_still_authorized', return_value=True),
            mock.patch('payments.bsc_flow._payment_step_up', return_value=''),
            mock.patch('payments.bsc_flow._validate_payment_batch', side_effect=self.record)]
        return self.run_with(patches, lambda: bsc_flow.submit_bsc_payment(
            self.owner, payment_tx, 0, int(time.time()) + 600, '0x' + '00' * 65))

    def test_trailing_own_cancel_claim_accepted_and_broadcast(self):
        base = [self.transfer]
        for calls in (base, base + [self.cancel]):
            out = self._submit(calls)
            self.assertEqual(out['error'], 'reached_broadcast', calls)
            self.assertEqual(self.validated, [base])      # the flow's check sees its own calls
            self.assertEqual(self.broadcasts, [calls])    # signed and broadcast with all

    def test_second_misplaced_or_foreign_cancel_claim_refused(self):
        for calls in self.refused_variants([self.transfer]):
            out = self._submit(calls)
            self.assertEqual(out['error'], 'claim_cancel_not_allowed', calls)
            self.assertEqual(self.broadcasts, [])


# ── presale (a focused submit test; the legacy one predates intent_digest's signature) ──

class PresaleCancelClaimTests(_FlowHarness):
    def _submit(self, calls):
        from presale import bsc_flow
        purchase = SimpleNamespace(
            id=10 ** 9, pk=10 ** 9, status='processing', funding_source=bsc_flow.BSC_FUNDING_SOURCES[0],
            notes=json.dumps({'bsc_calls': calls}), from_address=self.owner.wallet,
            phase=SimpleNamespace(status='active', refresh_from_db=lambda **kw: None))
        self.broadcasts.clear(); self.validated.clear()
        patches = self.signing(calls, self.owner.wallet) + [
            mock.patch('presale.geo_utils.check_presale_eligibility', return_value=(True, '')),
            mock.patch('presale.models.PresaleSettings.get_settings',
                       return_value=SimpleNamespace(is_presale_active=True)),
            mock.patch('cusd_plus.cusd_vault.require_operational'),
            mock.patch('presale.bsc_flow._validate_presale_batch', side_effect=self.record)]
        return self.run_with(patches, lambda: bsc_flow.submit_purchase(
            self.owner, purchase, 0, int(time.time()) + 600, '0x' + '00' * 65))

    def test_submit_path_with_and_without_the_trailing_cancel_claim(self):
        base = [self.transfer]
        for calls in (base, base + [self.cancel]):
            out = self._submit(calls)
            self.assertEqual(out['error'], 'reached_broadcast', calls)
            self.assertEqual(self.validated, [base])
            self.assertEqual(self.broadcasts, [calls])
        # A signature over other calls than the stored ones is refused.
        purchase_calls = base + [self.cancel]
        patches = self.signing(base, self.owner.wallet)
        from presale import bsc_flow
        purchase = SimpleNamespace(
            id=10 ** 9, pk=10 ** 9, status='processing', funding_source=bsc_flow.BSC_FUNDING_SOURCES[0],
            notes=json.dumps({'bsc_calls': purchase_calls}), from_address=self.owner.wallet,
            phase=SimpleNamespace(status='active', refresh_from_db=lambda **kw: None))
        patches += [mock.patch('presale.geo_utils.check_presale_eligibility', return_value=(True, '')),
                    mock.patch('presale.models.PresaleSettings.get_settings',
                               return_value=SimpleNamespace(is_presale_active=True)),
                    mock.patch('cusd_plus.cusd_vault.require_operational'),
                    mock.patch('presale.bsc_flow._validate_presale_batch')]
        out = self.run_with(patches, lambda: bsc_flow.submit_purchase(
            self.owner, purchase, 0, int(time.time()) + 600, '0x' + '00' * 65))
        self.assertEqual(out['error'], 'bad_intent_signature')

    def test_second_misplaced_or_foreign_cancel_claim_refused(self):
        for calls in self.refused_variants([self.transfer]):
            self.assertEqual(self._submit(calls)['error'], 'claim_cancel_not_allowed', calls)
            self.assertEqual(self.broadcasts, [])


# ── invite create ───────────────────────────────────────────────────────

class InviteCreateCancelClaimTests(_FlowHarness):
    def _submit(self, calls):
        from send import invite_bsc_flow
        invite = SimpleNamespace(pk=10 ** 9, inviter_user_id=self.owner.pk, status='draft', kind='phone',
                                 send_transaction=None, inviter_address=self.owner.wallet,
                                 invitation_id='ab' * 32, amount=5, token_type='CUSD')
        self.validated.clear()
        patches = self.signing(calls, self.owner.wallet) + [
            mock.patch('send.invite_bsc_flow._stored_create_calls', return_value=calls),
            mock.patch('send.bsc_flow._send_step_up', return_value=''),
            mock.patch('send.invite_bsc_flow._validate_create_batch', side_effect=self.record)]
        return self.run_with(patches, lambda: invite_bsc_flow.submit_create(
            self.owner, invite, 0, int(time.time()) + 600, '0x' + '00' * 65))

    def test_trailing_own_cancel_claim_accepted(self):
        base = [self.transfer]
        for calls in (base, base + [self.cancel]):
            # Past the signature check the row CAS fails (no such invite
            # row): the error proves the signature over ALL calls matched.
            self.assertEqual(self._submit(calls)['error'], 'invite_not_pending', calls)
            self.assertEqual(self.validated, [base])

    def test_second_misplaced_or_foreign_cancel_claim_refused(self):
        for calls in self.refused_variants([self.transfer]):
            self.assertEqual(self._submit(calls)['error'], 'claim_cancel_not_allowed', calls)


# ── Comprar (marketplace escrow): the app appends it; the signature decides ──

class MarketplaceCancelClaimTests(_FlowHarness):
    def _submit(self, signed):
        from marketplace import escrow
        order = SimpleNamespace(pk=10 ** 9, status='funded', pending_action='', pending_action_at=None,
                                buyer_address=self.owner.wallet, merchant_address=self.recipient)
        patches = self.signing(signed, self.owner.wallet) + [
            mock.patch('marketplace.escrow.enabled', return_value=True),
            mock.patch('marketplace.escrow.actor_allowed', return_value=True),
            mock.patch('marketplace.escrow.action_calls', return_value=[self.transfer]),
            mock.patch('marketplace.checkout.handover_action', return_value=False)]
        return self.run_with(patches, lambda: escrow.submit_action(
            self.owner, order, 'confirm', 0, int(time.time()) + 600, '0x' + '00' * 65))

    def test_signed_with_and_without_the_trailing_own_cancel_claim(self):
        base = [self.transfer]
        for signed in (base, base + [self.cancel]):
            # Signature matched; the row take then fails (no such order row).
            self.assertEqual(self._submit(signed)['error'], 'action_in_progress', signed)

    def test_second_misplaced_or_foreign_cancel_claim_refused(self):
        for signed in self.refused_variants([self.transfer]):
            self.assertEqual(self._submit(signed)['error'], 'bad_intent_signature', signed)

    def test_a_business_key_never_carries_it(self):
        from smart_account import relay_policy
        self.assertEqual(relay_policy.signed_variants([self.transfer], self.owner, '0x' + '42' * 20),
                         [[self.transfer]])


# ── payment bridge: server-built calls, signed and broadcast as stored ──

class BridgeCancelClaimTests(_FlowHarness):
    def _submit(self, stored, signed):
        from payment_accounts import bridge_execution
        quote = SimpleNamespace(source_token_id='BSC:USDC', source_address=self.owner.wallet,
                                money_flow=None, money_flow_id=None)
        t = SimpleNamespace(pk=5, internal_id='b1', funding_mode='wallet', status='prepared', source_tx_hash='',
                            quote=quote, deadline=int(time.time()) + 600, calls=stored, binding={})
        manager = mock.Mock()
        manager.select_related.return_value.get.return_value = t
        self.broadcasts.clear()
        patches = self.signing(signed, self.owner.wallet) + [
            mock.patch('payment_accounts.bridge_execution.PaymentBridgeTransfer.objects', manager),
            mock.patch('payment_accounts.bridge_execution.check_owner'),
            mock.patch('payment_accounts.bridge_execution.execution_enabled'),
            mock.patch('payment_accounts.bridge_execution.current_provider'),
            mock.patch('payment_accounts.infinia_legacy_fees.require_review'),
            mock.patch('payment_accounts.bridge_execution.chain.require_chain'),
            mock.patch('payment_accounts.bridge_execution._adopt_bsc_batch', return_value=None)]
        owner = SimpleNamespace(user=self.owner)
        return self.run_with(patches, lambda: bridge_execution.submit_bridge(owner, 'b1', '0x' + '00' * 65))

    def test_stored_trailing_cancel_claim_is_signed_and_broadcast(self):
        from payment_accounts.allbridge_next import NextError
        stored = [self.transfer, self.cancel]
        with self.assertRaises(PolicyError):
            self._submit(stored, stored)
        self.assertEqual(self.broadcasts, [stored])
        # A signature without it (or with another account's) is not this batch.
        for signed in ([self.transfer], [self.transfer, self.foreign]):
            with self.assertRaises(NextError):
                self._submit(stored, signed)
        self.assertEqual(self.broadcasts, [])

    def test_prepare_suffix_is_only_the_owners_own_account(self):
        from smart_account import relay_policy
        self.assertEqual(relay_policy.pending_cancel_claim_calls(self.owner, self.owner.wallet), [self.cancel])
        self.assertEqual(relay_policy.pending_cancel_claim_calls(self.owner, '0x' + '42' * 20), [])


@override_settings(CUSD_VAULT_ADDRESS=CUSD)
class SendArmAndCancelClaimTests(_FlowHarness):
    """send/bsc_flow: the fee-referral arm (first) and the cancelClaim (last)
    are both kept."""

    def test_armed_send_with_trailing_cancel_claim(self):
        from cusd_plus import fee_referral
        from send import bsc_flow
        arm = fee_referral.arm_call(fee_referral.ReferralArm(
            referrer_user_id=self.heir.pk, referrer_address='0x' + '3e' * 20, share_bps=5000))
        calls = [arm, self.transfer, self.cancel]
        send_tx = SimpleNamespace(
            id=92, pk=92, sender_user_id=self.owner.pk, sender_business_id=None, status='PENDING',
            recipient_user_id=None, recipient_business_id=None, idempotency_key='', amount=5,
            token_type='CUSD', sender_address=self.owner.wallet, recipient_address=self.recipient,
            bsc_calls_json=json.dumps({'kind': 'send_cusd', 'calls': calls, 'token': CUSD,
                                       'recipient': self.recipient, 'units': str(5 * WAD)}))
        patches = self.signing(calls, self.owner.wallet) + [
            mock.patch('send.bsc_flow._send_step_up', return_value=''),
            mock.patch('send.bsc_flow._send_face_terms', return_value={}),
            mock.patch('send.bsc_flow._validate_send_batch', side_effect=self.record)]
        out = self.run_with(patches, lambda: bsc_flow.submit_bsc_send(
            self.owner, send_tx, 0, int(time.time()) + 600, '0x' + '00' * 65))
        self.assertEqual(out['error'], 'reached_broadcast')
        self.assertEqual(self.validated, [[self.transfer]])
        self.assertEqual(self.broadcasts, [calls])
