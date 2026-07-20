#!/usr/bin/env python3
"""
Independent Python mirror of CusdPlusVault's accrual/share math
(CusdPlusVault.sol), used for DIFFERENTIAL testing: this file generates
random-but-deterministic op sequences, computes the expected vault state
after every step with its own integer arithmetic, and freezes both into
vectors.json. CusdPlusVault.differential.t.sol replays the same ops against
the real contract and asserts exact equality at every step.

Why: rounding-direction bugs (WAD/BPS floors and ceils drifting the wrong
way over thousands of ops) are invisible to invariant tests that only check
inequalities. Two independently written implementations agreeing to the wei
is the cheapest strong evidence the math is what we think it is.

Mirrored semantics (MUST track CusdPlusVault.sol exactly):
  accrue(p):   no-op if p == last or guard tripped;
               trip guard if p < last or (p-last)*BPS//last > 200;
               else growth = (p-last)*WAD//last
                    kept   = growth*(BPS-1500)//BPS
                    pPlus  = pPlus*(WAD+kept)//WAD ; last = p
  mint:        accrue first; require guard NOT tripped;
               shares = usdyIn*p//pPlus (floor, require > 0)
  redeem:      accrue first; require guard NOT tripped;
               usdyOut = shares*pPlus//p (floor, require > 0)
  owed(p):     ceil(totalSupply*pPlus/p)  = (ts*pPlus + p - 1)//p
  surplus(p):  max(bal - owed(p), 0)
  collect(x):  accrue first; require guard NOT tripped;
               require x <= surplus; bal -= x
  rebaseline:  require guard tripped; last = current price; guard
               untripped (no accrual granted — verified-fault verdict)
  accept:      require guard tripped and price > last; apply the ordinary
               85/15 growth from last to price; guard untripped
               (verified-growth verdict — same math as accrue)

Regenerate with:  python3 test/mirror/mirror_accrual.py
"""
import json
import random
from pathlib import Path

WAD = 10**18
BPS = 10_000
SHARE_BPS = 1_500  # CONFIO_YIELD_SHARE_BPS in the test deployment
MAX_JUMP_BPS = 200


class VaultMirror:
    def __init__(self):
        self.p_plus = WAD
        self.last = WAD  # oracle price at initialize()
        self.tripped = False
        self.total_supply = 0
        self.bal = 0  # vault USDY balance
        self.price = WAD  # current oracle price

    def set_price(self, p):
        self.price = p

    def accrue(self):
        p, last = self.price, self.last
        if p == last or self.tripped:
            return
        if p < last or (p - last) * BPS // last > MAX_JUMP_BPS:
            self.tripped = True
            return
        self._apply_growth()

    def mint(self, usdy_in):
        self.accrue()
        # Contract reverts every value exchange while the guard is tripped.
        assert not self.tripped, "oracle guard tripped"
        shares = usdy_in * self.price // self.p_plus
        assert shares > 0, "dust mint in generator"
        self.total_supply += shares
        self.bal += usdy_in
        return shares

    def redeem(self, shares):
        self.accrue()
        assert not self.tripped, "oracle guard tripped"
        usdy_out = shares * self.p_plus // self.price
        assert usdy_out > 0, "dust redeem in generator"
        self.total_supply -= shares
        self.bal -= usdy_out
        return usdy_out

    def owed(self):
        return (self.total_supply * self.p_plus + self.price - 1) // self.price

    def surplus(self):
        o = self.owed()
        return self.bal - o if self.bal > o else 0

    def collect(self, amount):
        self.accrue()
        assert not self.tripped, "oracle guard tripped"
        assert amount <= self.surplus()
        self.bal -= amount

    def _apply_growth(self):
        growth = (self.price - self.last) * WAD // self.last
        kept = growth * (BPS - SHARE_BPS) // BPS
        self.p_plus = self.p_plus * (WAD + kept) // WAD
        self.last = self.price

    def rebaseline(self):
        # Verified-fault verdict: adopt price as baseline, window to surplus.
        # Contract requires a tripped guard (never skips healthy growth).
        assert self.tripped, "guard not tripped"
        self.last = self.price
        self.tripped = False

    def accept_growth(self):
        # Verified-growth verdict: holders keep 85% exactly as if accrue()
        # had kept up. Same math path as accrue by construction.
        assert self.tripped, "guard not tripped"
        assert self.price > self.last, "no positive growth"
        self.tripped = False
        self._apply_growth()

    def state(self):
        return {
            "pPlus": str(self.p_plus),
            "lastOraclePrice": str(self.last),
            "tripped": self.tripped,
            "totalSupply": str(self.total_supply),
            "vaultUsdy": str(self.bal),
        }


