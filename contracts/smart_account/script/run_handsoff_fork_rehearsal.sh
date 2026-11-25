#!/usr/bin/env bash
# Hands-off v2 deployment rehearsal on a LOCAL anvil fork of BSC mainnet.
# Broadcasts only to the local anvil (refuses anything else); nothing is
# signed with a real key; Safe owners act through impersonated approveHash.
#
# Public RPCs keep ~2,000 blocks of state (about 15 minutes on BSC), so the
# whole run must finish soon after anvil starts. publicnode answers unknown
# tx-hash lookups with an 'archive' 403, which breaks anvil's receipt
# fallback; fork_rpc_proxy.py answers those with null. Usage:
#
#   python3 -I contracts/smart_account/script/fork_rpc_proxy.py https://bsc-rpc.publicnode.com 8598 &
#   anvil --fork-url http://127.0.0.1:8598 --port 8547 --auto-impersonate --chain-id 56 --retries 10 &
#   OUT=/tmp/handsoff-rehearsal contracts/smart_account/script/run_handsoff_fork_rehearsal.sh
#
# Env: RPC (default http://127.0.0.1:8547), OUT (log dir), USE_PLUS=1 (Trade
# rule in cUSD+; needs Ondo instant mint to work on the fork).
set -euo pipefail

RPC="${RPC:-http://127.0.0.1:8547}"
case "$RPC" in
  http://127.0.0.1:*|http://localhost:*) ;;
  *) echo "REFUSED: RPC must be a local anvil fork, got $RPC" >&2; exit 1 ;;
esac
cast rpc anvil_nodeInfo --rpc-url "$RPC" >/dev/null || { echo "REFUSED: not anvil" >&2; exit 1; }
[ "$(cast chain-id --rpc-url "$RPC")" = "56" ] || { echo "REFUSED: fork must use chain id 56" >&2; exit 1; }

HERE="$(cd "$(dirname "$0")/.." && pwd)"          # contracts/smart_account
CUSD_PLUS_DIR="$(cd "$HERE/../cusd_plus" && pwd)"
OUT="${OUT:-$(mktemp -d)}"
mkdir -p "$OUT"
SPONSOR=0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D
DELEGATE=0xC06BD197b34a587026615C6AEd21301F5E99bc00
SCRIPT=script/HandsOffV2ForkRehearsal.s.sol:HandsOffV2ForkRehearsal

fund() { cast rpc anvil_setBalance "$1" 0x8AC7230489E80000 --rpc-url "$RPC" >/dev/null; }   # 10 BNB, fork only
run() {  # run <sig> <logname>
  (cd "$HERE" && forge script "$SCRIPT" --sig "$1" --rpc-url "$RPC" --broadcast --unlocked --slow \
     --sender "$SPONSOR" -vv) > "$OUT/$2.log" 2>&1 || { tail -40 "$OUT/$2.log"; exit 1; }
  cp "$HERE/broadcast/HandsOffV2ForkRehearsal.s.sol/56/$(echo "$1" | tr -d '()')-latest.json" "$OUT/$2.broadcast.json" 2>/dev/null || true
  grep -E "OK|account|Safe nonce|0x" "$OUT/$2.log" | grep -v "^\s*\[" | head -30
}
view() { (cd "$HERE" && forge script "$SCRIPT" --sig "$1" --rpc-url "$RPC" -vv) > "$OUT/$2.log" 2>&1 || { tail -40 "$OUT/$2.log"; exit 1; }; }
warp() { cast rpc evm_increaseTime "$1" --rpc-url "$RPC" >/dev/null; cast rpc evm_mine --rpc-url "$RPC" >/dev/null; }

echo "fork block $(cast block-number --rpc-url "$RPC"), logs in $OUT"
for a in $SPONSOR 0xF977814e90dA44bFA03b6295A0616a897441aceC \
         0x3E5b538A721b25C974dAD8735B3679Fe69a2dA22 0x311153Bc7CD82D3D0c31A0d332DBFb3FF2bbf5f9 \
         0x13D29DeD5A7172244db2F35A61E7d785DAF2738c; do fund "$a"; done
ALICE=$(cast wallet address --private-key "$(cast keccak confio-fork-rehearsal-alice)")
BOB=$(cast wallet address --private-key "$(cast keccak confio-fork-rehearsal-bob)")
DANA=$(cast wallet address --private-key "$(cast keccak confio-fork-rehearsal-dana)")
for a in $ALICE $BOB $DANA; do fund "$a"; done

echo "== 1. v1 test accounts on the real factory (before the upgrade)"
run "setupV1()" 01-setupV1
view "snapshot()" 02-snapshot-pre

