"""
Deploy a cUSD (CusdVault) implementation to BSC via the KMS sponsor.

Only the logic contract: the Safe installs it on the live proxy afterwards
with upgradeToAndCall. Refuses an artifact without the address freeze or the
Cuenta inteligente factory set (setSmartAccountFactory, spec decision 32).

The production relay signs from the same KMS account: a broadcast takes the
shared sponsor nonce lock and must run on the production host, like
deploy_stock_router_v3. The deployment is written to --record (default
.kms-local/kms_evm_multisig/cusd_impl_deploy_bsc.json, gitignored) for the
Safe transaction builder.

Same KMS-creation-tx flow as deploy_presale_vault (non-extractable key).

Usage:
  # Dry run — builds the txn, estimates gas, broadcasts NOTHING (default):
  myvenv/bin/python manage.py deploy_cusd_impl

  # Real deployment — requires BOTH flags:
  myvenv/bin/python manage.py deploy_cusd_impl --broadcast --yes-mainnet
"""
import json
import time
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

USDT = "0x55d398326f99059fF775485246999027B3197955"  # immutable in the implementation

ARTIFACTS = Path(settings.BASE_DIR) / "contracts" / "cusd_plus" / "out"
RECORD = Path(settings.BASE_DIR) / ".kms-local" / "kms_evm_multisig" / "cusd_impl_deploy_bsc.json"


