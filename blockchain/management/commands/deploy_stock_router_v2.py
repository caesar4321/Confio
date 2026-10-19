"""Deploy the ConfioStockRouter v2 implementation (fee unification) via KMS.

v2 removes the stock-only 0.30% router fee: buys leave cUSD+ through the
public fee-bearing ``redeemToUsdt`` and sells re-enter through
``subscribeAndMint``, so stock trades pay cUSD's single 0.9% perimeter fee.
A transitional legacy path keeps pre-v2 app builds (maxFeeBps = 30) working
at their original 0.30% until ``CUSD_PLUS_STOCK_LEGACY_FEE_ENABLED`` is off.

No live proxy is mutated here. Dry run is the default; a real creation
transaction requires ``--broadcast --yes-mainnet``. After reviewing the
verified bytecode, the 3-of-5 Safe executes the single printed call. Then set
``CUSD_PLUS_STOCK_CONVERSION_FEE_BPS=90`` on the server (never before the
upgrade has executed: new builds would sign intents the v1 router rejects).
"""
import json
import time
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

USDT = "0x55d398326f99059fF775485246999027B3197955"
USDON = "0x1f8955E640Cbd9abc3C3Bb408c9E2E1f5F20DfE6"
GM_TOKEN_MANAGER = "0x91f8Aff3738825e8eB16FC6f6b1A7A4647bDB299"
SAFE = "0xF29A418744E793973BF4eEc676F8a30B2793b623"
CUSD_PLUS_PROXY = "0x3C29417eb4314155e63d4C7D4507852b87763Ed1"
STOCK_ROUTER_PROXY = "0x40c8e134BCAf44EEf9e7D184846F36c9862329c3"
EXPECTED_CONVERSION_FEE_BPS = 90
LEGACY_STOCK_FEE_BPS = 30
STOCK_ARTIFACT = (
    Path(settings.BASE_DIR) / "contracts" / "ondo_stocks" / "out"
    / "ConfioStockRouter.sol" / "ConfioStockRouter.json"
)


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
    help = "Deploy the Stock Router v2 implementation (uniform 0.9% fee) via KMS"

    def add_arguments(self, parser):
        parser.add_argument("--broadcast", action="store_true")
        parser.add_argument("--yes-mainnet", action="store_true")

    def handle(self, *args, **options):
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

        # Preconditions on the LIVE system the v2 code depends on.
        if address_at(STOCK_ROUTER_PROXY, "owner()") != to_checksum_address(SAFE):
            raise CommandError("Stock Router proxy is not owned by the Safe")
        cusd = address_at(CUSD_PLUS_PROXY, "CUSD()")
        live_fee = int(call_at(cusd, "feeBps()"), 16)
        if live_fee != EXPECTED_CONVERSION_FEE_BPS:
            raise CommandError(f"cUSD feeBps is {live_fee}, expected {EXPECTED_CONVERSION_FEE_BPS}")
        router_word = STOCK_ROUTER_PROXY.lower().removeprefix("0x").rjust(64, "0")
        if int(call_at(CUSD_PLUS_PROXY, "isSponsor(address)", router_word), 16) != 1:
            raise CommandError("router is not a cUSD+ sponsor; v2 sells (subscribeAndMint) would revert")
        if address_at(CUSD_PLUS_PROXY, "stockRouter()") != to_checksum_address(STOCK_ROUTER_PROXY):
            raise CommandError("cUSD+ stockRouter is not this proxy; the legacy path would revert")

        if not STOCK_ARTIFACT.exists():
            raise CommandError(f"missing artifact {STOCK_ARTIFACT}; run forge build in contracts/ondo_stocks")
        art = json.loads(STOCK_ARTIFACT.read_text())
        functions = {item.get("name") for item in art.get("abi", [])}
        if not {"conversionFeeBps", "LEGACY_STOCK_FEE_BPS", "buyWithSavings", "sellToSavings"}.issubset(functions):
            raise CommandError("stale Stock Router artifact; rebuild before deployment")
        data = bytes.fromhex(art["bytecode"]["object"].removeprefix("0x")) + abi_encode(
            ["address", "address", "address", "address"],
            [CUSD_PLUS_PROXY, USDT, USDON, GM_TOKEN_MANAGER],
        )

        nonce = int(_rpc(rpc_url, "eth_getTransactionCount", [deployer, "pending"]), 16)
        balance = int(_rpc(rpc_url, "eth_getBalance", [deployer, "latest"]), 16)
        gas_price = max(
            int(_rpc(rpc_url, "eth_gasPrice", []), 16),
            int(settings.CUSD_PLUS_GAS_PRICE_FLOOR_WEI),
        ) * 12 // 10
        import rlp
        impl_addr = to_checksum_address(
            keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce]))[-20:])
        estimate = int(_rpc(rpc_url, "eth_estimateGas", [{"from": deployer, "data": "0x" + data.hex()}]), 16)
        gas = estimate * 13 // 10
        self.stdout.write(
            f"KMS deployer {deployer} · nonce {nonce} · gas {gas_price / 1e9:.3f} gwei · "
            f"max {gas * gas_price / 1e18:.6f} BNB")
        self.stdout.write(f"  Stock Router v2 implementation -> {impl_addr}  gasLimit={gas}")

        if options["broadcast"] and not options["yes_mainnet"]:
            raise CommandError("--broadcast requires --yes-mainnet")
        if not options["broadcast"]:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing broadcast"))
            self._print_safe_call(impl_addr)
            return
        from cusd_plus.sponsor_7702 import PolicyError, require_shared_nonce_lock
        try:
            require_shared_nonce_lock()
        except PolicyError:
            raise CommandError(
                "broadcast must run on the production host (ssh confio-prod) after this code is "
                "deployed there: no fresh relay heartbeat in this process's cache, so the sponsor "
                "nonce lock would not be shared with the relay")
        if balance < gas * gas_price * 13 // 10:
            raise CommandError("insufficient deployer BNB for conservative maximum")

        from django.core.cache import cache

        from cusd_plus.sponsor_7702 import acquire_sponsor_nonce_lock, release_sponsor_nonce_lock

        # The production relay signs from this same KMS account: take the
        # shared nonce lock, read the nonce inside it, and re-check the lease
        # right before broadcasting.
        token = acquire_sponsor_nonce_lock(ttl_s=120)
        if token is None:
            raise CommandError("could not acquire the sponsor nonce lock; retry")
        try:
            nonce = int(_rpc(rpc_url, "eth_getTransactionCount", [deployer, "pending"]), 16)
            impl_addr = to_checksum_address(
                keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce]))[-20:])
            raw, _ = signer.sign_transaction({
                "chainId": chain_id, "nonce": nonce, "gasPrice": gas_price, "gas": gas,
                "to": b"", "value": 0, "data": "0x" + data.hex(),
            })
            if cache.get("bsc_sponsor_nonce_lock") != token:
                raise CommandError("lost the sponsor nonce lock; nothing was sent, retry")
            sent = _rpc(rpc_url, "eth_sendRawTransaction", [raw])
        finally:
            release_sponsor_nonce_lock(token)
        for _ in range(90):
            receipt = _rpc(rpc_url, "eth_getTransactionReceipt", [sent])
            if receipt:
                if receipt["status"] != "0x1":
                    raise CommandError(f"deployment reverted: {sent}")
                got = to_checksum_address(receipt["contractAddress"])
                if got != impl_addr:
                    raise CommandError(f"address mismatch: {got} != {impl_addr}")
                self.stdout.write(f"  deployed: {got} ({sent})")
                break
            time.sleep(2)
        else:
            raise CommandError(f"timeout waiting for deployment: {sent}")

        wiring = {"CUSD_PLUS()": CUSD_PLUS_PROXY, "USDT()": USDT, "USDON()": USDON, "GM()": GM_TOKEN_MANAGER}
        for signature, expected in wiring.items():
            if address_at(impl_addr, signature) != to_checksum_address(expected):
                raise CommandError(f"implementation {signature} mismatch")
        if int(call_at(impl_addr, "stockFeeBps()"), 16) != 0:
            raise CommandError("implementation router fee is not zero")
        if int(call_at(impl_addr, "LEGACY_STOCK_FEE_BPS()"), 16) != LEGACY_STOCK_FEE_BPS:
            raise CommandError("implementation legacy cap mismatch")
        if int(call_at(impl_addr, "conversionFeeBps()"), 16) != EXPECTED_CONVERSION_FEE_BPS:
            raise CommandError("implementation does not read cUSD's live fee")

        self.stdout.write(self.style.SUCCESS("v2 implementation deployed and verified"))
        self._print_safe_call(impl_addr)

    def _print_safe_call(self, impl):
        from eth_abi import encode as abi_encode
        from eth_utils import keccak

        upgrade = keccak(text="upgradeToAndCall(address,bytes)")[:4] + abi_encode(
            ["address", "bytes"], [impl, b""])
        self.stdout.write("Safe call (value 0):")
        self.stdout.write(f"  target={STOCK_ROUTER_PROXY} data=0x{upgrade.hex()}")
        self.stdout.write(
            "After it executes: verify source on BscScan, then set "
            "CUSD_PLUS_STOCK_CONVERSION_FEE_BPS=90 (legacy stays enabled until cutover).")
