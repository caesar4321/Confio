#!/usr/bin/env python3
"""
Setup delegate allowlists for the new payroll contract
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algosdk import account, mnemonic, encoding
from algosdk.v2client import algod
from algosdk.atomic_transaction_composer import AccountTransactionSigner
from beaker.client import ApplicationClient
from payroll import app as payroll_app

ALGOD_ADDRESS = os.getenv("ALGORAND_ALGOD_ADDRESS", "https://testnet-api.4160.nodely.dev")
ALGOD_TOKEN = os.getenv("ALGORAND_ALGOD_TOKEN", "")
APP_ID = int(os.getenv("ALGORAND_PAYROLL_APP_ID", "750525296"))

def main():
    # Business account
    business_addr = "PZL4WK7TTZNIQBXG4N56WG3USKMDZKSXA46RKOLKXV5TALVGL5SBZVMIME"

    # Delegates to add (from old contract)
    delegates_to_add = [
        "P7WYM6SDBLV5UWM6AWFD4ZCNH7DZE3EICBZOAOORAUHDBVQ44RRS6ZLZZU",  # delegate
        "PZL4WK7TTZNIQBXG4N56WG3USKMDZKSXA46RKOLKXV5TALVGL5SBZVMIME",  # self
    ]

    # Admin credentials (using sponsor address as admin)
    admin_mn = os.getenv("ALGORAND_ADMIN_MNEMONIC")
    if not admin_mn:
        print("ERROR: Set ALGORAND_ADMIN_MNEMONIC")
        return

    # Normalize mnemonic
    admin_mn = " ".join(admin_mn.strip().split()).lower()
    admin_sk = mnemonic.to_private_key(admin_mn)
    admin_addr = account.address_from_private_key(admin_sk)

    print("=" * 80)
    print("SETTING UP DELEGATE ALLOWLISTS")
    print("=" * 80)
    print(f"\nApp ID: {APP_ID}")
    print(f"Business: {business_addr}")
    print(f"Admin: {admin_addr}")
    print(f"\nDelegates to add ({len(delegates_to_add)}):")
    for i, d in enumerate(delegates_to_add, 1):
        print(f"  {i}. {d}")

    # Create client
    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    signer = AccountTransactionSigner(admin_sk)

    app_client = ApplicationClient(
        client=client,
        app=payroll_app,
        app_id=APP_ID,
        signer=signer
    )

    # Build box references for the delegates
    biz_bytes = encoding.decode_address(business_addr)
    boxes = []
    for delegate in delegates_to_add:
        del_bytes = encoding.decode_address(delegate)
        box_key = biz_bytes + del_bytes
        boxes.append((APP_ID, box_key))

    # Get suggested params and increase fee for multiple box creations
    params = client.suggested_params()
    params.flat_fee = True
    # Base fee + MBR for each box (2500 + 400*64 bytes = 28,100 microalgos per box)
    params.fee = params.min_fee * (2 + len(delegates_to_add) * 30)

    print(f"\nCalling set_business_delegates...")
    print(f"  Fee: {params.fee / 1_000_000:.6f} ALGO")
    print(f"  Box references: {len(boxes)}")

    try:
        result = app_client.call(
            "set_business_delegates",
            business_account=business_addr,
            add=delegates_to_add,
            remove=[],
            boxes=boxes,
            suggested_params=params
        )

        print(f"\n✅ Delegates added successfully!")
        print(f"   Transaction ID: {result.tx_id}")

        # Verify by checking boxes
        print(f"\nVerifying allowlist boxes...")
        for delegate in delegates_to_add:
            biz_bytes = encoding.decode_address(business_addr)
            del_bytes = encoding.decode_address(delegate)
            box_key = biz_bytes + del_bytes

            try:
                box_data = client.application_box_by_name(APP_ID, box_key)
                print(f"  ✓ {delegate[:10]}...{delegate[-10:]}")
            except Exception as e:
                print(f"  ✗ {delegate[:10]}...{delegate[-10:]} - ERROR: {e}")

    except Exception as e:
        print(f"\n❌ Error adding delegates: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print("\n" + "=" * 80)
    print("DELEGATE SETUP COMPLETE")
    print("=" * 80)
    return 0

if __name__ == "__main__":
    sys.exit(main())
