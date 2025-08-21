#!/usr/bin/env python3
"""
Verify P2P Trade deployment and sponsor-funded mark_paid flow.

Checks:
- Reads Algorand app global state and confirms sponsor_address matches .env
- (Optional) Calls your GraphQL backend prepareP2pMarkPaid to verify group shape:
  expects 1 sponsor Payment + 1 buyer AppCall.

Usage:
  python3 contracts/p2p_trade/verify_deploy.py [--app-id APP_ID] [--algod-url URL] [--algod-token TOKEN]
                                              [--graphql-url URL] [--jwt TOKEN] [--trade-id ID]

If flags are omitted, values are pulled from .env in repo root.
"""

import os
import sys
import json
from pathlib import Path
from typing import Optional

def load_env_from_file(root: Path) -> None:
    env_path = root / '.env'
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        if k:
            # Prefer .env over inherited env for Algorand/GraphQL keys
            if k.startswith('ALGORAND_') or k in {'GRAPHQL_URL','GRAPHQL_JWT','VERIFY_TRADE_ID'}:
                os.environ[k] = v
            elif os.environ.get(k) is None:
                os.environ[k] = v

def b32_algorand_address_from_key(pubkey32: bytes) -> Optional[str]:
    """Encode 32-byte public key into Algorand base32 address without algosdk."""
    try:
        if len(pubkey32) != 32:
            return None
        import hashlib, base64
        checksum = hashlib.new('sha512_256', pubkey32).digest()[-4:]
        addr_bytes = pubkey32 + checksum
        return base64.b32encode(addr_bytes).decode('ascii').rstrip('=')
    except Exception:
        return None

def verify_global_state(app_id: int, algod_url: str, algod_token: str) -> bool:
    from base64 import b64decode
    import json
    from urllib.request import Request, urlopen
    from urllib.error import URLError, HTTPError

    url = f"{algod_url.rstrip('/')}/v2/applications/{app_id}"
    headers = {"Accept": "application/json"}
    if algod_token:
        headers["X-Algo-API-Token"] = algod_token
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=20) as resp:
            app_info = json.loads(resp.read().decode('utf-8'))
    except (URLError, HTTPError) as e:
        print("Failed to query Algod:", e)
        return False

    gs = {}
    for kv in ((app_info.get('application') or {}).get('params') or {}).get('global-state', []) or []:
        key = b64decode(kv.get('key', '')).decode('utf-8', errors='ignore')
        val = kv.get('value') or {}
        if 'bytes' in val:
            try:
                raw = b64decode(val['bytes'])
            except Exception:
                raw = b''
            gs[key] = raw
        else:
            gs[key] = val.get('uint')

    sponsor_raw = gs.get('sponsor_address', b'')
    sponsor_addr_onchain = b32_algorand_address_from_key(sponsor_raw) if sponsor_raw else None
    sponsor_env = os.environ.get('ALGORAND_SPONSOR_ADDRESS')
    print(f"Sponsor (env):      {sponsor_env}")
    print(f"Sponsor (on-chain): {sponsor_addr_onchain}")

    ok = bool(sponsor_env and sponsor_addr_onchain and sponsor_env == sponsor_addr_onchain)
    print(f"Sponsor address match: {'OK' if ok else 'FAIL'}")
    return ok

def verify_prepare_mark_paid(graphql_url: str, jwt: str, trade_id: str) -> bool:
    q = {
        "query": "mutation($tradeId:String!,$paymentRef:String!){ prepareP2pMarkPaid(tradeId:$tradeId, paymentRef:$paymentRef){ success error userTransactions sponsorTransactions{txn index} groupId tradeId }}",
        "variables": {"tradeId": str(trade_id), "paymentRef": "verify-test"}
    }
    headers = {"Content-Type": "application/json"}
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"
    data = None
    # Try requests first; fallback to urllib
    try:
        import requests  # type: ignore
        r = requests.post(graphql_url, json=q, headers=headers, timeout=20)
        data = r.json()
    except Exception:
        try:
            from urllib.request import Request, urlopen
            req = Request(graphql_url, data=json.dumps(q).encode('utf-8'), headers=headers)
            with urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            print("GraphQL request failed:", e)
            return False
    res = ((data or {}).get('data') or {}).get('prepareP2pMarkPaid')
    if not res or not res.get('success'):
        print("prepareP2pMarkPaid error:", (res or {}).get('error'), "resp:", data)
        return False
    ut = res.get('userTransactions') or []
    st = res.get('sponsorTransactions') or []
    print(f"userTransactions: {len(ut)} | sponsorTransactions: {len(st)}")
    ok_shape = (len(ut) == 1 and len(st) == 1)
    print(f"Expected shape [sponsor Payment, buyer AppCall]: {'OK' if ok_shape else 'FAIL'}")
    return ok_shape

def main():
    root = Path(__file__).resolve().parents[2]
    load_env_from_file(root)

    app_id = int(os.environ.get('ALGORAND_P2P_TRADE_APP_ID', '0'))
    algod_url = os.environ.get('ALGORAND_ALGOD_ADDRESS', '')
    algod_token = os.environ.get('ALGORAND_ALGOD_TOKEN', '')

    # CLI overrides (very simple)
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == '--app-id' and i+1 < len(args):
            app_id = int(args[i+1])
        if a == '--algod-url' and i+1 < len(args):
            algod_url = args[i+1]
        if a == '--algod-token' and i+1 < len(args):
            algod_token = args[i+1]

    if not (app_id and algod_url is not None):
        print("Missing app id or algod config; set .env or pass flags.")
        sys.exit(1)

    print("\nVerifying global state...")
    ok1 = verify_global_state(app_id, algod_url, algod_token)

    graphql_url = os.environ.get('GRAPHQL_URL', '')
    jwt = os.environ.get('GRAPHQL_JWT', '')
    trade_id = os.environ.get('VERIFY_TRADE_ID', '')

    ok2 = True
    if graphql_url and jwt and trade_id:
        print("\nVerifying prepareP2pMarkPaid group shape via GraphQL...")
        ok2 = verify_prepare_mark_paid(graphql_url, jwt, trade_id)
    else:
        print("\nSkipping GraphQL shape verification (set GRAPHQL_URL, GRAPHQL_JWT, VERIFY_TRADE_ID to enable)")

    print("\nSummary:")
    print(f"  Sponsor global state: {'OK' if ok1 else 'FAIL'}")
    print(f"  Prepare mark_paid:    {'OK' if ok2 else 'SKIPPED/FAIL'}")
    sys.exit(0 if (ok1 and ok2) else 2)

if __name__ == '__main__':
    main()
