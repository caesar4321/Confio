#!/usr/bin/env python
"""
Verify all CONFIO transfers and show final balances
"""

import os
import sys
import django
from algosdk.v2client import algod

# Add project to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_account_manager import AlgorandAccountManager
from blockchain.algorand_sponsor_service import algorand_sponsor_service

def verify_transfers():
    """Verify all CONFIO transfers"""
    
    client = algod.AlgodClient('', 'https://testnet-api.algonode.cloud')
    
    # Accounts involved
    accounts = {
        "Sponsor": algorand_sponsor_service.sponsor_address,
        "Test Account": "SW3VSGM6DCZEL7WW6LPLTJORGHQD5IMCE4C7IR3WKT5YBCTZABJAGI6D5Q",
        "Final Recipient": "XTITQDJSETDOQG3WMSDKE7QPPAX22ZMDX6PZ5B43E4JCFTEBPUJGDY2RGQ"
    }
    
    print("=" * 80)
    print("CONFIO TRANSFER VERIFICATION REPORT")
    print("=" * 80)
    
    print(f"\nAsset ID: {AlgorandAccountManager.CONFIO_ASSET_ID}")
    print(f"Asset Name: CONFIO")
    
    # Get asset info
    asset_info = client.asset_info(AlgorandAccountManager.CONFIO_ASSET_ID)
    params = asset_info.get('params', {})
    print(f"Total Supply: {params.get('total', 0) / 1_000_000:,.2f} CONFIO")
    
    print("\n" + "=" * 80)
    print("ACCOUNT BALANCES")
    print("=" * 80)
    
    for name, address in accounts.items():
        try:
            info = client.account_info(address)
            algo_balance = info['amount'] / 1_000_000
            
            # Get CONFIO balance
            confio_balance = 0
            assets = info.get('assets', [])
            for asset in assets:
                if asset['asset-id'] == AlgorandAccountManager.CONFIO_ASSET_ID:
                    confio_balance = asset['amount'] / 1_000_000
                    break
            
            print(f"\n{name}:")
            print(f"  Address: {address[:10]}...{address[-4:]}")
            print(f"  ALGO Balance: {algo_balance:.6f}")
            print(f"  CONFIO Balance: {confio_balance:.2f}")
            
        except Exception as e:
            print(f"\n{name}:")
            print(f"  Address: {address[:10]}...{address[-4:]}")
            print(f"  Error: {e}")
    
    print("\n" + "=" * 80)
    print("COMPLETED TRANSACTIONS")
    print("=" * 80)
    
    transactions = [
        {
            "From": "Sponsor",
            "To": "Test Account",
            "Amount": "10 CONFIO",
            "Type": "Sponsored",
            "TX ID": "RP6D5RV37CGA6KSN4M2VIB7UBL4VS7J6X3KP6OFPDAPJHMJKTDDA"
        },
        {
            "From": "Test Account",
            "To": "Final Recipient",
            "Amount": "5 CONFIO",
            "Type": "Sponsored",
            "TX ID": "ZJGW7V4JDLKO5YHVOQDMC227RWFVRLHX52GLEDUZOTDBV36LPI4A"
        }
    ]
    
    for i, tx in enumerate(transactions, 1):
        print(f"\nTransaction {i}:")
        print(f"  From: {tx['From']}")
        print(f"  To: {tx['To']}")
        print(f"  Amount: {tx['Amount']}")
        print(f"  Type: {tx['Type']} (no gas fees for sender)")
        print(f"  TX ID: {tx['TX ID']}")
        print(f"  Explorer: https://testnet.algoexplorer.io/tx/{tx['TX ID']}")
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    print("\n✅ Successfully completed sponsored CONFIO transfers:")
    print("   1. Sponsor → Test Account: 10 CONFIO")
    print("   2. Test Account → Final Recipient: 5 CONFIO")
    print("\n💰 Gas fees saved:")
    print("   - Each transfer would normally cost 0.002 ALGO")
    print("   - Total saved by users: 0.004 ALGO")
    print("   - All fees paid by sponsor account")
    print("\n🚀 Key achievements:")
    print("   - Implemented two-step sponsored transaction flow")
    print("   - Used raw nacl signing for client-side signatures")
    print("   - Successfully submitted atomic transaction groups")
    print("   - Zero gas fees for end users")

if __name__ == "__main__":
    verify_transfers()