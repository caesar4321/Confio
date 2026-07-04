// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {CusdPlusVault} from "../CusdPlusVault.sol";
import {ConfioStockRouter, IGmSettlement} from "../ConfioStockRouter.sol";
import {MockToken, MockOracle, MockInstantManager} from "./CusdPlusVault.t.sol";

/// Swaps USDT <-> stock at a fixed price; attestation ignored (pattern-C
/// signature checks are Ondo-side and provisional here).
contract MockGmSettlement is IGmSettlement {
    MockToken public usdt;
    uint256 public priceUsd = 300e18; // $300/share

    constructor(MockToken _usdt) { usdt = _usdt; }

    function buy(address stockToken, uint256 paymentAmount, uint256, bytes calldata)
        external
        returns (uint256 stockOut)
    {
        usdt.transferFrom(msg.sender, address(this), paymentAmount);
        stockOut = (paymentAmount * 1e18) / priceUsd;
        MockToken(stockToken).mint(msg.sender, stockOut);
    }

    function sell(address stockToken, uint256 stockAmount, uint256, bytes calldata)
        external
        returns (uint256 paymentOut)
    {
        MockToken(stockToken).transferFrom(msg.sender, address(this), stockAmount);
        paymentOut = (stockAmount * priceUsd) / 1e18;
        usdt.transfer(msg.sender, paymentOut);
    }
}

contract ConfioStockRouterTest is Test {
    MockToken usdt;
    MockToken usdy;
    MockToken tsla;
    MockOracle oracle;
    MockInstantManager im;
    MockGmSettlement gm;
    CusdPlusVault vault;
    ConfioStockRouter router;

    address treasury = makeAddr("treasury");
    address feeTreasury = makeAddr("feeTreasury");
    address user = makeAddr("user");

    function setUp() public {
        usdt = new MockToken("USDT");
        usdy = new MockToken("USDY");
        tsla = new MockToken("TSLAon");
        oracle = new MockOracle();
        im = new MockInstantManager(usdt, usdy, oracle);
        usdt.mint(address(im), 100_000_000e18);
        usdy.mint(address(im), 100_000_000e18);

        CusdPlusVault impl = new CusdPlusVault(
            address(usdy), address(usdt), address(im), address(oracle), 1500
        );
        vault = CusdPlusVault(address(new ERC1967Proxy(
            address(impl), abi.encodeCall(CusdPlusVault.initialize, (treasury))
        )));

        gm = new MockGmSettlement(usdt);
        usdt.mint(address(gm), 10_000_000e18);

        router = new ConfioStockRouter(
            address(vault), address(usdt), address(gm), feeTreasury, treasury
        );
        vm.prank(treasury);
        router.setStockFeeBps(30); // launch-config placeholder for tests only

        // User saves $3,000 first (sweep model: cUSD+ is the buying power)
        usdt.mint(user, 3000e18);
        vm.startPrank(user);
        usdt.approve(address(vault), type(uint256).max);
        vault.subscribeAndMint(3000e18, 0, user);
        vault.approve(address(router), type(uint256).max);
        tsla.approve(address(router), type(uint256).max);
        vm.stopPrank();
    }

    function test_buy_takesExplicitFee_deliversStock() public {
        uint256 sharesIn = 600e18; // $600 of savings at par
        vm.prank(user);
        uint256 stockOut = router.buyWithSavings(address(tsla), sharesIn, 0, 0, "");

        // fee = 0.30% of the redeemed USDT, as an explicit transfer
        uint256 expectedFee = (600e18 * 30) / 10_000;
        assertEq(usdt.balanceOf(feeTreasury), expectedFee, "explicit fee to treasury");
        // remainder bought stock at $300
        assertEq(stockOut, ((600e18 - expectedFee) * 1e18) / 300e18);
        assertEq(tsla.balanceOf(user), stockOut, "stock delivered to user");
        assertEq(vault.balanceOf(user), 3000e18 - sharesIn, "savings reduced");
        // router is a pipe: nothing rests
        assertEq(usdt.balanceOf(address(router)), 0);
        assertEq(tsla.balanceOf(address(router)), 0);
        assertEq(vault.balanceOf(address(router)), 0);
    }

    function test_sell_reinvestsProceedsIntoSavings() public {
        vm.prank(user);
        uint256 stockOut = router.buyWithSavings(address(tsla), 600e18, 0, 0, "");
        uint256 sharesBefore = vault.balanceOf(user);

        vm.prank(user);
        uint256 sharesOut = router.sellToSavings(address(tsla), stockOut, 0, 0, "");

        assertEq(tsla.balanceOf(user), 0);
        assertEq(vault.balanceOf(user), sharesBefore + sharesOut, "proceeds keep earning");
        // round trip cost = buy fee + sell fee on the 600 that traded; the
        // untouched 2,400 of savings is unaffected (mock GM is spread-free)
        uint256 endValue = vault.balanceOf(user); // pPlus == 1e18 (no accrual)
        uint256 expected = 2400e18 + (600e18 * 9970 / 10_000) * 9970 / 10_000;
        assertApproxEqRel(endValue, expected, 0.0001e18);
        assertEq(usdt.balanceOf(address(router)), 0, "router keeps nothing");
        assertGe(vault.backingRatioBps(), 10_000, "vault invariant holds through trades");
    }

    function test_fee_capped_and_eventful() public {
        vm.prank(treasury);
        vm.expectRevert(bytes("fee above hard cap"));
        router.setStockFeeBps(101);

        vm.prank(user);
        vm.expectRevert(); // non-owner
        router.setStockFeeBps(10);
    }

    function test_zeroFee_isCleanPassThrough() public {
        vm.prank(treasury);
        router.setStockFeeBps(0);
        vm.prank(user);
        uint256 stockOut = router.buyWithSavings(address(tsla), 300e18, 0, 0, "");
        assertEq(stockOut, 1e18, "exactly one share at $300, no fee");
        assertEq(usdt.balanceOf(feeTreasury), 0);
    }

    function test_slippageFloor_reverts() public {
        vm.prank(user);
        vm.expectRevert(bytes("gm: insufficient stock out"));
        router.buyWithSavings(address(tsla), 300e18, 0, 2e18, ""); // demands 2 shares for $300
    }

    function test_pause_blocks_trades() public {
        vm.prank(treasury);
        router.pause();
        vm.prank(user);
        vm.expectRevert();
        router.buyWithSavings(address(tsla), 300e18, 0, 0, "");
    }

    function test_frozen_vault_user_cannot_trade() public {
        vm.prank(treasury);
        vault.freezeAddress(user);
        vm.prank(user);
        vm.expectRevert(bytes("address frozen"));
        router.buyWithSavings(address(tsla), 300e18, 0, 0, "");
    }
}
