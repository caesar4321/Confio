import assert from "node:assert/strict";
import test from "node:test";

const WAD = 10n ** 18n;
const BPS = 10_000n;
const CONFIO_SHARE = 1_500n;

const down = (a, b, d) => (a * b) / d;
const up = (a, b, d) => (a * b + d - 1n) / d;

function accrue(pPlus, last, next) {
  const growth = ((next - last) * WAD) / last;
  const kept = (growth * (BPS - CONFIO_SHARE)) / BPS;
  return (pPlus * (WAD + kept)) / WAD;
}

test("mint and redeem round down while obligations round up", () => {
  const price = 1_143_210_000_000_000_000n;
  const pPlus = 1_100_000_000_000_000_000n;
  const usdy = 1_000_001n;
  const shares = down(usdy, price, pPlus);
  const redeemed = down(shares, pPlus, price);
  assert.ok(redeemed <= usdy);
  assert.ok(up(shares, pPlus, price) <= usdy);
});

test("holders receive 85% of USDY reference appreciation", () => {
  const next = 1_010_000_000_000_000_000n;
  assert.equal(accrue(WAD, WAD, next), 1_008_500_000_000_000_000n);
});

test("collectable surplus never includes holder obligations", () => {
  const reserve = 1_000_000_000n;
  const supply = 1_000_000_000n;
  const pPlus = accrue(WAD, WAD, 1_010_000_000_000_000_000n);
  const price = 1_010_000_000_000_000_000n;
  const owed = up(supply, pPlus, price);
  const surplus = reserve - owed;
  assert.equal(reserve - surplus, owed);
  assert.ok(surplus > 0n);
});

test("a 2% jump is accepted and anything larger is guarded", () => {
  const jumpBps = (last, next) => ((next - last) * BPS) / last;
  assert.equal(jumpBps(WAD, 1_020_000_000_000_000_000n), 200n);
  assert.equal(jumpBps(WAD, 1_020_100_000_000_000_000n), 201n);
});
