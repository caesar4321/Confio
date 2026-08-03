"""
Deploy ConfioPayContract to BSC via the KMS sponsor.

Same KMS-creation-tx flow as deploy_presale_vault (the sponsor key is
non-extractable, so forge --broadcast is not an option). Single contract,
non-upgradeable, no proxy.

Constructor: (cusdPlus, usdt, confio, signer, owner)
  - cusdPlus  = CUSD_PLUS_VAULT_ADDRESS (live 0x3C29…3Ed1; vault shares
                are one of the two CHARGE denominations)
  - usdt      = BSC USDT 0x55d3…7955 — not a charge option, the payer's
                funding fallback (raw-USDT holders, including anyone
                geo-ineligible to mint cUSD+, must still be able to pay)
  - confio    = BSC_CONFIO_TOKEN_ADDRESS (re-issued BEP-20 0xCcEb…3fa8) —
                the second charge denomination (2026-08-01 ChargeScreen
                migration; v2 could not settle it, "token not allowed")
  - signer    = the backend payment authorizer = the sponsor KMS address.
                pay() only settles an invoice with this key's EIP-712
                authorization over the exact terms (audit 2026-07-31 P1:
                global invoiceDone guard, un-grief-able, no double-pay).
                Owner can rotate it on-chain via setPaymentSigner.
  - owner     = the 3-of-5 Safe (collects ACCRUED fees, rotates the signer,
                pauses new payments — fees accrue IN the contract, 07-31)

Usage:
  # Dry run — builds the txn, estimates gas, broadcasts NOTHING (default):
  myvenv/bin/python manage.py deploy_pay_contract

  # Real deployment — requires BOTH flags:
  myvenv/bin/python manage.py deploy_pay_contract --broadcast --yes-mainnet
"""
import json
import re
import time
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

