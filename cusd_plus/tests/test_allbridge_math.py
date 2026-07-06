"""
Cross-validation of the Python Allbridge quote port (allbridge_math.py)
against the client's TS port on a frozen token-info snapshot.

The vectors were generated with the TS math (itself SDK-validated to
≤ 1 micro-unit) over fixtures/token-info-snapshot.json — the two ports
must agree EXACTLY (both are integer math over the same inputs).

Runs without a database:
    myvenv/bin/python -m cusd_plus.tests.test_allbridge_math
or under the Django runner as a SimpleTestCase.
"""
import json
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase

from cusd_plus.allbridge_math import (
    Side,
    cost_bps,
    max_fill_under_threshold_usd,
    quote_receive_units,
    quote_receive_usd,
)

FIXTURES = Path(__file__).parent / 'fixtures'


def _sides():
    info = json.loads((FIXTURES / 'token-info-snapshot.json').read_text())
    alg = next(t for t in info['ALG']['tokens'] if t['symbol'] == 'USDC')
    bsc = next(t for t in info['BSC']['tokens'] if t['symbol'] == 'USDT')
    return Side.from_token_info(alg), Side.from_token_info(bsc)


def _vectors():
    return json.loads((FIXTURES / 'quote-vectors.json').read_text())


class AllbridgeMathCrossValidation(SimpleTestCase):
    def test_quotes_match_ts_port_exactly(self):
        alg, bsc = _sides()
        for v in _vectors():
            src, dst = (alg, bsc) if v['direction'] == 'alg_to_bsc' else (bsc, alg)
            got = quote_receive_units(int(v['send_units']), src, dst)
            self.assertEqual(
                got, int(v['receive_units']),
                f"{v['direction']} send={v['send_units']}: py={got} ts={v['receive_units']}",
            )

    def test_max_fill_sits_exactly_on_the_threshold_boundary(self):
        alg, bsc = _sides()
        for src, dst in ((alg, bsc), (bsc, alg)):
            for threshold in (Decimal(50), Decimal(100)):
                fill = max_fill_under_threshold_usd(Decimal(100_000), threshold, src, dst)
                if fill > 0:
                    self.assertLessEqual(
                        cost_bps(fill, quote_receive_usd(fill, src, dst)), threshold)
                over = fill + Decimal('0.01')
                self.assertGreater(
                    cost_bps(over, quote_receive_usd(over, src, dst)), threshold)

    def test_zero_and_negative_amounts_quote_zero(self):
        alg, bsc = _sides()
        self.assertEqual(quote_receive_units(0, alg, bsc), 0)
        self.assertEqual(quote_receive_units(-5, alg, bsc), 0)


if __name__ == '__main__':
    # Standalone runner (no Django settings needed for the math itself).
    t = AllbridgeMathCrossValidation()
    t.test_quotes_match_ts_port_exactly()
    t.test_max_fill_sits_exactly_on_the_threshold_boundary()
    t.test_zero_and_negative_amounts_quote_zero()
    print('allbridge_math cross-validation: ALL PASS')
