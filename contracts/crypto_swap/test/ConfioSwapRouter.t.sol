// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {CusdVault} from "cusd-plus/CusdVault.sol";
import {CusdPlusVault} from "cusd-plus/CusdPlusVault.sol";
import {MockToken, MockOracle, MockInstantManager} from "cusd-plus/test/CusdPlusVault.t.sol";
import {ConfioSwapRouter, IPancakeSmartRouter} from "../ConfioSwapRouter.sol";

/// Mock PancakeSwap SmartRouter. Prices are USDT per token (WAD). Pulls
/// exactly amountIn from the caller (like the real pay()), delivers to the
/// recipient. Knobs model a partial pull and a short delivery.
contract MockSmartRouter is IPancakeSmartRouter {
    MockToken public usdt;
    mapping(address => uint256) public priceUsd;
    bool public partialPull;
    uint256 public shortBps;

    constructor(MockToken _usdt) {
        usdt = _usdt;
    }

    function setPrice(address token, uint256 p) external {
        priceUsd[token] = p;
    }

    function setPartialPull(bool v) external {
        partialPull = v;
    }

    function setShortBps(uint256 v) external {
        shortBps = v;
    }

    function _settle(address tokenIn, address tokenOut, uint256 amountIn, uint256 minOut, address to)
        internal
        returns (uint256 out)
    {
        uint256 take = partialPull ? amountIn - 1 : amountIn;
        require(IERC20(tokenIn).transferFrom(msg.sender, address(this), take), "pull failed");
        if (tokenIn == address(usdt)) {
            out = Math.mulDiv(amountIn, 1e18, priceUsd[tokenOut]);
        } else {
            out = Math.mulDiv(amountIn, priceUsd[tokenIn], 1e18);
        }
        out -= (out * shortBps) / 10_000;
        require(out >= minOut, "Too little received");
        MockToken(tokenOut).mint(to, out);
    }

    function exactInput(ExactInputParams calldata p) external payable returns (uint256) {
        bytes memory path = p.path;
        address first;
        address last;
        assembly {
            first := shr(96, mload(add(path, 32)))
            last := shr(96, mload(add(add(path, 32), sub(mload(path), 20))))
        }
        return _settle(first, last, p.amountIn, p.amountOutMinimum, p.recipient);
    }

    function swapExactTokensForTokens(uint256 amountIn, uint256 amountOutMin, address[] calldata path, address to)
        external
        payable
        returns (uint256)
    {
        return _settle(path[0], path[path.length - 1], amountIn, amountOutMin, to);
    }
}

/// 1% transfer tax: the router must swap what arrived and floor the user.
contract TaxedToken is ERC20 {
    constructor() ERC20("TAX", "TAX") {}

    function mint(address to, uint256 amt) external {
        _mint(to, amt);
    }

    function _update(address from, address to, uint256 value) internal override {
        if (from != address(0) && to != address(0)) {
            uint256 tax = value / 100;
            super._update(from, address(0xdead), tax);
            value -= tax;
        }
        super._update(from, to, value);
    }
}

