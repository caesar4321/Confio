"""
Net-APY derivation (cusd_plus/vault.py) against canned RWADynamicOracle
responses — the math must mirror the vault's accrue() exactly: the oracle
price steps once per UTC day by dailyInterestRate (RAY), and pPlus keeps
(1 − CONFIO_YIELD_SHARE) of each step.

The reference vector is the real BSC oracle state read 2026-07-10:
dailyInterestRate 1.00009558e27, share 1500 bps → net APY ≈ 3.0097%.

Runs without a database:
    myvenv/bin/python manage.py test cusd_plus.tests.test_vault_apy
"""
import time
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from cusd_plus import vault

ORACLE = '0x8aaa843b848c2E3c83956Bc09aFBE4D9Dcf297b7'
VAULT = '0x3C29417eb4314155e63d4C7D4507852b87763Ed1'

DAILY_IR = 1_000_095_580_000_000_000_000_000_000  # 1.00009558 RAY
NOW = int(time.time())


def _word(value: int) -> str:
    return hex(value)[2:].rjust(64, '0')


def _range_words(start: int, end: int, daily_ir: int) -> str:
    return '0x' + _word(start) + _word(end) + _word(daily_ir) + _word(10 ** 18)


def fake_rpc(ranges, yield_share_bps=1500):
    """An eth_call-only _rpc double serving ranges(i) + the vault share."""
    def _rpc(method, params, timeout=12):
        assert method == 'eth_call'
        data = params[0]['data']
        if data.startswith(vault.SEL_YIELD_SHARE):
            return '0x' + _word(yield_share_bps)
        if data.startswith(vault.SEL_RANGES):
            idx = int(data[len(vault.SEL_RANGES):], 16)
            if idx >= len(ranges):
                raise RuntimeError('bsc rpc eth_call: execution reverted')
            return ranges[idx]
        raise AssertionError(f'unexpected call {data[:10]}')
    return _rpc


@override_settings(
    CUSD_PLUS_ORACLE_ADDRESS=ORACLE,
    CUSD_PLUS_VAULT_ADDRESS=VAULT,
    CUSD_PLUS_NET_APY_PCT=0.0,
)
class NetApyTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_live_vector_2026_07_10(self):
        """Real oracle state: 1.00009558 daily × 85% kept ≈ 3.0097% net."""
        ranges = [
            _range_words(NOW - 20 * 86400, NOW - 10 * 86400, DAILY_IR),
            _range_words(NOW - 10 * 86400, NOW + 20 * 86400, DAILY_IR),
        ]
        with mock.patch.object(vault, '_rpc', fake_rpc(ranges)):
            daily = vault.usdy_daily_rate()
            gross, net = vault.apy_split()
        self.assertAlmostEqual(daily, 9.558e-05, places=9)
        self.assertAlmostEqual(gross, ((1 + 9.558e-05) ** 365 - 1) * 100, places=6)
        expected = ((1 + 0.85 * 9.558e-05) ** 365 - 1) * 100
        self.assertAlmostEqual(net, expected, places=6)
        # The user-visible rounding (maximumFractionDigits: 1): the split
        # card reads ~3.6% gross / ~0.5% fee / ~3% net (gross 3.55006 sits
        # just past the .05 rounding boundary).
        self.assertEqual(round(gross, 1), 3.6)
        self.assertEqual(round(gross - net, 1), 0.5)
        self.assertEqual(round(net, 1), 3.0)

    def test_current_range_wins_over_older(self):
        """Rate must come from the range covering NOW, not an older one."""
        old_ir = 1_000_200_000_000_000_000_000_000_000
        ranges = [
            _range_words(NOW - 20 * 86400, NOW - 10 * 86400, old_ir),
            _range_words(NOW - 10 * 86400, NOW + 20 * 86400, DAILY_IR),
        ]
        with mock.patch.object(vault, '_rpc', fake_rpc(ranges)):
            self.assertAlmostEqual(vault.usdy_daily_rate(), 9.558e-05, places=9)

    def test_past_last_range_is_flat(self):
        """Past every posted range the oracle price is flat: honest 0%."""
        ranges = [_range_words(NOW - 20 * 86400, NOW - 10 * 86400, DAILY_IR)]
        with mock.patch.object(vault, '_rpc', fake_rpc(ranges)):
            self.assertEqual(vault.usdy_daily_rate(), 0.0)
            self.assertEqual(vault.net_apy_pct(), 0.0)

    def test_node_fault_serves_last_known_not_zero(self):
        """A mid-walk node error must not be read as end-of-array."""
        ranges = [_range_words(NOW - 10 * 86400, NOW + 20 * 86400, DAILY_IR)]
        with mock.patch.object(vault, '_rpc', fake_rpc(ranges)):
            good = vault.net_apy_pct()
        cache.delete('cusd_plus_apy')  # expire the fresh cache only

        def broken(method, params, timeout=12):
            raise RuntimeError('bsc rpc eth_call: header not found')

        with mock.patch.object(vault, '_rpc', broken):
            self.assertEqual(vault.net_apy_pct(), good)

    def test_unwired_oracle_uses_settings_fallback(self):
        with override_settings(CUSD_PLUS_ORACLE_ADDRESS=None,
                               CUSD_PLUS_NET_APY_PCT=1.25):
            self.assertEqual(vault.net_apy_pct(), 1.25)
            # No made-up gross: the client's fallback gate (gross > 0)
            # keeps the split card on the labeled example copy.
            self.assertEqual(vault.gross_apy_pct(), 0.0)
