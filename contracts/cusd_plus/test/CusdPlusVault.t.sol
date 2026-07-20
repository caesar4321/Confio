// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {CusdPlusVault, IRWADynamicOracle, IOndoInstantManager} from "../CusdPlusVault.sol";

// ── Mocks ────────────────────────────────────────────────────────────────

contract MockToken is ERC20 {
    constructor(string memory n) ERC20(n, n) {}
    function mint(address to, uint256 amt) external { _mint(to, amt); }
}

contract MockOracle is IRWADynamicOracle {
    uint256 public price = 1e18;
    function setPrice(uint256 p) external { price = p; }
    function getPrice() external view returns (uint256) { return price; }
}

/// Swaps USDT <-> USDY at the oracle price, no spread (Instant Manager
/// semantics). Pre-funded with both tokens in setUp.
contract MockInstantManager is IOndoInstantManager {
    MockToken public usdt;
    MockToken public usdy;
    MockOracle public oracle;

    constructor(MockToken _usdt, MockToken _usdy, MockOracle _oracle) {
        usdt = _usdt;
        usdy = _usdy;
        oracle = _oracle;
    }

    function subscribe(address depositToken, uint256 depositAmount, uint256 minimumRwaReceived)
        external
        returns (uint256 rwaAmountOut)
    {
        require(depositToken == address(usdt), "im: unsupported deposit token");
        usdt.transferFrom(msg.sender, address(this), depositAmount);
        rwaAmountOut = (depositAmount * 1e18) / oracle.price();
        require(rwaAmountOut >= minimumRwaReceived, "im slippage");
        usdy.transfer(msg.sender, rwaAmountOut);
    }

    function redeem(uint256 rwaAmount, address receivingToken, uint256 minimumTokenReceived)
        external
        returns (uint256 receiveTokenAmount)
    {
        require(receivingToken == address(usdt), "im: unsupported receive token");
        usdy.transferFrom(msg.sender, address(this), rwaAmount);
        receiveTokenAmount = (rwaAmount * oracle.price()) / 1e18;
        require(receiveTokenAmount >= minimumTokenReceived, "im slippage");
        usdt.transfer(msg.sender, receiveTokenAmount);
    }
}

contract BrickedVault is CusdPlusVault {
    constructor(address a, address b, address c, address d, uint256 e)
        CusdPlusVault(a, b, c, d, e) {}
    function marker() external pure returns (uint256) { return 42; }
}

// ── Tests ────────────────────────────────────────────────────────────────

