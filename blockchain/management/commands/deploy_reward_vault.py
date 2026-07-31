"""
Deploy ConfioRewardVault to BSC via the KMS sponsor.

Same KMS-creation-tx flow as deploy_presale_vault (the sponsor key is
non-extractable, so forge --broadcast is not an option). Single contract,
non-upgradeable, no proxy.

Constructor: (confio, attestor, owner)
  - confio    = BSC_CONFIO_TOKEN_ADDRESS (re-issued CONFIO BEP-20)
  - attestor  = the backend hot key that writes per-user eligibility;
                defaults to the KMS sponsor (--attestor to override)
  - owner     = the 3-of-5 Safe (price, attestor rotation, withdrawSurplus,
                cancelEligibility, pause)

Funding is SEPARATE: after deploy the Safe transfers CONFIO into the vault.
Reward fund is 7,400,000 CONFIO total across ALL chains (tokenomics §3);
the live Algorand vault (app 3361825928) has already committed ~2,250, so
fund a WORKING TRANCHE here, never the whole fund behind the hot attestor.

Usage:
  # Dry run — builds the txn, estimates gas, broadcasts NOTHING (default):
  myvenv/bin/python manage.py deploy_reward_vault

  # Real deployment — requires BOTH flags:
  myvenv/bin/python manage.py deploy_reward_vault --broadcast --yes-mainnet
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
    help = "Deploy ConfioRewardVault to BSC via the KMS sponsor"

    def add_arguments(self, parser):
        parser.add_argument("--broadcast", action="store_true", help="Actually send the transaction")
        parser.add_argument("--yes-mainnet", action="store_true", help="Required alongside --broadcast to confirm mainnet")
        parser.add_argument("--attestor", help="Attestor address (default: BSC_SPONSOR_ADDRESS)")

    def handle(self, *args, **options):
        from eth_abi import encode as abi_encode
        from eth_utils import keccak, to_checksum_address
        import rlp

        from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings

        signer = get_bsc_sponsor_signer_from_settings()
        rpc_url = settings.BSC_RPC_URL
        chain_id = settings.BSC_CHAIN_ID
        deployer = signer.address

        confio = getattr(settings, "BSC_CONFIO_TOKEN_ADDRESS", "") or ""
        if not confio:
            raise CommandError("BSC_CONFIO_TOKEN_ADDRESS not configured")
        attestor = options.get("attestor") or getattr(settings, "BSC_SPONSOR_ADDRESS", "") or ""
        if not attestor:
            raise CommandError("no attestor: pass --attestor or set BSC_SPONSOR_ADDRESS")

        balance = int(_rpc(rpc_url, "eth_getBalance", [deployer, "latest"]), 16)
        nonce = int(_rpc(rpc_url, "eth_getTransactionCount", [deployer, "latest"]), 16)
        gas_price = max(int(_rpc(rpc_url, "eth_gasPrice", []), 16), 1_000_000_000)

        self.stdout.write(f"Deployer (KMS sponsor): {deployer}")
        self.stdout.write(f"Chain {chain_id} · balance {balance/1e18:.6f} BNB · nonce {nonce} · gasPrice {gas_price/1e9:.3f} gwei")
        self.stdout.write(f"confio       = {confio}")
        self.stdout.write(f"attestor     = {attestor}")
        self.stdout.write(f"owner (Safe) = {SAFE}")

        art = json.loads((ARTIFACTS / "ConfioRewardVault.sol" / "ConfioRewardVault.json").read_text())
        bytecode = bytes.fromhex(art["bytecode"]["object"].removeprefix("0x"))
        ctor_args = abi_encode(
            ["address", "address", "address"],
            [confio, attestor, SAFE],
        )
        data = bytecode + ctor_args

        vault_addr = to_checksum_address(
            keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce]))[-20:]
        )
        gas_est = int(_rpc(rpc_url, "eth_estimateGas", [{"from": deployer, "data": "0x" + data.hex()}]), 16)
        total_cost = gas_est * gas_price
        self.stdout.write("")
        self.stdout.write(f"reward vault → {vault_addr}  (~{gas_est} gas, ≈ {total_cost/1e18:.6f} BNB)")

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

        self.stdout.write(self.style.SUCCESS(f"\nDEPLOYED. ConfioRewardVault: {got}"))
        self.stdout.write(f"  CONFIO   = {call_addr('CONFIO()')}")
        self.stdout.write(f"  signer   = {call_addr('signer()')}")
        self.stdout.write(f"  owner    = {call_addr('owner()')}")
        self.stdout.write("Next: add BSC_REWARD_VAULT_ADDRESS to .env.mainnet, BscScan verify, record in DEPLOYMENT.md.")
