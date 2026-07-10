"""
Smoke-test the BSC sponsor hot wallet KMS signer.

Shows the KMS-derived sponsor address, its BNB balance, and its nonce on the
configured BSC network. Read-only: nothing is signed or submitted unless
--sign-test is passed, which signs (but never broadcasts) a self-send to
prove the KMS signing path works end to end.

Usage:
    myvenv/bin/python manage.py bsc_sponsor_status
    myvenv/bin/python manage.py bsc_sponsor_status --sign-test
"""

import json
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand

from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings


def _rpc(url: str, method: str, params: list):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    req = urllib.request.Request(
        url, data=payload.encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    if "error" in body:
        raise RuntimeError(f"rpc {method}: {body['error']}")
    return body["result"]


class Command(BaseCommand):
    help = "Show BSC sponsor hot wallet status (KMS address, BNB balance, nonce)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--sign-test",
            action="store_true",
            help="Sign (but do NOT broadcast) a 0-value self-send to verify KMS signing",
        )

    def handle(self, *args, **options):
        signer = get_bsc_sponsor_signer_from_settings()
        rpc_url = settings.BSC_RPC_URL
        chain_id = settings.BSC_CHAIN_ID

        address = signer.address
        self.stdout.write(f"KMS alias:   {signer.key_alias} ({signer.region_name})")
        self.stdout.write(f"Sponsor:     {address}")
        self.stdout.write(f"Chain:       {chain_id} via {rpc_url}")

        balance = int(_rpc(rpc_url, "eth_getBalance", [address, "latest"]), 16)
        nonce = int(_rpc(rpc_url, "eth_getTransactionCount", [address, "latest"]), 16)
        self.stdout.write(f"Balance:     {balance / 1e18:.6f} BNB")
        self.stdout.write(f"Nonce:       {nonce}")

        if options["sign_test"]:
            gas_price = int(_rpc(rpc_url, "eth_gasPrice", []), 16)
            tx = {
                "chainId": chain_id,
                "nonce": nonce,
                "gasPrice": gas_price,
                "gas": 21000,
                "to": address,
                "value": 0,
                "data": "0x",
            }
            raw, tx_hash = signer.sign_transaction(tx)
            self.stdout.write(self.style.SUCCESS(f"Sign test OK: {tx_hash} ({len(raw) // 2 - 1} bytes, not broadcast)"))
