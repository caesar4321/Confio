// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * Stateful invariant suite (2026-07-06) — what the seeded fuzz in
 * CusdPlusVault.t.sol cannot prove:
 *
 *  - MULTI-ACTOR: three users mint/redeem/transfer around accruals and fee
 *    collections, so share fairness interactions are exercised.
 *  - LIVENESS, not just safety: fail_on_revert = true and the handler never
 *    try/catches — if an entitled withdrawal ever reverts, the run fails.
 *    (The seeded fuzz swallowed reverts, so a vault that rejected every
 *    redeem would still have passed it.)
 *  - FULL EXIT: afterInvariant() redeems every actor to zero and requires
 *    the vault to stay solvent to the last share.
 *
 * Invariants:
 *   I1  backingRatioBps() >= 10_000 after every op (vault USDY >= owed)
 *   I2  pPlus never decreases (asserted inside the handler after every op)
 *   I3  full exit always succeeds; only treasury surplus (and sub-wei share
 *       dust worth < 1 USDY-wei) may remain
 */
import {Test} from "forge-std/Test.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {CusdPlusVault} from "../CusdPlusVault.sol";
import {MockToken, MockOracle, MockInstantManager} from "./CusdPlusVault.t.sol";

contract VaultHandler is Test {
    CusdPlusVault public immutable vault;
    MockToken public immutable usdt;
    MockToken public immutable usdy;
    MockOracle public immutable oracle;
    address public immutable treasury;

    address[3] public actors;
    uint256 public lastSeenPPlus; // I2 ghost
    uint256 public collectedFees; // ghost: everything treasury withdrew

    constructor(
        CusdPlusVault _vault,
        MockToken _usdt,
        MockToken _usdy,
        MockOracle _oracle,
        address _treasury
    ) {
        vault = _vault;
        usdt = _usdt;
        usdy = _usdy;
        oracle = _oracle;
        treasury = _treasury;
        actors[0] = makeAddr("alice");
        actors[1] = makeAddr("bob");
        actors[2] = makeAddr("carol");
        for (uint256 i = 0; i < 3; i++) {
            vm.startPrank(actors[i]);
            usdt.approve(address(vault), type(uint256).max);
            usdy.approve(address(vault), type(uint256).max);
            vm.stopPrank();
        }
        vm.startPrank(_treasury);
        usdt.approve(address(vault), type(uint256).max);
        usdy.approve(address(vault), type(uint256).max);
        vm.stopPrank();
        lastSeenPPlus = vault.pPlus();
    }

    // ── ops (every path bounded so it MUST succeed) ──────────────────────

    function subscribe(uint256 actorSeed, uint256 amount) external {
        address a = actors[actorSeed % 3];
        amount = bound(amount, 1e18, 100_000e18);
        usdt.mint(a, amount);
        vm.prank(a);
        vault.subscribeAndMint(amount, 0, a);
        _afterOp();
    }

    /// Owner-gated USDY entry (treasury bridge leg): the Safe deposits raw
    /// USDY and an ordinary holder receives the shares.
    function depositUsdy(uint256 actorSeed, uint256 amount) external {
        address a = actors[actorSeed % 3];
        amount = bound(amount, 1e18, 100_000e18);
        usdy.mint(treasury, amount);
        vm.prank(treasury);
        vault.depositAndMint(amount, a);
        _afterOp();
    }

    /// Owner-gated raw-USDY exit: the treasury cycles its own shares out.
    /// Bounded above the dust floor so the call must succeed — raw-redeem
    /// liveness for the one caller allowed to use it.
    function treasuryRawRedeem(uint256 amount) external {
        amount = bound(amount, 1e18, 100_000e18);
        usdy.mint(treasury, amount);
        vm.startPrank(treasury);
        vault.depositAndMint(amount, treasury);
        uint256 bal = vault.balanceOf(treasury);
        uint256 minShares = _minRedeemableShares();
        if (bal >= minShares) vault.redeem(bal, treasury);
        vm.stopPrank();
        _afterOp();
    }

    function redeemToUsdt(uint256 actorSeed, uint256 shares) external {
        address a = actors[actorSeed % 3];
        uint256 bal = vault.balanceOf(a);
        uint256 minShares = _minRedeemableShares();
        if (bal < minShares) return;
        shares = bound(shares, minShares, bal);
        vm.prank(a);
        vault.redeemToUsdt(shares, 0, a);
        _afterOp();
    }

    /// Plain ERC-20 transfer between actors (exercises _update).
    function transferShares(uint256 fromSeed, uint256 toSeed, uint256 shares) external {
        address from = actors[fromSeed % 3];
        address to = actors[toSeed % 3];
        uint256 bal = vault.balanceOf(from);
        if (bal == 0 || from == to) return;
        shares = bound(shares, 1, bal);
        vm.prank(from);
        vault.transfer(to, shares);
        _afterOp();
    }

    /// USDY drips a few bps and the vault accrues — the normal yield path.
    /// Bounded well under the 200bps jump guard.
    function accrueUp(uint256 drip) external {
        drip = bound(drip, 1, 30);
        oracle.setPrice((oracle.price() * (10_000 + drip)) / 10_000);
        vault.accrue();
        _afterOp();
    }

    /// Oracle moves but nobody calls accrue() — the next mint/redeem must
    /// pick it up internally (lazy accrual path).
    function driftWithoutAccrue(uint256 drip) external {
        drip = bound(drip, 1, 30);
        oracle.setPrice((oracle.price() * (10_000 + drip)) / 10_000);
        _afterOp();
    }

    function collectSomeFees(uint256 amount) external {
        vault.accrue(); // settle any pending drift so surplus is exact
        uint256 surplus = vault.surplusUsdy(oracle.price());
        if (surplus == 0) return;
        amount = bound(amount, 1, surplus);
        vm.prank(treasury);
        vault.collectFees(treasury, amount);
        collectedFees += amount;
        _afterOp();
    }

    /// Direct-transfer griefing: donations must only ever HELP backing.
    function donateUsdy(uint256 amount) external {
        amount = bound(amount, 1, 10_000e18);
        usdy.mint(address(vault), amount);
        _afterOp();
    }

    function donateUsdt(uint256 amount) external {
        amount = bound(amount, 1, 10_000e18);
        usdt.mint(address(vault), amount);
        _afterOp();
    }

    // ── helpers ──────────────────────────────────────────────────────────

    /// Smallest share count whose redemption clears the "dust" floor
    /// (shares * pPlus / p >= 1).
    function _minRedeemableShares() internal view returns (uint256) {
        uint256 p = oracle.price();
        uint256 pPlus = vault.pPlus();
        return (p + pPlus - 1) / pPlus;
    }

    function _afterOp() internal {
        // I2: pPlus is monotonically non-decreasing, checked on EVERY op.
        uint256 pp = vault.pPlus();
        require(pp >= lastSeenPPlus, "I2: pPlus decreased");
        lastSeenPPlus = pp;
    }

    function actorCount() external pure returns (uint256) {
        return 3;
    }
}