contract ConfioSwapRouterTest is Test {
    MockToken usdt;
    MockToken usdy;
    MockToken btcb;
    MockOracle oracle;
    MockInstantManager im;
    CusdVault cusd;
    CusdPlusVault plus;
    MockSmartRouter dex;
    ConfioSwapRouter router;

    address treasury = makeAddr("treasury");
    address user = makeAddr("user");
    uint256 constant FEE = 90;
    uint256 constant BTC_PRICE = 100_000e18;
    uint24 constant POOL_FEE = 100;

    function setUp() public {
        usdt = new MockToken("USDT");
        usdy = new MockToken("USDY");
        btcb = new MockToken("BTCB");
        oracle = new MockOracle();
        im = new MockInstantManager(usdt, usdy, oracle);
        usdt.mint(address(im), 100_000_000e18);
        usdy.mint(address(im), 100_000_000e18);

        cusd = CusdVault(
            address(
                new ERC1967Proxy(
                    address(new CusdVault(address(usdt))), abi.encodeCall(CusdVault.initialize, (treasury, FEE))
                )
            )
        );
        plus = CusdPlusVault(
            address(
                new ERC1967Proxy(
                    address(new CusdPlusVault(address(usdy), address(usdt), address(im), address(oracle), 1500)),
                    abi.encodeCall(CusdPlusVault.initialize, (treasury))
                )
            )
        );
        dex = new MockSmartRouter(usdt);
        dex.setPrice(address(btcb), BTC_PRICE);

        // tx.origin (forge's default sender) stands in for Confío's KMS relay.
        vm.startPrank(treasury);
        cusd.setSponsor(tx.origin, true);
        cusd.setSavingsVault(address(plus));
        plus.setSponsor(tx.origin, true);
        plus.initializeCusd(address(cusd));
        vm.stopPrank();

        router = ConfioSwapRouter(
            address(
                new ERC1967Proxy(
                    address(new ConfioSwapRouter(address(plus), address(dex))),
                    abi.encodeCall(ConfioSwapRouter.initialize, (treasury))
                )
            )
        );
        // The router is a registered relay on BOTH dollars so it may mint to
        // the user on sells (deployment requirement).
        vm.startPrank(treasury);
        cusd.setSponsor(address(router), true);
        plus.setSponsor(address(router), true);
        vm.stopPrank();

        // User holds $1,000 of each dollar (both minted through the perimeter).
        usdt.mint(user, 2_000e18);
        vm.startPrank(user);
        usdt.approve(address(plus), type(uint256).max);
        usdt.approve(address(cusd), type(uint256).max);
        plus.subscribeAndMint(1_000e18, 0, user);
        cusd.mintWithFee(1_000e18, 0, user);
        plus.approve(address(router), type(uint256).max);
        cusd.approve(address(router), type(uint256).max);
        btcb.approve(address(router), type(uint256).max);
        vm.stopPrank();
    }

    // ── helpers ────────────────────────────────────────────────────────

    function _v3(address a, address b) internal pure returns (bytes memory) {
        return abi.encode(uint8(0), abi.encodePacked(a, POOL_FEE, b));
    }

    function _v2(address a, address b) internal pure returns (bytes memory) {
        address[] memory path = new address[](2);
        path[0] = a;
        path[1] = b;
        return abi.encode(uint8(1), abi.encode(path));
    }

    function _fee(uint256 gross) internal pure returns (uint256) {
        return Math.mulDiv(gross, FEE, 10_000, Math.Rounding.Ceil);
    }

    function _buy(uint8 source, uint256 amountIn) internal returns (uint256) {
        vm.prank(user);
        return router.buy(source, amountIn, 1, _v3(address(usdt), address(btcb)), address(btcb), 1, FEE);
    }

    function _assertRouterEmpty() internal view {
        assertEq(usdt.balanceOf(address(router)), 0, "router usdt");
        assertEq(btcb.balanceOf(address(router)), 0, "router btcb");
        assertEq(plus.balanceOf(address(router)), 0, "router cusd+");
        assertEq(cusd.balanceOf(address(router)), 0, "router cusd");
    }

    // ── buy ────────────────────────────────────────────────────────────

    function test_buyFromDollarPlus_paysExitFeeOnce_deliversToUser() public {
        uint256 shares = 100e18; // pPlus == 1 (no accrual)
        uint256 entryFeesBefore = cusd.accruedEntryFees();
        uint256 out = _buy(0, shares);

        uint256 net = 100e18 - _fee(100e18);
        assertEq(out, Math.mulDiv(net, 1e18, BTC_PRICE), "all net USDT swapped");
        assertEq(btcb.balanceOf(user), out);
        assertEq(cusd.accruedExitFees(), _fee(100e18), "0.9% at the perimeter");
        assertEq(cusd.accruedEntryFees(), entryFeesBefore, "no entry fee on a buy");
        _assertRouterEmpty();
    }

    function test_buyFromDollar_paysExitFeeOnce_deliversToUser() public {
        uint256 exitBefore = cusd.accruedExitFees();
        uint256 out = _buy(1, 100e18);
        uint256 net = 100e18 - _fee(100e18);
        assertEq(out, Math.mulDiv(net, 1e18, BTC_PRICE));
        assertEq(cusd.accruedExitFees() - exitBefore, _fee(100e18));
        _assertRouterEmpty();
    }

    function test_buy_v2Route() public {
        vm.prank(user);
        uint256 out = router.buy(0, 50e18, 1, _v2(address(usdt), address(btcb)), address(btcb), 1, FEE);
        assertGt(out, 0);
        _assertRouterEmpty();
    }

    function test_buy_userFloorEnforced() public {
        dex.setShortBps(100);
        uint256 net = 100e18 - _fee(100e18);
        uint256 fair = Math.mulDiv(net, 1e18, BTC_PRICE);
        vm.prank(user);
        vm.expectRevert(bytes("Too little received"));
        router.buy(0, 100e18, 1, _v3(address(usdt), address(btcb)), address(btcb), fair, FEE);
    }

    function test_buy_usdtFloorBindsNetAfterFee() public {
        vm.prank(user);
        vm.expectRevert(bytes("insufficient out"));
        router.buy(0, 100e18, 100e18, _v3(address(usdt), address(btcb)), address(btcb), 1, FEE);
    }

    function test_buy_feeCapBindsLiveConversionFee() public {
        vm.prank(user);
        vm.expectRevert(bytes("fee above trade cap"));
        router.buy(0, 10e18, 1, _v3(address(usdt), address(btcb)), address(btcb), 1, FEE - 1);
        assertEq(router.conversionFeeBps(), FEE);
    }

    function test_buy_rejectsUnsponsoredOrigin() public {
        vm.prank(user, user);
        vm.expectRevert(bytes("not sponsored"));
        router.buy(0, 10e18, 1, _v3(address(usdt), address(btcb)), address(btcb), 1, FEE);
    }

    function test_buy_routeMustStartAtUsdtAndEndAtToken() public {
        MockToken eth = new MockToken("ETH");
        vm.startPrank(user);
        vm.expectRevert(bytes("route endpoints"));
        router.buy(0, 10e18, 1, _v3(address(usdt), address(eth)), address(btcb), 1, FEE);
        vm.expectRevert(bytes("route endpoints"));
        router.buy(0, 10e18, 1, _v3(address(eth), address(btcb)), address(btcb), 1, FEE);
        vm.expectRevert(bytes("bad route kind"));
        router.buy(0, 10e18, 1, abi.encode(uint8(7), bytes("")), address(btcb), 1, FEE);
        vm.expectRevert(bytes("bad v3 path"));
        router.buy(0, 10e18, 1, abi.encode(uint8(0), abi.encodePacked(address(usdt))), address(btcb), 1, FEE);
        vm.stopPrank();
    }

    function test_buy_multiHopV3PathAccepted() public {
        MockToken wbnb = new MockToken("WBNB");
        bytes memory route =
            abi.encode(uint8(0), abi.encodePacked(address(usdt), uint24(500), address(wbnb), POOL_FEE, address(btcb)));
        vm.prank(user);
        assertGt(router.buy(0, 10e18, 1, route, address(btcb), 1, FEE), 0);
    }

    function test_cannotTradeDollarTokens() public {
        vm.startPrank(user);
        vm.expectRevert(bytes("dollar token"));
        router.buy(0, 10e18, 1, _v3(address(usdt), address(usdt)), address(usdt), 1, FEE);
        vm.expectRevert(bytes("dollar token"));
        router.buy(0, 10e18, 1, _v3(address(usdt), address(cusd)), address(cusd), 1, FEE);
        vm.expectRevert(bytes("dollar token"));
        router.sell(0, address(plus), 10e18, _v3(address(plus), address(usdt)), 1, 1, FEE);
        vm.stopPrank();
    }

    function test_buy_badSourceReverts() public {
        vm.prank(user);
        vm.expectRevert(bytes("bad source"));
        router.buy(2, 10e18, 1, _v3(address(usdt), address(btcb)), address(btcb), 1, FEE);
    }

    function test_partialPullReverts() public {
        dex.setPartialPull(true);
        vm.prank(user);
        vm.expectRevert(bytes("dex: partial fill"));
        router.buy(0, 10e18, 1, _v3(address(usdt), address(btcb)), address(btcb), 1, FEE);
    }

    // ── sell ───────────────────────────────────────────────────────────

    function test_sellToDollarPlus_paysEntryFeeOnce_mintsToUser() public {
        btcb.mint(user, 0.001e18); // $100
        uint256 sharesBefore = plus.balanceOf(user);
        uint256 entryBefore = cusd.accruedEntryFees();

        vm.prank(user);
        uint256 out = router.sell(0, address(btcb), 0.001e18, _v3(address(btcb), address(usdt)), 1, 1, FEE);

        assertEq(out, 100e18 - _fee(100e18), "net of the entry fee, pPlus == 1");
        assertEq(plus.balanceOf(user) - sharesBefore, out);
        assertEq(cusd.accruedEntryFees() - entryBefore, _fee(100e18));
        assertEq(btcb.balanceOf(user), 0);
        _assertRouterEmpty();
    }

    function test_sellToDollar_paysEntryFeeOnce_mintsToUser() public {
        btcb.mint(user, 0.001e18);
        uint256 before = cusd.balanceOf(user);
        vm.prank(user);
        uint256 out = router.sell(1, address(btcb), 0.001e18, _v2(address(btcb), address(usdt)), 1, 1, FEE);
        assertEq(out, 100e18 - _fee(100e18));
        assertEq(cusd.balanceOf(user) - before, out);
        _assertRouterEmpty();
    }

    function test_sell_floorsEnforced() public {
        btcb.mint(user, 0.001e18);
        vm.startPrank(user);
        vm.expectRevert(bytes("Too little received"));
        router.sell(0, address(btcb), 0.001e18, _v3(address(btcb), address(usdt)), 100e18 + 1, 1, FEE);
        vm.expectRevert(bytes("insufficient dollars out"));
        router.sell(0, address(btcb), 0.001e18, _v3(address(btcb), address(usdt)), 1, 100e18, FEE);
        vm.expectRevert(bytes("insufficient out"));
        router.sell(1, address(btcb), 0.001e18, _v3(address(btcb), address(usdt)), 1, 100e18, FEE);
        vm.stopPrank();
        assertEq(btcb.balanceOf(user), 0.001e18, "reverts restore the token");
    }

    function test_sell_routeMustEndAtUsdt() public {
        btcb.mint(user, 1e15);
        MockToken eth = new MockToken("ETH");
        vm.prank(user);
        vm.expectRevert(bytes("route endpoints"));
        router.sell(0, address(btcb), 1e15, _v3(address(btcb), address(eth)), 1, 1, FEE);
    }

    function test_sell_taxedTokenSwapsWhatArrived() public {
        TaxedToken tax = new TaxedToken();
        dex.setPrice(address(tax), 1e18);
        tax.mint(user, 100e18);
        vm.startPrank(user);
        tax.approve(address(router), type(uint256).max);
        uint256 out = router.sell(1, address(tax), 100e18, _v2(address(tax), address(usdt)), 1, 1, FEE);
        vm.stopPrank();
        // 1% lost on the way in, then the 0.9% entry fee.
        assertEq(out, 99e18 - _fee(99e18));
        assertEq(tax.balanceOf(address(router)), 0);
    }

    function test_sell_rejectsUnsponsoredOrigin() public {
        btcb.mint(user, 1e15);
        vm.prank(user, user);
        vm.expectRevert(bytes("not sponsored"));
        router.sell(0, address(btcb), 1e15, _v3(address(btcb), address(usdt)), 1, 1, FEE);
    }

    // ── ops ────────────────────────────────────────────────────────────

    function test_pauseBlocksTrades() public {
        vm.prank(treasury);
        router.pause();
        vm.prank(user);
        vm.expectRevert();
        router.buy(0, 10e18, 1, _v3(address(usdt), address(btcb)), address(btcb), 1, FEE);
    }

    function test_upgradeIsOwnerOnly() public {
        address next = address(new ConfioSwapRouter(address(plus), address(dex)));
        vm.prank(user);
        vm.expectRevert();
        router.upgradeToAndCall(next, "");
        vm.prank(treasury);
        router.upgradeToAndCall(next, "");
        assertEq(router.owner(), treasury);
    }

    function test_implementationCannotBeInitialized() public {
        ConfioSwapRouter impl = new ConfioSwapRouter(address(plus), address(dex));
        vm.expectRevert();
        impl.initialize(user);
    }

    function test_sweepRescuesStrays_ownerOnly() public {
        usdt.mint(address(router), 5e18);
        vm.prank(user);
        vm.expectRevert();
        router.sweep(address(usdt), user, 5e18);
        vm.prank(treasury);
        router.sweep(address(usdt), treasury, 5e18);
        assertEq(usdt.balanceOf(address(router)), 0);
    }

    function test_strayUsdtNeverJoinsATrade() public {
        usdt.mint(address(router), 7e18);
        uint256 out = _buy(0, 100e18);
        assertEq(out, Math.mulDiv(100e18 - _fee(100e18), 1e18, BTC_PRICE), "trade sized by its own delta");
        assertEq(usdt.balanceOf(address(router)), 7e18, "stray untouched");
    }

    function testFuzz_roundTrip_routerRetainsNothing(uint96 raw, bool fromPlus) public {
        uint256 amountIn = bound(uint256(raw), 1e18, 900e18);
        uint8 dollar = fromPlus ? 0 : 1;
        uint256 out = _buy(dollar, amountIn);
        vm.prank(user);
        router.sell(dollar, address(btcb), out, _v3(address(btcb), address(usdt)), 1, 1, FEE);
        _assertRouterEmpty();
        assertTrue(cusd.isFullyBacked());
        assertGe(plus.backingRatioBps(), 10_000);
    }
}