def _rpc(url: str, method: str, params: list):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    req = urllib.request.Request(url, data=payload.encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    if "error" in body:
        raise RuntimeError(f"rpc {method}: {body['error']}")
    return body["result"]


class Command(BaseCommand):
    help = "Deploy a CusdVault implementation to BSC via the KMS sponsor"

    def add_arguments(self, parser):
        parser.add_argument("--broadcast", action="store_true", help="Actually send the transaction")
        parser.add_argument("--yes-mainnet", action="store_true", help="Required alongside --broadcast to confirm mainnet")
        parser.add_argument("--record", default=str(RECORD), help="JSON record of the deployment")

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
        nonce = int(_rpc(rpc_url, "eth_getTransactionCount", [deployer, "pending"]), 16)
        # Floor + 1.2x inclusion buffer, same knob the sponsored paths use
        # (CUSD_PLUS_GAS_PRICE_FLOOR_WEI). This was a hardcoded 1 gwei — 20x
        # BSC's resting price — which burned ~$20 of gas across the July 2026
        # migration deploys before the 2026-08-03 sponsor audit caught it.
        gas_price = max(int(_rpc(rpc_url, "eth_gasPrice", []), 16),
                        int(settings.CUSD_PLUS_GAS_PRICE_FLOOR_WEI))
        gas_price = (gas_price * 12) // 10

        self.stdout.write(f"Deployer (KMS sponsor): {deployer}")
        self.stdout.write(f"Chain {chain_id} · balance {balance/1e18:.6f} BNB · nonce {nonce} · gasPrice {gas_price/1e9:.3f} gwei")
        self.stdout.write(f"USDT = {USDT}")

        art = json.loads((ARTIFACTS / "CusdVault.sol" / "CusdVault.json").read_text())
        names = {e.get("name") for e in art["abi"]}
        if not {"freezeAddress", "setSmartAccountFactory", "isSmartAccountFactory"}.issubset(names):
            raise CommandError("artifact has no freezeAddress()/setSmartAccountFactory() — rebuild with `forge build`")
        # The artifact must be built from this checkout's CusdVault.sol.
        meta = art["metadata"] if isinstance(art.get("metadata"), dict) else json.loads(art["rawMetadata"])
        src = Path(settings.BASE_DIR) / "contracts" / "cusd_plus" / "CusdVault.sol"
        if "0x" + keccak(src.read_bytes()).hex() != meta["sources"]["CusdVault.sol"]["keccak256"]:
            raise CommandError("CusdVault artifact is stale for CusdVault.sol — rebuild (and re-scp) it")
        bytecode = bytes.fromhex(art["bytecode"]["object"].removeprefix("0x"))
        data = bytecode + abi_encode(["address"], [USDT])

        impl_addr = to_checksum_address(
            keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce]))[-20:]
        )
        gas_est = int(_rpc(rpc_url, "eth_estimateGas", [{"from": deployer, "data": "0x" + data.hex()}]), 16)
        total_cost = gas_est * gas_price
        self.stdout.write("")
        self.stdout.write(f"implementation → {impl_addr}  (~{gas_est} gas, ≈ {total_cost/1e18:.6f} BNB)")

        if not options["broadcast"]:
            self.stdout.write(self.style.WARNING("\nDRY RUN — nothing broadcast. Re-run with --broadcast --yes-mainnet to deploy."))
            return
        if not options["yes_mainnet"]:
            raise CommandError("--broadcast requires --yes-mainnet to confirm a real mainnet deployment.")
        if balance < total_cost * 13 // 10:
            raise CommandError(f"Insufficient BNB: have {balance/1e18:.6f}, need ~{total_cost*1.3/1e18:.6f}")
        from cusd_plus.sponsor_7702 import PolicyError, require_shared_nonce_lock
        try:
            require_shared_nonce_lock()
        except PolicyError:
            raise CommandError(
                "broadcast must run on the production host (ssh confio-prod): no fresh relay heartbeat "
                "in this process's cache, so the sponsor nonce lock would not be shared with the relay")

        from django.core.cache import cache

        from cusd_plus.sponsor_7702 import acquire_sponsor_nonce_lock, release_sponsor_nonce_lock

        token = acquire_sponsor_nonce_lock(ttl_s=120)
        if token is None:
            raise CommandError("could not acquire the sponsor nonce lock; retry")
        try:
            nonce = int(_rpc(rpc_url, "eth_getTransactionCount", [deployer, "pending"]), 16)
            impl_addr = to_checksum_address(
                keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce]))[-20:]
            )
            tx = {"chainId": chain_id, "nonce": nonce, "gasPrice": gas_price,
                  "gas": int(gas_est * 13 // 10), "to": b"", "value": 0, "data": "0x" + data.hex()}
            raw, txh = signer.sign_transaction(tx)
            if cache.get("bsc_sponsor_nonce_lock") != token:
                raise CommandError("lost the sponsor nonce lock; nothing was sent, retry")
            sent = _rpc(rpc_url, "eth_sendRawTransaction", [raw])
        finally:
            release_sponsor_nonce_lock(token)
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
        if got != impl_addr:
            raise CommandError(f"address mismatch: {got} != {impl_addr}")

        calldata = keccak(text="USDT()")[:4]
        out = _rpc(rpc_url, "eth_call", [{"to": got, "data": "0x" + calldata.hex()}, "latest"])
        if to_checksum_address("0x" + out[-40:]) != USDT:
            raise CommandError(f"USDT read back {out}: do NOT install this implementation")
        self.stdout.write(self.style.SUCCESS(f"\nDEPLOYED. CusdVault implementation: {got}"))
        record = Path(options["record"])
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({
            "network": "bsc", "chain_id": chain_id, "deployer": deployer, "implementation": got,
            "tx": sent, "block": int(receipt["blockNumber"], 16), "nonce": nonce,
            "constructor_args": "0x" + abi_encode(["address"], [USDT]).hex(),
        }, indent=2) + "\n")
        self.stdout.write(f"Record: {record}")
        self.stdout.write(
            "Verify (in contracts/cusd_plus): forge verify-contract "
            f"{got} CusdVault.sol:CusdVault --chain bsc --compiler-version v0.8.26+commit.8a97fa7a "
            f"--num-of-optimizations 200 --constructor-args 0x{abi_encode(['address'], [USDT]).hex()} "
            '--etherscan-api-key "$ETHERSCAN_API_KEY" --watch')
        self.stdout.write("Then: the Safe tx builder (build_smart_account_cusd_upgrade.py), its fork replay, "
                          "Safe upgradeToAndCall, and re-link the cUSD proxy on BscScan.")
