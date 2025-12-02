#!/usr/bin/env python3
"""
Test payout transaction with dryrun to see exactly what the contract is reading
"""

import os
import sys
# sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
django.setup()

from blockchain.payroll_transaction_builder import PayrollTransactionBuilder
from algosdk.v2client import algod
from algosdk import encoding
import base64
import json

ALGOD_ADDRESS = os.getenv("ALGORAND_ALGOD_ADDRESS", "https://testnet-api.4160.nodely.dev")
ALGOD_TOKEN = os.getenv("ALGORAND_ALGOD_TOKEN", "")

def main():
    # Use the actual addresses
    business_addr = 'PZL4WK7TTZNIQBXG4N56WG3USKMDZKSXA46RKOLKXV5TALVGL5SBZVMIME'
    delegate_addr = 'P7WYM6SDBLV5UWM6AWFD4ZCNH7DZE3EICBZOAOORAUHDBVQ44RRS6ZLZZU'
    # Use a test recipient
    from algosdk import account
    _, recipient_addr = account.generate_account()

    builder = PayrollTransactionBuilder('testnet')
    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

    # Build the transaction
    txn = builder.build_payout_app_call(
        delegate_address=delegate_addr,
        business_address=business_addr,
        recipient_address=recipient_addr,
        net_amount=50000,  # 0.05 cUSD (small amount for testing)
        payroll_item_id='dryrun-test-123'
    )

    print("=" * 80)
    print("DRYRUN TEST - Delegate Payout")
    print("=" * 80)
    print(f"\nTransaction details:")
    print(f"  Sender (delegate): {txn.sender}")
    print(f"  Business (accounts[0]): {txn.accounts[0]}")
    print(f"  Recipient (accounts[1]): {txn.accounts[1]}")
    if len(txn.accounts) > 2:
        print(f"  Fee recipient (accounts[2]): {txn.accounts[2]}")

    # Prepare dryrun request
    from algosdk.v2client.models import DryrunRequest, DryrunSource
    from algosdk import transaction

    # Create a signed transaction (with dummy signature for dryrun)
    signed_txn = transaction.SignedTransaction(txn, bytes(64))

    # Fetch state for dryrun
    print("Fetching state for dryrun...")
    app_info = client.application_info(builder.payroll_app_id)
    biz_info = client.account_info(business_addr)
    del_info = client.account_info(delegate_addr)
    
    # Create dryrun request with state
    drr = DryrunRequest(
        txns=[signed_txn],
        apps=[app_info],
        accounts=[biz_info, del_info]
    )

    try:
        print(f"\nAttempting dryrun...")
        dryrun_result = client.dryrun(drr)

        print(f"\nDryrun result:")
        print(json.dumps(dryrun_result, indent=2, default=str))

        # Check if there are any errors
        if 'txns' in dryrun_result and dryrun_result['txns']:
            for i, txn_result in enumerate(dryrun_result['txns']):
                print(f"\nTransaction {i}:")

                if 'app-call-messages' in txn_result:
                    print("  Messages:")
                    for msg in txn_result['app-call-messages']:
                        print(f"    - {msg}")

                if 'logic-sig-messages' in txn_result:
                    print("  Logic sig messages:")
                    for msg in txn_result['logic-sig-messages']:
                        print(f"    - {msg}")

                if 'app-call-trace' in txn_result:
                    trace = txn_result['app-call-trace']
                    print(f"  Trace available ({len(trace)} steps)")

                    # Find where it fails
                    for step in trace:
                        if 'error' in step:
                            print(f"\n  ERROR at pc={step.get('pc', '?')}: {step['error']}")
                            print(f"    Step: {step}")

    except Exception as e:
        print(f"\nDryrun failed: {e}")
        print(f"Error type: {type(e).__name__}")

        # Try to get more info
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()
