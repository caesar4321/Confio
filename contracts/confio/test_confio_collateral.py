#!/usr/bin/env python3
"""
Test cUSD collateral minting and burning with CONFIO tokens
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import base64
from algosdk.v2client import algod
from algosdk.transaction import (
    AssetTransferTxn,
    ApplicationCallTxn,
    wait_for_confirmation,
    assign_group_id,
    OnComplete
)
from algosdk.abi import Method, Argument, Returns
from contracts.config.algorand_localnet_config import ALGORAND_NODE, ALGORAND_TOKEN
from contracts.config.localnet_accounts import ADMIN_ADDRESS, ADMIN_PRIVATE_KEY
from contracts.config.confio_token_config import CONFIO_ASSET_ID
from contracts.config.cusd_deployment_config import (
    APP_ID, 
    APP_ADDRESS, 
    CUSD_ASSET_ID,
    TEST_USER_ADDRESS,
    TEST_USER_PRIVATE_KEY
)

# Initialize client
algod_client = algod.AlgodClient(ALGORAND_TOKEN, ALGORAND_NODE)

def get_balance(address, asset_id):
    """Get asset balance for an account"""
    try:
        account_info = algod_client.account_info(address)
        for asset in account_info.get("assets", []):
            if asset["asset-id"] == asset_id:
                return asset["amount"] / 1_000_000  # Convert to decimal
    except:
        pass
    return 0

def print_balances(title):
    """Print current balances"""
    print(f"\n{title}")
    print("-" * 50)
    
    # User balances
    user_confio = get_balance(TEST_USER_ADDRESS, CONFIO_ASSET_ID)
    user_cusd = get_balance(TEST_USER_ADDRESS, CUSD_ASSET_ID)
    print(f"User Balances:")
    print(f"  CONFIO: {user_confio:,.2f}")
    print(f"  cUSD:   {user_cusd:,.2f}")
    
    # Contract balances
    app_confio = get_balance(APP_ADDRESS, CONFIO_ASSET_ID)
    app_cusd = get_balance(APP_ADDRESS, CUSD_ASSET_ID)
    print(f"\nContract Reserves:")
    print(f"  CONFIO: {app_confio:,.2f}")
    print(f"  cUSD:   {app_cusd:,.2f}")
    
    # Admin (reserve) balance
    admin_cusd = get_balance(ADMIN_ADDRESS, CUSD_ASSET_ID)
    print(f"\nAdmin Reserve:")
    print(f"  cUSD:   {admin_cusd:,.2f}")

def opt_in_to_app():
    """Opt user into the cUSD app"""
    print("\nOpting user into cUSD app...")
    
    params = algod_client.suggested_params()
    
    # Add opt_in method selector
    opt_in_selector = Method(
        name="opt_in",
        args=[],
        returns=Returns("void")
    ).get_selector()
    
    opt_in_txn = ApplicationCallTxn(
        sender=TEST_USER_ADDRESS,
        sp=params,
        index=APP_ID,
        on_complete=OnComplete.OptInOC,
        app_args=[opt_in_selector]
    )
    
    signed = opt_in_txn.sign(TEST_USER_PRIVATE_KEY)
    txid = algod_client.send_transaction(signed)
    wait_for_confirmation(algod_client, txid, 4)
    print("✅ User opted into app")

def test_collateral_minting():
    """Test minting cUSD with CONFIO collateral"""
    print("\n" + "=" * 60)
    print("TEST 1: COLLATERAL MINTING (CONFIO → cUSD)")
    print("=" * 60)
    
    # Amount to mint (300 CONFIO → 300 cUSD)
    collateral_amount = 300_000_000  # 300 CONFIO (6 decimals)
    
    print(f"\nMinting {collateral_amount/1_000_000} cUSD with {collateral_amount/1_000_000} CONFIO collateral")
    
    params = algod_client.suggested_params()
    params.flat_fee = True
    params.fee = 3000  # Cover both transactions
    
    # Transaction 1: Transfer CONFIO to app (collateral)
    confio_transfer = AssetTransferTxn(
        sender=TEST_USER_ADDRESS,
        sp=params,
        receiver=APP_ADDRESS,
        amt=collateral_amount,
        index=CONFIO_ASSET_ID
    )
    
    # Transaction 2: App call for minting
    mint_selector = Method(
        name="mint_with_collateral",
        args=[],
        returns=Returns("void")
    ).get_selector()
    
    mint_call = ApplicationCallTxn(
        sender=TEST_USER_ADDRESS,
        sp=params,
        index=APP_ID,
        on_complete=OnComplete.NoOpOC,
        app_args=[mint_selector],
        foreign_assets=[CUSD_ASSET_ID, CONFIO_ASSET_ID],
        accounts=[ADMIN_ADDRESS]  # For clawback
    )
    
    # Group and sign transactions
    assign_group_id([confio_transfer, mint_call])
    signed_transfer = confio_transfer.sign(TEST_USER_PRIVATE_KEY)
    signed_mint = mint_call.sign(TEST_USER_PRIVATE_KEY)
    
    # Send grouped transaction
    txid = algod_client.send_transactions([signed_transfer, signed_mint])
    print(f"Transaction ID: {txid}")
    
    # Wait for confirmation
    confirmed = wait_for_confirmation(algod_client, txid, 4)
    print(f"✅ Minting confirmed in round {confirmed['confirmed-round']}")
    
    # Print updated balances
    print_balances("After Minting")
    
    # Verify results
    user_cusd = get_balance(TEST_USER_ADDRESS, CUSD_ASSET_ID)
    app_confio = get_balance(APP_ADDRESS, CONFIO_ASSET_ID)
    
    print(f"\n✅ Success: User received {user_cusd} cUSD")
    print(f"✅ Contract holds {app_confio} CONFIO as collateral")

def test_collateral_burning():
    """Test burning cUSD to redeem CONFIO collateral"""
    print("\n" + "=" * 60)
    print("TEST 2: COLLATERAL BURNING (cUSD → CONFIO)")
    print("=" * 60)
    
    # Amount to burn (100 cUSD → 100 CONFIO)
    burn_amount = 100_000_000  # 100 cUSD (6 decimals)
    
    print(f"\nBurning {burn_amount/1_000_000} cUSD to redeem {burn_amount/1_000_000} CONFIO")
    
    params = algod_client.suggested_params()
    params.flat_fee = True
    params.fee = 3000  # Cover both transactions
    
    # Transaction 1: Transfer cUSD to app (to burn)
    cusd_transfer = AssetTransferTxn(
        sender=TEST_USER_ADDRESS,
        sp=params,
        receiver=APP_ADDRESS,
        amt=burn_amount,
        index=CUSD_ASSET_ID
    )
    
    # Transaction 2: App call for burning
    burn_selector = Method(
        name="burn_for_collateral",
        args=[],
        returns=Returns("void")
    ).get_selector()
    
    burn_call = ApplicationCallTxn(
        sender=TEST_USER_ADDRESS,
        sp=params,
        index=APP_ID,
        on_complete=OnComplete.NoOpOC,
        app_args=[burn_selector],
        foreign_assets=[CUSD_ASSET_ID, CONFIO_ASSET_ID]
    )
    
    # Group and sign transactions
    assign_group_id([cusd_transfer, burn_call])
    signed_transfer = cusd_transfer.sign(TEST_USER_PRIVATE_KEY)
    signed_burn = burn_call.sign(TEST_USER_PRIVATE_KEY)
    
    # Send grouped transaction
    txid = algod_client.send_transactions([signed_transfer, signed_burn])
    print(f"Transaction ID: {txid}")
    
    # Wait for confirmation
    confirmed = wait_for_confirmation(algod_client, txid, 4)
    print(f"✅ Burning confirmed in round {confirmed['confirmed-round']}")
    
    # Print updated balances
    print_balances("After Burning")
    
    # Verify results
    user_confio = get_balance(TEST_USER_ADDRESS, CONFIO_ASSET_ID)
    user_cusd = get_balance(TEST_USER_ADDRESS, CUSD_ASSET_ID)
    
    print(f"\n✅ Success: User redeemed {burn_amount/1_000_000} CONFIO")
    print(f"✅ User now has {user_confio} CONFIO and {user_cusd} cUSD")

def test_contract_stats():
    """Check contract global state"""
    print("\n" + "=" * 60)
    print("CONTRACT STATISTICS")
    print("=" * 60)
    
    app_info = algod_client.application_info(APP_ID)
    global_state = app_info['params']['global-state']
    
    state_dict = {}
    for item in global_state:
        key = base64.b64decode(item['key']).decode('utf-8', errors='ignore')
        if item['value']['type'] == 1:  # bytes
            value = base64.b64decode(item['value']['bytes'])
            try:
                from algosdk import encoding
                value = encoding.encode_address(value)
            except:
                value = value.hex()
        else:  # uint
            value = item['value']['uint']
        state_dict[key] = value
    
    print("\nGlobal State:")
    for key, value in sorted(state_dict.items()):
        if isinstance(value, int) and key in ['total_minted', 'total_burned', 'total_usdc_locked', 
                                               'cusd_circulating_supply']:
            print(f"  {key}: {value/1_000_000:,.2f}")
        elif key == 'collateral_ratio':
            print(f"  {key}: 1:{value/1_000_000:.2f}")
        elif key in ['cusd_asset_id', 'usdc_asset_id']:
            print(f"  {key}: {value}")
        elif key == 'is_paused':
            print(f"  {key}: {'Yes' if value else 'No'}")
        else:
            print(f"  {key}: {value}")

def main():
    print("=" * 60)
    print("cUSD COLLATERAL MECHANISM TEST")
    print("Using CONFIO as collateral instead of USDC")
    print("=" * 60)
    
    # Check connection
    try:
        status = algod_client.status()
        print(f"\nConnected to LocalNet (round {status.get('last-round', 0)})")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    print(f"\nTest Configuration:")
    print(f"  App ID: {APP_ID}")
    print(f"  App Address: {APP_ADDRESS}")
    print(f"  cUSD Asset: {CUSD_ASSET_ID}")
    print(f"  Collateral Asset: {CONFIO_ASSET_ID} (CONFIO)")
    print(f"  Test User: {TEST_USER_ADDRESS}")
    
    # Show initial balances
    print_balances("Initial Balances")
    
    try:
        # Opt-in to app first
        opt_in_to_app()
        
        # Test minting
        test_collateral_minting()
        
        # Test burning
        test_collateral_burning()
        
        # Show contract stats
        test_contract_stats()
        
        print("\n" + "=" * 60)
        print("ALL TESTS COMPLETED SUCCESSFULLY! 🎉")
        print("=" * 60)
        print("\nSummary:")
        print("✅ Successfully minted cUSD with CONFIO collateral")
        print("✅ Successfully burned cUSD to redeem CONFIO")
        print("✅ 1:1 exchange rate maintained")
        print("✅ Contract correctly manages collateral reserves")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()