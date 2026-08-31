"""Deploy cUSD plus cUSD+/Stock Router upgrade implementations via AWS KMS.

No live proxy is mutated here.  After reviewing the deployed bytecode, the
3-of-5 Safe executes the calldata blobs printed by this command in one
multisend: configure cUSD, upgrade cUSD+, upgrade the existing Stock Router
proxy, and authorize that router for fee-free stock settlement.
"""
import json
import time
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

USDT = "0x55d398326f99059fF775485246999027B3197955"
USDY = "0x608593d17A2decBbc4399e4185bE4922F97eD32E"
IM = "0x9bA360087075A4Cef548eeD71Eed197bf4cFA4E2"
ORACLE = "0x8aaa843b848c2E3c83956Bc09aFBE4D9Dcf297b7"
SAFE = "0xF29A418744E793973BF4eEc676F8a30B2793b623"
CUSD_PLUS_PROXY = "0x3C29417eb4314155e63d4C7D4507852b87763Ed1"
STOCK_ROUTER_PROXY = "0x40c8e134BCAf44EEf9e7D184846F36c9862329c3"
USDON = "0x1f8955E640Cbd9abc3C3Bb408c9E2E1f5F20DfE6"
GM_TOKEN_MANAGER = "0x91f8Aff3738825e8eB16FC6f6b1A7A4647bDB299"
FEE_BPS = 90
YIELD_SHARE_BPS = 1500
ARTIFACTS = Path(settings.BASE_DIR) / "contracts" / "cusd_plus" / "out"
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


def _artifact(sol, name):
    path = ARTIFACTS / f"{sol}.sol" / f"{name}.json"
    if not path.exists():
        raise CommandError(f"missing artifact {path}; run forge build")
    return json.loads(path.read_text())


