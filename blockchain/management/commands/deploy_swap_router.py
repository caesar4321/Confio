"""Deploy ConfioSwapRouter (crypto & metals on PancakeSwap) via the KMS sponsor.

Two creation transactions: the implementation, then an ERC-1967 proxy
initialized with the Safe as owner. Dry run is the default; broadcasting
requires ``--broadcast --yes-mainnet``. Nothing is activated here: the 3-of-5
Safe must then register the router as a sponsor on cUSD+ and on cUSD (the
two printed calls, one multisend), and only after that are the CRYPTO_*
settings switched on (router address first, trading last).
"""
import json
import time
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

SAFE = "0xF29A418744E793973BF4eEc676F8a30B2793b623"
CUSD_PLUS_PROXY = "0x3C29417eb4314155e63d4C7D4507852b87763Ed1"
CUSD_PROXY = "0x6101cC370635cF2c7f2725EaB010aC407A8d543F"
USDT = "0x55d398326f99059fF775485246999027B3197955"
SMART_ROUTER = "0x13f4EA83D0bd40E75C8222255bc855a974568Dd4"
OUT = Path(settings.BASE_DIR) / "contracts" / "crypto_swap" / "out"
ROUTER_ARTIFACT = OUT / "ConfioSwapRouter.sol" / "ConfioSwapRouter.json"
PROXY_ARTIFACT = OUT / "ERC1967Proxy.sol" / "ERC1967Proxy.json"


