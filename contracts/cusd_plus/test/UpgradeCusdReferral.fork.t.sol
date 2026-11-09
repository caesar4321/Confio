// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {CusdVault} from "../CusdVault.sol";

/**
 * Rehearses the fee-referral upgrade against the live cUSD proxy, then the
 * Safe's two setup calls and one real commission on the fork. What only the
 * fork proves: the two appended slots leave live state untouched, and a
 * sponsored 7702 batch (arm + mintWithFee) pays the referrer from real USDT
 * backing without breaking 1:1.
 *
 * BSC_RPC_URL=<rpc> [CUSD_IMPL=<deployed candidate>] \
 *   forge test --match-contract UpgradeCusdReferral
 *
 * Skips without BSC_RPC_URL. Before the Safe upgrades, set CUSD_IMPL so this
 * tests the implementation actually being installed.
 */
contract UpgradeCusdReferralForkTest is Test {
    CusdVault constant CUSD = CusdVault(0x6101cC370635cF2c7f2725EaB010aC407A8d543F);
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    address constant SPONSOR = 0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D;
    // ConfioBatchDelegate (settings CUSD_PLUS_BATCH_DELEGATE_ADDRESS).
    address constant BATCH_DELEGATE = 0xC06BD197b34a587026615C6AEd21301F5E99bc00;

    function test_upgrade_preserves_state_and_pays_a_referral() public {
        string memory rpc = vm.envOr("BSC_RPC_URL", string(""));
        if (bytes(rpc).length == 0) {
            vm.skip(true);
            return;
        }
        vm.createSelectFork(rpc);

        // ── live state before ──────────────────────────────────────────
        uint256 supply = CUSD.totalSupply();
        uint256 feeBps = CUSD.feeBps();
        uint256 entryFees = CUSD.accruedEntryFees();
        uint256 exitFees = CUSD.accruedExitFees();
        address savings = CUSD.savingsVault();
        bool sponsored = CUSD.isSponsor(SPONSOR);
        address usdt = address(CUSD.USDT());
        bool backed = CUSD.isFullyBacked();
        bool paused = CUSD.paused();
        uint256 sponsorBalance = CUSD.balanceOf(SPONSOR);
        assertEq(CUSD.owner(), SAFE);

        // ── upgrade (the Safe's first call) ────────────────────────────
        address candidate = vm.envOr("CUSD_IMPL", address(0));
        CusdVault impl = candidate == address(0) ? new CusdVault(usdt) : CusdVault(candidate);
        assertEq(address(impl.USDT()), usdt);
        vm.prank(SAFE);
        CUSD.upgradeToAndCall(address(impl), "");

        assertEq(CUSD.totalSupply(), supply);
        assertEq(CUSD.feeBps(), feeBps);
        assertEq(CUSD.accruedEntryFees(), entryFees);
        assertEq(CUSD.accruedExitFees(), exitFees);
        assertEq(CUSD.savingsVault(), savings);
        assertEq(CUSD.isSponsor(SPONSOR), sponsored);
        assertEq(CUSD.isFullyBacked(), backed);
        assertEq(CUSD.paused(), paused);
        assertEq(CUSD.balanceOf(SPONSOR), sponsorBalance);
        assertEq(CUSD.owner(), SAFE);
        // New appended slots start empty: arming is off until the Safe sets them.
        assertEq(CUSD.referralShareCapBps(), 0);
        assertEq(CUSD.batchDelegate(), address(0));

        // ── the Safe's setup calls ─────────────────────────────────────
        vm.startPrank(SAFE);
        CUSD.setBatchDelegate(BATCH_DELEGATE);
        CUSD.setReferralShareCapBps(5_000);
        vm.stopPrank();
        assertEq(CUSD.batchDelegate(), BATCH_DELEGATE);
        assertEq(CUSD.referralShareCapBps(), 5_000);
        assertTrue(sponsored, "live sponsor must be registered");

        // ── one real commission: a delegated member mints 100 USDT ──────
        address member = makeAddr("member");
        address referrer = makeAddr("referrer");
        vm.etch(member, abi.encodePacked(hex"ef0100", BATCH_DELEGATE));
        deal(usdt, member, 100e18);
        vm.prank(member);
        IERC20(usdt).approve(address(CUSD), type(uint256).max);

        uint256 vaultUsdtBefore = IERC20(usdt).balanceOf(address(CUSD));
        uint256 supplyBefore = CUSD.totalSupply();
        uint256 entryBefore = CUSD.accruedEntryFees();
        vm.startPrank(member, SPONSOR); // msg.sender = member, tx.origin = sponsor
        CUSD.armReferral(referrer, 5_000);
        uint256 net = CUSD.mintWithFee(100e18, 0, member);
        vm.stopPrank();

        uint256 fee = CUSD.feeFor(100e18);
        assertEq(net, 100e18 - fee);
        assertEq(CUSD.balanceOf(referrer), fee / 2, "referrer gets half the fee as cUSD");
        assertEq(CUSD.accruedEntryFees() - entryBefore, fee - fee / 2, "Confio keeps the other half");
        assertEq(CUSD.totalSupply() - supplyBefore, net + fee / 2);
        assertEq(IERC20(usdt).balanceOf(address(CUSD)) - vaultUsdtBefore, 100e18);
        assertTrue(CUSD.isFullyBacked(), "1:1 backing holds");

        // ── an unsponsored or non-Confío caller cannot arm ─────────────
        vm.prank(member, member);
        vm.expectRevert("not sponsored");
        CUSD.armReferral(referrer, 5_000);
        vm.prank(address(this), SPONSOR);
        vm.expectRevert("not a Confio account");
        CUSD.armReferral(referrer, 5_000);
    }
}
