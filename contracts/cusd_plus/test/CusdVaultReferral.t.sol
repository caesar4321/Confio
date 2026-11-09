// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {CusdVault} from "../CusdVault.sol";
import {CusdMockUsdt, MockSavingsVault} from "./CusdVault.t.sol";

/// Fee referral: a sponsored transaction arms a referrer once; every fee
/// charged later in that transaction mints the armed share to the referrer.
/// Foundry runs a test function as one transaction, so an arm made earlier
/// in a test is still live for later calls in it (except where isolated).
contract CusdVaultReferralTest is Test {
    CusdMockUsdt usdt;
    CusdVault vault;

    address treasury = makeAddr("treasury");
    address sponsor = makeAddr("sponsor");
    address savings;
    address user = makeAddr("user");
    address referrer = makeAddr("referrer");
    address recipient = makeAddr("recipient");
    address delegate = makeAddr("batchDelegate");

    event ReferralPaid(
        address indexed referee, address indexed referrer, uint256 feeUsdt, uint256 shareCusd, uint256 shareBps
    );

    function setUp() public {
        savings = address(new MockSavingsVault());
        usdt = new CusdMockUsdt();
        CusdVault implementation = new CusdVault(address(usdt));
        vault = CusdVault(
            address(new ERC1967Proxy(address(implementation), abi.encodeCall(CusdVault.initialize, (treasury, 90))))
        );
        vm.startPrank(treasury);
        vault.setSponsor(sponsor, true);
        vault.setSavingsVault(savings);
        vault.setReferralShareCapBps(5_000);
        vault.setBatchDelegate(delegate);
        vm.stopPrank();
        // The member's EOA is a 7702 account delegated to ConfioBatchDelegate.
        vm.etch(user, abi.encodePacked(hex"ef0100", delegate));

        usdt.mint(user, 1_000_000e18);
        vm.prank(user);
        usdt.approve(address(vault), type(uint256).max);
    }

    function _arm(uint256 shareBps) internal {
        vm.prank(user, sponsor);
        vault.armReferral(referrer, shareBps);
    }

    function _accrued() internal view returns (uint256) {
        return vault.accruedEntryFees() + vault.accruedExitFees();
    }

    // ── payouts ─────────────────────────────────────────────────────────

    function test_mint_paysHalfTheFeeToArmedReferrer() public {
        _arm(5_000);
        vm.expectEmit(true, true, false, true, address(vault));
        emit ReferralPaid(user, referrer, 0.9e18, 0.45e18, 5_000);
        vm.prank(user, sponsor);
        uint256 net = vault.mintWithFee(100e18, 99.1e18, user);

        assertEq(net, 99.1e18, "user net unchanged");
        assertEq(vault.balanceOf(referrer), 0.45e18);
        assertEq(vault.accruedEntryFees(), 0.45e18);
        assertEq(usdt.balanceOf(address(vault)), vault.totalSupply() + _accrued());
        assertTrue(vault.isFullyBacked());
    }

    function test_redeem_paysReferrerInsideSponsoredTx() public {
        vm.prank(user, sponsor);
        uint256 minted = vault.mintWithFee(100e18, 0, user); // before arm: no payout
        assertEq(vault.balanceOf(referrer), 0);

        _arm(5_000);
        vm.prank(user, sponsor);
        vault.redeemWithFee(minted, 0, recipient);

        uint256 exitFee = vault.feeFor(minted);
        assertEq(vault.balanceOf(referrer), exitFee / 2);
        assertEq(vault.accruedExitFees(), exitFee - exitFee / 2);
        assertEq(usdt.balanceOf(address(vault)), vault.totalSupply() + _accrued());
        assertTrue(vault.isFullyBacked());
    }

    function test_everyFeeInTheTransactionPays() public {
        _arm(5_000);
        vm.prank(user, sponsor);
        uint256 minted = vault.mintWithFee(100e18, 0, user);
        vm.prank(user, sponsor);
        vault.redeemWithFee(minted, 0, user);

        uint256 total = 0.45e18 + vault.feeFor(minted) / 2;
        assertEq(vault.balanceOf(referrer), total);
        assertTrue(vault.isFullyBacked());
    }

    function test_savingsEntryAndExit_payReferrer() public {
        usdt.mint(savings, 200e18);
        vm.prank(savings);
        usdt.approve(address(vault), type(uint256).max);

        _arm(5_000);
        vm.prank(savings, sponsor);
        vault.settleSavingsEntry(100e18, 0);
        assertEq(vault.balanceOf(referrer), 0.45e18);

        vm.prank(savings, sponsor);
        vault.settleSavingsExit(100e18, 0, recipient);
        assertEq(vault.balanceOf(referrer), 0.9e18);
        assertEq(_accrued(), 0.9e18);
        assertEq(usdt.balanceOf(address(vault)), vault.totalSupply() + _accrued());
        assertTrue(vault.isFullyBacked());
    }

    function test_smallerShare_isHonoured() public {
        _arm(2_000);
        vm.prank(user, sponsor);
        vault.mintWithFee(100e18, 0, user);
        assertEq(vault.balanceOf(referrer), 0.18e18);
        assertEq(vault.accruedEntryFees(), 0.72e18);
    }

    function test_withoutArm_feeIsKeptWhole() public {
        vm.prank(user, sponsor);
        vault.mintWithFee(100e18, 0, user);
        assertEq(vault.balanceOf(referrer), 0);
        assertEq(vault.accruedEntryFees(), 0.9e18);
    }

    function test_unsponsoredExit_keepsWholeFeeEvenIfArmed() public {
        vm.prank(user, sponsor);
        uint256 minted = vault.mintWithFee(100e18, 0, user);
        _arm(5_000);
        // A self-built exit (tx.origin = user) never pays a referrer.
        vm.prank(user, user);
        vault.redeemWithFee(minted, 0, user);
        assertEq(vault.balanceOf(referrer), 0);
        assertEq(vault.accruedExitFees(), vault.feeFor(minted));
    }

    // ── never blocks the user ───────────────────────────────────────────

    function test_frozenReferrer_conversionSucceedsAndFeeIsKept() public {
        _arm(5_000);
        vm.prank(treasury);
        vault.freezeAddress(referrer);
        vm.prank(user, sponsor);
        uint256 net = vault.mintWithFee(100e18, 0, user);
        assertEq(net, 99.1e18);
        assertEq(vault.balanceOf(referrer), 0);
        assertEq(vault.accruedEntryFees(), 0.9e18);
    }

    function test_capLoweredBelowArm_feeIsKept() public {
        _arm(5_000);
        vm.prank(treasury);
        vault.setReferralShareCapBps(1_000);
        vm.prank(user, sponsor);
        vault.mintWithFee(100e18, 0, user);
        assertEq(vault.balanceOf(referrer), 0);
        assertEq(vault.accruedEntryFees(), 0.9e18);
    }

    function test_dustShareRoundsToZero_feeIsKept() public {
        _arm(5_000);
        vm.prank(user, sponsor);
        vault.mintWithFee(3, 0, user); // fee = 1 wei, half rounds to 0
        assertEq(vault.balanceOf(referrer), 0);
        assertEq(vault.accruedEntryFees(), 1);
    }

    // ── arming rules ────────────────────────────────────────────────────

    function test_arm_requiresSponsoredTransaction() public {
        vm.prank(user, user);
        vm.expectRevert("not sponsored");
        vault.armReferral(referrer, 5_000);
    }

    function test_arm_onlyFromAConfioAccount() public {
        // Any other code reached in a sponsored batch (a token hook, a router
        // target) cannot arm itself.
        address hook = address(new MockSavingsVault());
        vm.prank(hook, sponsor);
        vm.expectRevert("not a Confio account");
        vault.armReferral(referrer, 5_000);
        // An account delegated somewhere else is not a Confío account either.
        address other = makeAddr("other");
        vm.etch(other, abi.encodePacked(hex"ef0100", makeAddr("otherDelegate")));
        vm.prank(other, sponsor);
        vm.expectRevert("not a Confio account");
        vault.armReferral(referrer, 5_000);
        // With no delegate configured, nobody can arm.
        vm.prank(treasury);
        vault.setBatchDelegate(address(0));
        vm.prank(user, sponsor);
        vm.expectRevert("not a Confio account");
        vault.armReferral(referrer, 5_000);
    }

    function test_batchDelegate_isOwnerOnly() public {
        vm.prank(user);
        vm.expectRevert();
        vault.setBatchDelegate(address(1));
    }

    function test_arm_onlyOncePerTransaction() public {
        _arm(5_000);
        vm.prank(user, sponsor);
        vm.expectRevert("already armed");
        vault.armReferral(recipient, 5_000);
    }

    function test_arm_rejectsSelfZeroAndCoreAddresses() public {
        vm.startPrank(user, sponsor);
        vm.expectRevert("self referral");
        vault.armReferral(user, 5_000);
        vm.expectRevert("zero referrer");
        vault.armReferral(address(0), 5_000);
        vm.expectRevert("bad referrer");
        vault.armReferral(address(vault), 5_000);
        vm.expectRevert("bad referrer");
        vault.armReferral(savings, 5_000);
        vm.expectRevert("bad referrer");
        vault.armReferral(sponsor, 5_000);
        vm.stopPrank();
    }

    function test_arm_shareMustBePositiveAndAtMostHalf() public {
        vm.startPrank(user, sponsor);
        vm.expectRevert("bad share");
        vault.armReferral(referrer, 0);
        vm.expectRevert("bad share");
        vault.armReferral(referrer, 5_001);
        vm.stopPrank();
    }

    /// The Safe zeroing or lowering the cap must never revert members'
    /// batches that still carry the old share: the arm is a no-op.
    function test_armAboveLiveCap_isNoOpAndConversionSucceeds() public {
        vm.prank(treasury);
        vault.setReferralShareCapBps(0);
        _arm(5_000);
        (address r,,) = vault.armedReferral();
        assertEq(r, address(0));
        vm.prank(user, sponsor);
        uint256 net = vault.mintWithFee(100e18, 0, user);
        assertEq(net, 99.1e18);
        assertEq(vault.balanceOf(referrer), 0);
        assertEq(vault.accruedEntryFees(), 0.9e18);

        // A later in-cap arm in the same transaction still works.
        vm.prank(treasury);
        vault.setReferralShareCapBps(2_500);
        _arm(2_500);
        vm.prank(user, sponsor);
        vault.mintWithFee(100e18, 0, user);
        assertEq(vault.balanceOf(referrer), 0.225e18);
    }

    function test_arm_blockedWhilePaused() public {
        vm.prank(treasury);
        vault.pause();
        vm.prank(user, sponsor);
        vm.expectRevert();
        vault.armReferral(referrer, 5_000);
    }

    function test_armedReferral_reportsArm() public {
        _arm(4_000);
        (address r, address referee, uint256 bps) = vault.armedReferral();
        assertEq(r, referrer);
        assertEq(referee, user);
        assertEq(bps, 4_000);
    }

    function test_cap_isOwnerOnlyAndBounded() public {
        vm.prank(user);
        vm.expectRevert();
        vault.setReferralShareCapBps(1_000);
        vm.prank(treasury);
        vm.expectRevert("cap too high");
        vault.setReferralShareCapBps(5_001);
    }

    /// forge-config: default.isolate = true
    function test_armVanishesWhenTransactionEnds() public {
        _arm(5_000); // its own transaction under isolate
        (address r,,) = vault.armedReferral();
        assertEq(r, address(0));
        vm.prank(user, sponsor);
        vault.mintWithFee(100e18, 0, user);
        assertEq(vault.balanceOf(referrer), 0);
        assertEq(vault.accruedEntryFees(), 0.9e18);
    }

    function testFuzz_referralPreservesBacking(uint96 rawGross, uint16 rawShare) public {
        uint256 gross = bound(uint256(rawGross), 3, 1_000_000e18);
        uint256 share = bound(uint256(rawShare), 1, 5_000);
        _arm(share);
        vm.prank(user, sponsor);
        uint256 minted = vault.mintWithFee(gross, 0, user);
        uint256 entryFee = vault.feeFor(gross);
        assertEq(vault.balanceOf(referrer), entryFee * share / 10_000);
        if (vault.feeFor(minted) < minted) {
            vm.prank(user, sponsor);
            vault.redeemWithFee(minted, 0, recipient);
        }
        assertEq(usdt.balanceOf(address(vault)), vault.totalSupply() + _accrued());
        assertTrue(vault.isFullyBacked());
    }
}
