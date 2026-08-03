"""
Deploy ConfioPayrollVault to BSC via the KMS sponsor.

Same KMS-creation-tx flow as deploy_presale_vault (the sponsor key is
non-extractable, so forge --broadcast is not an option). Single contract,
non-upgradeable, no proxy.

Constructor: (cusdPlusVault, owner)
  - cusdPlusVault  = CUSD_PLUS_VAULT_ADDRESS (live 0x3C29…3Ed1)
  - owner          = the 3-of-5 Safe (can only collect ACCRUED fees and
                     pause deposits/payouts; never touches escrow —
                     payout fees accrue IN the contract, Julian 07-31)

Usage:
  # Dry run — builds the txn, estimates gas, broadcasts NOTHING (default):
  myvenv/bin/python manage.py deploy_payroll_vault

  # Real deployment — requires BOTH flags:
  myvenv/bin/python manage.py deploy_payroll_vault --broadcast --yes-mainnet
"""
import json
import time
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

SAFE = "0xF29A418744E793973BF4eEc676F8a30B2793b623"  # 3-of-5, owner

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
    help = "Deploy ConfioPayrollVault to BSC via the KMS sponsor"

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

        cusd_plus = getattr(settings, "CUSD_PLUS_VAULT_ADDRESS", "") or ""
        if not cusd_plus:
            raise CommandError("CUSD_PLUS_VAULT_ADDRESS not configured")

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
        self.stdout.write(f"Chain {chain_id} · balance {balance/1e18:.6f} BNB · nonce {nonce} · gasPrice {gas_price/1e9:.3f} gwei")
        self.stdout.write(f"cusdPlusVault = {cusd_plus}")
        self.stdout.write(f"owner (Safe)  = {SAFE}")

        art = json.loads((ARTIFACTS / "ConfioPayrollVault.sol" / "ConfioPayrollVault.json").read_text())
        bytecode = bytes.fromhex(art["bytecode"]["object"].removeprefix("0x"))
        ctor_args = abi_encode(
            ["address", "address"],
            [cusd_plus, SAFE],
        )
        data = bytecode + ctor_args

        vault_addr = to_checksum_address(
            keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce]))[-20:]
        )
        gas_est = int(_rpc(rpc_url, "eth_estimateGas", [{"from": deployer, "data": "0x" + data.hex()}]), 16)
        total_cost = gas_est * gas_price
        self.stdout.write("")
        self.stdout.write(f"payroll vault → {vault_addr}  (~{gas_est} gas, ≈ {total_cost/1e18:.6f} BNB)")

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
        if got != vault_addr:
            raise CommandError(f"address mismatch: {got} != {vault_addr}")

        # Read back the wiring as a post-deploy sanity check
        def call_addr(sig):
            selector = keccak(text=sig)[:4]
            out = _rpc(rpc_url, "eth_call", [{"to": got, "data": "0x" + selector.hex()}, "latest"])
            return to_checksum_address("0x" + out[-40:])

        self.stdout.write(self.style.SUCCESS(f"\nDEPLOYED. ConfioPayrollVault: {got}"))
        self.stdout.write(f"  CUSD_PLUS    = {call_addr('CUSD_PLUS()')}")
        self.stdout.write(f"  owner        = {call_addr('owner()')}")
        self.stdout.write("Next: add BSC_PAYROLL_VAULT_ADDRESS to .env.mainnet, BscScan verify, record in DEPLOYMENT.md.")
