"""
Deploy CusdPlusVault (impl + ERC1967 proxy) to BSC via the KMS sponsor.

WHY A COMMAND (not `forge script --broadcast`): the sponsor key lives in
AWS KMS and is non-extractable, so we cannot hand a raw private key to
forge. Instead we build the two contract-creation transactions from the
forge-compiled bytecode and sign each with EVMKMSSigner — the same signer
bsc_sponsor_status verifies. No throwaway deployer key ever exists (the
2026-07-10 stranded-deployer lesson).

The vault is wired to the REAL Ondo mainnet contracts and owned by the
3-of-5 Safe from block one via initialize(). The router is NOT deployed
here (its GM attestation ABI is not yet wired).

Usage:
  # Dry run — builds txns, estimates gas, broadcasts NOTHING (default):
  myvenv/bin/python manage.py deploy_cusd_plus_vault

  # Real deployment — requires BOTH flags (belt and suspenders):
  myvenv/bin/python manage.py deploy_cusd_plus_vault --broadcast --yes-mainnet

  # Implementation only (UUPS upgrade path: deploy the new impl here, then
  # the 3-of-5 Safe calls upgradeToAndCall(newImpl, "") on the proxy):
  myvenv/bin/python manage.py deploy_cusd_plus_vault --impl-only --broadcast --yes-mainnet
"""
import json
import time
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# Real BSC mainnet wiring (Ondo 2026-07-07 + on-chain verification + fork rehearsal)
USDY = "0x608593d17A2decBbc4399e4185bE4922F97eD32E"
USDT = "0x55d398326f99059fF775485246999027B3197955"
IM = "0x9bA360087075A4Cef548eeD71Eed197bf4cFA4E2"
ORACLE = "0x8aaa843b848c2E3c83956Bc09aFBE4D9Dcf297b7"
SAFE = "0xF29A418744E793973BF4eEc676F8a30B2793b623"  # 3-of-5, owner + treasury
CONFIO_YIELD_SHARE_BPS = 1500

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
    help = "Deploy CusdPlusVault (impl + proxy) to BSC via the KMS sponsor"

    def add_arguments(self, parser):
        parser.add_argument("--broadcast", action="store_true", help="Actually send the transactions")
        parser.add_argument("--yes-mainnet", action="store_true", help="Required alongside --broadcast to confirm mainnet")
        parser.add_argument("--impl-only", action="store_true",
                            help="Deploy only a new implementation (for a Safe-driven UUPS upgrade); no proxy")

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

        # ── Build the two creation payloads ──────────────────────────────
        vault_bytecode = _bytecode("CusdPlusVault", "CusdPlusVault")
        proxy_bytecode = _bytecode("ERC1967Proxy", "ERC1967Proxy")

        impl_args = abi_encode(
            ["address", "address", "address", "address", "uint256"],
            [USDY, USDT, IM, ORACLE, CONFIO_YIELD_SHARE_BPS],
        )
        impl_data = vault_bytecode + impl_args

        # impl address is deterministic: CREATE(deployer, nonce)
        impl_addr = to_checksum_address(
            keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce]))[-20:]
        )
        impl_only = options["impl_only"]
        if not impl_only:
            # initialize(address) selector + Safe
            init_selector = keccak(b"initialize(address)")[:4]
            init_calldata = init_selector + abi_encode(["address"], [SAFE])
            proxy_args = abi_encode(["address", "bytes"], [impl_addr, init_calldata])
            proxy_data = proxy_bytecode + proxy_args
            proxy_addr = to_checksum_address(
                keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce + 1]))[-20:]
            )

        # Gas estimates (eth_estimateGas from the deployer, creation = no `to`)
        impl_gas = int(_rpc(rpc_url, "eth_estimateGas", [{"from": deployer, "data": "0x" + impl_data.hex()}]), 16)
        self.stdout.write("")
        self.stdout.write(f"1) impl  → {impl_addr}  (~{impl_gas} gas)")
        if impl_only:
            self.stdout.write("   (impl-only: no proxy; Safe upgrades the existing proxy to this address)")
            total_cost = impl_gas * gas_price
        else:
            self.stdout.write(f"2) proxy → {proxy_addr}  (owner {SAFE})")
            total_cost = (impl_gas + 900_000) * gas_price  # proxy est. ~900k
        self.stdout.write(f"Est. total cost ≈ {total_cost/1e18:.6f} BNB")

        if not options["broadcast"]:
            self.stdout.write(self.style.WARNING("\nDRY RUN — nothing broadcast. Re-run with --broadcast --yes-mainnet to deploy."))
            return

        if not options["yes_mainnet"]:
            raise CommandError("--broadcast requires --yes-mainnet to confirm a real mainnet deployment.")
        if balance < total_cost:
            raise CommandError(f"Insufficient BNB: have {balance/1e18:.6f}, need ~{total_cost/1e18:.6f}")

        def send(nonce_i, data, gas, label):
            tx = {"chainId": chain_id, "nonce": nonce_i, "gasPrice": gas_price,
                  "gas": gas, "to": b"", "value": 0, "data": data}
            raw, txh = signer.sign_transaction(tx)
            sent = _rpc(rpc_url, "eth_sendRawTransaction", [raw])
            self.stdout.write(f"  {label} sent: {sent}")
            for _ in range(90):
                rec = _rpc(rpc_url, "eth_getTransactionReceipt", [sent])
                if rec:
                    if rec["status"] != "0x1":
                        raise CommandError(f"{label} FAILED: {sent}")
                    return rec["contractAddress"]
                time.sleep(2)
            raise CommandError(f"{label} timeout: {sent}")

        self.stdout.write("\nBroadcasting…")
        got_impl = send(nonce, "0x" + impl_data.hex(), int(impl_gas * 13 // 10), "impl")
        if to_checksum_address(got_impl) != impl_addr:
            raise CommandError(f"impl address mismatch: {got_impl} != {impl_addr}")
        if impl_only:
            self.stdout.write(self.style.SUCCESS(f"\nDEPLOYED. New implementation: {got_impl}"))
            self.stdout.write("Next: Safe executes upgradeToAndCall(newImpl, \"\") on the proxy, then BscScan verify.")
            return
        got_proxy = send(nonce + 1, "0x" + proxy_data.hex(), 1_200_000, "proxy")

        self.stdout.write(self.style.SUCCESS(f"\nDEPLOYED. Vault (proxy): {got_proxy}"))
        self.stdout.write("Next: BscScan verify, then send this address to Ondo for PP whitelisting.")
