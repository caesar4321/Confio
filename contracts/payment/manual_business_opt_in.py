#!/usr/bin/env python3
"""
Manual opt-in script for business accounts that need to opt into CONFIO and cUSD
This creates sponsored opt-in transactions where the sponsor pays all fees
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
from algosdk.transaction import AssetTransferTxn, PaymentTxn, assign_group_id, wait_for_confirmation
from django.conf import settings

# Network/IDs from Django settings (.env)
ALGOD_ADDRESS = settings.ALGORAND_ALGOD_ADDRESS
ALGOD_TOKEN = getattr(settings, 'ALGORAND_ALGOD_TOKEN', '') or ''
CONFIO_ID = settings.ALGORAND_CONFIO_ASSET_ID
CUSD_ID = settings.ALGORAND_CUSD_ASSET_ID

# Business account (override via env BUSINESS_ADDRESS)
business_address = os.environ.get('BUSINESS_ADDRESS', 'YCV25L4FIZ66N3ZTAWKLREEMOFBBIB3CCV7BJIVBLDJZI2EM6VK6Z4MPEU')

async def manual_opt_in():
    """Manually opt-in a business account using sponsored transactions"""
    
    print('=== Manual Business Account Opt-In ===')
    print(f'Business Address: {business_address}')
    print()
    
    # Initialize algod client
    # Default LocalNet token if not provided
    algod_token = ALGOD_TOKEN or ('a' * 64 if ('localhost' in ALGOD_ADDRESS or '127.0.0.1' in ALGOD_ADDRESS) else '')
    algod_client = algod.AlgodClient(algod_token, ALGOD_ADDRESS)
    
    # Check current opt-in status
    try:
        account_info = algod_client.account_info(business_address)
        assets = account_info.get('assets', [])
        
        has_confio = any(a['asset-id'] == CONFIO_ID for a in assets)
        has_cusd = any(a['asset-id'] == CUSD_ID for a in assets)
        
        print('Current opt-in status:')
        print(f'  CONFIO: {"✓ Already opted in" if has_confio else "✗ Not opted in"}')
        print(f'  cUSD: {"✓ Already opted in" if has_cusd else "✗ Not opted in"}')
        print()
        
    except Exception as e:
        print(f'Error checking account: {e}')
        return
    
    # Get sponsor mnemonic from environment
    sponsor_mnemonic = os.environ.get('ALGORAND_SPONSOR_MNEMONIC')
    if not sponsor_mnemonic:
        print('Error: ALGORAND_SPONSOR_MNEMONIC not set')
        print('Please set it with:')
        print('export ALGORAND_SPONSOR_MNEMONIC="your sponsor mnemonic here"')
        return
    
    sponsor_private_key = mnemonic.to_private_key(sponsor_mnemonic)
    sponsor_address = account.address_from_private_key(sponsor_private_key)
    
    print(f'Sponsor Address: {sponsor_address}')
    
    # Check if we have the business account mnemonic
    business_mnemonic = os.environ.get('BUSINESS_MNEMONIC')
    if not business_mnemonic:
        print()
        print('Error: BUSINESS_MNEMONIC not set')
        print('To opt-in the business account, you need its mnemonic.')
        print('Please set it with:')
        print('export BUSINESS_MNEMONIC="your business account mnemonic here"')
        print()
        print('If you do not have the mnemonic, the business owner needs to:')
        print('1. Open their wallet app (Pera, MyAlgo, etc.)')
        print('2. Search for and add these assets:')
        print(f'   - CONFIO (Asset ID: {CONFIO_ID})')
        print(f'   - cUSD (Asset ID: {CUSD_ID})')
        return
    
    business_private_key = mnemonic.to_private_key(business_mnemonic)
    derived_address = account.address_from_private_key(business_private_key)
    
    if derived_address != business_address:
        print(f'Error: Mnemonic derives to {derived_address}')
        print(f'       Expected: {business_address}')
        return
    
    print('✓ Business account mnemonic verified')
    print()
    
    # Get suggested params
    params = algod_client.suggested_params()
    params.flat_fee = True
    
    # Process CONFIO opt-in if needed
    if not has_confio:
        print('Creating sponsored opt-in for CONFIO...')
        
        # Create opt-in transaction (0 amount transfer to self) with 0 fee
        opt_in_txn = AssetTransferTxn(
            sender=business_address,
            sp=params,
            receiver=business_address,
            amt=0,
            index=CONFIO_ID
        )
        opt_in_txn.fee = 0  # Business pays no fee (fee pooling in group)
        
        # Create fee payment transaction from sponsor
        fee_payment_txn = PaymentTxn(
            sender=sponsor_address,
            sp=params,
            receiver=business_address,
            amt=0,  # No ALGO transfer, just paying fees
            note=b"CONFIO opt-in sponsorship"
        )
        fee_payment_txn.fee = params.min_fee * 2  # Sponsor covers both tx fees
        
        # Create atomic group
        txn_group = [fee_payment_txn, opt_in_txn]
        
        # Assign group ID
        assign_group_id(txn_group)
        
        # Sign transactions
        signed_fee_txn = fee_payment_txn.sign(sponsor_private_key)
        signed_opt_in = opt_in_txn.sign(business_private_key)
        
        # Submit transaction group
        try:
            print('Submitting CONFIO opt-in transaction...')
            tx_id = algod_client.send_transactions([signed_fee_txn, signed_opt_in])
            print(f'Transaction sent: {tx_id}')
            
            # Wait for confirmation
            confirmed_txn = wait_for_confirmation(algod_client, tx_id, 10)
            print(f'✓ CONFIO opt-in confirmed in round {confirmed_txn.get("confirmed-round", 0)}')
            print()
        except Exception as e:
            print(f'Error during CONFIO opt-in: {e}')
            return
    
    # Process cUSD opt-in if needed
    if CUSD_ID and not has_cusd:
        print('Creating sponsored opt-in for cUSD...')
        
        # Create opt-in transaction (0 amount transfer to self) with 0 fee
        opt_in_txn = AssetTransferTxn(
            sender=business_address,
            sp=params,
            receiver=business_address,
            amt=0,
            index=CUSD_ID
        )
        opt_in_txn.fee = 0  # Business pays no fee (fee pooling)
        
        # Create fee payment transaction from sponsor
        fee_payment_txn = PaymentTxn(
            sender=sponsor_address,
            sp=params,
            receiver=business_address,
            amt=0,  # No ALGO transfer, just paying fees
            note=b"cUSD opt-in sponsorship"
        )
        fee_payment_txn.fee = params.min_fee * 2  # Sponsor covers both fees
        
        # Create atomic group
        txn_group = [fee_payment_txn, opt_in_txn]
        
        # Assign group ID
        assign_group_id(txn_group)
        
        # Sign transactions
        signed_fee_txn = fee_payment_txn.sign(sponsor_private_key)
        signed_opt_in = opt_in_txn.sign(business_private_key)
        
        # Submit transaction group
        try:
            print('Submitting cUSD opt-in transaction...')
            tx_id = algod_client.send_transactions([signed_fee_txn, signed_opt_in])
            print(f'Transaction sent: {tx_id}')
            
            # Wait for confirmation
            confirmed_txn = wait_for_confirmation(algod_client, tx_id, 10)
            print(f'✓ cUSD opt-in confirmed in round {confirmed_txn.get("confirmed-round", 0)}')
            print()
        except Exception as e:
            print(f'Error during cUSD opt-in: {e}')
            return
    
    print('✓ Business account opt-in complete!')
    print('The business account can now receive CONFIO and cUSD payments.')

if __name__ == '__main__':
    # Run the async function
    asyncio.run(manual_opt_in())
