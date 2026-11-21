// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ConfioSmartAccount} from "../ConfioSmartAccount.sol";
import {IConfioSmartAccount} from "../interfaces/IConfioSmartAccount.sol";
import {IConfioSmartAccountFactory} from "../interfaces/IConfioSmartAccountFactory.sol";
import {SmartAccountBase} from "./Base.t.sol";
import {ConfioBatchDelegate} from "cusd-plus/ConfioBatchDelegate.sol";

/// Looks like a live, non-inherited account of `owner`, at an address the
/// factory never deployed.
contract FakeAccount {
    address public owner;
    bool public inherited;

    constructor(address owner_) {
        owner = owner_;
    }
}

/// Spec 10.2, "Inheritance": designation, claim, challenge window,
/// cancellation and cooldown, execution and the withdraw-only box (section 6).
contract ConfioSmartAccountInheritanceTest is SmartAccountBase {
    IConfioSmartAccount.Plan constant M = IConfioSmartAccount.Plan.Monthly;
    bytes4 immutable NOT_BENEFICIARY = ConfioSmartAccount.NotBeneficiary.selector;
    bytes4 immutable NOT_OWNER = ConfioSmartAccount.NotOwner.selector;
    bytes4 immutable BAD_STATE = ConfioSmartAccount.BadState.selector;

    event BeneficiaryNamed(address indexed pendingBeneficiary, uint64 challengeWindow, uint64 expiresAt);
    event BeneficiaryAccepted(address indexed beneficiary, uint64 challengeWindow);
    event DesignationWithdrawn(address indexed pendingBeneficiary);
    event BeneficiaryRemoved(address indexed beneficiary);
    event ClaimInitiated(address indexed beneficiary, uint64 executableAt);
    event ClaimCancelled(address indexed beneficiary, uint64 cooldownUntil);
    event ClaimExecuted(address indexed previousOwner, address indexed newOwner);

    function setUp() public override {
        super.setUp();
        _subscribedMonthly(500e18);
    }

    function _initiate(address who) internal {
        vm.prank(who, who);
        acct.initiateClaim();
    }

    function _execute(address who) internal {
        vm.prank(who, who);
        acct.executeClaim();
    }

    /// Keeps the subscription paid across long waits, as the relayer would.
    function _warpPaid(uint256 to) internal {
        while (acct.paidUntil() <= to) {
            vm.warp(acct.paidUntil());
            vm.prank(relayer, relayer);
            acct.collectFee();
        }
        vm.warp(to);
    }

    function _pendingClaim() internal {
        _withBeneficiary();
        _initiate(bob);
        assertEq(acct.claimStatus(), 1);
    }

    function _assertCancelledWithCooldown() internal view {
        assertEq(acct.claimStartedAt(), 0, "claim cancelled");
        assertEq(acct.claimExecutableAt(), 0);
        assertEq(acct.claimCooldownUntil(), block.timestamp + 30 days, "cooldown set");
        assertEq(acct.beneficiary(), bob, "beneficiary stays");
    }

    // ── designation (4.6, decision 26, I-18) ────────────────────────────

    function test_setBeneficiary_revertsWhileInheritanceDisabled() public {
        _asOwner();
        vm.expectRevert(ConfioSmartAccount.InheritanceOff.selector);
        acct.setBeneficiary(bob, 180 days);
    }

    function test_setBeneficiary_revertsForSelfZeroAccountAndDisallowedWindow() public {
        _enableInheritance();
        vm.startPrank(alice, relayer);
        vm.expectRevert(ConfioSmartAccount.BadBeneficiary.selector);
        acct.setBeneficiary(alice, 180 days);
        vm.expectRevert(ConfioSmartAccount.BadBeneficiary.selector);
        acct.setBeneficiary(address(0), 180 days);
        vm.expectRevert(ConfioSmartAccount.BadBeneficiary.selector);
        acct.setBeneficiary(address(acct), 180 days);
        vm.expectRevert(ConfioSmartAccount.BadWindow.selector);
        acct.setBeneficiary(bob, 91 days);
        vm.expectRevert(ConfioSmartAccount.BadWindow.selector);
        acct.setBeneficiary(bob, 0);
        vm.stopPrank();

        // The three allowed windows.
        _name(bob, 90 days);
        _name(bob, 365 days);
        _approveName(acct, bob, 180 days);
        vm.expectEmit(true, false, false, true, address(acct));
        emit BeneficiaryNamed(bob, 180 days, uint64(block.timestamp + 30 days));
        _asOwner();
        acct.setBeneficiary(bob, 180 days);
        assertEq(acct.pendingBeneficiary(), bob);
        assertEq(acct.pendingChallengeWindow(), 180 days);
        assertEq(acct.pendingBeneficiaryExpiresAt(), block.timestamp + 30 days);
        assertEq(acct.beneficiary(), address(0), "not a beneficiary until accepted");
    }

    /// The 90-day floor is the account's own: a factory that allows a
    /// shorter window (an upgrade) cannot shorten it.
    function test_setBeneficiary_windowFloorHoldsWhateverTheFactoryAllows() public {
        _enableInheritance();
        vm.mockCall(
            address(factory),
            abi.encodeCall(IConfioSmartAccountFactory.allowedChallengeWindows, (uint64(1 days))),
            abi.encode(true)
        );
        _asOwner();
        vm.expectRevert(ConfioSmartAccount.BadWindow.selector);
        acct.setBeneficiary(bob, 1 days);
    }

    function test_setBeneficiary_needsAnActiveSubscription() public {
        _enableInheritance();
        ConfioSmartAccount fresh = _create(carol);
        vm.prank(carol, relayer);
        vm.expectRevert(BAD_STATE);
        fresh.setBeneficiary(bob, 180 days);
    }

    /// I-18: without the relayer's live approval for exactly this step, the
    /// origin does not matter: relay-originated, self-sent or forwarded.
    function test_designationAndAcceptance_withoutApproval_revert() public {
        _enableInheritance();
        bytes4 notApproved = ConfioSmartAccount.NotApproved.selector;
        // Relay-originated, self-sent, or through another origin: no approval.
        address[3] memory origins = [relayer, alice, eve];
        for (uint256 i = 0; i < origins.length; ++i) {
            vm.prank(alice, origins[i]);
            vm.expectRevert(notApproved);
            acct.setBeneficiary(bob, 180 days);
        }
        // An approval for another window, another person or another account.
        _approveName(acct, bob, 365 days);
        _approveName(acct, carol, 180 days);
        _approveName(_create(carol), bob, 180 days);
        _asOwner();
        vm.expectRevert(notApproved);
        acct.setBeneficiary(bob, 180 days);
        // An approval that has run out (one hour).
        _approveName(acct, bob, 180 days);
        assertEq(
            factory.designationApprovedUntil(address(acct), keccak256(abi.encode(bob, uint64(180 days)))),
            block.timestamp + 1 hours
        );
        uint256 snap = vm.snapshotState();
        vm.warp(block.timestamp + 1 hours);
        _asOwner();
        vm.expectRevert(notApproved);
        acct.setBeneficiary(bob, 180 days);
        vm.revertToState(snap);
        // A live approval: the approval, not the origin, is the gate.
        vm.prank(alice, alice);
        acct.setBeneficiary(bob, 180 days);
        assertEq(acct.pendingBeneficiary(), bob);

        // Acceptance: the named address without an approval, relayed or not.
        vm.prank(bob, relayer);
        vm.expectRevert(notApproved);
        acct.acceptBeneficiary();
        // An acceptance approval for someone else does not help.
        _approveAccept(acct, carol);
        vm.prank(bob, bob);
        vm.expectRevert(notApproved);
        acct.acceptBeneficiary();
        // Someone else, even approved and relay-originated.
        _approveAccept(acct, eve);
        vm.prank(eve, relayer);
        vm.expectRevert(NOT_BENEFICIARY);
        acct.acceptBeneficiary();
        // Expired.
        _approveAccept(acct, bob);
        snap = vm.snapshotState();
        vm.warp(block.timestamp + 1 hours);
        vm.prank(bob, relayer);
        vm.expectRevert(notApproved);
        acct.acceptBeneficiary();
        vm.revertToState(snap);

        vm.expectEmit(true, false, false, true, address(acct));
        emit BeneficiaryAccepted(bob, 180 days);
        vm.prank(bob, bob);
        acct.acceptBeneficiary();
        assertEq(acct.beneficiary(), bob);
        assertEq(acct.challengeWindow(), 180 days);
        assertEq(acct.pendingBeneficiary(), address(0));
        assertEq(acct.pendingChallengeWindow(), 0);
        assertEq(acct.pendingBeneficiaryExpiresAt(), 0);
    }

    function test_pendingDesignation_lapsesAfterThirtyDays() public {
        _enableInheritance();
        _name(bob, 180 days);
        vm.warp(block.timestamp + 30 days - 1);
        uint256 snap = vm.snapshotState();
        _accept(bob);
        vm.revertToState(snap);

        vm.warp(block.timestamp + 1);
        _approveAccept(acct, bob);
        vm.prank(bob, relayer);
        vm.expectRevert(ConfioSmartAccount.DesignationExpired.selector);
        acct.acceptBeneficiary();
        // The owner names again.
        _name(bob, 180 days);
        _accept(bob);
        assertEq(acct.beneficiary(), bob);
    }

    function test_withdrawDesignation_clearsOnlyThePending_removeBeneficiaryClearsBoth() public {
        _withBeneficiary();
        _asOwner();
        vm.expectRevert(ConfioSmartAccount.NoDesignation.selector);
        acct.withdrawDesignation();

        _name(carol, 365 days);
        vm.expectEmit(true, false, false, false, address(acct));
        emit DesignationWithdrawn(carol);
        _asOwner();
        acct.withdrawDesignation();
        assertEq(acct.pendingBeneficiary(), address(0));
        assertEq(acct.pendingChallengeWindow(), 0);
        assertEq(acct.pendingBeneficiaryExpiresAt(), 0);
        assertEq(acct.beneficiary(), bob, "the accepted beneficiary is untouched");
        assertEq(acct.challengeWindow(), 90 days);
        vm.prank(carol, relayer);
        vm.expectRevert(NOT_BENEFICIARY);
        acct.acceptBeneficiary();
        // Bob can still claim.
        _initiate(bob);
        assertEq(acct.claimStatus(), 1);

        _name(carol, 365 days);
        vm.expectEmit(true, false, false, false, address(acct));
        emit BeneficiaryRemoved(bob);
        vm.prank(alice, alice); // no sponsor gate
        acct.removeBeneficiary();
        assertEq(acct.beneficiary(), address(0));
        assertEq(acct.pendingBeneficiary(), address(0));
        assertEq(acct.challengeWindow(), 0);
        assertEq(acct.claimCooldownUntil(), 0);
        vm.prank(bob, bob);
        vm.expectRevert(NOT_BENEFICIARY);
        acct.initiateClaim();
    }

    // ── who may claim (I-8, I-10, I-16, I-19) ───────────────────────────

    function test_namedButNotAccepted_cannotClaim_previousKeepsStandingUntilAcceptance() public {
        _withBeneficiary();
        _name(carol, 180 days);

        // Carol is named, not accepted: no standing.
        vm.prank(carol, carol);
        vm.expectRevert(NOT_BENEFICIARY);
        acct.initiateClaim();
        vm.prank(carol, carol);
        vm.expectRevert(NOT_BENEFICIARY);
        acct.executeClaim();
        // Bob keeps his.
        assertEq(acct.beneficiary(), bob);
        uint256 snap = vm.snapshotState();
        _initiate(bob);
        vm.revertToState(snap);

        // Carol accepts: she can claim, Bob loses standing at that moment.
        _accept(carol);
        assertEq(acct.beneficiary(), carol);
        assertEq(acct.challengeWindow(), 180 days);
        vm.prank(bob, bob);
        vm.expectRevert(NOT_BENEFICIARY);
        acct.initiateClaim();
        _initiate(carol);
        assertEq(acct.claimExecutableAt(), block.timestamp + 180 days);
    }

    function test_onlyTheBeneficiaryCanInitiateAndExecute() public {
        _withBeneficiary();
        address[5] memory others = [alice, relayer, safe, eve, address(factory)];
        for (uint256 i = 0; i < others.length; ++i) {
            vm.prank(others[i], others[i]);
            vm.expectRevert(NOT_BENEFICIARY);
            acct.initiateClaim();
        }
        vm.expectEmit(true, false, false, true, address(acct));
        emit ClaimInitiated(bob, uint64(block.timestamp + 90 days));
        _initiate(bob);
        vm.prank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.ClaimAlreadyPending.selector);
        acct.initiateClaim();

        _warpPaid(block.timestamp + 90 days);
        for (uint256 i = 0; i < others.length; ++i) {
            if (others[i] == alice) continue; // an owner call would cancel the claim
            vm.prank(others[i], others[i]);
            vm.expectRevert(NOT_BENEFICIARY);
            acct.executeClaim();
        }
        vm.prank(alice, alice);
        vm.expectRevert(NOT_BENEFICIARY);
        acct.executeClaim();
        _execute(bob);
        assertEq(acct.owner(), bob);
    }

    function test_noBeneficiary_zeroAddressCannotClaim() public {
        vm.prank(address(0), address(0));
        vm.expectRevert(NOT_BENEFICIARY);
        acct.initiateClaim();
        vm.prank(address(0), address(0));
        vm.expectRevert(NOT_BENEFICIARY);
        acct.executeClaim();
    }

    function test_executeClaim_oneSecondBeforeTheWindowEnds_reverts_atTheEndSucceeds() public {
        _pendingClaim();
        uint256 at = acct.claimExecutableAt();
        _warpPaid(at - 1);
        vm.prank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.TooEarly.selector);
        acct.executeClaim();
        vm.warp(at);
        assertEq(acct.claimStatus(), 2, "Executable");
        vm.expectEmit(true, true, false, false, address(acct));
        emit ClaimExecuted(alice, bob);
        _execute(bob);
        assertEq(acct.owner(), bob);
    }

    function test_executeClaim_withoutAClaim_reverts() public {
        _withBeneficiary();
        vm.warp(block.timestamp + 20 days);
        vm.prank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.TooEarly.selector);
        acct.executeClaim();
    }

    // ── execution time is fixed at initiation (I-10) ────────────────────

    function test_claimExecutionTime_isFixed_reNamingSamePersonShorterDoesNotBringItForward() public {
        _enableInheritance();
        _name(bob, 365 days);
        _accept(bob);
        // The owner re-names Bob with a shorter window; not yet accepted.
        _name(bob, 90 days);
        _initiate(bob);
        uint64 executableAt = acct.claimExecutableAt();
        assertEq(executableAt, block.timestamp + 365 days, "the window as it stood at initiation");

        _accept(bob);
        assertEq(acct.challengeWindow(), 90 days, "applies to later claims only");
        assertEq(acct.claimExecutableAt(), executableAt, "execution not brought forward");
        assertEq(acct.claimStartedAt() != 0, true, "the same person's claim stays pending");

        _warpPaid(block.timestamp + 91 days);
        vm.prank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.TooEarly.selector);
        acct.executeClaim();
        _warpPaid(executableAt);
        _execute(bob);
    }

    function test_differentPersonAccepting_endsTheOldBeneficiarysClaim() public {
        _withBeneficiary();
        _name(carol, 180 days);
        // Bob claims after the naming.
        _initiate(bob);
        _approveAccept(acct, carol);
        vm.expectEmit(true, false, false, true, address(acct));
        emit ClaimCancelled(bob, 0);
        vm.prank(carol, relayer);
        acct.acceptBeneficiary();
        assertEq(acct.claimStartedAt(), 0);
        assertEq(acct.claimExecutableAt(), 0);
        assertEq(acct.claimCooldownUntil(), 0, "the new beneficiary starts without a cooldown");
        assertEq(acct.beneficiary(), carol);
        vm.warp(block.timestamp + 90 days);
        vm.prank(bob, bob);
        vm.expectRevert(NOT_BENEFICIARY);
        acct.executeClaim();
    }

    /// 6.4, I-11: re-designation can never shorten a cooldown.
    function test_reNamingCurrentBeneficiaryDuringTheirClaim_cancelsWithCooldown_acceptanceKeepsIt() public {
        _pendingClaim();
        _approveName(acct, bob, 180 days);
        vm.expectEmit(true, false, false, true, address(acct));
        emit ClaimCancelled(bob, uint64(block.timestamp + 30 days));
        _asOwner();
        acct.setBeneficiary(bob, 180 days);
        _assertCancelledWithCooldown();
        uint64 cooldown = acct.claimCooldownUntil();

        _accept(bob);
        assertEq(acct.claimCooldownUntil(), cooldown, "kept");
        assertEq(acct.challengeWindow(), 180 days);
        vm.prank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.Cooldown.selector);
        acct.initiateClaim();
        vm.warp(cooldown);
        _initiate(bob);
        assertEq(acct.claimExecutableAt(), block.timestamp + 180 days);
    }

    function test_namingSomeoneNewDuringAClaim_cancelsWithCooldown_oldKeepsStandingUntilAcceptance() public {
        _pendingClaim();
        _name(carol, 180 days);
        _assertCancelledWithCooldown();
        // Bob keeps standing: after the cooldown he can claim again.
        vm.warp(block.timestamp + 30 days - 1);
        vm.prank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.Cooldown.selector);
        acct.initiateClaim();
        // Carol accepts inside her 30 days: Bob loses standing then.
        _accept(carol);
        vm.warp(block.timestamp + 1);
        vm.prank(bob, bob);
        vm.expectRevert(NOT_BENEFICIARY);
        acct.initiateClaim();
    }

    function test_removeBeneficiary_duringAPendingClaim() public {
        _pendingClaim();
        vm.expectEmit(true, false, false, true, address(acct));
        emit ClaimCancelled(bob, 0);
        vm.prank(alice, alice);
        acct.removeBeneficiary();
        assertEq(acct.claimStartedAt(), 0);
        assertEq(acct.claimCooldownUntil(), 0, "the cooldown goes with the designation");
        assertEq(acct.beneficiary(), address(0));
        vm.warp(block.timestamp + 90 days);
        vm.prank(bob, bob);
        vm.expectRevert(NOT_BENEFICIARY);
        acct.executeClaim();
    }

    // ── claim versus cancel ordering (I-9, I-13) ────────────────────────

    function test_ordering_ownerFirst_theExecutionReverts() public {
        _pendingClaim();
        _warpPaid(acct.claimExecutableAt());
        // Same block: the owner's transaction lands first.
        vm.prank(alice, alice);
        acct.withdraw(address(cusd), 0);
        vm.prank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.TooEarly.selector);
        acct.executeClaim();
        assertEq(acct.owner(), alice);
    }

    function test_ordering_executionFirst_theOldOwnersTransactionRevertsAndChangesNothing() public {
        _pendingClaim();
        _warpPaid(acct.claimExecutableAt());
        uint256 balance = cusd.balanceOf(address(acct));
        _execute(bob);
        vm.prank(alice, alice);
        vm.expectRevert(NOT_OWNER);
        acct.withdraw(address(cusd), 1e18);
        vm.prank(alice, alice);
        vm.expectRevert(NOT_OWNER);
        acct.cancelClaim();
        assertEq(acct.owner(), bob);
        assertEq(cusd.balanceOf(address(acct)), balance);
        assertEq(cusd.balanceOf(alice), 0);
    }

    // ── every owner function cancels a pending claim (I-9) ──────────────

    function test_touch_withdrawOfAZeroValueToken() public {
        _pendingClaim();
        vm.expectEmit(true, false, false, true, address(acct));
        emit ClaimCancelled(bob, uint64(block.timestamp + 30 days));
        vm.prank(alice, alice);
        acct.withdraw(address(tsla), 0);
        _assertCancelledWithCooldown();
    }

    function test_touch_withdrawAll() public {
        _pendingClaim();
        vm.prank(alice, alice);
        acct.withdrawAll(new address[](0));
        _assertCancelledWithCooldown();
    }

    /// cancelClaim appended to an unrelated batch: here, alone.
    function test_touch_cancelClaim_andNoOpWithoutAClaim() public {
        // A no-op success with nothing pending: appendable to any batch.
        vm.prank(alice, alice);
        acct.cancelClaim();
        assertEq(acct.claimCooldownUntil(), 0);
        _pendingClaim();
        vm.prank(alice, alice);
        acct.cancelClaim();
        _assertCancelledWithCooldown();
    }

    function test_touch_changePlan() public {
        _pendingClaim();
        _asOwner();
        acct.changePlan(IConfioSmartAccount.Plan.Annual);
        _assertCancelledWithCooldown();
    }

    function test_touch_cancelSubscription_andUndoCancel() public {
        _pendingClaim();
        _asOwner();
        acct.cancelSubscription();
        _assertCancelledWithCooldown();
        vm.warp(block.timestamp + 30 days - 1);
        // CancelPending is still Active for a claim.
        vm.prank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.Cooldown.selector);
        acct.initiateClaim();
        _asOwner();
        acct.undoCancel();
        vm.warp(block.timestamp + 1);
        _asRelayer();
        acct.collectFee();
        _initiate(bob);
        _asOwner();
        acct.cancelSubscription();
        _assertCancelledWithCooldown();
        _asOwner();
        acct.undoCancel();
    }

    /// A claim started while CancelPending (it is still Active) is ended by
    /// undoCancel, an owner call like any other.
    function test_touch_undoCancel_endsAClaimStartedAfterTheCancellation() public {
        _withBeneficiary();
        _asOwner();
        acct.cancelSubscription();
        assertEq(acct.status(), 2, "CancelPending");
        assertEq(acct.claimCooldownUntil(), 0, "nothing was pending to cancel");
        _initiate(bob);
        assertEq(acct.claimStatus(), 1);
        vm.expectEmit(true, false, false, true, address(acct));
        emit ClaimCancelled(bob, uint64(block.timestamp + 30 days));
        _asOwner();
        acct.undoCancel();
        _assertCancelledWithCooldown();
        assertFalse(acct.cancelRequested());
    }

    function test_touch_subscribe_afterExpiry() public {
        _withBeneficiary();
        _asOwner();
        acct.cancelSubscription();
        _initiate(bob);
        vm.warp(acct.paidUntil());
        assertEq(acct.status(), 3);
        _subscribe(M);
        _assertCancelledWithCooldown();
    }

    function test_touch_trade() public {
        _pendingClaim();
        bytes memory data = _swapBuyData(CUSD_, address(btcb), 10e18);
        _asOwner();
        acct.trade(address(swapRouter), data, address(cusd), address(btcb), 10e18, 1);
        _assertCancelledWithCooldown();
    }

    function test_touch_createUpdateCancelRule() public {
        _pendingClaim();
        IConfioSmartAccount.RuleInput memory r = _rule(IConfioSmartAccount.RuleKind.Send, address(cusd), 1e18);
        r.payee = carol;
        _asOwner();
        uint256 id = acct.createRule(r);
        _assertCancelledWithCooldown();

        vm.warp(block.timestamp + 30 days);
        _asRelayer();
        acct.collectFee();
        _initiate(bob);
        _asOwner();
        acct.updateRule(id, r);
        _assertCancelledWithCooldown();

        vm.warp(block.timestamp + 30 days);
        _asRelayer();
        acct.collectFee();
        _initiate(bob);
        _asOwner();
        acct.cancelRule(id);
        _assertCancelledWithCooldown();
    }

    function test_touch_setBeneficiary_andWithdrawDesignation() public {
        _pendingClaim();
        _name(carol, 180 days);
        _assertCancelledWithCooldown();
        vm.warp(block.timestamp + 30 days);
        _asRelayer();
        acct.collectFee();
        _initiate(bob);
        _asOwner();
        acct.withdrawDesignation();
        _assertCancelledWithCooldown();
    }

    /// A reverting owner call cancels nothing: the whole call is undone.
    function test_touch_aRevertingOwnerCallDoesNotCancel() public {
        _pendingClaim();
        uint64 started = acct.claimStartedAt();
        vm.prank(alice, alice);
        vm.expectRevert();
        acct.withdraw(address(cusd), 1_000_000e18);
        assertEq(acct.claimStartedAt(), started);
    }

    // ── relayer and permissionless functions do not (I-8, 6.4) ──────────

    function test_feeDeductionDoesNotCancelAClaim_andEverythingRunsWhileItIsPending() public {
        _withBeneficiary();
        IConfioSmartAccount.RuleInput memory r = _rule(IConfioSmartAccount.RuleKind.Send, address(cusd), 1e18);
        r.payee = carol;
        _asOwner();
        uint256 id = acct.createRule(r);
        uint256 most = cusd.balanceOf(address(acct)) - 1e18;
        _asOwner();
        acct.withdraw(address(cusd), most);
        btcb.mint(address(acct), 1e18);
        usdt.mint(address(acct), 1e18);

        _initiate(bob);
        uint64 started = acct.claimStartedAt();
        uint64 executableAt = acct.claimExecutableAt();

        // executeRule and convertUsdt.
        _asRelayer();
        acct.executeRule(id, abi.encode(CUSD_, uint256(1)), address(0), 0);
        _asRelayer();
        acct.convertUsdt(CUSD_, 0.99e18, address(0), 0);
        // startPaymentNotice and forcedSale (which collects the fee).
        _toSaleAllowed();
        uint256 shortfall = MONTHLY - acct.dollarsUsd();
        _sale(_legs(_cryptoLeg(btcb, BTC_PRICE, CUSD_, shortfall + 0.01e18)), 0, address(0), 0);
        // collectFee.
        _giveCusd(address(acct), 20e18);
        vm.warp(acct.paidUntil());
        _asRelayer();
        acct.collectFee();
        // latchConfioSale (permissionless) cannot run here; a failed attempt
        // changes nothing either.
        vm.expectRevert(ConfioSmartAccount.ConfioSaleUnset.selector);
        acct.latchConfioSale();

        assertEq(acct.claimStartedAt(), started, "claimStartedAt unchanged");
        assertEq(acct.claimExecutableAt(), executableAt);
        assertEq(acct.claimCooldownUntil(), 0);
        assertEq(acct.beneficiary(), bob);
    }

    /// C6: a claim pending when a signed cancellation expires. The return
    /// wins and the claim cannot execute; returnAsset does not touch it.
    function test_claimPendingWhenCancellationExpires_returnWorks_claimCannotExecute() public {
        _withBeneficiary();
        _asOwner();
        acct.cancelSubscription();
        _initiate(bob);
        uint64 started = acct.claimStartedAt();
        uint256 balance = cusd.balanceOf(address(acct));

        vm.warp(acct.claimExecutableAt());
        assertEq(acct.status(), 3, "Expired long before the window ends");
        vm.prank(eve);
        acct.returnAsset(address(cusd));
        assertEq(cusd.balanceOf(alice), balance);
        assertEq(acct.claimStartedAt(), started, "returnAsset does not change claim state");

        vm.prank(bob, bob);
        vm.expectRevert(BAD_STATE);
        acct.executeClaim();
        assertEq(acct.owner(), alice);
        // Nor can a new claim start on an Expired account.
        vm.prank(alice, alice);
        acct.cancelClaim();
        vm.warp(block.timestamp + 30 days);
        vm.prank(bob, bob);
        vm.expectRevert(BAD_STATE);
        acct.initiateClaim();
    }

    // ── repeated claims (I-11) ──────────────────────────────────────────

    function test_repeatedClaims_cooldownEachTime_noAssetMoves_windowNeverShortens() public {
        _withBeneficiary();
        btcb.mint(address(acct), 1e18);
        for (uint256 i = 0; i < 6; ++i) {
            uint256 cusdBefore = cusd.balanceOf(address(acct));
            _initiate(bob);
            assertEq(acct.claimExecutableAt(), block.timestamp + 90 days, "a full window every time");
            _warpPaid(block.timestamp + 89 days);
            cusdBefore = cusd.balanceOf(address(acct));
            vm.prank(alice, alice);
            acct.cancelClaim();
            assertEq(acct.claimCooldownUntil(), block.timestamp + 30 days);

            // Immediate re-claim reverts during the cooldown.
            vm.prank(bob, bob);
            vm.expectRevert(ConfioSmartAccount.Cooldown.selector);
            acct.initiateClaim();
            _warpPaid(block.timestamp + 30 days - 1);
            vm.prank(bob, bob);
            vm.expectRevert(ConfioSmartAccount.Cooldown.selector);
            acct.initiateClaim();
            _warpPaid(block.timestamp + 1);
            assertEq(btcb.balanceOf(address(acct)), 1e18, "no asset moved");
            assertEq(btcb.balanceOf(bob) + cusd.balanceOf(bob) + cusd.balanceOf(alice), 0);
            assertEq(acct.owner(), alice);
        }
    }

    // ── CancelPending and Expired (C6) ──────────────────────────────────

    /// Annual, so the paid period outlives a 90-day window.
    function _annual() internal {
        _asOwner();
        acct.changePlan(IConfioSmartAccount.Plan.Annual);
        vm.warp(acct.paidUntil());
        _asRelayer();
        acct.collectFee();
        assertEq(uint8(acct.plan()), 2);
    }

    /// CancelPending is Active until paidUntil: a claim started after the
    /// cancellation can execute before the period ends.
    function test_executeClaim_inCancelPending_beforePaidUntil() public {
        _annual();
        _withBeneficiary();
        _asOwner();
        acct.cancelSubscription();
        _initiate(bob);
        vm.warp(acct.claimExecutableAt());
        assertLt(block.timestamp, acct.paidUntil());
        assertEq(acct.status(), 2, "still CancelPending");
        _execute(bob);
        assertEq(acct.owner(), bob);
        assertTrue(acct.inherited());
        assertFalse(acct.cancelRequested(), "the cancellation is cleared with the rest");
        assertEq(acct.paidUntil(), 0);
        // Nothing returns to the old owner afterwards.
        vm.warp(block.timestamp + 400 days);
        vm.expectRevert(ConfioSmartAccount.IsInherited.selector);
        acct.returnAsset(address(cusd));
    }

    function test_differentPersonAccepting_inCancelPending_endsTheOldClaim() public {
        _withBeneficiary();
        _name(carol, 180 days);
        _asOwner();
        acct.cancelSubscription();
        _initiate(bob);
        assertEq(acct.status(), 2);
        _accept(carol);
        assertEq(acct.beneficiary(), carol);
        assertEq(acct.challengeWindow(), 180 days);
        assertEq(acct.claimStartedAt(), 0, "bob's claim ended");
        assertEq(acct.claimCooldownUntil(), 0);
        _initiate(carol);
        assertEq(acct.claimExecutableAt(), block.timestamp + 180 days);
    }

    function test_acceptBeneficiary_onAnExpiredAccount_reverts() public {
        _enableInheritance();
        vm.warp(block.timestamp + 5 days);
        _name(bob, 180 days);
        _asOwner();
        acct.cancelSubscription();
        vm.warp(acct.paidUntil());
        assertEq(acct.status(), 3, "Expired");
        assertLt(block.timestamp, acct.pendingBeneficiaryExpiresAt(), "the naming itself is still live");
        _approveAccept(acct, bob);
        vm.prank(bob, relayer);
        vm.expectRevert(BAD_STATE);
        acct.acceptBeneficiary();
        assertEq(acct.beneficiary(), address(0));
    }

    // ── challenge window bounds (audit P3) ──────────────────────────────

    function test_setBeneficiary_windowCeiling_holdsWhateverTheFactoryAllows() public {
        _enableInheritance();
        uint64 max = acct.MAX_CHALLENGE_WINDOW();
        assertEq(max, 1825 days);
        uint64[2] memory tooLong = [max + 1, type(uint64).max];
        for (uint256 i = 0; i < tooLong.length; ++i) {
            vm.mockCall(
                address(factory),
                abi.encodeCall(IConfioSmartAccountFactory.allowedChallengeWindows, (tooLong[i])),
                abi.encode(true)
            );
            _approveName(acct, bob, tooLong[i]);
            _asOwner();
            vm.expectRevert(ConfioSmartAccount.BadWindow.selector);
            acct.setBeneficiary(bob, tooLong[i]);
        }
        vm.clearMockedCalls();

        // The factory refuses above the ceiling and allows it exactly.
        vm.startPrank(safe);
        vm.expectRevert(bytes("window too long"));
        factory.setChallengeWindow(max + 1, true);
        factory.setChallengeWindow(max + 1, false); // disallowing is always fine
        factory.setChallengeWindow(max, true);
        vm.stopPrank();
        _name(bob, max);
        _accept(bob);
        _initiate(bob);
        assertEq(acct.claimExecutableAt(), block.timestamp + max, "no overflow at the ceiling");
    }

    // ── through the real ConfioBatchDelegate (7702, decision 9) ─────────

    function _delegatedAlice() internal returns (uint256 key) {
        (, key) = makeAddrAndKey("alice");
        // A 7702 delegation, modelled as in cusd_plus's delegate tests: the
        // delegate's runtime code runs AT alice's address.
        vm.etch(alice, address(new ConfioBatchDelegate()).code);
    }

    function _batch(uint256 key, ConfioBatchDelegate.Call[] memory calls)
        internal
        view
        returns (uint256 nonce, uint256 deadline, bytes memory sig)
    {
        nonce = ConfioBatchDelegate(payable(alice)).nonces();
        deadline = block.timestamp + 1 hours;
        bytes32 digest = ConfioBatchDelegate(payable(alice)).hashExecute(calls, nonce, deadline, bytes32(0));
        (uint8 v, bytes32 r, bytes32 s_) = vm.sign(key, digest);
        sig = abi.encodePacked(r, s_, v);
    }

    function _relay(uint256 key, ConfioBatchDelegate.Call[] memory calls) internal {
        (uint256 nonce, uint256 deadline, bytes memory sig) = _batch(key, calls);
        vm.prank(relayer, relayer);
        ConfioBatchDelegate(payable(alice)).execute(calls, nonce, deadline, bytes32(0), sig);
    }

    /// 6.4: the relay appends cancelClaim to an unrelated batch the owner
    /// signs. Through the real delegate msg.sender is the owner's EOA.
    function test_batchDelegate_unrelatedCallPlusCancelClaim_endsTheClaim() public {
        uint256 key = _delegatedAlice();
        _pendingClaim();
        _giveCusd(alice, 5e18);
        ConfioBatchDelegate.Call[] memory calls = new ConfioBatchDelegate.Call[](2);
        calls[0] = ConfioBatchDelegate.Call(address(cusd), 0, abi.encodeCall(cusd.transfer, (carol, 5e18)));
        calls[1] = ConfioBatchDelegate.Call(address(acct), 0, abi.encodeCall(acct.cancelClaim, ()));
        vm.expectEmit(true, false, false, true, address(acct));
        emit ClaimCancelled(bob, uint64(block.timestamp + 30 days));
        _relay(key, calls);
        assertEq(cusd.balanceOf(carol), 5e18, "the unrelated call ran");
        _assertCancelledWithCooldown();
    }

    /// I-18 through the delegate: neither a relayed batch nor the owner's own
    /// self-call (the forwarding path the audit found) designates without a
    /// live approval for exactly that designation.
    function test_batchDelegate_setBeneficiary_needsALiveApproval() public {
        uint256 key = _delegatedAlice();
        _enableInheritance();
        ConfioBatchDelegate.Call[] memory calls = new ConfioBatchDelegate.Call[](1);
        calls[0] = ConfioBatchDelegate.Call(address(acct), 0, abi.encodeCall(acct.setBeneficiary, (carol, 180 days)));

        // Relayed, with no approval.
        (uint256 nonce, uint256 deadline, bytes memory sig) = _batch(key, calls);
        vm.prank(relayer, relayer);
        vm.expectRevert(ConfioSmartAccount.NotApproved.selector);
        ConfioBatchDelegate(payable(alice)).execute(calls, nonce, deadline, bytes32(0), sig);
        // Self-sent by alice's key inside a sponsored transaction's call
        // chain (tx.origin a sponsor): still no approval, still refused.
        vm.prank(alice, relayer);
        vm.expectRevert(ConfioSmartAccount.NotApproved.selector);
        ConfioBatchDelegate(payable(alice)).execute(calls, 0, 0, bytes32(0), "");
        // An approval for another window does not count.
        _approveName(acct, carol, 365 days);
        vm.prank(relayer, relayer);
        vm.expectRevert(ConfioSmartAccount.NotApproved.selector);
        ConfioBatchDelegate(payable(alice)).execute(calls, nonce, deadline, bytes32(0), sig);

        // The relay checks, approves, relays: it works.
        _approveName(acct, carol, 180 days);
        _relay(key, calls);
        assertEq(acct.pendingBeneficiary(), carol);
        assertEq(acct.pendingChallengeWindow(), 180 days);
    }

    // ── cooldown clamp (I-9, I-20) ──────────────────────────────────────

    function _cancelAndReadCooldown() internal returns (uint256) {
        vm.prank(alice, alice);
        acct.cancelClaim();
        return acct.claimCooldownUntil() - block.timestamp;
    }

    function test_cooldown_followsTheFactoryInsideItsBounds() public {
        _pendingClaim();
        vm.prank(safe);
        factory.setClaimCooldown(45 days);
        assertEq(_cancelAndReadCooldown(), 45 days);
    }

    function test_cooldown_factoryReturningZero_isRaisedToOneDay() public {
        _pendingClaim();
        vm.mockCall(
            address(factory), abi.encodeCall(IConfioSmartAccountFactory.claimCooldown, ()), abi.encode(uint64(0))
        );
        assertEq(_cancelAndReadCooldown(), 1 days, "the cooldown cannot be removed");
    }

    function test_cooldown_factoryReturningAHugeValue_isCappedAtNinetyDays() public {
        _pendingClaim();
        vm.mockCall(
            address(factory),
            abi.encodeCall(IConfioSmartAccountFactory.claimCooldown, ()),
            abi.encode(type(uint256).max)
        );
        assertEq(_cancelAndReadCooldown(), 90 days, "the owner call does not revert or lock the beneficiary out");
    }

    function test_cooldown_revertingFactory_fallsBackToThirtyDays() public {
        _pendingClaim();
        vm.mockCallRevert(address(factory), abi.encodeCall(IConfioSmartAccountFactory.claimCooldown, ()), "boom");
        assertEq(_cancelAndReadCooldown(), 30 days);
    }

    function test_cooldown_factoryWithoutCode_orShortAnswer_fallsBack() public {
        _pendingClaim();
        uint256 snap = vm.snapshotState();
        vm.etch(address(factory), hex"");
        assertEq(_cancelAndReadCooldown(), 30 days);
        vm.revertToState(snap);
        // Returns one byte instead of a word.
        vm.etch(address(factory), hex"600160005360016000f3");
        assertEq(_cancelAndReadCooldown(), 30 days);
    }

    /// A factory that burns all the gas it is given cannot starve the owner.
    function test_cooldown_gasBurningFactory_ownerCallStillSucceeds() public {
        _pendingClaim();
        vm.etch(address(factory), hex"5b600056"); // JUMPDEST PUSH1 0 JUMP: an infinite loop
        vm.prank(alice, alice);
        acct.withdraw{gas: 400_000}(address(cusd), 1e18);
        assertEq(cusd.balanceOf(alice), 1e18);
        assertEq(acct.claimCooldownUntil(), block.timestamp + 30 days);
    }

    // ── execution and the withdraw-only box (6.5, 6.6, I-12, I-13) ──────

    function _inherit() internal {
        _pendingClaim();
        _warpPaid(acct.claimExecutableAt());
        _execute(bob);
    }

    function test_execution_resetsEveryField_movesNoToken() public {
        _withBeneficiary();
        btcb.mint(address(acct), 1e18);
        _givePlus(address(acct), 7e18);
        IConfioSmartAccount.RuleInput memory r = _rule(IConfioSmartAccount.RuleKind.Send, address(cusd), 1e18);
        r.payee = carol;
        _asOwner();
        acct.createRule(r);
        _asOwner();
        acct.changePlan(IConfioSmartAccount.Plan.Annual);
        _name(carol, 365 days);
        // Leave the next period unpaid with a notice running, so the
        // billing fields are set too.
        uint256 all = cusd.balanceOf(address(acct));
        _asOwner();
        acct.withdraw(address(cusd), all);
        _initiate(bob);
        vm.warp(acct.paidUntil());
        _asRelayer();
        acct.startPaymentNotice();
        assertTrue(acct.noticeStartedAt() != 0);
        assertEq(uint8(acct.nextPlan()), 2);
        assertEq(acct.pendingBeneficiary(), carol);
        vm.warp(acct.claimExecutableAt());

        uint256 btc = btcb.balanceOf(address(acct));
        uint256 shares = plus.balanceOf(address(acct));
        _execute(bob);

        assertEq(acct.owner(), bob);
        assertTrue(acct.inherited());
        assertEq(uint8(acct.plan()), 0);
        assertEq(uint8(acct.nextPlan()), 0);
        assertEq(acct.paidUntil(), 0);
        assertFalse(acct.cancelRequested());
        assertEq(acct.noticeStartedAt(), 0);
        assertEq(acct.forcedSaleForPeriod(), 0);
        assertEq(acct.beneficiary(), address(0));
        assertEq(acct.pendingBeneficiary(), address(0));
        assertEq(acct.challengeWindow(), 0);
        assertEq(acct.pendingChallengeWindow(), 0);
        assertEq(acct.pendingBeneficiaryExpiresAt(), 0);
        assertEq(acct.claimStartedAt(), 0);
        assertEq(acct.claimExecutableAt(), 0);
        assertEq(acct.claimCooldownUntil(), 0);
        assertEq(acct.status(), 4);
        assertEq(acct.billingStatus(), 0);
        assertEq(acct.claimStatus(), 0);
        assertEq(acct.feeUsd(), 0);
        // Nothing moved, and no fee at execution (decision 8).
        assertEq(btcb.balanceOf(address(acct)), btc);
        assertEq(plus.balanceOf(address(acct)), shares);
        assertEq(btcb.balanceOf(bob) + plus.balanceOf(bob), 0);
        // The factory entries are unchanged for both parties.
        assertEq(factory.accountOf(alice), address(acct));
        assertEq(factory.accountOf(bob), address(0));
    }

    function test_afterExecution_everythingButInheritedWithdrawRevertsForever() public {
        IConfioSmartAccount.RuleInput memory r = _rule(IConfioSmartAccount.RuleKind.Send, address(cusd), 1e18);
        r.payee = carol;
        _asOwner();
        uint256 id = acct.createRule(r);
        _inherit();
        usdt.mint(address(acct), 1e18);
        vm.warp(block.timestamp + 400 days);

        // Relayer functions.
        vm.startPrank(relayer, relayer);
        vm.expectRevert(BAD_STATE);
        acct.collectFee();
        vm.expectRevert(BAD_STATE);
        acct.startPaymentNotice();
        vm.expectRevert(BAD_STATE);
        acct.forcedSale(new IConfioSmartAccount.SaleLeg[](0), 0, address(0), 0);
        vm.expectRevert(BAD_STATE);
        acct.executeRule(id, abi.encode(CUSD_, uint256(1)), address(0), 0);
        vm.expectRevert(BAD_STATE);
        acct.convertUsdt(CUSD_, 0.99e18, address(0), 0);
        vm.stopPrank();

        // The new owner cannot subscribe, automate, trade or designate.
        bytes memory buy = _swapBuyData(CUSD_, address(btcb), 1e18);
        address[] memory none = new address[](0);
        vm.startPrank(bob, relayer);
        vm.expectRevert(ConfioSmartAccount.IsInherited.selector);
        acct.subscribe(M, type(uint256).max);
        vm.expectRevert(BAD_STATE);
        acct.changePlan(M);
        vm.expectRevert(BAD_STATE);
        acct.cancelSubscription();
        vm.expectRevert(BAD_STATE);
        acct.undoCancel();
        vm.expectRevert(BAD_STATE);
        acct.setBeneficiary(carol, 180 days);
        vm.expectRevert(BAD_STATE);
        acct.createRule(r);
        vm.expectRevert(BAD_STATE);
        acct.updateRule(id, r);
        vm.expectRevert(BAD_STATE);
        acct.cancelRule(id);
        vm.expectRevert(BAD_STATE);
        acct.trade(address(swapRouter), buy, address(cusd), address(btcb), 1e18, 1);
        vm.expectRevert(ConfioSmartAccount.IsInherited.selector);
        acct.withdraw(address(cusd), 1);
        vm.expectRevert(ConfioSmartAccount.IsInherited.selector);
        acct.withdrawAll(none);
        vm.expectRevert(ConfioSmartAccount.IsInherited.selector);
        acct.withdrawDesignation();
        vm.expectRevert(ConfioSmartAccount.IsInherited.selector);
        acct.removeBeneficiary();
        vm.expectRevert(ConfioSmartAccount.IsInherited.selector);
        acct.cancelClaim();
        vm.expectRevert(NOT_BENEFICIARY);
        acct.acceptBeneficiary();
        vm.expectRevert(NOT_BENEFICIARY);
        acct.initiateClaim();
        vm.expectRevert(NOT_BENEFICIARY);
        acct.executeClaim();
        vm.stopPrank();

        // Permissionless functions.
        vm.expectRevert(ConfioSmartAccount.IsInherited.selector);
        acct.returnAsset(address(cusd));
        vm.expectRevert(ConfioSmartAccount.IsInherited.selector);
        acct.latchConfioSale();
    }

    /// I-13: the previous owner's key has no function left but views.
    function test_afterExecution_thePreviousOwnerCanCallNothing() public {
        _inherit();
        IConfioSmartAccount.RuleInput memory r = _rule(IConfioSmartAccount.RuleKind.Send, address(cusd), 1e18);
        r.payee = carol;
        address[] memory none = new address[](0);
        bytes memory buy = _swapBuyData(CUSD_, address(btcb), 1e18);
        vm.startPrank(alice, relayer);
        vm.expectRevert(NOT_OWNER);
        acct.subscribe(M, type(uint256).max);
        vm.expectRevert(NOT_OWNER);
        acct.changePlan(M);
        vm.expectRevert(NOT_OWNER);
        acct.cancelSubscription();
        vm.expectRevert(NOT_OWNER);
        acct.undoCancel();
        vm.expectRevert(NOT_OWNER);
        acct.withdraw(address(cusd), 1);
        vm.expectRevert(NOT_OWNER);
        acct.withdrawAll(none);
        vm.expectRevert(NOT_OWNER);
        acct.withdraw(address(cusd), 1, alice);
        vm.expectRevert(NOT_OWNER);
        acct.withdrawAll(none, alice);
        vm.expectRevert(NOT_OWNER);
        acct.trade(address(swapRouter), buy, address(cusd), address(btcb), 1e18, 1);
        vm.expectRevert(NOT_OWNER);
        acct.createRule(r);
        vm.expectRevert(NOT_OWNER);
        acct.updateRule(1, r);
        vm.expectRevert(NOT_OWNER);
        acct.cancelRule(1);
        vm.expectRevert(NOT_OWNER);
        acct.setBeneficiary(carol, 180 days);
        vm.expectRevert(NOT_OWNER);
        acct.withdrawDesignation();
        vm.expectRevert(NOT_OWNER);
        acct.removeBeneficiary();
        vm.expectRevert(NOT_OWNER);
        acct.cancelClaim();
        vm.expectRevert(NOT_BENEFICIARY);
        acct.acceptBeneficiary();
        vm.expectRevert(NOT_BENEFICIARY);
        acct.initiateClaim();
        vm.expectRevert(NOT_BENEFICIARY);
        acct.executeClaim();
        vm.stopPrank();
        // Alice's own factory entry still points here: she cannot open another.
        vm.prank(alice);
        vm.expectRevert(bytes("account exists"));
        factory.createAccount();
    }

    function test_inheritedWithdraw_toTheNewOwnersWallet_andOwnAccount_nothingElse() public {
        btcb.mint(address(acct), 1e18);
        _inherit();
        uint256 balance = cusd.balanceOf(address(acct));
        address[] memory tokens = new address[](2);
        tokens[0] = address(cusd);
        tokens[1] = address(btcb);

        // To accountOf(owner) when the new owner has none.
        address predicted = factory.predictAddress(bob);
        vm.startPrank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.BadDestination.selector);
        acct.withdraw(address(cusd), 1e18, predicted);
        // To any other address.
        vm.expectRevert(ConfioSmartAccount.BadDestination.selector);
        acct.withdraw(address(cusd), 1e18, eve);
        vm.expectRevert(ConfioSmartAccount.BadDestination.selector);
        acct.withdraw(address(cusd), 1e18, alice);
        vm.expectRevert(ConfioSmartAccount.BadDestination.selector);
        acct.withdrawAll(tokens, address(acct));
        vm.expectRevert(ConfioSmartAccount.BadDestination.selector);
        acct.withdrawAll(tokens, address(0));
        // To the wallet.
        acct.withdraw(address(cusd), 10e18, bob);
        vm.stopPrank();
        assertEq(cusd.balanceOf(bob), 10e18);

        // To the new owner's own Cuenta inteligente, no deadline.
        ConfioSmartAccount bobs = _create(bob);
        assertEq(address(bobs), predicted);
        vm.warp(block.timestamp + 1_000 days);
        vm.prank(bob, bob);
        acct.withdrawAll(tokens, address(bobs));
        assertEq(cusd.balanceOf(address(bobs)), balance - 10e18);
        assertEq(btcb.balanceOf(address(bobs)), 1e18);
        assertEq(cusd.balanceOf(address(acct)), 0);
        // Someone else's account is not a destination.
        ConfioSmartAccount carols = _create(carol);
        vm.prank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.BadDestination.selector);
        acct.withdraw(address(cusd), 0, address(carols));
    }

    /// Decision 10: an account the caller once opened may since have passed
    /// to someone else.
    function test_inheritedWithdraw_toOwnAccountThatWasItselfInherited_reverts() public {
        _inherit();
        // Bob's own account passes to Carol.
        ConfioSmartAccount bobs = _create(bob);
        _giveCusd(address(bobs), 500e18);
        _approveName(bobs, carol, 90 days);
        vm.startPrank(bob, relayer);
        bobs.subscribe(M, type(uint256).max);
        bobs.setBeneficiary(carol, 90 days);
        vm.stopPrank();
        _approveAccept(bobs, carol);
        vm.prank(carol, relayer);
        bobs.acceptBeneficiary();
        vm.prank(carol, carol);
        bobs.initiateClaim();
        uint256 at = bobs.claimExecutableAt();
        while (bobs.paidUntil() <= at) {
            vm.warp(bobs.paidUntil());
            vm.prank(relayer, relayer);
            bobs.collectFee();
        }
        vm.warp(at);
        vm.prank(carol, carol);
        bobs.executeClaim();
        assertEq(factory.accountOf(bob), address(bobs), "the factory still points at it");

        vm.prank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.BadDestination.selector);
        acct.withdraw(address(cusd), 1e18, address(bobs));
        // The wallet always works.
        vm.prank(bob, bob);
        acct.withdraw(address(cusd), 1e18, bob);
    }

    /// Audit P3: the destination is computed from (FACTORY, implementation,
    /// salt), never read. A factory that names another contract for the new
    /// owner is ignored; the real account works even with the factory dead.
    function test_inheritedWithdraw_factoryNamingAFakeAccount_isIgnored() public {
        _inherit();
        ConfioSmartAccount bobs = _create(bob);
        FakeAccount fake = new FakeAccount(bob);
        vm.mockCall(
            address(factory), abi.encodeCall(IConfioSmartAccountFactory.accountOf, (bob)), abi.encode(address(fake))
        );
        assertEq(factory.accountOf(bob), address(fake));
        vm.prank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.BadDestination.selector);
        acct.withdraw(address(cusd), 1e18, address(fake));
        // The real one still works, whatever the factory says.
        vm.prank(bob, bob);
        acct.withdraw(address(cusd), 1e18, address(bobs));
        assertEq(cusd.balanceOf(address(bobs)), 1e18);
    }

    function test_inheritedWithdraw_toOwnAccount_worksWithTheFactoryDead() public {
        _inherit();
        ConfioSmartAccount bobs = _create(bob);
        uint256 balance = cusd.balanceOf(address(acct));
        vm.etch(address(factory), hex"");
        address[] memory tokens = new address[](1);
        tokens[0] = address(cusd);
        vm.prank(bob, bob);
        acct.withdrawAll(tokens, address(bobs));
        assertEq(cusd.balanceOf(address(bobs)), balance);
        // Still nobody else's account.
        vm.prank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.BadDestination.selector);
        acct.withdraw(address(cusd), 0, address(acct));
    }

    // ── the direct path (6.7) ───────────────────────────────────────────

    /// initiateClaim, executeClaim and inherited withdraw as plain self-paid
    /// transactions: no sponsor anywhere in the call chain, relayer paused,
    /// nobody collecting fees.
    function test_directPath_withoutConfio() public {
        _withBeneficiary();
        btcb.mint(address(acct), 1e18);
        _giveCusd(address(acct), 2_000e18);
        // Annual, so the subscription outlives the window with no relayer.
        _asOwner();
        acct.cancelSubscription();
        vm.warp(acct.paidUntil());
        _giveCusd(address(acct), 0);
        _subscribe(IConfioSmartAccount.Plan.Annual);
        vm.prank(safe);
        factory.setRelayerPaused(true);
        vm.prank(safe);
        plus.setSponsor(relayer, false);

        vm.prank(bob, bob);
        acct.initiateClaim();
        vm.warp(block.timestamp + 90 days);
        vm.prank(bob, bob);
        acct.executeClaim();
        uint256 balance = cusd.balanceOf(address(acct));
        vm.startPrank(bob, bob);
        acct.withdraw(address(btcb), 1e18, bob);
        acct.withdraw(address(cusd), balance, bob);
        vm.stopPrank();
        assertEq(btcb.balanceOf(bob), 1e18);
        assertEq(cusd.balanceOf(bob), balance);
    }

    // ── bytecode (decision 23, I-20) ────────────────────────────────────

    /// Walks the implementation's runtime code opcode by opcode (skipping
    /// PUSH data and the trailing metadata) and refuses DELEGATECALL,
    /// CALLCODE and SELFDESTRUCT.
    function test_bytecode_implementationHasNoDelegatecallCallcodeOrSelfdestruct() public view {
        bytes memory code = address(implementation).code;
        assertLt(code.length, 24_576, "under the EIP-170 limit");
        // Solidity appends CBOR metadata; its length is the last two bytes.
        uint256 metadata = (uint256(uint8(code[code.length - 2])) << 8) + uint8(code[code.length - 1]) + 2;
        uint256 end = code.length - metadata;
        uint256 calls;
        for (uint256 i = 0; i < end; ++i) {
            uint8 op = uint8(code[i]);
            assertTrue(op != 0xf4, "DELEGATECALL");
            assertTrue(op != 0xf2, "CALLCODE");
            assertTrue(op != 0xff, "SELFDESTRUCT");
            if (op == 0xf1) ++calls;
            if (op >= 0x60 && op <= 0x7f) i += op - 0x5f; // PUSH1..PUSH32
        }
        assertGt(calls, 0, "the walk saw real code");
    }

    function test_bytecode_accountIsExactlyTheEip1167CloneOfTheImplementation() public {
        bytes memory expected =
            abi.encodePacked(hex"363d3d373d3d3d363d73", address(implementation), hex"5af43d82803e903d91602b57fd5bf3");
        assertEq(address(acct).code, expected);
        assertEq(address(_create(carol)).code, expected);
        assertEq(acct.FACTORY(), address(factory));
        // The implementation itself is inert: nobody owns it.
        assertEq(implementation.owner(), address(0));
        vm.prank(address(0), address(0));
        vm.expectRevert(ConfioSmartAccount.NotFactory.selector);
        implementation.initialize(eve);
        // A clone cannot be initialized twice, not even by the factory.
        vm.prank(address(factory));
        vm.expectRevert(BAD_STATE);
        acct.initialize(eve);
    }
}
