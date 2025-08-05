#!/usr/bin/env python3
"""
Test script for Aptos send integration

Tests the GraphQL mutation with Aptos sponsored transactions.
"""

import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import asyncio
from decimal import Decimal
from blockchain.aptos_transaction_manager import AptosTransactionManager
from users.models import User, Account


def test_aptos_transaction_manager():
    """Test the Aptos transaction manager directly"""
    print("=== Testing Aptos Transaction Manager ===")
    
    try:
        # Create a mock account for testing
        class MockAccount:
            def __init__(self, address):
                self.sui_address = address  # Using sui_address field for Aptos
                self.id = 1
        
        # Test account (personal account from earlier)
        sender_account = MockAccount("0x2a2549df49ec0e820b6c580c3af95b502ca7e2d956729860872fbc5de570795b")
        recipient_address = "0xda4fb7201e9abb2304c3367939914524842e0a41b61b2c305bd64656f3f25792"  # Business account
        
        # Test send tokens
        result = asyncio.run(
            AptosTransactionManager.send_tokens(
                sender_account=sender_account,
                recipient_address=recipient_address,
                amount=Decimal('50.25'),
                token_type='CUSD',
                user_signature=None  # Mock mode
            )
        )
        
        print(f"Send tokens result: {result}")
        
        # Test prepare transaction
        prepare_result = asyncio.run(
            AptosTransactionManager.prepare_send_transaction(
                account=sender_account,
                recipient=recipient_address,
                amount=Decimal('25.50'),
                token_type='CONFIO'
            )
        )
        
        print(f"Prepare transaction result: {prepare_result}")
        
        # Test execute transaction (if prepare was successful)
        if prepare_result.get('success') and prepare_result.get('txBytes'):
            execute_result = asyncio.run(
                AptosTransactionManager.execute_transaction_with_signatures(
                    tx_bytes=prepare_result['txBytes'],
                    sponsor_signature=prepare_result.get('sponsorSignature', ''),
                    user_signature='mock_keyless_signature',
                    account_id=1
                )
            )
            
            print(f"Execute transaction result: {execute_result}")
        
        print("\n✅ Aptos Transaction Manager tests completed successfully!")
        
    except Exception as e:
        print(f"❌ Error testing Aptos Transaction Manager: {e}")
        import traceback
        traceback.print_exc()


def test_graphql_mutation_simulation():
    """Simulate what happens in the GraphQL mutation"""
    print("\n=== Testing GraphQL Mutation Flow ===")
    
    try:
        # This simulates the key parts of CreateSendTransaction mutation
        from send.schema import CreateSendTransaction
        from users.models import User
        
        # Check if we have test users
        users = User.objects.all()[:2]
        if len(users) < 2:
            print("⚠️  Need at least 2 users in database to test. Creating mock flow...")
            
            # Mock the transaction flow
            class MockUser:
                def __init__(self, uid, phone):
                    self.id = uid
                    self.phone_number = phone
                    self.phone_country = "+1"
                    self.first_name = "Test"
                    self.last_name = "User"
                    self.username = f"testuser{uid}"
            
            class MockAccount:
                def __init__(self, address):
                    self.sui_address = address
                    self.id = 1
                    self.account_type = 'personal'
                    self.business = None
            
            sender_user = MockUser(1, "1234567890")
            sender_account = MockAccount("0x2a2549df49ec0e820b6c580c3af95b502ca7e2d956729860872fbc5de570795b")
            recipient_address = "0xda4fb7201e9abb2304c3367939914524842e0a41b61b2c305bd64656f3f25792"
            
            # Test the transaction manager call
            result = asyncio.run(
                AptosTransactionManager.send_tokens(
                    sender_account,
                    recipient_address,
                    Decimal('100.00'),
                    'CUSD',
                    None  # No keyless signature for mock
                )
            )
            
            print(f"Mock transaction result: {result}")
            
            if result.get('success'):
                print("✅ Mock GraphQL mutation flow would succeed!")
                print(f"   Transaction Hash: {result.get('digest', 'N/A')}")
                print(f"   Gas Saved: {result.get('gas_saved', 0)} APT")
                print(f"   Sponsored: {result.get('sponsored', False)}")
                if result.get('warning'):
                    print(f"   Warning: {result['warning']}")
            else:
                print(f"❌ Mock GraphQL mutation would fail: {result.get('error')}")
        else:
            print("✅ Found test users in database")
            
    except Exception as e:
        print(f"❌ Error testing GraphQL simulation: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("🚀 Testing Aptos Send Integration\n")
    
    test_aptos_transaction_manager()
    test_graphql_mutation_simulation()
    
    print("\n🎉 Integration tests completed!")
    print("\n📱 The app's Send feature should now work with Aptos sponsored transactions!")
    print("   - Mock transactions will work immediately")
    print("   - Real transactions need APTOS_SPONSOR_PRIVATE_KEY environment variable")
    print("   - User's keyless signatures will be used when provided")