SAFE = "0xF29A418744E793973BF4eEc676F8a30B2793b623"  # 3-of-5, owner

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
    help = "Deploy ConfioPayContract to BSC via the KMS sponsor"

    def add_arguments(self, parser):
        parser.add_argument("--broadcast", action="store_true", help="Actually send the transaction")
        parser.add_argument("--yes-mainnet", action="store_true", help="Required alongside --broadcast to confirm mainnet")

    def handle(self, *args, **options):
        from eth_abi import encode as abi_encode
        from eth_utils import keccak, to_checksum_address
        import rlp

        from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings

        signer = get_bsc_sponsor_signer_from_settings()
        rpc_url = settings.BSC_RPC_URL
        chain_id = settings.BSC_CHAIN_ID
        deployer = signer.address

        from cusd_plus.sponsor_7702 import USDT_BSC

        cusd_plus = getattr(settings, "CUSD_PLUS_VAULT_ADDRESS", "") or ""
        if not cusd_plus:
            raise CommandError("CUSD_PLUS_VAULT_ADDRESS not configured")
        confio = getattr(settings, "BSC_CONFIO_TOKEN_ADDRESS", "") or ""
        if not confio:
            raise CommandError("BSC_CONFIO_TOKEN_ADDRESS not configured")

        # The allowlist is IMMUTABLE and the contract is non-upgradeable, so
        # a typo'd or duplicated token address is unfixable after this runs
        # (Codex audit 2026-08-01 [P2]: these were printed, never checked).
        # Verify shape, distinctness, and that each address is actually a
        # deployed contract BEFORE spending a mainnet tx on it.
        tokens = {"cusdPlus": cusd_plus, "usdt": USDT_BSC, "confio": confio}
        for name, addr in tokens.items():
            if not re.fullmatch(r"0x[0-9a-fA-F]{40}", addr or ""):
                raise CommandError(f"{name} is not a valid address: {addr!r}")
        lowered = [a.lower() for a in tokens.values()]
        if len(set(lowered)) != len(lowered):
            raise CommandError(f"token addresses must be distinct: {tokens}")
        for name, addr in tokens.items():
            code = _rpc(rpc_url, "eth_getCode", [addr, "latest"])
            if code in (None, "0x", "0x0"):
                raise CommandError(f"{name} {addr} has NO CONTRACT CODE on chain {chain_id}")

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
        self.stdout.write(f"cusdPlus       = {cusd_plus}")
        self.stdout.write(f"usdt           = {USDT_BSC}")
        self.stdout.write(f"confio         = {confio}")
        self.stdout.write(f"signer (KMS)   = {deployer}")
        self.stdout.write(f"owner (Safe)   = {SAFE}")

        # The chain must be the one we think it is before anything is signed.
        on_chain_id = int(_rpc(rpc_url, "eth_chainId", []), 16)
        if on_chain_id != int(chain_id):
            raise CommandError(
                f"RPC reports chain {on_chain_id}, settings say {chain_id} — refusing to deploy")

        art = json.loads((ARTIFACTS / "ConfioPayContract.sol" / "ConfioPayContract.json").read_text())

        # Validate the ARTIFACT before broadcasting (Codex [P2], re-check):
        # a stale build without the CONFIO immutable would take the 5-arg
        # constructor args, deploy fine, and only fail at the post-deploy
        # read-back — after the BNB is spent and with a live, useless
        # contract on mainnet. Check the ABI says what this command assumes.
        abi = art.get("abi", [])
        ctor = next((x for x in abi if x.get("type") == "constructor"), None)
        ctor_arity = len(ctor.get("inputs", [])) if ctor else 0
        if ctor_arity != 5:
            raise CommandError(
                f"artifact constructor takes {ctor_arity} args, expected 5 "
                "(cusdPlus, usdt, confio, signer, owner) — rebuild with `forge build`")
        for getter in ("CUSD_PLUS", "USDT", "CONFIO", "paymentSigner", "owner"):
            if not any(x.get("type") == "function" and x.get("name") == getter for x in abi):
                raise CommandError(
                    f"artifact has no {getter}() — stale build, rebuild with `forge build`")

        bytecode = bytes.fromhex(art["bytecode"]["object"].removeprefix("0x"))
        ctor_args = abi_encode(
            ["address", "address", "address", "address", "address"],
            [cusd_plus, USDT_BSC, confio, deployer, SAFE],
        )
        data = bytecode + ctor_args

        vault_addr = to_checksum_address(
            keccak(rlp.encode([bytes.fromhex(deployer[2:]), nonce]))[-20:]
        )
        gas_est = int(_rpc(rpc_url, "eth_estimateGas", [{"from": deployer, "data": "0x" + data.hex()}]), 16)
        total_cost = gas_est * gas_price
        self.stdout.write("")
        self.stdout.write(f"pay contract → {vault_addr}  (~{gas_est} gas, ≈ {total_cost/1e18:.6f} BNB)")

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

        # Read back the wiring as a post-deploy sanity check
        def call_addr(sig):
            selector = keccak(text=sig)[:4]
            out = _rpc(rpc_url, "eth_call", [{"to": got, "data": "0x" + selector.hex()}, "latest"])
            # A missing getter returns '0x'; slicing that yields garbage or
            # throws, turning a clean "MISMATCH" report into a stack trace
            # (Codex [P2], re-check). Report it as the mismatch it is.
            body = (out or "")[2:] if (out or "").startswith("0x") else (out or "")
            if len(body) != 64:
                return f"<no result from {sig}>"
            return to_checksum_address("0x" + body[-40:])

        self.stdout.write(self.style.SUCCESS(f"\nDEPLOYED. ConfioPayContract: {got}"))

        # Read the immutables BACK and make a mismatch FATAL (Codex audit
        # [P2]). Printing them only helps if someone reads the output; this
        # contract is non-upgradeable, so a wrong wiring must never be
        # promoted into .env.mainnet as if the deploy had succeeded.
        expected = {
            "CUSD_PLUS()": cusd_plus,
            "USDT()": USDT_BSC,
            "CONFIO()": confio,
            "paymentSigner()": deployer,
            "owner()": SAFE,
        }
        mismatches = []
        for sig, want in expected.items():
            observed = call_addr(sig)
            ok = observed.lower() == to_checksum_address(want).lower()
            self.stdout.write(f"  {sig:<16} = {observed}  {'OK' if ok else 'MISMATCH'}")
            if not ok:
                mismatches.append(f"{sig}: got {observed}, expected {to_checksum_address(want)}")
        if mismatches:
            raise CommandError(
                "DEPLOYED CONTRACT IS MISWIRED — do NOT set BSC_PAY_CONTRACT_ADDRESS to "
                f"{got}. Redeploy after fixing:\n  " + "\n  ".join(mismatches))

        # The address is only usable if code actually landed there.
        deployed_code = _rpc(rpc_url, "eth_getCode", [got, "latest"])
        if deployed_code in (None, "0x", "0x0"):
            raise CommandError(f"no contract code at {got} after deploy — do NOT configure it")

        self.stdout.write(self.style.SUCCESS("All immutables verified against inputs."))
        self.stdout.write("Next: add BSC_PAY_CONTRACT_ADDRESS to .env.mainnet, BscScan verify, record in DEPLOYMENT.md.")