echo "== 2. deploy the implementations as the sponsor (the real scripts)"
(cd "$CUSD_PLUS_DIR" && forge script script/UpgradeConfioMarketEscrowDepositFrom.s.sol --rpc-url "$RPC" \
   --broadcast --unlocked --sender "$SPONSOR" -vv) > "$OUT/03-escrow-impl.log" 2>&1 || { tail -30 "$OUT/03-escrow-impl.log"; exit 1; }
NEW_ESCROW_IMPL=$(grep -m1 "NEW_IMPL" "$OUT/03-escrow-impl.log" | grep -oE "0x[0-9a-fA-F]{40}")
cp "$CUSD_PLUS_DIR/broadcast/UpgradeConfioMarketEscrowDepositFrom.s.sol/56/run-latest.json" "$OUT/03-escrow-impl.broadcast.json"
(cd "$HERE" && SMART_ACCOUNT_FACTORY_ADDRESS=0x339094A17605B842e0b2fc01441204E67020f953 \
   CONFIO_MARKET_ESCROW_ADDRESS=0x2DFDC1fB809322c12f54beFE8CC98E0d103a99Fd \
   CRYPTO_SWAP_ROUTER_ADDRESS=0xA7C27684aB38eC369cB1F4474f279ea503dbF712 \
   CONFIO_TOKEN_ADDRESS=0xF5765933764562A51e179F6AF2b19b7a3d506101 \
   SMART_ACCOUNT_FEE_COLLECTOR_ADDRESS=0x1AE0ACB82bAb9F506188c49305953CB655A539CD \
   V1_IMPLEMENTATION=0x8a20a0B3d2C0c6BED8BeB00bB6Bc7AE3c7ace44A \
   forge script script/DeploySmartAccountV2.s.sol --rpc-url "$RPC" --broadcast --unlocked --sender "$SPONSOR" -vv) \
   > "$OUT/04-v2-impl.log" 2>&1 || { tail -30 "$OUT/04-v2-impl.log"; exit 1; }
cp "$HERE/broadcast/DeploySmartAccountV2.s.sol/56/run-latest.json" "$OUT/04-v2-impl.broadcast.json"
V2_IMPL=$(grep -m1 "ConfioSmartAccountV2 (implementation)" "$OUT/04-v2-impl.log" | grep -oE "0x[0-9a-fA-F]{40}")
NEW_FACTORY_LOGIC=$(grep -m1 "ConfioSmartAccountFactory (new logic)" "$OUT/04-v2-impl.log" | grep -oE "0x[0-9a-fA-F]{40}")
export V2_IMPL NEW_FACTORY_LOGIC NEW_ESCROW_IMPL
echo "escrow impl $NEW_ESCROW_IMPL, v2 impl $V2_IMPL, factory logic $NEW_FACTORY_LOGIC"

echo "== 3. the Safe batch (MultiSendCallOnly, DELEGATECALL)"
run "safeBatch()" 05-safeBatch
view "snapshot()" 06-snapshot-post
diff <(grep "=" "$OUT/02-snapshot-pre.log" | sed 's/^ *//') <(grep "=" "$OUT/06-snapshot-post.log" | sed 's/^ *//') \
  > "$OUT/07-snapshot.diff" || true
echo "-- storage/getters that changed:"; cat "$OUT/07-snapshot.diff"
view "postChecks()" 08-postChecks && grep "postChecks" "$OUT/08-postChecks.log"

echo "== 4. owner's EOA delegated to the real ConfioBatchDelegate (7702 designator, fork only)"
cast rpc anvil_setCode "$ALICE" "0xef0100${DELEGATE#0x}" --rpc-url "$RPC" >/dev/null
run "phaseA()" 09-phaseA
warp 61
run "phaseB()" 10-phaseB
warp 61
run "phaseC()" 11-phaseC
warp $((4 * 24 * 3600))
run "phaseD()" 12-phaseD

echo "== gas (receipts)"
for f in "$OUT"/*.broadcast.json; do
  python3 - "$f" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
txs = d.get("transactions", []); rcs = d.get("receipts", [])
for t, r in zip(txs, rcs):
    fn = t.get("function") or t.get("transactionType")
    print(f"{sys.argv[1].split('/')[-1]:32s} {t['transaction'].get('from','')[:10]}  {str(t.get('contractName') or t.get('contractAddress') or '')[:28]:28s} {str(fn)[:60]:60s} gas={int(r['gasUsed'],16)}")
EOF
done | tee "$OUT/gas.txt"
echo "DONE: all phases passed. Logs: $OUT"
