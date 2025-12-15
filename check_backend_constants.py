
import os
import django
import sys

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_account_manager import AlgorandAccountManager
from django.conf import settings

print("--- AlgorandAccountManager Constants ---")
print(f"CONFIO_ASSET_ID: {AlgorandAccountManager.CONFIO_ASSET_ID}")
print(f"CUSD_ASSET_ID:   {AlgorandAccountManager.CUSD_ASSET_ID}")
print(f"USDC_ASSET_ID:   {AlgorandAccountManager.USDC_ASSET_ID}")

print("\n--- Django Settings ---")
print(f"ALGORAND_NETWORK: {settings.ALGORAND_NETWORK}")
print(f"ALGORAND_CONFIO_ASSET_ID: {getattr(settings, 'ALGORAND_CONFIO_ASSET_ID', 'Not Set')}")
print(f"ALGORAND_CUSD_ASSET_ID: {getattr(settings, 'ALGORAND_CUSD_ASSET_ID', 'Not Set')}")
print(f"ALGORAND_USDC_ASSET_ID: {getattr(settings, 'ALGORAND_USDC_ASSET_ID', 'Not Set')}")
