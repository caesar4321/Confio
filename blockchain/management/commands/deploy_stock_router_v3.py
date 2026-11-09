"""Deploy the ConfioStockRouter v3 implementation (legacy 0.30% path deleted) via KMS.

v3 removes the transitional pre-v2 path entirely: no LEGACY_STOCK_FEE_BPS,
no fee-free vault surfaces, no accrual and no withdrawFees. Every stock trade
pays cUSD's single 0.9% perimeter fee; a signed cap below the live fee
(including a pre-v2 build's 30) reverts. Storage slot 0 (accruedUsdtFees)
is kept for the proxy layout and must already be zero: the upgrade calls
initializeV3(), which refuses otherwise.

Order (2026-11-09): legacy fees withdrawn to the Safe (Safe nonce 28) ->
CUSD_PLUS_STOCK_LEGACY_FEE_ENABLED=False on the server -> this command ->
the 3-of-5 Safe executes the single printed call.

No live proxy is mutated here. Dry run is the default; a real creation
transaction requires ``--broadcast --yes-mainnet`` on the production host.
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
V3_VERSION = 3
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
    help = "Deploy the Stock Router v3 implementation (no legacy 0.30% path) via KMS"

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

        # Preconditions on the LIVE system v3 depends on.
        if address_at(STOCK_ROUTER_PROXY, "owner()") != to_checksum_address(SAFE):
            raise CommandError("Stock Router proxy is not owned by the Safe")
        accrued = int(call_at(STOCK_ROUTER_PROXY, "accruedUsdtFees()"), 16)
        if accrued != 0:
            raise CommandError(
                f"proxy still holds {accrued} wei of legacy fees: withdraw them to the Safe with the "
                "current router's withdrawFees first (initializeV3 would revert the upgrade)")
        if getattr(settings, "CUSD_PLUS_STOCK_LEGACY_FEE_ENABLED", True):
            raise CommandError(
                "CUSD_PLUS_STOCK_LEGACY_FEE_ENABLED is on: the relay would still sponsor cap-30 intents "
                "that v3 reverts. Turn it off first.")
        cusd = address_at(CUSD_PLUS_PROXY, "CUSD()")
        live_fee = int(call_at(cusd, "feeBps()"), 16)
        if live_fee != EXPECTED_CONVERSION_FEE_BPS:
            raise CommandError(f"cUSD feeBps is {live_fee}, expected {EXPECTED_CONVERSION_FEE_BPS}")
        router_word = STOCK_ROUTER_PROXY.lower().removeprefix("0x").rjust(64, "0")
        if int(call_at(CUSD_PLUS_PROXY, "isSponsor(address)", router_word), 16) != 1:
            raise CommandError("router is not a cUSD+ sponsor; sells (subscribeAndMint) would revert")

        if not STOCK_ARTIFACT.exists():
            raise CommandError(f"missing artifact {STOCK_ARTIFACT}; run forge build in contracts/ondo_stocks")
        art = json.loads(STOCK_ARTIFACT.read_text())
        functions = {item.get("name") for item in art.get("abi", [])}
        if not {"conversionFeeBps", "initializeV3", "VERSION", "buyWithSavings", "sellToSavings"}.issubset(functions):
            raise CommandError("stale Stock Router artifact; rebuild before deployment")
        if functions & {"LEGACY_STOCK_FEE_BPS", "LEGACY_MAX_EXCESS_BPS", "withdrawFees"}:
            raise CommandError("artifact still has the legacy fee path; rebuild the v3 source")
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
        self.stdout.write(f"  Stock Router v3 implementation -> {impl_addr}  gasLimit={gas}")

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
        if int(call_at(impl_addr, "VERSION()"), 16) != V3_VERSION:
            raise CommandError("implementation is not v3")
        if int(call_at(impl_addr, "conversionFeeBps()"), 16) != EXPECTED_CONVERSION_FEE_BPS:
            raise CommandError("implementation does not read cUSD's live fee")

        self.stdout.write(self.style.SUCCESS("v3 implementation deployed and verified"))
        self._print_safe_call(impl_addr)

    def _print_safe_call(self, impl):
        from eth_abi import encode as abi_encode
        from eth_utils import keccak

        init = keccak(text="initializeV3()")[:4]
        upgrade = keccak(text="upgradeToAndCall(address,bytes)")[:4] + abi_encode(
            ["address", "bytes"], [impl, init])
        self.stdout.write("Safe call (value 0):")
        self.stdout.write(f"  target={STOCK_ROUTER_PROXY} data=0x{upgrade.hex()}")
        self.stdout.write(
            "After it executes: VERSION() on the proxy reads 3 and accruedUsdtFees() 0; "
            "verify the source on BscScan.")
