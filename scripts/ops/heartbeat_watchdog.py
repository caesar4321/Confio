#!/usr/bin/env python3
"""Outside watchdog for the ConfioHeartbeat (run hourly by GitHub Actions).

Independent of Confío's own servers: if the whole backend is down, its
Celery monitor is down too, and this is what still pages the team. Reads
lastBeat()/silenceRequired() and the latest block straight from public BSC
RPCs, and posts to the ops Telegram group when the heartbeat is stale.

Env: CONFIO_HEARTBEAT_ADDRESS (empty = skip), OPS_ALERT_TELEGRAM_BOT_TOKEN,
OPS_ALERT_TELEGRAM_CHAT_ID, STALE_AFTER_HOURS (default 26).
Stdlib only. Never prints the token (this repository is public).
"""
import json
import os
import sys
import urllib.request

# Several public RPCs sit behind Cloudflare and 403 Python's default agent.
UA = 'confio-heartbeat-watchdog/1.0'

RPCS = [
    'https://bsc-dataseed.bnbchain.org',
    'https://bsc-rpc.publicnode.com',
    'https://bsc-dataseed1.defibit.io',
    'https://bsc.drpc.org',
    'https://1rpc.io/bnb',
]
# keccak is not in the stdlib, so selectors are pinned here and checked
# against keccak by cusd_plus/tests/test_confio_heartbeat.py.
SELECTORS = {
    'lastBeat()': '0xd3a7b7d3',
    'silenceRequired()': '0x0bada076',
}


def _selector(sig: str) -> str:
    return SELECTORS[sig]

# Test hook: comma-separated RPC URLs (e.g. a local anvil) replace the pool.
if os.environ.get('WATCHDOG_RPCS'):
    RPCS = [u.strip() for u in os.environ['WATCHDOG_RPCS'].split(',') if u.strip()]


def rpc(method, params):
    last = None
    for url in RPCS:
        try:
            req = urllib.request.Request(
                url, data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}).encode(),
                headers={'Content-Type': 'application/json', 'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.load(resp)
            if 'error' in body:
                raise RuntimeError(body['error'])
            return body['result']
        except Exception as exc:  # noqa: BLE001 — try the next endpoint
            last = exc
    raise RuntimeError(f'all BSC RPCs failed: {last}')


def telegram(text):
    token = os.environ.get('OPS_ALERT_TELEGRAM_BOT_TOKEN', '')
    chat = os.environ.get('OPS_ALERT_TELEGRAM_CHAT_ID', '')
    if not token or not chat:
        print('::error::Telegram secrets missing; alert not delivered:', text)
        return False
    req = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/sendMessage',
        data=json.dumps({'chat_id': chat, 'text': text, 'disable_web_page_preview': True}).encode(),
        headers={'Content-Type': 'application/json', 'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp).get('ok') is True
    except Exception as exc:  # noqa: BLE001
        print('::error::Telegram send failed:', type(exc).__name__)
        return False


def main() -> int:
    if os.environ.get('TEST_ALERT', '').lower() == 'true':
        ok = telegram('🧪 Prueba: el vigilante externo (GitHub Actions) puede alertar. Ignorar.')
        print('test alert delivered' if ok else '::error::test alert not delivered')
        return 0 if ok else 1
    hb = os.environ.get('CONFIO_HEARTBEAT_ADDRESS', '').strip()
    if not hb:
        print('CONFIO_HEARTBEAT_ADDRESS not set; nothing to watch.')
        return 0
    stale_after = float(os.environ.get('STALE_AFTER_HOURS') or 26) * 3600
    try:
        block = rpc('eth_getBlockByNumber', ['latest', False])
        tag, now = block['number'], int(block['timestamp'], 16)
        last = int(rpc('eth_call', [{'to': hb, 'data': _selector('lastBeat()')}, tag]), 16)
        silence = int(rpc('eth_call', [{'to': hb, 'data': _selector('silenceRequired()')}, tag]), 16)
    except Exception as exc:  # noqa: BLE001
        telegram(f'🟠 Heartbeat watchdog (GitHub Actions) cannot read BSC: {exc}')
        print('::error::chain read failed:', exc)
        return 1
    age = now - last
    print(f'last beat {age / 3600:.1f}h ago, silenceRequired {silence / 86400:.1f}d')
    if not last or not silence or age > stale_after:
        opens_in = ((last + silence) - now) / 3600 if last and silence else 0.0
        telegram(
            f'🚨 [watchdog] Confío heartbeat STALE: no beat on chain for {age / 3600:.1f}h.\n'
            f'Salida de emergencia opens for EVERY user (frozen accounts included) in {opens_in:.1f}h '
            f'unless beat() lands. Contract {hb}')
        print('::error::heartbeat stale')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
