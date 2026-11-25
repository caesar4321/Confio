// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {GmQuote} from "ondo-stocks/ConfioStockRouter.sol";
import {SmartAccountV2Base} from "./ConfioSmartAccountV2.t.sol";
import {ConfioSmartAccountV2} from "../ConfioSmartAccountV2.sol";
import {IConfioSmartAccountV2} from "../interfaces/IConfioSmartAccountV2.sol";
import {IConfioSmartAccount} from "../interfaces/IConfioSmartAccount.sol";

/// What a Safe upgrade of the stock router proxy could install: takes the
/// whole quantity, pays back 1 wei of cUSD+.
contract EvilStockRouterImpl is UUPSUpgradeable {
    address immutable PLUS;
    address immutable THIEF;

    constructor(address plus_, address thief_) {
        PLUS = plus_;
        THIEF = thief_;
    }

    function _authorizeUpgrade(address) internal override {}

    function sellToSavings(GmQuote calldata quote, bytes calldata, uint256, uint256, uint256)
        external
        returns (uint256)
    {
        IERC20(quote.asset).transferFrom(msg.sender, THIEF, quote.quantity);
        IERC20(PLUS).transfer(msg.sender, 1);
        return 1;
    }
}

/// Regression tests for the independent audit of v2 (2026-11-25). Each
/// proof of concept is kept, asserting that the attack now FAILS (or, for
/// decisions kept by the founder, the exact documented behaviour).
contract AuditV2RegressionTest is SmartAccountV2Base {
    address thief = makeAddr("thief");

    /// M1: a whole BTCB holding can no longer be sold on a $1 rule: sells
    /// count at the feed value of what goes out.
    function test_audit_M1_sellBeyondTheBucketReverts() public {
        _danaSubscribed(0, 0);
        uint256 id = _tradeRule(address(cusd), address(0), 1e18); // $1/week cap
        uint256 btc = 2e17; // 0.2 BTC = $20,000
        btcb.mint(address(a2), btc);
        dex.setHaircutBps(140);
        _relayTradeReverts(
            ConfioSmartAccountV2.CapExceeded.selector, id, address(swapRouter), _swapSellData(CUSD_, address(btcb), btc), btc
        );
        assertEq(btcb.balanceOf(address(a2)), btc);
        // Repeating after the min gap does not help either.
        _skip(61);
        _relayTradeReverts(
            ConfioSmartAccountV2.CapExceeded.selector, id, address(swapRouter), _swapSellData(CUSD_, address(btcb), btc), btc
        );
    }

    /// H1: relayer + a Safe upgrade of the stock router can no longer sell
    /// stock for 1 wei at an honest quote price: dollars received are held
    /// to the quote value (and the value counts in the bucket).
    function test_audit_H1_safeRouterUpgradePlusRelayer_cannotDrainStock() public {
        _danaSubscribed(0, 0);
        uint256 id = _tradeRule(address(cusd), address(0), 100_000e18); // even a huge cap
        tsla.mint(address(a2), 50e18);
        EvilStockRouterImpl evil = new EvilStockRouterImpl(address(plus), thief);
        _givePlus(address(stockRouter), 10);
        vm.prank(safe);
        UUPSUpgradeable(address(stockRouter)).upgradeToAndCall(address(evil), "");
        _relayTradeReverts(
            ConfioSmartAccountV2.BelowFeed.selector, id, address(stockRouter), _stockSellData(address(tsla), 50e18), 50e18
        );
        assertEq(tsla.balanceOf(thief), 0);
        assertEq(tsla.balanceOf(address(a2)), 50e18);
        // On a $1 rule as well (the price check comes before the bucket).
        uint256 small = _tradeRule(address(cusd), address(0), 1e18);
        _relayTradeReverts(
            ConfioSmartAccountV2.BelowFeed.selector, small, address(stockRouter), _stockSellData(address(tsla), 50e18), 50e18
        );
    }

    /// M3 (kept by decision, "en promedio"): one gap can admit just under two
    /// caps, never more than cap * (1 + d / gap) over a span d.
    function test_audit_M3_bucket_boundIsCapTimesOnePlusDOverGap() public {
        _danaSubscribed(5_000e18, 0);
        uint256 id = _tradeRule(address(cusd), address(0), CAP);
        uint256 t0 = vm.getBlockTimestamp();
        _buyBtc(id, CAP);
        _skip(WEEK - 60);
        (uint256 used,) = a2.bucketOf(id);
        uint256 room = CAP - used;
        _buyBtc(id, room);
        uint256 d = vm.getBlockTimestamp() - t0;
        assertLt(d, WEEK);
        assertLe((CAP + room) * WEEK, CAP * WEEK + CAP * d, "documented bound");
        assertLt(CAP + room, 2 * CAP);
    }

    /// L5: no silent uint192 truncation of the bucket.
    function test_audit_L5_bucketNeverTruncates() public {
        _danaSubscribed(0, 0);
        uint256 huge = uint256(1) << 200;
        uint256 id = _purchaseRule(address(cusd), huge);
        vm.prank(relayer, relayer);
        vm.expectRevert(ConfioSmartAccountV2.CapExceeded.selector);
        a2.relayPurchase(id, bytes32("o"), merchant, uint256(1) << 192, 0, vm.getBlockTimestamp() + 1, "ok");
        (uint256 used, uint256 lastAt) = a2.bucketOf(id);
        assertEq(used + lastAt, 0);
    }

    /// L4: a pending changePlan on the old account is now carried.
    function test_audit_L4_migrate_carriesNextPlan() public {
        _subscribedMonthly(0);
        vm.startPrank(alice, relayer);
        acct.changePlan(IConfioSmartAccount.Plan.Annual);
        acct.cancelSubscription();
        address moved = factory.migrate();
        vm.stopPrank();
        assertEq(uint8(ConfioSmartAccountV2(moved).nextPlan()), uint8(IConfioSmartAccountV2.Plan.Annual));
        assertEq(uint8(ConfioSmartAccountV2(moved).plan()), uint8(IConfioSmartAccountV2.Plan.Monthly));
    }

    /// Known, documented (v1 cannot be changed): after migrate the old v1
    /// account can undo its cancel, so both are Active until paidUntil. The
    /// leak is the unused rest of one period, once per upgrade; both renew
    /// (and are charged) separately afterwards.
    function test_audit_known_oldAccountUndoCancelAfterMigrate() public {
        _subscribedMonthly(0);
        vm.startPrank(alice, relayer);
        acct.cancelSubscription();
        address moved = factory.migrate();
        acct.undoCancel();
        vm.stopPrank();
        assertEq(acct.status(), 1);
        assertEq(ConfioSmartAccountV2(moved).status(), 1);
        assertEq(ConfioSmartAccountV2(moved).paidUntil(), acct.paidUntil());
        // migrate cannot be repeated for a second free copy.
        vm.prank(alice);
        vm.expectRevert(bytes("already current"));
        factory.migrate();
    }
}
