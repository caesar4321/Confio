import os
import sys
import django
import asyncio

sys.path.append(os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "confio_backend.settings")
django.setup()

from blockchain.algorand_sponsor_service import algorand_sponsor_service

async def main():
    vault_address = "T53KTDAXITS34Y5435VREARQTREJHUK4WEIF6FU5KLPW7OS5QET5QMHCEY"
    print(f"Funding vault {vault_address}...")
    try:
        result = await algorand_sponsor_service.fund_account(vault_address, 1_000_000)
        print(f"Result: {result}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
