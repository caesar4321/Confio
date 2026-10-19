// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * Live BSC rehearsal against the REAL cUSD/cUSD+ vaults and PancakeSwap.
 *
 *   forge test --match-path test/ConfioSwapRouter.fork.t.sol \
 *     --fork-url https://bsc-dataseed.bnbchain.org -vv
 *
 * Deploys the router on the fork, performs the two Safe registrations the
 * mainnet rollout needs, and round-trips $10 of BTCB (V3 0.01%) and XAUt
 * (V3 0.05%) from and back into both Confío dollars, with the KMS sponsor
 * as tx.origin exactly like a sponsored 7702 batch.
 */
import {Test, console2} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {ConfioSwapRouter} from "../ConfioSwapRouter.sol";

interface ILiveCusdPlus {
    function subscribeAndMint(uint256 usdtIn, uint256 minUsdyOut, address recipient) external returns (uint256);
    function setSponsor(address sponsor, bool allowed) external;
    function balanceOf(address) external view returns (uint256);
    function approve(address, uint256) external returns (bool);
    function positionUsd(address) external view returns (uint256);
}

interface ILiveCusd {
    function mintWithFee(uint256 grossUsdt, uint256 minCusdOut, address recipient) external returns (uint256);
    function setSponsor(address sponsor, bool allowed) external;
    function accruedExitFees() external view returns (uint256);
    function accruedEntryFees() external view returns (uint256);
    function balanceOf(address) external view returns (uint256);
    function approve(address, uint256) external returns (bool);
    function owner() external view returns (address);
}

