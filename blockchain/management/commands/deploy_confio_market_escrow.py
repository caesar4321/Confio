"""Deploy ConfioMarketEscrow (Comprar, UUPS proxy) via AWS KMS.

docs/designs/comprar-marketplace.md § Escrow. The proxy is created WITH its
initialize calldata in the same transaction, so nobody can front-run
initialize with their own owner/signer.

owner        = the BSC Safe (token limits, windows, roles, fees, upgrades)
orderSigner  = the KMS sponsor that signs this deployment (authorizes deposits)
arbiter      = the KMS sponsor too, until the Safe rotates it

The escrow accepts NO token after deployment: the Safe enables cUSD with
setTokenLimits(cUSD, maxOrder, maxOpen) as a separate Safe transaction.
Record proxy + implementation in contracts/cusd_plus/DEPLOYMENT.md and set
CONFIO_MARKET_ESCROW_ADDRESS (the PROXY, never the implementation).
"""
import json
import time
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

SAFE = "0xF29A418744E793973BF4eEc676F8a30B2793b623"
SHIP_WINDOW = 3 * 24 * 3600
RELEASE_WINDOW = 4 * 24 * 3600
DISPUTE_TIMEOUT = 30 * 24 * 3600
IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
ARTIFACTS = Path(settings.BASE_DIR) / "contracts" / "cusd_plus" / "out"


