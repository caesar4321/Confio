#!/usr/bin/env python
"""
Check CONFIO token details and accounts that have it
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

def check_confio_token():
    """Check CONFIO token details"""
    
    client = algod.AlgodClient('', 'https://testnet-api.algonode.cloud')
    
    # Get CONFIO asset ID
    asset_id = AlgorandAccountManager.CONFIO_ASSET_ID
    print(f"CONFIO Asset ID: {asset_id}")
    
    if not asset_id:
        print("CONFIO asset ID not configured")
        return
    
    # Get asset details
    try:
        asset_info = client.asset_info(asset_id)
        params = asset_info.get('params', {})
        
        print(f"\nCONFIO Token Details:")
        print(f"  Name: {params.get('name', 'N/A')}")
        print(f"  Unit: {params.get('unit-name', 'N/A')}")
        print(f"  Total Supply: {params.get('total', 0) / (10 ** params.get('decimals', 0)):,.2f}")
        print(f"  Decimals: {params.get('decimals', 0)}")
        print(f"  Creator: {params.get('creator', 'N/A')}")
        print(f"  Reserve: {params.get('reserve', 'N/A')}")
        print(f"  URL: {params.get('url', 'N/A')}")
        
        # Check if frozen
        if params.get('freeze'):
            print(f"  Freeze Address: {params.get('freeze')}")
        else:
            print(f"  Freeze: Disabled")
            
        # Check manager
        if params.get('manager'):
            print(f"  Manager: {params.get('manager')}")
        else:
            print(f"  Manager: None (immutable)")
            
        # Check clawback
        if params.get('clawback'):
            print(f"  Clawback: {params.get('clawback')}")
        else:
            print(f"  Clawback: Disabled")
            
        # Check creator balance
        creator = params.get('creator')
        if creator:
            print(f"\nCreator Account ({creator[:10]}...):")
            creator_info = client.account_info(creator)
            
            # Find CONFIO balance
            assets = creator_info.get('assets', [])
            for asset in assets:
                if asset['asset-id'] == asset_id:
                    balance = asset['amount'] / (10 ** params.get('decimals', 0))
                    print(f"  CONFIO Balance: {balance:,.2f}")
                    break
            else:
                print(f"  CONFIO Balance: 0 (not opted in)")
                
            print(f"  ALGO Balance: {creator_info['amount'] / 1_000_000:,.6f}")
            
        # Check reserve account if different from creator
        reserve = params.get('reserve')
        if reserve and reserve != creator:
            print(f"\nReserve Account ({reserve[:10]}...):")
            try:
                reserve_info = client.account_info(reserve)
                
                # Find CONFIO balance
                assets = reserve_info.get('assets', [])
                for asset in assets:
                    if asset['asset-id'] == asset_id:
                        balance = asset['amount'] / (10 ** params.get('decimals', 0))
                        print(f"  CONFIO Balance: {balance:,.2f}")
                        break
                else:
                    print(f"  CONFIO Balance: 0 (not opted in)")
                    
                print(f"  ALGO Balance: {reserve_info['amount'] / 1_000_000:,.6f}")
            except Exception as e:
                print(f"  Error checking reserve: {e}")
        
        # Check our test account
        test_address = "SW3VSGM6DCZEL7WW6LPLTJORGHQD5IMCE4C7IR3WKT5YBCTZABJAGI6D5Q"
        print(f"\nTest Account ({test_address[:10]}...):")
        test_info = client.account_info(test_address)
        
        # Check if opted in
        assets = test_info.get('assets', [])
        for asset in assets:
            if asset['asset-id'] == asset_id:
                balance = asset['amount'] / (10 ** params.get('decimals', 0))
                print(f"  Status: Opted in")
                print(f"  CONFIO Balance: {balance:,.2f}")
                break
        else:
            print(f"  Status: Not opted in to CONFIO")
            
        print(f"  ALGO Balance: {test_info['amount'] / 1_000_000:,.6f}")
        
    except Exception as e:
        print(f"Error getting asset info: {e}")

if __name__ == "__main__":
    check_confio_token()