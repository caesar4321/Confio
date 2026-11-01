"""
Net-APY derivation (cusd_plus/vault.py) against canned ContinuousPriceOracle
responses, plus the keeper's send threshold on that per-second oracle.

The reference vector is the real BSC oracle state read 2026-11-01:
getCurrentAPY 3.75017846%, share 1500 bps.

Runs without a database:
    myvenv/bin/python manage.py test cusd_plus.tests.test_vault_apy
"""
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from cusd_plus import tasks, vault

ORACLE = '0x1B508f3eF4a0c26fE9659eB1011BFb8E5e0c7782'
RATE_ORACLE = '0x2762e65716b93de5e4d736be1062bc02f4c05d06'
VAULT = '0x3C29417eb4314155e63d4C7D4507852b87763Ed1'

APY = 37_501_784_614  # 3.7501784614% at 1e12 precision


def _word(value: int) -> str:
    return hex(value)[2:].rjust(64, '0')


def fake_rpc(apy=APY, yield_share_bps=1500):
    def _rpc(method, params, timeout=12):
        assert method == 'eth_call'
        data = params[0]['data']
        if data.startswith(vault.SEL_YIELD_SHARE):
            return '0x' + _word(yield_share_bps)
        if data.startswith(vault.SEL_CURRENT_APY):
            assert params[0]['to'] == RATE_ORACLE
            return '0x' if apy is None else '0x' + _word(apy)
        raise AssertionError(f'unexpected call {data[:10]}')
    return _rpc


@override_settings(
    CUSD_PLUS_ORACLE_ADDRESS=ORACLE,
    CUSD_PLUS_RATE_ORACLE_ADDRESS=RATE_ORACLE,
    CUSD_PLUS_VAULT_ADDRESS=VAULT,
    CUSD_PLUS_NET_APY_PCT=0.0,
)
class NetApyTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_live_vector_2026_11_01(self):
        """Gross round-trips the published APY; holders keep 85% of it."""
        with mock.patch.object(vault, '_rpc', fake_rpc()):
            daily = vault.usdy_daily_rate()
            gross, net = vault.apy_split()
        self.assertAlmostEqual(daily, 1.0087e-04, places=9)
        self.assertAlmostEqual(gross, 3.7501784614, places=6)
        self.assertAlmostEqual(net, ((1 + 0.85 * daily) ** 365 - 1) * 100, places=6)
        self.assertEqual(round(gross - net, 1), 0.6)

    def test_frozen_oracle_is_an_honest_zero(self):
        with mock.patch.object(vault, '_rpc', fake_rpc()):
            vault.net_apy_pct()
        cache.delete('cusd_plus_apy')
        with mock.patch.object(vault, '_rpc', fake_rpc(apy=0)):
            self.assertEqual(vault.net_apy_pct(), 0.0)

    def test_empty_read_serves_last_known_not_zero(self):
        with mock.patch.object(vault, '_rpc', fake_rpc()):
            good = vault.net_apy_pct()
        cache.delete('cusd_plus_apy')
        with mock.patch.object(vault, '_rpc', fake_rpc(apy=None)):
            self.assertEqual(vault.net_apy_pct(), good)

    def test_node_fault_serves_last_known_not_zero(self):
        with mock.patch.object(vault, '_rpc', fake_rpc()):
            good = vault.net_apy_pct()
        cache.delete('cusd_plus_apy')  # expire the fresh cache only

        def broken(method, params, timeout=12):
            raise RuntimeError('bsc rpc eth_call: header not found')

        with mock.patch.object(vault, '_rpc', broken):
            self.assertEqual(vault.net_apy_pct(), good)

    def test_unwired_oracle_uses_settings_fallback(self):
        with override_settings(CUSD_PLUS_RATE_ORACLE_ADDRESS=None,
                               CUSD_PLUS_NET_APY_PCT=1.25):
            self.assertEqual(vault.net_apy_pct(), 1.25)
            # No made-up gross: the client's fallback gate (gross > 0)
            # keeps the split card on the labeled example copy.
            self.assertEqual(vault.gross_apy_pct(), 0.0)


@override_settings(
    CUSD_PLUS_ORACLE_ADDRESS=ORACLE,
    CUSD_PLUS_VAULT_ADDRESS=VAULT,
    CUSD_PLUS_ACCRUE_ENABLED=True,
)
class KeeperThresholdTests(SimpleTestCase):
    LAST = 1_151_678_470_000_000_000

    def _reads(self, price):
        def call(to, data):
            if data == tasks.SEL_GUARD_TRIPPED:
                return 0
            return self.LAST if data == tasks.SEL_LAST_ORACLE_PRICE else price
        return mock.patch.object(tasks, '_call_uint', call)

    def _run(self, price):
        with self._reads(price), mock.patch(
            'blockchain.evm_kms_signer.get_bsc_sponsor_signer_from_settings',
            side_effect=RuntimeError('no signer in tests'),
        ) as signer:
            return tasks.accrue_vault(), signer

    def test_per_second_movement_sends_nothing(self):
        result, signer = self._run(self.LAST + 10 ** 12)
        self.assertEqual(result, {'skipped': 'below_keeper_step'})
        signer.assert_not_called()

    def test_a_day_of_yield_reaches_the_signer(self):
        result, signer = self._run(self.LAST + self.LAST // 9_000)
        self.assertEqual(result, {'skipped': 'signer_unavailable'})
        signer.assert_called_once()

    def test_price_below_baseline_holds(self):
        result, signer = self._run(self.LAST - 1)
        self.assertEqual(result['skipped'], 'would_trip_guard')
        signer.assert_not_called()
