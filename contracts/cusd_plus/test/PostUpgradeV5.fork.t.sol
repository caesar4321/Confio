// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * POST-UPGRADE verification against the LIVE, ALREADY-UPGRADED proxy
 * (v5 executed at Safe nonce 4, 2026-07-31). Run:
 *
 *   forge test --match-path test/PostUpgradeV5.fork.t.sol \
 *     --fork-url https://bsc-dataseed.bnbchain.org -vv
 *
 * Unlike UpgradeRehearsalV5 (which upgrades a v4 proxy itself), this
 * exercises the implementation that is ACTUALLY DEPLOYED — no upgrade
 * step, no locally built impl. It answers the only question left after
 * the Safe transaction landed: does the production mint path still work,
 * and is the exit still open?
 */
import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {CusdPlusVault} from "../CusdPlusVault.sol";

contract PostUpgradeV5ForkTest is Test {
    address constant PROXY = 0x3C29417eb4314155e63d4C7D4507852b87763Ed1;
    address constant IMPL_V5 = 0xAa9AFf7CD9B995DF7d54B1e646e2746a90DbF5a9;
    address constant USDT = 0x55d398326f99059fF775485246999027B3197955;
    address constant KMS = 0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D;
    bytes32 constant IMPL_SLOT =
        0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc;

    CusdPlusVault v = CusdPlusVault(PROXY);
    address user = makeAddr("prod-like-user");

    function _forked() internal view returns (bool) {
        return PROXY.code.length > 0;
    }

    function test_fork_liveProxyIsV5WithGateArmed() public view {
        if (!_forked()) return;
        assertEq(
            address(uint160(uint256(vm.load(PROXY, IMPL_SLOT)))),
            IMPL_V5,
            "live proxy runs the v5 implementation"
        );
        assertTrue(v.isSponsor(KMS), "KMS sponsor armed");
        assertFalse(v.isSponsor(address(0xdead)), "nobody else is");
    }

    /// THE production path: user EOA is msg.sender (7702), KMS is tx.origin.
    /// If this broke, every app deposit would stop minting.
    function test_fork_productionRelayedMintStillWorks() public {
        if (!_forked()) return;
        deal(USDT, user, 500e18);

        vm.prank(user, KMS);
        IERC20(USDT).approve(PROXY, type(uint256).max);
        vm.prank(user, KMS);
        uint256 shares = v.subscribeAndMint(100e18, 0, user);

        assertGt(shares, 0, "relayed mint produced shares");
        assertEq(v.balanceOf(user), shares);
    }

    function test_fork_unsponsoredMintRejected() public {
        if (!_forked()) return;
        deal(USDT, user, 500e18);
        vm.startPrank(user, user); // no sponsor anywhere in the tx
        IERC20(USDT).approve(PROXY, type(uint256).max);
        vm.expectRevert("not sponsored");
        v.subscribeAndMint(100e18, 0, user);
        vm.stopPrank();
    }

    function test_fork_sponsoredMintCannotCreditAThirdParty() public {
        if (!_forked()) return;
        deal(USDT, user, 500e18);
        vm.prank(user, KMS);
        IERC20(USDT).approve(PROXY, type(uint256).max);
        vm.prank(user, KMS);
        vm.expectRevert("recipient not caller");
        v.subscribeAndMint(100e18, 0, makeAddr("ineligible"));
    }

    /// The exit must not depend on Confío at all.
    function test_fork_exitWorksWithNoSponsorInvolvement() public {
        if (!_forked()) return;
        deal(USDT, user, 500e18);
        vm.prank(user, KMS);
        IERC20(USDT).approve(PROXY, type(uint256).max);
        vm.prank(user, KMS);
        uint256 shares = v.subscribeAndMint(100e18, 0, user);

        uint256 before = IERC20(USDT).balanceOf(user);
        vm.prank(user, user); // user's OWN transaction, no sponsor
        uint256 out = v.redeemToUsdt(shares, 0, user);
        assertGt(out, 0, "exit open without Confio");
        assertEq(IERC20(USDT).balanceOf(user), before + out);
    }
}
