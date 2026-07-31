// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * Proves the two Safe transactions make the LIVE ConfioRewardVault
 * operational, by replaying their literal calldata against BSC state. Run:
 *
 *   forge test --match-path test/RewardFunding.fork.t.sol \
 *     --fork-url https://bsc-dataseed.bnbchain.org -vv
 *
 * TX1 (Safe): setManualPrice($0.20)
 * TX2 (Safe): CONFIO.transfer(vault, 50,000)
 * Then the attestor (KMS sponsor) calls setEligible and a user claims —
 * the whole path the funding unlocks.
 */
import {Test} from "forge-std/Test.sol";
import {ConfioRewardVault} from "../ConfioRewardVault.sol";

interface IERC20 {
    function balanceOf(address) external view returns (uint256);
}

contract RewardFundingForkTest is Test {
    address constant VAULT = 0x1766A2Ac798dA2247E5Da6E410453D526FD2f6ab;
    address constant CONFIO = 0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8;
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    address constant ATTESTOR = 0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D;

    // The literal calldata handed to the Safe signers.
    bytes constant SET_PRICE =
        hex"d7a7186800000000000000000000000000000000000000000000000002c68af0bb140000";
    bytes constant FUND =
        hex"a9059cbb0000000000000000000000001766a2ac798da2247e5da6e410453d526fd2f6ab000000000000000000000000000000000000000000000a968163f0a57b400000";

    address user = makeAddr("reward-user");
    address referrer = makeAddr("reward-referrer");

    function test_fork_funding_makes_vault_operational() public {
        if (VAULT.code.length == 0) return; // skip cleanly without --fork-url
        ConfioRewardVault v = ConfioRewardVault(VAULT);

        // Pre: unpriced, empty.
        assertEq(v.priceRound(), 0);
        assertEq(IERC20(CONFIO).balanceOf(VAULT), 0);

        // TX1 + TX2 exactly as the Safe will run them.
        vm.prank(SAFE);
        (bool ok1,) = VAULT.call(SET_PRICE);
        assertTrue(ok1, "setManualPrice");
        vm.prank(SAFE);
        (bool ok2,) = CONFIO.call(FUND);
        assertTrue(ok2, "fund");

        assertEq(v.priceRound(), 1, "price active, round bumped");
        assertEq(v.manualPrice(), 0.20e18);
        assertEq(IERC20(CONFIO).balanceOf(VAULT), 50_000e18, "tranche funded");
        assertEq(v.quoteConfio(5e18), 25e18, "$5 = 25 CONFIO at $0.20");

        // Now the attestor can actually write eligibility (this reverted
        // before funding — insufficient reserve).
        vm.prank(ATTESTOR);
        v.setEligible(user, 5e18, 1, referrer, 25e18); // $5 → 25 CONFIO, +25 to referrer
        (uint128 amount,,,,,) = v.rewards(user);
        assertEq(amount, 25e18);
        assertEq(v.outstanding(), 50e18); // 25 main + 25 referral

        // And both sides can claim from the funded balance.
        vm.prank(user);
        assertEq(v.claim(), 25e18);
        vm.prank(referrer);
        assertEq(v.claimReferral(user), 25e18);
        assertEq(IERC20(CONFIO).balanceOf(user), 25e18);
        assertEq(IERC20(CONFIO).balanceOf(referrer), 25e18);
        assertEq(v.surplus(), 50_000e18 - 50e18, "rest stays as surplus");
    }
}
