from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, override_settings

from cusd_plus import metrics, vault


VAULT = '0x3C29417eb4314155e63d4C7D4507852b87763Ed1'
WAD = 10 ** 18


@override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT)
class UncollectedYieldEarningsTests(SimpleTestCase):
    def test_values_surplus_at_the_guard_approved_price(self):
        price = 1_025_000_000_000_000_000
        surplus = 4 * WAD

        with (
            mock.patch.object(vault, 'last_oracle_price_wad', return_value=price),
            mock.patch.object(vault, '_call', return_value=surplus) as call,
        ):
            value = vault.uncollected_yield_earnings_usd_wad()

        self.assertEqual(value, surplus * price // WAD)
        call.assert_called_once_with(
            VAULT,
            vault.SEL_SURPLUS_USDY + hex(price)[2:].rjust(64, '0'),
        )

    def test_platform_metrics_expose_uncollected_earnings_and_share(self):
        with (
            mock.patch.object(vault, 'total_supply_shares_raw', return_value=100 * WAD),
            mock.patch.object(vault, 'p_plus_wad', return_value=1_010_000_000_000_000_000),
            mock.patch.object(vault, 'total_owed_usd_wad', return_value=101 * WAD),
            mock.patch.object(vault, 'backing_ratio_bps', return_value=10_010),
            mock.patch.object(vault, 'usdy_reserve_usd', return_value=101.1),
            mock.patch.object(vault, 'apy_split', return_value=(3.55, 3.01)),
            mock.patch.object(
                vault,
                'uncollected_yield_earnings_usd_wad',
                return_value=Decimal('0.10') * WAD,
            ),
            mock.patch.object(vault, 'confio_yield_share_bps', return_value=1500),
            mock.patch.object(vault, 'redeem_blocked_reason', return_value=None),
        ):
            result = metrics.get_cusd_plus_platform_metrics(use_cache=False)

        self.assertEqual(result.uncollected_yield_earnings_usd, Decimal('0.10'))
        self.assertEqual(result.confio_yield_share_bps, 1500)
        self.assertEqual(result.circulating_cusd_plus, Decimal('101'))

    def test_earnings_failure_does_not_hide_vault_health(self):
        with (
            mock.patch.object(vault, 'total_supply_shares_raw', return_value=100 * WAD),
            mock.patch.object(vault, 'p_plus_wad', return_value=WAD),
            mock.patch.object(vault, 'total_owed_usd_wad', return_value=100 * WAD),
            mock.patch.object(vault, 'backing_ratio_bps', return_value=10_000),
            mock.patch.object(vault, 'usdy_reserve_usd', return_value=100),
            mock.patch.object(vault, 'apy_split', return_value=(3.55, 3.01)),
            mock.patch.object(
                vault,
                'uncollected_yield_earnings_usd_wad',
                side_effect=RuntimeError('rpc unavailable'),
            ),
            mock.patch.object(vault, 'redeem_blocked_reason', return_value=None),
        ):
            result = metrics.get_cusd_plus_platform_metrics(use_cache=False)

        self.assertEqual(result.circulating_cusd_plus, Decimal('100'))
        self.assertIsNone(result.uncollected_yield_earnings_usd)
        self.assertIsNone(result.confio_yield_share_bps)
