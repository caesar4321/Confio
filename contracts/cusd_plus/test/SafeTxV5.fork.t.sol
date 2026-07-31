// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * THE EXACT SAFE TRANSACTION, replayed against live BSC state. Run:
 *
 *   forge test --match-path test/SafeTxV5.fork.t.sol \
 *     --fork-url https://bsc-dataseed.bnbchain.org -vv
 *
 * UpgradeRehearsalV5 rehearses the upgrade by CONSTRUCTING the call in
 * Solidity. This file does something narrower and stricter: it takes the
 * literal calldata bytes handed to the Safe signers and executes THOSE,
 * as the Safe, against the DEPLOYED implementation. If the bytes in the
 * signing UI differ from what we think they are, this fails.
 */
import {Test} from "forge-std/Test.sol";
import {CusdPlusVault} from "../CusdPlusVault.sol";

contract SafeTxV5ForkTest is Test {
    address constant PROXY = 0x3C29417eb4314155e63d4C7D4507852b87763Ed1;
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    address constant IMPL_V5 = 0xAa9AFf7CD9B995DF7d54B1e646e2746a90DbF5a9;
    address constant KMS = 0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D;

    /// The bytes the signers will see, verbatim.
    bytes constant SAFE_DATA =
        hex"4f1ef286000000000000000000000000aa9aff7cd9b995df7d54b1e646e2746a90dbf5a9"
        hex"0000000000000000000000000000000000000000000000000000000000000040"
        hex"0000000000000000000000000000000000000000000000000000000000000044"
        hex"84a7ebcd000000000000000000000000f9f93ba8ebf50515ed2729eb07657c8298cdfc9d"
        hex"0000000000000000000000000000000000000000000000000000000000000001"
        hex"00000000000000000000000000000000000000000000000000000000";

    function test_fork_theSafeCalldataDoesExactlyWhatWeClaim() public {
        if (PROXY.code.length == 0) return; // clean skip without --fork-url
        CusdPlusVault v = CusdPlusVault(PROXY);

        assertGt(IMPL_V5.code.length, 0, "v5 implementation is deployed");

        uint256 prePPlus = v.pPlus();
        uint256 preLast = v.lastOraclePrice();
        uint256 preSupply = v.totalSupply();

        // Execute the literal bytes, as the Safe, with operation = CALL.
        vm.prank(SAFE);
        (bool ok, ) = PROXY.call(SAFE_DATA);
        assertTrue(ok, "Safe transaction succeeds");

        // Upgraded, state intact, gate armed in the same transaction.
        assertEq(
            address(uint160(uint256(vm.load(
                PROXY,
                0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc // ERC-1967 impl slot
            )))),
            IMPL_V5,
            "implementation slot now points at v5"
        );
        assertEq(v.pPlus(), prePPlus, "pPlus survived");
        assertEq(v.lastOraclePrice(), preLast, "lastOraclePrice survived");
        assertEq(v.totalSupply(), preSupply, "supply survived");
        assertEq(v.owner(), SAFE, "owner survived");
        assertTrue(v.isSponsor(KMS), "KMS armed atomically");

        // And the gate is actually live.
        address outsider = makeAddr("outsider");
        vm.prank(outsider, outsider);
        vm.expectRevert("not sponsored");
        v.subscribeAndMint(1e18, 0, outsider);
    }
}