contract CusdPlusVaultInvariantTest is Test {
    MockToken usdt;
    MockToken usdy;
    MockOracle oracle;
    MockInstantManager im;
    CusdPlusVault vault;
    VaultHandler handler;

    address treasury = makeAddr("treasury");

    function setUp() public {
        usdt = new MockToken("USDT");
        usdy = new MockToken("USDY");
        oracle = new MockOracle();
        im = new MockInstantManager(usdt, usdy, oracle);
        usdt.mint(address(im), 1_000_000_000e18);
        usdy.mint(address(im), 1_000_000_000e18);

        CusdPlusVault impl = new CusdPlusVault(
            address(usdy), address(usdt), address(im), address(oracle), 1500
        );
        ERC1967Proxy proxy = new ERC1967Proxy(
            address(impl), abi.encodeCall(CusdPlusVault.initialize, (treasury))
        );
        vault = CusdPlusVault(address(proxy));

        handler = new VaultHandler(vault, usdt, usdy, oracle, treasury);
        targetContract(address(handler));
    }

    /// I1: the public invariant — vault USDY covers what holders are owed.
    function invariant_backingNeverBelow100() public view {
        assertGe(vault.backingRatioBps(), 10_000, "I1: backing broken");
    }

    /// I1 restated at the raw-balance level (avoids the view's own division).
    function invariant_vaultHoldsWhatItOwes() public view {
        uint256 p = oracle.price();
        assertGe(
            usdy.balanceOf(address(vault)),
            vault.usdyOwed(p),
            "I1: owed exceeds balance"
        );
    }

    /// I3: after any op sequence, EVERY holder can exit fully (via the
    /// holder exit, redeemToUsdt — raw redeem is owner-only), and the vault
    /// stays solvent to the last share. Only surplus + sub-wei dust remain.
    function afterInvariant() public {
        uint256 p = oracle.price();
        for (uint256 i = 0; i < handler.actorCount(); i++) {
            address a = handler.actors(i);
            uint256 bal = vault.balanceOf(a);
            if (bal == 0) continue;
            if ((bal * vault.pPlus()) / p == 0) continue; // < 1 USDY-wei of value
            vm.prank(a);
            vault.redeemToUsdt(bal, 0, a); // MUST NOT revert — liveness at full size
        }
        assertGe(vault.backingRatioBps(), 10_000, "I3: insolvent at exit");
        // Whatever supply remains is dust worth < 1 USDY-wei per holder.
        assertLe(
            (vault.totalSupply() * vault.pPlus()) / p,
            handler.actorCount(),
            "I3: more than dust stranded"
        );
    }
}
