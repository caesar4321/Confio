"""
Deploy ConfioToken ($CONFIO BEP-20) to BSC via the KMS sponsor.

Fixed-supply token: 1,000,000,000 CONFIO (18dp) minted in the constructor
to the 3-of-5 Safe treasury; no owner, no minter, no pause. Mirrors the
Algorand ASA 3351104258 (name "Confío", unit CONFIO, 1B total).

Same KMS-creation-tx flow as deploy_presale_vault (non-extractable key).

Usage:
  # Dry run — builds the txn, estimates gas, broadcasts NOTHING (default):
  myvenv/bin/python manage.py deploy_confio_token

  # Real deployment — requires BOTH flags:
  myvenv/bin/python manage.py deploy_confio_token --broadcast --yes-mainnet
"""
import json
import time
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

SAFE = "0xF29A418744E793973BF4eEc676F8a30B2793b623"  # 3-of-5, treasury

ARTIFACTS = Path(settings.BASE_DIR) / "contracts" / "cusd_plus" / "out"


def _rpc(url: str, method: str, params: list):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    req = urllib.request.Request(url, data=payload.encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    if "error" in body:
        raise RuntimeError(f"rpc {method}: {body['error']}")
    return body["result"]


class Command(BaseCommand):
    help = "Deploy ConfioToken ($CONFIO BEP-20, fixed 1B supply to the Safe) to BSC"

    def add_arguments(self, parser):
        parser.add_argument("--broadcast", action="store_true", help="Actually send the transaction")
        parser.add_argument("--yes-mainnet", action="store_true", help="Required alongside --broadcast to confirm mainnet")

    def handle(self, *args, **options):
        from eth_abi import encode as abi_encode
        from eth_utils import keccak, to_checksum_address
        import rlp

        from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings

        signer = get_bsc_sponsor_signer_from_settings()
        rpc_url = settings.BSC_RPC_URL
        chain_id = settings.BSC_CHAIN_ID
        deployer = signer.address

        balance = int(_rpc(rpc_url, "eth_getBalance", [deployer, "latest"]), 16)
        nonce = int(_rpc(rpc_url, "eth_getTransactionCount", [deployer, "latest"]), 16)
        gas_price = max(int(_rpc(rpc_url, "eth_gasPrice", []), 16), 1_000_000_000)

        self.stdout.write(f"Deployer (KMS sponsor): {deployer}")
        self.stdout.write(f"Chain {chain_id} · balance {balance/1e18:.6f} BNB · nonce {nonce} · gasPrice {gas_price/1e9:.3f} gwei")
        self.stdout.write(f"Treasury (Safe, receives full 1B supply) = {SAFE}")

        art = json.loads((ARTIFACTS / "ConfioToken.sol" / "ConfioToken.json").read_text())
        bytecode = bytes.fromhex(art["bytecode"]["object"].removeprefix("0x"))
        data = bytecode + abi_encode(["address"], [SAFE])

        token_addr = to_checksum_address(
            keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce]))[-20:]
        )
        gas_est = int(_rpc(rpc_url, "eth_estimateGas", [{"from": deployer, "data": "0x" + data.hex()}]), 16)
        total_cost = gas_est * gas_price
        self.stdout.write("")
        self.stdout.write(f"token → {token_addr}  (~{gas_est} gas, ≈ {total_cost/1e18:.6f} BNB)")

        if not options["broadcast"]:
            self.stdout.write(self.style.WARNING("\nDRY RUN — nothing broadcast. Re-run with --broadcast --yes-mainnet to deploy."))
            return
        if not options["yes_mainnet"]:
            raise CommandError("--broadcast requires --yes-mainnet to confirm a real mainnet deployment.")
        if balance < total_cost * 13 // 10:
            raise CommandError(f"Insufficient BNB: have {balance/1e18:.6f}, need ~{total_cost*1.3/1e18:.6f}")

        tx = {"chainId": chain_id, "nonce": nonce, "gasPrice": gas_price,
              "gas": int(gas_est * 13 // 10), "to": b"", "value": 0, "data": "0x" + data.hex()}
        raw, txh = signer.sign_transaction(tx)
        sent = _rpc(rpc_url, "eth_sendRawTransaction", [raw])
        self.stdout.write(f"\nBroadcasting… sent: {sent}")
        receipt = None
        for _ in range(90):
            receipt = _rpc(rpc_url, "eth_getTransactionReceipt", [sent])
            if receipt:
                break
            time.sleep(2)
        if not receipt:
            raise CommandError(f"timeout waiting for receipt: {sent}")
        if receipt["status"] != "0x1":
            raise CommandError(f"deploy FAILED: {sent}")
        got = to_checksum_address(receipt["contractAddress"])
        if got != token_addr:
            raise CommandError(f"address mismatch: {got} != {token_addr}")

        # Post-deploy sanity reads
        def call(sig, args_types=None, args=None):
            calldata = keccak(text=sig)[:4]
            if args_types:
                calldata += abi_encode(args_types, args)
            return _rpc(rpc_url, "eth_call", [{"to": got, "data": "0x" + calldata.hex()}, "latest"])

        supply = int(call("totalSupply()"), 16)
        safe_bal = int(call("balanceOf(address)", ["address"], [SAFE]), 16)
        self.stdout.write(self.style.SUCCESS(f"\nDEPLOYED. ConfioToken (CONFIO): {got}"))
        self.stdout.write(f"  totalSupply      = {supply/1e18:,.0f} CONFIO")
        self.stdout.write(f"  balanceOf(Safe)  = {safe_bal/1e18:,.0f} CONFIO")
        self.stdout.write("Next steps (all Safe transactions):")
        self.stdout.write(f"  1. presaleVault.setConfioToken({got})  [one-shot]")
        self.stdout.write("  2. token.transfer(presaleVault, >= totalSold) to fund claims")
        self.stdout.write("  3. presaleVault.unlockClaims() when claims open (one-way; needs full backing)")
        self.stdout.write("Then: BscScan verify, BSC_CONFIO_TOKEN_ADDRESS in .env.mainnet, DEPLOYMENT.md.")
