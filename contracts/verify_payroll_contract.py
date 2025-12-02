#!/usr/bin/env python3
"""
Verify the new payroll contract is working correctly
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
django.setup()

from blockchain.payroll_transaction_builder import PayrollTransactionBuilder
from algosdk.v2client import algod
from algosdk import encoding, account
from django.conf import settings
import base64

def main():
    print("=" * 80)
    print("VERIFYING NEW PAYROLL CONTRACT")
    print("=" * 80)

    # Check Django settings
    print(f"\nDjango Settings:")
    print(f"  ALGORAND_PAYROLL_APP_ID: {settings.ALGORAND_PAYROLL_APP_ID}")
    print(f"  ALGORAND_PAYROLL_ASSET_ID: {settings.ALGORAND_PAYROLL_ASSET_ID}")

    expected_app_id = 750524790
    if settings.ALGORAND_PAYROLL_APP_ID != expected_app_id:
        print(f"  ❌ ERROR: App ID should be {expected_app_id}, but is {settings.ALGORAND_PAYROLL_APP_ID}")
        print(f"     Did you restart the Django server?")
        return 1
    else:
        print(f"  ✓ App ID is correct")

    # Check contract state
    client = algod.AlgodClient(
        settings.ALGORAND_ALGOD_TOKEN,
        settings.ALGORAND_ALGOD_ADDRESS
    )

    print(f"\nContract State:")
    try:
        app_info = client.application_info(settings.ALGORAND_PAYROLL_APP_ID)
        global_state = {}
        for item in app_info['params']['global-state']:
            key = base64.b64decode(item['key']).decode('utf-8', errors='ignore')
            value_obj = item['value']

            if value_obj['type'] == 1:  # bytes
                raw_bytes = base64.b64decode(value_obj.get('bytes', ''))
                if len(raw_bytes) == 32:  # Address
                    global_state[key] = encoding.encode_address(raw_bytes)
                else:
                    global_state[key] = raw_bytes
            elif value_obj['type'] == 2:  # uint
                global_state[key] = value_obj.get('uint', 0)

        print(f"  Admin: {global_state.get('admin', 'Not set')}")
        print(f"  Fee Recipient: {global_state.get('fee_recipient', 'Not set')}")
        print(f"  Payroll Asset: {global_state.get('payroll_asset', 0)}")
        print(f"  Paused: {'Yes' if global_state.get('is_paused', 0) == 1 else 'No'}")

        if global_state.get('payroll_asset', 0) != settings.ALGORAND_PAYROLL_ASSET_ID:
            print(f"  ⚠️  Warning: Asset ID mismatch")
        else:
            print(f"  ✓ Contract configured correctly")

    except Exception as e:
        print(f"  ❌ Error reading contract: {e}")
        return 1

    # Check delegate allowlists
    print(f"\nDelegate Allowlists:")
    business_addr = 'PZL4WK7TTZNIQBXG4N56WG3USKMDZKSXA46RKOLKXV5TALVGL5SBZVMIME'
    business_bytes = encoding.decode_address(business_addr)

    try:
        boxes = client.application_boxes(settings.ALGORAND_PAYROLL_APP_ID).get('boxes', [])
        delegate_count = 0
        for box_info in boxes:
            box_name = base64.b64decode(box_info.get('name', ''))
            if len(box_name) == 64 and box_name[:32] == business_bytes:
                del_bytes = box_name[32:]
                del_addr = encoding.encode_address(del_bytes)
                delegate_count += 1
                is_self = " (self)" if del_addr == business_addr else ""
                print(f"  {delegate_count}. {del_addr}{is_self}")

        if delegate_count == 0:
            print(f"  ❌ No delegates found for business {business_addr}")
            return 1
        else:
            print(f"  ✓ {delegate_count} delegates configured")

    except Exception as e:
        print(f"  ❌ Error checking delegates: {e}")
        return 1

    # Test transaction building
    print(f"\nTransaction Building Test:")
    builder = PayrollTransactionBuilder(network=settings.ALGORAND_NETWORK)

    delegate_addr = 'P7WYM6SDBLV5UWM6AWFD4ZCNH7DZE3EICBZOAOORAUHDBVQ44RRS6ZLZZU'
    _, recipient_addr = account.generate_account()

    txn = builder.build_payout_app_call(
        delegate_address=delegate_addr,
        business_address=business_addr,
        recipient_address=recipient_addr,
        net_amount=50000,  # 0.05 cUSD
        payroll_item_id='verification-test-123'
    )

    print(f"  App ID: {txn.index}")
    print(f"  Sender (delegate): {txn.sender}")
    print(f"  Accounts[0] (business): {txn.accounts[0]}")
    print(f"  Accounts[1] (recipient): {txn.accounts[1]}")
    print(f"  Boxes: {len(txn.boxes)}")

    # Verify vault key
    vault_box = [b for b in txn.boxes if (b[1] if isinstance(b, tuple) else b.name).startswith(b'VAULT')][0]
    vault_key = vault_box[1] if isinstance(vault_box, tuple) else vault_box.name
    expected_vault = b'VAULT' + business_bytes

    if vault_key == expected_vault:
        print(f"  ✓ Vault key matches business address")
    else:
        print(f"  ❌ Vault key mismatch!")
        print(f"     Expected: {expected_vault.hex()}")
        print(f"     Got:      {vault_key.hex()}")
        return 1

    # Verify allowlist box
    allowlist_boxes = [b for b in txn.boxes if len((b[1] if isinstance(b, tuple) else b.name)) == 64]
    found_correct_allowlist = False
    for box in allowlist_boxes:
        box_name = box[1] if isinstance(box, tuple) else box.name
        if box_name[:32] == business_bytes and box_name[32:] == encoding.decode_address(delegate_addr):
            found_correct_allowlist = True
            break

    if found_correct_allowlist:
        print(f"  ✓ Allowlist box reference correct")
    else:
        print(f"  ❌ Allowlist box not found in transaction")
        return 1

    if txn.index != expected_app_id:
        print(f"  ❌ Transaction using wrong app ID: {txn.index}")
        return 1
    else:
        print(f"  ✓ Transaction uses correct app ID")

    print("\n" + "=" * 80)
    print("✅ VERIFICATION SUCCESSFUL!")
    print("=" * 80)
    print(f"\nNext steps:")
    print(f"  1. Fund the vault: Business needs to add ~1.2 cUSD to replace old vault")
    print(f"  2. Test a payout: Try a small payout from the delegate account")
    print(f"  3. Monitor: Check that payouts work end-to-end")
    print("=" * 80)

    return 0

if __name__ == "__main__":
    sys.exit(main())
