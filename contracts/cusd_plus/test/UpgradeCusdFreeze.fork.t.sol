// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {CusdVault} from "../CusdVault.sol";

/**
 * Rehearses the freeze upgrade against the live cUSD proxy. What only the
 * fork proves: the appended `frozen` slot leaves live state untouched.
 *
 * BSC_RPC_URL=<rpc> [CUSD_IMPL=<deployed candidate>] \
 *   forge test --match-contract UpgradeCusdFreeze
 *
 * Skips without BSC_RPC_URL. Before the Safe upgrades, set CUSD_IMPL so this
 * tests the implementation actually being installed.
 */
contract UpgradeCusdFreezeForkTest is Test {
    CusdVault constant CUSD = CusdVault(0x6101cC370635cF2c7f2725EaB010aC407A8d543F);
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    address constant SPONSOR = 0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D;

    function test_upgrade_preserves_state_and_enables_freeze() public {
        string memory rpc = vm.envOr("BSC_RPC_URL", string(""));
        if (bytes(rpc).length == 0) {
            vm.skip(true);
            return;
        }
        vm.createSelectFork(rpc);

        uint256 supply = CUSD.totalSupply();
        uint256 feeBps = CUSD.feeBps();
        uint256 entryFees = CUSD.accruedEntryFees();
        uint256 exitFees = CUSD.accruedExitFees();
        address savings = CUSD.savingsVault();
        bool sponsored = CUSD.isSponsor(SPONSOR);
        address usdt = address(CUSD.USDT());
        bool backed = CUSD.isFullyBacked();

        address candidate = vm.envOr("CUSD_IMPL", address(0));
        CusdVault impl = candidate == address(0) ? new CusdVault(usdt) : CusdVault(candidate);
        assertEq(address(impl.USDT()), usdt);
        vm.prank(SAFE);
        CUSD.upgradeToAndCall(address(impl), "");

        assertEq(CUSD.totalSupply(), supply);
        assertEq(CUSD.feeBps(), feeBps);
        assertEq(CUSD.accruedEntryFees(), entryFees);
        assertEq(CUSD.accruedExitFees(), exitFees);
        assertEq(CUSD.savingsVault(), savings);
        assertEq(CUSD.isSponsor(SPONSOR), sponsored);
        assertEq(CUSD.owner(), SAFE);
        assertEq(CUSD.isFullyBacked(), backed);
        assertFalse(CUSD.frozen(SPONSOR));

        address target = makeAddr("target");
        vm.prank(SAFE);
        CUSD.freezeAddress(target);
        assertTrue(CUSD.frozen(target));
    }
}
