// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {CusdVault} from "../CusdVault.sol";
import {CusdPlusVault} from "../CusdPlusVault.sol";
import {MockToken, MockOracle, MockInstantManager} from "./CusdPlusVault.t.sol";

contract CusdSystemTest is Test {
    MockToken usdt;
    MockToken usdy;
    MockOracle oracle;
    MockInstantManager im;
    CusdVault cusd;
    CusdPlusVault plus;

    address treasury = makeAddr("treasury");
    address sponsor = makeAddr("sponsor");
    address user = makeAddr("user");
    address recipient = makeAddr("recipient");

    function setUp() public {
        usdt = new MockToken("USDT");
        usdy = new MockToken("USDY");
        oracle = new MockOracle();
        im = new MockInstantManager(usdt, usdy, oracle);
        usdt.mint(address(im), 100_000_000e18);
        usdy.mint(address(im), 100_000_000e18);

        CusdVault cusdImplementation = new CusdVault(address(usdt));
        cusd = CusdVault(
            address(new ERC1967Proxy(address(cusdImplementation), abi.encodeCall(CusdVault.initialize, (treasury, 90))))
        );

        CusdPlusVault plusImplementation =
            new CusdPlusVault(address(usdy), address(usdt), address(im), address(oracle), 1500);
        plus = CusdPlusVault(
            address(new ERC1967Proxy(address(plusImplementation), abi.encodeCall(CusdPlusVault.initialize, (treasury))))
        );

        vm.startPrank(treasury);
        cusd.setSponsor(sponsor, true);
        cusd.setSavingsVault(address(plus));
        plus.setSponsor(sponsor, true);
        plus.initializeCusd(address(cusd));
        vm.stopPrank();

        usdt.mint(user, 1_000_000e18);
        vm.startPrank(user);
        usdt.approve(address(cusd), type(uint256).max);
        usdt.approve(address(plus), type(uint256).max);
        cusd.approve(address(plus), type(uint256).max);
        vm.stopPrank();
    }

    function test_legacyUsdtToPlus_chargesOneEntryFee() public {
        vm.prank(user, sponsor);
        uint256 shares = plus.subscribeAndMint(100e18, 99e18, user);

        assertEq(shares, 99.1e18);
        assertEq(plus.balanceOf(user), 99.1e18);
        assertEq(cusd.totalSupply(), 0);
        assertEq(cusd.accruedEntryFees(), 0.9e18);
        assertEq(usdt.balanceOf(address(cusd)), 0.9e18);
        assertTrue(cusd.isFullyBacked());
    }

    function test_legacyPlusExit_isPermissionlessAndChargesExitFee() public {
        vm.prank(user, sponsor);
        uint256 shares = plus.subscribeAndMint(100e18, 0, user);
        uint256 before = usdt.balanceOf(recipient);

        vm.prank(user, user);
        uint256 net = plus.redeemToUsdt(shares, 0, recipient);

        assertEq(net, 98.2081e18);
        assertEq(usdt.balanceOf(recipient) - before, net);
        assertEq(cusd.accruedEntryFees(), 0.9e18);
        assertEq(cusd.accruedExitFees(), 0.8919e18);
        assertEq(plus.balanceOf(user), 0);
        assertTrue(cusd.isFullyBacked());
    }

    function test_cusdPlusWrapAndUnwrap_areFeeFreeButSponsored() public {
        vm.prank(user, sponsor);
        uint256 cusdAmount = cusd.mintWithFee(100e18, 0, user);
        uint256 entryFees = cusd.accruedEntryFees();

        vm.prank(user, sponsor);
        uint256 shares = plus.wrapCusd(cusdAmount, 0, user);
        assertEq(shares, cusdAmount);
        assertEq(cusd.balanceOf(user), 0);
        assertEq(cusd.accruedEntryFees(), entryFees);

        vm.prank(user, sponsor);
        uint256 unwrapped = plus.unwrapToCusd(shares, cusdAmount, user);
        assertEq(unwrapped, cusdAmount);
        assertEq(cusd.balanceOf(user), cusdAmount);
        assertEq(plus.balanceOf(user), 0);
        assertEq(cusd.accruedEntryFees(), entryFees);
        assertEq(cusd.accruedExitFees(), 0);
        assertTrue(cusd.isFullyBacked());
    }

    function test_sponsorOriginCanConvertDirectlyToFriend() public {
        vm.prank(user, sponsor);
        uint256 cusdAmount = cusd.mintWithFee(100e18, 0, user);

        vm.prank(user, sponsor);
        uint256 shares = plus.wrapCusd(cusdAmount, 0, recipient);
        assertEq(plus.balanceOf(recipient), shares);

        vm.prank(recipient, sponsor);
        uint256 unwrapped = plus.unwrapToCusd(shares, 0, user);
        assertEq(cusd.balanceOf(user), unwrapped);
        assertEq(cusd.accruedExitFees(), 0);
    }

    function test_wrapAndUnwrap_rejectUnsponsoredUser() public {
        vm.prank(user, sponsor);
        uint256 cusdAmount = cusd.mintWithFee(100e18, 0, user);

        vm.prank(user, user);
        vm.expectRevert("not sponsored");
        plus.wrapCusd(cusdAmount, 0, user);

        vm.prank(user, sponsor);
        uint256 shares = plus.wrapCusd(cusdAmount, 0, user);
        vm.prank(user, user);
        vm.expectRevert("not sponsored");
        plus.unwrapToCusd(shares, 0, user);
    }

    function test_secondaryPlusTransferRemainsOpen() public {
        vm.prank(user, sponsor);
        uint256 shares = plus.subscribeAndMint(100e18, 0, user);

        vm.prank(user, user);
        plus.transfer(recipient, shares);
        assertEq(plus.balanceOf(recipient), shares);
    }

    function test_onlyRegisteredPlusCanUseCusdSavingsMethods() public {
        vm.prank(user, sponsor);
        vm.expectRevert("not savings vault");
        cusd.mintForSavings(1e18, user);

        vm.prank(user, user);
        vm.expectRevert("not savings vault");
        cusd.settleSavingsExit(1e18, 0, user);
    }
}
