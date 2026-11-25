// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {ConfioStockRouter} from "ondo-stocks/ConfioStockRouter.sol";
import {ConfioSwapRouter} from "crypto-swap/ConfioSwapRouter.sol";
import {SmartAccountBase} from "./Base.t.sol";
import {MockToken, EvilSwapRouter, SponsorContract} from "./Mocks.sol";
import {ConfioSmartAccount} from "../ConfioSmartAccount.sol";
import {ConfioSmartAccountV2} from "../ConfioSmartAccountV2.sol";
import {ConfioSmartAccountFactory} from "../ConfioSmartAccountFactory.sol";
import {IConfioSmartAccount} from "../interfaces/IConfioSmartAccount.sol";
import {IConfioSmartAccountV2} from "../interfaces/IConfioSmartAccountV2.sol";

interface IAccountOwner {
    function owner() external view returns (address);
}

interface IIsAccount {
    function isAccount(address) external view returns (bool);
}

/// ConfioMarketEscrow.depositFrom as the escrow builder specifies it: the
/// caller must be a factory account owned by `buyer`; pulls exactly `amount`;
/// refunds go to the paying account. authSig "ok" stands for the backend's
/// order signature.
contract MockEscrow {
    IIsAccount public factory;
    mapping(bytes32 => address) public refundToOf;
    mapping(bytes32 => address) public buyerOf;
    mapping(bytes32 => address) public merchantOf;
    mapping(bytes32 => address) public tokenOf;
    mapping(bytes32 => uint256) public amountOf;

    constructor(address factory_) {
        factory = IIsAccount(factory_);
    }

    function depositFrom(
        bytes32 orderId,
        address buyer,
        address merchant,
        address token,
        uint256 amount,
        uint16 feeBps,
        uint256 deadline,
        bytes calldata authSig
    ) external {
        require(factory.isAccount(msg.sender), "not account");
        require(buyer != address(0) && IAccountOwner(msg.sender).owner() == buyer, "not account owner");
        require(merchant != buyer && merchant != address(0), "bad merchant");
        require(keccak256(authSig) == keccak256("ok"), "bad authorization");
        require(block.timestamp <= deadline, "expired");
        require(feeBps <= 1000, "fee");
        require(amountOf[orderId] == 0, "order exists");
        refundToOf[orderId] = msg.sender;
        buyerOf[orderId] = buyer;
        merchantOf[orderId] = merchant;
        tokenOf[orderId] = token;
        amountOf[orderId] = amount;
        uint256 before = IERC20(token).balanceOf(address(this));
        require(IERC20(token).transferFrom(msg.sender, address(this), amount), "pull");
        require(IERC20(token).balanceOf(address(this)) - before == amount, "mismatch");
    }

    function refund(bytes32 orderId) external {
        uint256 amount = amountOf[orderId];
        amountOf[orderId] = 0;
        require(IERC20(tokenOf[orderId]).transfer(refundToOf[orderId], amount), "refund");
    }
}

/// v2 fixture: the v1 factory of SmartAccountBase (alice holds a v1
/// account) is upgraded by the Safe to the hands-off factory with a v2
/// implementation; dana opens a v2 account afterwards.
abstract contract SmartAccountV2Base is SmartAccountBase {
    uint256 constant CAP = 1_000e18;
    uint256 constant WEEK = 7 days;

    MockEscrow escrow;
    ConfioSmartAccountV2 implV2;
    ConfioSmartAccount implV1;
    ConfioSmartAccountV2 a2;
    address dana = makeAddr("dana");
    address merchant = makeAddr("merchant");
    uint256 orderNonce;

    function setUp() public virtual override {
        super.setUp();
        implV1 = implementation;
        escrow = new MockEscrow(address(factory));
        implV2 = _newImplementationV2(address(factory));
        _upgradeFactory();
        vm.prank(dana);
        a2 = ConfioSmartAccountV2(factory.createAccount());
    }

    function _newImplementationV2(address factory_) internal returns (ConfioSmartAccountV2) {
        return new ConfioSmartAccountV2(
            factory_,
            address(cusd),
            address(plus),
            address(usdt),
            address(confio),
            address(stockRouter),
            address(swapRouter),
            address(collector),
            address(btcb),
            address(btcFeed),
            address(xaut),
            address(xauFeed),
            address(escrow)
        );
    }

    function _upgradeFactory() internal {
        ConfioSmartAccountFactory logic = _newFactoryLogic();
        vm.prank(safe);
        factory.upgradeToAndCall(address(logic), abi.encodeCall(ConfioSmartAccountFactory.initializeV2, (address(implV2))));
    }

    // ── dana's v2 account ──

    function _danaSubscribed(uint256 cusdExtra, uint256 plusUsd) internal {
        _giveCusd(address(a2), MONTHLY + cusdExtra);
        if (plusUsd > 0) _givePlusUsd(address(a2), plusUsd);
        vm.prank(dana, relayer);
        a2.subscribe(IConfioSmartAccountV2.Plan.Monthly, type(uint256).max);
    }

    function _input(IConfioSmartAccountV2.RuleKind kind, address tokenIn, address tokenOut, address payee, uint256 cap)
        internal
        pure
        returns (IConfioSmartAccountV2.RuleInput memory r)
    {
        r.kind = kind;
        r.frequency = IConfioSmartAccountV2.Frequency.Weekly;
        r.tokenIn = tokenIn;
        r.tokenOut = tokenOut;
        r.payee = payee;
        r.amountUsd = cap;
    }

    function _danaRule(IConfioSmartAccountV2.RuleInput memory input) internal returns (uint256 id) {
        vm.prank(dana, relayer);
        id = a2.createRule(input);
    }

    function _tradeRule(address tokenIn, address pinned, uint256 cap) internal returns (uint256) {
        return _danaRule(_input(IConfioSmartAccountV2.RuleKind.Trade, tokenIn, pinned, address(0), cap));
    }

    function _purchaseRule(address tokenIn, uint256 cap) internal returns (uint256) {
        return _danaRule(_input(IConfioSmartAccountV2.RuleKind.Purchase, tokenIn, address(0), address(escrow), cap));
    }

    function _relayTrade(uint256 id, address venue, bytes memory data, uint256 maxIn) internal {
        vm.prank(relayer, relayer);
        a2.relayTrade(id, venue, data, maxIn, 1);
    }

    function _relayTradeReverts(bytes4 err, uint256 id, address venue, bytes memory data, uint256 maxIn) internal {
        vm.prank(relayer, relayer);
        vm.expectRevert(err);
        a2.relayTrade(id, venue, data, maxIn, 1);
    }

    function _buyBtc(uint256 id, uint256 usd) internal {
        _relayTrade(id, address(swapRouter), _swapBuyData(CUSD_, address(btcb), usd), usd);
    }

    function _purchase(uint256 id, uint256 amount) internal returns (bytes32 orderId) {
        orderId = keccak256(abi.encode(++orderNonce));
        uint256 deadline = vm.getBlockTimestamp() + 1 hours;
        vm.prank(relayer, relayer);
        a2.relayPurchase(id, orderId, merchant, amount, 250, deadline, "ok");
    }

    function _skip(uint256 secs) internal {
        vm.warp(vm.getBlockTimestamp() + secs);
        _freshFeeds();
    }
}

