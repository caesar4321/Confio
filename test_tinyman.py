import os
import django
import sys

# Setup Django environment
sys.path.append('/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
from blockchain.algorand_client import get_algod_client
from tinyman.v2.client import TinymanV2MainnetClient, TinymanV2TestnetClient
from tinyman.assets import AssetAmount

def test_tinyman():
    algod_client = get_algod_client()
    
    # Check if we are on mainnet or testnet
    is_mainnet = settings.ALGORAND_NETWORK == 'mainnet'
    print(f"Network: {settings.ALGORAND_NETWORK}")
    
    if is_mainnet:
        tm_client = TinymanV2MainnetClient(algod_client=algod_client)
    else:
        tm_client = TinymanV2TestnetClient(algod_client=algod_client)

    usdc_id = settings.ALGORAND_USDC_ASSET_ID
    # ALGO is asset ID 0
    algo_id = 0
    
    print(f"Fetching pool for ALGO (0) and USDC ({usdc_id})")
    
    try:
        pool = tm_client.fetch_pool(algo_id, usdc_id)
        print(f"Pool found: {pool}")
        
        # We want to swap a fixed amount of ALGO for USDC
        amount_in = 1_000_000 # 1 ALGO
        algo_asset = tm_client.fetch_asset(algo_id)
        
        quote = pool.fetch_fixed_input_swap_quote(
            amount_in=AssetAmount(algo_asset, amount_in)
        )
        
        print(f"Quote: {quote}")
        print(f"Amount out: {quote.amount_out.amount} {quote.amount_out.asset.unit_name}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    test_tinyman()
