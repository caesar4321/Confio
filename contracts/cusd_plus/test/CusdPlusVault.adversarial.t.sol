// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * Adversarial cases (2026-07-06) — the classic vault exploits, shown to be
 * structurally inapplicable here, plus rounding-direction bounds.
 *
 * Key structural fact: pPlus is ORACLE-DRIVEN, never balance-derived. The
 * ERC4626 first-depositor / donation family of attacks all work by skewing
 * the assets-per-share ratio with direct transfers — here a donation cannot
 * move the share price at all; it lands in Confío's surplus.
 */
import {Test} from "forge-std/Test.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {CusdPlusVault} from "../CusdPlusVault.sol";
import {MockToken, MockOracle, MockInstantManager} from "./CusdPlusVault.t.sol";

contract CusdPlusVaultAdversarialTest is Test {
    MockToken usdt;
    MockToken usdy;
    MockOracle oracle;
    MockInstantManager im;
    CusdPlusVault vault;

    address treasury = makeAddr("treasury");
    address attacker = makeAddr("attacker");
    address victim = makeAddr("victim");

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
            address(impl), abi.encodeCall(CusdPlusVault.initialize, (treasury))
        );
        vault = CusdPlusVault(address(proxy));

        for (uint256 i = 0; i < 2; i++) {
            address a = i == 0 ? attacker : victim;
            vm.startPrank(a);
            usdt.approve(address(vault), type(uint256).max);
            usdy.approve(address(vault), type(uint256).max);
            vm.stopPrank();
        }
    }

    /// ERC4626-style inflation: tiny first deposit + huge donation is
    /// supposed to make the victim's shares round to ~zero value. Here the
    /// share price ignores balances entirely, so the victim is untouched
    /// and the "attack" gifts Confío the donation.
    function test_firstDepositorInflationIsStructurallyDead() public {
        usdy.mint(attacker, 1_000_000e18 + 1);

        vm.prank(attacker);
        vault.depositAndMint(1, attacker); // 1 wei first deposit
        vm.prank(attacker);
        usdy.transfer(address(vault), 1_000_000e18); // donation

        assertEq(vault.pPlus(), WAD, "donation must not move share price");

        usdt.mint(victim, 1_000e18);
        vm.prank(victim);
        uint256 victimShares = vault.subscribeAndMint(1_000e18, 0, victim);
        assertEq(victimShares, 1_000e18, "victim mints at fair price");

        // Victim exits whole — attacker gained nothing from them.
        vm.prank(victim);
        uint256 victimOut = vault.redeem(victimShares, victim);
        assertEq(victimOut, 1_000e18, "victim exits whole");

        // Attacker's own exit returns exactly the 1 wei entitlement.
        vm.prank(attacker);
        uint256 attackerOut = vault.redeem(1, attacker);
        assertEq(attackerOut, 1, "attacker gets 1 wei back");

        // The donation is Confío surplus, withdrawable by treasury only.
        uint256 surplus = vault.surplusUsdy(oracle.price());
        assertEq(surplus, 1_000_000e18, "donation became surplus");
        vm.prank(treasury);
        vault.collectFees(treasury, surplus);
        assertEq(usdy.balanceOf(treasury), 1_000_000e18);
    }

    /// Donations of the backing asset increase surplus 1:1, exactly.
    function test_usdyDonationBecomesSurplusExactly() public {
        usdt.mint(victim, 500e18);
        vm.prank(victim);
        vault.subscribeAndMint(500e18, 0, victim);

        uint256 before = vault.surplusUsdy(oracle.price());
        usdy.mint(address(vault), 777e18);
        assertEq(
            vault.surplusUsdy(oracle.price()) - before,
            777e18,
            "surplus grows by exactly the donation"
        );
        assertEq(vault.pPlus(), WAD, "pPlus untouched");
    }

    /// Rounding direction under redemption: floor may shave at most one
    /// USDY-wei of value versus the exact entitlement, never more, and
    /// never in the holder's favor.
    function test_redeemRoundingBoundedToOneWei() public {
        // Awkward numbers: prices/pPlus far from round WADs.
        oracle.setPrice(1.013370000000000001e18);
        vault.accrue();
        uint256 usdtIn = 333_333_333_333_333_333_337;
        usdt.mint(victim, usdtIn);
        vm.prank(victim);
        uint256 shares = vault.subscribeAndMint(usdtIn, 0, victim);

        oracle.setPrice(1.027272727272727273e18);
        vault.accrue();

        uint256 p = oracle.price();
        uint256 pPlus = vault.pPlus();
        vm.prank(victim);
        uint256 usdyOut = vault.redeem(shares, victim);

        // exact entitlement in USDY terms: shares * pPlus / p
        uint256 exactFloor = (shares * pPlus) / p;
        assertEq(usdyOut, exactFloor, "floor semantics");
        // and the floor loses less than one USDY-wei vs the rational value
        assertLe((shares * pPlus) - usdyOut * p, p, "at most 1 wei shaved");
    }

    /// Marathon: many users, many accruals, interleaved entries/exits, then
    /// EVERYONE leaves. The vault must pay every holder and stay solvent —
    /// the long-horizon rounding-dust question answered empirically.
    function test_marathonFullExitStaysSolvent() public {
        address[5] memory users;
        for (uint256 i = 0; i < 5; i++) {
            users[i] = makeAddr(string(abi.encodePacked("u", i)));
            vm.prank(users[i]);
            usdt.approve(address(vault), type(uint256).max);
        }

        uint256 seed = 20260706;
        for (uint256 round = 0; round < 60; round++) {
            seed = uint256(keccak256(abi.encode(seed)));
            address u = users[seed % 5];

            if (round % 3 == 0) {
                // yield drip 1..19 bps
                oracle.setPrice((oracle.price() * (10_000 + (seed % 19) + 1)) / 10_000);
                vault.accrue();
            }
            uint256 amt = (seed >> 16) % 10_000e18 + 1e18;
            usdt.mint(u, amt);
            vm.prank(u);
            vault.subscribeAndMint(amt, 0, u);

            if (round % 4 == 1) {
                address w = users[(seed >> 32) % 5];
                uint256 bal = vault.balanceOf(w);
                if (bal > 2) {
                    vm.prank(w);
                    vault.redeem(bal / 2, w);
                }
            }
            if (round % 10 == 5) {
                uint256 s = vault.surplusUsdy(oracle.price());
                if (s > 0) {
                    vm.prank(treasury);
                    vault.collectFees(treasury, s);
                }
            }
        }

        // Everyone out, in full, no excuses.
        uint256 p = oracle.price();
        for (uint256 i = 0; i < 5; i++) {
            uint256 bal = vault.balanceOf(users[i]);
            if (bal == 0 || (bal * vault.pPlus()) / p == 0) continue;
            vm.prank(users[i]);
            vault.redeem(bal, users[i]);
        }
        assertGe(vault.backingRatioBps(), 10_000, "solvent after full exit");
        assertLe(
            (vault.totalSupply() * vault.pPlus()) / p,
            5,
            "only sub-wei dust may remain"
        );
    }
}
