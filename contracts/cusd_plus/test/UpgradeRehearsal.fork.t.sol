// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * v4 UPGRADE REHEARSAL against the LIVE BSC proxy state (2026-07-20). Run:
 *
 *   forge test --match-path test/UpgradeRehearsal.fork.t.sol \
 *     --fork-url <bsc-rpc> -vv
 *
 * Rehearses exactly what the Safe will execute at nonce 2: deploy the v4
 * implementation, upgradeToAndCall on the REAL proxy (pranked as the Safe),
 * then assert state survival, removed surface, verdict gating, live-oracle
 * accrual, and that the USDT rail still stops at Ondo's PP gate.
 */
import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {CusdPlusVault} from "../CusdPlusVault.sol";

interface IOracleView {
    function getPrice() external view returns (uint256);
}

contract UpgradeRehearsalForkTest is Test {
    address constant PROXY = 0x3C29417eb4314155e63d4C7D4507852b87763Ed1;
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    address constant USDY = 0x608593d17A2decBbc4399e4185bE4922F97eD32E;
    address constant USDT = 0x55d398326f99059fF775485246999027B3197955;
    address constant IM = 0x9bA360087075A4Cef548eeD71Eed197bf4cFA4E2;
    address constant ORACLE = 0x8aaa843b848c2E3c83956Bc09aFBE4D9Dcf297b7;

    address user = makeAddr("user");

    function test_upgradeLiveProxyToV4() public {
        if (PROXY.code.length == 0) return; // skip cleanly without --fork-url
        CusdPlusVault v = CusdPlusVault(PROXY);

        // ── pre-state (v2 surface) ──────────────────────────────────────
        uint256 prePPlus = v.pPlus();
        uint256 preLast = v.lastOraclePrice();
        address preOwner = v.owner();
        assertEq(preOwner, SAFE, "owner is the Safe pre-upgrade");

        // ── the Safe's upgrade, exactly as nonce 2 will run it ──────────
        CusdPlusVault impl4 = new CusdPlusVault(USDY, USDT, IM, ORACLE, 1500);
        vm.prank(SAFE);
        v.upgradeToAndCall(address(impl4), "");

        // ── state survives byte-for-byte ────────────────────────────────
        assertEq(v.pPlus(), prePPlus, "pPlus intact");
        assertEq(v.lastOraclePrice(), preLast, "baseline intact");
        assertEq(v.owner(), preOwner, "owner intact");
        assertEq(v.totalSupply(), 0, "supply intact");
        assertEq(v.guardedOraclePrice(), 0, "new slot clean");
        assertFalse(v.oracleGuardTripped(), "guard clear");

        // ── removed surface is really gone ──────────────────────────────
        (bool ok, ) = PROXY.call(abi.encodeWithSignature("lockUpgrades()"));
        assertFalse(ok, "lockUpgrades removed");
        (ok, ) = PROXY.call(abi.encodeWithSignature("resetOracleBaseline()"));
        assertFalse(ok, "resetOracleBaseline removed");
        (ok, ) = PROXY.call(abi.encodeWithSignature("upgradesLocked()"));
        assertFalse(ok, "upgradesLocked getter removed");

        // ── verdicts exist and are gated ────────────────────────────────
        vm.prank(SAFE);
        vm.expectRevert(bytes("guard not tripped"));
        v.acceptVerifiedOracleGrowth(0, type(uint256).max, keccak256("e"));
        vm.prank(SAFE);
        vm.expectRevert(bytes("guard not tripped"));
        v.rebaselineAfterVerifiedOracleFault(0, type(uint256).max, keccak256("e"));

        // ── live-oracle accrue: real USDY growth since 07-10, 85/15 ─────
        uint256 p = IOracleView(ORACLE).getPrice();
        assertGt(p, preLast, "USDY accreted since deploy");
        v.accrue();
        assertEq(v.lastOraclePrice(), p, "baseline advanced to live read");
        assertGt(v.pPlus(), prePPlus, "holders credited 85% of real growth");
        assertFalse(v.oracleGuardTripped(), "sub-2% real growth, no trip");

        // ── raw USDY stays owner-only ───────────────────────────────────
        vm.prank(user);
        vm.expectRevert();
        v.redeem(1);

        // ── USDT rail reaches the REAL IM and stops at the PP gate ──────
        deal(USDT, user, 10e18);
        vm.startPrank(user);
        IERC20(USDT).approve(PROXY, 10e18);
        vm.expectRevert(); // Ondo UserNotRegistered() until PP whitelisting
        v.subscribeAndMint(10e18, 0, user);
        vm.stopPrank();
    }
}