class Command(BaseCommand):
    help = "Deploy cUSD proxy plus cUSD+/Stock Router upgrade implementations via KMS"

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
        if int(_rpc(rpc_url, "eth_chainId", []), 16) != chain_id:
            raise CommandError("RPC chain id does not match settings")
        if chain_id != 56:
            raise CommandError(f"expected BSC mainnet chain 56, got {chain_id}")

        plus_proxy_code = _rpc(rpc_url, "eth_getCode", [CUSD_PLUS_PROXY, "latest"])
        if plus_proxy_code in (None, "0x", "0x0"):
            raise CommandError("configured cUSD+ proxy has no mainnet code")
        stock_proxy_code = _rpc(rpc_url, "eth_getCode", [STOCK_ROUTER_PROXY, "latest"])
        if stock_proxy_code in (None, "0x", "0x0"):
            raise CommandError("configured Stock Router proxy has no mainnet code")

        def read_proxy_address(signature):
            raw = _rpc(rpc_url, "eth_call", [{
                "to": CUSD_PLUS_PROXY,
                "data": "0x" + keccak(text=signature)[:4].hex(),
            }, "latest"])
            body = (raw or "").removeprefix("0x")
            if len(body) != 64:
                raise CommandError(f"cUSD+ proxy returned no {signature}")
            return to_checksum_address("0x" + body[-40:])

        if read_proxy_address("owner()") != to_checksum_address(SAFE):
            raise CommandError("cUSD+ proxy is not owned by the expected Safe")
        if read_proxy_address("USDT()") != to_checksum_address(USDT):
            raise CommandError("cUSD+ proxy uses an unexpected USDT backing token")

        def read_stock_address(signature):
            raw = _rpc(rpc_url, "eth_call", [{
                "to": STOCK_ROUTER_PROXY,
                "data": "0x" + keccak(text=signature)[:4].hex(),
            }, "latest"])
            body = (raw or "").removeprefix("0x")
            if len(body) != 64:
                raise CommandError(f"Stock Router proxy returned no {signature}")
            return to_checksum_address("0x" + body[-40:])

        expected_stock_wiring = {
            "owner()": SAFE,
            "CUSD_PLUS()": CUSD_PLUS_PROXY,
            "USDT()": USDT,
            "USDON()": USDON,
            "GM()": GM_TOKEN_MANAGER,
        }
        for signature, expected in expected_stock_wiring.items():
            if read_stock_address(signature) != to_checksum_address(expected):
                raise CommandError(f"Stock Router {signature} wiring mismatch")

        cusd_art = _artifact("CusdVault", "CusdVault")
        plus_art = _artifact("CusdPlusVault", "CusdPlusVault")
        proxy_art = _artifact("ERC1967Proxy", "ERC1967Proxy")
        if not STOCK_ARTIFACT.exists():
            raise CommandError(f"missing artifact {STOCK_ARTIFACT}; run forge build in contracts/ondo_stocks")
        stock_art = json.loads(STOCK_ARTIFACT.read_text())
        required_cusd = {"initialize", "backingToken", "setSponsor", "setSavingsVault"}
        cusd_functions = {
            item.get("name") for item in cusd_art.get("abi", [])
            if item.get("type") == "function"
        }
        if not required_cusd.issubset(cusd_functions):
            raise CommandError("stale CusdVault artifact; rebuild before deployment")
        if not any(
            item.get("type") == "function" and item.get("name") == "initializeCusd"
            for item in plus_art.get("abi", [])
        ):
            raise CommandError("stale CusdPlusVault artifact; initializeCusd missing")
        stock_functions = {
            item.get("name") for item in stock_art.get("abi", [])
            if item.get("type") == "function"
        }
        if not {"sellToSavings", "sellToUsdt", "buyWithSavings"}.issubset(stock_functions):
            raise CommandError("stale Stock Router artifact; rebuild before deployment")

        def code(art):
            return bytes.fromhex(art["bytecode"]["object"].removeprefix("0x"))

        # Use the pending nonce so this command never replaces or collides
        # with an already-queued sponsor transaction.
        nonce = int(_rpc(rpc_url, "eth_getTransactionCount", [deployer, "pending"]), 16)
        balance = int(_rpc(rpc_url, "eth_getBalance", [deployer, "latest"]), 16)
        gas_price = max(
            int(_rpc(rpc_url, "eth_gasPrice", []), 16),
            int(settings.CUSD_PLUS_GAS_PRICE_FLOOR_WEI),
        )
        gas_price = gas_price * 12 // 10

        predicted = [
            to_checksum_address(keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce + i]))[-20:])
            for i in range(4)
        ]
        cusd_impl_addr, cusd_proxy_addr, plus_impl_addr, stock_impl_addr = predicted
        cusd_impl_data = code(cusd_art) + abi_encode(["address"], [USDT])
        init_cusd = keccak(text="initialize(address,uint256)")[:4] + abi_encode(
            ["address", "uint256"], [SAFE, FEE_BPS])
        cusd_proxy_data = code(proxy_art) + abi_encode(
            ["address", "bytes"], [cusd_impl_addr, init_cusd])
        plus_impl_data = code(plus_art) + abi_encode(
            ["address", "address", "address", "address", "uint256"],
            [USDY, USDT, IM, ORACLE, YIELD_SHARE_BPS],
        )
        stock_impl_data = code(stock_art) + abi_encode(
            ["address", "address", "address", "address"],
            [CUSD_PLUS_PROXY, USDT, USDON, GM_TOKEN_MANAGER],
        )
        payloads = [
            ("cUSD implementation", cusd_impl_addr, cusd_impl_data, 4_500_000),
            ("cUSD proxy", cusd_proxy_addr, cusd_proxy_data, 1_200_000),
            ("cUSD+ implementation", plus_impl_addr, plus_impl_data, 5_500_000),
            ("Stock implementation", stock_impl_addr, stock_impl_data, 4_500_000),
        ]
        # The proxy cannot be estimated before its predicted implementation
        # exists.  Estimate the independent implementations and retain a
        # conservative fixed proxy limit, then estimate each again immediately
        # before broadcast once its dependency exists.
        for index in (0, 2, 3):
            label, address, data, _limit = payloads[index]
            estimate = int(_rpc(
                rpc_url, "eth_estimateGas",
                [{"from": deployer, "data": "0x" + data.hex()}],
            ), 16)
            payloads[index] = (label, address, data, estimate * 13 // 10)

        total_max = sum(item[3] for item in payloads) * gas_price
        self.stdout.write(
            f"KMS deployer {deployer} · nonce {nonce} · "
            f"gas {gas_price / 1e9:.3f} gwei · max {total_max / 1e18:.6f} BNB")
        for label, address, _data, limit in payloads:
            self.stdout.write(f"  {label:<22} {address}  gasLimit={limit}")

        if options["broadcast"] and not options["yes_mainnet"]:
            raise CommandError("--broadcast requires --yes-mainnet")
        if not options["broadcast"]:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing broadcast"))
            self._print_safe_calls(cusd_proxy_addr, plus_impl_addr, stock_impl_addr, deployer)
            return
        if balance < total_max * 13 // 10:
            raise CommandError("insufficient deployer BNB for conservative maximum")

        def send(index, label, expected, data, limit):
            # Dependencies deployed by prior steps now exist, so replace the
            # conservative limit with a live estimate where possible.
            estimate = int(_rpc(
                rpc_url, "eth_estimateGas",
                [{"from": deployer, "data": "0x" + data.hex()}],
            ), 16)
            gas = max(limit, estimate * 13 // 10)
            tx = {
                "chainId": chain_id, "nonce": nonce + index,
                "gasPrice": gas_price, "gas": gas, "to": b"",
                "value": 0, "data": "0x" + data.hex(),
            }
            raw, _tx_hash = signer.sign_transaction(tx)
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
                    return
                time.sleep(2)
            raise CommandError(f"timeout waiting for {label}: {sent}")

        for i, args in enumerate(payloads):
            send(i, *args)

        def call_at(target, sig):
            return _rpc(rpc_url, "eth_call", [{
                "to": target, "data": "0x" + keccak(text=sig)[:4].hex(),
            }, "latest"])

        def call(sig):
            return call_at(cusd_proxy_addr, sig)

        def address_at(target, sig):
            return to_checksum_address("0x" + call_at(target, sig)[-40:])

        owner = to_checksum_address("0x" + call("owner()")[-40:])
        fee = int(call("feeBps()"), 16)
        backing = to_checksum_address("0x" + call("backingToken()")[-40:])
        if owner != to_checksum_address(SAFE) or fee != FEE_BPS or backing != to_checksum_address(USDT):
            raise CommandError(
                f"cUSD proxy post-deploy mismatch: owner={owner}, fee={fee}, backing={backing}")

        plus_wiring = {
            "USDY()": USDY,
            "USDT()": USDT,
            "INSTANT_MANAGER()": IM,
            "ORACLE()": ORACLE,
        }
        for signature, expected in plus_wiring.items():
            if address_at(plus_impl_addr, signature) != to_checksum_address(expected):
                raise CommandError(f"cUSD+ implementation {signature} mismatch")

        for signature, expected in expected_stock_wiring.items():
            if signature == "owner()":
                # Ownership is proxy storage and is intentionally unset on a
                # disabled implementation contract.
                continue
            if address_at(stock_impl_addr, signature) != to_checksum_address(expected):
                raise CommandError(f"Stock implementation {signature} mismatch")
        stock_fee = int(call_at(stock_impl_addr, "stockFeeBps()"), 16)
        if stock_fee != 30:
            raise CommandError(f"Stock implementation fee mismatch: {stock_fee}")

        self.stdout.write(self.style.SUCCESS(
            "All four contracts deployed; cUSD proxy and upgrade implementation wiring verified"))
        self._print_safe_calls(cusd_proxy_addr, plus_impl_addr, stock_impl_addr, deployer)

    def _print_safe_calls(self, cusd_proxy, plus_impl, stock_impl, sponsor):
        from eth_abi import encode as abi_encode
        from eth_utils import keccak

        set_sponsor = keccak(text="setSponsor(address,bool)")[:4] + abi_encode(
            ["address", "bool"], [sponsor, True])
        set_savings = keccak(text="setSavingsVault(address)")[:4] + abi_encode(
            ["address"], [CUSD_PLUS_PROXY])
        init = keccak(text="initializeCusd(address)")[:4] + abi_encode(
            ["address"], [cusd_proxy])
        upgrade = keccak(text="upgradeToAndCall(address,bytes)")[:4] + abi_encode(
            ["address", "bytes"], [plus_impl, init])
        upgrade_stock = keccak(text="upgradeToAndCall(address,bytes)")[:4] + abi_encode(
            ["address", "bytes"], [stock_impl, b""])
        set_stock_sponsor = keccak(text="setSponsor(address,bool)")[:4] + abi_encode(
            ["address", "bool"], [STOCK_ROUTER_PROXY, True])
        set_stock_router = keccak(text="setStockRouter(address)")[:4] + abi_encode(
            ["address"], [STOCK_ROUTER_PROXY])
        self.stdout.write("Safe multisend calls (value 0, in this order):")
        self.stdout.write(f"  1 target={cusd_proxy} data=0x{set_sponsor.hex()}")
        self.stdout.write(f"  2 target={cusd_proxy} data=0x{set_savings.hex()}")
        self.stdout.write(f"  3 target={CUSD_PLUS_PROXY} data=0x{upgrade.hex()}")
        self.stdout.write(f"  4 target={STOCK_ROUTER_PROXY} data=0x{upgrade_stock.hex()}")
        self.stdout.write(f"  5 target={CUSD_PLUS_PROXY} data=0x{set_stock_sponsor.hex()}")
        self.stdout.write(f"  6 target={CUSD_PLUS_PROXY} data=0x{set_stock_router.hex()}")
