"""
Deploy ConfioBatchDelegate (the EIP-7702 sponsored-batch delegate) to BSC
via the KMS sponsor.

Same rationale as deploy_cusd_plus_vault: the sponsor key is non-extractable
in AWS KMS, so `forge script --broadcast` is unusable — we build the single
contract-creation transaction from the forge artifact and sign with
EVMKMSSigner. No constructor args, no proxy, no owner: the delegate is
immutable shared code every user EOA designates via its 7702 authorization.

After deployment:
  1. BscScan/Sourcify verify (solc 0.8.26, optimizer 200, evm cancun;
     ETHERSCAN_API_KEY in git-crypted .env).
  2. Set CUSD_PLUS_BATCH_DELEGATE_ADDRESS in the environment.
  3. Flip CUSD_PLUS_7702_ENABLED when canary-ready (dust rail stays armed).

Usage:
  # Dry run — builds the txn, estimates gas, broadcasts NOTHING (default):
  myvenv/bin/python manage.py deploy_batch_delegate

  # Real deployment — requires BOTH flags (belt and suspenders):
  myvenv/bin/python manage.py deploy_batch_delegate --broadcast --yes-mainnet
"""
import json
import time
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

ARTIFACTS = Path(settings.BASE_DIR) / "contracts" / "cusd_plus" / "out"


def _rpc(url: str, method: str, params: list):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    req = urllib.request.Request(url, data=payload.encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    if "error" in body:
        raise RuntimeError(f"rpc {method}: {body['error']}")
    return body["result"]


def _bytecode(sol: str, name: str) -> bytes:
    art = json.loads((ARTIFACTS / f"{sol}.sol" / f"{name}.json").read_text())
    return bytes.fromhex(art["bytecode"]["object"].removeprefix("0x"))


class Command(BaseCommand):
    help = "Deploy ConfioBatchDelegate (EIP-7702 delegate) to BSC via the KMS sponsor"

    def add_arguments(self, parser):
        parser.add_argument("--broadcast", action="store_true", help="Actually send the transaction")
        parser.add_argument("--yes-mainnet", action="store_true",
                            help="Required alongside --broadcast to confirm mainnet")

    def handle(self, *args, **options):
        from eth_utils import keccak, to_checksum_address
        import rlp

        from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings

        signer = get_bsc_sponsor_signer_from_settings()
        rpc_url = settings.BSC_RPC_URL
        chain_id = settings.BSC_CHAIN_ID
        deployer = signer.address

        balance = int(_rpc(rpc_url, "eth_getBalance", [deployer, "latest"]), 16)
        nonce = int(_rpc(rpc_url, "eth_getTransactionCount", [deployer, "latest"]), 16)
        # Floor + 1.2x inclusion buffer, same knob the sponsored paths use
        # (CUSD_PLUS_GAS_PRICE_FLOOR_WEI). This was a hardcoded 1 gwei — 20x
        # BSC's resting price — which burned ~$20 of gas across the July 2026
        # migration deploys before the 2026-08-03 sponsor audit caught it.
        gas_price = max(int(_rpc(rpc_url, "eth_gasPrice", []), 16),
                        int(settings.CUSD_PLUS_GAS_PRICE_FLOOR_WEI))
        gas_price = (gas_price * 12) // 10

        self.stdout.write(f"Deployer (KMS sponsor): {deployer}")
        self.stdout.write(
            f"Chain {chain_id} · balance {balance/1e18:.6f} BNB · nonce {nonce} · gasPrice {gas_price/1e9:.3f} gwei")

        data = _bytecode("ConfioBatchDelegate", "ConfioBatchDelegate")  # no constructor args
        delegate_addr = to_checksum_address(
            keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce]))[-20:]
        )
        gas = int(_rpc(rpc_url, "eth_estimateGas", [{"from": deployer, "data": "0x" + data.hex()}]), 16)
        total_cost = gas * gas_price
        self.stdout.write("")
        self.stdout.write(f"ConfioBatchDelegate → {delegate_addr}  (~{gas} gas)")
        self.stdout.write(f"Est. cost ≈ {total_cost/1e18:.6f} BNB")

        if not options["broadcast"]:
            self.stdout.write(self.style.WARNING(
                "\nDRY RUN — nothing broadcast. Re-run with --broadcast --yes-mainnet to deploy."))
            return

        if not options["yes_mainnet"]:
            raise CommandError("--broadcast requires --yes-mainnet to confirm a real mainnet deployment.")
        if balance < (total_cost * 13) // 10:
            raise CommandError(f"Insufficient BNB: have {balance/1e18:.6f}, need ~{total_cost*1.3/1e18:.6f}")

        self.stdout.write("\nBroadcasting…")
        tx = {"chainId": chain_id, "nonce": nonce, "gasPrice": gas_price,
              "gas": int(gas * 13 // 10), "to": b"", "value": 0, "data": data}
        raw, _txh = signer.sign_transaction(tx)
        sent = _rpc(rpc_url, "eth_sendRawTransaction", [raw])
        self.stdout.write(f"  delegate sent: {sent}")
        for _ in range(90):
            rec = _rpc(rpc_url, "eth_getTransactionReceipt", [sent])
            if rec:
                if rec["status"] != "0x1":
                    raise CommandError(f"delegate deployment FAILED: {sent}")
                got = to_checksum_address(rec["contractAddress"])
                if got != delegate_addr:
                    raise CommandError(f"delegate address mismatch: {got} != {delegate_addr}")
                self.stdout.write(self.style.SUCCESS(f"\nDEPLOYED. ConfioBatchDelegate: {got}"))
                self.stdout.write(
                    "Next: BscScan/Sourcify verify, set CUSD_PLUS_BATCH_DELEGATE_ADDRESS, "
                    "then canary CUSD_PLUS_7702_ENABLED.")
                return
            time.sleep(2)
        raise CommandError(f"delegate deployment timeout: {sent}")
