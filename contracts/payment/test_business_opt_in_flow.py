#!/usr/bin/env python3
"""
Test the complete business owner opt-in flow
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

from algosdk.v2client import algod
from blockchain.algorand_sponsor_service import algorand_sponsor_service

# Setup
ALGOD_ADDRESS = 'https://testnet-api.algonode.cloud'
ALGOD_TOKEN = ''
CONFIO_ID = 744150851
CUSD_ID = 744192921

# Business account
business_address = 'YCV25L4FIZ66N3ZTAWKLREEMOFBBIB3CCV7BJIVBLDJZI2EM6VK6Z4MPEU'

async def test_business_opt_in_flow():
    """Test the business owner opt-in flow"""
    
    print('=== Testing Business Owner Opt-In Flow ===')
    print(f'Business Address: {business_address}')
    print()
    
    # Initialize algod client
    algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    
    # Step 1: Check current opt-in status
    print('Step 1: Checking current opt-in status...')
    try:
        account_info = algod_client.account_info(business_address)
        assets = account_info.get('assets', [])
        balance = account_info.get('amount', 0) / 1_000_000
        
        has_confio = any(a['asset-id'] == CONFIO_ID for a in assets)
        has_cusd = any(a['asset-id'] == CUSD_ID for a in assets)
        
        print(f'  ALGO Balance: {balance} ALGO')
        print(f'  CONFIO: {"✓ Opted in" if has_confio else "✗ Not opted in"}')
        print(f'  cUSD: {"✓ Opted in" if has_cusd else "✗ Not opted in"}')
        print()
        
    except Exception as e:
        print(f'Error checking account: {e}')
        return
    
    # Step 2: Create sponsored opt-in transactions if needed
    needed_assets = []
    if not has_confio:
        needed_assets.append(('CONFIO', CONFIO_ID))
    if not has_cusd:
        needed_assets.append(('cUSD', CUSD_ID))
    
    if not needed_assets:
        print('Business account already opted into all required assets!')
        return
    
    print('Step 2: Creating sponsored opt-in transactions...')
    opt_in_transactions = []
    
    for asset_name, asset_id in needed_assets:
        print(f'  Creating opt-in for {asset_name} (ID: {asset_id})...')
        
        result = await algorand_sponsor_service.create_sponsored_opt_in(
            user_address=business_address,
            asset_id=asset_id
        )
        
        if result.get('success'):
            print(f'    ✓ Created sponsored opt-in transaction')
            print(f'    Group ID: {result.get("group_id")}')
            print(f'    Total fee: {result.get("total_fee")} microAlgos')
            
            opt_in_transactions.append({
                'asset_name': asset_name,
                'asset_id': asset_id,
                'user_transaction': result.get('user_transaction'),
                'sponsor_transaction': result.get('sponsor_transaction'),
                'group_id': result.get('group_id')
            })
        else:
            print(f'    ✗ Failed to create opt-in: {result.get("error")}')
            if result.get('details'):
                print(f'    Details: {result.get("details")}')
    
    if not opt_in_transactions:
        print('No opt-in transactions created')
        return
    
    print()
    print('Step 3: Business owner needs to sign transactions')
    print('=' * 50)
    print('In a real flow, the client would:')
    print('1. Receive these unsigned transactions')
    print('2. Sign the user transactions with the business owner\'s Web3Auth wallet')
    print('3. Submit the signed group to the blockchain')
    print()
    
    for txn in opt_in_transactions:
        print(f'Asset: {txn["asset_name"]} (ID: {txn["asset_id"]})')
        print(f'  User transaction: {txn["user_transaction"][:50]}...')
        print(f'  Sponsor transaction: {txn["sponsor_transaction"][:50]}...')
        print(f'  Group ID: {txn["group_id"]}')
        print()
    
    # Step 4: Check sponsor health
    print('Step 4: Checking sponsor health...')
    health = await algorand_sponsor_service.check_sponsor_health()
    
    print(f'  Sponsor healthy: {health.get("healthy")}')
    print(f'  Balance: {health.get("balance_formatted")}')
    print(f'  Can sponsor: {health.get("can_sponsor")}')
    if health.get('estimated_transactions'):
        print(f'  Estimated transactions: {health.get("estimated_transactions")}')
    
    print()
    print('=== Test Complete ===')
    print('Note: The business account owner would need to:')
    print('1. Sign the user transactions with their Web3Auth private key')
    print('2. Submit the signed transactions to complete the opt-ins')
    print()
    print('To manually opt-in the business account, run:')
    print('  export BUSINESS_MNEMONIC="<business account mnemonic>"')
    print('  python contracts/payment/manual_business_opt_in.py')

if __name__ == '__main__':
    asyncio.run(test_business_opt_in_flow())