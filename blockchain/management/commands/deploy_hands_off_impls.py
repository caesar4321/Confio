"""
Deploy the three logic contracts of the hands-off Cuenta inteligente to BSC via
the KMS sponsor (docs/designs/hands-off-account.md, docs/deploy/hands-off-v2-deploy.md):

  1. ConfioSmartAccountV2           the v2 account implementation (clones are never upgraded)
  2. ConfioSmartAccountFactory      the factory's new logic (the Safe upgrades the proxy to it)
  3. ConfioMarketEscrow             the escrow's new logic (depositFrom)

Only logic contracts: the Safe installs them afterwards in ONE batch (factory
upgradeToAndCall(initializeV2(v2)) + setTradePaused(true) + escrow
upgradeToAndCall(setAccountFactory(factory))). Nothing here touches a proxy.

The production relay signs from the same KMS account: a broadcast takes the
shared sponsor nonce lock and must run on the production host, like
deploy_cusd_impl. Each artifact must be built from this checkout's source
(its metadata keccak is compared). The deployments are written to --record
(default .kms-local/kms_evm_multisig/hands_off_impls_deploy_bsc.json, gitignored).

Usage:
  # Dry run — builds the three transactions, estimates gas, broadcasts NOTHING (default):
  myvenv/bin/python manage.py deploy_hands_off_impls

  # Real deployment — requires BOTH flags:
  myvenv/bin/python manage.py deploy_hands_off_impls --broadcast --yes-mainnet
"""
import json
import time
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# Mirrors contracts/smart_account/script/DeploySmartAccountV2.s.sol (and the live v1 implementation's arguments).
SAFE = "0xF29A418744E793973BF4eEc676F8a30B2793b623"
CUSD = "0x6101cC370635cF2c7f2725EaB010aC407A8d543F"
CUSD_PLUS = "0x3C29417eb4314155e63d4C7D4507852b87763Ed1"
USDT = "0x55d398326f99059fF775485246999027B3197955"
STOCK_ROUTER = "0x40c8e134BCAf44EEf9e7D184846F36c9862329c3"
BTCB = "0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c"
XAUT = "0x21cAef8A43163Eea865baeE23b9C2E327696A3bf"
BTC_USD_FEED = "0x264990fbd0A4796A3E3d8E37C4d5F87a3aCa5Ebf"
XAU_USD_FEED = "0x86896fEB19D8A607c3b11f2aF50A0f239Bd71CD0"

BASE = Path(settings.BASE_DIR) / "contracts"
RECORD = Path(settings.BASE_DIR) / ".kms-local" / "kms_evm_multisig" / "hands_off_impls_deploy_bsc.json"


