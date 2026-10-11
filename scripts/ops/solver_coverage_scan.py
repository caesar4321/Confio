"""Read-only scan: which Ondo GM tokens on BSC can a self-custody wallet buy AND sell
through intent/solver venues right now, and at what round-trip cost.

For every token in cusd_plus/gm_tokens.json it asks CoW Protocol (a multi-solver
auction) for a $100 USDT->token quote, then quotes selling that amount back.
Tokens CoW cannot quote are retried on KyberSwap and LI.FI. No keys, no signing,
no transactions.

    myvenv/bin/python scripts/ops/solver_coverage_scan.py [label]

Writes accounting-local/solver-coverage/<UTC timestamp>_<label>.json (git-excluded).
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

USDT = '0x55d398326f99059fF775485246999027B3197955'
PROBE = '0x000000000000000000000000000000000000dEaD'
NOTIONAL = 100 * 10**18
COW = 'https://api.cow.fi/bnb/api/v1/quote'
KYBER = 'https://aggregator-api.kyberswap.com/bsc/api/v1/routes'
LIFI = 'https://li.quest/v1/quote'
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / 'accounting-local' / 'solver-coverage'


def cow(sell, buy, amount):
    body = {'sellToken': sell, 'buyToken': buy, 'from': PROBE, 'sellAmountBeforeFee': str(amount),
            'kind': 'sell', 'appData': '{}', 'signingScheme': 'eip712'}
    for attempt in range(4):
        r = requests.post(COW, json=body, timeout=30)
        if r.status_code == 429:
            time.sleep(2 + attempt * 2)
            continue
        if r.status_code == 200:
            return int(r.json()['quote']['buyAmount']), None
        return None, r.json().get('errorType', str(r.status_code))
    return None, 'rate_limited'


def kyber(sell, buy, amount):
    r = requests.get(KYBER, params={'tokenIn': sell, 'tokenOut': buy, 'amountIn': str(amount)},
                     headers={'x-client-id': 'confio-coverage-scan'}, timeout=30)
    data = r.json().get('data') if r.status_code == 200 else None
    if not data or not data.get('routeSummary'):
        return None, f'kyber_{r.status_code}'
    return int(data['routeSummary']['amountOut']), None


def lifi(sell, buy, amount):
    r = requests.get(LIFI, params={'fromChain': 56, 'toChain': 56, 'fromToken': sell, 'toToken': buy,
                                   'fromAmount': str(amount), 'fromAddress': PROBE}, timeout=30)
    if r.status_code != 200:
        return None, f'lifi_{r.status_code}'
    return int(r.json()['estimate']['toAmount']), None


def round_trip(venue, token):
    got, err = venue(USDT, token, NOTIONAL)
    if got is None:
        return None, f'buy:{err}'
    back, err = venue(token, USDT, got)
    if back is None:
        return None, f'sell:{err}'
    return round((NOTIONAL - back) * 10_000 / NOTIONAL, 1), None


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else 'scan'
    tokens = json.loads((ROOT / 'cusd_plus' / 'gm_tokens.json').read_text())
    started = datetime.now(timezone.utc)
    results = {}
    lifi_blocked = False
    for i, (symbol, meta) in enumerate(sorted(tokens.items()), 1):
        addr = meta['address']
        row = {}
        row['cow_bps'], row['cow_err'] = round_trip(cow, addr)
        if row['cow_bps'] is None:
            row['kyber_bps'], row['kyber_err'] = round_trip(kyber, addr)
            if not lifi_blocked:
                row['lifi_bps'], row['lifi_err'] = round_trip(lifi, addr)
                if row['lifi_err'] and '429' in row['lifi_err']:
                    lifi_blocked = True
        # Above 300 bps a "route" is a junk pool, not a market (Kyber returns -90% routes).
        venues = {k[:-4]: v for k, v in row.items() if k.endswith('_bps') and v is not None and v <= 300}
        row['best'] = min(venues.items(), key=lambda kv: kv[1]) if venues else None
        results[symbol] = row
        if i % 25 == 0:
            done = sum(1 for r in results.values() if r['best'])
            print(f'{i}/{len(tokens)} scanned, {done} tradable both ways', flush=True)
        time.sleep(0.3)

    tradable = {s: r for s, r in results.items() if r['best']}
    bps = sorted(r['best'][1] for r in tradable.values())
    summary = {
        'label': label, 'started_utc': started.isoformat(), 'finished_utc': datetime.now(timezone.utc).isoformat(),
        'tokens': len(results), 'tradable_both_ways': len(tradable),
        'by_venue': {v: sum(1 for r in tradable.values() if r['best'][0] == v) for v in ('cow', 'kyber', 'lifi')},
        'round_trip_bps_median': bps[len(bps) // 2] if bps else None,
        'round_trip_bps_p90': bps[int(len(bps) * 0.9)] if bps else None,
        'under_50bps': sum(1 for b in bps if b < 50), 'under_100bps': sum(1 for b in bps if b < 100),
        'cow_errors': {e: sum(1 for r in results.values() if r['cow_err'] and r['cow_err'].endswith(e))
                       for e in {(r['cow_err'] or '').split(':')[-1] for r in results.values() if r['cow_err']}},
        'lifi_rate_limited': lifi_blocked,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f'{started.strftime("%Y%m%dT%H%MZ")}_{label}.json'
    out.write_text(json.dumps({'summary': summary, 'results': results}, indent=1))
    print(json.dumps(summary, indent=1))
    print(f'saved {out}')


if __name__ == '__main__':
    main()