contract ConfioSwapRouterForkTest is Test {
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    address constant KMS = 0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D;
    address constant CUSD_PLUS = 0x3C29417eb4314155e63d4C7D4507852b87763Ed1;
    address constant CUSD = 0x6101cC370635cF2c7f2725EaB010aC407A8d543F;
    address constant USDT = 0x55d398326f99059fF775485246999027B3197955;
    address constant SMART_ROUTER = 0x13f4EA83D0bd40E75C8222255bc855a974568Dd4;
    address constant BTCB = 0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c;
    address constant XAUT = 0x21cAef8A43163Eea865baeE23b9C2E327696A3bf;

    ConfioSwapRouter router;
    address user = makeAddr("forkUser");

    function _forked() private view returns (bool) {
        return CUSD_PLUS.code.length > 0;
    }

    function setUp() public {
        if (!_forked()) return;
        router = ConfioSwapRouter(
            address(
                new ERC1967Proxy(
                    address(new ConfioSwapRouter(CUSD_PLUS, SMART_ROUTER)),
                    abi.encodeCall(ConfioSwapRouter.initialize, (SAFE))
                )
            )
        );
        assertEq(ILiveCusd(CUSD).owner(), SAFE, "cUSD not Safe-owned");
        // The two Safe calls of the rollout.
        vm.startPrank(SAFE);
        ILiveCusdPlus(CUSD_PLUS).setSponsor(address(router), true);
        ILiveCusd(CUSD).setSponsor(address(router), true);
        vm.stopPrank();

        deal(USDT, user, 100e18);
        vm.startPrank(user, KMS);
        IERC20(USDT).approve(CUSD_PLUS, type(uint256).max);
        IERC20(USDT).approve(CUSD, type(uint256).max);
        ILiveCusdPlus(CUSD_PLUS).subscribeAndMint(40e18, 0, user);
        ILiveCusd(CUSD).mintWithFee(40e18, 0, user);
        ILiveCusdPlus(CUSD_PLUS).approve(address(router), type(uint256).max);
        ILiveCusd(CUSD).approve(address(router), type(uint256).max);
        IERC20(BTCB).approve(address(router), type(uint256).max);
        IERC20(XAUT).approve(address(router), type(uint256).max);
        vm.stopPrank();
    }

    function _v3(address a, uint24 fee, address b) private pure returns (bytes memory) {
        return abi.encode(uint8(0), abi.encodePacked(a, fee, b));
    }

    function _roundTrip(uint8 dollar, address token, uint24 poolFee, uint256 amountIn) private {
        address dollarToken = dollar == 0 ? CUSD_PLUS : CUSD;
        uint256 dollarsBefore = IERC20(dollarToken).balanceOf(user);
        uint256 exitBefore = ILiveCusd(CUSD).accruedExitFees();
        uint256 entryBefore = ILiveCusd(CUSD).accruedEntryFees();

        vm.prank(user, KMS);
        uint256 got = router.buy(dollar, amountIn, 1, _v3(USDT, poolFee, token), token, 1, 90);
        assertGt(got, 0, "no token out");
        assertEq(IERC20(token).balanceOf(user), got, "token to user");
        assertGt(ILiveCusd(CUSD).accruedExitFees(), exitBefore, "exit fee at the perimeter");

        vm.prank(user, KMS);
        uint256 back = router.sell(dollar, token, got, _v3(token, poolFee, USDT), 1, 1, 90);
        assertGt(ILiveCusd(CUSD).accruedEntryFees(), entryBefore, "entry fee at the perimeter");

        uint256 dollarsAfter = IERC20(dollarToken).balanceOf(user);
        // Round trip ~= 2 x 0.9% + pool fees + impact. Log it in bps.
        uint256 spent = amountIn;
        uint256 returned = dollarsAfter - (dollarsBefore - amountIn);
        console2.log("dollar", dollar, "token", token);
        console2.log("  in / back (wei units of the dollar):", spent, returned);
        console2.log("  round-trip cost bps:", ((spent - returned) * 10_000) / spent);
        assertEq(back, returned, "sell output is the user's dollar delta");
        assertLt((spent - returned) * 10_000 / spent, 250, "round trip under 2.5%");

        assertEq(IERC20(USDT).balanceOf(address(router)), 0, "router usdt");
        assertEq(IERC20(token).balanceOf(address(router)), 0, "router token");
        assertEq(IERC20(CUSD_PLUS).balanceOf(address(router)), 0, "router cusd+");
        assertEq(IERC20(CUSD).balanceOf(address(router)), 0, "router cusd");
    }

    function test_fork_btcbRoundTrip_fromDollarPlus() public {
        if (!_forked()) return;
        _roundTrip(0, BTCB, 100, 10e18);
    }

    function test_fork_btcbRoundTrip_fromDollar() public {
        if (!_forked()) return;
        _roundTrip(1, BTCB, 100, 10e18);
    }

    function test_fork_xautRoundTrip_fromDollarPlus() public {
        if (!_forked()) return;
        _roundTrip(0, XAUT, 500, 10e18);
    }

    function test_fork_xautRoundTrip_fromDollar() public {
        if (!_forked()) return;
        _roundTrip(1, XAUT, 500, 10e18);
    }

    address constant WBNB = 0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c;
    address constant SOL = 0x570A5D26f7765Ecb712C0924E4De545B89fD43dF;
    address constant ADA = 0x3EE2200Efb3400fAbB9AacF31297cBdD1d435D47;

    /// Catalog route shapes beyond a single 0.01%/0.05% hop: a two-hop V3
    /// path through WBNB (SOL) and a 0.25% pool (ADA).
    function _roundTripPath(uint8 dollar, address token, bytes memory buyPath, bytes memory sellPath) private {
        vm.startPrank(user, KMS);
        IERC20(token).approve(address(router), type(uint256).max);
        uint256 got = router.buy(dollar, 10e18, 1, abi.encode(uint8(0), buyPath), token, 1, 90);
        assertGt(got, 0, "no token out");
        router.sell(dollar, token, got, abi.encode(uint8(0), sellPath), 1, 1, 90);
        vm.stopPrank();
        assertEq(IERC20(token).balanceOf(address(router)), 0, "router token");
        assertEq(IERC20(USDT).balanceOf(address(router)), 0, "router usdt");
        assertEq(IERC20(WBNB).balanceOf(address(router)), 0, "router hop token");
    }

    function test_fork_multiHopSol_bothDollars() public {
        if (!_forked()) return;
        bytes memory buyPath = abi.encodePacked(USDT, uint24(100), WBNB, uint24(500), SOL);
        bytes memory sellPath = abi.encodePacked(SOL, uint24(500), WBNB, uint24(100), USDT);
        _roundTripPath(0, SOL, buyPath, sellPath);
        _roundTripPath(1, SOL, buyPath, sellPath);
    }

    function test_fork_quarterPercentPoolAda() public {
        if (!_forked()) return;
        _roundTripPath(1, ADA, abi.encodePacked(USDT, uint24(2500), ADA), abi.encodePacked(ADA, uint24(2500), USDT));
    }

    function test_fork_unsponsoredOriginRejected() public {
        if (!_forked()) return;
        vm.prank(user, user);
        vm.expectRevert(bytes("not sponsored"));
        router.buy(0, 1e18, 1, _v3(USDT, 100, BTCB), BTCB, 1, 90);
    }
}
