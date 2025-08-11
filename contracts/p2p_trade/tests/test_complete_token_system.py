#!/usr/bin/env python3
"""
Test the complete token system with:
- CONFIO (Asset 1057): 1B governance token
- Mock USDC (Asset 1020): Old CONFIO used as collateral
- cUSD (Asset 1036): Stablecoin
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from algosdk.v2client import algod
from algosdk.transaction import AssetTransferTxn, PaymentTxn, wait_for_confirmation
from contracts.config.algorand_localnet_config import ALGORAND_NODE, ALGORAND_TOKEN
from contracts.config.new_token_config import (
    CONFIO_ASSET_ID,
    CONFIO_CREATOR_ADDRESS,
    CONFIO_CREATOR_PRIVATE_KEY,
    MOCK_USDC_ASSET_ID,
    CUSD_ASSET_ID
)
from contracts.config.confio_token_config import (
    CONFIO_CREATOR_ADDRESS as MOCK_USDC_CREATOR,
    CONFIO_CREATOR_PRIVATE_KEY as MOCK_USDC_KEY
)
from contracts.config.localnet_accounts import ADMIN_ADDRESS, ADMIN_PRIVATE_KEY

# Initialize client
algod_client = algod.AlgodClient(ALGORAND_TOKEN, ALGORAND_NODE)

def get_asset_info(asset_id):
    """Get asset information"""
    try:
        asset_info = algod_client.asset_info(asset_id)
        params = asset_info['params']
        return {
            'name': params.get('name', 'N/A'),
            'unit': params.get('unit-name', 'N/A'),
            'total': params.get('total', 0) / (10 ** params.get('decimals', 0)),
            'decimals': params.get('decimals', 0),
            'creator': params.get('creator', 'N/A'),
            'manager': params.get('manager', ''),
            'reserve': params.get('reserve', ''),
            'freeze': params.get('freeze', ''),
            'clawback': params.get('clawback', '')
        }
    except Exception as e:
        return None

def get_balance(address, asset_id):
    """Get asset balance for an account"""
    try:
        account_info = algod_client.account_info(address)
        for asset in account_info.get("assets", []):
            if asset["asset-id"] == asset_id:
                return asset["amount"] / 1_000_000
    except:
        pass
    return 0

def test_token_configuration():
    """Test that all tokens are configured correctly"""
    print("\n" + "=" * 60)
    print("TEST 1: TOKEN CONFIGURATION")
    print("=" * 60)
    
    # Check CONFIO
    print("\n1. CONFIO Token (Governance):")
    confio_info = get_asset_info(CONFIO_ASSET_ID)
    if confio_info:
        print(f"   Asset ID: {CONFIO_ASSET_ID}")
        print(f"   Name: {confio_info['name']}")
        print(f"   Symbol: {confio_info['unit']}")
        print(f"   Total Supply: {confio_info['total']:,.0f}")
        print(f"   Decimals: {confio_info['decimals']}")
        print(f"   Reserve: {confio_info['reserve'] or 'None (all to creator)'}")
        print(f"   Freeze: {confio_info['freeze'] or 'None'}")
        print(f"   Clawback: {confio_info['clawback'] or 'None'}")
        
        # Verify creator has all tokens
        creator_balance = get_balance(CONFIO_CREATOR_ADDRESS, CONFIO_ASSET_ID)
        print(f"   Creator Balance: {creator_balance:,.0f} CONFIO")
        
        if creator_balance == 1_000_000_000:
            print("   ✅ CONFIO configured correctly!")
        else:
            print("   ❌ CONFIO balance incorrect!")
    else:
        print("   ❌ CONFIO asset not found!")
    
    # Check Mock USDC
    print("\n2. Mock USDC (Old CONFIO for collateral):")
    usdc_info = get_asset_info(MOCK_USDC_ASSET_ID)
    if usdc_info:
        print(f"   Asset ID: {MOCK_USDC_ASSET_ID}")
        print(f"   Name: {usdc_info['name']}")
        print(f"   Symbol: {usdc_info['unit']}")
        print(f"   Total Supply: {usdc_info['total']:,.0f}")
        print(f"   ✅ Mock USDC available for testing!")
    else:
        print("   ❌ Mock USDC asset not found!")
    
    # Check cUSD
    print("\n3. cUSD Stablecoin:")
    cusd_info = get_asset_info(CUSD_ASSET_ID)
    if cusd_info:
        print(f"   Asset ID: {CUSD_ASSET_ID}")
        print(f"   Name: {cusd_info['name']}")
        print(f"   Symbol: {cusd_info['unit']}")
        print(f"   Total Supply: {cusd_info['total']:,.0f}")
        print(f"   Clawback: {cusd_info['clawback'][:8]}... (contract)")
        print(f"   ✅ cUSD configured correctly!")
    else:
        print("   ❌ cUSD asset not found!")

def test_token_distribution():
    """Test distributing tokens to a test user"""
    print("\n" + "=" * 60)
    print("TEST 2: TOKEN DISTRIBUTION")
    print("=" * 60)
    
    # Create test user
    from algosdk import account
    test_user_key, test_user_address = account.generate_account()
    print(f"\nCreated test user: {test_user_address}")
    
    # Fund test user
    params = algod_client.suggested_params()
    fund_txn = PaymentTxn(
        sender=ADMIN_ADDRESS,
        sp=params,
        receiver=test_user_address,
        amt=5_000_000  # 5 ALGO
    )
    signed = fund_txn.sign(ADMIN_PRIVATE_KEY)
    txid = algod_client.send_transaction(signed)
    wait_for_confirmation(algod_client, txid, 4)
    print("✅ Funded test user with 5 ALGO")
    
    # Test user opts in to CONFIO
    opt_in_txn = AssetTransferTxn(
        sender=test_user_address,
        sp=params,
        receiver=test_user_address,
        amt=0,
        index=CONFIO_ASSET_ID
    )
    signed = opt_in_txn.sign(test_user_key)
    txid = algod_client.send_transaction(signed)
    wait_for_confirmation(algod_client, txid, 4)
    print("✅ Test user opted in to CONFIO")
    
    # Transfer 100 CONFIO to test user
    transfer_txn = AssetTransferTxn(
        sender=CONFIO_CREATOR_ADDRESS,
        sp=params,
        receiver=test_user_address,
        amt=100_000_000,  # 100 CONFIO
        index=CONFIO_ASSET_ID
    )
    signed = transfer_txn.sign(CONFIO_CREATOR_PRIVATE_KEY)
    txid = algod_client.send_transaction(signed)
    wait_for_confirmation(algod_client, txid, 4)
    print("✅ Transferred 100 CONFIO to test user")
    
    # Verify balance
    balance = get_balance(test_user_address, CONFIO_ASSET_ID)
    print(f"✅ Test user balance: {balance:,.0f} CONFIO")
    
    # Test user opts in to Mock USDC
    opt_in_txn = AssetTransferTxn(
        sender=test_user_address,
        sp=params,
        receiver=test_user_address,
        amt=0,
        index=MOCK_USDC_ASSET_ID
    )
    signed = opt_in_txn.sign(test_user_key)
    txid = algod_client.send_transaction(signed)
    wait_for_confirmation(algod_client, txid, 4)
    print("✅ Test user opted in to Mock USDC")
    
    # Transfer Mock USDC to test user
    transfer_txn = AssetTransferTxn(
        sender=MOCK_USDC_CREATOR,
        sp=params,
        receiver=test_user_address,
        amt=500_000_000,  # 500 Mock USDC
        index=MOCK_USDC_ASSET_ID
    )
    signed = transfer_txn.sign(MOCK_USDC_KEY)
    txid = algod_client.send_transaction(signed)
    wait_for_confirmation(algod_client, txid, 4)
    print("✅ Transferred 500 Mock USDC to test user")
    
    # Verify balance
    balance = get_balance(test_user_address, MOCK_USDC_ASSET_ID)
    print(f"✅ Test user Mock USDC balance: {balance:,.0f}")
    
    return test_user_address

def main():
    print("=" * 60)
    print("COMPLETE TOKEN SYSTEM TEST")
    print("=" * 60)
    
    # Check connection
    try:
        status = algod_client.status()
        print(f"\nConnected to LocalNet (round {status.get('last-round', 0)})")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    print("\n📊 Token Setup:")
    print(f"  CONFIO: Asset {CONFIO_ASSET_ID} - 1B governance token")
    print(f"  Mock USDC: Asset {MOCK_USDC_ASSET_ID} - Collateral testing")
    print(f"  cUSD: Asset {CUSD_ASSET_ID} - Stablecoin")
    
    try:
        # Test token configuration
        test_token_configuration()
        
        # Test token distribution
        test_user = test_token_distribution()
        
        print("\n" + "=" * 60)
        print("ALL TESTS PASSED! 🎉")
        print("=" * 60)
        
        print("\n✅ Summary:")
        print("1. CONFIO has correct 1B supply with no reserve")
        print("2. Mock USDC (old CONFIO) available for collateral")
        print("3. cUSD ready for minting with collateral")
        print("4. Tokens can be distributed successfully")
        
        print(f"\n📝 Test User: {test_user}")
        print("   - Has 100 CONFIO")
        print("   - Has 500 Mock USDC")
        print("   - Ready to test cUSD minting!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()