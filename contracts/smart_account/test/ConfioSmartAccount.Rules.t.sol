// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {ConfioSmartAccount} from "../ConfioSmartAccount.sol";
import {ConfioSmartAccountFactory} from "../ConfioSmartAccountFactory.sol";
import {IConfioSmartAccount} from "../interfaces/IConfioSmartAccount.sol";
import {SmartAccountBase} from "./Base.t.sol";
import {EvilSwapRouter} from "./Mocks.sol";
import {ConfioStockRouter} from "ondo-stocks/ConfioStockRouter.sol";

/// Spec 10.2, "Rules": send, payout and buy rules (4.7, decisions 16-18, 29).
contract ConfioSmartAccountRulesTest is SmartAccountBase {
    IConfioSmartAccount.RuleKind constant SEND = IConfioSmartAccount.RuleKind.Send;
    IConfioSmartAccount.RuleKind constant PAYOUT = IConfioSmartAccount.RuleKind.Payout;
    IConfioSmartAccount.RuleKind constant BUY = IConfioSmartAccount.RuleKind.Buy;
    bytes32 constant PAYOUT_REF = keccak256("mx_clabe:saved-destination-1");

    event RuleExecuted(uint256 indexed id, address tokenIn, address tokenOut, uint256 amountIn, uint256 amountOut);
    event PayoutSent(
        uint256 indexed id,
        bytes32 indexed payoutRef,
        address destination,
        address tokenIn,
        uint256 amountIn,
        uint256 usdtOut
    );

    function setUp() public override {
        super.setUp();
        _subscribedMonthly(1_000e18);
        _givePlus(address(acct), 1_000e18);
    }

    function _create(IConfioSmartAccount.RuleInput memory r) internal returns (uint256 id) {
        vm.prank(alice, relayer);
        id = acct.createRule(r);
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

    function _sendRule(address tokenIn, uint256 amountUsd) internal returns (uint256) {
        IConfioSmartAccount.RuleInput memory r = _rule(SEND, tokenIn, amountUsd);
        r.payee = carol;
        return _create(r);
    }

    function _payoutRule(address tokenIn, uint256 amountUsd) internal returns (uint256) {
        IConfioSmartAccount.RuleInput memory r = _rule(PAYOUT, tokenIn, amountUsd);
        r.payoutRef = PAYOUT_REF;
        return _create(r);
    }

    function _buyRule(address tokenIn, address tokenOut, uint256 amountUsd) internal returns (uint256) {
        IConfioSmartAccount.RuleInput memory r = _rule(BUY, tokenIn, amountUsd);
        r.tokenOut = tokenOut;
        return _create(r);
    }

    function _send(uint8 payeeDollar) internal pure returns (bytes memory) {
        return abi.encode(payeeDollar, uint256(1));
    }

    // ── create / update / cancel ────────────────────────────────────────

    function test_createRule_storesWhatTheOwnerSigned() public {
        IConfioSmartAccount.RuleInput memory r = _rule(SEND, address(cusd), 25e18);
        r.payee = carol;
        r.firstRunAt = uint64(block.timestamp + 3 days);
        uint256 id = _create(r);
        assertEq(id, 1);
        assertEq(acct.nextRuleId(), 2);
        IConfioSmartAccount.Rule memory stored = acct.rule(id);
        assertEq(uint8(stored.kind), uint8(SEND));
        assertEq(uint8(stored.frequency), uint8(IConfioSmartAccount.Frequency.Weekly));
        assertTrue(stored.active);
        assertEq(stored.tokenIn, address(cusd));
        assertEq(stored.payee, carol);
        assertEq(stored.amountUsd, 25e18);
        assertEq(stored.nextRunAt, block.timestamp + 3 days);

        _runReverts(ConfioSmartAccount.TooEarly.selector, id, _send(CUSD_));
        vm.warp(block.timestamp + 3 days);
        _run(id, _send(CUSD_));
        assertEq(cusd.balanceOf(carol), 25e18);
    }

    function test_createRule_validation() public {
        bytes4 bad = ConfioSmartAccount.BadRule.selector;
        IConfioSmartAccount.RuleInput memory r = _rule(SEND, address(cusd), 1e18);
        // Send without a payee, to the account itself, with stray fields.
        vm.startPrank(alice, relayer);
        vm.expectRevert(bad);
        acct.createRule(r);
        r.payee = address(acct);
        vm.expectRevert(bad);
        acct.createRule(r);
        r.payee = carol;
        r.tokenOut = address(btcb);
        vm.expectRevert(bad);
        acct.createRule(r);
        r.tokenOut = address(0);
        r.amountUsd = 0;
        vm.expectRevert(bad);
        acct.createRule(r);
        r.amountUsd = 1e18;
        // tokenIn must be one of the two dollars.
        r.tokenIn = address(usdt);
        vm.expectRevert(bad);
        acct.createRule(r);
        r.tokenIn = address(btcb);
        vm.expectRevert(bad);
        acct.createRule(r);

        // Payout needs its reference and nothing else.
        r = _rule(PAYOUT, address(cusd), 1e18);
        vm.expectRevert(bad);
        acct.createRule(r);
        r.payoutRef = PAYOUT_REF;
        r.payee = carol;
        vm.expectRevert(bad);
        acct.createRule(r);

        // Buy: a real asset; a stock only from cUSD+.
        r = _rule(BUY, address(cusd), 1e18);
        vm.expectRevert(bad);
        acct.createRule(r);
        r.tokenOut = address(plus);
        vm.expectRevert(bad);
        acct.createRule(r);
        r.tokenOut = address(usdt);
        vm.expectRevert(bad);
        acct.createRule(r);
        r.tokenOut = address(tsla);
        vm.expectRevert(bad);
        acct.createRule(r);
        r.tokenIn = address(plus);
        acct.createRule(r);
        r.tokenIn = address(cusd);
        r.tokenOut = address(xaut);
        acct.createRule(r);
        vm.stopPrank();
    }

    function test_updateAndCancelRule() public {
        uint256 id = _sendRule(address(cusd), 10e18);
        IConfioSmartAccount.RuleInput memory r = _rule(SEND, address(cusd), 3e18);
        r.payee = bob;
        vm.prank(alice, relayer);
        acct.updateRule(id, r);
        _run(id, _send(CUSD_));
        assertEq(cusd.balanceOf(bob), 3e18);
        assertEq(cusd.balanceOf(carol), 0);

        vm.prank(alice, relayer);
        acct.cancelRule(id);
        assertFalse(acct.rule(id).active);
        vm.warp(block.timestamp + 30 days - 1);
        _runReverts(ConfioSmartAccount.BadRule.selector, id, _send(CUSD_));
        vm.startPrank(alice, relayer);
        vm.expectRevert(ConfioSmartAccount.BadRule.selector);
        acct.cancelRule(id);
        vm.expectRevert(ConfioSmartAccount.BadRule.selector);
        acct.updateRule(id, r);
        vm.expectRevert(ConfioSmartAccount.BadRule.selector);
        acct.updateRule(99, r);
        vm.stopPrank();
        _runReverts(ConfioSmartAccount.BadRule.selector, 99, _send(CUSD_));
    }

    function test_rules_needAnActiveSubscription() public {
        ConfioSmartAccount fresh = _create(carol);
        IConfioSmartAccount.RuleInput memory r = _rule(SEND, address(cusd), 1e18);
        r.payee = bob;
        vm.prank(carol, relayer);
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        fresh.createRule(r);
    }

    // ── Send (4.7, decisions 16 and 17) ─────────────────────────────────

    /// Every source/payee dollar combination: the only recipient is the
    /// stored payee and the account never ends up holding the other dollar.
    function test_send_fromCusd_toACusdPayee_inKind() public {
        uint256 id = _sendRule(address(cusd), 40e18);
        vm.expectEmit(true, false, false, true, address(acct));
        emit RuleExecuted(id, address(cusd), address(cusd), 40e18, 40e18);
        _run(id, _send(CUSD_));
        assertEq(cusd.balanceOf(carol), 40e18);
        assertEq(cusd.balanceOf(address(acct)), 960e18);
        assertEq(plus.balanceOf(address(acct)), 1_000e18);
    }

    function test_send_fromCusdPlus_toACusdPlusPayee_inKind() public {
        _growPPlus(150);
        uint256 id = _sendRule(address(plus), 40e18);
        uint256 shares = _sharesFor(40e18);
        _run(id, _send(PLUS));
        assertEq(plus.balanceOf(carol), shares);
        assertEq(plus.balanceOf(address(acct)), 1_000e18 - shares);
        assertEq(cusd.balanceOf(carol), 0);
    }

    function test_send_fromCusdPlus_toACusdPayee_unwrapsStraightToThePayee() public {
        _growPPlus(150);
        uint256 id = _sendRule(address(plus), 40e18);
        uint256 shares = _sharesFor(40e18);
        uint256 cusdBefore = cusd.balanceOf(address(acct));
        uint256 feesBefore = cusd.accruedEntryFees() + cusd.accruedExitFees();
        _run(id, abi.encode(CUSD_, uint256(39.99e18)));
        // Fee-free conversion: the payee gets the dollar value, in cUSD.
        assertApproxEqAbs(cusd.balanceOf(carol), 40e18, 1e6);
        assertEq(plus.balanceOf(carol), 0);
        assertEq(plus.balanceOf(address(acct)), 1_000e18 - shares);
        assertEq(cusd.balanceOf(address(acct)), cusdBefore, "the account holds none of the other dollar");
        assertEq(cusd.accruedEntryFees() + cusd.accruedExitFees(), feesBefore, "no conversion fee");
        _noAllowances(address(acct));
    }

    function test_send_fromCusd_toACusdPlusPayee_wrapsStraightToThePayee() public {
        _growPPlus(150);
        uint256 id = _sendRule(address(cusd), 40e18);
        uint256 plusBefore = plus.balanceOf(address(acct));
        _run(id, abi.encode(PLUS, _sharesFor(39.99e18)));
        assertApproxEqAbs((plus.balanceOf(carol) * plus.pPlus()) / 1e18, 40e18, 1e6);
        assertEq(cusd.balanceOf(carol), 0);
        assertEq(cusd.balanceOf(address(acct)), 960e18);
        assertEq(plus.balanceOf(address(acct)), plusBefore, "the account holds none of the other dollar");
        _noAllowances(address(acct));
    }

    /// Decision 16: the relayer can only trigger that exact transfer.
    function test_send_onlyStoredPayeeAmountToken_oncePerGap() public {
        uint256 id = _sendRule(address(cusd), 40e18);
        // Payout- or buy-shaped data cannot redirect a send rule: whatever
        // decodes as (dollar, minOut) still pays carol, anything else fails.
        vm.prank(relayer, relayer);
        vm.expectRevert();
        acct.executeRule(id, abi.encode(eve, uint256(1)), address(0), 0);
        _runReverts(ConfioSmartAccount.BadCall.selector, id, abi.encode(uint8(2), uint256(1)));
        _runReverts(ConfioSmartAccount.Slippage.selector, id, abi.encode(CUSD_, uint256(41e18)));

        _run(id, _send(CUSD_));
        assertEq(cusd.balanceOf(carol), 40e18);
        assertEq(cusd.balanceOf(eve) + cusd.balanceOf(relayer), 0);

        // At most once per minimum gap (weekly: 7 days).
        _runReverts(ConfioSmartAccount.TooEarly.selector, id, _send(CUSD_));
        vm.warp(block.timestamp + 7 days - 1);
        _runReverts(ConfioSmartAccount.TooEarly.selector, id, _send(CUSD_));
        vm.warp(block.timestamp + 1);
        _run(id, _send(CUSD_));
        assertEq(cusd.balanceOf(carol), 80e18);

        // The stored rule is unchanged but for nextRunAt (I-4).
        IConfioSmartAccount.Rule memory stored = acct.rule(id);
        assertEq(stored.payee, carol);
        assertEq(stored.amountUsd, 40e18);
        assertEq(stored.tokenIn, address(cusd));
        assertEq(stored.nextRunAt, block.timestamp + 7 days);
    }

    function test_executeRule_onlyRelayer() public {
        uint256 id = _sendRule(address(cusd), 40e18);
        vm.prank(alice, relayer);
        vm.expectRevert(ConfioSmartAccount.NotRelayer.selector);
        acct.executeRule(id, _send(CUSD_), address(0), 0);
        vm.prank(eve, eve);
        vm.expectRevert(ConfioSmartAccount.NotRelayer.selector);
        acct.executeRule(id, _send(CUSD_), address(0), 0);
    }

    // ── frequencies (decision 18) ───────────────────────────────────────

    function _gapTest(IConfioSmartAccount.Frequency f, uint256 gap) internal {
        IConfioSmartAccount.RuleInput memory r = _rule(SEND, address(cusd), 1e18);
        r.payee = carol;
        r.frequency = f;
        uint256 id = _create(r);
        _run(id, _send(CUSD_));
        assertEq(acct.rule(id).nextRunAt, block.timestamp + gap);
        vm.warp(block.timestamp + gap - 1);
        _runReverts(ConfioSmartAccount.TooEarly.selector, id, _send(CUSD_));
        vm.warp(block.timestamp + 1);
        _run(id, _send(CUSD_));
    }

    function test_frequency_daily() public {
        _gapTest(IConfioSmartAccount.Frequency.Daily, 1 days);
    }

    function test_frequency_weekly() public {
        _gapTest(IConfioSmartAccount.Frequency.Weekly, 7 days);
    }

    function test_frequency_biweekly() public {
        _gapTest(IConfioSmartAccount.Frequency.Biweekly, 14 days);
    }

    function test_frequency_monthly() public {
        _giveCusd(address(acct), 100e18);
        // 28 days fits inside the 30-day paid period.
        _gapTest(IConfioSmartAccount.Frequency.Monthly, 28 days);
    }

    function test_missedRuns_areNotCaughtUp() public {
        IConfioSmartAccount.RuleInput memory r = _rule(SEND, address(cusd), 1e18);
        r.payee = carol;
        r.frequency = IConfioSmartAccount.Frequency.Daily;
        uint256 id = _create(r);
        _run(id, _send(CUSD_));
        // Ten days pass with no run.
        vm.warp(block.timestamp + 10 days);
        _run(id, _send(CUSD_));
        _runReverts(ConfioSmartAccount.TooEarly.selector, id, _send(CUSD_));
        assertEq(cusd.balanceOf(carol), 2e18, "one run, not ten");
        assertEq(acct.rule(id).nextRunAt, block.timestamp + 1 days);
    }

    // ── dollar amounts (4.4) ────────────────────────────────────────────

    function test_ruleAmountsAreDollars_sameValueDifferentSharesAsPPlusRises() public {
        IConfioSmartAccount.RuleInput memory r = _rule(SEND, address(plus), 50e18);
        r.payee = carol;
        r.frequency = IConfioSmartAccount.Frequency.Daily;
        uint256 id = _create(r);

        uint256 p1 = plus.pPlus();
        _run(id, _send(PLUS));
        uint256 shares1 = plus.balanceOf(carol);

        vm.warp(block.timestamp + 1 days);
        _growPPlus(180);
        uint256 p2 = plus.pPlus();
        assertGt(p2, p1);
        _run(id, _send(PLUS));
        uint256 shares2 = plus.balanceOf(carol) - shares1;

        assertLt(shares2, shares1, "fewer shares at a higher price");
        assertEq(shares1, (50e18 * 1e18 + p1 - 1) / p1, "computed in the call from pPlus");
        assertEq(shares2, (50e18 * 1e18 + p2 - 1) / p2);
        assertApproxEqAbs((shares1 * p1) / 1e18, 50e18, 1);
        assertApproxEqAbs((shares2 * p2) / 1e18, 50e18, 1);
    }

    /// The share limit is computed from the oracle price at execution even
    /// when nobody poked the vault: executeRule accrues first.
    function test_ruleAmount_accruesBeforePricing() public {
        uint256 id = _sendRule(address(plus), 50e18);
        oracle.setPrice((oracle.price() * 10_150) / 10_000);
        uint256 stale = plus.pPlus();
        _run(id, _send(PLUS));
        uint256 p = plus.pPlus();
        assertGt(p, stale);
        assertEq(plus.balanceOf(carol), (50e18 * 1e18 + p - 1) / p);
    }

    // ── Payout (decisions 18 and 29, C7) ────────────────────────────────

    function test_payout_fromCusd_exitsAtMostItsAmount_emitsRefAndDestination() public {
        uint256 id = _payoutRule(address(cusd), 100e18);
        address bridge = makeAddr("bridgeDepositAddress");
        vm.expectEmit(true, true, false, true, address(acct));
        emit PayoutSent(id, PAYOUT_REF, bridge, address(cusd), 100e18, 99.1e18);
        _run(id, abi.encode(bridge, uint256(99.1e18)));
        assertEq(usdt.balanceOf(bridge), 99.1e18, "normal 0.9% exit fee");
        assertEq(cusd.balanceOf(address(acct)), 900e18, "at most the rule's amount");
        assertEq(usdt.balanceOf(address(acct)), 0);

        // At most once per minimum gap.
        _runReverts(ConfioSmartAccount.TooEarly.selector, id, abi.encode(bridge, uint256(1)));
        vm.warp(block.timestamp + 7 days);
        _run(id, abi.encode(bridge, uint256(1)));
        assertEq(cusd.balanceOf(address(acct)), 800e18);
    }

    /// cUSD+ Payout data: the exact USDT the destination receives and the
    /// gross cUSD redeemed for it (the relayer's figures).
    function _plusPayout(address destination, uint256 gross) internal view returns (bytes memory) {
        return abi.encode(destination, gross - cusd.feeFor(gross), gross);
    }

    function _assertNoAllowance() internal view {
        assertEq(cusd.allowance(address(acct), address(plus)), 0);
        assertEq(cusd.allowance(address(acct), address(cusd)), 0);
        assertEq(plus.allowance(address(acct), address(plus)), 0);
        assertEq(plus.allowance(address(acct), address(cusd)), 0);
    }

    function test_payout_fromCusdPlus_exactUsdt_withinLimit_dustBounded() public {
        _growPPlus(150);
        uint256 id = _payoutRule(address(plus), 100e18);
        address bridge = makeAddr("bridgeDepositAddress");
        uint256 gross = 60e18;
        uint256 net = gross - cusd.feeFor(gross);
        uint256 plusBefore = plus.balanceOf(address(acct));
        uint256 cusdBefore = cusd.balanceOf(address(acct));
        uint256 shares = _sharesFor(gross + (gross * 5) / 10_000);
        uint256 fees = cusd.accruedExitFees();

        vm.expectEmit(true, true, false, true, address(acct));
        emit PayoutSent(id, PAYOUT_REF, bridge, address(plus), shares, net);
        _run(id, abi.encode(bridge, net, gross));

        assertEq(usdt.balanceOf(bridge), net, "exact USDT");
        assertEq(net, 59.46e18);
        assertEq(plus.balanceOf(address(acct)), plusBefore - shares);
        assertLe(shares, _sharesFor(100e18), "within the rule's share limit");
        uint256 dust = cusd.balanceOf(address(acct)) - cusdBefore;
        assertGt(dust, 0);
        assertLe(dust, (gross * 5) / 10_000 + 2, "dust at most the margin");
        assertEq(usdt.balanceOf(address(acct)), 0);
        assertEq(cusd.accruedExitFees() - fees, cusd.feeFor(gross), "one 0.9% exit, the unwrap is free");
        _assertNoAllowance();
    }

    /// A gross near the rule amount: the margin would exceed the limit, so
    /// the unwrap is capped at exactly the share limit and still covers.
    function test_payout_fromCusdPlus_grossNearAmount_unwrapCappedAtLimit() public {
        _growPPlus(150);
        uint256 id = _payoutRule(address(plus), 100e18);
        address bridge = makeAddr("bridgeDepositAddress");
        uint256 plusBefore = plus.balanceOf(address(acct));
        bytes memory data = _plusPayout(bridge, 99.99e18);
        _run(id, data);
        assertEq(usdt.balanceOf(bridge), 99.99e18 - cusd.feeFor(99.99e18));
        assertEq(plus.balanceOf(address(acct)), plusBefore - _sharesFor(100e18), "exactly the limit");
        _assertNoAllowance();
    }

    function test_payout_fromCusdPlus_guards() public {
        _growPPlus(150);
        uint256 id = _payoutRule(address(plus), 100e18);
        address bridge = makeAddr("bridgeDepositAddress");
        // The gross is bounded by the rule's amount.
        _runReverts(ConfioSmartAccount.BadAmount.selector, id, abi.encode(bridge, uint256(1), uint256(100e18 + 1)));
        _runReverts(ConfioSmartAccount.BadAmount.selector, id, abi.encode(bridge, uint256(0), uint256(0)));
        bytes memory toSelf = _plusPayout(address(acct), 50e18);
        bytes memory toZero = _plusPayout(address(0), 50e18);
        _runReverts(ConfioSmartAccount.BadDestination.selector, id, toSelf);
        _runReverts(ConfioSmartAccount.BadDestination.selector, id, toZero);
        uint256 net = 50e18 - cusd.feeFor(50e18);
        // Exact means exact: one wei under the delivered amount is refused
        // by the account, one over by the vault.
        _runReverts(ConfioSmartAccount.Slippage.selector, id, abi.encode(bridge, net - 1, uint256(50e18)));
        vm.prank(relayer, relayer);
        vm.expectRevert(bytes("insufficient out"));
        acct.executeRule(id, abi.encode(bridge, net + 1, uint256(50e18)), address(0), 0);
        // The pre-change two-word form has no gross: refused.
        vm.prank(relayer, relayer);
        vm.expectRevert();
        acct.executeRule(id, abi.encode(bridge, net), address(0), 0);
        // A gross equal to the amount whose unwrap at the share limit falls
        // short is refused by the vault's floor; nothing moved.
        im.setRedeemHaircutBps(1);
        bytes memory full = _plusPayout(bridge, 100e18);
        vm.prank(relayer, relayer);
        vm.expectRevert();
        acct.executeRule(id, full, address(0), 0);
        assertEq(usdt.balanceOf(bridge), 0);
    }

    /// Ondo paying below the vault's price: within the margin the unwrap
    /// still covers the gross; beyond it the run is refused.
    function test_payout_fromCusdPlus_unwrapCannotCover_refused() public {
        _growPPlus(150);
        uint256 id = _payoutRule(address(plus), 100e18);
        address bridge = makeAddr("bridgeDepositAddress");
        uint256 plusBefore = plus.balanceOf(address(acct));
        uint256 cusdBefore = cusd.balanceOf(address(acct));
        im.setRedeemHaircutBps(10);
        bytes memory data = _plusPayout(bridge, 50e18);
        vm.prank(relayer, relayer);
        vm.expectRevert(bytes("im slippage"));
        acct.executeRule(id, data, address(0), 0);
        assertEq(plus.balanceOf(address(acct)), plusBefore);
        assertEq(cusd.balanceOf(address(acct)), cusdBefore, "the owner's cUSD is never spent");

        im.setRedeemHaircutBps(3);
        _run(id, _plusPayout(bridge, 50e18));
        assertEq(usdt.balanceOf(bridge), 50e18 - cusd.feeFor(50e18));
        assertGe(cusd.balanceOf(address(acct)), cusdBefore);
        assertLe(cusd.balanceOf(address(acct)) - cusdBefore, (50e18 * 5) / 10_000 + 2);
    }

    /// The relayer's figures do not depend on pPlus: when the price moves
    /// between quoting and inclusion (here accrued inside the run itself),
    /// the USDT is still exact and the shares are computed at the new price.
    function test_payout_fromCusdPlus_movingPPlus_stillExact() public {
        _growPPlus(150);
        uint256 id = _payoutRule(address(plus), 100e18);
        address bridge = makeAddr("bridgeDepositAddress");
        bytes memory data = _plusPayout(bridge, 80e18);
        uint256 net = 80e18 - cusd.feeFor(80e18);
        uint256 stale = plus.pPlus();

        oracle.setPrice((oracle.price() * 10_100) / 10_000); // not accrued yet
        uint256 plusBefore = plus.balanceOf(address(acct));
        uint256 cusdBefore = cusd.balanceOf(address(acct));
        _run(id, data);
        uint256 p = plus.pPlus();
        assertGt(p, stale, "accrued inside the run");
        assertEq(usdt.balanceOf(bridge), net);
        assertEq(plus.balanceOf(address(acct)), plusBefore - _sharesFor(80e18 + (80e18 * 5) / 10_000));
        assertLe(cusd.balanceOf(address(acct)) - cusdBefore, (80e18 * 5) / 10_000 + 2);

        // Next period, price moved again: same data, same exact USDT.
        vm.warp(block.timestamp + 7 days);
        _growPPlus(40);
        _run(id, data);
        assertEq(usdt.balanceOf(bridge), 2 * net);
        _assertNoAllowance();
    }

    function test_payout_guards() public {
        uint256 id = _payoutRule(address(cusd), 100e18);
        _runReverts(ConfioSmartAccount.BadDestination.selector, id, abi.encode(address(0), uint256(1)));
        _runReverts(ConfioSmartAccount.BadDestination.selector, id, abi.encode(address(acct), uint256(1)));
        // The relayer's floor is enforced by the vault and by the account.
        vm.prank(relayer, relayer);
        vm.expectRevert(bytes("insufficient out"));
        acct.executeRule(id, abi.encode(eve, uint256(99.2e18)), address(0), 0);
    }

    /// C7: an account with no payment rule gives the relayer no path to an
    /// arbitrary address.
    function test_noPayoutRule_noPathToAnArbitraryAddress() public {
        uint256 sendId = _sendRule(address(cusd), 40e18);
        uint256 buyId = _buyRule(address(cusd), address(btcb), 40e18);
        bytes memory payoutData = abi.encode(eve, uint256(1));

        // Payout-shaped data on a send rule or a buy rule goes nowhere.
        vm.startPrank(relayer, relayer);
        vm.expectRevert();
        acct.executeRule(sendId, payoutData, address(0), 0);
        vm.expectRevert();
        acct.executeRule(buyId, payoutData, address(0), 0);
        // The relayer cannot create a payout rule or touch the dollars.
        IConfioSmartAccount.RuleInput memory r = _rule(PAYOUT, address(cusd), 1e18);
        r.payoutRef = PAYOUT_REF;
        vm.expectRevert(ConfioSmartAccount.NotOwner.selector);
        acct.createRule(r);
        vm.expectRevert(ConfioSmartAccount.NotOwner.selector);
        acct.updateRule(sendId, r);
        vm.expectRevert(ConfioSmartAccount.NotOwner.selector);
        acct.withdraw(address(cusd), 1);
        vm.stopPrank();
        assertEq(cusd.balanceOf(eve) + usdt.balanceOf(eve) + plus.balanceOf(eve), 0);
        assertEq(cusd.balanceOf(address(acct)), 1_000e18);
    }

    // ── Buy (4.7) ───────────────────────────────────────────────────────

    function _buyData(address venue, bytes memory venueData, uint256 minOut) internal pure returns (bytes memory) {
        return abi.encode(venue, venueData, minOut);
    }

    function test_buy_bitcoin_spendsAtMostItsAmount_deliversToTheAccount() public {
        uint256 id = _buyRule(address(cusd), address(btcb), 50e18);
        bytes memory data = _buyData(address(swapRouter), _swapBuyData(CUSD_, address(btcb), 50e18), 1);
        _run(id, data);
        assertEq(cusd.balanceOf(address(acct)), 950e18);
        // 50 less 0.9% at US$100,000.
        assertEq(btcb.balanceOf(address(acct)), (49.55e18 * 1e18) / BTC_PRICE);
        _noAllowances(address(acct));

        // More than the rule's amount: the approval is the limit.
        vm.warp(block.timestamp + 7 days);
        bytes memory tooMuch = _buyData(address(swapRouter), _swapBuyData(CUSD_, address(btcb), 50e18 + 1), 1);
        vm.prank(relayer, relayer);
        vm.expectRevert();
        acct.executeRule(id, tooMuch, address(0), 0);
        // Less is fine: "up to".
        _run(id, _buyData(address(swapRouter), _swapBuyData(CUSD_, address(btcb), 20e18), 1));
        assertEq(cusd.balanceOf(address(acct)), 930e18);
    }

    function test_buy_gold_fromCusdPlus() public {
        _growPPlus(100);
        uint256 id = _buyRule(address(plus), address(xaut), 50e18);
        uint256 shares = _sharesFor(50e18);
        _run(id, _buyData(address(swapRouter), _swapBuyData(PLUS, address(xaut), shares), 1));
        assertEq(plus.balanceOf(address(acct)), 1_000e18 - shares);
        assertApproxEqAbs(xaut.balanceOf(address(acct)), (49.55e18 * 1e6) / XAU_PRICE, 2);
        _noAllowances(address(acct));
    }

    function test_buy_stock_fromCusdPlus_spendsTheWholeRedemption() public {
        uint256 id = _buyRule(address(plus), address(tsla), 60e18);
        bytes memory venueData = _stockBuyData(address(tsla), 60e18, 10_000);
        _run(id, _buyData(address(stockRouter), venueData, 0.19e18));
        assertEq(plus.balanceOf(address(acct)), 940e18);
        assertGt(tsla.balanceOf(address(acct)), 0.19e18);
        assertLe(usdt.balanceOf(address(acct)), 1e16, "at most the quote's rounding stays as USDT");
        _noAllowances(address(acct));
    }

    /// buyWithSavings for exactly `quantity` at STOCK_PRICE, redeeming 60
    /// shares: the rest of the redemption comes back as USDT.
    function _stockBuyQuantity(uint256 quantity) internal returns (bytes memory) {
        uint256 spend = (quantity * STOCK_PRICE) / 1e18;
        return abi.encodeCall(
            ConfioStockRouter.buyWithSavings,
            (_quote(address(tsla), quantity, STOCK_PRICE, 0), "", 60e18, spend, 1, FEE_BPS)
        );
    }

    /// Audit P3: the relayer redeems the whole rule amount, buys a sliver
    /// and leaves the rest as USDT, so convertUsdt would charge the entry
    /// fee a second time. More than one cent of USDT left reverts the run.
    function test_buy_stock_churn_moreThanOneCentOfUsdtLeftReverts() public {
        uint256 id = _buyRule(address(plus), address(tsla), 60e18);
        uint256 net = _netUsdtForShares(60e18);
        bytes4 slippage = ConfioSmartAccount.Slippage.selector;
        // A sliver of stock, the rest left as USDT.
        _runReverts(slippage, id, _buyData(address(stockRouter), _stockBuyData(address(tsla), 60e18, 1), 1));
        // 99%: 0.6 USDT left.
        _runReverts(slippage, id, _buyData(address(stockRouter), _stockBuyData(address(tsla), 60e18, 9_900), 1));
        // The boundary: the smallest quantity leaving at most one cent works,
        // one unit of stock less leaves more and reverts. Stock units of
        // 1e-18 at US$300 are 300 wei of USDT each.
        uint256 q = (net - 1e16 + 299) / 300;
        assertLe(net - q * 300, 1e16);
        assertGt(net - (q - 1) * 300, 1e16);
        _runReverts(slippage, id, _buyData(address(stockRouter), _stockBuyQuantity(q - 1), 1));
        _run(id, _buyData(address(stockRouter), _stockBuyQuantity(q), 1));
        assertEq(usdt.balanceOf(address(acct)), net - q * 300);
        assertEq(tsla.balanceOf(address(acct)), q);
        assertEq(plus.balanceOf(address(acct)), 940e18);
        _noAllowances(address(acct));
    }

    function test_buy_guards() public {
        uint256 btcId = _buyRule(address(cusd), address(btcb), 50e18);
        uint256 stockId = _buyRule(address(plus), address(tsla), 60e18);
        bytes4 badCall = ConfioSmartAccount.BadCall.selector;
        bytes4 badVenue = ConfioSmartAccount.BadVenue.selector;
        bytes memory btcBuy = _swapBuyData(CUSD_, address(btcb), 50e18);
        bytes memory stockBuy = _stockBuyData(address(tsla), 60e18, 10_000);

        // Venue is fixed by the rule's asset.
        _runReverts(badVenue, btcId, _buyData(address(stockRouter), btcBuy, 1));
        _runReverts(badVenue, btcId, _buyData(eve, btcBuy, 1));
        _runReverts(badVenue, stockId, _buyData(address(swapRouter), stockBuy, 1));
        // The pair in the calldata must be the rule's pair.
        _runReverts(badCall, btcId, _buyData(address(swapRouter), _swapBuyData(CUSD_, address(xaut), 50e18), 1));
        _runReverts(badCall, btcId, _buyData(address(swapRouter), _swapBuyData(PLUS, address(btcb), 50e18), 1));
        _runReverts(badCall, stockId, _buyData(address(stockRouter), _stockBuyData(address(aapl), 60e18, 10_000), 1));
        // A sell is not a buy.
        _runReverts(badCall, btcId, _buyData(address(swapRouter), _swapSellData(CUSD_, address(btcb), 1e10), 1));
        _runReverts(badCall, stockId, _buyData(address(stockRouter), _stockSellData(address(tsla), 1e17), 1));
        // The relayer's floor on what the account receives.
        _runReverts(ConfioSmartAccount.Slippage.selector, btcId, _buyData(address(swapRouter), btcBuy, 1e18));
        _noAllowances(address(acct));
        assertEq(cusd.balanceOf(address(acct)), 1_000e18);
    }

    /// A venue that delivers the asset but makes another balance fall is
    /// refused. The real routers cannot do this (they hold no allowance but
    /// tokenIn's); a second implementation with a hostile router shows the
    /// account's own check.
    function test_buy_revertsIfAnotherBalanceFalls() public {
        EvilSwapRouter evil = new EvilSwapRouter(usdt);
        address predicted = vm.computeCreateAddress(address(this), vm.getNonce(address(this)) + 2);
        ConfioSmartAccount impl = new ConfioSmartAccount(
            predicted,
            address(cusd),
            address(plus),
            address(usdt),
            address(confio),
            address(stockRouter),
            address(evil),
            address(collector),
            address(btcb),
            address(btcFeed),
            address(xaut),
            address(xauFeed)
        );
        ConfioSmartAccountFactory logic = _newFactoryLogic();
        ConfioSmartAccountFactory f2 = ConfioSmartAccountFactory(
            address(
                new ERC1967Proxy(
                    address(logic),
                    abi.encodeCall(ConfioSmartAccountFactory.initialize, (safe, address(impl), MONTHLY, ANNUAL))
                )
            )
        );
        vm.prank(alice);
        ConfioSmartAccount a2 = ConfioSmartAccount(f2.createAccount());
        _giveCusd(address(a2), 100e18);
        usdt.mint(address(a2), 5e18);
        vm.startPrank(alice, relayer);
        a2.subscribe(IConfioSmartAccount.Plan.Monthly, type(uint256).max);
        IConfioSmartAccount.RuleInput memory r = _rule(BUY, address(cusd), 50e18);
        r.tokenOut = address(btcb);
        uint256 id = a2.createRule(r);
        vm.stopPrank();

        bytes memory data = _buyData(address(evil), _swapBuyData(CUSD_, address(btcb), 50e18), 1);
        vm.prank(relayer, relayer);
        vm.expectRevert(ConfioSmartAccount.BalanceFell.selector);
        a2.executeRule(id, data, address(0), 0);
        // The owner's own trade is held to the same check.
        vm.prank(alice, relayer);
        vm.expectRevert(ConfioSmartAccount.BalanceFell.selector);
        a2.trade(address(evil), _swapBuyData(CUSD_, address(btcb), 50e18), address(cusd), address(btcb), 50e18, 1);
        assertEq(usdt.balanceOf(address(a2)), 5e18);
    }

    // ── a pending claim does not pause rules (decision 25) ──────────────

    function test_rules_runWhileAClaimIsPending_andDoNotCancelIt() public {
        _withBeneficiary();
        uint256 id = _sendRule(address(cusd), 40e18);
        vm.prank(bob, bob);
        acct.initiateClaim();
        uint64 started = acct.claimStartedAt();
        _run(id, _send(CUSD_));
        assertEq(cusd.balanceOf(carol), 40e18);
        assertEq(acct.claimStartedAt(), started);
        assertEq(acct.claimCooldownUntil(), 0);
    }
}
