"""
Deploy ConfioPurchaseSpender (contracts/smart_account/ConfioPurchaseSpender.sol) to BSC via the KMS sponsor.

The spender pulls exactly one approved purchase's USDT from a Cuenta inteligente's Card rule and forwards all of it
to that purchase's deposit (agent_tasks/account_pay.py). Its operator — the only caller, and tx.origin too — is
the BSC KMS sponsor that relays purchases. Audit L3 (2026-11-25): the operator must be that sponsor (not a typo of
it), an EOA, and a registered sponsor on both dollar vaults; the deployed contract is read back before the Safe
allowlists it (factory.setCardSpender). Nothing here touches the factory.

The production relay signs from the same KMS account: a broadcast takes the shared sponsor nonce lock and must run
on the production host, like deploy_hands_off_impls.

Usage:
  myvenv/bin/python manage.py deploy_purchase_spender                         # dry run (default)
  myvenv/bin/python manage.py deploy_purchase_spender --broadcast --yes-mainnet
"""
import json
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from .deploy_hands_off_impls import CUSD, CUSD_PLUS, USDT, _artifact, _rpc

RECORD = Path(settings.BASE_DIR) / ".kms-local" / "kms_evm_multisig" / "purchase_spender_deploy_bsc.json"


class Command(BaseCommand):
    help = "Deploy ConfioPurchaseSpender via the KMS sponsor (operator = that sponsor)"

    def add_arguments(self, parser):
        parser.add_argument("--broadcast", action="store_true", help="Actually send the transaction")
        parser.add_argument("--yes-mainnet", action="store_true", help="Required alongside --broadcast")
        parser.add_argument("--record", default=str(RECORD), help="JSON record of the deployment")

    def handle(self, *args, **options):
        from eth_abi import decode as abi_decode, encode as abi_encode
        from eth_utils import keccak, to_checksum_address
        import rlp

        from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings

        signer = get_bsc_sponsor_signer_from_settings()
        rpc_url, chain_id, deployer = settings.BSC_RPC_URL, settings.BSC_CHAIN_ID, signer.address
        if int(chain_id) != 56:
            raise CommandError(f"BSC mainnet only (chain {chain_id})")
        operator = to_checksum_address(deployer)
        configured = getattr(settings, "BSC_SPONSOR_ADDRESS", None)
        if configured and to_checksum_address(configured) != operator:
            raise CommandError(f"BSC_SPONSOR_ADDRESS {configured} is not the KMS sponsor {operator}")

        def call(to, signature, args_types=(), args=(), out=("bool",)):
            data = keccak(text=signature)[:4] + (abi_encode(list(args_types), list(args)) if args_types else b"")
            raw = _rpc(rpc_url, "eth_call", [{"to": to, "data": "0x" + data.hex()}, "latest"])
            return abi_decode(list(out), bytes.fromhex(raw[2:]))[0]

        if _rpc(rpc_url, "eth_getCode", [operator, "latest"]) not in ("0x", "0x0"):
            raise CommandError("the operator has code: it must be an EOA (a 7702 delegation would let others act)")
        for vault in (CUSD, CUSD_PLUS):
            if not call(vault, "isSponsor(address)", ["address"], [operator]):
                raise CommandError(f"operator {operator} is not a sponsor on {vault}")

        art = _artifact("smart_account", "ConfioPurchaseSpender.sol", "ConfioPurchaseSpender")
        if not {"pullTo", "operator", "usdt"}.issubset({e.get("name") for e in art["abi"]}):
            raise CommandError("ConfioPurchaseSpender artifact lacks pullTo/operator/usdt — rebuild with `forge build`")
        data = bytes.fromhex(art["bytecode"]["object"].removeprefix("0x")) + abi_encode(
            ["address", "address"], [operator, USDT])
        balance = int(_rpc(rpc_url, "eth_getBalance", [deployer, "latest"]), 16)
        nonce = int(_rpc(rpc_url, "eth_getTransactionCount", [deployer, "pending"]), 16)
        gas_price = max(int(_rpc(rpc_url, "eth_gasPrice", []), 16), int(settings.CUSD_PLUS_GAS_PRICE_FLOOR_WEI))
        gas_price = (gas_price * 12) // 10
        gas = int(_rpc(rpc_url, "eth_estimateGas", [{"from": deployer, "data": "0x" + data.hex()}]), 16)
        at = to_checksum_address(keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce]))[-20:])
        self.stdout.write(f"Deployer = operator (KMS sponsor): {operator} · sponsor on cUSD and cUSD+ · EOA")
        self.stdout.write(f"ConfioPurchaseSpender → {at}  (~{gas} gas, ≈ {gas * gas_price / 1e18:.6f} BNB)")
        if not options["broadcast"]:
            self.stdout.write(self.style.WARNING("\nDRY RUN — nothing broadcast. Re-run with --broadcast --yes-mainnet."))
            return
        if not options["yes_mainnet"]:
            raise CommandError("--broadcast requires --yes-mainnet to confirm a real mainnet deployment.")
        if balance < gas * gas_price * 13 // 10:
            raise CommandError(f"Insufficient BNB: have {balance/1e18:.6f}")
        from cusd_plus.sponsor_7702 import (PolicyError, acquire_sponsor_nonce_lock, release_sponsor_nonce_lock,
                                            require_shared_nonce_lock)
        try:
            require_shared_nonce_lock()
        except PolicyError:
            raise CommandError("broadcast must run on the production host (ssh confio-prod)")
        from django.core.cache import cache
        token = acquire_sponsor_nonce_lock(ttl_s=120)
        if token is None:
            raise CommandError("could not acquire the sponsor nonce lock; retry")
        try:
            nonce = int(_rpc(rpc_url, "eth_getTransactionCount", [deployer, "pending"]), 16)
            at = to_checksum_address(keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce]))[-20:])
            raw, _ = signer.sign_transaction({"chainId": chain_id, "nonce": nonce, "gasPrice": gas_price,
                                              "gas": int(gas * 13 // 10), "to": b"", "value": 0,
                                              "data": "0x" + data.hex()})
            if cache.get("bsc_sponsor_nonce_lock") != token:
                raise CommandError("lost the sponsor nonce lock; nothing was sent, retry")
            sent = _rpc(rpc_url, "eth_sendRawTransaction", [raw])
        finally:
            release_sponsor_nonce_lock(token)
        self.stdout.write(f"sent {sent}")
        receipt = None
        for _ in range(90):
            receipt = _rpc(rpc_url, "eth_getTransactionReceipt", [sent])
            if receipt:
                break
            time.sleep(2)
        if not receipt or receipt["status"] != "0x1":
            raise CommandError(f"deploy failed or timed out: {sent}")
        got = to_checksum_address(receipt["contractAddress"])
        if got != at:
            raise CommandError(f"address mismatch: {got} != {at}")
        if (to_checksum_address(call(got, "operator()", out=("address",))) != operator
                or to_checksum_address(call(got, "usdt()", out=("address",))) != USDT):
            raise CommandError("read-back differs: do NOT allowlist this spender")
        self.stdout.write(self.style.SUCCESS(f"\nDEPLOYED. ConfioPurchaseSpender: {got} (tx {sent}, block "
                                             f"{int(receipt['blockNumber'], 16)})"))
        try:
            record = Path(options["record"])
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text(json.dumps({"network": "bsc", "spender": got, "operator": operator, "tx": sent,
                                          "block": int(receipt["blockNumber"], 16)}, indent=2) + "\n")
        except OSError as exc:  # the deployment stands; only the local record failed
            self.stdout.write(self.style.WARNING(f"record not written ({exc}); the line above is the record"))
        self.stdout.write("Then: the Safe allowlists it (factory.setCardSpender(spender, true)) and "
                          "SMART_ACCOUNT_PURCHASE_SPENDER_ADDRESS is set.")
