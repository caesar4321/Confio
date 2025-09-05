#!/usr/bin/env python3
import os
import sys
from decimal import Decimal

from algosdk.v2client import algod
from algosdk import account, mnemonic
from algosdk import transaction


def _get_from_django(key: str, default: str | None = None):
    try:
        import django
        from django.conf import settings as dj_settings
        if not os.getenv('DJANGO_SETTINGS_MODULE'):
            os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
        # Ensure Django is set up once
        try:
            django.setup()
        except Exception:
            pass
        return getattr(dj_settings, key, default)
    except Exception:
        return default


def get_algod_client():
    addr = os.getenv('ALGORAND_ALGOD_ADDRESS') or _get_from_django('ALGORAND_ALGOD_ADDRESS') or 'https://mainnet-api.algonode.cloud'
    token = os.getenv('ALGORAND_ALGOD_TOKEN', '') or _get_from_django('ALGORAND_ALGOD_TOKEN', '') or ''
    headers = {
        'User-Agent': 'Confio/asset-tool'
    }
    # If token is present, set header; otherwise, many providers accept empty token.
    if token:
        headers['X-API-Key'] = token
    return algod.AlgodClient(token, addr, headers)


def wait_for_confirmation(client, txid, timeout=20):
    last_round = client.status().get('last-round')
    current_round = last_round
    for _ in range(timeout):
        try:
            pending_txn = client.pending_transaction_info(txid)
        except Exception:
            pending_txn = {}
        if pending_txn.get('confirmed-round', 0) > 0:
            return pending_txn
        current_round += 1
        client.status_after_block(current_round)
    raise TimeoutError(f'Transaction {txid} not confirmed after {timeout} rounds')


def main():
    # Required env vars
    m = os.getenv('ALGORAND_SPONSOR_MNEMONIC') or _get_from_django('ALGORAND_SPONSOR_MNEMONIC')
    if not m:
        print('ALGORAND_SPONSOR_MNEMONIC not set in environment', file=sys.stderr)
        sys.exit(1)
    sponsor_pk = mnemonic.to_private_key(m)
    sponsor_addr = account.address_from_private_key(sponsor_pk)

    unit_name = os.getenv('CONFIO_UNIT_NAME', 'CONFIO')
    asset_name = os.getenv('CONFIO_ASSET_NAME', 'Confío')
    url = os.getenv('CONFIO_ASSET_URL', 'https://confio.lat')
    decimals = int(os.getenv('CONFIO_DECIMALS', '6'))
    total_supply_display = Decimal(os.getenv('CONFIO_TOTAL_SUPPLY', '1000000000'))  # 1B
    total = int(total_supply_display * (10 ** decimals))

    client = get_algod_client()
    params = client.suggested_params()

    print(f'Creating ASA {asset_name} ({unit_name}), total={total}, decimals={decimals}')
    txn = transaction.AssetCreateTxn(
        sender=sponsor_addr,
        sp=params,
        total=total,
        default_frozen=False,
        unit_name=unit_name,
        asset_name=asset_name,
        manager=sponsor_addr,
        reserve=sponsor_addr,
        freeze=sponsor_addr,
        clawback=sponsor_addr,
        url=url,
        decimals=decimals,
    )
    stx = txn.sign(sponsor_pk)
    txid = client.send_transaction(stx)
    ptx = wait_for_confirmation(client, txid, timeout=30)
    asset_id = ptx.get('asset-index') or ptx.get('asset-index', None)
    if not asset_id:
        print('Failed to retrieve asset id from pending tx', file=sys.stderr)
        sys.exit(2)
    print(f'ASA created: asset_id={asset_id}')

    # Immediately lock admin addresses to prevent deletion/reconfig (manager/freeze/clawback to empty)
    params = client.suggested_params()
    cfg = transaction.AssetConfigTxn(
        sender=sponsor_addr,
        sp=params,
        index=asset_id,
        manager="",  # clear manager to disable future destroy/reconfig
        reserve=sponsor_addr,  # keep reserve at sponsor (or set to cold wallet if provided)
        freeze="",
        clawback="",
        strict_empty_address_check=False,
    )
    stx2 = cfg.sign(sponsor_pk)
    txid2 = client.send_transaction(stx2)
    wait_for_confirmation(client, txid2, timeout=30)
    print('Admin addresses locked (manager/freeze/clawback cleared).')

    # Output only the asset id on last line for easy capture
    print(asset_id)


if __name__ == '__main__':
    main()
