"""Deploy ConfioStockRouter to BSC mainnet with the non-extractable KMS sponsor.

Dry run is the default. A real creation transaction requires both
``--broadcast`` and ``--yes-mainnet``. Deployment does not activate trading:
Ondo registration and the Safe's vault sponsor transaction remain separate.
"""
import json
import time
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


CUSD_PLUS = "0x3C29417eb4314155e63d4C7D4507852b87763Ed1"
USDT = "0x55d398326f99059fF775485246999027B3197955"
USDON = "0x1f8955E640Cbd9abc3C3Bb408c9E2E1f5F20DfE6"
GM_TOKEN_MANAGER = "0x91f8Aff3738825e8eB16FC6f6b1A7A4647bDB299"
SAFE = "0xF29A418744E793973BF4eEc676F8a30B2793b623"
ERC1967_IMPLEMENTATION_SLOT = (
    "0x360894a13ba1a3210667c828492db98dca3e2076"
    "cc3735a920a3ca505d382bbc"
)
ROUTER_ARTIFACT = (
    Path(settings.BASE_DIR)
    / "contracts"
    / "ondo_stocks"
    / "out"
    / "ConfioStockRouter.sol"
    / "ConfioStockRouter.json"
)
PROXY_ARTIFACT = (
    Path(settings.BASE_DIR)
    / "contracts"
    / "ondo_stocks"
    / "out"
    / "ERC1967Proxy.sol"
    / "ERC1967Proxy.json"
)


