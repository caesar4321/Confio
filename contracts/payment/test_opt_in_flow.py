#!/usr/bin/env python3
"""
Test script to verify the automatic opt-in flow for business accounts
"""

import sys
import os
import asyncio

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Setup Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from algosdk import mnemonic, account
from algosdk.v2client import algod
from blockchain.algorand_sponsor_service import algorand_sponsor_service

# Setup
ALGOD_ADDRESS = 'https://testnet-api.algonode.cloud'
ALGOD_TOKEN = ''
CONFIO_ID = 744150851
CUSD_ID = 744152157

# Business account that needs opt-in
business_address = 'YCV25L4FIZ66N3ZTAWKLREEMOFBBIB3CCV7BJIVBLDJZI2EM6VK6Z4MPEU'

async def test_opt_in_flow():
    """Test the sponsored opt-in flow"""
    
    print('=== Testing Sponsored Opt-In Flow ===')
    print(f'Business Address: {business_address}')
    print(f'CONFIO Asset ID: {CONFIO_ID}')
    print(f'cUSD Asset ID: {CUSD_ID}')
    print()
    
    # Initialize algod client
    algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    
    # Check current opt-in status
    try:
        account_info = algod_client.account_info(business_address)
        assets = account_info.get('assets', [])
        
        has_confio = any(a['asset-id'] == CONFIO_ID for a in assets)
        has_cusd = any(a['asset-id'] == CUSD_ID for a in assets)
        
        print('Current opt-in status:')
        print(f'  CONFIO: {"✓ Opted in" if has_confio else "✗ Not opted in"}')
        print(f'  cUSD: {"✓ Opted in" if has_cusd else "✗ Not opted in"}')
        print()
        
    except Exception as e:
        print(f'Error checking account: {e}')
        return
    
    # Test creating sponsored opt-in for CONFIO if needed
    if not has_confio:
        print('Testing sponsored opt-in for CONFIO...')
        
        result = await algorand_sponsor_service.create_sponsored_opt_in(
            user_address=business_address,
            asset_id=CONFIO_ID
        )
        
        if result.get('success'):
            print('✓ Successfully created sponsored opt-in transaction')
            print(f'  User transaction: {result.get("user_transaction")[:50]}...')
            print(f'  Sponsor transaction: {result.get("sponsor_transaction")[:50]}...')
            print(f'  Group ID: {result.get("group_id")}')
            print(f'  Total fee: {result.get("total_fee")} microAlgos')
            print()
            print('The business account owner needs to sign the user transaction.')
            print('This would normally happen automatically in the app.')
        else:
            print(f'✗ Failed to create opt-in: {result.get("error")}')
            if result.get('details'):
                print(f'  Details: {result.get("details")}')
    else:
        print('Business account already opted into CONFIO')
    
    # Test creating sponsored opt-in for cUSD if needed
    if not has_cusd:
        print('Testing sponsored opt-in for cUSD...')
        
        result = await algorand_sponsor_service.create_sponsored_opt_in(
            user_address=business_address,
            asset_id=CUSD_ID
        )
        
        if result.get('success'):
            print('✓ Successfully created sponsored opt-in transaction')
            print(f'  User transaction: {result.get("user_transaction")[:50]}...')
            print(f'  Sponsor transaction: {result.get("sponsor_transaction")[:50]}...')
            print(f'  Group ID: {result.get("group_id")}')
            print(f'  Total fee: {result.get("total_fee")} microAlgos')
            print()
            print('The business account owner needs to sign the user transaction.')
            print('This would normally happen automatically in the app.')
        else:
            print(f'✗ Failed to create opt-in: {result.get("error")}')
            if result.get('details'):
                print(f'  Details: {result.get("details")}')
    else:
        print('Business account already opted into cUSD')
    
    # Check sponsor health
    print()
    print('Checking sponsor health...')
    health = await algorand_sponsor_service.check_sponsor_health()
    
    print(f'  Sponsor healthy: {health.get("healthy")}')
    print(f'  Balance: {health.get("balance_formatted")}')
    print(f'  Can sponsor: {health.get("can_sponsor")}')
    if health.get('estimated_transactions'):
        print(f'  Estimated transactions: {health.get("estimated_transactions")}')
    if health.get('recommendations'):
        print(f'  Recommendations: {health.get("recommendations")}')

if __name__ == '__main__':
    # Run the async test
    asyncio.run(test_opt_in_flow())