contract ConfioSmartAccountV2Test is SmartAccountV2Base {
    event RelayTraded(
        uint256 indexed id,
        address indexed venue,
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 amountOut,
        uint256 usdCounted
    );
    event RelayPurchased(uint256 indexed id, bytes32 indexed orderId, uint256 amount, uint256 usdCounted);

    // ═════════════════════════ Factory upgrade ═══════════════════════════

    function test_upgrade_keepsStateAndListsBothImplementations() public {
        assertEq(factory.implementation(), address(implV2));
        assertEq(factory.implementationCount(), 2);
        assertEq(factory.implementationAt(0), address(implV1));
        assertEq(factory.implementationAt(1), address(implV2));
        // Pre-upgrade state is intact.
        assertEq(factory.accountOf(alice), address(acct));
        assertTrue(factory.isAccount(address(acct)));
        assertEq(factory.feeUsd(1), MONTHLY);
        assertEq(factory.claimCooldown(), 30 days);
        assertEq(factory.owner(), safe);
        // Each account's implementation, from its own code.
        assertEq(factory.implementationOf(address(acct)), address(implV1));
        assertEq(factory.implementationOf(address(a2)), address(implV2));
        assertEq(factory.implementationOf(eve), address(0));
        // predictAddressAt finds the v1 account at generation 0 and dana's v2.
        assertEq(factory.predictAddressAt(alice, 0), address(acct));
        assertEq(factory.predictAddressAt(dana, 0), address(a2));
        assertEq(factory.predictAddress(alice), address(acct));
        // A generation that does not exist yet: the current implementation.
        assertEq(factory.predictAddressAt(alice, 1), _predict(address(implV2), alice, 1));
        assertEq(a2.VERSION(), 2);
        assertEq(a2.ESCROW(), address(escrow));
        assertEq(a2.FACTORY(), address(factory));
    }

    /// Append-only storage: tradePaused packs into slot 12 after cardPaused
    /// (offset 1), _implementations is slot 13; every older slot keeps its
    /// meaning (`forge inspect ConfioSmartAccountFactory storageLayout`).
    function test_upgrade_storageLayoutIsAppended() public {
        address issuer = makeAddr("issuer");
        vm.startPrank(safe);
        factory.setCardSpender(issuer, true);
        factory.setCardPaused(true);
        factory.setTradePaused(true);
        vm.stopPrank();
        assertEq(address(uint160(uint256(vm.load(address(factory), bytes32(uint256(0)))))), address(implV2));
        assertEq(
            address(uint160(uint256(vm.load(address(factory), keccak256(abi.encode(alice, uint256(1))))))),
            address(acct),
            "accountOf at 1"
        );
        assertEq(uint256(vm.load(address(factory), keccak256(abi.encode(issuer, uint256(11))))), 1);
        uint256 slot12 = uint256(vm.load(address(factory), bytes32(uint256(12))));
        assertEq(uint8(slot12), 1, "cardPaused at 12/0");
        assertEq(uint8(slot12 >> 8), 1, "tradePaused at 12/1");
        assertEq(uint256(vm.load(address(factory), bytes32(uint256(13)))), 2, "_implementations length at 13");
        bytes32 arr = keccak256(abi.encode(uint256(13)));
        assertEq(address(uint160(uint256(vm.load(address(factory), arr)))), address(implV1));
        assertEq(address(uint160(uint256(vm.load(address(factory), bytes32(uint256(arr) + 1))))), address(implV2));
        uint256 slot5 = uint256(vm.load(address(factory), bytes32(uint256(5))));
        assertEq(uint64(slot5), 30 days);
        assertEq(uint64(slot5 >> 64), 7 days);
    }

    function test_upgrade_onlySafe_once_andImplementationMustNameThisFactory() public {
        // The reinitializer cannot run again, by anyone.
        vm.prank(safe);
        vm.expectRevert();
        factory.initializeV2(address(implV2));
        ConfioSmartAccountV2 wrong = _newImplementationV2(eve);
        ConfioSmartAccountFactory logic = _newFactoryLogic();
        vm.prank(carol);
        vm.expectRevert();
        factory.upgradeToAndCall(address(logic), "");
        // Safe-only setter.
        vm.prank(eve);
        vm.expectRevert();
        factory.setTradePaused(true);
        vm.prank(safe);
        factory.setTradePaused(true);
        assertTrue(factory.tradePaused());
        // An implementation built for another factory is refused.
        ConfioSmartAccountFactory logic2 = _newFactoryLogic();
        vm.expectRevert(bytes("implementation factory"));
        new ERC1967Proxy(
            address(logic2), abi.encodeCall(ConfioSmartAccountFactory.initialize, (safe, address(wrong), MONTHLY, ANNUAL))
        );
    }

    function test_createAccount_afterUpgrade_isV2() public {
        assertEq(factory.implementationOf(address(a2)), address(implV2));
        assertEq(a2.owner(), dana);
        assertEq(a2.nextRuleId(), 1);
        // The implementation itself is inert.
        assertEq(implV2.owner(), address(0));
        vm.expectRevert(ConfioSmartAccountV2.NotFactory.selector);
        implV2.initialize(eve);
        vm.expectRevert(ConfioSmartAccountV2.NotFactory.selector);
        a2.initializeMigrated(eve, IConfioSmartAccountV2.Plan.Monthly, IConfioSmartAccountV2.Plan.None, uint64(vm.getBlockTimestamp() + 1 days));
    }

    // ═════════════════════════ Rules ═════════════════════════════════════

    function test_storeRule_tradeAndPurchaseShapes() public {
        _danaSubscribed(0, 0);
        // Valid shapes.
        _tradeRule(address(plus), address(0), CAP);
        _tradeRule(address(cusd), address(0), CAP);
        _tradeRule(address(cusd), address(btcb), CAP);
        _tradeRule(address(plus), address(tsla), CAP);
        _purchaseRule(address(cusd), CAP);
        _purchaseRule(address(plus), CAP);
        IConfioSmartAccountV2.RuleKind T = IConfioSmartAccountV2.RuleKind.Trade;
        IConfioSmartAccountV2.RuleKind P = IConfioSmartAccountV2.RuleKind.Purchase;
        IConfioSmartAccountV2.RuleInput[8] memory bad = [
            _input(T, address(plus), address(0), eve, CAP), // payee
            _input(T, address(cusd), address(tsla), address(0), CAP), // stock from cUSD
            _input(T, address(plus), address(cusd), address(0), CAP), // a dollar
            _input(T, address(plus), address(usdt), address(0), CAP), // USDT
            _input(T, address(usdt), address(0), address(0), CAP), // tokenIn not a dollar
            _input(T, address(plus), address(0), address(0), 0), // zero cap
            _input(P, address(cusd), address(0), eve, CAP), // payee not the escrow
            _input(P, address(cusd), address(btcb), address(escrow), CAP) // tokenOut
        ];
        for (uint256 i = 0; i < bad.length; ++i) {
            vm.prank(dana, relayer);
            vm.expectRevert(ConfioSmartAccountV2.BadRule.selector);
            a2.createRule(bad[i]);
        }
    }

    function test_executeRule_and_cardPull_refuseTradeAndPurchaseRules() public {
        _danaSubscribed(500e18, 0);
        uint256 t = _tradeRule(address(cusd), address(0), CAP);
        uint256 p = _purchaseRule(address(cusd), CAP);
        vm.startPrank(relayer, relayer);
        vm.expectRevert(ConfioSmartAccountV2.BadRule.selector);
        a2.executeRule(t, abi.encode(address(swapRouter), _swapBuyData(CUSD_, address(btcb), 10e18), uint256(1)), address(0), 0);
        vm.expectRevert(ConfioSmartAccountV2.BadRule.selector);
        a2.executeRule(p, "", address(0), 0);
        vm.stopPrank();
        vm.prank(address(escrow));
        vm.expectRevert(ConfioSmartAccountV2.BadRule.selector);
        a2.cardPull(p, 1e18);
        // A Trade rule cannot be used for a purchase, nor the reverse.
        vm.prank(relayer, relayer);
        vm.expectRevert(ConfioSmartAccountV2.BadRule.selector);
        a2.relayPurchase(t, bytes32("o"), merchant, 1e18, 0, vm.getBlockTimestamp() + 1, "ok");
        _relayTradeReverts(ConfioSmartAccountV2.BadRule.selector, p, address(swapRouter), _swapBuyData(CUSD_, address(btcb), 1e18), 1e18);
    }

    // ═════════════════════════ relayTrade ════════════════════════════════

    function test_relayTrade_swapBuy_countsDollars_andEmits() public {
        _danaSubscribed(2_000e18, 0);
        uint256 id = _tradeRule(address(cusd), address(0), CAP);
        uint256 cusdBefore = cusd.balanceOf(address(a2));
        vm.expectEmit(true, true, false, false, address(a2));
        emit RelayTraded(id, address(swapRouter), address(cusd), address(btcb), 0, 0, 0);
        _buyBtc(id, 400e18);
        assertEq(cusdBefore - cusd.balanceOf(address(a2)), 400e18);
        assertGt(btcb.balanceOf(address(a2)), 0);
        (uint256 used, uint256 lastAt) = a2.bucketOf(id);
        assertEq(used, 400e18);
        assertEq(lastAt, vm.getBlockTimestamp());
        _noAllowances(address(a2));
    }

    function test_relayTrade_stockBuyAndSell_cusdPlus() public {
        _danaSubscribed(0, 2_000e18);
        uint256 id = _tradeRule(address(plus), address(0), CAP);
        uint256 shares = _sharesFor(300e18);
        bytes memory buy = _stockBuyData(address(tsla), shares, 10_000);
        uint256 p = plus.pPlus();
        _relayTrade(id, address(stockRouter), buy, shares);
        uint256 got = tsla.balanceOf(address(a2));
        assertGt(got, 0);
        (uint256 used,) = a2.bucketOf(id);
        assertEq(used, (shares * p + 1e18 - 1) / 1e18, "cUSD+ counted at pPlus, rounded up");
        // A sell stays in the account and counts at the quote price.
        _skip(60);
        (uint256 usedBefore,) = a2.bucketOf(id);
        uint256 plusBefore = plus.balanceOf(address(a2));
        _relayTrade(id, address(stockRouter), _stockSellData(address(tsla), got), got);
        assertEq(tsla.balanceOf(address(a2)), 0);
        assertGt(plus.balanceOf(address(a2)), plusBefore);
        (uint256 usedAfter,) = a2.bucketOf(id);
        assertEq(usedAfter, usedBefore + (got * STOCK_PRICE) / 1e18, "sell counted at the quote price");
        _noAllowances(address(a2));
    }

    function test_relayTrade_capExceeded_andSellsCounted() public {
        _danaSubscribed(3_000e18, 0);
        uint256 id = _tradeRule(address(cusd), address(0), CAP);
        _buyBtc(id, 900e18);
        _skip(60);
        _relayTradeReverts(
            ConfioSmartAccountV2.CapExceeded.selector, id, address(swapRouter), _swapBuyData(CUSD_, address(btcb), 200e18), 200e18
        );
        // A sell with the bucket full counts too, at the feed: refused.
        uint256 btc = btcb.balanceOf(address(a2));
        _relayTradeReverts(
            ConfioSmartAccountV2.CapExceeded.selector, id, address(swapRouter), _swapSellData(CUSD_, address(btcb), btc / 2), btc / 2
        );
        // Half a week later half the cap has leaked.
        _skip(WEEK / 2);
        (uint256 used,) = a2.bucketOf(id);
        assertApproxEqAbs(used, 400e18, 0.2e18); // plus the 60 s leak
        // A sell of ~US$100 at the feed now fits and is counted.
        _relayTrade(id, address(swapRouter), _swapSellData(CUSD_, address(btcb), 1e15), 1e15);
        assertApproxEqAbs(_used(id), 500e18, 0.2e18);
        _skip(60);
        _buyBtc(id, 490e18);
        _skip(60);
        _relayTradeReverts(
            ConfioSmartAccountV2.CapExceeded.selector, id, address(swapRouter), _swapBuyData(CUSD_, address(btcb), 20e18), 20e18
        );
    }

    /// The fixed-window flaw (2x across a boundary) cannot happen: a full
    /// bucket at any moment refuses a second full cap a minute later, and a
    /// week later exactly one more cap fits.
    function test_relayTrade_rollingWindow_noDoubleAtABoundary() public {
        _danaSubscribed(5_000e18, 0);
        uint256 id = _tradeRule(address(cusd), address(0), CAP);
        _skip(WEEK - 30); // anywhere: there is no boundary to straddle
        _buyBtc(id, CAP);
        _skip(60);
        // Within one hour of a full cap, at most cap/168 more.
        _relayTradeReverts(
            ConfioSmartAccountV2.CapExceeded.selector, id, address(swapRouter), _swapBuyData(CUSD_, address(btcb), 1e18), 1e18
        );
        _skip(1 hours);
        uint256 room = CAP - _used(id);
        assertLe(room, CAP / 168 + 1e18);
        _buyBtc(id, room);
        _skip(WEEK - 1 hours - 120);
        // One gap after the first full buy: total admitted <= cap * (1 + d/gap).
        _relayTradeReverts(
            ConfioSmartAccountV2.CapExceeded.selector, id, address(swapRouter), _swapBuyData(CUSD_, address(btcb), CAP), CAP
        );
    }

    function test_relayTrade_minGapBetweenTrades() public {
        _danaSubscribed(2_000e18, 0);
        uint256 id = _tradeRule(address(cusd), address(0), CAP);
        _buyBtc(id, 10e18);
        _skip(59);
        _relayTradeReverts(
            ConfioSmartAccountV2.TooEarly.selector, id, address(swapRouter), _swapBuyData(CUSD_, address(btcb), 10e18), 10e18
        );
        // Sells too.
        _relayTradeReverts(
            ConfioSmartAccountV2.TooEarly.selector, id, address(swapRouter), _swapSellData(CUSD_, address(btcb), 1), 1
        );
        _skip(1);
        _buyBtc(id, 10e18);
        // Per rule: another Trade rule is not blocked.
        uint256 id2 = _tradeRule(address(cusd), address(0), CAP);
        _buyBtc(id2, 10e18);
    }

    function test_relayTrade_pausedStopsBuysAndSells_ownerUnaffected() public {
        _danaSubscribed(2_000e18, 0);
        uint256 id = _tradeRule(address(cusd), address(0), CAP);
        _buyBtc(id, 100e18);
        _skip(60);
        vm.prank(safe);
        factory.setTradePaused(true);
        uint256 btc = btcb.balanceOf(address(a2));
        _relayTradeReverts(
            ConfioSmartAccountV2.TradePaused.selector, id, address(swapRouter), _swapSellData(CUSD_, address(btcb), btc), btc
        );
        _relayTradeReverts(
            ConfioSmartAccountV2.TradePaused.selector, id, address(swapRouter), _swapBuyData(CUSD_, address(btcb), 1e18), 1e18
        );
        uint256 p = _purchaseRule(address(cusd), CAP);
        vm.prank(relayer, relayer);
        vm.expectRevert(ConfioSmartAccountV2.TradePaused.selector);
        a2.relayPurchase(p, bytes32("o"), merchant, 1e18, 0, vm.getBlockTimestamp() + 1, "ok");
        // Rules and the owner keep working.
        vm.prank(dana, relayer);
        a2.withdraw(address(btcb), btc);
        assertEq(btcb.balanceOf(dana), btc);
        // The relayer pause stops them as well.
        vm.startPrank(safe);
        factory.setTradePaused(false);
        factory.setRelayerPaused(true);
        vm.stopPrank();
        _relayTradeReverts(
            ConfioSmartAccountV2.RelayerPaused.selector, id, address(swapRouter), _swapBuyData(CUSD_, address(btcb), 1e18), 1e18
        );
    }

    function test_relayTrade_onlyRelayer_currentBilling() public {
        _danaSubscribed(2_000e18, 0);
        uint256 id = _tradeRule(address(cusd), address(0), CAP);
        bytes memory data = _swapBuyData(CUSD_, address(btcb), 10e18);
        // The owner, a stranger, a sponsor not tx.origin, a sponsor contract.
        address[3] memory callers = [dana, eve, relayer];
        address[3] memory origins = [relayer, eve, eve];
        for (uint256 i = 0; i < 3; ++i) {
            vm.prank(callers[i], origins[i]);
            vm.expectRevert(ConfioSmartAccountV2.NotRelayer.selector);
            a2.relayTrade(id, address(swapRouter), data, 10e18, 1);
        }
        SponsorContract sc = new SponsorContract();
        vm.prank(safe);
        plus.setSponsor(address(sc), true);
        vm.prank(relayer, relayer);
        (bool ok, bytes memory ret) =
            sc.call(address(a2), abi.encodeCall(a2.relayTrade, (id, address(swapRouter), data, 10e18, 1)));
        assertFalse(ok);
        assertEq(bytes4(ret), ConfioSmartAccountV2.NotRelayer.selector);
        // Payment due: no hands-off.
        vm.warp(a2.paidUntil());
        _freshFeeds();
        _relayTradeReverts(ConfioSmartAccountV2.BadState.selector, id, address(swapRouter), data, 10e18);
    }

    /// The relayer cannot take anything out: only the two routers, only
    /// their buy/sell, never a dollar or USDT as the asset.
    function test_relayTrade_relayerCannotPullAssetsOut() public {
        _danaSubscribed(2_000e18, 1_000e18);
        uint256 id = _tradeRule(address(cusd), address(0), CAP);
        uint256 idPlus = _tradeRule(address(plus), address(0), CAP);
        uint256 before = a2.dollarsUsd();
        // Another venue: an evil router, the owner's wallet, a token.
        EvilSwapRouter evil = new EvilSwapRouter(btcb);
        bytes memory buy = _swapBuyData(CUSD_, address(btcb), 10e18);
        _relayTradeReverts(ConfioSmartAccountV2.BadVenue.selector, id, address(evil), buy, 10e18);
        _relayTradeReverts(ConfioSmartAccountV2.BadVenue.selector, id, eve, buy, 10e18);
        _relayTradeReverts(ConfioSmartAccountV2.BadVenue.selector, id, address(cusd), abi.encodeCall(IERC20.transfer, (eve, 1e18)), 1e18);
        // A router selector other than buy/sell (sellToUsdt, a transferFrom).
        bytes memory other = abi.encodeCall(
            ConfioStockRouter.sellToUsdt, (_quote(address(tsla), 1e18, STOCK_PRICE, 1), "", 1, 1, FEE_BPS)
        );
        _relayTradeReverts(ConfioSmartAccountV2.BadCall.selector, idPlus, address(stockRouter), other, 1e18);
        _relayTradeReverts(
            ConfioSmartAccountV2.BadCall.selector, id, address(swapRouter), abi.encodeCall(IERC20.transferFrom, (address(a2), eve, 1)), 1
        );
        // A "stock" sell whose asset is a dollar or USDT.
        _relayTradeReverts(
            ConfioSmartAccountV2.BadToken.selector, idPlus, address(stockRouter), _stockSellData(address(plus), 1e18), 1e18
        );
        _relayTradeReverts(
            ConfioSmartAccountV2.BadToken.selector, idPlus, address(stockRouter), _stockSellData(address(usdt), 1e18), 1e18
        );
        // Swap to a token without a feed (CONFIO) or from it.
        _relayTradeReverts(
            ConfioSmartAccountV2.BadToken.selector, id, address(swapRouter), _swapBuyData(CUSD_, address(confio), 1e18), 1e18
        );
        // A dollar that is not the rule's (cUSD+ source on a cUSD rule), a
        // stock from a cUSD rule.
        _relayTradeReverts(
            ConfioSmartAccountV2.BadCall.selector, id, address(swapRouter), _swapBuyData(PLUS, address(btcb), 1e18), 1e18
        );
        uint256 shares = _sharesFor(300e18);
        _relayTradeReverts(
            ConfioSmartAccountV2.BadCall.selector, id, address(stockRouter), _stockBuyData(address(tsla), shares, 10_000), shares
        );
        // maxIn bounds what the router may take.
        vm.prank(relayer, relayer);
        vm.expectRevert();
        a2.relayTrade(id, address(swapRouter), _swapBuyData(CUSD_, address(btcb), 10e18), 9e18, 1);
        // minOut must be positive.
        vm.prank(relayer, relayer);
        vm.expectRevert(ConfioSmartAccountV2.Slippage.selector);
        a2.relayTrade(id, address(swapRouter), buy, 10e18, 0);
        assertEq(a2.dollarsUsd(), before, "nothing moved");
        assertEq(cusd.balanceOf(relayer) + plus.balanceOf(relayer) + usdt.balanceOf(relayer), 0);
        _noAllowances(address(a2));
    }

    function test_relayTrade_pinnedAsset() public {
        _danaSubscribed(2_000e18, 0);
        uint256 id = _tradeRule(address(cusd), address(btcb), CAP);
        _relayTradeReverts(
            ConfioSmartAccountV2.BadToken.selector, id, address(swapRouter), _swapBuyData(CUSD_, address(xaut), 10e18), 10e18
        );
        xaut.mint(address(a2), 1e6);
        _relayTradeReverts(
            ConfioSmartAccountV2.BadToken.selector, id, address(swapRouter), _swapSellData(CUSD_, address(xaut), 1e6), 1e6
        );
        _buyBtc(id, 10e18);
    }

    function test_relayTrade_swapSlippageBeyondFeedBound() public {
        _danaSubscribed(2_000e18, 0);
        uint256 id = _tradeRule(address(cusd), address(0), CAP);
        // 1.6% below the market (after the fee): refused both ways.
        dex.setHaircutBps(160);
        _relayTradeReverts(
            ConfioSmartAccountV2.BelowFeed.selector, id, address(swapRouter), _swapBuyData(CUSD_, address(btcb), 100e18), 100e18
        );
        btcb.mint(address(a2), 5e15);
        _relayTradeReverts(
            ConfioSmartAccountV2.BelowFeed.selector, id, address(swapRouter), _swapSellData(CUSD_, address(btcb), 5e15), 5e15
        );
        // 1.4%: inside the bound.
        dex.setHaircutBps(140);
        _buyBtc(id, 100e18);
        _skip(60);
        _relayTrade(id, address(swapRouter), _swapSellData(CUSD_, address(btcb), 5e15), 5e15);
        // A stale feed refuses.
        dex.setHaircutBps(0);
        _skip(60);
        btcFeed.set(btcFeed.answer(), vm.getBlockTimestamp() - 1 hours - 1);
        _relayTradeReverts(
            ConfioSmartAccountV2.StaleFeed.selector, id, address(swapRouter), _swapBuyData(CUSD_, address(btcb), 10e18), 10e18
        );
    }

    function test_relayTrade_maxFeeBpsAboveConstant() public {
        _danaSubscribed(2_000e18, 2_000e18);
        uint256 id = _tradeRule(address(cusd), address(0), CAP);
        uint256 idPlus = _tradeRule(address(plus), address(0), CAP);
        bytes memory swapBuy = abi.encodeCall(
            ConfioSwapRouter.buy, (CUSD_, 10e18, 1, _route(address(usdt), address(btcb)), address(btcb), 1, 91)
        );
        _relayTradeReverts(ConfioSmartAccountV2.BadCall.selector, id, address(swapRouter), swapBuy, 10e18);
        uint256 shares = _sharesFor(300e18);
        bytes memory stockBuy = abi.encodeCall(
            ConfioStockRouter.buyWithSavings, (_quote(address(tsla), 1e18, STOCK_PRICE, 0), "", shares, STOCK_PRICE, 1, 91)
        );
        _relayTradeReverts(ConfioSmartAccountV2.BadCall.selector, idPlus, address(stockRouter), stockBuy, shares);
        tsla.mint(address(a2), 1e18);
        bytes memory stockSell = abi.encodeCall(
            ConfioStockRouter.sellToSavings, (_quote(address(tsla), 1e18, STOCK_PRICE, 1), "", 1, 1, 91)
        );
        _relayTradeReverts(ConfioSmartAccountV2.BadCall.selector, idPlus, address(stockRouter), stockSell, 1e18);
        // 90 passes.
        _relayTrade(idPlus, address(stockRouter), _stockSellData(address(tsla), 1e18), 1e18);
    }

    function test_relayTrade_usdtExcessBound() public {
        _danaSubscribed(0, 2_000e18);
        uint256 id = _tradeRule(address(plus), address(0), CAP);
        uint256 shares = _sharesFor(300e18);
        // Spends 90% of the redemption: 10% would stay as USDT.
        _relayTradeReverts(
            ConfioSmartAccountV2.Slippage.selector, id, address(stockRouter), _stockBuyData(address(tsla), shares, 9_000), shares
        );
    }

    // ═════════════════════════ relayPurchase ═════════════════════════════

    function test_relayPurchase_cusd_paysEscrowForOwner_refundComesBack() public {
        _danaSubscribed(500e18, 0);
        uint256 id = _purchaseRule(address(cusd), 200e18);
        uint256 before = cusd.balanceOf(address(a2));
        bytes32 orderId = keccak256(abi.encode(orderNonce + 1));
        vm.expectEmit(true, true, false, true, address(a2));
        emit RelayPurchased(id, orderId, 120e18, 120e18);
        _purchase(id, 120e18);
        assertEq(before - cusd.balanceOf(address(a2)), 120e18);
        assertEq(cusd.balanceOf(address(escrow)), 120e18);
        assertEq(escrow.buyerOf(orderId), dana, "the owner is the buyer");
        assertEq(escrow.refundToOf(orderId), address(a2));
        (uint256 used,) = a2.bucketOf(id);
        assertEq(used, 120e18);
        // Cap.
        vm.prank(relayer, relayer);
        vm.expectRevert(ConfioSmartAccountV2.CapExceeded.selector);
        a2.relayPurchase(id, bytes32("x"), merchant, 81e18, 0, vm.getBlockTimestamp() + 1, "ok");
        _purchase(id, 80e18);
        escrow.refund(orderId);
        assertEq(cusd.balanceOf(address(a2)), before - 80e18);
        _noAllowances(address(a2));
        assertEq(cusd.allowance(address(a2), address(escrow)), 0);
    }

    function test_relayPurchase_cusdPlus_unwrapsOwnersCusdUntouched() public {
        _danaSubscribed(50e18, 500e18);
        uint256 id = _purchaseRule(address(plus), 200e18);
        uint256 cusdBefore = cusd.balanceOf(address(a2));
        uint256 plusBefore = plus.balanceOf(address(a2));
        _purchase(id, 100e18);
        assertGe(cusd.balanceOf(address(a2)), cusdBefore, "owner's cUSD not spent");
        assertLe(cusd.balanceOf(address(a2)) - cusdBefore, 0.1e18, "excess about the margin");
        assertLe(plusBefore - plus.balanceOf(address(a2)), _sharesFor(100.06e18));
        assertEq(cusd.balanceOf(address(escrow)), 100e18);
        _noAllowances(address(a2));
    }

    function test_relayPurchase_refusals() public {
        _danaSubscribed(500e18, 0);
        uint256 id = _purchaseRule(address(cusd), 200e18);
        uint256 deadline = vm.getBlockTimestamp() + 1;
        vm.startPrank(relayer, relayer);
        vm.expectRevert(ConfioSmartAccountV2.BadAmount.selector);
        a2.relayPurchase(id, bytes32("a"), merchant, 0, 0, deadline, "ok");
        // The escrow's own checks: authorization, the owner as merchant.
        vm.expectRevert(bytes("bad authorization"));
        a2.relayPurchase(id, bytes32("a"), merchant, 1e18, 0, deadline, "forged");
        vm.expectRevert(bytes("bad merchant"));
        a2.relayPurchase(id, bytes32("a"), dana, 1e18, 0, deadline, "ok");
        vm.stopPrank();
        // Only the relayer.
        vm.prank(dana, relayer);
        vm.expectRevert(ConfioSmartAccountV2.NotRelayer.selector);
        a2.relayPurchase(id, bytes32("a"), merchant, 1e18, 0, deadline, "ok");
        vm.prank(merchant, merchant);
        vm.expectRevert(ConfioSmartAccountV2.NotRelayer.selector);
        a2.relayPurchase(id, bytes32("a"), merchant, 1e18, 0, deadline, "ok");
        // A cancelled rule.
        vm.prank(dana, relayer);
        a2.cancelRule(id);
        vm.prank(relayer, relayer);
        vm.expectRevert(ConfioSmartAccountV2.BadRule.selector);
        a2.relayPurchase(id, bytes32("a"), merchant, 1e18, 0, deadline, "ok");
        assertEq(cusd.balanceOf(address(escrow)), 0);
    }

    /// Model-checked leaky bucket: for any sequence of (wait, amount) the
    /// contract admits exactly what the model admits, and over any span d
    /// the admitted total never exceeds cap * (1 + d / gap).
    function testFuzz_bucket_matchesModel_andBoundsEveryWindow(uint256 seed) public {
        uint256 cap = 500e18;
        _danaSubscribed(100_000e18, 0);
        IConfioSmartAccountV2.RuleInput memory input =
            _input(IConfioSmartAccountV2.RuleKind.Purchase, address(cusd), address(0), address(escrow), cap);
        // Daily (gap 1 day) so a dozen steps of up to two gaps stay inside
        // the paid month.
        input.frequency = IConfioSmartAccountV2.Frequency.Daily;
        uint256 id = _danaRule(input);
        uint256 gap = 1 days;
        uint256 n = 12;
        uint256[] memory at = new uint256[](n);
        uint256[] memory amt = new uint256[](n);
        uint256 k;
        uint256 level;
        uint256 last;
        for (uint256 i = 0; i < n; ++i) {
            seed = uint256(keccak256(abi.encode(seed, i)));
            uint256 wait = seed % (2 * gap);
            if (seed % 3 == 0) wait = seed % 1 hours;
            uint256 amount = 1 + (seed >> 64) % (cap + cap / 4);
            vm.warp(vm.getBlockTimestamp() + wait);
            uint256 nowTs = vm.getBlockTimestamp();
            // Model.
            uint256 lvl = level;
            if (last != 0 && lvl != 0) {
                uint256 el = nowTs - last;
                if (el >= gap) {
                    lvl = 0;
                } else {
                    uint256 leak = (cap * el) / gap;
                    lvl = lvl > leak ? lvl - leak : 0;
                }
            }
            (uint256 used,) = a2.bucketOf(id);
            assertEq(used, lvl, "level");
            bool fits = lvl + amount <= cap;
            vm.prank(relayer, relayer);
            if (!fits) vm.expectRevert(ConfioSmartAccountV2.CapExceeded.selector);
            a2.relayPurchase(id, keccak256(abi.encode(seed)), merchant, amount, 0, nowTs + 1, "ok");
            if (fits) {
                level = lvl + amount;
                last = nowTs;
                at[k] = nowTs;
                amt[k] = amount;
                ++k;
            }
        }
        for (uint256 i = 0; i < k; ++i) {
            uint256 sum;
            for (uint256 j = i; j < k; ++j) {
                sum += amt[j];
                assertLe(sum * gap, cap * gap + cap * (at[j] - at[i]), "window bound");
            }
        }
    }

    // ═════════════════════════ Migration ═════════════════════════════════

    /// The batch the app signs (one Face), run end to end against alice's
    /// deployed-v1 account: only v1 functions on the old account.
    function test_migration_batch_endToEnd() public {
        // Alice: v1, monthly, with cUSD, cUSD+, bitcoin, gold and a stock.
        _subscribedMonthly(300e18);
        uint256 shares = _givePlusUsd(address(acct), 700e18);
        btcb.mint(address(acct), 1e16);
        xaut.mint(address(acct), 5e5);
        tsla.mint(address(acct), 2e18);
        vm.prank(alice, relayer);
        IConfioSmartAccount.RuleInput memory send = _rule(IConfioSmartAccount.RuleKind.Send, address(cusd), 10e18);
        send.payee = bob;
        acct.createRule(send);
        uint64 paidUntil = acct.paidUntil();
        vm.warp(vm.getBlockTimestamp() + 10 days);
        _freshFeeds();

        address[] memory tokens = new address[](7);
        tokens[0] = address(cusd);
        tokens[1] = address(plus);
        tokens[2] = address(usdt);
        tokens[3] = address(btcb);
        tokens[4] = address(xaut);
        tokens[5] = address(confio);
        tokens[6] = address(tsla);
        uint256[] memory amounts = new uint256[](7);
        for (uint256 i = 0; i < 7; ++i) {
            amounts[i] = IERC20(tokens[i]).balanceOf(address(acct));
        }
        address predicted = factory.predictAddressAt(alice, factory.generationOf(alice) + 1);

        // ── the batch: msg.sender alice (7702), origin the sponsor ──
        vm.startPrank(alice, relayer);
        acct.cancelSubscription(); // 1. old: no renewal
        address moved = factory.migrate(); // 2. new clone, subscription carried
        acct.withdrawAll(tokens); // 3. old -> alice
        for (uint256 i = 0; i < 7; ++i) {
            if (amounts[i] > 0) IERC20(tokens[i]).transfer(moved, amounts[i]); // 4. alice -> new
        }
        ConfioSmartAccountV2 n = ConfioSmartAccountV2(moved);
        n.createRule( // 5. rules re-signed, plus the hands-off ones
            IConfioSmartAccountV2.RuleInput({
                kind: IConfioSmartAccountV2.RuleKind.Send,
                frequency: IConfioSmartAccountV2.Frequency.Weekly,
                tokenIn: address(cusd),
                tokenOut: address(0),
                payee: bob,
                payoutRef: bytes32(0),
                amountUsd: 10e18,
                firstRunAt: 0
            })
        );
        n.createRule(_input(IConfioSmartAccountV2.RuleKind.Trade, address(plus), address(0), address(0), CAP));
        n.createRule(_input(IConfioSmartAccountV2.RuleKind.Purchase, address(cusd), address(0), address(escrow), 200e18));
        vm.stopPrank();

        assertEq(moved, predicted, "predicted before the batch");
        assertEq(factory.accountOf(alice), moved);
        assertEq(factory.generationOf(alice), 1);
        assertTrue(factory.isAccount(address(acct)), "old stays an account");
        assertEq(factory.implementationOf(moved), address(implV2));
        assertEq(factory.predictAddressAt(alice, 0), address(acct));
        assertEq(factory.predictAddressAt(alice, 1), moved);
        assertEq(factory.predictAddress(alice), moved);
        // Assets moved in full, nothing left behind.
        for (uint256 i = 0; i < 7; ++i) {
            assertEq(IERC20(tokens[i]).balanceOf(address(acct)), 0, "old empty");
            assertEq(IERC20(tokens[i]).balanceOf(moved), amounts[i], "new holds it");
        }
        assertEq(plus.balanceOf(moved), shares);
        // Subscription carried: same plan and paidUntil, no charge, epoch 1.
        assertEq(uint8(n.plan()), uint8(IConfioSmartAccountV2.Plan.Monthly));
        assertEq(n.paidUntil(), paidUntil);
        assertEq(n.status(), 1);
        assertEq(n.subscriptionEpoch(), 1);
        assertEq(acct.status(), 2, "old cancel pending");
        assertEq(acct.owner(), alice);
        // Hands-off works at once on the new account.
        uint256 tradeId = 2;
        uint256 sh = _sharesFor(300e18);
        bytes memory buyData = _stockBuyData(address(aapl), sh, 10_000);
        vm.prank(relayer, relayer);
        n.relayTrade(tradeId, address(stockRouter), buyData, sh, 1);
        assertGt(aapl.balanceOf(moved), 0);
        // At paidUntil: the old account expires uncharged, the new one renews.
        vm.warp(paidUntil);
        assertEq(acct.status(), 3);
        vm.prank(relayer, relayer);
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.collectFee();
        uint256 collectorBefore = cusd.balanceOf(address(collector));
        vm.prank(relayer, relayer);
        n.collectFee();
        assertEq(cusd.balanceOf(address(collector)) - collectorBefore, MONTHLY);
        // The old account still answers its owner.
        vm.prank(alice, relayer);
        acct.withdrawAll(tokens);
    }

    function test_migrate_withoutASubscription_startsUnsubscribed() public {
        vm.prank(alice);
        address moved = factory.migrate();
        assertEq(ConfioSmartAccountV2(moved).status(), 0);
        assertEq(ConfioSmartAccountV2(moved).owner(), alice);
        // Once current, migrate refuses.
        vm.prank(alice);
        vm.expectRevert(bytes("already current"));
        factory.migrate();
    }

    function test_migrate_refusals() public {
        // An uncancelled Active subscription.
        _subscribedMonthly(0);
        vm.prank(alice);
        vm.expectRevert(bytes("cancel subscription first"));
        factory.migrate();
        // No account, or someone else's: there is no parameter to name one.
        vm.prank(eve);
        vm.expectRevert(bytes("no live account"));
        factory.migrate();
        // Already on the current implementation.
        vm.prank(dana);
        vm.expectRevert(bytes("already current"));
        factory.migrate();
        // Creation pause stops it too.
        vm.prank(safe);
        factory.pause();
        vm.prank(alice);
        vm.expectRevert();
        factory.migrate();
    }

    function test_migrate_inheritedAccount_refusedForEveryone() public {
        _subscribedMonthly(100e18);
        _withBeneficiary();
        vm.prank(bob);
        acct.initiateClaim();
        vm.warp(acct.claimExecutableAt());
        vm.prank(bob);
        acct.executeClaim();
        assertTrue(acct.inherited());
        // Alice's account is no longer hers; bob's is not his account.
        vm.prank(alice);
        vm.expectRevert(bytes("no live account"));
        factory.migrate();
        vm.prank(bob);
        vm.expectRevert(bytes("no live account"));
        factory.migrate();
        // Alice reopens (createAccount) on v2 at generation 1.
        vm.prank(alice);
        address reopened = factory.createAccount();
        assertEq(factory.implementationOf(reopened), address(implV2));
        assertEq(factory.predictAddressAt(alice, 0), address(acct));
        assertEq(factory.predictAddressAt(alice, 1), reopened);
    }

    // ── helpers ──

    function _used(uint256 id) internal view returns (uint256 used) {
        (used,) = a2.bucketOf(id);
    }

    function _predict(address impl, address owner_, uint64 g) internal view returns (address) {
        bytes32 salt = keccak256(abi.encode(owner_, g));
        bytes memory code = abi.encodePacked(
            hex"3d602d80600a3d3981f3363d3d373d3d3d363d73", impl, hex"5af43d82803e903d91602b57fd5bf3"
        );
        return address(uint160(uint256(keccak256(abi.encodePacked(bytes1(0xff), address(factory), salt, keccak256(code))))));
    }
}
