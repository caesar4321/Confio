#!/usr/bin/env python3
"""
Debug the deployed payroll contract to understand vault key mismatch

This script:
1. Fetches the deployed approval program
2. Analyzes the bytecode to understand vault key construction
3. Checks on-chain boxes to see what vault keys exist
4. Compares with what the transaction builder sends
"""

import os
import sys
import base64
from algosdk.v2client import algod
from algosdk import encoding

# Add parent to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ALGOD_ADDRESS = os.getenv("ALGORAND_ALGOD_ADDRESS", "https://testnet-api.4160.nodely.dev")
ALGOD_TOKEN = os.getenv("ALGORAND_ALGOD_TOKEN", "")
APP_ID = 750067819

def main():
    print("=" * 80)
    print("PAYROLL CONTRACT VAULT KEY DEBUGGING")
    print("=" * 80)

    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

    # Get business address from env
    business_addr = os.getenv("ALGORAND_SPONSOR_ADDRESS")
    if not business_addr:
        print("ERROR: Set ALGORAND_SPONSOR_ADDRESS env var")
        return

    print(f"\nBusiness address: {business_addr}")

    # Calculate expected vault key
    business_bytes = encoding.decode_address(business_addr)
    expected_vault_key = b"VAULT" + business_bytes

    print(f"\nExpected vault key:")
    print(f"  Hex: {expected_vault_key.hex()}")
    print(f"  Length: {len(expected_vault_key)} bytes")
    print(f"  First 10 bytes: {expected_vault_key[:10].hex()}")

    # Fetch all boxes for the app
    print(f"\nFetching boxes for app {APP_ID}...")
    try:
        boxes_response = client.application_boxes(APP_ID)
        boxes = boxes_response.get('boxes', [])
        print(f"Found {len(boxes)} boxes")

        vault_boxes = []
        for box_info in boxes:
            box_name_b64 = box_info.get('name', '')
            box_name = base64.b64decode(box_name_b64)

            # Check if it's a VAULT box
            if box_name.startswith(b"VAULT"):
                vault_boxes.append(box_name)

                # Try to read the value
                try:
                    box_data = client.application_box_by_name(APP_ID, box_name)
                    value_b64 = box_data.get('value', '')
                    value_bytes = base64.b64decode(value_b64) if value_b64 else b''

                    # Parse as uint64
                    vault_amount = int.from_bytes(value_bytes[:8], 'big') if len(value_bytes) >= 8 else 0
                    vault_cusd = vault_amount / 1_000_000

                    # Extract address from key
                    if len(box_name) == 37:  # "VAULT" + 32-byte address
                        addr_bytes = box_name[5:]
                        addr = encoding.encode_address(addr_bytes)
                        match = " ← THIS IS THE BUSINESS!" if addr == business_addr else ""

                        print(f"\n  VAULT box found:{match}")
                        print(f"    Key hex: {box_name.hex()}")
                        print(f"    Address: {addr}")
                        print(f"    Balance: {vault_cusd:.6f} cUSD ({vault_amount} base units)")
                        print(f"    Matches expected: {box_name == expected_vault_key}")
                    else:
                        print(f"\n  VAULT box (unexpected length):")
                        print(f"    Key hex: {box_name.hex()}")
                        print(f"    Length: {len(box_name)} bytes")
                        print(f"    Balance: {vault_cusd:.6f} cUSD")

                except Exception as e:
                    print(f"\n  VAULT box (could not read):")
                    print(f"    Key hex: {box_name.hex()}")
                    print(f"    Error: {e}")

        if not vault_boxes:
            print("\n  No VAULT boxes found!")

        # Show allowlist boxes for context
        print(f"\nAllowlist boxes (first 5):")
        count = 0
        for box_info in boxes:
            if count >= 5:
                break
            box_name_b64 = box_info.get('name', '')
            box_name = base64.b64decode(box_name_b64)

            # Skip VAULT boxes
            if box_name.startswith(b"VAULT"):
                continue

            # Check if it's an allowlist box (64 bytes = 32 + 32)
            if len(box_name) == 64:
                biz_bytes = box_name[:32]
                del_bytes = box_name[32:]
                biz_addr = encoding.encode_address(biz_bytes)
                del_addr = encoding.encode_address(del_bytes)

                match_biz = " ← BUSINESS" if biz_addr == business_addr else ""

                print(f"\n  Allowlist box {count}:{match_biz}")
                print(f"    Business: {biz_addr}")
                print(f"    Delegate: {del_addr}")
                count += 1

    except Exception as e:
        print(f"Error fetching boxes: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 80)
    print("DIAGNOSIS")
    print("=" * 80)
    print("""
If the vault box exists with the business address as expected, but the
transaction is failing with "vault insufficient funds", then the issue is:

1. The contract is reading Txn.accounts[X] where X is not 0, OR
2. The accounts array being sent doesn't have business at index 0, OR
3. The deployed contract has different logic than the source

To fix:
- If accounts[0] is not business, check transaction builder output
- If contract expects different index, we need to redeploy
- Run a test transaction and log the actual Txn.accounts values
""")
    print("=" * 80)

if __name__ == "__main__":
    main()
