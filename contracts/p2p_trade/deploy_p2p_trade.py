#!/usr/bin/env python3
"""
Deploy/Configure P2P Trade Contract (single deploy script)

Builds and deploys the P2P Trade Beaker app, opts it into assets,
and sets the sponsor address. All configuration is enforced here —
no separate configure/update scripts needed.
"""

import os
import sys
import base64
from pathlib import Path

from algosdk import account, mnemonic, logic
from algosdk.v2client import algod
from algosdk.transaction import (
    ApplicationCreateTxn,
    ApplicationCallTxn,
    PaymentTxn,
    OnComplete,
    StateSchema,
    wait_for_confirmation,
    assign_group_id,
)
from algosdk.abi import Method, Returns, Argument
from algosdk.encoding import decode_address

# Allow importing the contract module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from p2p_trade import app as p2p_app


def _load_env_fallback():
    """Load required ALGORAND_* vars from .env if missing in environment.
    This is a minimal parser to avoid external dependencies.
    """
    needed = {
        'ALGORAND_NETWORK',
        'ALGORAND_ALGOD_ADDRESS',
        'ALGORAND_ALGOD_TOKEN',
        'ALGORAND_SPONSOR_ADDRESS',
        'ALGORAND_SPONSOR_MNEMONIC',
        'ALGORAND_ADMIN_MNEMONIC',
        'ALGORAND_CUSD_ASSET_ID',
        'ALGORAND_CONFIO_ASSET_ID',
    }
    missing = [k for k in needed if not os.environ.get(k)]
    if not missing:
        return
    env_path = Path(__file__).resolve().parents[2] / '.env'
    if not env_path.exists():
        return
    try:
        content = env_path.read_text().splitlines()
        for line in content:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            if k in needed and not os.environ.get(k):
                os.environ[k] = v
    except Exception:
        pass


# Network selection
_load_env_fallback()
NETWORK = os.environ.get('ALGORAND_NETWORK', 'testnet')

# Algod endpoint/token
ALGOD_ADDRESS = os.environ.get('ALGORAND_ALGOD_ADDRESS')
ALGOD_TOKEN = os.environ.get('ALGORAND_ALGOD_TOKEN', '')

if not ALGOD_ADDRESS:
    if NETWORK == 'testnet':
        ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
        ALGOD_TOKEN = ""
    elif NETWORK == 'mainnet':
        ALGOD_ADDRESS = "https://mainnet-api.algonode.cloud"
        ALGOD_TOKEN = ""
    else:  # localnet
        ALGOD_ADDRESS = "http://localhost:4001"
        ALGOD_TOKEN = "a" * 64


def _get_admin():
    mn = os.environ.get('ALGORAND_ADMIN_MNEMONIC')
    if not mn and NETWORK == 'localnet':
        try:
            from contracts.config.localnet_accounts import ADMIN_MNEMONIC as LN_ADMIN
            mn = LN_ADMIN
            print("Using LocalNet admin mnemonic from config.")
        except Exception:
            pass
    if not mn:
        raise SystemExit('ALGORAND_ADMIN_MNEMONIC not set')
    sk = mnemonic.to_private_key(mn)
    addr = account.address_from_private_key(sk)
    return addr, sk


def _get_required_sponsor():
    sponsor_addr = os.environ.get('ALGORAND_SPONSOR_ADDRESS', '').strip()
    if not sponsor_addr:
        raise SystemExit('ALGORAND_SPONSOR_ADDRESS not set')
    return sponsor_addr


def _resolve_asset_ids() -> tuple[int, int]:
    cusd = int(os.environ.get('ALGORAND_CUSD_ASSET_ID', '0'))
    confio = int(os.environ.get('ALGORAND_CONFIO_ASSET_ID', '0'))
    if NETWORK == 'localnet':
        if cusd == 0:
            try:
                from contracts.config.localnet_assets import CUSD_ASSET_ID as LN_CUSD
                cusd = LN_CUSD
                print(f"Using LocalNet cUSD asset id from config: {cusd}")
            except Exception:
                pass
        if confio == 0:
            confio = int(os.environ.get('LOCALNET_CONFIO_ASSET_ID', '0'))
            if confio:
                print(f"Using LocalNet CONFIO asset id from env: {confio}")
    if cusd == 0 and confio == 0:
        raise SystemExit('At least one asset (CUSD or CONFIO) must be configured')
    return cusd, confio


