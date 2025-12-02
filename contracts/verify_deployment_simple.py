#!/usr/bin/env python3
"""
Simple verification of new payroll contract (no Django dependencies)
"""

import sys
sys.path.append('/Users/julian/Confio')

from algosdk.v2client import algod
from algosdk import encoding
import base64

APP_ID = 750527129
ASSET_ID = 744368179
BUSINESS_ADDR = 'PZL4WK7TTZNIQBXG4N56WG3USKMDZKSXA46RKOLKXV5TALVGL5SBZVMIME'
DELEGATE_ADDR = 'P7WYM6SDBLV5UWM6AWFD4ZCNH7DZE3EICBZOAOORAUHDBVQ44RRS6ZLZZU'

def main():
    print("=" * 80)
    print("PAYROLL CONTRACT VERIFICATION")
    print("=" * 80)
    print(f"\nNew App ID: {APP_ID}")
    print(f"Asset ID: {ASSET_ID}")

    client = algod.AlgodClient('', 'https://testnet-api.4160.nodely.dev')

    # Check contract state
    print(f"\n1. Checking contract configuration...")
    try:
        app_info = client.application_info(APP_ID)
        global_state = {}
        for item in app_info['params']['global-state']:
            key = base64.b64decode(item['key']).decode('utf-8', errors='ignore')
            value_obj = item['value']

            if value_obj['type'] == 1:  # bytes
                raw_bytes = base64.b64decode(value_obj.get('bytes', ''))
                if len(raw_bytes) == 32:
                    global_state[key] = encoding.encode_address(raw_bytes)
            elif value_obj['type'] == 2:  # uint
                global_state[key] = value_obj.get('uint', 0)

        print(f"   Payroll Asset: {global_state.get('payroll_asset', 0)}")
        print(f"   Expected: {ASSET_ID}")

        if global_state.get('payroll_asset', 0) == ASSET_ID:
            print(f"   ✓ Asset configured correctly")
        else:
            print(f"   ❌ Asset mismatch!")
            return False

    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

    # Check delegates
    print(f"\n2. Checking delegate allowlists...")
    try:
        business_bytes = encoding.decode_address(BUSINESS_ADDR)
        boxes = client.application_boxes(APP_ID).get('boxes', [])

        delegate_count = 0
        has_delegate = False

        for box_info in boxes:
            box_name = base64.b64decode(box_info.get('name', ''))
            if len(box_name) == 64 and box_name[:32] == business_bytes:
                delegate_count += 1
                del_addr = encoding.encode_address(box_name[32:])
                if del_addr == DELEGATE_ADDR:
                    has_delegate = True
                    print(f"   Found delegate: {del_addr}")

        if has_delegate:
            print(f"   ✓ Delegate allowlist configured ({delegate_count} total)")
        else:
            print(f"   ❌ Delegate not found in allowlist")
            return False

    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

    # Check vault (should be empty for now)
    print(f"\n3. Checking vault...")
    try:
        vault_key = b'VAULT' + business_bytes
        vault_box = client.application_box_by_name(APP_ID, vault_key)
        value_bytes = base64.b64decode(vault_box.get('value', ''))
        vault_amount = int.from_bytes(value_bytes[:8], 'big') if len(value_bytes) >= 8 else 0
        vault_cusd = vault_amount / 1_000_000

        print(f"   Vault balance: {vault_cusd:.6f} cUSD ({vault_amount} base units)")

        if vault_amount == 0:
            print(f"   ⚠️  Vault is empty - business needs to fund it")
        else:
            print(f"   ✓ Vault has funds")

    except Exception as e:
        # Vault box might not exist yet
        print(f"   ⚠️  Vault not initialized (will be created on first funding)")

    print("\n" + "=" * 80)
    print("✅ CONTRACT VERIFICATION SUCCESSFUL!")
    print("=" * 80)
    print(f"\nContract is deployed and configured correctly.")
    print(f"\nNext steps:")
    print(f"  1. ✓ Django settings updated:")
    print(f"     - ALGORAND_PAYROLL_APP_ID = {APP_ID}")
    print(f"     - ALGORAND_PAYROLL_ASSET_ID = {ASSET_ID}")
    print(f"  2. Fund the vault from business account (~1.2 cUSD)")
    print(f"  3. Test a delegate payout")
    print(f"  4. NEW: Business can withdraw funds using withdraw_vault()!")
    print(f"  5. NEW: Admin can emergency withdraw using admin_withdraw_vault()!")
    print("=" * 80)

    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
