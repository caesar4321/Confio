// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {IERC20Metadata} from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Metadata.sol";
import {ConfioSmartAccount} from "../ConfioSmartAccount.sol";
import {IConfioSmartAccount} from "../interfaces/IConfioSmartAccount.sol";
import {IConfioSmartAccountFactory} from "../interfaces/IConfioSmartAccountFactory.sol";
import {SmartAccountBase} from "./Base.t.sol";
import {MockToken, MockFeed, MockConfioVenue, SponsorContract} from "./Mocks.sol";

/// Spec 10.2, "Lifecycle and billing": subscription, the fee and its
/// sources, payment failure, notices and forced sales.
contract ConfioSmartAccountBillingTest is SmartAccountBase {
    IConfioSmartAccount.Plan constant NONE = IConfioSmartAccount.Plan.None;
    IConfioSmartAccount.Plan constant M = IConfioSmartAccount.Plan.Monthly;
    IConfioSmartAccount.Plan constant A = IConfioSmartAccount.Plan.Annual;

    event FeeCollected(
        IConfioSmartAccount.Plan plan,
        uint256 feeUsd,
        uint256 cusdAmount,
        uint256 cusdPlusShares,
        uint256 pPlus,
        uint64 paidUntil
    );
    event ForcedSale(address indexed tokenIn, uint256 amountIn, uint256 dollarsOut, uint64 forPeriod);
    event ConfioSaleLatched(address venue, address priceRef);

    // ── subscribe and the fee sources (5.1, I-3) ────────────────────────

    function test_decimals_areEighteen_andConstructorRefusesOtherwise() public {
        assertEq(IERC20Metadata(address(cusd)).decimals(), 18);
        assertEq(IERC20Metadata(address(plus)).decimals(), 18);
        assertEq(usdt.decimals(), 18);
        MockToken six = new MockToken("USDT6", 6);
        vm.expectRevert(bytes("dollar decimals"));
        new ConfioSmartAccount(
            address(factory),
            address(cusd),
            address(plus),
            address(six),
            address(confio),
            address(stockRouter),
            address(swapRouter),
            address(collector),
            address(btcb),
            address(btcFeed),
            address(xaut),
            address(xauFeed)
        );
    }

    function test_subscribe_takesFirstFeeInCusd() public {
        _giveCusd(address(acct), 20e18);
        vm.expectEmit(false, false, false, true, address(acct));
        emit FeeCollected(M, MONTHLY, MONTHLY, 0, 0, uint64(block.timestamp + 30 days));
        _subscribe(M);
        assertEq(cusd.balanceOf(address(collector)), MONTHLY);
        assertEq(cusd.balanceOf(address(acct)), 20e18 - MONTHLY);
        assertEq(acct.paidUntil(), block.timestamp + 30 days);
        assertEq(uint8(acct.plan()), uint8(M));
        assertEq(acct.status(), 1);
        assertEq(acct.billingStatus(), 0);
        assertEq(acct.periodSeconds(), 30 days);
        assertEq(acct.feeUsd(), MONTHLY);
    }

    /// In-kind cUSD+ fee: shares = ceil(fee / pPlus), transferred not
    /// redeemed, so cUSD's perimeter charges nothing.
    function test_subscribe_inCusdPlusOnly_sharesAreCeilAndNoConversionFee() public {
        _growPPlus(150);
        uint256 p = plus.pPlus();
        assertGt(p, 1e18, "pPlus grew");
        uint256 shares = _givePlusUsd(address(acct), 20e18);
        uint256 valueBefore = acct.dollarsUsd();
        uint256 feesBefore = cusd.accruedEntryFees() + cusd.accruedExitFees();

        _subscribe(M);

        uint256 expected = (MONTHLY * 1e18 + p - 1) / p;
        assertEq(plus.balanceOf(address(collector)), expected, "shares = ceil(fee / pPlus)");
        assertEq(plus.balanceOf(address(acct)), shares - expected);
        assertEq(cusd.accruedEntryFees() + cusd.accruedExitFees(), feesBefore, "no conversion fee charged");
        assertEq(cusd.balanceOf(address(collector)), 0);
        // Remaining shares are worth the balance minus the fee, to within
        // the one-share rounding of the ceil.
        assertApproxEqAbs(acct.dollarsUsd(), valueBefore - MONTHLY, 2);
        // The collected shares are worth the fee, rounded up by < 1 share.
        uint256 collectedUsd = (expected * p) / 1e18;
        assertGe(collectedUsd + 1, MONTHLY);
        assertLe(collectedUsd, MONTHLY + p / 1e18 + 1);
    }

    function test_subscribe_splitAcrossBothDollars() public {
        _growPPlus(100);
        uint256 p = plus.pPlus();
        _giveCusd(address(acct), 5e18);
        _givePlusUsd(address(acct), 15e18);
        _subscribe(M);
        assertEq(cusd.balanceOf(address(collector)), 5e18, "cUSD first, all of it");
        assertEq(plus.balanceOf(address(collector)), ((MONTHLY - 5e18) * 1e18 + p - 1) / p, "then shares for the rest");
        assertEq(cusd.balanceOf(address(acct)), 0);
    }

    function test_subscribe_revertsWhenShort_nothingTakenPartially() public {
        _giveCusd(address(acct), 5e18);
        uint256 shares = _givePlusUsd(address(acct), 5e18);
        _asOwner();
        vm.expectRevert(ConfioSmartAccount.DollarsShort.selector);
        acct.subscribe(M, type(uint256).max);
        assertEq(cusd.balanceOf(address(acct)), 5e18);
        assertEq(plus.balanceOf(address(acct)), shares);
        assertEq(acct.status(), 0);
    }

    function test_subscribe_guards() public {
        _giveCusd(address(acct), 400e18);
        vm.prank(eve, relayer);
        vm.expectRevert(ConfioSmartAccount.NotOwner.selector);
        acct.subscribe(M, type(uint256).max);

        vm.startPrank(alice, relayer);
        vm.expectRevert(ConfioSmartAccount.BadPlan.selector);
        acct.subscribe(NONE, type(uint256).max);
        // The signed maximum binds the first charge (5.4).
        vm.expectRevert(ConfioSmartAccount.FeeAboveMax.selector);
        acct.subscribe(M, MONTHLY - 1);
        acct.subscribe(M, MONTHLY);
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.subscribe(A, type(uint256).max);
        vm.stopPrank();
    }

    function test_subscribe_annual() public {
        _giveCusd(address(acct), ANNUAL);
        _subscribe(A);
        assertEq(acct.paidUntil(), block.timestamp + 365 days);
        assertEq(acct.periodSeconds(), 365 days);
        assertEq(cusd.balanceOf(address(collector)), ANNUAL);
    }

    // ── collectFee (I-3) ────────────────────────────────────────────────

    function test_collectFee_oncePerPeriod_andNotBeforePaidUntil() public {
        _subscribedMonthly(50e18);
        uint64 until = acct.paidUntil();

        vm.warp(until - 1);
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.collectFee();

        vm.warp(until);
        assertEq(acct.billingStatus(), 1, "PaymentDue");
        _asRelayer();
        acct.collectFee();
        assertEq(acct.paidUntil(), block.timestamp + 30 days, "exactly one period from the block time");
        assertEq(cusd.balanceOf(address(collector)), 2 * MONTHLY);

        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.collectFee();
        assertEq(cusd.balanceOf(address(collector)), 2 * MONTHLY, "one fee per period");
    }

    function test_collectFee_latePayment_startsNewPeriodAtPaymentTime() public {
        _subscribedMonthly(50e18);
        vm.warp(acct.paidUntil() + 5 days);
        _asRelayer();
        acct.collectFee();
        assertEq(acct.paidUntil(), block.timestamp + 30 days, "lapsed days are not charged");
    }

    function test_collectFee_revertsWhenShort() public {
        _subscribedMonthly(1e18);
        vm.warp(acct.paidUntil());
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.DollarsShort.selector);
        acct.collectFee();
        assertEq(cusd.balanceOf(address(acct)), 1e18, "nothing taken partially");
    }

    // ── relayer authority (I-4, 4.1) ────────────────────────────────────

    function test_relayer_cannotCallAnyOwnerFunction() public {
        _subscribedMonthly(50e18);
        IConfioSmartAccount.RuleInput memory r = _rule(IConfioSmartAccount.RuleKind.Send, address(cusd), 1e18);
        r.payee = eve;
        address[] memory tokens = new address[](1);
        tokens[0] = address(cusd);
        bytes4 notOwner = ConfioSmartAccount.NotOwner.selector;

        vm.startPrank(relayer, relayer);
        vm.expectRevert(notOwner);
        acct.subscribe(A, type(uint256).max);
        vm.expectRevert(notOwner);
        acct.changePlan(A);
        vm.expectRevert(notOwner);
        acct.cancelSubscription();
        vm.expectRevert(notOwner);
        acct.undoCancel();
        vm.expectRevert(notOwner);
        acct.withdraw(address(cusd), 1);
        vm.expectRevert(notOwner);
        acct.withdrawAll(tokens);
        vm.expectRevert(notOwner);
        acct.withdraw(address(cusd), 1, relayer);
        vm.expectRevert(notOwner);
        acct.withdrawAll(tokens, relayer);
        vm.expectRevert(notOwner);
        acct.trade(address(swapRouter), _swapBuyData(CUSD_, address(btcb), 1e18), address(cusd), address(btcb), 1e18, 1);
        vm.expectRevert(notOwner);
        acct.createRule(r);
        vm.expectRevert(notOwner);
        acct.updateRule(1, r);
        vm.expectRevert(notOwner);
        acct.cancelRule(1);
        vm.expectRevert(notOwner);
        acct.setBeneficiary(relayer, 90 days);
        vm.expectRevert(notOwner);
        acct.withdrawDesignation();
        vm.expectRevert(notOwner);
        acct.removeBeneficiary();
        vm.expectRevert(notOwner);
        acct.cancelClaim();
        vm.expectRevert(ConfioSmartAccount.NotFactory.selector);
        acct.initialize(relayer);
        vm.stopPrank();

        assertEq(acct.owner(), alice);
        assertEq(uint8(acct.plan()), uint8(M));
        assertEq(uint8(acct.nextPlan()), uint8(NONE));
        assertEq(acct.feeUsd(), MONTHLY);
    }

    /// The sponsor set contains contracts (the routers). A contract must
    /// never hold the relayer role: sponsor AND tx.origin.
    function test_relayerRole_needsSponsorThatIsAlsoOrigin() public {
        _subscribedMonthly(50e18);
        vm.warp(acct.paidUntil());

        SponsorContract router = new SponsorContract();
        vm.prank(safe);
        plus.setSponsor(address(router), true);
        // A sponsor contract, called inside a relayer-originated transaction.
        vm.prank(relayer, relayer);
        (bool ok, bytes memory ret) = router.call(address(acct), abi.encodeCall(acct.collectFee, ()));
        assertFalse(ok);
        assertEq(bytes4(ret), ConfioSmartAccount.NotRelayer.selector);

        // The real stock router is a sponsor too.
        vm.prank(address(stockRouter), relayer);
        vm.expectRevert(ConfioSmartAccount.NotRelayer.selector);
        acct.collectFee();

        // An origin that is not a sponsor.
        vm.prank(eve, eve);
        vm.expectRevert(ConfioSmartAccount.NotRelayer.selector);
        acct.collectFee();

        _asRelayer();
        acct.collectFee();
    }

    // ── payment due (4.9, 5.2) ──────────────────────────────────────────

    function test_paymentDue_blocksRulesAndTrade_allowsWithdrawClaimsDeposits() public {
        _subscribedMonthly(1e18);
        _withBeneficiary();
        IConfioSmartAccount.RuleInput memory r = _rule(IConfioSmartAccount.RuleKind.Send, address(cusd), 0.5e18);
        r.payee = carol;
        _asOwner();
        uint256 id = acct.createRule(r);

        vm.warp(acct.paidUntil());
        assertEq(acct.billingStatus(), 1);

        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.executeRule(id, abi.encode(CUSD_, uint256(0)), address(0), 0);

        _asOwner();
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.trade(address(swapRouter), _swapBuyData(CUSD_, address(btcb), 1e18), address(cusd), address(btcb), 1e18, 1);

        // Deposits are plain transfers.
        _giveCusd(address(acct), 2e18);
        _asOwner();
        acct.withdraw(address(cusd), 1e18);
        assertEq(cusd.balanceOf(alice), 1e18);
        vm.prank(bob, bob);
        acct.initiateClaim();
        assertEq(acct.claimStatus(), 1);
    }

    // ── price changes and the factory (decision 24, I-3, I-20) ──────────

    function test_scheduledPriceChange_appliesFromTheRenewalAfterEffectiveAt() public {
        _subscribedMonthly(100e18);
        uint64 effectiveAt = uint64(block.timestamp + 45 days);
        vm.prank(safe);
        factory.scheduleFee(1, 19.99e18, effectiveAt);

        // First renewal, day 30: before effectiveAt, old price.
        vm.warp(acct.paidUntil());
        assertEq(acct.feeUsd(), MONTHLY);
        _asRelayer();
        acct.collectFee();
        assertEq(cusd.balanceOf(address(collector)), 2 * MONTHLY);

        // Second renewal, day 60: after effectiveAt, new price.
        vm.warp(acct.paidUntil());
        assertEq(acct.feeUsd(), 19.99e18);
        _asRelayer();
        acct.collectFee();
        assertEq(cusd.balanceOf(address(collector)), 2 * MONTHLY + 19.99e18);
    }

    function test_feeAboveHardMaximum_isClamped() public {
        _subscribedMonthly(100e18);
        vm.warp(acct.paidUntil());
        // A factory (upgraded by a compromised Safe, say) quoting US$1,000.
        vm.mockCall(address(factory), abi.encodeCall(IConfioSmartAccountFactory.feeUsd, (1)), abi.encode(1_000e18));
        assertEq(acct.feeUsd(), 29.99e18);
        _asRelayer();
        acct.collectFee();
        assertEq(cusd.balanceOf(address(collector)), MONTHLY + 29.99e18);
        vm.mockCall(address(factory), abi.encodeCall(IConfioSmartAccountFactory.feeUsd, (2)), abi.encode(1_000e18));
        vm.clearMockedCalls();
    }

    function test_annualFeeAboveHardMaximum_isClamped() public {
        _giveCusd(address(acct), 400e18);
        vm.mockCall(address(factory), abi.encodeCall(IConfioSmartAccountFactory.feeUsd, (2)), abi.encode(5_000e18));
        _subscribe(A);
        assertEq(cusd.balanceOf(address(collector)), 299.99e18);
    }

    /// I-20: with every factory call reverting, the owner still withdraws,
    /// the return still works and a claim still starts and executes.
    function test_revertingFactory_doesNotBlockWithdrawReturnOrClaims() public {
        _subscribedMonthly(30e18);
        _withBeneficiary();
        ConfioSmartAccount second = _create(carol);
        _giveCusd(address(second), 30e18);
        vm.prank(carol, relayer);
        second.subscribe(M, type(uint256).max);
        vm.prank(carol, relayer);
        second.cancelSubscription();

        vm.prank(bob, bob);
        acct.initiateClaim();

        // PUSH0 PUSH0 REVERT: every call to the factory now fails.
        vm.etch(address(factory), hex"5f5ffd");

        // Owner calls with a pending claim read the cooldown: fallback.
        vm.prank(alice, alice);
        acct.withdraw(address(cusd), 1e18);
        assertEq(cusd.balanceOf(alice), 1e18);
        assertEq(acct.claimCooldownUntil(), block.timestamp + 30 days, "fallback cooldown");
        address[] memory tokens = new address[](1);
        tokens[0] = address(cusd);
        vm.prank(alice, alice);
        acct.withdrawAll(tokens);
        vm.prank(alice, alice);
        acct.cancelClaim();

        vm.warp(block.timestamp + 30 days);
        // (Alice's period is now over and unpaid; a claim does not need it.)
        vm.prank(bob, bob);
        acct.initiateClaim();
        vm.warp(block.timestamp + 90 days);
        vm.prank(bob, bob);
        acct.executeClaim();
        assertEq(acct.owner(), bob);
        _giveCusd(address(acct), 3e18);
        vm.prank(bob, bob);
        acct.withdraw(address(cusd), 3e18, bob);
        assertEq(cusd.balanceOf(bob), 3e18);

        // The other account is Expired by now: anyone returns its assets.
        vm.prank(eve, eve);
        second.returnAsset(address(cusd));
        assertEq(cusd.balanceOf(carol), 30e18 - MONTHLY);

        // What does stop: charging a fee, and the relayer.
        ConfioSmartAccount third = ConfioSmartAccount(address(second));
        vm.prank(carol, relayer);
        vm.expectRevert(ConfioSmartAccount.FactoryUnavailable.selector);
        third.subscribe(M, type(uint256).max);
    }

    // ── notices and forced sales (I-5, I-6, 5.3) ────────────────────────

    function test_startPaymentNotice_onlyWhenDueAndShort() public {
        _subscribedMonthly(20e18);
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.startPaymentNotice();

        vm.warp(acct.paidUntil());
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.DollarsCover.selector);
        acct.startPaymentNotice();

        _asOwner();
        acct.withdraw(address(cusd), 10e18);
        _asRelayer();
        acct.startPaymentNotice();
        assertEq(acct.noticeStartedAt(), block.timestamp);
        assertEq(acct.billingStatus(), 2, "Notice");
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.startPaymentNotice();

        // The owner adds dollars: collectFee cures it and clears the notice.
        _giveCusd(address(acct), 10e18);
        _asRelayer();
        acct.collectFee();
        assertEq(acct.noticeStartedAt(), 0);
        assertEq(acct.billingStatus(), 0);
    }

    function test_forcedSale_revertsBeforeNotice_beforeNoticeEnds_twice_withDollars_onDollars() public {
        _subscribedMonthly(1e18);
        tsla.mint(address(acct), 1e18);
        uint256 shortfall = MONTHLY - 1e18;
        IConfioSmartAccount.SaleLeg[] memory legs = _legs(_stockLeg(tsla, shortfall + 0.01e18));

        // Current.
        _saleReverts(ConfioSmartAccount.BadState.selector, legs, 0);

        // Due, no notice.
        vm.warp(acct.paidUntil());
        _saleReverts(ConfioSmartAccount.BadState.selector, legs, 0);

        // Notice running, not over.
        _asRelayer();
        acct.startPaymentNotice();
        vm.warp(block.timestamp + 7 days - 1);
        _saleReverts(ConfioSmartAccount.BadState.selector, legs, 0);
        vm.warp(block.timestamp + 1);
        assertEq(acct.billingStatus(), 3, "SaleAllowed");

        // A dollar is not sold for dollars.
        _saleReverts(
            ConfioSmartAccount.BadToken.selector,
            _legs(_leg(address(swapRouter), address(cusd), 1e18, _swapSellData(PLUS, address(cusd), 1e18))),
            0
        );
        _saleReverts(
            ConfioSmartAccount.BadToken.selector,
            _legs(_leg(address(stockRouter), address(plus), 1e18, _stockSellData(address(plus), 1e18))),
            0
        );

        // With enough dollars present there is nothing to sell for.
        uint256 snap = vm.snapshotState();
        _giveCusd(address(acct), 20e18);
        _saleReverts(ConfioSmartAccount.DollarsCover.selector, legs, 0);
        vm.revertToState(snap);

        // Once.
        legs = _legs(_stockLeg(tsla, shortfall + 0.01e18));
        _sale(legs, 0, address(0), 0);
        // Twice in the period: the account is Current again.
        legs = _legs(_stockLeg(tsla, 1e18));
        _saleReverts(ConfioSmartAccount.BadState.selector, legs, 0);
    }

    function test_forcedSale_stock_proceedsInCusdPlus_withinCap_feeCollectedSameCall() public {
        _subscribedMonthly(1e18);
        tsla.mint(address(acct), 1e18);
        _toSaleAllowed();
        uint64 period = acct.paidUntil();
        uint256 shortfall = MONTHLY - 1e18;
        IConfioSmartAccount.SaleLeg memory leg = _stockLeg(tsla, shortfall + 0.01e18);
        uint256 collectorCusd = cusd.balanceOf(address(collector));

        vm.expectEmit(true, false, false, false, address(acct));
        emit ForcedSale(address(tsla), 0, 0, period);
        _sale(_legs(leg), shortfall, address(0), 0);

        assertEq(tsla.balanceOf(address(acct)), 1e18 - leg.maxIn, "sold exactly the leg");
        // Fee: the 1 cUSD first, the rest in cUSD+ shares; leftover < US$1.
        assertEq(cusd.balanceOf(address(collector)) - collectorCusd, 1e18);
        assertGt(plus.balanceOf(address(collector)), 0);
        assertLt(acct.dollarsUsd(), 0.05e18, "only the rounding margin is left");
        assertEq(acct.forcedSaleForPeriod(), period, "the unpaid period, not the new one");
        assertEq(acct.paidUntil(), block.timestamp + 30 days);
        assertEq(acct.noticeStartedAt(), 0);
        assertEq(acct.billingStatus(), 0);
        assertEq(cusd.balanceOf(alice) + plus.balanceOf(alice) + tsla.balanceOf(alice), 0, "nothing to the owner");
        _noAllowances(address(acct));
    }

    function _cryptoSale(MockToken token, uint256 price, uint8 dest) internal {
        _subscribedMonthly(0);
        token.mint(address(acct), 10 ** token.decimals());
        _toSaleAllowed();
        IConfioSmartAccount.SaleLeg memory leg = _cryptoLeg(token, price, dest, MONTHLY + 0.01e18);
        uint256 before = token.balanceOf(address(acct));
        _sale(_legs(leg), MONTHLY, address(0), 0);
        assertEq(before - token.balanceOf(address(acct)), leg.maxIn);
        assertEq(acct.billingStatus(), 0);
        assertLt(acct.dollarsUsd(), 0.05e18);
        if (dest == CUSD_) {
            assertEq(cusd.balanceOf(address(collector)), 2 * MONTHLY, "fee in cUSD");
            assertEq(plus.balanceOf(address(acct)), 0);
        } else {
            assertGt(plus.balanceOf(address(collector)), 0, "fee in cUSD+ shares");
            assertEq(cusd.balanceOf(address(acct)), 0);
        }
        _noAllowances(address(acct));
    }

    function test_forcedSale_bitcoin_toCusdPlus() public {
        _cryptoSale(btcb, BTC_PRICE, PLUS);
    }

    function test_forcedSale_bitcoin_toCusd() public {
        _cryptoSale(btcb, BTC_PRICE, CUSD_);
    }

    function test_forcedSale_gold_toCusdPlus() public {
        _cryptoSale(xaut, XAU_PRICE, PLUS);
    }

    function test_forcedSale_gold_toCusd() public {
        _cryptoSale(xaut, XAU_PRICE, CUSD_);
    }

    function test_forcedSale_proceedsAboveCap_revert() public {
        _subscribedMonthly(0);
        btcb.mint(address(acct), 1e18);
        _toSaleAllowed();
        // Cap: 14.99 * 1.05 + 1 = 16.7395. Sell US$17 net.
        _saleReverts(ConfioSmartAccount.CapExceeded.selector, _legs(_cryptoLeg(btcb, BTC_PRICE, CUSD_, 17e18)), 0);
        // Just under the cap passes.
        _sale(_legs(_cryptoLeg(btcb, BTC_PRICE, CUSD_, 16.7e18)), 0, address(0), 0);
    }

    function test_forcedSale_relayerFloor() public {
        _subscribedMonthly(0);
        btcb.mint(address(acct), 1e18);
        _toSaleAllowed();
        _saleReverts(ConfioSmartAccount.Slippage.selector, _legs(_cryptoLeg(btcb, BTC_PRICE, CUSD_, 15.1e18)), 16e18);
    }

    /// 5.3: an annual subscriber with two positions, each worth less than
    /// the fee and together worth more, is charged by ONE operation.
    function test_forcedSale_diversified_twoLegsOneOperationOneCap() public {
        _giveCusd(address(acct), ANNUAL);
        _subscribe(A);
        tsla.mint(address(acct), 0.3e18); // US$90
        btcb.mint(address(acct), 0.0009e18); // US$90
        _toSaleAllowed();
        uint64 period = acct.paidUntil();

        // Legs that together still fall short: the whole call reverts and
        // nothing is sold.
        _saleReverts(
            ConfioSmartAccount.DollarsShort.selector,
            _legs(_stockLeg(tsla, 70e18), _cryptoLeg(btcb, BTC_PRICE, PLUS, 70e18)),
            0
        );
        assertEq(tsla.balanceOf(address(acct)), 0.3e18);
        assertEq(btcb.balanceOf(address(acct)), 0.0009e18);
        assertEq(acct.billingStatus(), 3);

        // Legs that together exceed the aggregate cap (157.49 + 1).
        _saleReverts(
            ConfioSmartAccount.CapExceeded.selector,
            _legs(_stockLeg(tsla, 85e18), _cryptoLeg(btcb, BTC_PRICE, PLUS, 85e18)),
            0
        );

        _sale(_legs(_stockLeg(tsla, 75e18), _cryptoLeg(btcb, BTC_PRICE, PLUS, 75e18)), 0, address(0), 0);
        assertEq(acct.forcedSaleForPeriod(), period);
        assertEq(acct.paidUntil(), block.timestamp + 365 days);
        assertLt(acct.dollarsUsd(), 0.05e18);
        assertLt(tsla.balanceOf(address(acct)), 0.3e18);
        assertLt(btcb.balanceOf(address(acct)), 0.0009e18);
        _noAllowances(address(acct));

        // A second operation in the period.
        _saleReverts(ConfioSmartAccount.BadState.selector, _legs(_stockLeg(tsla, 1e18)), 0);
    }

    function test_forcedSale_legGuards() public {
        _subscribedMonthly(0);
        btcb.mint(address(acct), 1e18);
        tsla.mint(address(acct), 1e18);
        _toSaleAllowed();
        IConfioSmartAccount.SaleLeg memory good = _cryptoLeg(btcb, BTC_PRICE, CUSD_, 15e18);

        // A venue that is neither router.
        _saleReverts(ConfioSmartAccount.BadVenue.selector, _legs(_leg(eve, address(btcb), good.maxIn, good.data)), 0);
        // Bitcoin through the stock router (no feed check there).
        _saleReverts(
            ConfioSmartAccount.BadVenue.selector,
            _legs(_leg(address(stockRouter), address(btcb), good.maxIn, good.data)),
            0
        );
        // A stock (no feed) through the swap router.
        _saleReverts(
            ConfioSmartAccount.BadToken.selector,
            _legs(_leg(address(swapRouter), address(tsla), 1e18, _swapSellData(CUSD_, address(tsla), 1e18))),
            0
        );
        // A buy dressed as a sale leg.
        _saleReverts(
            ConfioSmartAccount.BadCall.selector,
            _legs(_leg(address(swapRouter), address(btcb), 1e18, _swapBuyData(CUSD_, address(btcb), 1e18))),
            0
        );
        // Calldata that sells a different token than the leg names.
        _saleReverts(
            ConfioSmartAccount.BadCall.selector,
            _legs(_leg(address(swapRouter), address(btcb), 1e6, _swapSellData(CUSD_, address(xaut), 1e6))),
            0
        );
        // The venue pulls no more than maxIn: the approval is the limit.
        _asRelayer();
        vm.expectRevert();
        acct.forcedSale(_legs(_leg(address(swapRouter), address(btcb), good.maxIn - 1, good.data)), 0, address(0), 0);
        // No legs.
        _saleReverts(ConfioSmartAccount.DollarsShort.selector, new IConfioSmartAccount.SaleLeg[](0), 0);
    }

    // ── feed check (C2) ─────────────────────────────────────────────────

    function test_forcedSale_manipulatedRoute_refusedByFeed() public {
        _subscribedMonthly(0);
        btcb.mint(address(acct), 1e18);
        _toSaleAllowed();
        // The route returns 5% less than the market: beyond the 3% tolerance.
        dex.setHaircutBps(500);
        uint256 amount = _unitsForNet(16e18, BTC_PRICE, 18);
        IConfioSmartAccount.SaleLeg memory leg =
            _leg(address(swapRouter), address(btcb), amount, _swapSellData(CUSD_, address(btcb), amount));
        _saleReverts(ConfioSmartAccount.BelowFeed.selector, _legs(leg), 0);

        // Within tolerance (2%) it passes.
        dex.setHaircutBps(200);
        _sale(_legs(leg), 0, address(0), 0);
    }

    function test_forcedSale_staleGoldFeed_reverts_thenRetrySucceeds() public {
        _subscribedMonthly(0);
        xaut.mint(address(acct), 1e6);
        _toSaleAllowed();
        IConfioSmartAccount.SaleLeg memory leg = _cryptoLeg(xaut, XAU_PRICE, PLUS, MONTHLY + 0.01e18);

        // Weekend: the gold feed last moved 26 hours and a second ago.
        xauFeed.set(4_000e8, block.timestamp - 26 hours - 1);
        _saleReverts(ConfioSmartAccount.StaleFeed.selector, _legs(leg), 0);
        assertEq(acct.billingStatus(), 3);

        // Exactly at the limit it is still fresh.
        xauFeed.set(4_000e8, block.timestamp - 26 hours);
        _sale(_legs(leg), 0, address(0), 0);
        assertEq(acct.billingStatus(), 0);
    }

    function test_forcedSale_bitcoinFeedAge_oneHour_andBadAnswer() public {
        _subscribedMonthly(0);
        btcb.mint(address(acct), 1e18);
        _toSaleAllowed();
        IConfioSmartAccount.SaleLeg memory leg = _cryptoLeg(btcb, BTC_PRICE, PLUS, MONTHLY + 0.01e18);
        btcFeed.set(100_000e8, block.timestamp - 1 hours - 1);
        _saleReverts(ConfioSmartAccount.StaleFeed.selector, _legs(leg), 0);
        btcFeed.set(0, block.timestamp);
        _saleReverts(ConfioSmartAccount.StaleFeed.selector, _legs(leg), 0);
        btcFeed.set(100_000e8, block.timestamp - 1 hours);
        _sale(_legs(leg), 0, address(0), 0);
    }

    // ── failure and retry (decision 7, I-7) ─────────────────────────────

    function test_failedSale_staysSaleAllowed_nothingReturned_retrySucceeds() public {
        _subscribedMonthly(1e18);
        tsla.mint(address(acct), 1e18);
        _toSaleAllowed();
        IConfioSmartAccount.SaleLeg[] memory legs = _legs(_stockLeg(tsla, MONTHLY - 1e18 + 0.01e18));

        // The venue reverts (halted market, expired quote, paused router).
        gm.setHalted(true);
        _asRelayer();
        vm.expectRevert(bytes("gm: halted"));
        acct.forcedSale(legs, 0, address(0), 0);
        vm.prank(safe);
        stockRouter.pause();
        _asRelayer();
        vm.expectRevert();
        acct.forcedSale(legs, 0, address(0), 0);

        assertEq(acct.billingStatus(), 3, "still SaleAllowed");
        assertEq(tsla.balanceOf(address(acct)), 1e18);
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.returnAsset(address(tsla));
        assertEq(tsla.balanceOf(alice), 0, "nothing returned");

        // Days later the market is back.
        vm.warp(block.timestamp + 3 days);
        gm.setHalted(false);
        vm.prank(safe);
        stockRouter.unpause();
        legs = _legs(_stockLeg(tsla, MONTHLY - 1e18 + 0.01e18));
        _sale(legs, 0, address(0), 0);
        assertEq(acct.billingStatus(), 0);
    }

    function test_accountWorthLessThanOneFee_staysPaused_nothingTaken_nothingReturned() public {
        _subscribedMonthly(2e18);
        btcb.mint(address(acct), 0.00005e18); // US$5
        _toSaleAllowed();
        uint256 all = btcb.balanceOf(address(acct));

        _saleReverts(
            ConfioSmartAccount.DollarsShort.selector,
            _legs(_leg(address(swapRouter), address(btcb), all, _swapSellData(CUSD_, address(btcb), all))),
            0
        );
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.DollarsShort.selector);
        acct.collectFee();

        vm.warp(block.timestamp + 400 days);
        assertEq(acct.billingStatus(), 3, "stays SaleAllowed indefinitely");
        assertEq(btcb.balanceOf(address(acct)), all, "nothing taken partially");
        assertEq(cusd.balanceOf(address(acct)), 2e18);
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.returnAsset(address(btcb));
        assertEq(btcb.balanceOf(alice), 0);
    }

    /// 5.3: the fee rose between sizing and execution, so the proceeds no
    /// longer cover it: the whole call reverts and a retry succeeds.
    function test_forcedSale_feeRoseSoProceedsShort_revertsAndRetries() public {
        _subscribedMonthly(0);
        btcb.mint(address(acct), 1e18);
        uint64 effectiveAt = uint64(acct.paidUntil() + 7 days);
        vm.prank(safe);
        factory.scheduleFee(1, 19.99e18, effectiveAt);
        vm.warp(acct.paidUntil());
        _asRelayer();
        acct.startPaymentNotice();
        IConfioSmartAccount.SaleLeg[] memory sizedForOld = _legs(_cryptoLeg(btcb, BTC_PRICE, CUSD_, MONTHLY + 0.01e18));
        vm.warp(block.timestamp + 7 days);
        _freshFeeds();
        assertEq(acct.feeUsd(), 19.99e18);

        uint256 before = btcb.balanceOf(address(acct));
        _saleReverts(ConfioSmartAccount.DollarsShort.selector, sizedForOld, 0);
        assertEq(btcb.balanceOf(address(acct)), before, "nothing sold without the fee being paid by it");

        _sale(_legs(_cryptoLeg(btcb, BTC_PRICE, CUSD_, 20e18)), 0, address(0), 0);
        assertEq(cusd.balanceOf(address(collector)), MONTHLY + 19.99e18);
    }

    /// I-5: after a successful sale the next unpaid period needs a new
    /// notice and the full notice period.
    function test_afterForcedSale_nextPeriodNeedsFreshNoticeAndFullWait() public {
        _subscribedMonthly(0);
        btcb.mint(address(acct), 1e18);
        _toSaleAllowed();
        _sale(_legs(_cryptoLeg(btcb, BTC_PRICE, CUSD_, MONTHLY + 0.01e18)), 0, address(0), 0);
        assertEq(acct.noticeStartedAt(), 0);

        vm.warp(acct.paidUntil());
        _freshFeeds();
        uint256 shortfall = MONTHLY - acct.dollarsUsd();
        IConfioSmartAccount.SaleLeg[] memory legs = _legs(_cryptoLeg(btcb, BTC_PRICE, CUSD_, shortfall + 0.01e18));
        _saleReverts(ConfioSmartAccount.BadState.selector, legs, 0);
        _asRelayer();
        acct.startPaymentNotice();
        vm.warp(block.timestamp + 7 days - 1);
        _freshFeeds();
        _saleReverts(ConfioSmartAccount.BadState.selector, legs, 0);
        vm.warp(block.timestamp + 1);
        _freshFeeds();
        _sale(legs, 0, address(0), 0);
    }

    /// The notice floor: a factory value below 3 days is raised to 3 days;
    /// an unreadable factory stops the relayer altogether.
    function test_forcedSaleNotice_isFlooredAtThreeDays() public {
        _subscribedMonthly(0);
        btcb.mint(address(acct), 1e18);
        vm.warp(acct.paidUntil());
        _asRelayer();
        acct.startPaymentNotice();
        vm.mockCall(
            address(factory), abi.encodeCall(IConfioSmartAccountFactory.forcedSaleNotice, ()), abi.encode(uint64(0))
        );
        IConfioSmartAccount.SaleLeg[] memory legs = _legs(_cryptoLeg(btcb, BTC_PRICE, CUSD_, MONTHLY + 0.01e18));

        vm.warp(block.timestamp + 3 days - 1);
        _freshFeeds();
        assertEq(acct.billingStatus(), 2);
        _saleReverts(ConfioSmartAccount.BadState.selector, legs, 0);
        vm.warp(block.timestamp + 1);
        _freshFeeds();
        assertEq(acct.billingStatus(), 3);
        _sale(legs, 0, address(0), 0);
    }

    // ── CONFIO (decision 30, 5.5) ───────────────────────────────────────

    function _confioSetup() internal returns (MockConfioVenue venue, MockFeed feed) {
        venue = new MockConfioVenue(IERC20(address(cusd)), 0.5e18);
        feed = new MockFeed(0.5e8, 8);
        _giveCusd(address(venue), 10_000e18);
    }

    function _confioLeg(address venue, uint256 amount) internal view returns (IConfioSmartAccount.SaleLeg memory) {
        return _leg(venue, address(confio), amount, _swapSellData(CUSD_, address(confio), amount));
    }

    function test_confio_cannotBeSoldWhileUnset_setOnce_thenObeysEveryCap() public {
        (MockConfioVenue venue, MockFeed feed) = _confioSetup();
        _subscribedMonthly(0);
        confio.mint(address(acct), 1_000e18);
        _toSaleAllowed();

        // Unset: no venue can sell CONFIO, including the real routers.
        _saleReverts(ConfioSmartAccount.ConfioSaleUnset.selector, _legs(_confioLeg(address(venue), 31e18)), 0);
        _saleReverts(ConfioSmartAccount.ConfioSaleUnset.selector, _legs(_confioLeg(address(swapRouter), 31e18)), 0);
        vm.expectRevert(ConfioSmartAccount.ConfioSaleUnset.selector);
        acct.latchConfioSale();

        // The Safe sets it once (the reference must be live to be set).
        feed.set(0.5e8, block.timestamp);
        vm.expectRevert();
        factory.setConfioSale(address(venue), address(feed));
        vm.startPrank(safe);
        factory.setConfioSale(address(venue), address(feed));
        vm.expectRevert(bytes("already set"));
        factory.setConfioSale(address(dex), address(btcFeed));
        vm.stopPrank();

        // Every cap of 5.3 applies. Too much: above the proceeds cap.
        _saleReverts(ConfioSmartAccount.CapExceeded.selector, _legs(_confioLeg(address(venue), 40e18)), 0);
        // Too little: short.
        _saleReverts(ConfioSmartAccount.DollarsShort.selector, _legs(_confioLeg(address(venue), 20e18)), 0);
        // Only through the latched venue.
        _saleReverts(ConfioSmartAccount.BadVenue.selector, _legs(_confioLeg(address(swapRouter), 31e18)), 0);
        // Price reference: a venue paying 10% under it is refused.
        venue.setPrice(0.45e18);
        _saleReverts(ConfioSmartAccount.BelowFeed.selector, _legs(_confioLeg(address(venue), 34e18)), 0);
        venue.setPrice(0.5e18);
        // Stale reference.
        feed.set(0.5e8, block.timestamp - 26 hours - 1);
        _saleReverts(ConfioSmartAccount.StaleFeed.selector, _legs(_confioLeg(address(venue), 31e18)), 0);
        feed.set(0.5e8, block.timestamp);

        // 31 CONFIO at US$0.50 = US$15.50: covers 14.99, inside the cap.
        vm.expectEmit(false, false, false, true, address(acct));
        emit ConfioSaleLatched(address(venue), address(feed));
        _sale(_legs(_confioLeg(address(venue), 31e18)), 0, address(0), 0);
        assertEq(confio.balanceOf(address(acct)), 969e18);
        assertEq(acct.confioSaleVenue(), address(venue));
        assertEq(acct.confioSalePriceRef(), address(feed));
        assertEq(acct.billingStatus(), 0);
        assertEq(confio.allowance(address(acct), address(venue)), 0);

        // One sale per unpaid period, like any token.
        _saleReverts(ConfioSmartAccount.BadState.selector, _legs(_confioLeg(address(venue), 31e18)), 0);
        vm.expectRevert(ConfioSmartAccount.AlreadyLatched.selector);
        acct.latchConfioSale();
    }

    /// The slot affects no other token, destination or fee.
    function test_confio_slotAffectsNothingElse() public {
        (MockConfioVenue venue, MockFeed feed) = _confioSetup();
        _subscribedMonthly(0);
        btcb.mint(address(acct), 1e18);
        tsla.mint(address(acct), 1e18);
        vm.prank(safe);
        factory.setConfioSale(address(venue), address(feed));
        vm.prank(eve);
        acct.latchConfioSale();
        assertEq(acct.confioSaleVenue(), address(venue));
        assertEq(acct.feeUsd(), MONTHLY, "fee unchanged");
        _toSaleAllowed();
        feed.set(0.5e8, block.timestamp);

        // The CONFIO venue cannot sell bitcoin or a stock.
        uint256 amount = _unitsForNet(15e18, BTC_PRICE, 18);
        _saleReverts(
            ConfioSmartAccount.BadVenue.selector,
            _legs(_leg(address(venue), address(btcb), amount, _swapSellData(CUSD_, address(btcb), amount))),
            0
        );
        _saleReverts(
            ConfioSmartAccount.BadToken.selector,
            _legs(_leg(address(venue), address(tsla), 1e17, _swapSellData(CUSD_, address(tsla), 1e17))),
            0
        );
        // CONFIO cannot go through the stock router.
        confio.mint(address(acct), 100e18);
        _saleReverts(
            ConfioSmartAccount.BadVenue.selector,
            _legs(_leg(address(stockRouter), address(confio), 31e18, _stockSellData(address(confio), 31e18))),
            0
        );
    }

    /// The latch is the account's own copy: a factory that later reports a
    /// different venue (an upgrade) changes nothing for a latched account.
    function test_confio_latchIsFinal() public {
        (MockConfioVenue venue, MockFeed feed) = _confioSetup();
        vm.prank(safe);
        factory.setConfioSale(address(venue), address(feed));
        acct.latchConfioSale();
        vm.mockCall(address(factory), abi.encodeCall(IConfioSmartAccountFactory.confioSale, ()), abi.encode(eve, eve));
        assertEq(acct.confioSaleVenue(), address(venue));
        vm.expectRevert(ConfioSmartAccount.AlreadyLatched.selector);
        acct.latchConfioSale();
    }

    // ── changePlan (I-3, I-4) ───────────────────────────────────────────

    function test_changePlan_annualToMonthly_renewsWithoutNoticeWhenBalanceCoversMonthly() public {
        _giveCusd(address(acct), ANNUAL + 20e18);
        _subscribe(A);
        uint64 until = acct.paidUntil();
        _asOwner();
        acct.changePlan(M);
        assertEq(acct.paidUntil(), until, "current period untouched");
        assertEq(uint8(acct.plan()), uint8(A));
        assertEq(uint8(acct.nextPlan()), uint8(M));
        assertEq(acct.feeUsd(), MONTHLY, "feeUsd resolves the renewal plan");

        vm.warp(until);
        // US$20 covers 14.99: no notice, no sale.
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.DollarsCover.selector);
        acct.startPaymentNotice();
        _asRelayer();
        acct.collectFee();
        assertEq(cusd.balanceOf(address(collector)), ANNUAL + MONTHLY);
        assertEq(acct.paidUntil(), block.timestamp + 30 days, "the new plan's length");
        assertEq(uint8(acct.plan()), uint8(M));
        assertEq(uint8(acct.nextPlan()), uint8(NONE));
    }

    function test_changePlan_monthlyToAnnual_startsNoticeWhenBalanceDoesNotCoverAnnual() public {
        _subscribedMonthly(20e18);
        uint64 until = acct.paidUntil();
        _asOwner();
        acct.changePlan(A);
        assertEq(acct.paidUntil(), until);
        assertEq(acct.feeUsd(), ANNUAL);

        vm.warp(until);
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.DollarsShort.selector);
        acct.collectFee();
        _asRelayer();
        acct.startPaymentNotice();
        assertEq(acct.billingStatus(), 2);

        _giveCusd(address(acct), ANNUAL);
        _asRelayer();
        acct.collectFee();
        assertEq(cusd.balanceOf(address(collector)), MONTHLY + ANNUAL);
        assertEq(acct.paidUntil(), block.timestamp + 365 days);
        assertEq(uint8(acct.plan()), uint8(A));
    }

    function test_changePlan_guards_andWithdrawingTheChange() public {
        _subscribedMonthly(20e18);
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.NotOwner.selector);
        acct.changePlan(A);
        _asOwner();
        vm.expectRevert(ConfioSmartAccount.BadPlan.selector);
        acct.changePlan(NONE);
        _asOwner();
        acct.changePlan(A);
        _asOwner();
        acct.changePlan(M);
        assertEq(uint8(acct.nextPlan()), uint8(NONE), "naming the current plan withdraws the change");
        vm.warp(acct.paidUntil());
        _asOwner();
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.changePlan(A);
    }

    // ── cancel, expiry, return (I-7, decision 7) ────────────────────────

    function test_cancel_automationRunsUntilPaidUntil_returnOnlyAfter_toOwnerOnly() public {
        _subscribedMonthly(10e18);
        IConfioSmartAccount.RuleInput memory r = _rule(IConfioSmartAccount.RuleKind.Send, address(cusd), 1e18);
        r.payee = carol;
        r.frequency = IConfioSmartAccount.Frequency.Daily;
        _asOwner();
        uint256 id = acct.createRule(r);
        _asOwner();
        acct.cancelSubscription();
        assertEq(acct.status(), 2, "CancelPending");

        // Automation keeps running in the paid period.
        _asRelayer();
        acct.executeRule(id, abi.encode(CUSD_, uint256(0)), address(0), 0);
        assertEq(cusd.balanceOf(carol), 1e18);

        vm.warp(acct.paidUntil() - 1);
        vm.prank(eve);
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.returnAsset(address(cusd));

        vm.warp(acct.paidUntil());
        assertEq(acct.status(), 3, "Expired");
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.executeRule(id, abi.encode(CUSD_, uint256(0)), address(0), 0);
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.collectFee();

        vm.prank(eve);
        acct.returnAsset(address(cusd));
        assertEq(cusd.balanceOf(alice), 9e18, "to the owner");
        assertEq(cusd.balanceOf(eve), 0);
        assertEq(cusd.balanceOf(address(acct)), 0);
    }

    function test_return_perAsset_oneFailingTokenDoesNotBlockTheOthers() public {
        _subscribedMonthly(5e18);
        _givePlus(address(acct), 5e18);
        btcb.mint(address(acct), 1e18);
        tsla.mint(address(acct), 1e18);
        usdon.mint(address(acct), 1e12);
        _asOwner();
        acct.cancelSubscription();
        vm.warp(acct.paidUntil());

        // A reverting mock.
        tsla.setBroken(true);
        vm.expectRevert(bytes("token broken"));
        acct.returnAsset(address(tsla));
        // Paused cUSD.
        vm.prank(safe);
        cusd.pause();
        vm.expectRevert(bytes("Pausable: paused"));
        acct.returnAsset(address(cusd));
        // The others go.
        acct.returnAsset(address(btcb));
        acct.returnAsset(address(plus));
        acct.returnAsset(address(usdon));
        assertEq(btcb.balanceOf(alice), 1e18);
        assertEq(plus.balanceOf(alice), 5e18);
        assertEq(usdon.balanceOf(alice), 1e12, "USDon dust is returnable");

        // And the failing ones go once they work again.
        vm.prank(safe);
        cusd.unpause();
        tsla.setBroken(false);
        acct.returnAsset(address(cusd));
        acct.returnAsset(address(tsla));
        assertEq(cusd.balanceOf(alice), 5e18);
        assertEq(tsla.balanceOf(alice), 1e18);
    }

    function test_return_pausedCusdPlus_andFrozenAddress() public {
        _subscribedMonthly(5e18);
        _givePlus(address(acct), 5e18);
        _asOwner();
        acct.cancelSubscription();
        vm.warp(acct.paidUntil());

        vm.prank(safe);
        plus.pause();
        vm.expectRevert();
        acct.returnAsset(address(plus));
        vm.prank(safe);
        plus.unpause();

        vm.prank(safe);
        cusd.freezeAddress(address(acct));
        vm.expectRevert(bytes("address frozen"));
        acct.returnAsset(address(cusd));
        acct.returnAsset(address(plus));
        assertEq(plus.balanceOf(alice), 5e18, "the frozen cUSD does not block cUSD+");
    }

    function test_returnAsset_withoutSignedCancellation_revertsInEveryBillingState() public {
        bytes4 bad = ConfioSmartAccount.BadState.selector;
        // Unsubscribed.
        vm.expectRevert(bad);
        acct.returnAsset(address(cusd));
        _subscribedMonthly(1e18);
        // Current.
        vm.expectRevert(bad);
        acct.returnAsset(address(cusd));
        // PaymentDue.
        vm.warp(acct.paidUntil());
        vm.expectRevert(bad);
        acct.returnAsset(address(cusd));
        // Notice.
        _asRelayer();
        acct.startPaymentNotice();
        vm.expectRevert(bad);
        acct.returnAsset(address(cusd));
        // SaleAllowed.
        vm.warp(block.timestamp + 7 days);
        assertEq(acct.billingStatus(), 3);
        vm.expectRevert(bad);
        acct.returnAsset(address(cusd));
        vm.warp(block.timestamp + 1000 days);
        vm.expectRevert(bad);
        acct.returnAsset(address(cusd));
    }

    function test_undoCancel_andResubscribeAfterExpired() public {
        _subscribedMonthly(40e18);
        _asOwner();
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.undoCancel();
        _asOwner();
        acct.cancelSubscription();
        _asOwner();
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.cancelSubscription();
        _asOwner();
        acct.undoCancel();
        assertEq(acct.status(), 1);
        assertFalse(acct.cancelRequested());

        _asOwner();
        acct.cancelSubscription();
        vm.warp(acct.paidUntil());
        assertEq(acct.status(), 3);
        _asOwner();
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.undoCancel();

        // Expired --subscribe--> Active, with a fresh first fee.
        _giveCusd(address(acct), ANNUAL);
        _subscribe(A);
        assertEq(acct.status(), 1);
        assertFalse(acct.cancelRequested());
        assertEq(acct.paidUntil(), block.timestamp + 365 days);
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.returnAsset(address(cusd));
    }

    function test_cancelWhilePaymentDue_expiresAtOnce_noForcedSaleCanFollow() public {
        _subscribedMonthly(1e18);
        btcb.mint(address(acct), 1e18);
        _toSaleAllowed();
        uint256 collected = cusd.balanceOf(address(collector));

        _asOwner();
        acct.cancelSubscription();
        assertEq(acct.status(), 3, "Expired at once");

        _saleReverts(ConfioSmartAccount.BadState.selector, _legs(_cryptoLeg(btcb, BTC_PRICE, CUSD_, 14e18)), 0);
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.collectFee();

        vm.prank(eve);
        acct.returnAsset(address(btcb));
        vm.prank(eve);
        acct.returnAsset(address(cusd));
        assertEq(btcb.balanceOf(alice), 1e18);
        assertEq(cusd.balanceOf(alice), 1e18);
        assertEq(cusd.balanceOf(address(collector)), collected, "the lapsed period is not charged");
    }

    /// I-5: a notice started under one subscription does not survive cancel
    /// and re-subscribe.
    function test_noticeDoesNotSurviveCancelAndResubscribe() public {
        _subscribedMonthly(0);
        btcb.mint(address(acct), 1e18);
        _toSaleAllowed();
        assertTrue(acct.noticeStartedAt() != 0);
        _asOwner();
        acct.cancelSubscription();

        _giveCusd(address(acct), MONTHLY);
        _subscribe(M);
        assertEq(acct.noticeStartedAt(), 0);
        assertEq(acct.forcedSaleForPeriod(), 0);

        vm.warp(acct.paidUntil());
        _freshFeeds();
        IConfioSmartAccount.SaleLeg[] memory legs = _legs(_cryptoLeg(btcb, BTC_PRICE, CUSD_, MONTHLY + 0.01e18));
        _saleReverts(ConfioSmartAccount.BadState.selector, legs, 0);
        _asRelayer();
        acct.startPaymentNotice();
        vm.warp(block.timestamp + 7 days - 1);
        _freshFeeds();
        _saleReverts(ConfioSmartAccount.BadState.selector, legs, 0);
        vm.warp(block.timestamp + 1);
        _freshFeeds();
        _sale(legs, 0, address(0), 0);
    }

    // ── relayerPaused (I-15) ────────────────────────────────────────────

    function test_relayerPaused_blocksOnlyRelayerFunctions() public {
        _subscribedMonthly(30e18);
        _withBeneficiary();
        usdt.mint(address(acct), 1e18);
        IConfioSmartAccount.RuleInput memory r = _rule(IConfioSmartAccount.RuleKind.Send, address(cusd), 1e18);
        r.payee = carol;
        _asOwner();
        uint256 id = acct.createRule(r);
        vm.prank(safe);
        factory.setRelayerPaused(true);
        bytes4 paused = ConfioSmartAccount.RelayerPaused.selector;

        vm.startPrank(relayer, relayer);
        vm.expectRevert(paused);
        acct.executeRule(id, abi.encode(CUSD_, uint256(0)), address(0), 0);
        vm.expectRevert(paused);
        acct.convertUsdt(CUSD_, 0.99e18, address(0), 0);
        vm.stopPrank();
        vm.warp(acct.paidUntil());
        vm.startPrank(relayer, relayer);
        vm.expectRevert(paused);
        acct.collectFee();
        vm.expectRevert(paused);
        acct.startPaymentNotice();
        vm.expectRevert(paused);
        acct.forcedSale(new IConfioSmartAccount.SaleLeg[](0), 0, address(0), 0);
        vm.stopPrank();

        // Owner, beneficiary and permissionless functions all work.
        address[] memory tokens = new address[](1);
        tokens[0] = address(usdt);
        _asOwner();
        acct.withdraw(address(cusd), 1e18);
        _asOwner();
        acct.withdrawAll(tokens);
        _asOwner();
        acct.cancelClaim();
        vm.prank(bob, bob);
        acct.initiateClaim();
        vm.warp(block.timestamp + 90 days);
        vm.prank(bob, bob);
        acct.executeClaim();
        assertEq(acct.owner(), bob);

        ConfioSmartAccount other = _create(carol);
        _giveCusd(address(other), 20e18);
        vm.prank(carol, relayer);
        other.subscribe(M, type(uint256).max);
        // A designation needs a relayer approval, and the relayer is paused:
        // designation and acceptance are relay-gated by design (I-18).
        vm.prank(relayer, relayer);
        vm.expectRevert(bytes("relayer paused"));
        factory.approveDesignation(address(other), bob, 90 days);
        vm.startPrank(carol, relayer);
        vm.expectRevert(ConfioSmartAccount.NotApproved.selector);
        other.setBeneficiary(bob, 90 days);
        other.removeBeneficiary();
        other.cancelSubscription();
        vm.stopPrank();
        vm.warp(other.paidUntil());
        vm.prank(eve);
        other.returnAsset(address(cusd));
        assertEq(cusd.balanceOf(carol), 20e18 - MONTHLY);
    }
}
