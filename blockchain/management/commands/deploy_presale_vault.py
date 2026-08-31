"""
Deploy ConfioPresaleVault to BSC via the KMS sponsor.

Same KMS-creation-tx flow as deploy_cusd_plus_vault (the sponsor key is
non-extractable, so forge --broadcast is not an option). Single contract,
non-upgradeable, no proxy.

Curve "A" (locked): 0–4M @ $0.20→0.30, 4–24M @ $0.30→0.70,
24–74M @ $0.70→1.30 — payment token cUSD (18dp), prices in cUSD base
units per whole CONFIO.

The four required snapshot values must be captured after pausing the old BSC
vault. Their exact reconciliation is enforced by the constructor.

Usage:
  # Dry run — builds the txn, estimates gas, broadcasts NOTHING (default):
  myvenv/bin/python manage.py deploy_presale_vault \
    --initial-sold <wei> --initial-claimed <wei> \
    --initial-migrated-pool <wei> --initial-legacy-pool <wei>

  # Real deployment — requires BOTH flags:
  myvenv/bin/python manage.py deploy_presale_vault --broadcast --yes-mainnet
"""
import json
import re
import time
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

SAFE = "0xF29A418744E793973BF4eEc676F8a30B2793b623"  # 3-of-5, owner
SOLD_BREAKPOINTS = [4_000_000 * 10**18, 24_000_000 * 10**18, 74_000_000 * 10**18]
PRICES = [int(0.2e18), int(0.3e18), int(0.7e18), int(1.3e18)]

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
    help = "Deploy ConfioPresaleVault to BSC via the KMS sponsor"

    def add_arguments(self, parser):
        parser.add_argument("--broadcast", action="store_true", help="Actually send the transaction")
        parser.add_argument("--yes-mainnet", action="store_true", help="Required alongside --broadcast to confirm mainnet")
        parser.add_argument("--initial-sold", type=int, required=True)
        parser.add_argument("--initial-claimed", type=int, required=True)
        parser.add_argument("--initial-migrated-pool", type=int, required=True)
        parser.add_argument("--initial-legacy-pool", type=int, required=True)

    def handle(self, *args, **options):
        from eth_abi import encode as abi_encode
        from eth_utils import keccak, to_checksum_address
        import rlp

        from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings

        signer = get_bsc_sponsor_signer_from_settings()
        rpc_url = settings.BSC_RPC_URL
        chain_id = settings.BSC_CHAIN_ID
        deployer = signer.address

        initial_sold = options["initial_sold"]
        initial_claimed = options["initial_claimed"]
        initial_migrated_pool = options["initial_migrated_pool"]
        initial_legacy_pool = options["initial_legacy_pool"]
        if initial_sold > SOLD_BREAKPOINTS[-1]:
            raise CommandError("initialSold exceeds TOKENS_FOR_SALE — check the source")
        if initial_claimed + initial_migrated_pool + initial_legacy_pool != initial_sold:
            raise CommandError(
                "snapshot does not reconcile: claimed + migratedPool + legacyPool must equal totalSold"
            )
        payment = getattr(settings, "CUSD_VAULT_ADDRESS", "") or ""
        if not payment:
            raise CommandError("CUSD_VAULT_ADDRESS not configured")
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", payment):
            raise CommandError(f"CUSD_VAULT_ADDRESS is invalid: {payment!r}")
        on_chain_id = int(_rpc(rpc_url, "eth_chainId", []), 16)
        if on_chain_id != int(chain_id):
            raise CommandError(
                f"RPC reports chain {on_chain_id}, settings say {chain_id} — refusing to deploy")
        if _rpc(rpc_url, "eth_getCode", [payment, "latest"]) in (None, "0x", "0x0"):
            raise CommandError(f"cUSD {payment} has no contract code")

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
        self.stdout.write(f"initialSold = {initial_sold} ({initial_sold/1e18:.6f} CONFIO)")
        self.stdout.write(f"initialClaimed = {initial_claimed/1e18:.6f} CONFIO")
        self.stdout.write(f"initialMigratedPool = {initial_migrated_pool/1e18:.6f} CONFIO")
        self.stdout.write(f"initialLegacyPool = {initial_legacy_pool/1e18:.6f} CONFIO")
        self.stdout.write(f"Owner (Safe) = {SAFE} · sponsor = {deployer} · payment = cUSD {payment}")

        art = json.loads((ARTIFACTS / "ConfioPresaleVault.sol" / "ConfioPresaleVault.json").read_text())
        abi = art.get("abi", [])
        ctor = next((x for x in abi if x.get("type") == "constructor"), None)
        ctor_arity = len(ctor.get("inputs", [])) if ctor else 0
        if ctor_arity != 9:
            raise CommandError(
                f"artifact constructor takes {ctor_arity} args, expected 9 — rebuild with `forge build`")
        for getter in ("PAYMENT_TOKEN", "totalSold", "totalClaimed", "migratedPool", "legacyPool"):
            if not any(x.get("type") == "function" and x.get("name") == getter for x in abi):
                raise CommandError(f"artifact has no {getter}() — stale build")
        bytecode = bytes.fromhex(art["bytecode"]["object"].removeprefix("0x"))
        ctor_args = abi_encode(
            ["address", "address", "uint256[]", "uint256[]", "uint256", "uint256", "uint256", "uint256", "address"],
            [SAFE, payment, SOLD_BREAKPOINTS, PRICES, initial_sold, initial_claimed,
             initial_migrated_pool, initial_legacy_pool, deployer],
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

        def call_addr(sig):
            selector = keccak(text=sig)[:4]
            out = _rpc(rpc_url, "eth_call", [{"to": got, "data": "0x" + selector.hex()}, "latest"])
            return to_checksum_address("0x" + out[-40:])

        price = call("currentPrice()")
        sold = call("totalSold()")
        pool = call("migratedPool()")
        legacy_pool = call("legacyPool()")
        claimed = call("totalClaimed()")
        payment_observed = call_addr("PAYMENT_TOKEN()")
        if (sold, claimed, pool, legacy_pool, payment_observed.lower()) != (
            initial_sold, initial_claimed, initial_migrated_pool,
            initial_legacy_pool, to_checksum_address(payment).lower(),
        ):
            raise CommandError("deployed presale snapshot/wiring does not match requested values")
        self.stdout.write(self.style.SUCCESS(f"\nDEPLOYED. ConfioPresaleVault: {got}"))
        self.stdout.write(f"  currentPrice = {price/1e18:.6f} cUSD/CONFIO")
        self.stdout.write(f"  totalSold    = {sold/1e18:.6f} CONFIO")
        self.stdout.write(f"  totalClaimed = {claimed/1e18:.6f} CONFIO")
        self.stdout.write(f"  migratedPool = {pool/1e18:.6f} CONFIO")
        self.stdout.write(f"  legacyPool   = {legacy_pool/1e18:.6f} CONFIO")
        self.stdout.write(f"  paymentToken = {payment_observed}")
        self.stdout.write(
            "Next: DO NOT switch BSC_PRESALE_VAULT_ADDRESS yet. Safe-call "
            "creditLegacy() for every snapshotted predecessor buyer, verify "
            "legacyPool()==0 and every purchased(address), fund the outstanding "
            "CONFIO liability, then update config and DEPLOYMENT.md."
        )
