
import os
import django
import algosdk
from algosdk.v2client import algod

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.conf import settings

ADDR = "P7WYM6SDBLV5UWM6AWFD4ZCNH7DZE3EICBZOAOORAUHDBVQ44RRS6ZLZZU"

def check_balance():
    algod_address = settings.ALGORAND_ALGOD_ADDRESS
    algod_token = settings.ALGORAND_ALGOD_TOKEN
    client = algod.AlgodClient(algod_token, algod_address)
    
    try:
        info = client.account_info(ADDR)
        print(f"Address: {ADDR}")
        print(f"Algo Balance: {info.get('amount')} microAlgos")
        print("Assets:")
        for asset in info.get('assets', []):
            print(f" - ID {asset['asset-id']}: {asset['amount']}")
    except Exception as e:
        print(e)

if __name__ == "__main__":
    check_balance()
