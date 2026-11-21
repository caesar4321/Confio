"""cUSD+ payout rules: executeRule data abi.encode(destination, usdtOut,
grossCusd) with an EXACT usdtOut (ConfioSmartAccount._runPayout), the gross
search mirroring CusdVault.feeFor/previewRedeem, the gross margin against
the share limit, Pago Móvil for cUSD+ accounts end to end (mocked), and the
small cUSD dust such a payout leaves in a cUSD+ account."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import override_settings
from django.utils import timezone
from eth_abi import decode as abi_decode

from smart_account import abi, assistant_ops, automation, payouts, quotes, schema, services
from smart_account.models import SmartAccountPayout, SmartAccountRule, SmartAccountRuleRun

from .base import CUSD, VAULT, WAD, SmartAccountTestCase, vault_preview
from .test_pagomovil_payouts import DEPOSIT, TX, VE_ON, PagoMovilBase, _reserve_without_sender, quote
from .test_tasks import RelayHarness

AMOUNTS = (Decimal('1'), Decimal('13.37'), Decimal('100'), Decimal('10000'))


class CalldataTests(SmartAccountTestCase):
    A = '0x' + '12' * 20

    def test_plus_payout_data_decodes_against_the_abi(self):
        data = abi.payout_plus_rule_data(self.A, 99 * WAD, 100 * WAD - 1)
        self.assertEqual(len(data), 96)
        dest, usdt_out, gross = abi_decode(['address', 'uint256', 'uint256'], data)
        self.assertEqual((dest.lower(), usdt_out, gross), (self.A, 99 * WAD, 100 * WAD - 1))
        # The cUSD form stays two words (a floor), and is not the cUSD+ one.
        self.assertEqual(len(abi.payout_rule_data(self.A, 7)), 64)
        name, args = abi.decode_call(abi.encode_call('executeRule', 3, data, abi.ZERO_ADDRESS, 0))
        self.assertEqual((name, args[0]), ('executeRule', 3))
        self.assertEqual(abi_decode(['address', 'uint256', 'uint256'], bytes(args[1]))[1:], (99 * WAD, 100 * WAD - 1))


class GrossNetSearchTests(SmartAccountTestCase):
    def test_fee_for_mirrors_the_vault(self):
        preview = vault_preview(90)
        for gross in (0, 1, 111, 10 ** 16 + 1, 13_370_000_000_000_000_001, 10_000 * WAD):
            self.assertEqual(payouts.net_for_gross(gross, 90), preview(gross).net_wei)
        self.assertEqual(payouts.fee_for_wei(1, 90), 1)          # ceil
        self.assertEqual(payouts.fee_for_wei(10 ** 6, 0), 0)

    def test_every_target_is_hit_by_its_smallest_gross(self):
        for bps in (0, 1, 45, 90):
            for target in range(1, 3000):
                gross = payouts.gross_for_net(target, bps)
                self.assertEqual(payouts.net_for_gross(gross, bps), target)
                self.assertLess(payouts.net_for_gross(gross - 1, bps), target)

    def test_exact_exit_for_rule_amounts(self):
        window = (WAD, WAD)
        for amount in AMOUNTS:
            amount_wei = int(amount * WAD)
            for bps in (90, 45, 0):
                out = payouts.plus_payout_exit(amount_wei, bps, window)
                cap = payouts.plus_gross_cap(amount_wei, window)
                # usdtOut == gross - feeFor(gross) EXACTLY, the vault's own preview.
                self.assertEqual(vault_preview(bps)(out.gross_wei).net_wei, out.usdt_wei, (amount, bps))
                self.assertLess(payouts.net_for_gross(out.gross_wei - 1, bps), out.usdt_wei)
                self.assertEqual(out.usdt_wei % payouts.USDT_STEP_WEI, 0)
                # Within the rule and its 5 bps unwrap margin.
                self.assertGreater(out.gross_wei, 0)
                self.assertLessEqual(out.gross_wei, cap)
                self.assertLessEqual(cap + cap * 5 // 10_000, amount_wei)
                self.assertGreater((cap + 1) + (cap + 1) * 5 // 10_000, amount_wei)
                # And close to it: under 5 bps plus a micro-dollar below.
                floor = amount_wei * 10_000 // 10_005 - payouts.USDT_STEP_WEI * 10_000 // (10_000 - bps) - 2
                self.assertGreaterEqual(out.gross_wei, floor, (amount, bps))
        hundred = payouts.plus_payout_exit(100 * WAD, 90, window)
        # 100 / 1.0005 = 99.950024987506246877 gross cap; at 0.9%: 99.050474 USDT.
        self.assertEqual(hundred.usdt_wei, 99_050_474_000_000_000_000)

    def test_a_pinned_target_keeps_its_gross_or_refuses(self):
        first = payouts.plus_payout_exit(50 * WAD, 90, (WAD, WAD))
        again = payouts.plus_payout_exit(50 * WAD, 90, (WAD, WAD + 10 ** 12), target=first.usdt_wei)
        self.assertEqual(again, first)
        with self.assertRaises(payouts.PayoutSkip) as raised:
            payouts.plus_payout_exit(50 * WAD, 90, (WAD, WAD), target=50 * WAD)
        self.assertEqual(raised.exception.code, 'exit_moved')
        with self.assertRaises(payouts.PayoutSkip) as raised:
            payouts.plus_payout_exit(10 ** 9, 90, (WAD, WAD))
        self.assertEqual(raised.exception.code, 'amount_too_small')


class MarginTests(SmartAccountTestCase):
    def test_the_unwrap_fits_the_share_limit_wherever_a_growing_pplus_lands(self):
        for base in (WAD, 1_050_000_000_000_000_000, 1_234_567_890_123_456_789):
            # No growth, a normal inclusion horizon (about a part per
            # million) and an exaggerated one (1%).
            for growth_ppm in (0, 1, 10_000):
                low, high = base, base + base * growth_ppm // 1_000_000
                for amount in AMOUNTS:
                    amount_wei = int(amount * WAD)
                    out = payouts.plus_payout_exit(amount_wei, 90, (low, high))
                    basis = out.gross_wei + out.gross_wei * 5 // 10_000
                    for p in (low, (low + high) // 2, high):
                        limit = quotes.shares_ceil(amount_wei, p)       # executeRule's limit at p
                        shares = quotes.shares_ceil(basis, p)          # _runPayout's unwrap at p
                        self.assertLessEqual(shares, limit, (base, growth_ppm, amount, p))
                        # Never capped: the whole 5 bps margin backs the unwrap.
                        self.assertGreaterEqual(shares * p // WAD, basis)

    def test_the_margin_is_needed(self):
        # A gross equal to the rule amount would ask for more shares than the
        # limit: the unwrap would be capped and come out short.
        amount_wei = 100 * WAD
        p = 1_050_000_000_000_000_000
        basis = amount_wei + amount_wei * 5 // 10_000
        self.assertGreater(quotes.shares_ceil(basis, p), quotes.shares_ceil(amount_wei, p))


@override_settings(**VE_ON)
class PagoMovilPlusTests(PagoMovilBase):
    """A cUSD+ account pays by Pago Móvil: accepted at creation, and the run
    reserves the order for, and the contract sends, the exact usdtOut."""

    def setUp(self):
        super().setUp()
        from ramps import pagoasap_send
        self.fund(CUSD, self.address, 0)
        self.fund(VAULT, self.address, 500 * WAD)
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
        from ramps import ve_send
        reserve, self.reserved = _reserve_without_sender(ve_send.reserve)
        self.target = mock.MagicMock(return_value={
            'deposit_address': DEPOSIT, 'binding': {'provider': 'relay', 'request_id': 'r1', 'response': {},
                                                    'deadline': int(timezone.now().timestamp()) + 900}})
        self.relay = mock.MagicMock(return_value=(SimpleNamespace(signed_tx_hash=TX), True))
        self.window = mock.MagicMock(return_value=(WAD, WAD))
        patches = [
            mock.patch('ramps.ve_send.reserve', side_effect=reserve),
            mock.patch.object(pagoasap_send, 'SHARED_DEPOSIT_TARGET', False),
            mock.patch('ramps.pagoasap_send.quote', return_value=quote()),
            mock.patch('ramps.pagoasap_send.funding_target', self.target),
            mock.patch('ramps.ve_send.current_block', return_value=100),
            mock.patch('cusd_plus.cusd_vault.preview_redeem_wei', side_effect=vault_preview(90)),
            mock.patch('smart_account.quotes.plus_price_window', self.window),
            mock.patch('smart_account.relayer.send_relayer_call', self.relay),
            mock.patch('smart_account.relayer.live_tx', return_value=None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.expected = payouts.plus_payout_exit(50 * WAD, 90, (WAD, WAD))

    def run_rule(self):
        with mock.patch('smart_account.notifications.rule_run'):
            return automation.run_rules()

    def test_prepare_accepts_a_cusd_plus_account(self):
        self.assertEqual(self.rule.token_in.lower(), VAULT)
        self.assertEqual(self.rule.payout_rail, 've_pagomovil')

    def test_run_sends_the_exact_usdt_the_order_waits_for(self):
        from ramps import ve_send
        self.assertEqual(self.run_rule()['sent'], 1)
        name, args = abi.decode_call(self.relay.call_args[0][1])
        self.assertEqual((name, args[0]), ('executeRule', 1))
        data = bytes(args[1])
        self.assertEqual(data, abi.payout_plus_rule_data(DEPOSIT, self.expected.usdt_wei, self.expected.gross_wei))
        dest, usdt_out, gross = abi_decode(['address', 'uint256', 'uint256'], data)
        self.assertEqual(dest.lower(), DEPOSIT)
        self.assertEqual(usdt_out, gross - payouts.fee_for_wei(gross, 90))
        self.assertLessEqual(gross + gross * 5 // 10_000, 50 * WAD)
        ramp = self.ramps().get()
        section = ve_send._section(ramp)
        self.assertEqual((section['deposit_wei'], section['gross_wei']), (str(usdt_out), str(gross)))
        self.assertEqual(section['gross_usd'], '50.00')
        self.assertEqual(self.reserved['funding_sender'], CUSD)   # the USDT still leaves the cUSD vault
        self.assertEqual(SmartAccountPayout.objects.get().status, 'prepared')

    def test_a_retry_pins_the_reserved_usdt_while_the_window_moves(self):
        from smart_account import relayer
        self.relay.side_effect = [relayer.RelayError('nonce'), (SimpleNamespace(signed_tx_hash=TX), True)]
        self.run_rule()
        self.assertEqual(SmartAccountRuleRun.objects.get().status, 'failed')
        self.window.return_value = (WAD, WAD + 3 * 10 ** 12)        # a slightly grown pPlus window
        self.run_rule()
        self.assertEqual(SmartAccountRuleRun.objects.get().status, 'sent')
        self.assertEqual(self.ramps().count(), 1)
        first, second = (bytes(abi.decode_call(c[0][1])[1][1]) for c in self.relay.call_args_list)
        self.assertEqual(first, second)

    def test_a_fee_change_between_reads_skips(self):
        with mock.patch('cusd_plus.cusd_vault.preview_redeem_wei', side_effect=vault_preview(45)):
            self.run_rule()
        run = SmartAccountRuleRun.objects.get()
        self.assertEqual((run.status, run.error), ('skipped', 'provider_unavailable'))
        self.relay.assert_not_called()
        self.assertFalse(self.ramps().exists())

    def ramps(self):
        from ramps.models import RampTransaction
        return RampTransaction.objects.filter(provider='pagoasap')


DUST = 25 * 10 ** 15 + 2      # what a US$50 cUSD+ payout's 5 bps unwrap margin leaves


class DustTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.account = self.make_account(self.owner)
        self.address = self.account.contract_address.lower()
        self.fund(VAULT, self.address, 400 * WAD)
        self.fund(CUSD, self.address, DUST)

    def test_dust_never_flips_the_accounts_dollar(self):
        from cusd_plus.crypto_policy import DOLLAR_PLUS
        from smart_account import assets
        self.assertEqual(assets.held_dollar(self.address), 'cusd_plus')
        # Even for an owner the phone alone would put in cUSD.
        with mock.patch('smart_account.offer.viewer_dollar', return_value='cusd'):
            self.assertEqual(services.account_dollar_token(self.account, self.owner).lower(), VAULT)
        with mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=False):
            self.assertEqual(automation._account_dollar(self.account), DOLLAR_PLUS)
        # A real cUSD balance larger than the shares still is the account's dollar.
        self.fund(CUSD, self.address, 500 * WAD)
        self.assertEqual(assets.held_dollar(self.address), 'cusd')

    def test_listing_shows_dust_as_minor_confio_dollar_inside_the_dollars(self):
        account = schema.Query.resolve_smart_account(None, self.info(self.owner))
        rows = {a.key: a for a in account.assets}
        self.assertEqual(set(rows), {'cusd_plus', 'cusd'})
        self.assertEqual((rows['cusd'].kind, rows['cusd'].name), ('dollar', 'Confío Dollar'))
        self.assertEqual(rows['cusd'].units, str(DUST))
        # The app shows one dollar row valued at dollarsUsd: the dust is in it.
        self.assertEqual(account.dollars_usd, '400.03')
        self.assertEqual(account.total_usd, '400.03')
        # The offer's dollar stays the owner's (eligibility), not the dust's.
        offer = schema.Query.resolve_smart_account_offer(None, self.info(self.owner))
        self.assertEqual(offer.dollar, 'cusd_plus')

    def test_move_out_and_withdraw_take_the_dust(self):
        preview = services.move_preview(self.viewer(self.owner), 'out')
        self.assertIn('cusd', [r['asset'].key for r in preview['rows'] if r['included']])
        batch = services.prepare_withdraw(self.viewer(self.owner), 'cusd', 'max')
        self.assertTrue(batch.calls)

    def test_review_and_monthly_note_count_it(self):
        data = assistant_ops.review(self.owner)
        names = [row['activo'] for row in data['saldos_actuales']]
        self.assertEqual(sorted(names), ['Confío Dollar', 'Confío Dollar+'])
        self.assertEqual(data['total_actual_usd'], '400.03')

    def test_a_payout_rule_still_uses_the_owners_dollar(self):
        from smart_account import offer
        with override_settings(**VE_ON), \
                mock.patch('ramps.ve_send.CONTRACT_FUNDING', True, create=True), \
                mock.patch('payment_accounts.services.require_outgoing_face', return_value='face-key-1'), \
                mock.patch('security.face_step_up.step_up_applies', return_value=True), \
                mock.patch('smart_account.payouts.reference_ves_rate', return_value=Decimal('40')):
            self.assertIn('ve_pagomovil', offer.payout_rails())
            saved = schema.SaveSmartAccountPagoMovilDestination.mutate(
                None, self.info(self.owner), phone='0414 1234567', bank_code='0134', id_number='V12345678',
                holder_name='Ana Pérez')
            services.prepare_payout_rule(self.viewer(self.owner), None, saved.payout_method.payout_method_id,
                                         '50.00', 'monthly')
        self.assertEqual(SmartAccountRule.objects.get().token_in.lower(), VAULT)


class DustFeeTests(RelayHarness):
    def test_dust_counts_toward_the_fee(self):
        shares = 14_980_000_000_000_000_000
        self.fund(VAULT, self.address, shares)
        self.fund(CUSD, self.address, 30 * 10 ** 15)
        self.due(shares + 30 * 10 ** 15, fee=15 * WAD)
        least, most = automation._dollars_window(self.account, automation._billing_state(self.account))
        self.assertEqual(least, shares + 30 * 10 ** 15)
        self.assertEqual(automation.collect_due_fees()['sent'], 1)
        # Without the dust the shares alone are short.
        self.fund(CUSD, self.address, 0)
        least, _ = automation._dollars_window(self.account, automation._billing_state(self.account))
        self.assertLess(least, 15 * WAD)
