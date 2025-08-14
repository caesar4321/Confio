#!/usr/bin/env python3
"""
Clear the cached opt-in status for all business accounts to force re-checking
This is useful when the backend has been fixed and we need fresh checks
"""

import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Setup Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from algosdk.v2client import algod

# Setup
ALGOD_ADDRESS = 'https://testnet-api.algonode.cloud'
ALGOD_TOKEN = ''
CONFIO_ID = 744150851
CUSD_ID = 744192921

# Business account
business_address = 'YCV25L4FIZ66N3ZTAWKLREEMOFBBIB3CCV7BJIVBLDJZI2EM6VK6Z4MPEU'

def check_actual_opt_ins():
    """Check the actual opt-in status on blockchain"""
    
    print('=== Checking Actual Blockchain Opt-In Status ===')
    print(f'Business Address: {business_address}')
    print(f'Explorer: https://testnet.explorer.perawallet.app/address/{business_address}/')
    print()
    
    # Initialize algod client
    algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    
    try:
        account_info = algod_client.account_info(business_address)
        assets = account_info.get('assets', [])
        balance = account_info.get('amount', 0) / 1_000_000
        
        print(f'ALGO Balance: {balance} ALGO')
        print(f'Number of assets: {len(assets)}')
        print()
        
        has_confio = any(a['asset-id'] == CONFIO_ID for a in assets)
        has_cusd = any(a['asset-id'] == CUSD_ID for a in assets)
        
        print('Opt-in status:')
        print(f'  CONFIO (744150851): {"✓ Opted in" if has_confio else "✗ NOT opted in"}')
        print(f'  cUSD (744192921): {"✓ Opted in" if has_cusd else "✗ NOT opted in"}')
        
        if assets:
            print('\nAssets opted into:')
            for asset in assets:
                print(f"  - Asset ID: {asset['asset-id']}, Balance: {asset['amount']}")
        else:
            print('\n⚠️  NO ASSETS - This account is not opted into any assets!')
        
        print()
        print('IMPORTANT: The opt-in cache has been stored in React Native Keychain.')
        print('To clear it and force a fresh opt-in check:')
        print()
        print('1. Sign out from the app')
        print('2. Sign back in')
        print('3. Switch to business account')  
        print('4. Try generating an invoice again')
        print()
        print('The backend mutation has been fixed to properly detect missing opt-ins.')
        
    except Exception as e:
        print(f'Error checking account: {e}')

if __name__ == '__main__':
    check_actual_opt_ins()