def _rpc(url, method, params):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    req = urllib.request.Request(
        url, data=payload.encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    if "error" in body:
        raise RuntimeError(f"rpc {method}: {body['error']}")
    return body["result"]


class Command(BaseCommand):
    help = "Deploy ConfioSwapRouter (implementation + proxy) to BSC via KMS"

    def add_arguments(self, parser):
        parser.add_argument("--broadcast", action="store_true")
        parser.add_argument("--yes-mainnet", action="store_true")

    def handle(self, *args, **options):
        import rlp
        from eth_abi import encode as abi_encode
        from eth_utils import keccak, to_checksum_address

        from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings

        signer = get_bsc_sponsor_signer_from_settings()
        deployer = signer.address
        rpc_url = settings.BSC_RPC_URL
        chain_id = int(settings.BSC_CHAIN_ID)
        if int(_rpc(rpc_url, "eth_chainId", []), 16) != chain_id or chain_id != 56:
            raise CommandError(f"expected BSC mainnet chain 56, got {chain_id}")

        def call_at(target, sig, suffix=""):
            return _rpc(rpc_url, "eth_call", [{
                "to": target, "data": "0x" + keccak(text=sig)[:4].hex() + suffix,
            }, "latest"])

        def address_at(target, sig):
            return to_checksum_address("0x" + call_at(target, sig)[-40:])

        # Live preconditions the router's constructor and flows depend on.
        if address_at(CUSD_PLUS_PROXY, "CUSD()") != to_checksum_address(CUSD_PROXY):
            raise CommandError("cUSD+ is not wired to the expected cUSD proxy")
        if address_at(CUSD_PLUS_PROXY, "USDT()") != to_checksum_address(USDT):
            raise CommandError("cUSD+ USDT mismatch")
        for target in (CUSD_PLUS_PROXY, CUSD_PROXY):
            if address_at(target, "owner()") != to_checksum_address(SAFE):
                raise CommandError(f"{target} is not owned by the Safe")
        if _rpc(rpc_url, "eth_getCode", [SMART_ROUTER, "latest"]) in (None, "0x", "0x0"):
            raise CommandError("PancakeSwap SmartRouter has no code")

        for path in (ROUTER_ARTIFACT, PROXY_ARTIFACT):
            if not path.exists():
                raise CommandError(f"missing {path}; run forge build in contracts/crypto_swap")
        router_art = json.loads(ROUTER_ARTIFACT.read_text())
        proxy_art = json.loads(PROXY_ARTIFACT.read_text())
        names = {item.get("name") for item in router_art.get("abi", [])}
        if not {"buy", "sell", "conversionFeeBps", "sweep"}.issubset(names):
            raise CommandError("stale ConfioSwapRouter artifact; rebuild")

        def code(art):
            return bytes.fromhex(art["bytecode"]["object"].removeprefix("0x"))

        nonce = int(_rpc(rpc_url, "eth_getTransactionCount", [deployer, "pending"]), 16)
        balance = int(_rpc(rpc_url, "eth_getBalance", [deployer, "latest"]), 16)
        gas_price = max(
            int(_rpc(rpc_url, "eth_gasPrice", []), 16),
            int(settings.CUSD_PLUS_GAS_PRICE_FLOOR_WEI),
        ) * 12 // 10
        impl_addr, proxy_addr = (
            to_checksum_address(keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce + i]))[-20:])
            for i in range(2)
        )
        impl_data = code(router_art) + abi_encode(["address", "address"], [CUSD_PLUS_PROXY, SMART_ROUTER])
        init = keccak(text="initialize(address)")[:4] + abi_encode(["address"], [SAFE])
        proxy_data = code(proxy_art) + abi_encode(["address", "bytes"], [impl_addr, init])
        impl_gas = int(_rpc(rpc_url, "eth_estimateGas", [{"from": deployer, "data": "0x" + impl_data.hex()}]), 16)
        payloads = [
            ("Swap router implementation", impl_addr, impl_data, impl_gas * 13 // 10),
            ("Swap router proxy", proxy_addr, proxy_data, 1_200_000),
        ]
        total_max = sum(item[3] for item in payloads) * gas_price
        self.stdout.write(
            f"KMS deployer {deployer} · nonce {nonce} · gas {gas_price / 1e9:.3f} gwei · "
            f"max {total_max / 1e18:.6f} BNB")
        for label, address, _data, limit in payloads:
            self.stdout.write(f"  {label:<28} {address}  gasLimit={limit}")

        if options["broadcast"] and not options["yes_mainnet"]:
            raise CommandError("--broadcast requires --yes-mainnet")
        if not options["broadcast"]:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing broadcast"))
            self._print_safe_calls(proxy_addr)
            return
        from cusd_plus.sponsor_7702 import PolicyError, require_shared_nonce_lock
        try:
            require_shared_nonce_lock()
        except PolicyError:
            raise CommandError(
                "broadcast must run on the production host (ssh confio-prod) after this code is "
                "deployed there: no fresh relay heartbeat in this process's cache, so the sponsor "
                "nonce lock would not be shared with the relay")
        if balance < total_max * 13 // 10:
            raise CommandError("insufficient deployer BNB for conservative maximum")

        from cusd_plus.sponsor_7702 import acquire_sponsor_nonce_lock, release_sponsor_nonce_lock

        def deploy(label, data, limit):
            """One creation tx under the SHARED sponsor nonce lock (the
            production relay signs from this same KMS account), nonce read
            fresh inside the lock; returns the deployed address."""
            from django.core.cache import cache

            # Slow, nonce-independent work stays OUTSIDE the critical section.
            estimate = int(_rpc(rpc_url, "eth_estimateGas",
                                [{"from": deployer, "data": "0x" + data.hex()}]), 16)
            gas = max(limit, estimate * 13 // 10)
            # A lease long enough for nonce read + KMS sign + broadcast, and
            # ownership re-checked right before broadcasting (Codex P2).
            token = acquire_sponsor_nonce_lock(ttl_s=120)
            if token is None:
                raise CommandError("could not acquire the sponsor nonce lock; retry")
            try:
                tx_nonce = int(_rpc(rpc_url, "eth_getTransactionCount", [deployer, "pending"]), 16)
                expected = to_checksum_address(
                    keccak(rlp.encode([bytes.fromhex(deployer[2:]), tx_nonce]))[-20:])
                raw, _ = signer.sign_transaction({
                    "chainId": chain_id, "nonce": tx_nonce, "gasPrice": gas_price,
                    "gas": gas, "to": b"", "value": 0, "data": "0x" + data.hex(),
                })
                if cache.get("bsc_sponsor_nonce_lock") != token:
                    raise CommandError(f"lost the sponsor nonce lock before broadcasting {label}; "
                                       "nothing was sent, retry")
                sent = _rpc(rpc_url, "eth_sendRawTransaction", [raw])
            finally:
                release_sponsor_nonce_lock(token)
            for _ in range(90):
                receipt = _rpc(rpc_url, "eth_getTransactionReceipt", [sent])
                if receipt:
                    if receipt["status"] != "0x1":
                        raise CommandError(f"{label} reverted: {sent}")
                    got = to_checksum_address(receipt["contractAddress"])
                    if got != expected:
                        raise CommandError(f"{label} address mismatch: {got} != {expected}")
                    self.stdout.write(f"  {label} deployed: {got} ({sent})")
                    return got
                time.sleep(2)
            raise CommandError(f"timeout waiting for {label}: {sent}")

        impl_addr = deploy("Swap router implementation", impl_data, payloads[0][3])
        proxy_data = code(proxy_art) + abi_encode(["address", "bytes"], [impl_addr, init])
        proxy_addr = deploy("Swap router proxy", proxy_data, payloads[1][3])

        if address_at(proxy_addr, "owner()") != to_checksum_address(SAFE):
            raise CommandError("proxy owner is not the Safe")
        for sig, expected in (("VAULT()", CUSD_PLUS_PROXY), ("USDT()", USDT), ("SMART_ROUTER()", SMART_ROUTER)):
            if address_at(proxy_addr, sig) != to_checksum_address(expected):
                raise CommandError(f"proxy {sig} mismatch")
        if int(call_at(proxy_addr, "conversionFeeBps()"), 16) != 90:
            raise CommandError("router does not read cUSD's 90 bps fee")
        self.stdout.write(self.style.SUCCESS("Swap router deployed and verified"))
        self._print_safe_calls(proxy_addr)

    def _print_safe_calls(self, router):
        from eth_abi import encode as abi_encode
        from eth_utils import keccak

        set_sponsor = keccak(text="setSponsor(address,bool)")[:4] + abi_encode(["address", "bool"], [router, True])
        self.stdout.write("Safe multisend (value 0, in this order):")
        self.stdout.write(f"  1 target={CUSD_PLUS_PROXY} data=0x{set_sponsor.hex()}  # cUSD+.setSponsor(router)")
        self.stdout.write(f"  2 target={CUSD_PROXY} data=0x{set_sponsor.hex()}  # cUSD.setSponsor(router)")
        self.stdout.write(
            "Then: verify source on BscScan; set CRYPTO_SWAP_ROUTER_ADDRESS, CRYPTO_ENABLED, "
            "CRYPTO_BUY_ALLOWED_USER_IDS (canary), and CRYPTO_TRADING_ENABLED last.")