def _rpc(url: str, method: str, params: list):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    req = urllib.request.Request(
        url, data=payload.encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    if "error" in body:
        raise RuntimeError(f"rpc {method}: {body['error']}")
    return body["result"]


class Command(BaseCommand):
    help = "Deploy ConfioStockRouter to BSC mainnet via the KMS sponsor"

    def add_arguments(self, parser):
        parser.add_argument("--broadcast", action="store_true", help="Actually send the transaction")
        parser.add_argument(
            "--yes-mainnet",
            action="store_true",
            help="Required alongside --broadcast to confirm BSC mainnet",
        )

    def handle(self, *args, **options):
        from eth_abi import encode as abi_encode
        from eth_utils import keccak, to_checksum_address
        import rlp

        from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings

        if int(settings.BSC_CHAIN_ID) != 56:
            raise CommandError(f"BSC_CHAIN_ID must be 56, got {settings.BSC_CHAIN_ID}")
        for artifact_path in (ROUTER_ARTIFACT, PROXY_ARTIFACT):
            if not artifact_path.exists():
                raise CommandError(f"Missing forge artifact: {artifact_path}; run forge build first")

        signer = get_bsc_sponsor_signer_from_settings()
        rpc_url = settings.BSC_RPC_URL
        deployer = signer.address
        chain_id = int(_rpc(rpc_url, "eth_chainId", []), 16)
        if chain_id != 56:
            raise CommandError(f"RPC is not BSC mainnet: chainId={chain_id}")

        dependencies = [CUSD_PLUS, USDT, USDON, GM_TOKEN_MANAGER]
        for address in dependencies:
            if _rpc(rpc_url, "eth_getCode", [address, "latest"]) == "0x":
                raise CommandError(f"Dependency has no code: {address}")
        if _rpc(rpc_url, "eth_getCode", [SAFE, "latest"]) == "0x":
            raise CommandError(f"Safe has no code: {SAFE}")

        # Confirm the immutable graph before asking KMS to sign anything.
        usdon_result = _rpc(
            rpc_url,
            "eth_call",
            [{"to": GM_TOKEN_MANAGER, "data": "0x" + keccak(text="usdon()")[:4].hex()}, "latest"],
        )
        gm_usdon = to_checksum_address("0x" + usdon_result[-40:])
        if gm_usdon.lower() != USDON.lower():
            raise CommandError(f"GM usdon mismatch: {gm_usdon} != {USDON}")

        router_artifact = json.loads(ROUTER_ARTIFACT.read_text())
        router_bytecode = bytes.fromhex(
            router_artifact["bytecode"]["object"].removeprefix("0x")
        )
        implementation_data = router_bytecode + abi_encode(
            ["address", "address", "address", "address"], dependencies
        )

        balance = int(_rpc(rpc_url, "eth_getBalance", [deployer, "latest"]), 16)
        nonce = int(_rpc(rpc_url, "eth_getTransactionCount", [deployer, "pending"]), 16)
        gas_price = max(
            int(_rpc(rpc_url, "eth_gasPrice", []), 16),
            int(settings.CUSD_PLUS_GAS_PRICE_FLOOR_WEI),
        )
        gas_price = gas_price * 12 // 10
        expected_implementation = to_checksum_address(
            keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce]))[-20:]
        )
        expected_proxy = to_checksum_address(
            keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce + 1]))[-20:]
        )
        initializer = keccak(text="initialize(address)")[:4] + abi_encode(["address"], [SAFE])
        proxy_artifact = json.loads(PROXY_ARTIFACT.read_text())
        proxy_bytecode = bytes.fromhex(proxy_artifact["bytecode"]["object"].removeprefix("0x"))
        proxy_data = proxy_bytecode + abi_encode(
            ["address", "bytes"], [expected_implementation, initializer]
        )

        def estimate(data: bytes) -> int:
            return int(
                _rpc(
                    rpc_url,
                    "eth_estimateGas",
                    [{"from": deployer, "data": "0x" + data.hex()}],
                ),
                16,
            )

        implementation_gas = estimate(implementation_data)
        # The proxy constructor delegatecalls initialize(), so it cannot be
        # estimated until the implementation exists. Use a conservative dry-
        # run budget, then replace it with a live estimate after tx 1 mines.
        proxy_gas = 400_000
        total_cost = (implementation_gas + proxy_gas) * gas_price

        self.stdout.write(f"Deployer (KMS sponsor): {deployer}")
        self.stdout.write(
            f"Chain {chain_id} · balance {balance / 1e18:.6f} BNB · "
            f"nonce {nonce} · gasPrice {gas_price / 1e9:.3f} gwei"
        )
        self.stdout.write(f"Implementation: {expected_implementation} (~{implementation_gas} gas)")
        self.stdout.write(f"Router proxy:   {expected_proxy} (~{proxy_gas} gas)")
        self.stdout.write(f"Estimated total: ≈ {total_cost / 1e18:.6f} BNB")
        self.stdout.write(f"Owner:  {SAFE}")
        self.stdout.write("Fee:    30 bps fixed in bytecode")

        if not options["broadcast"]:
            self.stdout.write(
                self.style.WARNING(
                    "\nDRY RUN — nothing broadcast. Re-run with "
                    "--broadcast --yes-mainnet to deploy."
                )
            )
            return
        if not options["yes_mainnet"]:
            raise CommandError("--broadcast requires --yes-mainnet")
        if balance < total_cost * 13 // 10:
            raise CommandError(
                f"Insufficient BNB: have {balance / 1e18:.6f}, "
                f"need ~{total_cost * 1.3 / 1e18:.6f}"
            )

        def deploy(label: str, data: bytes, tx_nonce: int, gas_estimate: int, expected: str):
            tx = {
                "chainId": chain_id,
                "nonce": tx_nonce,
                "gasPrice": gas_price,
                "gas": gas_estimate * 13 // 10,
                "to": b"",
                "value": 0,
                "data": "0x" + data.hex(),
            }
            raw, local_hash = signer.sign_transaction(tx)
            sent = _rpc(rpc_url, "eth_sendRawTransaction", [raw])
            if sent.lower() != local_hash.lower():
                raise CommandError(f"{label} transaction hash mismatch: {sent} != {local_hash}")
            self.stdout.write(f"\n{label} broadcast: {sent}")

            receipt = None
            for _ in range(90):
                receipt = _rpc(rpc_url, "eth_getTransactionReceipt", [sent])
                if receipt:
                    break
                time.sleep(2)
            if not receipt:
                raise CommandError(f"Timeout waiting for {label} receipt: {sent}")
            if receipt["status"] != "0x1":
                raise CommandError(f"{label} deployment reverted: {sent}")
            deployed = to_checksum_address(receipt["contractAddress"])
            if deployed != expected:
                raise CommandError(f"{label} address mismatch: {deployed} != {expected}")
            return sent, deployed

        implementation_tx, implementation = deploy(
            "Implementation", implementation_data, nonce, implementation_gas, expected_implementation
        )
        proxy_gas = estimate(proxy_data)
        proxy_tx, deployed = deploy("Router proxy", proxy_data, nonce + 1, proxy_gas, expected_proxy)

        implementation_slot = _rpc(
            rpc_url,
            "eth_getStorageAt",
            [deployed, ERC1967_IMPLEMENTATION_SLOT, "latest"],
        )
        slotted_implementation = to_checksum_address("0x" + implementation_slot[-40:])
        if slotted_implementation.lower() != implementation.lower():
            raise CommandError(
                "Post-deploy ERC-1967 implementation mismatch: "
                f"{slotted_implementation} != {implementation}"
            )

        def call_address(signature: str) -> str:
            result = _rpc(
                rpc_url,
                "eth_call",
                [{"to": deployed, "data": "0x" + keccak(text=signature)[:4].hex()}, "latest"],
            )
            return to_checksum_address("0x" + result[-40:])

        post_addresses = {
            "CUSD_PLUS()": CUSD_PLUS,
            "USDT()": USDT,
            "USDON()": USDON,
            "GM()": GM_TOKEN_MANAGER,
            "owner()": SAFE,
        }
        for signature, wanted in post_addresses.items():
            got = call_address(signature)
            if got.lower() != wanted.lower():
                raise CommandError(f"Post-deploy {signature} mismatch: {got} != {wanted}")
        fee = int(
            _rpc(
                rpc_url,
                "eth_call",
                [{"to": deployed, "data": "0x" + keccak(text="stockFeeBps()")[:4].hex()}, "latest"],
            ),
            16,
        )
        if fee != 30:
            raise CommandError(f"Post-deploy fee mismatch: {fee}")

        self.stdout.write(self.style.SUCCESS(f"\nDEPLOYED. ConfioStockRouter proxy: {deployed}"))
        self.stdout.write(f"Implementation: {implementation} ({implementation_tx})")
        self.stdout.write(f"Proxy tx:       {proxy_tx}")
        self.stdout.write("Post-deploy UUPS proxy ownership, immutable wiring, and 30 bps fee verified on-chain.")
        self.stdout.write("Trading is still inactive pending source verification, Ondo registration,")
        self.stdout.write("Safe setSponsor(router, true), fork rehearsal, and a minimum-size canary.")
