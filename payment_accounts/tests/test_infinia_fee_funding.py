from unittest import TestCase

from payment_accounts.infinia_fee_funding import funding_plan, net_units
from payment_accounts.infinia_fees import FeePricingError

WAD = 10**18


class FeeFundingTests(TestCase):
    def plan(self, usdt, cusd, budget=10*WAD, fee=125*WAD//100, bps=90):
        return funding_plan(budget=budget, fee=fee, wallet_usdt=usdt,
                            wallet_cusd=cusd, fee_bps=bps)

    def test_cusd_fee_does_not_cross_perimeter(self):
        result = self.plan(0, 10*WAD)
        self.assertEqual(int(result['bridge_units']), net_units(875*WAD//100, 90))
        self.assertEqual(result['fee_mint_gross_units'], '0')

    def test_existing_usdt_and_cusd_need_no_conversion(self):
        result = self.plan(9*WAD, 2*WAD)
        self.assertEqual(int(result['bridge_units']), 875*WAD//100)
        self.assertEqual(result['perimeter_fee_units'], '0')

    def test_usdt_only_wallet_mints_only_the_collector_fee(self):
        result = self.plan(10*WAD, 0)
        minted = int(result['fee_mint_gross_units'])
        self.assertEqual(net_units(minted, 90), 125*WAD//100)
        self.assertEqual(int(result['bridge_units']) + minted, 10*WAD)
        self.assertEqual(result['gross_redeem_units'], '0')

    def test_small_cusd_balance_reduces_fee_mint(self):
        result = self.plan(10*WAD, WAD)
        self.assertEqual(int(result['fee_existing_units']), WAD)
        self.assertEqual(int(result['fee_mint_net_units']), WAD//4)
        self.assertEqual(result['gross_redeem_units'], '0')

    def test_budget_conservation_across_wallet_mixes_and_fee_rates(self):
        for bps in (0, 1, 25, 90):
            for usdt in range(101):
                result = self.plan(usdt*WAD//10, (100-usdt)*WAD//10, bps=bps)
                self.assertEqual(int(result['bridge_units']) + int(result['fee_units'])
                                 + int(result['perimeter_fee_units']), 10*WAD)
                self.assertLessEqual(int(result['wallet_usdt_units']), usdt*WAD//10)
                self.assertLessEqual(int(result['gross_redeem_units'])
                                     + int(result['fee_existing_units']), (100-usdt)*WAD//10)

    def test_insufficient_or_invalid_budgets_fail(self):
        for args in ({'budget': WAD}, {'budget': 11*WAD}, {'fee': 0}, {'bps': 91}):
            with self.subTest(args=args), self.assertRaises(FeePricingError):
                self.plan(10*WAD, 0, **args)
