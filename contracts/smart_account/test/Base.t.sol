// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {CusdVault} from "cusd-plus/CusdVault.sol";
import {CusdPlusVault} from "cusd-plus/CusdPlusVault.sol";
import {ConfioStockRouter, GmQuote} from "ondo-stocks/ConfioStockRouter.sol";
import {ConfioSwapRouter} from "crypto-swap/ConfioSwapRouter.sol";
import {ConfioSmartAccount} from "../ConfioSmartAccount.sol";
import {ConfioSmartAccountFactory} from "../ConfioSmartAccountFactory.sol";
import {ConfioSmartAccountFeeCollector} from "../ConfioSmartAccountFeeCollector.sol";
import {IConfioSmartAccount} from "../interfaces/IConfioSmartAccount.sol";
import {MockToken, MockOracle, MockInstantManager, MockGM, MockDex, MockFeed} from "./Mocks.sol";

/// Shared fixture: the REAL CusdVault, CusdPlusVault, ConfioStockRouter and
/// ConfioSwapRouter, wired as on mainnet, with mocks only for what is
/// outside Confío (Ondo, PancakeSwap, Chainlink). `alice` owns the account
/// under test, `bob` is the beneficiary, `relayer` is the KMS sponsor.
abstract contract SmartAccountBase is Test {
    uint256 constant MONTHLY = 14.99e18;
    uint256 constant ANNUAL = 149.99e18;
    uint256 constant FEE_BPS = 90;
    uint256 constant BTC_PRICE = 100_000e18;
    uint256 constant XAU_PRICE = 4_000e18;
    uint256 constant STOCK_PRICE = 300e18;
    uint8 constant PLUS = 0;
    uint8 constant CUSD_ = 1;

    MockToken usdt;
    MockToken usdy;
    MockToken usdon;
    MockToken btcb;
    MockToken xaut;
    MockToken confio;
    MockToken tsla;
    MockToken aapl;
    MockOracle oracle;
    MockInstantManager im;
    MockGM gm;
    MockDex dex;
    MockFeed btcFeed;
    MockFeed xauFeed;

    CusdVault cusd;
    CusdPlusVault plus;
    ConfioStockRouter stockRouter;
    ConfioSwapRouter swapRouter;

    ConfioSmartAccountFeeCollector collector;
    ConfioSmartAccount implementation;
    ConfioSmartAccountFactory factory;
    ConfioSmartAccount acct;

    address safe = makeAddr("safe");
    address treasury = makeAddr("treasury");
    address relayer = makeAddr("relayer");
    address bank = makeAddr("bank");
    address alice = makeAddr("alice");
    address bob = makeAddr("bob");
    address carol = makeAddr("carol");
    address eve = makeAddr("eve");
    address referrer = makeAddr("referrer");

    uint256 private _attestationId = 1;

    function setUp() public virtual {
        vm.warp(1_800_000_000);
        usdt = new MockToken("USDT", 18);
        usdy = new MockToken("USDY", 18);
        usdon = new MockToken("USDon", 18);
        btcb = new MockToken("BTCB", 18);
        xaut = new MockToken("XAUt", 6);
        confio = new MockToken("CONFIO", 18);
        tsla = new MockToken("TSLAon", 18);
        aapl = new MockToken("AAPLon", 18);
        oracle = new MockOracle();
        im = new MockInstantManager(usdt, usdy, oracle);
        usdt.mint(address(im), 1e30);
        usdy.mint(address(im), 1e30);

        cusd = CusdVault(
            address(
                new ERC1967Proxy(
                    address(new CusdVault(address(usdt))), abi.encodeCall(CusdVault.initialize, (safe, FEE_BPS))
                )
            )
        );
        plus = CusdPlusVault(
            address(
                new ERC1967Proxy(
                    address(new CusdPlusVault(address(usdy), address(usdt), address(im), address(oracle), 1500)),
                    abi.encodeCall(CusdPlusVault.initialize, (safe))
                )
            )
        );
        vm.startPrank(safe);
        cusd.setSavingsVault(address(plus));
        plus.initializeCusd(address(cusd));
        vm.stopPrank();
        gm = new MockGM(usdt, address(usdon));
        usdt.mint(address(gm), 1e30);
        stockRouter = ConfioStockRouter(
            address(
                new ERC1967Proxy(
                    address(new ConfioStockRouter(address(plus), address(usdt), address(usdon), address(gm))),
                    abi.encodeCall(ConfioStockRouter.initialize, (safe))
                )
            )
        );
        dex = new MockDex(usdt);
        dex.setPrice(address(btcb), BTC_PRICE);
        dex.setPrice(address(xaut), XAU_PRICE);
        swapRouter = ConfioSwapRouter(
            address(
                new ERC1967Proxy(
                    address(new ConfioSwapRouter(address(plus), address(dex))),
                    abi.encodeCall(ConfioSwapRouter.initialize, (safe))
                )
            )
        );
        btcFeed = new MockFeed(100_000e8, 8);
        xauFeed = new MockFeed(4_000e8, 8);

        collector = new ConfioSmartAccountFeeCollector(IERC20(address(cusd)), IERC20(address(plus)), treasury);

        // The account implementation is deployed against the factory proxy's
        // predicted address (implementation, factory logic, then the proxy).
        address predicted = vm.computeCreateAddress(address(this), vm.getNonce(address(this)) + 2);
        implementation = _newImplementation(predicted);
        ConfioSmartAccountFactory logic = _newFactoryLogic();
        factory = ConfioSmartAccountFactory(
            address(
                new ERC1967Proxy(
                    address(logic),
                    abi.encodeCall(
                        ConfioSmartAccountFactory.initialize, (safe, address(implementation), MONTHLY, ANNUAL)
                    )
                )
            )
        );
        assertEq(address(factory), predicted, "factory address prediction");

        vm.startPrank(safe);
        // The relayer key is in BOTH sponsor sets (4.1).
        cusd.setSponsor(relayer, true);
        plus.setSponsor(relayer, true);
        plus.setSponsor(address(stockRouter), true);
        plus.setSponsor(address(swapRouter), true);
        cusd.setSponsor(address(swapRouter), true);
        cusd.setReferralShareCapBps(5_000);
        cusd.setSmartAccountFactory(address(factory), true);
        vm.stopPrank();

        // The bank holds both dollars, minted through the real perimeter.
        usdt.mint(bank, 4_000_000e18);
        vm.startPrank(bank, relayer);
        usdt.approve(address(cusd), type(uint256).max);
        usdt.approve(address(plus), type(uint256).max);
        cusd.mintWithFee(2_000_000e18, 0, bank);
        plus.subscribeAndMint(2_000_000e18, 0, bank);
        vm.stopPrank();

        acct = _create(alice);
    }

    function _newFactoryLogic() internal returns (ConfioSmartAccountFactory) {
        return new ConfioSmartAccountFactory(address(plus), address(stockRouter));
    }

    function _newImplementation(address factory_) internal returns (ConfioSmartAccount) {
        return new ConfioSmartAccount(
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
            address(xauFeed)
        );
    }

    // ── actors ──────────────────────────────────────────────────────────

    function _create(address who) internal returns (ConfioSmartAccount a) {
        vm.prank(who);
        a = ConfioSmartAccount(factory.createAccount());
    }

    /// An owner call inside a sponsored 7702 batch: msg.sender is the
    /// owner, tx.origin is the sponsor.
    function _asOwner() internal {
        vm.prank(alice, relayer);
    }

    function _asRelayer() internal {
        vm.prank(relayer, relayer);
    }

    // ── funding ─────────────────────────────────────────────────────────

    function _giveCusd(address to, uint256 amount) internal {
        vm.prank(bank);
        cusd.transfer(to, amount);
    }

    function _givePlus(address to, uint256 shares) internal {
        vm.prank(bank);
        plus.transfer(to, shares);
    }

    /// cUSD+ shares worth at least `usd`, rounded up like the fee.
    function _sharesFor(uint256 usd) internal view returns (uint256) {
        uint256 p = plus.pPlus();
        return (usd * 1e18 + p - 1) / p;
    }

    function _givePlusUsd(address to, uint256 usd) internal returns (uint256 shares) {
        shares = _sharesFor(usd);
        _givePlus(to, shares);
    }

    /// Raises pPlus: USDY's price grows, cUSD+ takes its share of it.
    function _growPPlus(uint256 bps) internal {
        oracle.setPrice((oracle.price() * (10_000 + bps)) / 10_000);
        plus.accrue();
    }

    // ── lifecycle helpers ───────────────────────────────────────────────

    function _subscribe(IConfioSmartAccount.Plan p) internal {
        _asOwner();
        acct.subscribe(p, type(uint256).max);
    }

    /// Alice subscribes monthly, paid in cUSD, leaving `extra` cUSD inside.
    function _subscribedMonthly(uint256 extra) internal {
        _giveCusd(address(acct), MONTHLY + extra);
        _subscribe(IConfioSmartAccount.Plan.Monthly);
    }

    function _enableInheritance() internal {
        vm.prank(safe);
        factory.enableInheritance();
    }

    /// The relayer's approval for exactly this designation (decision 26),
    /// recorded after the server's checks.
    function _approveName(ConfioSmartAccount a, address who, uint64 window) internal {
        vm.prank(relayer, relayer);
        factory.approveDesignation(address(a), who, window);
    }

    function _approveAccept(ConfioSmartAccount a, address who) internal {
        vm.prank(relayer, relayer);
        factory.approveAcceptance(address(a), who);
    }

    function _name(address who, uint64 window) internal {
        _approveName(acct, who, window);
        _asOwner();
        acct.setBeneficiary(who, window);
    }

    function _accept(address who) internal {
        _approveAccept(acct, who);
        vm.prank(who, relayer);
        acct.acceptBeneficiary();
    }

    /// Bob is the accepted beneficiary with a 90-day window.
    function _withBeneficiary() internal {
        _enableInheritance();
        _name(bob, 90 days);
        _accept(bob);
    }

    // ── venue calldata ──────────────────────────────────────────────────

    function _quote(address asset, uint256 quantity, uint256 price, uint8 side) internal returns (GmQuote memory) {
        return GmQuote({
            chainId: block.chainid,
            attestationId: _attestationId++,
            userId: keccak256("confio-purchaser"),
            asset: asset,
            price: price,
            quantity: quantity,
            expiration: block.timestamp + 300,
            side: side,
            additionalData: bytes32(0)
        });
    }

    /// Net USDT `shares` of cUSD+ redeem to, after cUSD's exit fee.
    function _netUsdtForShares(uint256 shares) internal view returns (uint256) {
        uint256 usdyOut = (shares * plus.pPlus()) / oracle.price();
        uint256 gross = (usdyOut * oracle.price()) / 1e18;
        return gross - cusd.feeFor(gross);
    }

    /// buyWithSavings spending `sharesIn`; `spendBps` of the net USDT buys
    /// stock and the rest comes back to the caller as USDT excess (N6).
    function _stockBuyData(address asset, uint256 sharesIn, uint256 spendBps) internal returns (bytes memory) {
        uint256 net = (_netUsdtForShares(sharesIn) * spendBps) / 10_000;
        uint256 quantity = (net * 1e18) / STOCK_PRICE;
        uint256 spend = (quantity * STOCK_PRICE) / 1e18;
        return abi.encodeCall(
            ConfioStockRouter.buyWithSavings, (_quote(asset, quantity, STOCK_PRICE, 0), "", sharesIn, spend, 1, FEE_BPS)
        );
    }

    function _stockSellData(address asset, uint256 quantity) internal returns (bytes memory) {
        return
            abi.encodeCall(
                ConfioStockRouter.sellToSavings, (_quote(asset, quantity, STOCK_PRICE, 1), "", 1, 1, FEE_BPS)
            );
    }

    function _route(address a, address b) internal pure returns (bytes memory) {
        return abi.encode(uint8(0), abi.encodePacked(a, uint24(100), b));
    }

    function _swapBuyData(uint8 source, address token, uint256 amountIn) internal view returns (bytes memory) {
        return
            abi.encodeCall(ConfioSwapRouter.buy, (source, amountIn, 1, _route(address(usdt), token), token, 1, FEE_BPS));
    }

    function _swapSellData(uint8 dest, address token, uint256 amountIn) internal view returns (bytes memory) {
        return
            abi.encodeCall(ConfioSwapRouter.sell, (dest, token, amountIn, _route(token, address(usdt)), 1, 1, FEE_BPS));
    }

    /// Token units whose sale nets `netUsd` after the 0.9% entry fee, at
    /// `priceUsd` per whole token.
    function _unitsForNet(uint256 netUsd, uint256 priceUsd, uint8 decimals_) internal pure returns (uint256) {
        uint256 gross = (netUsd * 10_000) / (10_000 - FEE_BPS) + 1;
        return (gross * 10 ** decimals_) / priceUsd + 1;
    }

    function _leg(address venue, address token, uint256 maxIn, bytes memory data)
        internal
        pure
        returns (IConfioSmartAccount.SaleLeg memory)
    {
        return IConfioSmartAccount.SaleLeg({venue: venue, tokenIn: token, maxIn: maxIn, data: data});
    }

    function _legs(IConfioSmartAccount.SaleLeg memory a)
        internal
        pure
        returns (IConfioSmartAccount.SaleLeg[] memory l)
    {
        l = new IConfioSmartAccount.SaleLeg[](1);
        l[0] = a;
    }

    function _legs(IConfioSmartAccount.SaleLeg memory a, IConfioSmartAccount.SaleLeg memory b)
        internal
        pure
        returns (IConfioSmartAccount.SaleLeg[] memory l)
    {
        l = new IConfioSmartAccount.SaleLeg[](2);
        l[0] = a;
        l[1] = b;
    }

    /// A stock leg that nets `netUsd` into cUSD+.
    function _stockLeg(MockToken stock, uint256 netUsd) internal returns (IConfioSmartAccount.SaleLeg memory) {
        uint256 quantity = _unitsForNet(netUsd, STOCK_PRICE, 18);
        return _leg(address(stockRouter), address(stock), quantity, _stockSellData(address(stock), quantity));
    }

    /// A bitcoin or gold leg that nets `netUsd` into `dest`.
    function _cryptoLeg(MockToken token, uint256 priceUsd, uint8 dest, uint256 netUsd)
        internal
        view
        returns (IConfioSmartAccount.SaleLeg memory)
    {
        uint256 amount = _unitsForNet(netUsd, priceUsd, token.decimals());
        return _leg(address(swapRouter), address(token), amount, _swapSellData(dest, address(token), amount));
    }

    /// Brings the account to SaleAllowed: period over, notice started and
    /// run out.
    function _toSaleAllowed() internal {
        vm.warp(acct.paidUntil());
        _asRelayer();
        acct.startPaymentNotice();
        vm.warp(block.timestamp + 7 days);
        _freshFeeds();
    }

    function _freshFeeds() internal {
        btcFeed.set(btcFeed.answer(), block.timestamp);
        xauFeed.set(xauFeed.answer(), block.timestamp);
    }

    /// forcedSale as the relayer. The arguments are evaluated before the
    /// prank, so helper calls inside them cannot consume it.
    function _sale(IConfioSmartAccount.SaleLeg[] memory legs, uint256 minOut, address ref, uint256 bps) internal {
        vm.prank(relayer, relayer);
        acct.forcedSale(legs, minOut, ref, bps);
    }

    function _saleReverts(bytes4 err, IConfioSmartAccount.SaleLeg[] memory legs, uint256 minOut) internal {
        vm.prank(relayer, relayer);
        vm.expectRevert(err);
        acct.forcedSale(legs, minOut, address(0), 0);
    }

    function _rule(IConfioSmartAccount.RuleKind kind, address tokenIn, uint256 amountUsd)
        internal
        pure
        returns (IConfioSmartAccount.RuleInput memory r)
    {
        r.kind = kind;
        r.frequency = IConfioSmartAccount.Frequency.Weekly;
        r.tokenIn = tokenIn;
        r.amountUsd = amountUsd;
    }

    function _noAllowances(address a) internal view {
        address[4] memory spenders = [address(stockRouter), address(swapRouter), address(cusd), address(plus)];
        address[8] memory tokens = [
            address(cusd),
            address(plus),
            address(usdt),
            address(btcb),
            address(xaut),
            address(confio),
            address(tsla),
            address(aapl)
        ];
        for (uint256 i = 0; i < tokens.length; ++i) {
            for (uint256 j = 0; j < spenders.length; ++j) {
                assertEq(IERC20(tokens[i]).allowance(a, spenders[j]), 0, "allowance left");
            }
        }
    }
}