def _rpc(url: str, method: str, params: list):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    req = urllib.request.Request(url, data=payload.encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    if "error" in body:
        raise RuntimeError(f"rpc {method}: {body['error']}")
    return body["result"]


def _artifact(package: str, source: str, name: str) -> dict:
    """The forge artifact, refused unless it was built from this checkout's source."""
    from eth_utils import keccak
    path = BASE / package / "out" / source / f"{name}.json"
    if not path.exists():
        raise CommandError(f"no artifact {path}: run `forge build` in contracts/{package}")
    art = json.loads(path.read_text())
    meta = art["metadata"] if isinstance(art.get("metadata"), dict) else json.loads(art["rawMetadata"])
    src = BASE / package / source
    want = "0x" + keccak(src.read_bytes()).hex()
    if meta["sources"].get(source, {}).get("keccak256") != want:
        raise CommandError(f"{name} artifact is stale for {source} — rebuild (and re-scp) it")
    return art


def _address(value, label: str) -> str:
    from eth_utils import is_address, to_checksum_address
    if not value or not is_address(value):
        raise CommandError(f"{label} is not configured")
    return to_checksum_address(value)


class Command(BaseCommand):
    help = "Deploy the hands-off Cuenta inteligente logic contracts (v2 account, factory, escrow) via the KMS sponsor"

    def add_arguments(self, parser):
        parser.add_argument("--broadcast", action="store_true", help="Actually send the transactions")
        parser.add_argument("--yes-mainnet", action="store_true", help="Required alongside --broadcast to confirm mainnet")
        parser.add_argument("--record", default=str(RECORD), help="JSON record of the deployments")

    def handle(self, *args, **options):
        from eth_abi import encode as abi_encode
        from eth_utils import keccak, to_checksum_address
        import rlp

        from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings
        from smart_account import chain

        signer = get_bsc_sponsor_signer_from_settings()
        rpc_url, chain_id, deployer = settings.BSC_RPC_URL, settings.BSC_CHAIN_ID, signer.address
        if int(chain_id) != 56:
            raise CommandError(f"BSC mainnet only (chain {chain_id})")

        factory = _address(chain.factory_address(), "SMART_ACCOUNT_FACTORY_ADDRESS")
        escrow = _address(getattr(settings, "MARKETPLACE_ESCROW_ADDRESS", ""), "MARKETPLACE_ESCROW_ADDRESS")
        swap_router = _address(chain.swap_router_address(), "CRYPTO_SWAP_ROUTER_ADDRESS")
        confio = _address(chain.confio_address(), "BSC_CONFIO_TOKEN_ADDRESS")
        collector = _address(getattr(settings, "SMART_ACCOUNT_FEE_COLLECTOR_ADDRESS", ""),
                             "SMART_ACCOUNT_FEE_COLLECTOR_ADDRESS")

        def call(to, signature, out_types=("address",)):
            from eth_abi import decode as abi_decode
            data = "0x" + keccak(text=signature)[:4].hex()
            raw = _rpc(rpc_url, "eth_call", [{"to": to, "data": data}, "latest"])
            return abi_decode(list(out_types), bytes.fromhex(raw[2:]))[0]

        # The factory these logic contracts are for: Safe-owned, with the same immutables.
        if to_checksum_address(call(factory, "owner()")) != SAFE:
            raise CommandError("factory is not owned by the Safe")
        if (to_checksum_address(call(factory, "CUSD_PLUS()")) != CUSD_PLUS
                or to_checksum_address(call(factory, "STOCK_ROUTER()")) != STOCK_ROUTER):
            raise CommandError("factory immutables differ from the constants here")

        v2_args = (["address"] * 13,
                   [factory, CUSD, CUSD_PLUS, USDT, confio, STOCK_ROUTER, swap_router, collector,
                    BTCB, BTC_USD_FEED, XAUT, XAU_USD_FEED, escrow])
        plan = [
            ("ConfioSmartAccountV2", _artifact("smart_account", "ConfioSmartAccountV2.sol", "ConfioSmartAccountV2"),
             v2_args),
            ("ConfioSmartAccountFactory",
             _artifact("smart_account", "ConfioSmartAccountFactory.sol", "ConfioSmartAccountFactory"),
             (["address", "address"], [CUSD_PLUS, STOCK_ROUTER])),
            ("ConfioMarketEscrow", _artifact("cusd_plus", "ConfioMarketEscrow.sol", "ConfioMarketEscrow"),
             ([], [])),
        ]
        for name, art, _ in plan:
            names = {e.get("name") for e in art["abi"]}
            need = {"ConfioSmartAccountV2": {"relayTrade", "relayPurchase", "bucketOf"},
                    "ConfioSmartAccountFactory": {"migrate", "setTradePaused", "initializeV2"},
                    "ConfioMarketEscrow": {"depositFrom", "depositFromDigest", "setAccountFactory"}}[name]
            if not need.issubset(names):
                raise CommandError(f"{name} artifact lacks {sorted(need - names)} — rebuild with `forge build`")

        balance = int(_rpc(rpc_url, "eth_getBalance", [deployer, "latest"]), 16)
        nonce = int(_rpc(rpc_url, "eth_getTransactionCount", [deployer, "pending"]), 16)
        gas_price = max(int(_rpc(rpc_url, "eth_gasPrice", []), 16), int(settings.CUSD_PLUS_GAS_PRICE_FLOOR_WEI))
        gas_price = (gas_price * 12) // 10
        self.stdout.write(f"Deployer (KMS sponsor): {deployer}")
        self.stdout.write(f"Chain {chain_id} · balance {balance/1e18:.6f} BNB · nonce {nonce} · "
                          f"gasPrice {gas_price/1e9:.3f} gwei")
        self.stdout.write(f"factory {factory} · escrow {escrow} · swap router {swap_router} · CONFIO {confio} · "
                          f"collector {collector}")

        txs, total = [], 0
        for i, (name, art, (types, values)) in enumerate(plan):
            code = bytes.fromhex(art["bytecode"]["object"].removeprefix("0x"))
            runtime = bytes.fromhex(art["deployedBytecode"]["object"].removeprefix("0x"))
            if len(runtime) > 24_576:
                raise CommandError(f"{name} runtime is {len(runtime)} bytes: over EIP-170")
            data = code + (abi_encode(types, values) if types else b"")
            gas = int(_rpc(rpc_url, "eth_estimateGas", [{"from": deployer, "data": "0x" + data.hex()}]), 16)
            at = to_checksum_address(keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce + i]))[-20:])
            txs.append((name, data, gas, types, values))
            total += gas * gas_price
            self.stdout.write(f"{name} → {at}  ({len(runtime)} bytes runtime, ~{gas} gas)")
        self.stdout.write(f"\nTotal ≈ {total/1e18:.6f} BNB")

        if not options["broadcast"]:
            self.stdout.write(self.style.WARNING("\nDRY RUN — nothing broadcast. Re-run with --broadcast --yes-mainnet "
                                                 "to deploy."))
            return
        if not options["yes_mainnet"]:
            raise CommandError("--broadcast requires --yes-mainnet to confirm a real mainnet deployment.")
        if balance < total * 13 // 10:
            raise CommandError(f"Insufficient BNB: have {balance/1e18:.6f}, need ~{total*1.3/1e18:.6f}")
        from cusd_plus.sponsor_7702 import PolicyError, require_shared_nonce_lock
        try:
            require_shared_nonce_lock()
        except PolicyError:
            raise CommandError(
                "broadcast must run on the production host (ssh confio-prod): no fresh relay heartbeat in this "
                "process's cache, so the sponsor nonce lock would not be shared with the relay")

        from django.core.cache import cache
        from cusd_plus.sponsor_7702 import acquire_sponsor_nonce_lock, release_sponsor_nonce_lock

        deployed = {}
        for name, data, gas, types, values in txs:
            token = acquire_sponsor_nonce_lock(ttl_s=120)
            if token is None:
                raise CommandError(f"could not acquire the sponsor nonce lock before {name}; deployed so far: "
                                   f"{deployed}")
            try:
                nonce = int(_rpc(rpc_url, "eth_getTransactionCount", [deployer, "pending"]), 16)
                at = to_checksum_address(keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce]))[-20:])
                tx = {"chainId": chain_id, "nonce": nonce, "gasPrice": gas_price, "gas": int(gas * 13 // 10),
                      "to": b"", "value": 0, "data": "0x" + data.hex()}
                raw, _ = signer.sign_transaction(tx)
                if cache.get("bsc_sponsor_nonce_lock") != token:
                    raise CommandError(f"lost the sponsor nonce lock; {name} not sent; deployed so far: {deployed}")
                sent = _rpc(rpc_url, "eth_sendRawTransaction", [raw])
            finally:
                release_sponsor_nonce_lock(token)
            self.stdout.write(f"\n{name}: sent {sent}")
            receipt = None
            for _ in range(90):
                receipt = _rpc(rpc_url, "eth_getTransactionReceipt", [sent])
                if receipt:
                    break
                time.sleep(2)
            if not receipt or receipt["status"] != "0x1":
                raise CommandError(f"{name} deploy failed or timed out: {sent}; deployed so far: {deployed}")
            got = to_checksum_address(receipt["contractAddress"])
            if got != at:
                raise CommandError(f"{name} address mismatch: {got} != {at}")
            deployed[name] = {"address": got, "tx": sent, "block": int(receipt["blockNumber"], 16), "nonce": nonce,
                              "constructor_args": "0x" + (abi_encode(types, values).hex() if types else "")}

        # Read back what the Safe will install: never a contract wired to anything else.
        v2 = deployed["ConfioSmartAccountV2"]["address"]
        if (to_checksum_address(call(v2, "FACTORY()")) != factory or to_checksum_address(call(v2, "ESCROW()")) != escrow
                or call(v2, "VERSION()", ("uint256",)) != 2):
            raise CommandError("v2 implementation read-back differs: do NOT install it")
        logic = deployed["ConfioSmartAccountFactory"]["address"]
        if to_checksum_address(call(logic, "CUSD_PLUS()")) != CUSD_PLUS:
            raise CommandError("factory logic read-back differs: do NOT install it")
        self.stdout.write(self.style.SUCCESS("\nDEPLOYED:"))
        for name, row in deployed.items():
            self.stdout.write(f"  {name}: {row['address']}")
        record = Path(options["record"])
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({"network": "bsc", "chain_id": chain_id, "deployer": deployer,
                                      "deployed": deployed}, indent=2) + "\n")
        self.stdout.write(f"Record: {record}")
        self.stdout.write("Then: the Safe batch in docs/deploy/hands-off-v2-deploy.md (factory upgradeToAndCall("
                          "initializeV2) + setTradePaused(true) + escrow upgradeToAndCall(setAccountFactory)), and "
                          "set SMART_ACCOUNT_V2_IMPLEMENTATION_ADDRESS only after the canary.")