def deploy_p2p_trade():
    print(f"Deploying P2P Trade to {NETWORK}...")

    admin_addr, admin_sk = _get_admin()
    sponsor_addr = _get_required_sponsor()
    cusd_id, confio_id = _resolve_asset_ids()

    print(f"Admin:   {admin_addr}")
    print(f"Sponsor: {sponsor_addr}")
    if cusd_id:
        print(f"cUSD:    {cusd_id}")
    if confio_id:
        print(f"CONFIO:  {confio_id}")

    algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

    # Build contract
    print("\nBuilding contract (approval + clear)...")
    spec = p2p_app.build()

    # Compile programs
    ap_comp = algod_client.compile(spec.approval_program)
    approval = base64.b64decode(ap_comp['result'])
    cl_comp = algod_client.compile(spec.clear_program)
    clear = base64.b64decode(cl_comp['result'])
    print(f"Approval size: {len(approval)} bytes | Clear size: {len(clear)} bytes")

    # Create app
    params = algod_client.suggested_params()

    # Compute extra pages if needed
    extra_pages = 0
    if len(approval) > 2048:
        extra_pages = (len(approval) - 2048 + 2047) // 2048
        print(f"Approval requires {extra_pages} extra page(s)")

    # Global integers used (current):
    # - asset ids: cusd_asset_id, confio_asset_id (2)
    # - flags/counters: is_paused, active_trades, active_disputes (3)
    # - volumes: total_cusd_volume, total_confio_volume (2)
    # - trade stats: total_trades_created, completed, cancelled, disputed (4)
    # Total = 11. Provide headroom (12) to avoid schema overflow on future increments.
    global_schema = StateSchema(
        num_uints=12,
        num_byte_slices=3,  # admin, sponsor_address, padding
    )
    local_schema = StateSchema(num_uints=0, num_byte_slices=0)

    # Beaker create() selector
    create_selector = bytes.fromhex('4c5c61ba')  # create()void

    create_txn = ApplicationCreateTxn(
        sender=admin_addr,
        sp=params,
        on_complete=OnComplete.NoOpOC,
        approval_program=approval,
        clear_program=clear,
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=[create_selector],
        extra_pages=extra_pages,
    )

    stx = create_txn.sign(admin_sk)
    try:
        txid = algod_client.send_transaction(stx)
        print(f"Create tx sent: {txid}")
        res = wait_for_confirmation(algod_client, txid, 10)
        app_id = res['application-index']
    except Exception as e:
        print(f"Create failed: {e}")
        raise

    app_addr = logic.get_application_address(app_id)
    print(f"✅ App ID: {app_id}\nApp Address: {app_addr}")

    # Set sponsor address via set_sponsor(address)
    print("\nSetting sponsor address...")
    method = Method(name='set_sponsor', args=[Argument('address', 'sponsor')], returns=Returns('void'))
    params = algod_client.suggested_params()
    set_sp = ApplicationCallTxn(
        sender=admin_addr,
        sp=params,
        index=app_id,
        on_complete=OnComplete.NoOpOC,
        app_args=[method.get_selector(), decode_address(sponsor_addr)],
    )
    txid = algod_client.send_transaction(set_sp.sign(admin_sk))
    wait_for_confirmation(algod_client, txid, 10)
    print("✓ Sponsor set")

    # setup_assets(cusd, confio) with sponsor-funded MBR (0.2 ALGO)
    print("\nOpting app into assets (sponsor-funded)...")
    params = algod_client.suggested_params()
    # Fund base + two opt-ins = 300_000 µALGO
    pay = PaymentTxn(sender=sponsor_addr, sp=params, receiver=app_addr, amt=300_000, note=b'P2P asset setup')

    method = Method(
        name='setup_assets',
        args=[Argument('uint64', 'cusd_id'), Argument('uint64', 'confio_id')],
        returns=Returns('void'),
    )
    params.fee = 2000  # two inner opt-ins
    call = ApplicationCallTxn(
        sender=admin_addr,
        sp=params,
        index=app_id,
        on_complete=OnComplete.NoOpOC,
        app_args=[method.get_selector(), cusd_id.to_bytes(8, 'big'), confio_id.to_bytes(8, 'big')],
        foreign_assets=[aid for aid in (cusd_id, confio_id) if aid],
    )

    grp = [pay, call]
    assign_group_id(grp)
    stx = [grp[0], grp[1]]
    # Sign and send (admin signs call, sponsor signs pay is off-chain; here we only have admin key)
    # For production, sponsor Payment can be sent by ADMIN if sponsor==admin; otherwise expect sponsor mnemonic
    sponsor_mn = os.environ.get('ALGORAND_SPONSOR_MNEMONIC')
    if not sponsor_mn:
        raise SystemExit('ALGORAND_SPONSOR_MNEMONIC not set for setup_assets funding')
    sponsor_sk = mnemonic.to_private_key(sponsor_mn)
    stx[0] = pay.sign(sponsor_sk)
    stx[1] = call.sign(admin_sk)
    txid = algod_client.send_transactions(stx)
    wait_for_confirmation(algod_client, txid, 10)
    print("✓ Asset setup complete")

    # Save deployment info
    out = {
        'network': NETWORK,
        'app_id': app_id,
        'app_address': app_addr,
        'admin_address': admin_addr,
        'sponsor_address': sponsor_addr,
        'cusd_asset_id': cusd_id,
        'confio_asset_id': confio_id,
    }
    out_file = Path(__file__).parent / f'deployment_{NETWORK}.json'
    out_file.write_text(__import__('json').dumps(out, indent=2))
    print(f"\n✅ Deployment info saved to {out_file}")

    # Update .env with ALGORAND_P2P_TRADE_APP_ID
    env_file = Path(__file__).parent.parent.parent / '.env'
    if env_file.exists():
        lines = env_file.read_text().splitlines(True)
        wrote = False
        for i, line in enumerate(lines):
            if line.startswith('ALGORAND_P2P_TRADE_APP_ID='):
                lines[i] = f'ALGORAND_P2P_TRADE_APP_ID={app_id}\n'
                wrote = True
                break
        if not wrote:
            lines.append(f'ALGORAND_P2P_TRADE_APP_ID={app_id}\n')
        env_file.write_text(''.join(lines))
        print("✓ .env updated with ALGORAND_P2P_TRADE_APP_ID")

    print("\n🎉 P2P Trade deployed successfully!")
    return app_id, app_addr


if __name__ == '__main__':
    deploy_p2p_trade()
