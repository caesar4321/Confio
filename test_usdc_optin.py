#!/usr/bin/env python
"""
Test script for USDC opt-in mutation
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from blockchain.algorand_account_manager import AlgorandAccountManager

User = get_user_model()

def test_usdc_optin():
    """Test the USDC opt-in functionality"""
    
    # Get a test user (you'll need to replace with an actual user email)
    email = "test@example.com"  # Replace with your test user email
    
    try:
        user = User.objects.get(email=email)
        print(f"Testing USDC opt-in for user: {user.email}")
        print("=" * 60)
        
        # Test the opt-in
        result = AlgorandAccountManager.opt_in_to_usdc(user)
        
        print(f"Success: {result['success']}")
        print(f"Already opted in: {result.get('already_opted_in', False)}")
        print(f"Error: {result.get('error', 'None')}")
        print(f"Algorand address: {result.get('algorand_address', 'None')}")
        print()
        
        # Show current network config
        print("Network Configuration:")
        print(f"  Network: {AlgorandAccountManager.NETWORK}")
        print(f"  USDC Asset ID: {AlgorandAccountManager.USDC_ASSET_ID}")
        
    except User.DoesNotExist:
        print(f"User {email} not found. Please update the email in the script.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_usdc_optin()