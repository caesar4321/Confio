"""
Deploy ConfioPresaleVault to BSC via the KMS sponsor.

Same KMS-creation-tx flow as deploy_cusd_plus_vault (the sponsor key is
non-extractable, so forge --broadcast is not an option). Single contract,
non-upgradeable, no proxy.

Curve "A" (locked): 0–4M @ $0.20→0.30, 4–24M @ $0.30→0.70,
24–74M @ $0.70→1.30 — payment token USDT (18dp), prices in USDT base
units per whole CONFIO.

INITIAL_SOLD is read LIVE from the Algorand presale app's `confio_sold`
global (6dp → scaled to 1e18) at run time — the Algorand sale is still
active, so the number moves; any delta sold after this deploy is added
later via expandMigratedPool(). Use --initial-sold to override.

Usage:
  # Dry run — builds the txn, estimates gas, broadcasts NOTHING (default):
  myvenv/bin/python manage.py deploy_presale_vault

  # Real deployment — requires BOTH flags:
  myvenv/bin/python manage.py deploy_presale_vault --broadcast --yes-mainnet
"""
import json
import time
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

SAFE = "0xF29A418744E793973BF4eEc676F8a30B2793b623"  # 3-of-5, owner
USDT = "0x55d398326f99059fF775485246999027B3197955"  # Binance-Peg BSC-USD, 18dp

SOLD_BREAKPOINTS = [4_000_000 * 10**18, 24_000_000 * 10**18, 74_000_000 * 10**18]
PRICES = [int(0.2e18), int(0.3e18), int(0.7e18), int(1.3e18)]

ALGOD_URL = "https://mainnet-api.algonode.cloud"

ARTIFACTS = Path(settings.BASE_DIR) / "contracts" / "cusd_plus" / "out"


def _rpc(url: str, method: str, params: list):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    req = urllib.request.Request(url, data=payload.encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    if "error" in body:
        raise RuntimeError(f"rpc {method}: {body['error']}")
    return body["result"]


def _algorand_confio_sold(app_id: int) -> int:
    """Read `confio_sold` (6dp) from the Algorand presale app's global state."""
    import base64
    with urllib.request.urlopen(f"{ALGOD_URL}/v2/applications/{app_id}", timeout=30) as resp:
        app = json.loads(resp.read())
    for kv in app["params"]["global-state"]:
        if base64.b64decode(kv["key"]) == b"confio_sold":
            return int(kv["value"]["uint"])
    raise RuntimeError("confio_sold not found in Algorand app global state")


class Command(BaseCommand):
    help = "Deploy ConfioPresaleVault to BSC via the KMS sponsor"

    def add_arguments(self, parser):
        parser.add_argument("--broadcast", action="store_true", help="Actually send the transaction")
        parser.add_argument("--yes-mainnet", action="store_true", help="Required alongside --broadcast to confirm mainnet")
        parser.add_argument("--initial-sold", type=int, default=None,
                            help="Override initialSold in 1e18 base units (default: live Algorand confio_sold × 1e12)")

    def handle(self, *args, **options):
        from eth_abi import encode as abi_encode
        from eth_utils import keccak, to_checksum_address
        import rlp

        from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings

        signer = get_bsc_sponsor_signer_from_settings()
        rpc_url = settings.BSC_RPC_URL
        chain_id = settings.BSC_CHAIN_ID
        deployer = signer.address

        # initialSold: live Algorand read (6dp → 1e18) unless overridden
        if options["initial_sold"] is not None:
            initial_sold = options["initial_sold"]
            source = "override"
        else:
            app_id = int(getattr(settings, "ALGORAND_PRESALE_APP_ID", 0) or 0)
            if not app_id:
                raise CommandError("ALGORAND_PRESALE_APP_ID not configured and no --initial-sold given")
            sold_6dp = _algorand_confio_sold(app_id)
            initial_sold = sold_6dp * 10**12
            source = f"Algorand app {app_id} (confio_sold={sold_6dp})"
        if initial_sold > SOLD_BREAKPOINTS[-1]:
            raise CommandError("initialSold exceeds TOKENS_FOR_SALE — check the source")

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
        self.stdout.write(f"initialSold = {initial_sold} ({initial_sold/1e18:.6f} CONFIO) from {source}")
        self.stdout.write(f"Owner (Safe) = {SAFE} · sponsor = {deployer} · payment = USDT")

        art = json.loads((ARTIFACTS / "ConfioPresaleVault.sol" / "ConfioPresaleVault.json").read_text())
        bytecode = bytes.fromhex(art["bytecode"]["object"].removeprefix("0x"))
        ctor_args = abi_encode(
            ["address", "address", "uint256[]", "uint256[]", "uint256", "address"],
            [SAFE, USDT, SOLD_BREAKPOINTS, PRICES, initial_sold, deployer],
        )
        data = bytecode + ctor_args

        vault_addr = to_checksum_address(
            keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce]))[-20:]
        )
        gas_est = int(_rpc(rpc_url, "eth_estimateGas", [{"from": deployer, "data": "0x" + data.hex()}]), 16)
        total_cost = gas_est * gas_price
        self.stdout.write("")
        self.stdout.write(f"vault → {vault_addr}  (~{gas_est} gas, ≈ {total_cost/1e18:.6f} BNB)")

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

        # Read back the seeded curve as a post-deploy sanity check
        def call(sig):
            selector = keccak(text=sig)[:4]
            return int(_rpc(rpc_url, "eth_call", [{"to": got, "data": "0x" + selector.hex()}, "latest"]), 16)

        price = call("currentPrice()")
        sold = call("totalSold()")
        pool = call("migratedPool()")
        self.stdout.write(self.style.SUCCESS(f"\nDEPLOYED. ConfioPresaleVault: {got}"))
        self.stdout.write(f"  currentPrice = {price/1e18:.6f} USDT/CONFIO")
        self.stdout.write(f"  totalSold    = {sold/1e18:.6f} CONFIO")
        self.stdout.write(f"  migratedPool = {pool/1e18:.6f} CONFIO")
        self.stdout.write("Next: add BSC_PRESALE_VAULT_ADDRESS to .env.mainnet, BscScan verify, record in DEPLOYMENT.md.")
