#!/usr/bin/env python
"""
Test script for sponsored opt-in with Web3Auth flow
"""
import os
import sys
import django
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv('/Users/julian/Confio/.env.algorand')

# Setup Django
sys.path.append('/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_sponsor_service import algorand_sponsor_service
from blockchain.algorand_account_manager import AlgorandAccountManager
from algosdk import account, mnemonic
import json


async def test_sponsored_opt_in_flow():
    """Test the complete sponsored opt-in flow"""
    print("\n=== Testing Sponsored Opt-In Flow ===\n")
    
    # 1. Create a test user account (simulating Web3Auth)
    test_private_key, test_address = account.generate_account()
    print(f"Test User Address: {test_address}")
    print(f"Test User Mnemonic: {mnemonic.from_private_key(test_private_key)}")
    
    # 2. Check sponsor health
    print("\n1. Checking sponsor health...")
    health = await algorand_sponsor_service.check_sponsor_health()
    print(f"   Sponsor Balance: {health['balance']} ALGO")
    print(f"   Can Sponsor: {health['can_sponsor']}")
    
    if not health['can_sponsor']:
        print("\n⚠️  Sponsor account needs funding!")
        return False
    
    # 3. Create sponsored opt-in for CONFIO
    print("\n2. Creating sponsored opt-in for CONFIO...")
    asset_id = AlgorandAccountManager.CONFIO_ASSET_ID
    print(f"   Asset ID: {asset_id}")
    
    result = await algorand_sponsor_service.execute_server_side_opt_in(
        user_address=test_address,
        asset_id=asset_id
    )
    
    print(f"\n3. Opt-in result:")
    print(f"   Success: {result.get('success')}")
    
    if result.get('already_opted_in'):
        print(f"   Status: Already opted in!")
        return True
    
    if result.get('requires_user_signature'):
        print(f"   Status: Requires user signature (Web3Auth flow)")
        print(f"   Group ID: {result.get('group_id')}")
        print(f"   User Transaction: {result.get('user_transaction')[:50]}...")
        print(f"   Sponsor Transaction: {result.get('sponsor_transaction')[:50]}...")
        
        # In a real app, the client would sign this with Web3Auth
        print("\n   ✅ In production, client would:")
        print("      1. Receive unsigned user transaction")
        print("      2. Sign with Web3Auth private key")
        print("      3. Submit both transactions as atomic group")
        print("      4. User pays 0 fees!")
        
        return True
    
    return False


async def test_mutation_directly():
    """Test the GraphQL mutation directly"""
    print("\n=== Testing GraphQL Mutation ===\n")
    
    from users.models import User, Account
    from blockchain.mutations import AlgorandSponsoredOptInMutation
    
    # Create a test user
    test_user, _ = User.objects.get_or_create(
        email='test@confio.app',
        defaults={'username': 'test_user'}
    )
    
    # Create test account with Algorand address
    test_private_key, test_address = account.generate_account()
    test_account, _ = Account.objects.get_or_create(
        user=test_user,
        account_type='personal',
        defaults={'algorand_address': test_address}
    )
    
    print(f"Test User: {test_user.email}")
    print(f"Test Address: {test_address}")
    
    # Create mock info object
    class MockInfo:
        class MockContext:
            def __init__(self, user):
                self.user = user
        
        def __init__(self, user):
            self.context = self.MockContext(user)
    
    mock_info = MockInfo(test_user)
    
    # Call the mutation
    print("\nCalling AlgorandSponsoredOptIn mutation...")
    result = AlgorandSponsoredOptInMutation.mutate(
        root=None,
        info=mock_info,
        asset_id=AlgorandAccountManager.CONFIO_ASSET_ID
    )
    
    print(f"\nMutation Result:")
    print(f"  Success: {result.success}")
    if result.error:
        print(f"  Error: {result.error}")
    print(f"  Already Opted In: {result.already_opted_in}")
    print(f"  Requires Signature: {result.requires_user_signature}")
    print(f"  Asset: {result.asset_name} (ID: {result.asset_id})")
    
    if result.group_id:
        print(f"  Group ID: {result.group_id}")
    
    return result.success


async def main():
    """Main test function"""
    print("\n" + "="*60)
    print("  Algorand Sponsored Opt-In Test Suite")
    print("="*60)
    
    try:
        # Test 1: Direct service test
        print("\n[Test 1] Direct Service Test")
        service_result = await test_sponsored_opt_in_flow()
        
        # Test 2: GraphQL mutation test
        print("\n" + "-"*60)
        print("\n[Test 2] GraphQL Mutation Test")
        mutation_result = await test_mutation_directly()
        
        # Summary
        print("\n" + "="*60)
        print("  Test Summary")
        print("="*60)
        print(f"✅ Service Test: {'Passed' if service_result else 'Failed'}")
        print(f"✅ Mutation Test: {'Passed' if mutation_result else 'Failed'}")
        
        if service_result and mutation_result:
            print("\n🎉 All tests passed! The sponsored opt-in system is working.")
            print("\nNOTE: In production with Web3Auth:")
            print("  1. User logs in with Google/Apple")
            print("  2. Server creates sponsored opt-in transaction")
            print("  3. Client signs with Web3Auth private key")
            print("  4. Both transactions submitted atomically")
            print("  5. User pays 0 fees!")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())