"""Deploy the Cuenta inteligente package to BSC mainnet via the KMS sponsor.

Python twin of contracts/smart_account/script/DeploySmartAccount.s.sol (the
sponsor key is non-extractable, so forge --broadcast is not an option). Same
four creations, same order, same constructor arguments and constants:

  1. ConfioSmartAccountFeeCollector(CUSD, CUSD_PLUS, SAFE)
  2. ConfioSmartAccount implementation, built against the factory proxy's
     PREDICTED address (its FACTORY is an immutable)
  3. ConfioSmartAccountFactory logic (CUSD_PLUS, STOCK_ROUTER)
  4. ERC1967Proxy(logic, initialize(SAFE, implementation, 14.99e18, 149.99e18))

The production relay signs from the same KMS account, so the proxy's address
is only predictable if 2-4 take three CONSECUTIVE sponsor nonces. They are
signed and broadcast back to back inside ONE lease of the shared sponsor nonce
lock (the relay waits a few seconds). The factory's initialize refuses an
implementation that names another factory, so a broken prediction reverts
instead of producing a mismatched pair.

Artifacts: contracts/smart_account/out (via_ir, 100 runs, solc 0.8.26; run
`forge build` there). out/ is gitignored and prod has no forge: build on a
laptop and scp the four artifact JSONs (runbook: contracts/cusd_plus/DEPLOYMENT.md,
"Cuenta inteligente"). Every artifact's metadata source hashes are
checked against the sources in this checkout, so a stale or foreign artifact
is refused.

Resume-safe. Each creation is written to the JSON record (default
.kms-local/kms_evm_multisig/smart_account_deploy_bsc.json, gitignored) as
"signed" BEFORE it is broadcast, then "landed" with its block. A re-run skips
what landed, resolves what was signed, and never redeploys silently.

Usage:
  # Dry run (default): preflight, gas estimates, predicted addresses.
  myvenv/bin/python manage.py deploy_smart_account --expected-confio-token 0xF576…6101

  # Full rehearsal on a local anvil fork of BSC (impersonated sponsor, no KMS):
  anvil --fork-url https://bsc-dataseed.bnbchain.org --port 8546 &
  myvenv/bin/python manage.py deploy_smart_account --expected-confio-token 0xF576…6101 \
      --rpc-url http://127.0.0.1:8546 --rehearse-fork

  # Real deployment, production host only:
  myvenv/bin/python manage.py deploy_smart_account --expected-confio-token 0xF576…6101 \
      --broadcast --yes-mainnet

  # Re-run post-deploy checks / print env lines and the verify recipe:
  myvenv/bin/python manage.py deploy_smart_account --expected-confio-token 0xF576…6101 --check-only
"""
import json
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# BSC mainnet, identical to script/DeploySmartAccount.s.sol.
SAFE = "0xF29A418744E793973BF4eEc676F8a30B2793b623"
SPONSOR = "0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D"
CUSD = "0x6101cC370635cF2c7f2725EaB010aC407A8d543F"
CUSD_PLUS = "0x3C29417eb4314155e63d4C7D4507852b87763Ed1"
USDT = "0x55d398326f99059fF775485246999027B3197955"
CONFIO = "0xF5765933764562A51e179F6AF2b19b7a3d506101"
STOCK_ROUTER = "0x40c8e134BCAf44EEf9e7D184846F36c9862329c3"
BTCB = "0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c"
XAUT = "0x21cAef8A43163Eea865baeE23b9C2E327696A3bf"
# Chainlink BNB Chain mainnet, matched against Chainlink's published list.
BTC_USD_FEED = "0x264990fbd0A4796A3E3d8E37C4d5F87a3aCa5Ebf"
XAU_USD_FEED = "0x86896fEB19D8A607c3b11f2aF50A0f239Bd71CD0"
# The account's own max ages (ConfioSmartAccount BTC/XAU_FEED_MAX_AGE).
FEED_MAX_AGE = {BTC_USD_FEED: 3600, XAU_USD_FEED: 26 * 3600}

MONTHLY_FEE_USD = 14_990_000_000_000_000_000  # 14.99e18
ANNUAL_FEE_USD = 149_990_000_000_000_000_000  # 149.99e18
DAY = 86_400

ERC1967_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
SOLC = "v0.8.26+commit.8a97fa7a"

SA_DIR = Path(settings.BASE_DIR) / "contracts" / "smart_account"
DEFAULT_RECORD = Path(settings.BASE_DIR) / ".kms-local" / "kms_evm_multisig" / "smart_account_deploy_bsc.json"

