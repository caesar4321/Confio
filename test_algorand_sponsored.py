#!/usr/bin/env python
"""
Test script for Algorand sponsored transactions
"""
import os
import sys
import django
import asyncio
from decimal import Decimal

# Setup Django
sys.path.append('/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_sponsor_service import algorand_sponsor_service
from blockchain.algorand_account_manager import AlgorandAccountManager
from algosdk import account, mnemonic
from algosdk.v2client import algod
import json


async def test_sponsor_service():
    """Test the sponsor service setup and health"""
    print("\n=== Testing Algorand Sponsor Service ===\n")
    
    # 1. Check sponsor health
    print("1. Checking sponsor health...")
    health = await algorand_sponsor_service.check_sponsor_health()
    print(f"Sponsor Health: {json.dumps(health, indent=2, default=str)}")
    
    if not health['healthy']:
        print("\n⚠️  Sponsor account is not healthy. Setting up sponsor account...")
        await setup_sponsor_account()
        # Re-check health
        health = await algorand_sponsor_service.check_sponsor_health()
        print(f"Updated Health: {json.dumps(health, indent=2, default=str)}")
    
    # 2. Estimate sponsorship costs
    print("\n2. Estimating sponsorship costs...")
    for tx_type in ['transfer', 'opt_in', 'swap']:
        estimate = await algorand_sponsor_service.estimate_sponsorship_cost(tx_type, {})
        print(f"{tx_type}: {estimate['estimated_fee_algo']} ALGO")
    
    return health['healthy']


async def setup_sponsor_account():
    """Setup sponsor account if not configured"""
    print("\n=== Setting up Sponsor Account ===\n")
    
    # Check if sponsor is already configured
    sponsor_address = os.environ.get('ALGORAND_SPONSOR_ADDRESS')
    if sponsor_address:
        print(f"Sponsor already configured: {sponsor_address}")
        return sponsor_address
    
    # Create new sponsor account
    private_key, address = account.generate_account()
    mnemonic_phrase = mnemonic.from_private_key(private_key)
    
    print(f"Created new sponsor account:")
    print(f"Address: {address}")
    print(f"Mnemonic: {mnemonic_phrase}")
    
    # Save to .env.algorand file
    env_file = '/Users/julian/Confio/.env.algorand'
    with open(env_file, 'a') as f:
        f.write(f"\n# Sponsor Account (created by test script)\n")
        f.write(f"ALGORAND_SPONSOR_ADDRESS={address}\n")
        f.write(f"ALGORAND_SPONSOR_MNEMONIC={mnemonic_phrase}\n")
    
    print(f"\n✅ Sponsor account saved to {env_file}")
    print(f"\n⚠️  IMPORTANT: Fund this account with at least 1 ALGO on testnet:")
    print(f"https://testnet.algoexplorer.io/dispenser")
    print(f"Address to fund: {address}")
    
    # Update environment
    os.environ['ALGORAND_SPONSOR_ADDRESS'] = address
    os.environ['ALGORAND_SPONSOR_MNEMONIC'] = mnemonic_phrase
    
    return address


async def test_sponsored_send():
    """Test a sponsored send transaction"""
    print("\n=== Testing Sponsored Send ===\n")
    
    # Create test accounts
    sender_private_key, sender_address = account.generate_account()
    recipient_private_key, recipient_address = account.generate_account()
    
    print(f"Test Sender: {sender_address}")
    print(f"Test Recipient: {recipient_address}")
    
    # Create sponsored ALGO transfer
    print("\n1. Creating sponsored ALGO transfer...")
    result = await algorand_sponsor_service.create_and_submit_sponsored_transfer(
        sender=sender_address,
        recipient=recipient_address,
        amount=Decimal('0.1'),  # 0.1 ALGO
        asset_id=None,  # Native ALGO
        note="Test sponsored transfer"
    )
    
    if result['success']:
        print(f"✅ Sponsored transaction created successfully!")
        print(f"   Group ID: {result['group_id']}")
        print(f"   Total Fee: {result['total_fee']} microAlgos")
        print(f"   Fee in ALGO: {result['fee_in_algo']}")
        print("\n   User Transaction: Ready for signing")
        print("   Sponsor Transaction: Already signed")
        
        # Note: In production, the user would sign their transaction
        # Here we're just demonstrating the structure
        
    else:
        print(f"❌ Failed to create sponsored transaction: {result['error']}")
    
    return result


async def test_asset_sponsored_send():
    """Test a sponsored ASA (CONFIO/USDC) transfer"""
    print("\n=== Testing Sponsored Asset Transfer ===\n")
    
    # Use the CONFIO asset ID from settings
    CONFIO_ASSET_ID = AlgorandAccountManager.CONFIO_ASSET_ID
    if not CONFIO_ASSET_ID:
        print("⚠️  CONFIO_ASSET_ID not configured")
        return None
    
    # Create test accounts
    sender_private_key, sender_address = account.generate_account()
    recipient_private_key, recipient_address = account.generate_account()
    
    print(f"Test Sender: {sender_address}")
    print(f"Test Recipient: {recipient_address}")
    print(f"CONFIO Asset ID: {CONFIO_ASSET_ID}")
    
    # Note: Both accounts need to opt-in to the asset first
    print("\n⚠️  Note: Both sender and recipient need to opt-in to CONFIO first")
    print("   In production, this would be handled by the app")
    
    # Create sponsored CONFIO transfer
    print("\n1. Creating sponsored CONFIO transfer...")
    result = await algorand_sponsor_service.create_and_submit_sponsored_transfer(
        sender=sender_address,
        recipient=recipient_address,
        amount=Decimal('10'),  # 10 CONFIO
        asset_id=CONFIO_ASSET_ID,
        note="Test CONFIO sponsored transfer"
    )
    
    if result['success']:
        print(f"✅ Sponsored CONFIO transaction created!")
        print(f"   Group ID: {result['group_id']}")
        print(f"   Fee saved by user: {result['fee_in_algo']} ALGO")
    else:
        print(f"❌ Failed: {result['error']}")
    
    return result


async def main():
    """Main test function"""
    print("\n" + "="*50)
    print("  Algorand Sponsored Transaction Test Suite")
    print("="*50)
    
    try:
        # Test 1: Check sponsor service health
        is_healthy = await test_sponsor_service()
        
        if not is_healthy:
            print("\n⚠️  Please fund the sponsor account and run the test again")
            print("   Use the Algorand testnet dispenser to get free test ALGO")
            return
        
        # Test 2: Test ALGO sponsored send
        print("\n" + "-"*50)
        algo_result = await test_sponsored_send()
        
        # Test 3: Test CONFIO sponsored send
        print("\n" + "-"*50)
        confio_result = await test_asset_sponsored_send()
        
        # Summary
        print("\n" + "="*50)
        print("  Test Summary")
        print("="*50)
        print(f"✅ Sponsor Service: {'Healthy' if is_healthy else 'Unhealthy'}")
        print(f"✅ ALGO Transfer: {'Success' if algo_result and algo_result.get('success') else 'Failed'}")
        print(f"✅ CONFIO Transfer: {'Success' if confio_result and confio_result.get('success') else 'Failed'}")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())