def _would_be_tripped(m: VaultMirror) -> bool:
    """True if the guard is already tripped OR the next accrue() would trip
    it (a setPriceOnly step may have staged an anomalous price).

    Vectors must contain NO value op in either state: on-chain such a call
    reverts (rolling back the in-call trip), while this Python model has no
    rollback — emitting one would fork the two state machines."""
    if m.tripped:
        return True
    p, last = m.price, m.last
    if p == last:
        return False
    return p < last or (p - last) * BPS // last > MAX_JUMP_BPS


def min_redeemable_shares(m: VaultMirror) -> int:
    # shares * pPlus // price >= 1  ⇒  shares >= ceil(price / pPlus)
    return (m.price + m.p_plus - 1) // m.p_plus


def generate(seed: int, steps_n: int):
    rng = random.Random(seed)
    m = VaultMirror()
    holder_shares = 0  # single mirrored holder is enough for global math
    steps = []

    def emit(op, arg, ret=""):
        steps.append({"op": op, "arg": str(arg), "ret": str(ret), **m.state()})

    for i in range(steps_n):
        roll = rng.random()
        if roll < 0.22:
            # normal yield drip 1..25 bps, explicit accrue
            drip = rng.randint(1, 25)
            m.set_price(m.price * (BPS + drip) // BPS)
            m.accrue()
            emit("setPriceAccrue", m.price)
        elif roll < 0.32:
            # price drifts, NOBODY accrues — next op exercises lazy accrual
            drip = rng.randint(1, 25)
            m.set_price(m.price * (BPS + drip) // BPS)
            emit("setPriceOnly", m.price)
        elif roll < 0.37 and not m.tripped:
            # fault injection: >2% jump must trip the guard, freezing pPlus
            jump = rng.randint(300, 900)
            m.set_price(m.price * (BPS + jump) // BPS)
            m.accrue()
            assert m.tripped
            emit("setPriceAccrue", m.price)
        elif roll < 0.42 and m.tripped:
            if rng.random() < 0.5:
                m.accept_growth()
                emit("acceptGrowth", 0)
            else:
                m.rebaseline()
                emit("rebaseline", 0)
        elif roll < 0.72 and not _would_be_tripped(m):
            # mint with awkward amounts, incl. 1-wei and prime-ish values
            usdy_in = rng.choice([
                1,
                rng.randint(2, 10**12),
                rng.randint(10**12, 10**21),
                rng.randint(1, 10**23) | 1,
            ])
            # ensure not a dust mint at current prices
            if usdy_in * m.price // m.p_plus == 0:
                usdy_in = (m.p_plus + m.price - 1) // m.price
            ret = m.mint(usdy_in)
            holder_shares += ret
            emit("mint", usdy_in, ret)
        elif roll < 0.92 and holder_shares > 0 and not _would_be_tripped(m):
            lo = min_redeemable_shares(m)
            if holder_shares < lo:
                continue
            shares = rng.randint(lo, holder_shares)
            ret = m.redeem(shares)
            holder_shares -= shares
            emit("redeem", shares, ret)
        else:
            # collect() accrues first (contract semantics), which can shrink
            # surplus when price drifted un-accrued — bound on a lookahead.
            if _would_be_tripped(m):
                continue
            import copy
            look = copy.deepcopy(m)
            look.accrue()
            s = look.surplus()
            if s == 0:
                continue
            amount = rng.randint(1, s)
            m.collect(amount)
            emit("collect", amount)

    return steps


def main():
    sequences = [
        generate(seed=1, steps_n=140),
        generate(seed=20260706, steps_n=140),
        generate(seed=0xC0FFEE, steps_n=140),
    ]
    out = {"sequences": []}
    for s in sequences:
        out["sequences"].append({"n": len(s), "steps": s})
    path = Path(__file__).parent / "vectors.json"
    path.write_text(json.dumps(out, indent=0))
    total = sum(len(s) for s in sequences)
    print(f"wrote {total} steps across {len(sequences)} sequences to {path}")


if __name__ == "__main__":
    main()
