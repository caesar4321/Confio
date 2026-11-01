// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * Rehearses the continuous-oracle upgrade against the LIVE proxy. Run:
 *
 *   forge test --match-path test/UpgradeRehearsalV6.fork.t.sol \
 *     --fork-url <bsc rpc> -vv
 *
 * Executes the exact Safe call, then proves what shipped apps depend on:
 * exits sized from the stored pPlus (the way every released build sizes a
 * stock buy) settle in full, and the vault's price matches the Instant
 * Manager's in the same block.
 */
import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {CusdPlusVault} from "../CusdPlusVault.sol";

interface IOndoOracle {
    function getAssetPrice(address token) external view returns (uint256);
}

interface IAggregator {
    function latestRoundData() external view returns (uint80, int256, uint256, uint256, uint80);
}

contract UpgradeRehearsalV6ForkTest is Test {
    address constant PROXY = 0x3C29417eb4314155e63d4C7D4507852b87763Ed1;
    address constant USDY = 0x608593d17A2decBbc4399e4185bE4922F97eD32E;
    address constant USDT = 0x55d398326f99059fF775485246999027B3197955;
    address constant IM = 0x9bA360087075A4Cef548eeD71Eed197bf4cFA4E2;
    address constant WRAPPER = 0x1B508f3eF4a0c26fE9659eB1011BFb8E5e0c7782;
    address constant ONDO_ORACLE = 0x7EFD1dd84E4dE0F607943F8452a34CC12B82EF7b;
    address constant USDT_FEED = 0xB97Ad0E74fa7d920791E90258A6E2085088b4320;
    address constant KMS = 0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D;

    CusdPlusVault v = CusdPlusVault(PROXY);
    address user = makeAddr("v6-user");
    address owner;
    address router;
    uint256 supplyBefore;
    uint256 pPlusBefore;
    uint256 baselineBefore;
    CusdPlusVault impl;

    function setUp() public {
        if (PROXY.code.length == 0) return;
        owner = v.owner();
        router = v.stockRouter();
        supplyBefore = v.totalSupply();
        pPlusBefore = v.pPlus();
        baselineBefore = v.lastOraclePrice();
        impl = new CusdPlusVault(USDY, USDT, IM, WRAPPER, v.CONFIO_YIELD_SHARE_BPS());
    }

    function _upgrade() internal {
        vm.prank(owner);
        v.upgradeToAndCall(address(impl), abi.encodeCall(CusdPlusVault.initializeContinuousOracle, ()));
    }

    /// Ondo's token router rejects a stale Chainlink USDT round, and vm.warp
    /// ages the forked feed in a way the live chain never does.
    function _warp(uint256 dt) internal {
        (, int256 answer,,,) = IAggregator(USDT_FEED).latestRoundData();
        vm.warp(block.timestamp + dt);
        vm.mockCall(
            USDT_FEED,
            abi.encodeWithSelector(IAggregator.latestRoundData.selector),
            abi.encode(uint80(1), answer, block.timestamp, block.timestamp, uint80(1))
        );
    }

    function _mint(uint256 usdtIn) internal returns (uint256 shares) {
        deal(USDT, user, usdtIn);
        vm.prank(user, KMS);
        IERC20(USDT).approve(PROXY, type(uint256).max);
        vm.prank(user, KMS);
        shares = v.subscribeAndMint(usdtIn, 0, user);
    }

    function test_fork_upgradeKeepsStateAndArmsNewOracle() public {
        if (PROXY.code.length == 0) return;
        _upgrade();
        assertEq(address(v.ORACLE()), WRAPPER);
        assertEq(v.totalSupply(), supplyBefore, "supply");
        assertEq(v.owner(), owner, "owner");
        assertGe(v.pPlus(), pPlusBefore, "pPlus never falls");
        assertFalse(v.oracleGuardTripped(), "guard");
        assertEq(v.lastOraclePrice(), IOndoOracle(ONDO_ORACLE).getAssetPrice(USDY), "baseline = IM price");
        assertGe(v.backingRatioBps(), 10_000, "fully backed");
    }

    function test_fork_vaultStaysOnTheInstantManagerCurve() public {
        if (PROXY.code.length == 0) return;
        _upgrade();
        for (uint256 i = 0; i < 4; i++) {
            _warp(6 hours);
            v.accrue();
            assertFalse(v.oracleGuardTripped(), "guard stays quiet");
            assertEq(v.lastOraclePrice(), IOndoOracle(ONDO_ORACLE).getAssetPrice(USDY), "same curve");
            assertGe(v.backingRatioBps(), 10_000, "fully backed");
        }
    }

    /// A released build reads the stored pPlus, sizes shares to the wei, and
    /// the transaction lands later at a higher price.
    function test_fork_exactlySizedExitFromAnOlderBuildSettles() public {
        if (PROXY.code.length == 0) return;
        _upgrade();
        uint256 owned = _mint(100e18);
        _warp(90 minutes); // live curve has moved on
        v.accrue();
        _warp(45); // quote -> mined delay

        uint256 gross = 1.01e18;
        uint256 shares = Math.mulDiv(gross, 1e18, v.pPlus(), Math.Rounding.Ceil);
        assertLt(shares, owned);
        vm.prank(user);
        v.transfer(router, shares);
        vm.prank(router);
        uint256 out = v.redeemForStock(shares, gross, router);
        assertGe(out, gross, "exact floor met");
    }

    function test_fork_userExitStillOpen() public {
        if (PROXY.code.length == 0) return;
        _upgrade();
        uint256 shares = _mint(20e18);
        _warp(3 hours);
        vm.prank(user);
        assertGt(v.redeemToUsdt(shares, 1, user), 0);
        assertGe(v.backingRatioBps(), 10_000, "fully backed");
    }

    function test_fork_initializerRunsOnceAndOnlyForOwner() public {
        if (PROXY.code.length == 0) return;
        vm.prank(owner);
        v.upgradeToAndCall(address(impl), "");
        vm.expectRevert();
        vm.prank(user);
        v.initializeContinuousOracle();
        vm.prank(owner);
        v.initializeContinuousOracle();
        vm.expectRevert();
        vm.prank(owner);
        v.initializeContinuousOracle();
    }

    function test_fork_wideGapRefusesAndRollsBackUpgrade() public {
        if (PROXY.code.length == 0) return;
        address before = address(uint160(uint256(vm.load(
            PROXY, 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc))));
        vm.mockCall(
            WRAPPER,
            abi.encodeWithSignature("getPrice()"),
            abi.encode(baselineBefore * 9_997 / 10_000)
        );
        vm.expectRevert(bytes("oracle gap too wide"));
        vm.prank(owner);
        v.upgradeToAndCall(address(impl), abi.encodeCall(CusdPlusVault.initializeContinuousOracle, ()));
        assertEq(address(uint160(uint256(vm.load(
            PROXY, 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc)))), before);
    }
}
