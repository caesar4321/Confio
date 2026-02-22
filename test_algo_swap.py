import os
import django
import sys
import base64

# Setup Django environment
sys.path.append('/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
from blockchain.algorand_client import get_algod_client
from tinyman.v2.client import TinymanV2MainnetClient, TinymanV2TestnetClient
from tinyman.assets import AssetAmount
from algosdk.transaction import create_dryrun

def dryrun_tinyman_swap():
    algod_client = get_algod_client()
    
    # We will pretend to be the sender
    sender = "2PIFZW53RHCSFSYMCFUBW4XOCXOMB7XOYQSQ6KGT3KVGJTL4HM6COZRNMM" # just some random valid address
    
    amount_micro = 1_000_000
    is_mainnet = getattr(settings, 'ALGORAND_NETWORK', 'testnet') == 'mainnet'
    if is_mainnet:
        tm_client = TinymanV2MainnetClient(algod_client=algod_client)
    else:
        tm_client = TinymanV2TestnetClient(algod_client=algod_client)
    
    algo_id = 0
    usdc_id = settings.ALGORAND_USDC_ASSET_ID
    
    pool = tm_client.fetch_pool(algo_id, usdc_id)
    algo_asset = tm_client.fetch_asset(algo_id)
    
    quote = pool.fetch_fixed_input_swap_quote(
        amount_in=AssetAmount(algo_asset, amount_micro)
    )
    
    params = algod_client.suggested_params()
    
    txn_group = pool.prepare_swap_transactions_from_quote(
        quote=quote,
        user_address=sender,
        suggested_params=params
    )
    
    print(f"Generated {len(txn_group.transactions)} transactions in group")
    
    # We don't have the private key, but we want to know what transactions were built
    for i, txn in enumerate(txn_group.transactions):
        print(f"Txn {i}: {type(txn).__name__}, Sender: {txn.sender}, Fee: {txn.fee}")
        
    print("Success building Tinyman transactions!")

if __name__ == '__main__':
    dryrun_tinyman_swap()
