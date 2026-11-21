// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";
import {ConfioSmartAccount} from "../ConfioSmartAccount.sol";
import {IConfioSmartAccount} from "../interfaces/IConfioSmartAccount.sol";
import {IConfioSmartAccountFactory} from "../interfaces/IConfioSmartAccountFactory.sol";
import {SmartAccountBase} from "./Base.t.sol";
import {ReentrantCardSpender} from "./Mocks.sol";

/// Spec decision 35 and 4.6 "Card spender": a Card rule lets an allowlisted
/// card issuer's spender pull exact USDT, up to the rule's amount per period.
contract ConfioSmartAccountCardTest is SmartAccountBase {
    IConfioSmartAccount.RuleKind constant CARD = IConfioSmartAccount.RuleKind.Card;
    IConfioSmartAccount.Frequency constant DAILY = IConfioSmartAccount.Frequency.Daily;
    IConfioSmartAccount.Frequency constant WEEKLY = IConfioSmartAccount.Frequency.Weekly;

    event CardPulled(uint256 indexed id, address indexed spender, uint256 usdtOut, uint256 usdSpent);

    address card = makeAddr("cardIssuer");
    address card2 = makeAddr("otherCardIssuer");

    function setUp() public override {
        super.setUp();
        _subscribedMonthly(1_000e18);
        _givePlus(address(acct), 1_000e18);
        vm.startPrank(safe);
        factory.setCardSpender(card, true);
        factory.setCardSpender(card2, true);
        vm.stopPrank();
    }

    // ── helpers ─────────────────────────────────────────────────────────

    function _cardInput(address tokenIn, uint256 cap, IConfioSmartAccount.Frequency f)
        internal
        view
        returns (IConfioSmartAccount.RuleInput memory r)
    {
        r = _rule(CARD, tokenIn, cap);
        r.frequency = f;
        r.payee = card;
    }

    function _createRule(IConfioSmartAccount.RuleInput memory r) internal returns (uint256 id) {
        vm.prank(alice, relayer);
        id = acct.createRule(r);
    }

    function _cardRule(address tokenIn, uint256 cap) internal returns (uint256) {
        return _createRule(_cardInput(tokenIn, cap, WEEKLY));
    }

    function _pull(uint256 id, uint256 usdtOut) internal {
        vm.prank(card);
        acct.cardPull(id, usdtOut);
    }

    function _pullReverts(bytes4 err, uint256 id, uint256 usdtOut) internal {
        vm.prank(card);
        vm.expectRevert(err);
        acct.cardPull(id, usdtOut);
    }

    /// The smallest gross whose net after cUSD's ceil-rounded fee is `net`,
    /// found by search against the vault's own feeFor (not the formula).
    function _grossBySearch(uint256 net) internal view returns (uint256 g) {
        g = (net * 10_000) / (10_000 - cusd.feeBps()); // a floor, close below
        g = g > net + 2 ? g - 2 : net;
        while (g - cusd.feeFor(g) < net) ++g;
        while (g > net && (g - 1) - cusd.feeFor(g - 1) >= net) --g;
    }

    function _grossFor(uint256 net) internal view returns (uint256) {
        uint256 bps = cusd.feeBps();
        return (net * 10_000 + (10_000 - bps) - 1) / (10_000 - bps);
    }

    // ── creation (decision 35) ──────────────────────────────────────────

    function test_card_create_needsAnAllowlistedSpender_andCleanFields() public {
        bytes4 bad = ConfioSmartAccount.BadRule.selector;
        IConfioSmartAccount.RuleInput memory r = _cardInput(address(cusd), 100e18, WEEKLY);
        vm.startPrank(alice, relayer);
        r.payee = eve; // not allowlisted
        vm.expectRevert(bad);
        acct.createRule(r);
        r.payee = address(0);
        vm.expectRevert(bad);
        acct.createRule(r);
        r.payee = address(acct);
        vm.expectRevert(bad);
        acct.createRule(r);
        r.payee = card;
        r.tokenOut = address(btcb);
        vm.expectRevert(bad);
        acct.createRule(r);
        r.tokenOut = address(0);
        r.payoutRef = keccak256("x");
        vm.expectRevert(bad);
        acct.createRule(r);
        r.payoutRef = bytes32(0);
        r.tokenIn = address(usdt);
        vm.expectRevert(bad);
        acct.createRule(r);
        r.tokenIn = address(cusd);
        r.amountUsd = 0;
        vm.expectRevert(bad);
        acct.createRule(r);
        r.amountUsd = 100e18;
        r.firstRunAt = uint64(vm.getBlockTimestamp() + 2 days);
        uint256 id = acct.createRule(r);
        vm.stopPrank();

        IConfioSmartAccount.Rule memory stored = acct.rule(id);
        assertEq(uint8(stored.kind), uint8(CARD));
        assertEq(stored.payee, card);
        assertEq(stored.tokenIn, address(cusd));
        assertEq(stored.amountUsd, 100e18);
        assertEq(stored.nextRunAt, vm.getBlockTimestamp() + 2 days, "period start");
        assertEq(acct.cardSpentUsd(id), 0);
        // Before its first period the spender gets nothing.
        _pullReverts(ConfioSmartAccount.TooEarly.selector, id, 1e18);
        vm.warp(vm.getBlockTimestamp() + 2 days);
        _pull(id, 1e18);
    }

    function test_card_create_refusedWhileCardsArePaused_orOnAnInactiveAccount() public {
        vm.prank(safe);
        factory.setCardPaused(true);
        IConfioSmartAccount.RuleInput memory r = _cardInput(address(cusd), 100e18, WEEKLY);
        vm.prank(alice, relayer);
        vm.expectRevert(ConfioSmartAccount.BadRule.selector);
        acct.createRule(r);

        ConfioSmartAccount fresh = _create(carol);
        vm.prank(carol, relayer);
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        fresh.createRule(r);
    }

    // ── exact USDT out, fee math ────────────────────────────────────────

    function test_card_fromCusd_exactUsdt_grossCounted_oneExitFee() public {
        uint256 id = _cardRule(address(cusd), 150e18);
        uint256 fees = cusd.accruedExitFees();
        vm.expectEmit(true, true, false, true, address(acct));
        emit CardPulled(id, card, 99.1e18, 100e18);
        _pull(id, 99.1e18);
        assertEq(usdt.balanceOf(card), 99.1e18, "exact USDT to the spender");
        assertEq(cusd.balanceOf(address(acct)), 900e18, "gross 100 = 99.1 + 0.9% exit");
        assertEq(cusd.accruedExitFees() - fees, 0.9e18, "the normal exit fee, once");
        assertEq(acct.cardSpentUsd(id), 100e18);
        assertEq(plus.balanceOf(address(acct)), 1_000e18, "the other dollar untouched");
        assertEq(usdt.balanceOf(address(acct)), 0);
        _noAllowances(address(acct));
    }

    /// cUSD+ exits through its own redeemToUsdt (unwrapToCusd needs a
    /// sponsor as origin, which a spender's transaction never has), to the
    /// account, and exactly usdtOut is pushed on. The margin's USDT stays.
    function test_card_fromCusdPlus_exactUsdt_marginStaysAsUsdt_ownDollarsUntouched() public {
        _growPPlus(150);
        uint256 id = _cardRule(address(plus), 200e18);
        uint256 net = 123.456789e18;
        uint256 gross = _grossBySearch(net);
        uint256 plusBefore = plus.balanceOf(address(acct));
        uint256 cusdBefore = cusd.balanceOf(address(acct));
        usdt.mint(address(acct), 5e18); // USDT already held, awaiting conversion
        uint256 fees = cusd.accruedExitFees();
        vm.expectEmit(true, true, false, true, address(acct));
        emit CardPulled(id, card, net, gross);
        vm.prank(card, card); // the spender's own transaction: no sponsor
        acct.cardPull(id, net);
        assertEq(usdt.balanceOf(card), net, "exact");
        uint256 shares = _sharesFor(gross + (gross * 5) / 10_000 + 10);
        assertEq(plus.balanceOf(address(acct)), plusBefore - shares, "gross plus the margin");
        assertEq(cusd.balanceOf(address(acct)), cusdBefore, "cUSD untouched");
        uint256 excess = usdt.balanceOf(address(acct)) - 5e18;
        assertLe(excess, (gross * 5) / 10_000 + 12, "at most the margin stays, as USDT");
        assertLe(cusd.accruedExitFees() - fees, cusd.feeFor(gross + (gross * 6) / 10_000), "one 0.9% exit");
        assertEq(acct.cardSpentUsd(id), gross);
        _noAllowances(address(acct));
    }

    /// The account's gross is the smallest whose net is exactly usdtOut,
    /// for any amount and any fee the vault may charge (0 to 90 bps).
    function testFuzz_card_exactUsdt_minimalGross(uint256 net, uint256 feeBps, bool plusIn) public {
        feeBps = bound(feeBps, 0, 90);
        net = bound(net, 1, 900e18);
        vm.prank(safe);
        cusd.setFeeBps(feeBps);
        if (plusIn) _growPPlus(150);
        uint256 id = _cardRule(plusIn ? address(plus) : address(cusd), 1_000e18);
        uint256 cusdBefore = cusd.balanceOf(address(acct));
        uint256 plusBefore = plus.balanceOf(address(acct));
        vm.prank(card, card);
        acct.cardPull(id, net);
        uint256 gross = acct.cardSpentUsd(id);
        assertEq(usdt.balanceOf(card), net, "exact");
        assertEq(gross - cusd.feeFor(gross), net, "net of the counted gross");
        assertEq(gross, _grossBySearch(net), "minimal gross");
        if (plusIn) {
            assertEq(cusd.balanceOf(address(acct)), cusdBefore, "cUSD untouched");
            assertEq(plusBefore - plus.balanceOf(address(acct)), _sharesFor(gross + (gross * 5) / 10_000 + 10));
            assertLe(usdt.balanceOf(address(acct)), (gross * 5) / 10_000 + 12, "margin left as USDT");
        } else {
            assertEq(cusdBefore - cusd.balanceOf(address(acct)), gross, "exactly the gross");
            assertEq(usdt.balanceOf(address(acct)), 0);
        }
    }

    function test_card_cusdPlus_unwrapShort_refused_nothingCounted() public {
        _growPPlus(150);
        uint256 id = _cardRule(address(plus), 200e18);
        im.setRedeemHaircutBps(10); // Ondo pays 10 bps under: beyond the 5 bps margin
        uint256 plusBefore = plus.balanceOf(address(acct));
        vm.prank(card, card);
        vm.expectRevert(bytes("insufficient out"));
        acct.cardPull(id, 50e18);
        assertEq(plus.balanceOf(address(acct)), plusBefore);
        assertEq(acct.cardSpentUsd(id), 0);
        assertEq(usdt.balanceOf(card), 0);
    }

    function test_card_notEnoughDollars_reverts() public {
        uint256 id = _cardRule(address(cusd), 5_000e18);
        vm.prank(card);
        vm.expectRevert();
        acct.cardPull(id, 1_000e18);
        assertEq(acct.cardSpentUsd(id), 0);
    }

    // ── cap per period ──────────────────────────────────────────────────

    function test_card_cap_manyPullsPerPeriod_resetAtTheBoundary() public {
        uint256 id = _cardRule(address(cusd), 100e18);
        uint64 start = uint64(vm.getBlockTimestamp());
        _pull(id, 29.73e18); // gross 30
        _pull(id, 29.73e18);
        _pull(id, 29.73e18);
        assertEq(acct.cardSpentUsd(id), 90e18);
        _pullReverts(ConfioSmartAccount.CapExceeded.selector, id, 9.92e18); // gross 10.0101 > 10 left
        _pull(id, 9.91e18); // gross exactly 10
        assertEq(acct.cardSpentUsd(id), 100e18);
        _pullReverts(ConfioSmartAccount.CapExceeded.selector, id, 1);

        vm.warp(start + 7 days - 1);
        _pullReverts(ConfioSmartAccount.CapExceeded.selector, id, 1);
        vm.warp(start + 7 days);
        _pull(id, 99.1e18);
        assertEq(acct.rule(id).nextRunAt, start + 7 days, "the next fixed period");
        assertEq(acct.cardSpentUsd(id), 100e18);
        assertEq(usdt.balanceOf(card), 3 * 29.73e18 + 9.91e18 + 99.1e18);
    }

    /// Periods are fixed from the first run; periods with no pull are
    /// skipped, never carried over.
    function test_card_periodsAreFixed_missedOnesSkipped_noCarryOver() public {
        uint256 id = _createRule(_cardInput(address(cusd), 50e18, DAILY));
        uint64 start = uint64(vm.getBlockTimestamp());
        _pull(id, 9.91e18);
        vm.warp(start + 3 days + 5 hours);
        _pullReverts(ConfioSmartAccount.CapExceeded.selector, id, 49.56e18); // 50.0101: no carry-over
        _pull(id, 49.55e18); // 50 exactly
        assertEq(acct.rule(id).nextRunAt, start + 3 days);
        vm.warp(start + 4 days - 1);
        _pullReverts(ConfioSmartAccount.CapExceeded.selector, id, 1);
        vm.warp(start + 4 days);
        _pull(id, 1e18);
        assertEq(acct.rule(id).nextRunAt, start + 4 days);
    }

    /// The cap holds for any sequence of pulls and waits: the gross counted
    /// in each fixed period (computed here, independently) never exceeds
    /// the amount, and a pull is refused for the cap only when it would.
    function testFuzz_card_neverMoreThanTheCapPerPeriod(uint256 seed, bool plusIn) public {
        uint256 cap = 30e18;
        uint256 id = _createRule(_cardInput(plusIn ? address(plus) : address(cusd), cap, DAILY));
        uint256 start = vm.getBlockTimestamp();
        uint256 lastPeriod;
        uint256 inPeriod;
        uint256 delivered;
        for (uint256 i = 0; i < 40; ++i) {
            uint256 r = uint256(keccak256(abi.encode(seed, i)));
            if (r % 3 == 0) {
                vm.warp(vm.getBlockTimestamp() + (r >> 8) % 14 hours);
                continue;
            }
            uint256 period = (vm.getBlockTimestamp() - start) / 1 days;
            if (period != lastPeriod) {
                lastPeriod = period;
                inPeriod = 0;
            }
            uint256 net = 1 + (r >> 8) % 35e18;
            uint256 gross = _grossBySearch(net);
            uint256 cardBefore = usdt.balanceOf(card);
            uint256 cusdBefore = cusd.balanceOf(address(acct));
            uint256 plusBefore = plus.balanceOf(address(acct));
            vm.prank(card, card);
            (bool ok, bytes memory ret) = address(acct).call(abi.encodeCall(acct.cardPull, (id, net)));
            if (ok) {
                inPeriod += gross;
                delivered += net;
                assertEq(usdt.balanceOf(card) - cardBefore, net, "exact");
                if (plusIn) {
                    assertEq(cusd.balanceOf(address(acct)), cusdBefore);
                    assertEq(plusBefore - plus.balanceOf(address(acct)), _sharesFor(gross + (gross * 5) / 10_000 + 10));
                } else {
                    assertEq(cusdBefore - cusd.balanceOf(address(acct)), gross, "gross counted = gross taken");
                }
                assertEq(acct.cardSpentUsd(id), inPeriod, "the account's count");
                assertEq(acct.rule(id).nextRunAt, start + period * 1 days, "the account's period");
            } else {
                assertEq(bytes4(ret), ConfioSmartAccount.CapExceeded.selector, "refused for another reason");
                assertGt(inPeriod + gross, cap, "refused although it fit");
            }
            assertLe(inPeriod, cap, "more than the cap in one period");
        }
        assertEq(usdt.balanceOf(card), delivered);
    }

    // ── who may pull ────────────────────────────────────────────────────

    function test_card_onlyTheStoredSpender() public {
        uint256 id = _cardRule(address(cusd), 100e18);
        address[5] memory others = [alice, relayer, eve, card2, address(factory)];
        for (uint256 i = 0; i < others.length; ++i) {
            vm.prank(others[i], others[i]);
            vm.expectRevert(ConfioSmartAccount.NotSpender.selector);
            acct.cardPull(id, 1e18);
        }
        _pullReverts(ConfioSmartAccount.BadAmount.selector, id, 0);
        _pullReverts(ConfioSmartAccount.BadRule.selector, 99, 1e18);

        // A Send rule whose payee is an allowlisted spender is not a card.
        IConfioSmartAccount.RuleInput memory s = _rule(IConfioSmartAccount.RuleKind.Send, address(cusd), 10e18);
        s.payee = card;
        uint256 sendId = _createRule(s);
        _pullReverts(ConfioSmartAccount.BadRule.selector, sendId, 1e18);
    }

    function test_card_relayerCannotRunACardRule() public {
        uint256 id = _cardRule(address(cusd), 100e18);
        bytes[3] memory datas =
            [abi.encode(CUSD_, uint256(1)), abi.encode(card, uint256(1)), abi.encode(address(swapRouter), "", 1)];
        for (uint256 i = 0; i < datas.length; ++i) {
            vm.prank(relayer, relayer);
            vm.expectRevert(ConfioSmartAccount.BadRule.selector);
            acct.executeRule(id, datas[i], address(0), 0);
        }
        assertEq(cusd.balanceOf(address(acct)), 1_000e18);
    }

    function test_card_ownerStopsItAtOnce_cancelOrUpdate() public {
        uint256 id = _cardRule(address(cusd), 100e18);
        _pull(id, 59.46e18); // gross 60
        // An update keeps what was taken and restarts the period from the
        // update: never more room than before.
        vm.prank(alice, relayer);
        acct.updateRule(id, _cardInput(address(cusd), 100e18, WEEKLY));
        assertEq(acct.cardSpentUsd(id), 60e18);
        assertEq(acct.rule(id).nextRunAt, vm.getBlockTimestamp());
        _pullReverts(ConfioSmartAccount.CapExceeded.selector, id, 39.65e18);
        _pull(id, 39.64e18); // 40 exactly

        vm.prank(alice, relayer);
        acct.cancelRule(id);
        vm.warp(vm.getBlockTimestamp() + 8 days);
        _pullReverts(ConfioSmartAccount.BadRule.selector, id, 1e18);

        // A card rule turned into a send rule is no card any more.
        uint256 id2 = _cardRule(address(cusd), 100e18);
        IConfioSmartAccount.RuleInput memory s = _rule(IConfioSmartAccount.RuleKind.Send, address(cusd), 10e18);
        s.payee = carol;
        vm.prank(alice, relayer);
        acct.updateRule(id2, s);
        _pullReverts(ConfioSmartAccount.BadRule.selector, id2, 1e18);
    }

    // ── the Safe's switches ─────────────────────────────────────────────

    function test_card_allowlistRemovedMidPeriod_stopsPulls_readdKeepsTheSameCap() public {
        uint256 id = _cardRule(address(cusd), 100e18);
        _pull(id, 39.64e18); // 40
        vm.prank(safe);
        factory.setCardSpender(card, false);
        _pullReverts(ConfioSmartAccount.SpenderNotAllowed.selector, id, 1e18);
        // Other spenders are unaffected.
        IConfioSmartAccount.RuleInput memory r = _cardInput(address(cusd), 10e18, WEEKLY);
        r.payee = card2;
        uint256 id2 = _createRule(r);
        vm.prank(card2);
        acct.cardPull(id2, 1e18);

        vm.prank(safe);
        factory.setCardSpender(card, true);
        _pullReverts(ConfioSmartAccount.CapExceeded.selector, id, 59.47e18);
        _pull(id, 59.46e18); // 60: 100 in the period in all
    }

    function test_card_cardPause_stopsPulls_relayerPauseDoesNot() public {
        uint256 id = _cardRule(address(cusd), 100e18);
        vm.prank(safe);
        factory.setRelayerPaused(true);
        _pull(id, 1e18);

        vm.startPrank(safe);
        factory.setRelayerPaused(false);
        factory.setCardPaused(true);
        vm.stopPrank();
        _pullReverts(ConfioSmartAccount.SpenderNotAllowed.selector, id, 1e18);
        // Owner functions are untouched by it.
        vm.prank(alice, relayer);
        acct.withdraw(address(cusd), 1e18);

        vm.prank(safe);
        factory.setCardPaused(false);
        _pull(id, 1e18);
    }

    /// An unreadable factory fails closed for cards only.
    function test_card_unreadableFactory_failsClosed() public {
        uint256 id = _cardRule(address(cusd), 100e18);
        vm.mockCallRevert(
            address(factory), abi.encodeWithSelector(IConfioSmartAccountFactory.cardSpenderAllowed.selector), ""
        );
        _pullReverts(ConfioSmartAccount.SpenderNotAllowed.selector, id, 1e18);
        vm.prank(alice, relayer);
        acct.withdraw(address(cusd), 1e18);
        vm.clearMockedCalls();
        _pull(id, 1e18);
    }

    // ── lifecycle and billing gates ─────────────────────────────────────

    function test_card_needsActiveAndCurrent_cancelPendingStillPulls() public {
        uint256 id = _cardRule(address(cusd), 100e18);
        // Payment due: refused, like a rule run.
        vm.warp(acct.paidUntil());
        _pullReverts(ConfioSmartAccount.BadState.selector, id, 1e18);
        vm.prank(relayer, relayer);
        acct.collectFee();
        _pull(id, 1e18);

        // Cancel pending runs to the end of the paid period.
        vm.prank(alice, relayer);
        acct.cancelSubscription();
        _pull(id, 1e18);
        // Expired: refused.
        vm.warp(acct.paidUntil());
        _pullReverts(ConfioSmartAccount.BadState.selector, id, 1e18);
    }

    /// Decision 25 applies: a pending claim does not stop pulls (the owner
    /// still controls the account and can stop the rule, which also ends the
    /// claim). After the ownership transfer no card rule can ever be pulled.
    function test_card_pendingClaimDoesNotBlock_inheritanceEndsIt() public {
        _withBeneficiary();
        uint256 id = _cardRule(address(cusd), 100e18);
        vm.prank(bob, bob);
        acct.initiateClaim();
        uint64 started = acct.claimStartedAt();
        _pull(id, 1e18);
        assertEq(acct.claimStartedAt(), started, "a pull does not touch the claim");
        assertEq(acct.claimCooldownUntil(), 0);

        uint256 executableAt = acct.claimExecutableAt();
        while (acct.paidUntil() <= executableAt) {
            vm.warp(acct.paidUntil());
            vm.prank(relayer, relayer);
            acct.collectFee();
        }
        vm.warp(executableAt);
        vm.prank(bob, bob);
        acct.executeClaim();
        _pullReverts(ConfioSmartAccount.BadState.selector, id, 1e18);
        // Neither the previous owner nor the heir can open a card rule: the
        // box is withdraw-only.
        vm.prank(alice, relayer);
        vm.expectRevert(ConfioSmartAccount.NotOwner.selector);
        acct.createRule(_cardInput(address(cusd), 1e18, WEEKLY));
        vm.prank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.createRule(_cardInput(address(cusd), 1e18, WEEKLY));
    }

    // ── re-entrancy ─────────────────────────────────────────────────────

    /// A spender called back by the token while it is being paid tries to
    /// pull again: the guard refuses, and the outer pull counts once.
    function test_card_reentrantSpender_refused() public {
        ReentrantCardSpender evil = new ReentrantCardSpender();
        vm.prank(safe);
        factory.setCardSpender(address(evil), true);
        IConfioSmartAccount.RuleInput memory r = _cardInput(address(cusd), 100e18, WEEKLY);
        r.payee = address(evil);
        uint256 id = _createRule(r);
        usdt.setCallsBack(address(evil), true);

        evil.pull(address(acct), id, 9.91e18, 9.91e18);
        assertTrue(evil.reentered(), "the callback ran");
        assertFalse(evil.reentrySucceeded(), "re-entry got through");
        assertEq(bytes4(evil.reentryError()), ReentrancyGuardTransient.ReentrancyGuardReentrantCall.selector);
        assertEq(usdt.balanceOf(address(evil)), 9.91e18);
        assertEq(acct.cardSpentUsd(id), 10e18);
        assertEq(cusd.balanceOf(address(acct)), 990e18);
        _noAllowances(address(acct));
    }
}
