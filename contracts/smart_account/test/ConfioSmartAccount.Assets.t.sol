// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ConfioStockRouter} from "ondo-stocks/ConfioStockRouter.sol";
import {ConfioSwapRouter} from "crypto-swap/ConfioSwapRouter.sol";
import {ConfioSmartAccount, ISmartAccountStockRouter, ISmartAccountSwapRouter} from "../ConfioSmartAccount.sol";
import {IConfioSmartAccount} from "../interfaces/IConfioSmartAccount.sol";
import {SmartAccountBase} from "./Base.t.sol";

contract ArmingStranger {
    function arm(address vault, address referrer, uint256 shareBps) external {
        (bool ok, bytes memory ret) =
            vault.call(abi.encodeWithSignature("armReferral(address,uint256)", referrer, shareBps));
        if (!ok) {
            assembly {
                revert(add(ret, 32), mload(ret))
            }
        }
    }
}

/// Spec 10.2: trade, withdrawals, USDT conversion (decision 31), the fee
/// referral (decision 32) and the "death with only bitcoin" scenario.
contract ConfioSmartAccountAssetsTest is SmartAccountBase {
    IConfioSmartAccount.Plan constant M = IConfioSmartAccount.Plan.Monthly;

    event Traded(
        address indexed venue, address indexed tokenIn, address indexed tokenOut, uint256 amountIn, uint256 amountOut
    );
    event UsdtConverted(uint8 dollar, uint256 usdtIn, uint256 dollarsOut);

    function _trade(address venue, bytes memory data, address tokenIn, address tokenOut, uint256 maxIn, uint256 minOut)
        internal
    {
        vm.prank(alice, relayer);
        acct.trade(venue, data, tokenIn, tokenOut, maxIn, minOut);
    }

    function _tradeReverts(bytes4 err, address venue, bytes memory data, address tokenIn, address tokenOut) internal {
        vm.prank(alice, relayer);
        vm.expectRevert(err);
        acct.trade(venue, data, tokenIn, tokenOut, 100e18, 1);
    }

    // ── selectors ───────────────────────────────────────────────────────

    /// The account derives its allowed selectors from its own copies of the
    /// router signatures. They must be the real routers' selectors.
    function test_selectors_matchTheRealRouters() public pure {
        assertEq(ISmartAccountStockRouter.buyWithSavings.selector, ConfioStockRouter.buyWithSavings.selector);
        assertEq(ISmartAccountStockRouter.sellToSavings.selector, ConfioStockRouter.sellToSavings.selector);
        assertEq(ISmartAccountSwapRouter.buy.selector, ConfioSwapRouter.buy.selector);
        assertEq(ISmartAccountSwapRouter.sell.selector, ConfioSwapRouter.sell.selector);
    }

    // ── withdraw ────────────────────────────────────────────────────────

    function test_withdraw_paysOwnerOnly_inAnyLifecycleState() public {
        // Unsubscribed: an account can hold and release assets.
        _giveCusd(address(acct), 50e18);
        btcb.mint(address(acct), 1e18);
        vm.prank(alice, alice);
        acct.withdraw(address(cusd), 10e18);
        assertEq(cusd.balanceOf(alice), 10e18);

        _subscribe(M);
        address[] memory tokens = new address[](2);
        tokens[0] = address(cusd);
        tokens[1] = address(btcb);
        _asOwner();
        acct.withdrawAll(tokens);
        assertEq(cusd.balanceOf(alice), 50e18 - MONTHLY);
        assertEq(btcb.balanceOf(alice), 1e18);
        assertEq(cusd.balanceOf(address(acct)), 0);

        // The three-argument forms are for an inherited account only.
        _asOwner();
        vm.expectRevert(ConfioSmartAccount.NotInherited.selector);
        acct.withdraw(address(cusd), 0, alice);
        _asOwner();
        vm.expectRevert(ConfioSmartAccount.NotInherited.selector);
        acct.withdrawAll(tokens, alice);

        vm.prank(eve);
        vm.expectRevert(ConfioSmartAccount.NotOwner.selector);
        acct.withdraw(address(cusd), 0);
    }

    /// Balance reads go through a raw staticcall (size audit): a "token"
    /// with no code, or one that answers less than a word, still reverts
    /// the call as a typed call would, and moves nothing.
    function test_withdrawAll_ofANonContractOrShortAnsweringToken_reverts() public {
        _giveCusd(address(acct), 5e18);
        address[] memory tokens = new address[](2);
        tokens[0] = address(cusd);
        tokens[1] = eve;
        _asOwner();
        vm.expectRevert();
        acct.withdrawAll(tokens);
        tokens[1] = address(new ArmingStranger()); // code, but no balanceOf
        _asOwner();
        vm.expectRevert();
        acct.withdrawAll(tokens);
        assertEq(cusd.balanceOf(address(acct)), 5e18);
    }

    function test_account_cannotReceiveBnb() public {
        vm.deal(eve, 1 ether);
        vm.prank(eve);
        (bool ok,) = address(acct).call{value: 1}("");
        assertFalse(ok);
    }

    // ── trade (4.6) ─────────────────────────────────────────────────────

    function test_trade_stockBuyAndSell() public {
        _subscribedMonthly(0);
        _givePlus(address(acct), 400e18);
        bytes memory buy = _stockBuyData(address(tsla), 300e18, 10_000);
        vm.expectEmit(true, true, true, false, address(acct));
        emit Traded(address(stockRouter), address(plus), address(tsla), 0, 0);
        _trade(address(stockRouter), buy, address(plus), address(tsla), 300e18, 0.9e18);
        uint256 stock = tsla.balanceOf(address(acct));
        assertGt(stock, 0.98e18);
        assertEq(plus.balanceOf(address(acct)), 100e18);
        _noAllowances(address(acct));

        bytes memory sell = _stockSellData(address(tsla), stock);
        _trade(address(stockRouter), sell, address(tsla), address(plus), stock, 290e18);
        assertEq(tsla.balanceOf(address(acct)), 0);
        assertGt(plus.balanceOf(address(acct)), 390e18);
        _noAllowances(address(acct));
    }

    function test_trade_bitcoinAndGold_fromBothDollars() public {
        _subscribedMonthly(100e18);
        _givePlus(address(acct), 100e18);
        _trade(address(swapRouter), _swapBuyData(CUSD_, address(btcb), 50e18), address(cusd), address(btcb), 50e18, 1);
        _trade(address(swapRouter), _swapBuyData(PLUS, address(xaut), 50e18), address(plus), address(xaut), 50e18, 1);
        uint256 btc = btcb.balanceOf(address(acct));
        uint256 gold = xaut.balanceOf(address(acct));
        assertGt(btc, 0);
        assertGt(gold, 0);
        _trade(address(swapRouter), _swapSellData(PLUS, address(btcb), btc), address(btcb), address(plus), btc, 1);
        _trade(address(swapRouter), _swapSellData(CUSD_, address(xaut), gold), address(xaut), address(cusd), gold, 1);
        assertEq(btcb.balanceOf(address(acct)), 0);
        assertEq(xaut.balanceOf(address(acct)), 0);
        _noAllowances(address(acct));
    }

    function test_trade_guards() public {
        _subscribedMonthly(100e18);
        _givePlus(address(acct), 100e18);
        // Not a venue.
        _tradeReverts(
            ConfioSmartAccount.BadVenue.selector,
            eve,
            _swapBuyData(CUSD_, address(btcb), 1e18),
            address(cusd),
            address(btcb)
        );
        _tradeReverts(
            ConfioSmartAccount.BadVenue.selector,
            address(cusd),
            abi.encodeWithSignature("transfer(address,uint256)", eve, 1e18),
            address(cusd),
            address(btcb)
        );
        // Through the swap router only a token with a feed constant.
        _tradeReverts(
            ConfioSmartAccount.BadToken.selector,
            address(swapRouter),
            _swapBuyData(CUSD_, address(confio), 1e18),
            address(cusd),
            address(confio)
        );
        _tradeReverts(
            ConfioSmartAccount.BadToken.selector,
            address(swapRouter),
            _swapSellData(CUSD_, address(tsla), 1e18),
            address(tsla),
            address(cusd)
        );
        // The pair in the calldata is what counts, not the arguments.
        _tradeReverts(
            ConfioSmartAccount.BadCall.selector,
            address(swapRouter),
            _swapBuyData(CUSD_, address(confio), 1e18),
            address(cusd),
            address(btcb)
        );
        _tradeReverts(
            ConfioSmartAccount.BadCall.selector,
            address(swapRouter),
            _swapBuyData(PLUS, address(btcb), 1e18),
            address(cusd),
            address(btcb)
        );
        // Selectors outside the allowlist: sellToUsdt, sweep, anything.
        bytes memory sellToUsdt =
            abi.encodeCall(ConfioStockRouter.sellToUsdt, (_quote(address(tsla), 1e18, STOCK_PRICE, 1), "", 1, 1, 90));
        _tradeReverts(
            ConfioSmartAccount.BadCall.selector, address(stockRouter), sellToUsdt, address(tsla), address(usdt)
        );
        _tradeReverts(
            ConfioSmartAccount.BadCall.selector,
            address(swapRouter),
            abi.encodeWithSignature("sweep(address,address,uint256)", address(cusd), eve, 1),
            address(cusd),
            address(btcb)
        );
        _tradeReverts(ConfioSmartAccount.BadCall.selector, address(swapRouter), hex"", address(cusd), address(btcb));
        // Floor on what the account receives.
        bytes memory buy = _swapBuyData(CUSD_, address(btcb), 10e18);
        vm.prank(alice, relayer);
        vm.expectRevert(ConfioSmartAccount.Slippage.selector);
        acct.trade(address(swapRouter), buy, address(cusd), address(btcb), 10e18, 1e18);
        // The approval is maxIn: a venue call that wants more fails.
        vm.prank(alice, relayer);
        vm.expectRevert();
        acct.trade(address(swapRouter), buy, address(cusd), address(btcb), 10e18 - 1, 1);
        // Not relay-originated: the routers themselves refuse.
        vm.prank(alice, alice);
        vm.expectRevert(bytes("not sponsored"));
        acct.trade(address(swapRouter), buy, address(cusd), address(btcb), 10e18, 1);
        _noAllowances(address(acct));
    }

    // ── USDT (decision 31, N6) ──────────────────────────────────────────

    function test_convertUsdt_excessFromAStockBuy_becomesCusdPlus() public {
        _subscribedMonthly(0);
        _givePlus(address(acct), 300e18);
        // 2% of the redeemed USDT is not spent and comes back as USDT.
        _trade(
            address(stockRouter), _stockBuyData(address(tsla), 300e18, 9_800), address(plus), address(tsla), 300e18, 1
        );
        uint256 usdtIn = usdt.balanceOf(address(acct));
        assertGt(usdtIn, 5e18, "USDT excess arrived");
        uint256 sharesBefore = plus.balanceOf(address(acct));
        uint256 floor = (usdtIn * (10_000 - 90 - 50)) / 10_000;

        // Only the relayer.
        vm.prank(alice, relayer);
        vm.expectRevert(ConfioSmartAccount.NotRelayer.selector);
        acct.convertUsdt(PLUS, floor, address(0), 0);
        // Never below the fee-adjusted floor.
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.Slippage.selector);
        acct.convertUsdt(PLUS, floor - 1, address(0), 0);
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.Slippage.selector);
        acct.convertUsdt(PLUS, 0, address(0), 0);
        // A floor the conversion cannot meet.
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.Slippage.selector);
        acct.convertUsdt(PLUS, usdtIn, address(0), 0);
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.BadCall.selector);
        acct.convertUsdt(2, floor, address(0), 0);

        _asRelayer();
        acct.convertUsdt(PLUS, floor, address(0), 0);
        assertEq(usdt.balanceOf(address(acct)), 0, "the whole balance");
        uint256 gained = plus.balanceOf(address(acct)) - sharesBefore;
        assertApproxEqAbs((gained * plus.pPlus()) / 1e18, usdtIn - cusd.feeFor(usdtIn), 1e6, "normal 0.9% entry");
        assertEq(cusd.balanceOf(address(acct)), 0, "never the other dollar");
        _noAllowances(address(acct));

        // Nothing left to convert.
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.BadAmount.selector);
        acct.convertUsdt(PLUS, 0, address(0), 0);
    }

    function test_convertUsdt_directTransfer_becomesCusd_recipientIsTheAccount() public {
        _subscribedMonthly(0);
        usdt.mint(address(acct), 100e18);
        vm.expectEmit(false, false, false, true, address(acct));
        emit UsdtConverted(CUSD_, 100e18, 99.1e18);
        _asRelayer();
        acct.convertUsdt(CUSD_, 99.1e18, address(0), 0);
        assertEq(cusd.balanceOf(address(acct)), 99.1e18);
        assertEq(cusd.balanceOf(relayer) + cusd.balanceOf(alice), 0, "never to another recipient");
        assertEq(plus.balanceOf(address(acct)), 0);
        _noAllowances(address(acct));
    }

    /// A USDT deposit into an unpaid account converts and then pays the fee.
    function test_convertUsdt_curesAMissedPayment() public {
        _subscribedMonthly(0);
        vm.warp(acct.paidUntil());
        _asRelayer();
        acct.startPaymentNotice();
        usdt.mint(address(acct), 20e18);
        _asRelayer();
        acct.convertUsdt(CUSD_, 19.75e18, address(0), 0);
        _asRelayer();
        acct.collectFee();
        assertEq(acct.billingStatus(), 0);
        assertEq(cusd.balanceOf(address(acct)), 19.82e18 - MONTHLY);
    }

    function test_convertUsdt_notOnUnsubscribedOrExpired() public {
        usdt.mint(address(acct), 10e18);
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.convertUsdt(CUSD_, 9.9e18, address(0), 0);
        // The owner can always take raw USDT out.
        vm.prank(alice, alice);
        acct.withdraw(address(usdt), 10e18);
        assertEq(usdt.balanceOf(alice), 10e18);
    }

    function test_usdonDust_isWithdrawable() public {
        usdon.mint(address(acct), 112);
        vm.prank(alice, alice);
        acct.withdraw(address(usdon), 112);
        assertEq(usdon.balanceOf(alice), 112);
    }

    // ── fee referral (decision 32) ──────────────────────────────────────

    function test_referral_paidOnARuleBuy() public {
        _subscribedMonthly(100e18);
        IConfioSmartAccount.RuleInput memory r = _rule(IConfioSmartAccount.RuleKind.Buy, address(cusd), 50e18);
        r.tokenOut = address(btcb);
        _asOwner();
        uint256 id = acct.createRule(r);
        bytes memory data = abi.encode(address(swapRouter), _swapBuyData(CUSD_, address(btcb), 50e18), uint256(1));
        _asRelayer();
        acct.executeRule(id, data, referrer, 5_000);
        // 0.9% of 50 = 0.45, half to the referrer, as cUSD.
        assertEq(cusd.balanceOf(referrer), 0.225e18);
        assertEq(cusd.accruedExitFees(), 0.225e18);
    }

    function test_referral_paidOnAForcedSale() public {
        _subscribedMonthly(0);
        btcb.mint(address(acct), 1e18);
        _toSaleAllowed();
        uint256 entryBefore = cusd.accruedEntryFees();
        _sale(_legs(_cryptoLeg(btcb, BTC_PRICE, CUSD_, MONTHLY + 0.01e18)), 0, referrer, 5_000);
        assertGt(cusd.balanceOf(referrer), 0.06e18);
        assertApproxEqAbs(cusd.accruedEntryFees() - entryBefore, cusd.balanceOf(referrer), 1, "half each");
    }

    function test_referral_paidOnAUsdtConversion() public {
        _subscribedMonthly(0);
        usdt.mint(address(acct), 100e18);
        _asRelayer();
        acct.convertUsdt(PLUS, 98.7e18, referrer, 5_000);
        assertEq(cusd.balanceOf(referrer), 0.45e18);
    }

    function test_referral_withoutReferrer_vaultKeepsTheWholeFee() public {
        _subscribedMonthly(0);
        usdt.mint(address(acct), 100e18);
        uint256 before = cusd.accruedEntryFees();
        _asRelayer();
        acct.convertUsdt(CUSD_, 99.1e18, address(0), 5_000);
        assertEq(cusd.accruedEntryFees() - before, 0.9e18);
        assertEq(cusd.balanceOf(referrer), 0);
    }

    function test_referral_ownerCannotBeTheirOwnReferrer() public {
        _subscribedMonthly(0);
        usdt.mint(address(acct), 100e18);
        _asRelayer();
        vm.expectRevert(ConfioSmartAccount.SelfReferral.selector);
        acct.convertUsdt(CUSD_, 99.1e18, alice, 5_000);
    }

    function test_referral_arbitraryContractAndUnrecognisedFactoryCannotArm() public {
        ArmingStranger stranger = new ArmingStranger();
        vm.prank(relayer, relayer);
        vm.expectRevert(bytes("not a Confio account"));
        stranger.arm(address(cusd), referrer, 5_000);

        // The Safe withdraws recognition: accounts can no longer arm.
        vm.prank(safe);
        cusd.setSmartAccountFactory(address(factory), false);
        _subscribedMonthly(0);
        usdt.mint(address(acct), 100e18);
        _asRelayer();
        vm.expectRevert(bytes("not a Confio account"));
        acct.convertUsdt(CUSD_, 99.1e18, referrer, 5_000);
        // Without a referrer the conversion is unaffected.
        _asRelayer();
        acct.convertUsdt(CUSD_, 99.1e18, address(0), 0);
    }

    // ── death with only bitcoin (decisions 6 to 9; I-5, I-8) ────────────

    function test_deathWithOnlyBitcoin() public {
        _subscribedMonthly(0);
        _withBeneficiary();
        btcb.mint(address(acct), 0.01e18); // US$1,000
        uint256 claimExecutableAt;

        // The owner never signs again. Each period: notice, wait, a forced
        // sale of one fee's worth, fee collected.
        for (uint256 period = 0; period < 4; ++period) {
            vm.warp(acct.paidUntil());
            _asRelayer();
            acct.startPaymentNotice();
            if (period == 0) {
                // The beneficiary initiates during the first unpaid period.
                vm.prank(bob, bob);
                acct.initiateClaim();
                claimExecutableAt = acct.claimExecutableAt();
            }
            vm.warp(vm.getBlockTimestamp() + 7 days);
            _freshFeeds();
            uint256 shortfall = MONTHLY - acct.dollarsUsd();
            uint256 btcBefore = btcb.balanceOf(address(acct));
            _sale(_legs(_cryptoLeg(btcb, BTC_PRICE, PLUS, shortfall + 0.01e18)), shortfall, address(0), 0);
            uint256 sold = btcBefore - btcb.balanceOf(address(acct));
            // One fee's worth, not more: about US$15.1 of US$100,000 bitcoin.
            assertLt(sold, 0.00017e18);
            assertEq(acct.billingStatus(), 0);
            // Fees and sales do not cancel the claim (I-8, decision 25).
            assertEq(acct.claimExecutableAt(), claimExecutableAt);
            assertEq(acct.claimStatus() > 0, true);
            assertEq(
                btcb.balanceOf(alice) + cusd.balanceOf(alice) + plus.balanceOf(alice), 0, "nothing to the old owner"
            );
        }

        // Four periods of 37 days have passed: the window is over.
        assertGe(vm.getBlockTimestamp(), claimExecutableAt);
        vm.prank(bob, bob);
        acct.executeClaim();
        uint256 remaining = btcb.balanceOf(address(acct));
        assertGt(remaining, 0.0093e18);
        vm.prank(bob, bob);
        acct.withdraw(address(btcb), remaining, bob);
        assertEq(btcb.balanceOf(bob), remaining);
        assertEq(btcb.balanceOf(alice) + cusd.balanceOf(alice) + plus.balanceOf(alice), 0);
        assertGt(plus.balanceOf(address(collector)), 0);
    }
}
