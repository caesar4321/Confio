from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from cusd_plus import cusd_vault, metrics, vault


VAULT = '0x3C29417eb4314155e63d4C7D4507852b87763Ed1'
WAD = 10 ** 18
CUSD_VAULT = '0x6101cC370635cF2c7f2725EaB010aC407A8d543F'


@override_settings(CUSD_VAULT_ADDRESS=CUSD_VAULT)
class CusdBscPlatformMetricsTests(SimpleTestCase):
    def test_reads_holder_reserve_and_fee_accounting_separately(self):
        with (
            mock.patch.object(cusd_vault, 'total_supply_wei', return_value=100 * WAD),
            mock.patch.object(cusd_vault, 'backing_usdt_wei', return_value=101 * WAD),
            mock.patch.object(cusd_vault, 'current_fee_bps', return_value=90),
            mock.patch.object(
                cusd_vault, 'accrued_entry_fees_wei', return_value=WAD // 2,
            ),
            mock.patch.object(
                cusd_vault, 'accrued_exit_fees_wei', return_value=WAD // 4,
            ),
            mock.patch.object(cusd_vault, 'is_paused', return_value=False),
        ):
            result = metrics.get_cusd_bsc_platform_metrics(use_cache=False)

        self.assertEqual(result.circulating_cusd, Decimal('100'))
        self.assertEqual(result.usdt_reserve_usd, Decimal('101'))
        self.assertEqual(result.backing_ratio_bps, 10_100)
        self.assertEqual(result.fee_bps, 90)
        self.assertEqual(result.fee_pct, Decimal('0.9'))
        self.assertEqual(result.accrued_entry_fees_usd, Decimal('0.5'))
        self.assertEqual(result.accrued_exit_fees_usd, Decimal('0.25'))
        self.assertFalse(result.paused)

    def test_rpc_failure_is_unavailable_not_zero(self):
        with mock.patch.object(
            cusd_vault, 'total_supply_wei', side_effect=RuntimeError('rpc down')
        ):
            result = metrics.get_cusd_bsc_platform_metrics(use_cache=False)

        self.assertEqual(result.source, 'unavailable')
        self.assertIsNone(result.circulating_cusd)
        self.assertIsNone(result.usdt_reserve_usd)
        self.assertIsNone(result.fee_bps)

    def test_fee_rpc_failure_does_not_hide_supply_or_reserve(self):
        with (
            mock.patch.object(cusd_vault, 'total_supply_wei', return_value=10 * WAD),
            mock.patch.object(cusd_vault, 'backing_usdt_wei', return_value=10 * WAD),
            mock.patch.object(
                cusd_vault, 'current_fee_bps', side_effect=RuntimeError('fee rpc down'),
            ),
            mock.patch.object(cusd_vault, 'accrued_entry_fees_wei', return_value=0),
            mock.patch.object(cusd_vault, 'accrued_exit_fees_wei', return_value=0),
            mock.patch.object(cusd_vault, 'is_paused', return_value=False),
        ):
            result = metrics.get_cusd_bsc_platform_metrics(use_cache=False)

        self.assertEqual(result.source, 'bsc')
        self.assertEqual(result.circulating_cusd, Decimal('10'))
        self.assertEqual(result.usdt_reserve_usd, Decimal('10'))
        self.assertIsNone(result.fee_bps)

    def test_admin_dashboard_exposes_cusd_and_shared_conversion_fee(self):
        template = (
            Path(__file__).resolve().parents[2]
            / 'templates/admin/dashboard.html'
        ).read_text()

        self.assertIn('cUSD — BNB Smart Chain payment rail', template)
        self.assertIn('Accrued Entry Fees', template)
        self.assertIn('Accrued Exit Fees', template)
        self.assertIn('Shared cUSD perimeter', template)
        self.assertIn('cusd_bsc_metrics.fee_pct', template)


@override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT)
class UncollectedYieldEarningsTests(SimpleTestCase):
    def tearDown(self):
        cache.delete('cusd_plus_reserve_usd')
        cache.delete('cusd_plus_reserve_usd_last')

    def test_reserve_failure_without_last_known_value_is_unknown_not_zero(self):
        cache.delete('cusd_plus_reserve_usd')
        cache.delete('cusd_plus_reserve_usd_last')
        with (
            mock.patch.object(vault, 'oracle_address', return_value='0xOracle'),
            mock.patch.object(
                vault, 'erc20_balance_raw', side_effect=RuntimeError('rpc down'),
            ),
        ):
            result = vault.usdy_reserve_usd()

        self.assertIsNone(result)

    def test_reserve_failure_preserves_last_known_value(self):
        cache.delete('cusd_plus_reserve_usd')
        cache.set('cusd_plus_reserve_usd_last', 123.45, 60)
        with (
            mock.patch.object(vault, 'oracle_address', return_value='0xOracle'),
            mock.patch.object(
                vault, 'erc20_balance_raw', side_effect=RuntimeError('rpc down'),
            ),
        ):
            result = vault.usdy_reserve_usd()

        self.assertEqual(result, 123.45)

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

    def test_unknown_reserve_does_not_hide_cusd_plus_obligations(self):
        with (
            mock.patch.object(vault, 'total_supply_shares_raw', return_value=100 * WAD),
            mock.patch.object(vault, 'p_plus_wad', return_value=WAD),
            mock.patch.object(vault, 'total_owed_usd_wad', return_value=100 * WAD),
            mock.patch.object(vault, 'backing_ratio_bps', return_value=10_000),
            mock.patch.object(vault, 'usdy_reserve_usd', return_value=None),
            mock.patch.object(vault, 'apy_split', return_value=(3.55, 3.01)),
            mock.patch.object(
                vault, 'uncollected_yield_earnings_usd_wad', return_value=0,
            ),
            mock.patch.object(vault, 'confio_yield_share_bps', return_value=1500),
            mock.patch.object(vault, 'redeem_blocked_reason', return_value=None),
        ):
            result = metrics.get_cusd_plus_platform_metrics(use_cache=False)

        self.assertEqual(result.circulating_cusd_plus, Decimal('100'))
        self.assertIsNone(result.usdy_reserve_usd)
