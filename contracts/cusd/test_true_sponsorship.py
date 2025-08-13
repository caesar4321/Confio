#!/usr/bin/env python3
"""
Test true sponsorship pattern for cUSD minting
"""

import os
import sys
from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import AssetTransferTxn, ApplicationCallTxn, PaymentTxn
from algosdk.transaction import calculate_group_id, wait_for_confirmation
from algosdk.abi import Method, Returns
from algosdk.logic import get_application_address
import base64

# Configuration
ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
ALGOD_TOKEN = ""
APP_ID = 744192908
CUSD_ASSET_ID = 744192921
USDC_ASSET_ID = 10458941

# Initialize client
algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

def test_sponsorship():
    """Test the true sponsorship pattern"""
    
    # Sponsor account (admin)
    sponsor_mnemonic = "<REDACTED_OLD_COMPROMISED_MNEMONIC>"
    sponsor_private_key = mnemonic.to_private_key(sponsor_mnemonic)
    sponsor_address = account.address_from_private_key(sponsor_private_key)
    
    # Test user account (create new for testing)
    user_private_key, user_address = account.generate_account()
    user_mnemonic = mnemonic.from_private_key(user_private_key)
    
    print("=" * 60)
    print("TRUE SPONSORSHIP PATTERN TEST")
    print("=" * 60)
    print(f"Sponsor: {sponsor_address}")
    print(f"User: {user_address}")
    print(f"App ID: {APP_ID}")
    
    # Get app address
    app_address = get_application_address(APP_ID)
    print(f"App Address: {app_address}")
    
    # Step 1: Fund user with minimum balance only (not for fees)
    print("\n1. Funding user with minimum balance...")
    params = algod_client.suggested_params()
    
    fund_txn = PaymentTxn(
        sender=sponsor_address,
        sp=params,
        receiver=user_address,
        amt=500000  # 0.5 ALGO for min balance and opt-ins
    )
    
    signed_fund = fund_txn.sign(sponsor_private_key)
    tx_id = algod_client.send_transaction(signed_fund)
    wait_for_confirmation(algod_client, tx_id, 4)
    print(f"✅ User funded with 0.5 ALGO")
    
    # Step 2: User opts into USDC
    print("\n2. User opting into USDC...")
    opt_in_params = algod_client.suggested_params()
    
    usdc_optin = AssetTransferTxn(
        sender=user_address,
        sp=opt_in_params,
        receiver=user_address,
        amt=0,
        index=USDC_ASSET_ID
    )
    
    signed_optin = usdc_optin.sign(user_private_key)
    tx_id = algod_client.send_transaction(signed_optin)
    wait_for_confirmation(algod_client, tx_id, 4)
    print(f"✅ User opted into USDC")
    
    # Step 3: Send user some USDC for testing (simulate user having USDC)
    print("\n3. Sending test USDC to user...")
    # For this test, sponsor has USDC
    # In production, user would already have USDC
    
    # First sponsor needs to opt into USDC if not already
    try:
        sponsor_optin = AssetTransferTxn(
            sender=sponsor_address,
            sp=opt_in_params,
            receiver=sponsor_address,
            amt=0,
            index=USDC_ASSET_ID
        )
        signed = sponsor_optin.sign(sponsor_private_key)
        algod_client.send_transaction(signed)
        wait_for_confirmation(algod_client, tx_id, 4)
    except:
        pass  # Already opted in
    
    print("Note: User needs USDC to test. Get testnet USDC from a faucet.")
    
    # Step 4: User opts into the app
    print("\n4. User opting into cUSD app...")
    app_optin_params = algod_client.suggested_params()
    
    # The opt_in method selector for Beaker apps
    opt_in_selector = bytes.fromhex("30c6d58a")  # "opt_in()void"
    
    app_optin = ApplicationCallTxn(
        sender=user_address,
        sp=app_optin_params,
        index=APP_ID,
        on_complete=1,  # OptIn
        app_args=[opt_in_selector]
    )
    
    signed_app_optin = app_optin.sign(user_private_key)
    tx_id = algod_client.send_transaction(signed_app_optin)
    wait_for_confirmation(algod_client, tx_id, 4)
    print(f"✅ User opted into cUSD app")
    
    # Step 5: User opts into cUSD asset
    print("\n5. User opting into cUSD asset...")
    cusd_optin = AssetTransferTxn(
        sender=user_address,
        sp=opt_in_params,
        receiver=user_address,
        amt=0,
        index=CUSD_ASSET_ID
    )
    
    signed_cusd_optin = cusd_optin.sign(user_private_key)
    tx_id = algod_client.send_transaction(signed_cusd_optin)
    wait_for_confirmation(algod_client, tx_id, 4)
    print(f"✅ User opted into cUSD asset")
    
    # Check user balance
    account_info = algod_client.account_info(user_address)
    algo_balance = account_info['amount'] / 1000000
    print(f"\nUser ALGO balance: {algo_balance} ALGO")
    
    print("\n" + "=" * 60)
    print("TEST SETUP COMPLETE")
    print("=" * 60)
    print(f"User address: {user_address}")
    print(f"User mnemonic: {user_mnemonic}")
    print("\nUser is now ready to mint cUSD with true sponsorship!")
    print("User will ONLY sign the USDC transfer, not the app call.")
    print("Sponsor will sign the payment and app call.")
    
    return user_address, user_private_key

if __name__ == "__main__":
    test_sponsorship()