def _rpc(url, method, params):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    req = urllib.request.Request(
        url, data=payload.encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    if "error" in body:
        raise RuntimeError(f"rpc {method}: {body['error']}")
    return body["result"]


def _artifact(sol, name):
    path = ARTIFACTS / f"{sol}.sol" / f"{name}.json"
    if not path.exists():
        raise CommandError(f"missing artifact {path}; run forge build in contracts/cusd_plus")
    return json.loads(path.read_text())


class Command(BaseCommand):
    help = "Deploy the ConfioMarketEscrow UUPS proxy (Comprar) via KMS"

    def add_arguments(self, parser):
        parser.add_argument("--broadcast", action="store_true")
        parser.add_argument("--yes-mainnet", action="store_true")

    def handle(self, *args, **options):
        import rlp
        from eth_abi import encode as abi_encode
        from eth_utils import keccak, to_checksum_address

        from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings

        signer = get_bsc_sponsor_signer_from_settings()
        deployer = to_checksum_address(signer.address)
        rpc_url = settings.BSC_RPC_URL
        chain_id = int(settings.BSC_CHAIN_ID)
        if int(_rpc(rpc_url, "eth_chainId", []), 16) != chain_id:
            raise CommandError("RPC chain id does not match settings")
        if chain_id != 56:
            raise CommandError(f"expected BSC mainnet chain 56, got {chain_id}")
        if _rpc(rpc_url, "eth_getCode", [SAFE, "latest"]) in (None, "0x", "0x0"):
            raise CommandError("owner Safe has no code on this chain")

        impl_art = _artifact("ConfioMarketEscrow", "ConfioMarketEscrow")
        proxy_art = _artifact("ERC1967Proxy", "ERC1967Proxy")
        functions = {i.get("name") for i in impl_art.get("abi", []) if i.get("type") == "function"}
        required = {
            "initialize", "deposit", "markShipped", "confirm", "release", "dispute", "resolve",
            "refundExpiredDispute", "refund", "reclaim", "setTokenLimits", "collectFees",
            "sweepStray", "depositDigest", "upgradeToAndCall",
        }
        if not required <= functions:
            raise CommandError(f"stale ConfioMarketEscrow artifact (missing {required - functions}); rebuild")

        def code(art):
            return bytes.fromhex(art["bytecode"]["object"].removeprefix("0x"))

        nonce = int(_rpc(rpc_url, "eth_getTransactionCount", [deployer, "pending"]), 16)
        balance = int(_rpc(rpc_url, "eth_getBalance", [deployer, "latest"]), 16)
        gas_price = max(
            int(_rpc(rpc_url, "eth_gasPrice", []), 16),
            int(settings.CUSD_PLUS_GAS_PRICE_FLOOR_WEI),
        ) * 12 // 10

        impl_addr, proxy_addr = [
            to_checksum_address(keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce + i]))[-20:])
            for i in range(2)
        ]
        init = keccak(text="initialize(address,address,address,uint64,uint64,uint64)")[:4] + abi_encode(
            ["address", "address", "address", "uint64", "uint64", "uint64"],
            [SAFE, deployer, deployer, SHIP_WINDOW, RELEASE_WINDOW, DISPUTE_TIMEOUT])
        payloads = [
            ("MarketEscrow implementation", impl_addr, code(impl_art), None),
            ("MarketEscrow proxy", proxy_addr,
             code(proxy_art) + abi_encode(["address", "bytes"], [impl_addr, init]), 600_000),
        ]
        impl_gas = int(_rpc(rpc_url, "eth_estimateGas",
                            [{"from": deployer, "data": "0x" + payloads[0][2].hex()}]), 16) * 13 // 10
        payloads[0] = payloads[0][:3] + (impl_gas,)

        total_max = sum(p[3] for p in payloads) * gas_price
        self.stdout.write(
            f"KMS deployer/signer/arbiter {deployer} · nonce {nonce} · balance {balance / 1e18:.6f} BNB · "
            f"gas {gas_price / 1e9:.3f} gwei · max {total_max / 1e18:.6f} BNB")
        for label, address, _data, limit in payloads:
            self.stdout.write(f"  {label:<30} {address}  gasLimit={limit}")
        self.stdout.write(
            f"  owner={SAFE} ship={SHIP_WINDOW}s release={RELEASE_WINDOW}s dispute={DISPUTE_TIMEOUT}s; "
            "no token enabled until the Safe calls setTokenLimits")

        if options["broadcast"] and not options["yes_mainnet"]:
            raise CommandError("--broadcast requires --yes-mainnet")
        if not options["broadcast"]:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing broadcast"))
            return
        if balance < total_max * 13 // 10:
            raise CommandError("insufficient deployer BNB for conservative maximum")

        for index, (label, expected, data, limit) in enumerate(payloads):
            estimate = int(_rpc(rpc_url, "eth_estimateGas",
                                [{"from": deployer, "data": "0x" + data.hex()}]), 16)
            tx = {
                "chainId": chain_id, "nonce": nonce + index, "gasPrice": gas_price,
                "gas": max(limit, estimate * 13 // 10), "to": b"", "value": 0,
                "data": "0x" + data.hex(),
            }
            raw, _ = signer.sign_transaction(tx)
            sent = _rpc(rpc_url, "eth_sendRawTransaction", [raw])
            for _ in range(90):
                receipt = _rpc(rpc_url, "eth_getTransactionReceipt", [sent])
                if receipt:
                    if receipt["status"] != "0x1":
                        raise CommandError(f"{label} deployment reverted: {sent}")
                    got = to_checksum_address(receipt["contractAddress"])
                    if got != expected:
                        raise CommandError(f"{label} address mismatch: {got} != {expected}")
                    self.stdout.write(f"  {label} deployed: {got} ({sent})")
                    break
                time.sleep(2)
            else:
                raise CommandError(f"timeout waiting for {label}: {sent}")

        def call(sig):
            return _rpc(rpc_url, "eth_call", [{
                "to": proxy_addr, "data": "0x" + keccak(text=sig)[:4].hex()}, "latest"])

        def addr(word):
            return to_checksum_address("0x" + word[-40:])

        owner = addr(call("owner()"))
        order_signer = addr(call("orderSigner()"))
        arbiter = addr(call("arbiter()"))
        windows = (int(call("shipWindow()"), 16), int(call("releaseWindow()"), 16),
                   int(call("disputeTimeout()"), 16))
        paused = int(call("paused()"), 16)
        slot_impl = addr(_rpc(rpc_url, "eth_getStorageAt", [proxy_addr, IMPL_SLOT, "latest"]))
        if (owner != to_checksum_address(SAFE) or order_signer != deployer or arbiter != deployer
                or windows != (SHIP_WINDOW, RELEASE_WINDOW, DISPUTE_TIMEOUT) or paused
                or slot_impl != impl_addr):
            raise CommandError(
                f"post-deploy mismatch: owner={owner} signer={order_signer} arbiter={arbiter} "
                f"windows={windows} paused={paused} impl={slot_impl}")
        self.stdout.write(self.style.SUCCESS(
            f"ConfioMarketEscrow proxy verified: {proxy_addr} (use THIS address; "
            f"implementation {impl_addr}). Next: Safe setTokenLimits(cUSD, …)."))