contract CusdPlusVaultTest is Test {
    MockToken usdt;
    MockToken usdy;
    MockOracle oracle;
    MockInstantManager im;
    CusdPlusVault vault; // via proxy

    address treasury = makeAddr("treasury");
    address user = makeAddr("user");
    address user2 = makeAddr("user2");

    uint256 constant WAD = 1e18;

    function setUp() public {
        usdt = new MockToken("USDT");
        usdy = new MockToken("USDY");
        oracle = new MockOracle();
        im = new MockInstantManager(usdt, usdy, oracle);
        usdt.mint(address(im), 100_000_000e18);
        usdy.mint(address(im), 100_000_000e18);

        CusdPlusVault impl = new CusdPlusVault(
            address(usdy), address(usdt), address(im), address(oracle), 1500
        );
        ERC1967Proxy proxy = new ERC1967Proxy(
            address(impl),
            abi.encodeCall(CusdPlusVault.initialize, (treasury))
        );
        vault = CusdPlusVault(address(proxy));

        usdt.mint(user, 1_000_000e18);
        vm.prank(user);
        usdt.approve(address(vault), type(uint256).max);
    }

    function _backed() internal view returns (bool) {
        return vault.backingRatioBps() >= 10_000;
    }

    // ── Mint / redeem ────────────────────────────────────────────────

    function test_subscribeAndMint_atPar() public {
        vm.prank(user);
        uint256 shares = vault.subscribeAndMint(1000e18, 990e18, user);
        assertEq(shares, 1000e18, "1 USDT = 1 share at $1.00");
        assertEq(vault.balanceOf(user), 1000e18);
        assertEq(vault.totalOwedUsd(), 1000e18);
        assertTrue(_backed());
    }

    // Raw-USDY paths are owner-only (PP representations: USDY never
    // touches holder wallets; the sole holder exit is redeemToUsdt).

    function test_depositAndMint_directUsdy_ownerOnly() public {
        usdy.mint(treasury, 500e18);
        vm.startPrank(treasury);
        usdy.approve(address(vault), type(uint256).max);
        uint256 shares = vault.depositAndMint(500e18, treasury);
        vm.stopPrank();
        assertEq(shares, 500e18);
        assertTrue(_backed());
    }

    function test_depositAndMint_rejects_nonOwner() public {
        usdy.mint(user, 500e18);
        vm.startPrank(user);
        usdy.approve(address(vault), type(uint256).max);
        vm.expectRevert(); // OwnableUnauthorizedAccount
        vault.depositAndMint(500e18, user);
        vm.stopPrank();
    }

    function test_redeem_roundTrip_ownerOnly() public {
        // treasury acquires shares (subscribe like any depositor), then
        // exercises the raw-USDY exit that only it may use
        usdt.mint(treasury, 1000e18);
        vm.startPrank(treasury);
        usdt.approve(address(vault), type(uint256).max);
        uint256 shares = vault.subscribeAndMint(1000e18, 990e18, treasury);
        uint256 usdyOut = vault.redeem(shares);
        vm.stopPrank();
        assertEq(vault.totalSupply(), 0);
        assertApproxEqAbs(usdyOut, 1000e18, 2, "floor rounding only");
        assertEq(usdy.balanceOf(treasury), usdyOut);
    }

    function test_redeem_rejects_holder() public {
        vm.startPrank(user);
        uint256 shares = vault.subscribeAndMint(1000e18, 990e18, user);
        vm.expectRevert(); // OwnableUnauthorizedAccount
        vault.redeem(shares);
        vm.stopPrank();
        // the holder's exit still works, and pays USDT — never USDY
        vm.prank(user);
        vault.redeemToUsdt(shares, 999e18, user);
        assertEq(usdy.balanceOf(user), 0, "no raw USDY ever reaches a holder");
    }

    function test_redeemToUsdt() public {
        vm.startPrank(user);
        uint256 shares = vault.subscribeAndMint(1000e18, 990e18, user);
        uint256 usdtOut = vault.redeemToUsdt(shares, 999e18, user2);
        vm.stopPrank();
        assertApproxEqAbs(usdtOut, 1000e18, 2);
        assertEq(usdt.balanceOf(user2), usdtOut);
        assertTrue(_backed());
    }

    function test_mint_slippageFloor_reverts() public {
        oracle.setPrice(1.01e18); // 1000 USDT -> ~990 USDY
        vm.prank(user);
        vm.expectRevert();
        vault.subscribeAndMint(1000e18, 995e18, user);
    }

    // ── Accrual & fee split ──────────────────────────────────────────

    function test_accrue_keeps85pct() public {
        vm.prank(user);
        vault.subscribeAndMint(1000e18, 990e18, user);
        oracle.setPrice(1.001e18); // +10 bps
        vault.accrue();
        // holders keep 8.5 bps of the 10
        assertEq(vault.pPlus(), (WAD * (WAD + 0.00085e18)) / WAD);
        assertTrue(_backed());
    }

    function test_feeSurplus_only_above_full_backing() public {
        vm.prank(user);
        vault.subscribeAndMint(100_000e18, 99_000e18, user);
        oracle.setPrice(1.01e18); // +1% USDY yield
        vault.accrue();

        uint256 p = oracle.price();
        uint256 surplus = vault.surplusUsdy(p);
        assertGt(surplus, 0, "15pct of the yield must be withdrawable");

        // more than surplus: rejected
        vm.prank(treasury);
        vm.expectRevert(bytes("exceeds surplus"));
        vault.collectFees(surplus + 1);

        // exact surplus: fine, and backing still >= 100%
        vm.prank(treasury);
        vault.collectFees(surplus);
        assertEq(usdy.balanceOf(treasury), surplus);
        assertTrue(_backed());
    }

    function test_userValue_grows_at_85pct_of_yield() public {
        vm.prank(user);
        vault.subscribeAndMint(1000e18, 990e18, user);
        // One +1% step (single steps > 2% trip the jump guard by design —
        // USDY moves a few bps/day; see test_jumpGuard_freezes_not_bricks).
        oracle.setPrice(1.01e18);
        vault.accrue();
        uint256 valueUsd = (vault.balanceOf(user) * vault.pPlus()) / WAD;
        assertEq(valueUsd, 1008.5e18, "user keeps 85% of 1% = 0.85%");
    }

    function test_multiStep_compounding_favors_backing() public {
        vm.prank(user);
        vault.subscribeAndMint(1000e18, 990e18, user);
        // Four +1% steps = USDY +4.06%; per-step compounding gives holders
        // (1.0085)^4 - 1 = 3.445%, a hair under 85% of the total 4.06% —
        // the drift lands in surplus, never against backing.
        uint256 price = WAD;
        for (uint256 i = 0; i < 4; i++) {
            price = (price * 101) / 100;
            oracle.setPrice(price);
            vault.accrue();
        }
        uint256 valueUsd = (vault.balanceOf(user) * vault.pPlus()) / WAD;
        assertApproxEqRel(valueUsd, 1034.4e18, 0.001e18);
        uint256 kept85OfTotal = 1000e18 + (1000e18 * (price - WAD) / WAD) * 8500 / 10_000;
        assertLe(valueUsd, kept85OfTotal, "compounding drift must favor surplus");
        assertGe(vault.backingRatioBps(), 10_000);
    }

    // ── Oracle jump guard ────────────────────────────────────────────

    /// A tripped guard means the live price is suspect — every value
    /// exchange halts. EVM nuance: a value path that DETECTS the anomaly
    /// reverts, which rolls the trip flag back with everything else, so
    /// value paths block-but-record-nothing; only a standalone accrue()
    /// (the daily keeper) persists the trip. Both branches tested here.
    function test_jumpGuard_halts_valuePaths_untilReset() public {
        vm.prank(user);
        vault.subscribeAndMint(1000e18, 990e18, user);
        uint256 pBefore = vault.pPlus();

        oracle.setPrice(1.03e18); // +3% in one step: fault

        // Value path BEFORE any keeper run: blocks at the bad price, but
        // the revert also rolls back the flag — nothing persisted.
        vm.prank(user);
        vm.expectRevert(bytes("oracle guard tripped"));
        vault.subscribeAndMint(100e18, 0, user);
        assertFalse(vault.oracleGuardTripped(), "revert rolled the flag back");

        // The keeper's standalone accrue() is what persists the trip.
        vault.accrue();
        assertTrue(vault.oracleGuardTripped(), "keeper persisted the trip");
        assertEq(vault.pPlus(), pBefore, "no accrual on faulty read");

        // every value path is halted while tripped
        vm.prank(user);
        vm.expectRevert(bytes("oracle guard tripped"));
        vault.subscribeAndMint(100e18, 0, user);
        vm.prank(user);
        vm.expectRevert(bytes("oracle guard tripped"));
        vault.redeemToUsdt(100e18, 0, user);
        usdy.mint(treasury, 1e18);
        vm.startPrank(treasury);
        usdy.approve(address(vault), type(uint256).max);
        vm.expectRevert(bytes("oracle guard tripped"));
        vault.depositAndMint(1e18, treasury);
        vm.expectRevert(bytes("oracle guard tripped"));
        vault.redeem(1e18);
        vm.expectRevert(bytes("oracle guard tripped"));
        vault.collectFees(1);
        vm.stopPrank();

        // a fault verdict reopens everything, window forfeited to surplus
        vm.prank(treasury);
        vault.rebaselineAfterVerifiedOracleFault(keccak256("incident-2026-07-13"));
        assertFalse(vault.oracleGuardTripped());
        assertEq(vault.pPlus(), pBefore, "frozen-window yield goes to surplus");
        vm.prank(user);
        vault.subscribeAndMint(100e18, 0, user);
        assertTrue(_backed());
    }

    /// The other keeper-timing branch: a transient glitch that NO keeper
    /// observes self-heals. Value paths block during the glitch (recording
    /// nothing), and once the oracle recovers they simply work again — no
    /// trip persisted, no reset, no forfeited yield.
    function test_jumpGuard_transientGlitch_selfHeals() public {
        vm.prank(user);
        vault.subscribeAndMint(1000e18, 990e18, user);

        uint256 healthy = oracle.price();
        oracle.setPrice(0.5e18); // glitch: absurd low read
        vm.prank(user);
        vm.expectRevert(bytes("oracle guard tripped"));
        vault.redeemToUsdt(100e18, 0, user);
        assertFalse(vault.oracleGuardTripped(), "glitch not persisted");

        oracle.setPrice(healthy); // oracle recovers before any keeper run
        vm.prank(user);
        vault.redeemToUsdt(100e18, 0, user); // works, no intervention
        assertTrue(_backed());
    }

    function test_decreasingOracle_trips_guard() public {
        oracle.setPrice(0.999e18);
        vault.accrue();
        assertTrue(vault.oracleGuardTripped());
    }

    /// Regression (2026-07-13 review): reset is incident response ONLY.
    /// Without the tripped-guard gate, the owner could re-baseline past
    /// healthy sub-2% growth before anyone accrues, silently converting
    /// the holders' 85% into owner-collectable surplus.
    function test_reset_requiresTrippedGuard_cannotSkipHealthyYield() public {
        vm.prank(user);
        vault.subscribeAndMint(1000e18, 990e18, user);

        // Ordinary +1% USDY appreciation, not yet accrued: BOTH verdicts
        // must revert — neither may skip healthy growth past accrue().
        oracle.setPrice(1.01e18);
        vm.startPrank(treasury);
        vm.expectRevert(bytes("guard not tripped"));
        vault.rebaselineAfterVerifiedOracleFault(keccak256("e"));
        vm.expectRevert(bytes("guard not tripped"));
        vault.acceptVerifiedOracleGrowth(keccak256("e"));
        vm.stopPrank();

        // The growth is still the holders' to claim — anyone can accrue.
        vault.accrue();
        assertEq(vault.pPlus(), WAD + (0.01e18 * 8500) / 10_000, "holders keep 85%");

        // A genuinely tripped guard allows the fault verdict.
        oracle.setPrice(1.05e18); // ~+4% from 1.01: fault
        vault.accrue();
        assertTrue(vault.oracleGuardTripped());
        vm.prank(treasury);
        vault.rebaselineAfterVerifiedOracleFault(keccak256("incident"));
        assertFalse(vault.oracleGuardTripped());
    }

    /// The accept verdict: a verified-legitimate jump (e.g. long keeper gap)
    /// preserves holder economics EXACTLY as if accrue() had kept up —
    /// fairness does not depend on keeper uptime.
    function test_acceptVerifiedGrowth_preserves8515() public {
        vm.prank(user);
        vault.subscribeAndMint(1000e18, 990e18, user);

        oracle.setPrice(1.03e18); // +3%: real accumulation past the guard
        vault.accrue();
        assertTrue(vault.oracleGuardTripped());
        uint256 pBefore = vault.pPlus();

        vm.prank(treasury);
        vault.acceptVerifiedOracleGrowth(keccak256("ondo-notice-hash"));
        assertFalse(vault.oracleGuardTripped());
        // same math as accrue: pPlus grows by 85% of the full 3%
        assertEq(vault.pPlus(), (pBefore * (WAD + (0.03e18 * 8500) / 10_000)) / WAD);
        assertEq(vault.lastOraclePrice(), 1.03e18);
        assertTrue(_backed());
    }

    function test_verdicts_require_evidence_and_direction() public {
        oracle.setPrice(0.9e18); // drop: trips
        vault.accrue();
        assertTrue(vault.oracleGuardTripped());

        vm.startPrank(treasury);
        vm.expectRevert(bytes("missing evidence"));
        vault.acceptVerifiedOracleGrowth(bytes32(0));
        vm.expectRevert(bytes("missing evidence"));
        vault.rebaselineAfterVerifiedOracleFault(bytes32(0));
        // a DROP can never be accepted as growth
        vm.expectRevert(bytes("not positive growth"));
        vault.acceptVerifiedOracleGrowth(keccak256("e"));
        // but a verified fault can rebaseline downward (pPlus untouched)
        uint256 pBefore = vault.pPlus();
        vault.rebaselineAfterVerifiedOracleFault(keccak256("e"));
        vm.stopPrank();
        assertEq(vault.pPlus(), pBefore);
        assertEq(vault.lastOraclePrice(), 0.9e18);

        // non-owner can render no verdict
        oracle.setPrice(0.8e18);
        vault.accrue();
        vm.startPrank(user);
        vm.expectRevert();
        vault.acceptVerifiedOracleGrowth(keccak256("e"));
        vm.expectRevert();
        vault.rebaselineAfterVerifiedOracleFault(keccak256("e"));
        vm.stopPrank();
    }

    // ── Freeze (cusd.py parity) ──────────────────────────────────────

    function test_freeze_blocks_everything_detains_not_confiscates() public {
        vm.prank(user);
        vault.subscribeAndMint(1000e18, 990e18, user);

        vm.prank(treasury);
        vault.freezeAddress(user);

        vm.prank(user);
        vm.expectRevert(bytes("address frozen"));
        vault.transfer(user2, 1e18);

        vm.prank(user);
        vm.expectRevert(bytes("address frozen"));
        vault.redeemToUsdt(1e18, 0, user);

        vm.prank(user);
        vm.expectRevert(bytes("address frozen"));
        vault.subscribeAndMint(1e18, 0, user);

        // yield keeps accruing to frozen shares
        oracle.setPrice(1.001e18);
        vault.accrue();

        vm.prank(treasury);
        vault.unfreezeAddress(user);
        vm.prank(user);
        vault.transfer(user2, 1e18); // works again, value grown
        assertTrue(_backed());
    }

    function test_cannot_freeze_vault_itself() public {
        vm.prank(treasury);
        vm.expectRevert(bytes("cannot freeze vault"));
        vault.freezeAddress(address(vault));
    }

    // ── Pause ────────────────────────────────────────────────────────

    function test_pause_blocks_mint_redeem_not_transfers() public {
        vm.prank(user);
        vault.subscribeAndMint(1000e18, 990e18, user);
        // treasury holds shares from before the pause (emergency scenario:
        // Safe acquired holders' shares to make them whole off-rail)
        usdy.mint(treasury, 10e18);
        vm.startPrank(treasury);
        usdy.approve(address(vault), type(uint256).max);
        uint256 shares = vault.depositAndMint(10e18, treasury);
        vault.pause();
        vm.stopPrank();

        vm.prank(user);
        vm.expectRevert();
        vault.subscribeAndMint(1e18, 0, user);
        vm.prank(user);
        vm.expectRevert();
        vault.redeemToUsdt(1e18, 0, user);

        // Owner EXITS are not pause-gated (like collectFees/sweep): pause
        // protects holders, and the emergency playbook is exactly
        // pause-the-users-then-treasury-liquidates. Owner MINTING during
        // pause has no such need — depositAndMint stays gated.
        vm.startPrank(treasury);
        vm.expectRevert();
        vault.depositAndMint(1e18, treasury);
        uint256 usdyOut = vault.redeem(shares);
        vm.stopPrank();
        assertApproxEqAbs(usdyOut, 10e18, 2, "treasury raw exit during pause");

        // soft transfer policy: plain transfers unaffected by pause
        vm.prank(user);
        vault.transfer(user2, 1e18);
    }

    // ── Upgradeability posture ───────────────────────────────────────

    function test_upgrade_then_lock_forever() public {
        BrickedVault impl2 = new BrickedVault(
            address(usdy), address(usdt), address(im), address(oracle), 1500
        );

        // non-owner cannot upgrade
        vm.prank(user);
        vm.expectRevert();
        vault.upgradeToAndCall(address(impl2), "");

        // owner can (maturation phase)
        vm.prank(treasury);
        vault.upgradeToAndCall(address(impl2), "");
        assertEq(BrickedVault(address(vault)).marker(), 42);

        // one-way lock
        vm.prank(treasury);
        vault.lockUpgrades();
        vm.prank(treasury);
        vm.expectRevert(bytes("upgrades locked forever"));
        vault.upgradeToAndCall(address(impl2), "");
    }

    // ── Sweep ────────────────────────────────────────────────────────

    function test_sweep_never_touches_backing() public {
        vm.prank(user);
        vault.subscribeAndMint(1000e18, 990e18, user);
        vm.prank(treasury);
        vm.expectRevert(bytes("backing is sacred"));
        vault.sweep(address(usdy), treasury, 1);

        MockToken stray = new MockToken("STRAY");
        stray.mint(address(vault), 5e18);
        vm.prank(treasury);
        vault.sweep(address(stray), treasury, 5e18);
        assertEq(stray.balanceOf(treasury), 5e18);
    }

    // ── Fuzz: the invariant under arbitrary op sequences ─────────────

    function testFuzz_backingInvariant(uint256 seed) public {
        uint256 state = seed;
        for (uint256 i = 0; i < 24; i++) {
            state = uint256(keccak256(abi.encode(state)));
            uint256 op = state % 5;
            uint256 amt = (state >> 8) % 50_000e18 + 1e18;

            if (op == 0) {
                vm.prank(user);
                try vault.subscribeAndMint(amt, 0, user) {} catch {}
            } else if (op == 1) {
                uint256 bal = vault.balanceOf(user);
                if (bal > 0) {
                    vm.prank(user);
                    try vault.redeemToUsdt((amt % bal) + 1 > bal ? bal : (amt % bal) + 1, 0, user) {} catch {}
                }
            } else if (op == 2) {
                // yield drips a few bps
                oracle.setPrice((oracle.price() * (10_000 + (state % 15))) / 10_000);
                vault.accrue();
            } else if (op == 3) {
                uint256 s = vault.surplusUsdy(oracle.price());
                if (s > 0) {
                    vm.prank(treasury);
                    try vault.collectFees(s) {} catch {}
                }
            } else {
                uint256 bal = vault.balanceOf(user);
                if (bal > 1e18) {
                    vm.prank(user);
                    try vault.redeemToUsdt(bal / 2, 0, user) {} catch {}
                }
            }
            assertGe(vault.backingRatioBps(), 10_000, "INVARIANT BROKEN");
        }
    }
}