ARTIFACTS = {
    "collector": ("ConfioSmartAccountFeeCollector.sol", "ConfioSmartAccountFeeCollector"),
    "implementation": ("ConfioSmartAccount.sol", "ConfioSmartAccount"),
    "factory_logic": ("ConfioSmartAccountFactory.sol", "ConfioSmartAccountFactory"),
    "factory_proxy": ("ERC1967Proxy.sol", "ERC1967Proxy"),
}
SOURCE_PATHS = {
    "collector": "ConfioSmartAccountFeeCollector.sol:ConfioSmartAccountFeeCollector",
    "implementation": "ConfioSmartAccount.sol:ConfioSmartAccount",
    "factory_logic": "ConfioSmartAccountFactory.sol:ConfioSmartAccountFactory",
    "factory_proxy": "../ondo_stocks/node_modules/@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol:ERC1967Proxy",
}
TRIPLE = ("implementation", "factory_logic", "factory_proxy")
# Floor for the proxy's gas limit: it cannot be estimated before the
# implementation exists. Measured on an anvil fork; unused gas is not charged.
PROXY_GAS_FLOOR = 1_000_000


def _rpc(url, method, params):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    req = urllib.request.Request(url, data=payload.encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    if "error" in body:
        raise RuntimeError(f"rpc {method}: {body['error']}")
    return body["result"]


class Command(BaseCommand):
    help = "Deploy the Cuenta inteligente contracts (collector, account, factory) to BSC via the KMS sponsor"

    def add_arguments(self, parser):
        parser.add_argument("--broadcast", action="store_true", help="Send real mainnet transactions")
        parser.add_argument("--yes-mainnet", action="store_true", help="Required alongside --broadcast")
        parser.add_argument("--rehearse-fork", action="store_true",
                            help="Deploy for real on a local anvil fork (--rpc-url) as the impersonated sponsor")
        parser.add_argument("--check-only", action="store_true",
                            help="Only run the post-deploy checks against the record and print env/verify lines")
        parser.add_argument("--expected-confio-token", required=True,
                            help="Required, no default: the CONFIO token the operator states is final")
        parser.add_argument("--confio-token", default=CONFIO, help="CONFIO token baked into every account")
        parser.add_argument("--swap-router", default="",
                            help="Default: settings.CRYPTO_SWAP_ROUTER_ADDRESS")
        parser.add_argument("--artifacts", default=str(SA_DIR / "out"), help="forge out/ directory")
        parser.add_argument("--record", default="", help=f"Deploy record JSON (default {DEFAULT_RECORD})")
        parser.add_argument("--rpc-url", default="", help="Default: settings.BSC_RPC_URL")
        parser.add_argument("--redeploy-triple", action="store_true",
                            help="After a FAILED implementation/logic/proxy triple: abandon it and deploy a new one")

    # ───────────────────────────── helpers ─────────────────────────────

    def handle(self, *args, **options):
        import rlp
        from eth_abi import encode as abi_encode
        from eth_utils import keccak, to_checksum_address

        self.keccak, self.cs, self.abi_encode, self.rlp = keccak, to_checksum_address, abi_encode, rlp
        mode = ("broadcast" if options["broadcast"] else "rehearse" if options["rehearse_fork"]
                else "check" if options["check_only"] else "dry")
        if sum([options["broadcast"], options["rehearse_fork"], options["check_only"]]) > 1:
            raise CommandError("--broadcast, --rehearse-fork and --check-only are exclusive")
        if options["broadcast"] and not options["yes_mainnet"]:
            raise CommandError("--broadcast requires --yes-mainnet")
        self.mode = mode
        self.rpc_url = options["rpc_url"] or settings.BSC_RPC_URL
        if int(_rpc(self.rpc_url, "eth_chainId", []), 16) != 56:
            raise CommandError("expected BSC mainnet (chain 56) or a fork of it")
        client = str(_rpc(self.rpc_url, "web3_clientVersion", [])).lower()
        if mode == "rehearse" and "anvil" not in client:
            raise CommandError(f"--rehearse-fork needs a local anvil fork, got client {client!r}")
        if mode == "broadcast" and "anvil" in client:
            raise CommandError("--broadcast against an anvil fork: use --rehearse-fork")

        record_path = Path(options["record"]) if options["record"] else DEFAULT_RECORD
        if mode == "rehearse" and not options["record"]:
            record_path = record_path.with_name(record_path.stem + ".rehearsal.json")
        self.record_path = record_path
        self.record = json.loads(record_path.read_text()) if record_path.exists() else {}

        confio = self.cs(options["confio_token"])
        if confio != self.cs(options["expected_confio_token"]):
            raise CommandError("CONFIO token != --expected-confio-token")
        bsc_confio = getattr(settings, "BSC_CONFIO_TOKEN_ADDRESS", "") or ""
        if bsc_confio and self.cs(bsc_confio) != confio:
            raise CommandError(f"CONFIO {confio} differs from settings.BSC_CONFIO_TOKEN_ADDRESS {bsc_confio}")
        swap_router = options["swap_router"] or getattr(settings, "CRYPTO_SWAP_ROUTER_ADDRESS", "")
        if not swap_router:
            raise CommandError("CRYPTO_SWAP_ROUTER_ADDRESS not configured (or pass --swap-router)")
        swap_router = self.cs(swap_router)
        if self.record.get("params"):
            prev = self.record["params"]
            if prev["confio"] != confio or prev["swap_router"] != swap_router:
                raise CommandError("record was started with other CONFIO / swap router: refusing to mix")

        self.params = {"confio": confio, "swap_router": swap_router}
        self.arts = self._load_artifacts(Path(options["artifacts"]))

        if mode == "check":
            self._post_checks(confio, swap_router)
            return

        self._preflight(confio, swap_router)

        # Deployer: the KMS sponsor. A dry run tries KMS too (read-only
        # GetPublicKey) so a key or alias problem shows before broadcast day.
        self.signer = None
        if mode == "broadcast":
            from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings
            self.signer = get_bsc_sponsor_signer_from_settings()
            deployer = self.signer.address
        elif mode == "dry":
            try:
                from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings
                deployer = get_bsc_sponsor_signer_from_settings().address
                self.stdout.write(f"KMS sponsor key resolves to {deployer}")
            except Exception as exc:  # dry run only: report, continue with the configured address
                deployer = getattr(settings, "BSC_SPONSOR_ADDRESS", SPONSOR)
                self.stdout.write(self.style.WARNING(f"KMS signer not available here ({exc}); using {deployer}"))
        else:
            deployer = SPONSOR
            _rpc(self.rpc_url, "anvil_impersonateAccount", [deployer])
        if self.cs(deployer) != self.cs(SPONSOR):
            raise CommandError(f"deployer {deployer} is not the KMS sponsor {SPONSOR}")
        self.deployer = self.cs(deployer)

        self.gas_price = max(int(_rpc(self.rpc_url, "eth_gasPrice", []), 16),
                             int(settings.CUSD_PLUS_GAS_PRICE_FLOOR_WEI)) * 12 // 10
        balance = int(_rpc(self.rpc_url, "eth_getBalance", [self.deployer, "latest"]), 16)
        nonce = self._pending_nonce()
        self.stdout.write(f"Deployer {self.deployer} · nonce {nonce} · balance {balance / 1e18:.6f} BNB · "
                          f"gasPrice {self.gas_price / 1e9:.3f} gwei")

        # Gas limits from estimates (nonce-independent), proxy from a floor.
        collector_addr = self._resolved_address("collector") or self._create_address(nonce)
        placeholder_factory = self._create_address(nonce + 3)
        limits = {
            "collector": self._estimate(self._collector_data()) * 13 // 10,
            "implementation": self._estimate(self._impl_data(placeholder_factory, collector_addr)) * 13 // 10,
            "factory_logic": self._estimate(self._logic_data()) * 13 // 10,
            "factory_proxy": PROXY_GAS_FLOOR,
        }
        todo = [s for s in ("collector",) + TRIPLE if not self._landed(s)]
        max_cost = sum(limits[s] for s in todo) * self.gas_price
        self.stdout.write(f"\nTo deploy: {', '.join(todo) or 'nothing'} · max cost {max_cost / 1e18:.6f} BNB "
                          f"(balance {balance / 1e18:.6f})")
        n = nonce
        predicted = {}
        for step in ("collector",) + TRIPLE:
            if self._landed(step):
                predicted[step] = self.record[step]["address"]
                self.stdout.write(f"  {step:<15} LANDED {predicted[step]}")
                continue
            predicted[step] = self._create_address(n)
            self.stdout.write(f"  {step:<15} nonce {n} -> {predicted[step]}  gasLimit {limits[step]}")
            n += 1
        if balance < max_cost * 13 // 10:
            raise CommandError(f"insufficient sponsor BNB: {balance / 1e18:.6f} < {max_cost * 1.3 / 1e18:.6f}")

        if mode == "dry":
            self.stdout.write(self.style.WARNING(
                "\nDRY RUN — nothing broadcast. Predicted addresses hold only if no other sponsor "
                "transaction lands first (the relay shares this key); the real run re-reads the nonce "
                "inside the nonce lock. Re-run with --broadcast --yes-mainnet on the production host."))
            return

        if mode == "broadcast":
            from cusd_plus.sponsor_7702 import PolicyError, require_shared_nonce_lock
            try:
                require_shared_nonce_lock()
            except PolicyError:
                raise CommandError(
                    "broadcast must run on the production host (ssh confio-prod): no fresh relay heartbeat "
                    "in this process's cache, so the sponsor nonce lock would not be shared with the relay")
            self._require_clean_sources()

        self.record.setdefault("network", "bsc")
        self.record.setdefault("chain_id", 56)
        self.record.setdefault("mode", mode)
        self.record.setdefault("deployer", self.deployer)
        self.record.setdefault("safe", SAFE)
        self.record["params"] = self.params
        self.record.setdefault("git_commit", self._git_commit())
        self.record["artifact_hashes"] = {k: v["code_hash"] for k, v in self.arts.items()}
        self._save()

        # 1. Collector, its own transaction.
        self._resolve("collector")
        if not self._landed("collector"):
            self._send_batch([("collector", lambda _n: self._collector_data(), limits["collector"])])
        collector = self.record["collector"]["address"]

        # 2-4. The triple, three consecutive nonces in one lock lease.
        for step in TRIPLE:
            self._resolve(step)
        if not all(self._landed(s) for s in TRIPLE):
            states = {s: (self.record.get(s) or {}).get("status") for s in TRIPLE}
            if any(states.values()):
                if not options["redeploy_triple"]:
                    raise CommandError(
                        f"previous triple did not complete ({states}). Inspect the txs in the record, then "
                        "re-run with --redeploy-triple to abandon it and deploy a fresh triple")
                self.record.setdefault("abandoned", []).append({s: self.record.pop(s, None) for s in TRIPLE})
                self._save()

            def impl_data(n0):
                return self._impl_data(self._create_address(n0 + 2), collector)

            def logic_data(_n):
                return self._logic_data()

            def proxy_data(n0):
                return self._proxy_data(self._create_address(n0 - 2), self._create_address(n0 - 1))

            self._send_batch([
                ("implementation", impl_data, limits["implementation"]),
                ("factory_logic", logic_data, limits["factory_logic"]),
                ("factory_proxy", proxy_data, limits["factory_proxy"]),
            ])

        self.record["start_block"] = self.record["factory_proxy"]["block"]
        self._save()
        self._post_checks(self.params["confio"], self.params["swap_router"])

    # ─────────────────────────── calldata ────────────────────────────

    def _code(self, step):
        return self.arts[step]["creation"]

    def _collector_data(self):
        return self._code("collector") + self.abi_encode(["address"] * 3, [CUSD, CUSD_PLUS, SAFE])

    def _impl_args(self, factory, collector):
        return [factory, CUSD, CUSD_PLUS, USDT, self.params["confio"], STOCK_ROUTER, self.params["swap_router"],
                collector, BTCB, BTC_USD_FEED, XAUT, XAU_USD_FEED]

    def _impl_data(self, factory, collector):
        return self._code("implementation") + self.abi_encode(["address"] * 12, self._impl_args(factory, collector))

    def _logic_data(self):
        return self._code("factory_logic") + self.abi_encode(["address", "address"], [CUSD_PLUS, STOCK_ROUTER])

    def _init_data(self, implementation):
        return self.keccak(text="initialize(address,address,uint256,uint256)")[:4] + self.abi_encode(
            ["address", "address", "uint256", "uint256"], [SAFE, implementation, MONTHLY_FEE_USD, ANNUAL_FEE_USD])

    def _proxy_args(self, implementation, logic):
        return self.abi_encode(["address", "bytes"], [logic, self._init_data(implementation)])

    def _proxy_data(self, implementation, logic):
        return self._code("factory_proxy") + self._proxy_args(implementation, logic)

    # ─────────────────────────── chain I/O ───────────────────────────

    def _create_address(self, nonce):
        return self.cs(self.keccak(self.rlp.encode([bytes.fromhex(SPONSOR[2:]), nonce]))[-20:])

    def _pending_nonce(self):
        return int(_rpc(self.rpc_url, "eth_getTransactionCount", [SPONSOR, "pending"]), 16)

    def _estimate(self, data):
        return int(_rpc(self.rpc_url, "eth_estimateGas", [{"from": SPONSOR, "data": "0x" + data.hex()}]), 16)

    def _call(self, target, sig, types=(), values=()):
        data = self.keccak(text=sig)[:4] + self.abi_encode(list(types), list(values))
        return _rpc(self.rpc_url, "eth_call", [{"to": target, "data": "0x" + data.hex()}, "latest"])

    def _addr(self, target, sig, *a):
        return self.cs("0x" + self._call(target, sig, *a)[-40:])

    def _uint(self, target, sig, *a):
        return int(self._call(target, sig, *a), 16)

    def _string(self, target, sig):
        from eth_abi import decode
        return decode(["string"], bytes.fromhex(self._call(target, sig)[2:]))[0]

    def _get_code(self, address):
        return bytes.fromhex(_rpc(self.rpc_url, "eth_getCode", [address, "latest"])[2:])

    def _save(self):
        self.record_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.record_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.record, indent=2) + "\n")
        tmp.replace(self.record_path)

    def _landed(self, step):
        return (self.record.get(step) or {}).get("status") == "landed"

    def _resolved_address(self, step):
        return self.record[step]["address"] if self._landed(step) else None

    def _resolve(self, step):
        """Settle a step left 'signed' by an interrupted run."""
        entry = self.record.get(step)
        if not entry or entry["status"] != "signed":
            return
        receipt = _rpc(self.rpc_url, "eth_getTransactionReceipt", [entry["tx"]])
        if receipt:
            self._apply_receipt(step, entry, receipt)
            return
        latest = int(_rpc(self.rpc_url, "eth_getTransactionCount", [SPONSOR, "latest"]), 16)
        if latest > entry["nonce"]:
            entry["status"] = "dropped"  # another transaction took that nonce
            self._save()
            return
        raise CommandError(f"{step} tx {entry['tx']} (nonce {entry['nonce']}) is still pending: wait and re-run")

    def _apply_receipt(self, step, entry, receipt):
        if receipt["status"] != "0x1":
            entry["status"] = "failed"
            self._save()
            raise CommandError(f"{step} REVERTED: {entry['tx']}")
        got = self.cs(receipt["contractAddress"])
        if got != entry["address"]:
            entry["status"] = "failed"
            self._save()
            raise CommandError(f"{step} address mismatch: {got} != {entry['address']}")
        entry.update(status="landed", block=int(receipt["blockNumber"], 16),
                     gas_used=int(receipt["gasUsed"], 16))
        self._save()
        self.stdout.write(f"  {step} landed: {got} (block {entry['block']}, tx {entry['tx']})")

    def _send_batch(self, steps):
        """Sign and broadcast `steps` at consecutive nonces, under one lease
        of the shared sponsor nonce lock in broadcast mode. Each entry is
        recorded as 'signed' before it is sent; a send error stops the batch
        so no later nonce is left queued behind a gap."""
        token = None
        cache = None
        if self.mode == "broadcast":
            from django.core.cache import cache
            from cusd_plus.sponsor_7702 import acquire_sponsor_nonce_lock
            token = acquire_sponsor_nonce_lock(ttl_s=120)
            if token is None:
                raise CommandError("could not acquire the sponsor nonce lock; retry")
        sent = []
        try:
            n0 = self._pending_nonce()
            signed = []
            for i, (step, build, gas) in enumerate(steps):
                n = n0 + i
                data = build(n)
                tx = {"chainId": 56, "nonce": n, "gasPrice": self.gas_price, "gas": gas,
                      "to": b"", "value": 0, "data": "0x" + data.hex()}
                if self.mode == "broadcast":
                    raw, txh = self.signer.sign_transaction(tx)
                    signed.append((step, n, raw, txh))
                else:
                    signed.append((step, n, tx, None))
            for step, n, raw, txh in signed:
                if self.mode == "broadcast":
                    if cache.get("bsc_sponsor_nonce_lock") != token:
                        raise CommandError(f"lost the sponsor nonce lock before {step}; nothing more sent")
                    self.record[step] = {"status": "signed", "nonce": n, "tx": txh,
                                         "address": self._create_address(n),
                                         "signed_at": datetime.now(timezone.utc).isoformat()}
                    self._save()
                    got = _rpc(self.rpc_url, "eth_sendRawTransaction", [raw])
                    if got.lower() != txh.lower():
                        raise CommandError(f"{step}: node returned {got}, signed {txh}")
                else:
                    raw["from"] = SPONSOR
                    raw.pop("chainId")
                    raw.pop("to")
                    for k in ("nonce", "gasPrice", "gas", "value"):
                        raw[k] = hex(raw[k])
                    txh = _rpc(self.rpc_url, "eth_sendTransaction", [raw])
                    self.record[step] = {"status": "signed", "nonce": n, "tx": txh,
                                         "address": self._create_address(n)}
                    self._save()
                sent.append(step)
                self.stdout.write(f"  {step} sent: nonce {n} tx {txh}")
        finally:
            if token is not None:
                from cusd_plus.sponsor_7702 import release_sponsor_nonce_lock
                release_sponsor_nonce_lock(token)
        for step in sent:
            entry = self.record[step]
            for _ in range(120):
                receipt = _rpc(self.rpc_url, "eth_getTransactionReceipt", [entry["tx"]])
                if receipt:
                    self._apply_receipt(step, entry, receipt)
                    break
                time.sleep(2)
            else:
                raise CommandError(f"timeout waiting for {step}: {entry['tx']} (re-run resolves it)")

    # ────────────────────────── artifacts ────────────────────────────

    def _load_artifacts(self, out_dir):
        arts = {}
        for step, (folder, name) in ARTIFACTS.items():
            path = out_dir / folder / f"{name}.json"
            if not path.exists():
                raise CommandError(f"missing {path}; run `forge build` in contracts/smart_account (and scp out/)")
            art = json.loads(path.read_text())
            meta = art["metadata"] if isinstance(art.get("metadata"), dict) else json.loads(art["rawMetadata"])
            st = meta["settings"]
            if not (st.get("viaIR") and st["optimizer"] == {"enabled": True, "runs": 100}
                    and meta["compiler"]["version"] == SOLC[1:]):
                raise CommandError(f"{name}: artifact not built with via_ir / 100 runs / solc {SOLC}")
            # The artifact must be built from THESE sources (Confío files only;
            # OpenZeppelin lives in node_modules, which prod does not have).
            for src, info in meta["sources"].items():
                if "node_modules" in src or "/lib/" in src:
                    continue
                file = (SA_DIR / src).resolve()
                if not file.exists():
                    raise CommandError(f"{name}: source {src} missing in this checkout")
                if "0x" + self.keccak(file.read_bytes()).hex() != info["keccak256"]:
                    raise CommandError(f"{name}: artifact is stale for {src}; rebuild (and re-scp) the artifacts")
            creation = bytes.fromhex(art["bytecode"]["object"].removeprefix("0x"))
            arts[step] = {
                "creation": creation,
                "runtime": bytes.fromhex(art["deployedBytecode"]["object"].removeprefix("0x")),
                "immutables": art["deployedBytecode"].get("immutableReferences") or {},
                "abi": art["abi"],
                "code_hash": "0x" + self.keccak(creation).hex(),
            }
        if not any(e.get("name") == "cardSpenderAllowed" for e in arts["factory_logic"]["abi"]):
            raise CommandError("factory artifact predates decision 35 (no cardSpenderAllowed); rebuild")
        return arts

    def _require_clean_sources(self):
        """Mainnet bytecode comes from committed source only."""
        try:
            dirty = subprocess.run(
                ["git", "status", "--porcelain", "--", "ConfioSmartAccount.sol", "ConfioSmartAccountFactory.sol",
                 "ConfioSmartAccountFeeCollector.sol", "interfaces"],
                cwd=SA_DIR, capture_output=True, text=True, timeout=30)
        except Exception as exc:
            raise CommandError(f"cannot check source state with git: {exc}")
        if dirty.returncode != 0 or dirty.stdout.strip():
            raise CommandError(f"smart_account sources are not clean at HEAD:\n{dirty.stdout}{dirty.stderr}")

    def _git_commit(self):
        try:
            return subprocess.run(["git", "rev-parse", "HEAD"], cwd=SA_DIR, capture_output=True,
                                  text=True, timeout=30).stdout.strip()
        except Exception:
            return ""

    def _check_runtime(self, step, address):
        """Deployed runtime == artifact runtime with the immutables masked.
        Returns the immutable values in AST-id order, which within one source
        file is declaration order."""
        code = self._get_code(address)
        ref = self.arts[step]["runtime"]
        if len(code) != len(ref):
            raise CommandError(f"{step} runtime length {len(code)} != artifact {len(ref)}")
        masked_code, masked_ref = bytearray(code), bytearray(ref)
        values = {}
        for ast_id, spans in self.arts[step]["immutables"].items():
            seen = {code[s["start"]:s["start"] + s["length"]] for s in spans}
            if len(seen) != 1:
                raise CommandError(f"{step} immutable {ast_id} differs between its occurrences")
            values[int(ast_id)] = seen.pop()
            for s in spans:
                masked_code[s["start"]:s["start"] + s["length"]] = b"\0" * s["length"]
                masked_ref[s["start"]:s["start"] + s["length"]] = b"\0" * s["length"]
        if masked_code != masked_ref:
            raise CommandError(f"{step} at {address}: runtime bytecode does not match the artifact")
        return [values[k] for k in sorted(values)]

    # ─────────────────────────── preflight ───────────────────────────

    def _preflight(self, confio, swap_router):
        self.stdout.write("Preflight (live BSC state):")
        for name, a in [("Safe", SAFE), ("cUSD", CUSD), ("cUSD+", CUSD_PLUS), ("USDT", USDT), ("CONFIO", confio),
                        ("stock router", STOCK_ROUTER), ("swap router", swap_router), ("BTCB", BTCB),
                        ("XAUt", XAUT), ("BTC/USD feed", BTC_USD_FEED), ("XAU/USD feed", XAU_USD_FEED)]:
            if not self._get_code(a):
                raise CommandError(f"{name} {a} has no code")
        checks = [
            (self._addr(swap_router, "VAULT()") == self.cs(CUSD_PLUS), "swap router VAULT == cUSD+"),
            (self._addr(swap_router, "owner()") == self.cs(SAFE), "swap router owned by the Safe"),
            (self._addr(STOCK_ROUTER, "VAULT()") == self.cs(CUSD_PLUS), "stock router VAULT == cUSD+"),
            (self._addr(STOCK_ROUTER, "owner()") == self.cs(SAFE), "stock router owned by the Safe"),
            (self._addr(CUSD_PLUS, "CUSD()") == self.cs(CUSD), "cUSD+ CUSD == cUSD"),
            (self._addr(CUSD_PLUS, "owner()") == self.cs(SAFE), "cUSD+ owned by the Safe"),
            (self._addr(CUSD, "owner()") == self.cs(SAFE), "cUSD owned by the Safe"),
            (self._uint(CUSD_PLUS, "isSponsor(address)", ["address"], [SPONSOR]) == 1, "relayer is a cUSD+ sponsor"),
            (self._uint(CUSD, "isSponsor(address)", ["address"], [SPONSOR]) == 1, "relayer is a cUSD sponsor"),
            (self._uint(CUSD_PLUS, "isSponsor(address)", ["address"], [STOCK_ROUTER]) == 1,
             "stock router is a cUSD+ sponsor"),
            (self._uint(CUSD_PLUS, "isSponsor(address)", ["address"], [swap_router]) == 1,
             "swap router is a cUSD+ sponsor"),
            (self._uint(CUSD, "isSponsor(address)", ["address"], [swap_router]) == 1, "swap router is a cUSD sponsor"),
        ]
        for token, label in [(CUSD, "cUSD"), (CUSD_PLUS, "cUSD+"), (USDT, "USDT")]:
            checks.append((self._uint(token, "decimals()") == 18, f"{label} has 18 decimals"))
        now = int(time.time())
        for feed, desc in [(BTC_USD_FEED, "BTC / USD"), (XAU_USD_FEED, "XAU / USD")]:
            checks.append((self._string(feed, "description()") == desc, f"feed {feed} is {desc!r}"))
            checks.append((self._uint(feed, "decimals()") == 8, f"{desc} decimals 8"))
            out = bytes.fromhex(self._call(feed, "latestRoundData()")[2:])
            answer = int.from_bytes(out[32:64], "big", signed=True)
            updated = int.from_bytes(out[96:128], "big")
            age = now - updated
            checks.append((answer > 0 and age <= FEED_MAX_AGE[feed],
                           f"{desc} answer {answer / 1e8:,.2f}, updated {age}s ago (max {FEED_MAX_AGE[feed]})"))
        for ok, label in checks:
            self.stdout.write(f"  [{'ok' if ok else 'FAIL'}] {label}")
        if not all(ok for ok, _ in checks):
            raise CommandError("preflight failed")
        self.stdout.write(f"  CONFIO {confio} (== --expected-confio-token) · swap router {swap_router}")

    # ────────────────────────── post checks ──────────────────────────

    def _post_checks(self, confio, swap_router):
        for step in ("collector",) + TRIPLE:
            if not self._landed(step):
                raise CommandError(f"record {self.record_path} has no landed {step}")
        collector = self.record["collector"]["address"]
        impl = self.record["implementation"]["address"]
        logic = self.record["factory_logic"]["address"]
        proxy = self.record["factory_proxy"]["address"]
        f = proxy
        clone_hash = self.keccak(bytes.fromhex("363d3d373d3d3d363d73") + bytes.fromhex(impl[2:])
                                 + bytes.fromhex("5af43d82803e903d91602b57fd5bf3"))

        def word(a):
            return bytes(12) + bytes.fromhex(a[2:])

        impl_values = self._check_runtime("implementation", impl)
        expected_impl = [word(proxy), clone_hash] + [word(a) for a in self._impl_args(proxy, collector)[1:]]
        coll_values = self._check_runtime("collector", collector)
        logic_values = self._check_runtime("factory_logic", logic)
        self._check_runtime("factory_proxy", proxy)
        slot = _rpc(self.rpc_url, "eth_getStorageAt", [proxy, ERC1967_IMPL_SLOT, "latest"])
        checks = [
            (impl_values == expected_impl, "implementation immutables (declaration order) match the constructor args"),
            (sorted(coll_values) == sorted(word(a) for a in (CUSD, CUSD_PLUS, SAFE)), "collector immutables"),
            (self._addr(collector, "cusd()") == self.cs(CUSD), "collector.cusd == cUSD"),
            (self._addr(collector, "cusdPlus()") == self.cs(CUSD_PLUS), "collector.cusdPlus == cUSD+"),
            (self._addr(collector, "treasury()") == self.cs(SAFE), "collector.treasury == Safe"),
            (sorted(logic_values) == sorted([word(CUSD_PLUS), word(STOCK_ROUTER), word(logic)]),
             "factory logic immutables (CUSD_PLUS, STOCK_ROUTER, UUPS self)"),
            (self.cs("0x" + slot[-40:]) == self.cs(logic), "proxy ERC-1967 slot == factory logic"),
            (self._addr(impl, "FACTORY()") == self.cs(proxy), "implementation.FACTORY == factory proxy"),
            (self._addr(impl, "owner()") == self.cs("0x" + "00" * 20), "implementation is inert (owner 0)"),
            (self._addr(f, "owner()") == self.cs(SAFE), "factory.owner == Safe"),
            (self._addr(f, "pendingOwner()") == self.cs("0x" + "00" * 20), "factory.pendingOwner == 0"),
            (self._addr(f, "implementation()") == self.cs(impl), "factory.implementation == implementation"),
            (self._uint(f, "feeUsd(uint8)", ["uint8"], [1]) == MONTHLY_FEE_USD, "factory.feeUsd(1) == 14.99"),
            (self._uint(f, "feeUsd(uint8)", ["uint8"], [2]) == ANNUAL_FEE_USD, "factory.feeUsd(2) == 149.99"),
            (self._uint(f, "monthlyFeeUsd()") == MONTHLY_FEE_USD, "factory.monthlyFeeUsd == 14.99"),
            (self._uint(f, "annualFeeUsd()") == ANNUAL_FEE_USD, "factory.annualFeeUsd == 149.99"),
            (self._addr(f, "CUSD_PLUS()") == self.cs(CUSD_PLUS), "factory.CUSD_PLUS == cUSD+"),
            (self._addr(f, "STOCK_ROUTER()") == self.cs(STOCK_ROUTER), "factory.STOCK_ROUTER == stock router"),
            (self._uint(f, "inheritanceEnabled()") == 0, "inheritance starts off"),
            (self._uint(f, "relayerPaused()") == 0, "relayer not paused"),
            (self._uint(f, "paused()") == 0, "creation not paused"),
            (self._uint(f, "cardPaused()") == 0, "cards not paused"),
            (self._uint(f, "claimCooldown()") == 30 * DAY, "claimCooldown 30 days"),
            (self._uint(f, "forcedSaleNotice()") == 7 * DAY, "forcedSaleNotice 7 days"),
            (all(self._uint(f, "allowedChallengeWindows(uint64)", ["uint64"], [d * DAY]) == 1 for d in (90, 180, 365)),
             "challenge windows 90 / 180 / 365 days"),
            (self._call(f, "confioSale()") == "0x" + "00" * 64, "confioSale empty"),
            (self._uint(f, "generationOf(address)", ["address"], [SPONSOR]) == 0
             and self._addr(f, "predictAddress(address)", ["address"], [SPONSOR])
             == self._addr(f, "predictAddressAt(address,uint64)", ["address", "uint64"], [SPONSOR, 0]),
             "account address semantics (generation 0)"),
        ]
        self.stdout.write("\nPost-deploy checks:")
        for ok, label in checks:
            self.stdout.write(f"  [{'ok' if ok else 'FAIL'}] {label}")
        if not all(ok for ok, _ in checks):
            raise CommandError("POST-DEPLOY CHECKS FAILED: do not wire this factory")
        self.record["post_checks_passed_at"] = datetime.now(timezone.utc).isoformat()
        self.record["start_block"] = self.record["factory_proxy"]["block"]
        self.record["verify_args"] = {
            "collector": "0x" + self.abi_encode(["address"] * 3, [CUSD, CUSD_PLUS, SAFE]).hex(),
            "implementation": "0x" + self.abi_encode(["address"] * 12, self._impl_args(proxy, collector)).hex(),
            "factory_logic": "0x" + self.abi_encode(["address", "address"], [CUSD_PLUS, STOCK_ROUTER]).hex(),
            "factory_proxy": "0x" + self._proxy_args(impl, logic).hex(),
        }
        self._save()
        self.stdout.write(self.style.SUCCESS(f"\nCuenta inteligente deployed and verified · record {self.record_path}"))
        for step in ("collector",) + TRIPLE:
            e = self.record[step]
            self.stdout.write(f"  {step:<15} {e['address']}  tx {e['tx']}  block {e['block']}")

        self.stdout.write("\nServer settings (.env.mainnet; SMART_ACCOUNT_ENABLED stays False until the canary):")
        self.stdout.write(f"SMART_ACCOUNT_FACTORY_ADDRESS={proxy}")
        self.stdout.write(f"SMART_ACCOUNT_FEE_COLLECTOR_ADDRESS={collector}")
        self.stdout.write(f"SMART_ACCOUNT_START_BLOCK={self.record['start_block']}")

        self.stdout.write("\nBscScan verification (run in contracts/smart_account, ETHERSCAN_API_KEY from .env):")
        for step in ("collector",) + TRIPLE:
            self.stdout.write(
                f"forge verify-contract {self.record[step]['address']} '{SOURCE_PATHS[step]}' --chain bsc "
                f"--compiler-version {SOLC} --num-of-optimizations 100 --via-ir "
                f"--constructor-args {self.record['verify_args'][step]} "
                f"--etherscan-api-key \"$ETHERSCAN_API_KEY\" --watch")
        self.stdout.write(
            "Then mark the factory proxy as a proxy (Etherscan v2 verifyproxycontract, chainid=56, "
            f"address={proxy}, expectedimplementation={logic}); see contracts/cusd_plus/DEPLOYMENT.md.")
        self.stdout.write(
            "\nNext: deploy_cusd_impl, then build the Safe tx: "
            ".kms-local/kms_evm_multisig/build_smart_account_cusd_upgrade.py --cusd-impl <impl>")
