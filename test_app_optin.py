#!/usr/bin/env python3
"""
Test script to verify app opt-in funding calculations
"""

import os
import sys
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from decimal import Decimal
from algosdk.v2client import algod
from django.conf import settings
from blockchain.account_funding_service import account_funding_service

def test_app_optin_funding():
    """Test the app opt-in funding calculation"""
    
    # Test address (from the logs)
    test_address = "N3T5WQVBAVMTSIVYNBLIEE4XNFLDYLY3SIIP6B6HENADL6UH7HA56MZSDE"
    
    print(f"\n{'='*60}")
    print("Testing App Opt-In Funding Calculation")
    print(f"{'='*60}")
    print(f"Test Address: {test_address}")
    print(f"cUSD App ID: {settings.ALGORAND_CUSD_APP_ID}")
    
    # Connect to Algorand
    algod_client = algod.AlgodClient("", settings.ALGORAND_ALGOD_ADDRESS)
    
    # Get account info
    account_info = algod_client.account_info(test_address)
    current_balance = account_info.get('amount', 0)
    current_min_balance = account_info.get('min-balance', 0)
    num_assets = len(account_info.get('assets', []))
    num_apps = len(account_info.get('apps-local-state', []))
    
    print(f"\nCurrent Account State:")
    print(f"  Balance: {current_balance:,} microAlgos ({current_balance/1_000_000:.6f} ALGO)")
    print(f"  Min Balance: {current_min_balance:,} microAlgos ({current_min_balance/1_000_000:.6f} ALGO)")
    print(f"  Assets Opted In: {num_assets}")
    print(f"  Apps Opted In: {num_apps}")
    
    # Check if already opted into cUSD app
    apps_local_state = account_info.get('apps-local-state', [])
    already_opted_in = any(app['id'] == settings.ALGORAND_CUSD_APP_ID for app in apps_local_state)
    
    if already_opted_in:
        print(f"\n✅ Already opted into cUSD app {settings.ALGORAND_CUSD_APP_ID}")
        return
    
    print(f"\n❌ Not opted into cUSD app {settings.ALGORAND_CUSD_APP_ID}")
    
    # Calculate MBR increase for app opt-in
    # cUSD app has 2 uint64 fields (is_frozen, is_vault) in local state
    # Base opt-in: 100,000 microAlgos + (2 * 28,500) for the uint64 fields = 157,000 total
    app_mbr_increase = 100_000 + (2 * 28_500)  # 157,000 microAlgos
    min_balance_after_optin = current_min_balance + app_mbr_increase
    
    print(f"\nMBR Calculation for App Opt-In:")
    print(f"  Current Min Balance: {current_min_balance:,} microAlgos")
    print(f"  App MBR Increase: {app_mbr_increase:,} microAlgos")
    print(f"    Base: 100,000 microAlgos")
    print(f"    2 uint64 fields: 2 × 28,500 = 57,000 microAlgos")
    print(f"  New Min Balance: {min_balance_after_optin:,} microAlgos")
    
    # Calculate funding needed
    min_fee = 1000  # 1000 microAlgos
    
    print(f"\nFunding Calculation:")
    print(f"  Current Balance: {current_balance:,} microAlgos")
    print(f"  Required After Opt-in: {min_balance_after_optin + min_fee:,} microAlgos (MBR + fee buffer)")
    
    if current_balance < min_balance_after_optin + min_fee:
        funding_needed = min_balance_after_optin + min_fee - current_balance
        print(f"  ❌ Insufficient Balance!")
        print(f"  Funding Needed: {funding_needed:,} microAlgos ({funding_needed/1_000_000:.6f} ALGO)")
    else:
        print(f"  ✅ Sufficient Balance!")
        print(f"  No funding needed")
        funding_needed = 0
    
    # Test the account_funding_service calculation
    print(f"\n{'='*60}")
    print("Testing account_funding_service.calculate_funding_needed()")
    print(f"{'='*60}")
    
    service_funding = account_funding_service.calculate_funding_needed(test_address, for_app_optin=True)
    print(f"Service calculated funding: {service_funding:,} microAlgos ({service_funding/1_000_000:.6f} ALGO)")
    
    # Compare calculations
    if service_funding != funding_needed:
        print(f"\n⚠️ WARNING: Service calculation differs from manual calculation!")
        print(f"  Manual: {funding_needed:,} microAlgos")
        print(f"  Service: {service_funding:,} microAlgos")
    else:
        print(f"\n✅ Service calculation matches manual calculation")
    
    # Check sponsor balance
    print(f"\n{'='*60}")
    print("Checking Sponsor Account")
    print(f"{'='*60}")
    
    sponsor_info = algod_client.account_info(settings.ALGORAND_SPONSOR_ADDRESS)
    sponsor_balance = sponsor_info.get('amount', 0)
    sponsor_min = sponsor_info.get('min-balance', 0)
    sponsor_available = sponsor_balance - sponsor_min
    
    print(f"Sponsor Address: {settings.ALGORAND_SPONSOR_ADDRESS}")
    print(f"Sponsor Balance: {sponsor_balance:,} microAlgos ({sponsor_balance/1_000_000:.6f} ALGO)")
    print(f"Sponsor Min Balance: {sponsor_min:,} microAlgos")
    print(f"Sponsor Available: {sponsor_available:,} microAlgos ({sponsor_available/1_000_000:.6f} ALGO)")
    
    if sponsor_available >= funding_needed + 1000:
        print(f"✅ Sponsor has sufficient balance to fund opt-in")
    else:
        print(f"❌ Sponsor has insufficient balance!")
        print(f"  Needed: {funding_needed + 1000:,} microAlgos")
        print(f"  Available: {sponsor_available:,} microAlgos")

if __name__ == "__main__":
    test_app_optin_funding()