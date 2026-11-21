// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ConfioSmartAccount} from "../ConfioSmartAccount.sol";
import {IConfioSmartAccount} from "../interfaces/IConfioSmartAccount.sol";
import {SmartAccountBase} from "./Base.t.sol";

/// Subscription epochs (P3-1): a subscription that ended (Expired, assets
/// returned) and is started again never revives the rules, Card rules or
/// beneficiary of the old one; the owner can always stop a rule.
contract ConfioSmartAccountEpochTest is SmartAccountBase {
    IConfioSmartAccount.Plan constant M = IConfioSmartAccount.Plan.Monthly;
    IConfioSmartAccount.RuleKind constant SEND = IConfioSmartAccount.RuleKind.Send;
    IConfioSmartAccount.RuleKind constant PAYOUT = IConfioSmartAccount.RuleKind.Payout;
    IConfioSmartAccount.RuleKind constant BUY = IConfioSmartAccount.RuleKind.Buy;
    IConfioSmartAccount.RuleKind constant CARD = IConfioSmartAccount.RuleKind.Card;
    bytes4 immutable BAD_RULE = ConfioSmartAccount.BadRule.selector;

    event Subscribed(IConfioSmartAccount.Plan plan, uint256 feeUsd, uint64 paidUntil);
    event RuleCancelled(uint256 indexed id);
    event DesignationWithdrawn(address indexed pendingBeneficiary);
    event BeneficiaryRemoved(address indexed beneficiary);

    address card = makeAddr("cardIssuer");
    address bridge = makeAddr("bridgeDepositAddress");

    uint256 sendId;
    uint256 payoutId;
    uint256 buyId;
    uint256 cardId;

    function setUp() public override {
        super.setUp();
        vm.prank(safe);
        factory.setCardSpender(card, true);
        _subscribedMonthly(1_000e18);
        _givePlus(address(acct), 1_000e18);
    }

    // ── helpers ─────────────────────────────────────────────────────────

    function _create(IConfioSmartAccount.RuleInput memory r) internal returns (uint256 id) {
        _asOwner();
        id = acct.createRule(r);
    }

    function _sendInput(uint256 amountUsd) internal view returns (IConfioSmartAccount.RuleInput memory r) {
        r = _rule(SEND, address(cusd), amountUsd);
        r.payee = carol;
    }

    function _cardInput() internal view returns (IConfioSmartAccount.RuleInput memory r) {
        r = _rule(CARD, address(cusd), 100e18);
        r.payee = card;
    }

    /// One rule of every kind, each run (or pulled) once.
    function _fourRules() internal {
        sendId = _create(_sendInput(10e18));
        IConfioSmartAccount.RuleInput memory r = _rule(PAYOUT, address(cusd), 20e18);
        r.payoutRef = keccak256("ve_pago_movil:1");
        payoutId = _create(r);
        r = _rule(BUY, address(cusd), 30e18);
        r.tokenOut = address(btcb);
        buyId = _create(r);
        cardId = _create(_cardInput());

        _run(sendId, _sendData());
        _run(payoutId, _payoutData());
        _run(buyId, _buyData());
        vm.prank(card);
        acct.cardPull(cardId, 10e18);
        assertGt(acct.cardSpentUsd(cardId), 0);
    }

    function _sendData() internal pure returns (bytes memory) {
        return abi.encode(CUSD_, uint256(1));
    }

    function _payoutData() internal view returns (bytes memory) {
        return abi.encode(bridge, uint256(1));
    }

    function _buyData() internal view returns (bytes memory) {
        return abi.encode(address(swapRouter), _swapBuyData(CUSD_, address(btcb), 30e18), uint256(1));
    }

    function _run(uint256 id, bytes memory data) internal {
        vm.prank(relayer, relayer);
        acct.executeRule(id, data, address(0), 0);
    }

    function _runReverts(bytes4 err, uint256 id, bytes memory data) internal {
        vm.prank(relayer, relayer);
        vm.expectRevert(err);
        acct.executeRule(id, data, address(0), 0);
    }

    /// Cancel, let the period run out (Expired), return the assets.
    function _expireAndReturn() internal {
        _asOwner();
        acct.cancelSubscription();
        vm.warp(acct.paidUntil());
        assertEq(acct.status(), 3, "Expired");
        acct.returnAsset(address(cusd));
        acct.returnAsset(address(plus));
        acct.returnAsset(address(btcb));
    }

    /// The owner moves dollars back in, then subscribes again.
    function _resubscribe() internal {
        _giveCusd(address(acct), 500e18);
        _subscribe(M);
    }

    // ── epoch ───────────────────────────────────────────────────────────

    function test_epoch_startsAtZero_firstSubscribeIsOne_rulesCarryIt() public {
        assertEq(_create(carol).subscriptionEpoch(), 0, "never subscribed");
        assertEq(acct.subscriptionEpoch(), 1);
        uint256 id = _create(_sendInput(1e18));
        assertEq(acct.rule(id).epoch, 1);
        assertTrue(acct.rule(id).active);
    }

    function test_renewal_doesNotBumpTheEpoch_rulesKeepRunning() public {
        _fourRules();
        // Renewal by collectFee, a plan change at renewal, cancel and undo:
        // one subscription throughout.
        _asOwner();
        acct.changePlan(IConfioSmartAccount.Plan.Annual);
        vm.warp(acct.paidUntil());
        vm.prank(relayer, relayer);
        acct.collectFee();
        _asOwner();
        acct.cancelSubscription();
        _asOwner();
        acct.undoCancel();
        assertEq(acct.subscriptionEpoch(), 1, "renewals keep the epoch");

        _run(sendId, _sendData());
        _run(payoutId, _payoutData());
        _run(buyId, _buyData());
        vm.prank(card);
        acct.cardPull(cardId, 10e18);
        assertTrue(acct.rule(sendId).active);
    }

    function test_renewalByForcedSale_doesNotBumpTheEpoch() public {
        uint256 id = _create(_sendInput(1e18));
        vm.startPrank(alice, alice);
        acct.withdraw(address(cusd), cusd.balanceOf(address(acct)));
        acct.withdraw(address(plus), plus.balanceOf(address(acct)));
        vm.stopPrank();
        tsla.mint(address(acct), 1e18);
        _toSaleAllowed();
        _sale(_legs(_stockLeg(tsla, MONTHLY + 0.01e18)), 0, address(0), 0);
        assertEq(acct.billingStatus(), 0, "paid by the sale");
        assertEq(acct.subscriptionEpoch(), 1);
        assertTrue(acct.rule(id).active);
    }

    function test_resubscribe_oldRulesOfEveryKindAreDead() public {
        _fourRules();
        _expireAndReturn();
        _giveCusd(address(acct), 500e18);
        vm.expectEmit(false, false, false, false, address(acct));
        emit Subscribed(M, 0, 0);
        _subscribe(M);
        assertEq(acct.subscriptionEpoch(), 2);
        assertEq(acct.status(), 1);

        vm.warp(vm.getBlockTimestamp() + 28 days);
        uint256[4] memory ids = [sendId, payoutId, buyId, cardId];
        for (uint256 i = 0; i < 4; ++i) {
            IConfioSmartAccount.Rule memory r = acct.rule(ids[i]);
            assertFalse(r.active, "rule(id) reports the old rule inactive");
            assertEq(r.epoch, 1);
        }
        _runReverts(BAD_RULE, sendId, _sendData());
        _runReverts(BAD_RULE, payoutId, _payoutData());
        _runReverts(BAD_RULE, buyId, _buyData());
        _runReverts(BAD_RULE, cardId, _sendData());
        // The old card, with its old count, can never pull again.
        vm.prank(card);
        vm.expectRevert(BAD_RULE);
        acct.cardPull(cardId, 1e18);

        // Nor can the owner revive one by updating it; cancelling a dead
        // rule is refused like a cancelled one.
        vm.startPrank(alice, relayer);
        vm.expectRevert(BAD_RULE);
        acct.updateRule(sendId, _sendInput(1e18));
        vm.expectRevert(BAD_RULE);
        acct.updateRule(cardId, _cardInput());
        vm.expectRevert(BAD_RULE);
        acct.cancelRule(sendId);
        vm.stopPrank();
    }

    function test_resubscribe_newRulesWork() public {
        _fourRules();
        _expireAndReturn();
        _resubscribe();

        uint256 newSend = _create(_sendInput(5e18));
        uint256 newCard = _create(_cardInput());
        assertGt(newSend, cardId, "ids are never reused");
        assertEq(acct.rule(newSend).epoch, 2);
        assertEq(acct.cardSpentUsd(newCard), 0, "a fresh count");

        uint256 before = cusd.balanceOf(carol);
        _run(newSend, _sendData());
        assertEq(cusd.balanceOf(carol) - before, 5e18);
        vm.prank(card);
        acct.cardPull(newCard, 50e18);
        assertEq(usdt.balanceOf(card), 10e18 + 50e18);

        // A new rule updated in the new epoch stays live.
        _asOwner();
        acct.updateRule(newSend, _sendInput(2e18));
        assertTrue(acct.rule(newSend).active);
        assertEq(acct.rule(newSend).epoch, 2);
    }

    // ── cancelRule in any state but Inherited ──────────────────────────

    function test_cancelRule_whileExpired_works_andStaysCancelled() public {
        _fourRules();
        _expireAndReturn();
        vm.expectEmit(true, false, false, false, address(acct));
        emit RuleCancelled(cardId);
        _asOwner();
        acct.cancelRule(cardId);
        _asOwner();
        acct.cancelRule(sendId);
        assertFalse(acct.rule(cardId).active);
        // Still Expired: creating or updating is not allowed there.
        vm.startPrank(alice, relayer);
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.updateRule(payoutId, _sendInput(1e18));
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.createRule(_sendInput(1e18));
        vm.stopPrank();
    }

    function test_cancelRule_whilePaymentDueAndCancelPending_works() public {
        uint256 a = _create(_sendInput(1e18));
        uint256 b = _create(_sendInput(1e18));
        _asOwner();
        acct.cancelSubscription();
        assertEq(acct.status(), 2, "CancelPending");
        _asOwner();
        acct.cancelRule(a);
        _asOwner();
        acct.undoCancel();
        vm.warp(acct.paidUntil());
        assertEq(acct.billingStatus(), 1, "PaymentDue");
        _asOwner();
        acct.cancelRule(b);
        assertFalse(acct.rule(a).active);
        assertFalse(acct.rule(b).active);
    }

    function test_cancelRule_stillOwnerOnly() public {
        uint256 id = _create(_sendInput(1e18));
        _expireAndReturn();
        vm.prank(eve, relayer);
        vm.expectRevert(ConfioSmartAccount.NotOwner.selector);
        acct.cancelRule(id);
        vm.prank(relayer, relayer);
        vm.expectRevert(ConfioSmartAccount.NotOwner.selector);
        acct.cancelRule(id);
    }

    // ── beneficiary ─────────────────────────────────────────────────────

    function test_resubscribe_dropsTheBeneficiaryAndTheDesignation() public {
        _withBeneficiary();
        _name(carol, 180 days);
        _expireAndReturn();
        // Both approvals are live again: only the account's state refuses.
        _approveAccept(acct, carol);
        _giveCusd(address(acct), 500e18);
        vm.expectEmit(true, false, false, false, address(acct));
        emit DesignationWithdrawn(carol);
        vm.expectEmit(true, false, false, false, address(acct));
        emit BeneficiaryRemoved(bob);
        _subscribe(M);

        assertEq(acct.beneficiary(), address(0));
        assertEq(acct.challengeWindow(), 0);
        assertEq(acct.pendingBeneficiary(), address(0));
        assertEq(acct.pendingChallengeWindow(), 0);
        assertEq(acct.pendingBeneficiaryExpiresAt(), 0);
        assertEq(acct.claimCooldownUntil(), 0);

        vm.prank(carol, relayer);
        vm.expectRevert(ConfioSmartAccount.NotBeneficiary.selector);
        acct.acceptBeneficiary();
        vm.prank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.NotBeneficiary.selector);
        acct.initiateClaim();

        // A new designation and acceptance work as on a new account.
        _name(carol, 180 days);
        _accept(carol);
        assertEq(acct.beneficiary(), carol);
        assertEq(acct.challengeWindow(), 180 days);
    }

    function test_resubscribe_endsAClaimPendingOnTheExpiredAccount() public {
        _withBeneficiary();
        _asOwner();
        acct.cancelSubscription();
        vm.prank(bob, bob);
        acct.initiateClaim();
        vm.warp(vm.getBlockTimestamp() + 90 days);
        assertEq(acct.status(), 3, "Expired with the claim pending");
        assertEq(acct.claimStatus(), 2, "Executable, but not on an Expired account");
        vm.prank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.executeClaim();
        _resubscribe();
        assertEq(acct.claimStatus(), 0);
        assertEq(acct.beneficiary(), address(0));
        vm.prank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.NotBeneficiary.selector);
        acct.executeClaim();
        assertEq(acct.owner(), alice);
    }
}
