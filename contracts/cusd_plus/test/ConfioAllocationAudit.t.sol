// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ConfioToken} from "../ConfioToken.sol";
import {ConfioVestingVault} from "../ConfioVestingVault.sol";
import {ConfioPresaleVault} from "../ConfioPresaleVault.sol";
import {ConfioRewardVault} from "../ConfioRewardVault.sol";

contract AllocationPayment is ERC20 {
    constructor() ERC20("cUSD test", "cUSD") {}
}

/// Integration tests use the actual fixed-supply token and five separate
/// allocation addresses. No private keys, RPC, mainnet fork or broadcast.
contract ConfioAllocationAuditTest is Test {
    ConfioToken token;
    ConfioVestingVault[3] vesting;
    ConfioPresaleVault presale;
    ConfioRewardVault rewards;
    address safe = makeAddr("treasurySafe");
    address sponsor = makeAddr("sponsor");
    address outsider = makeAddr("outsider");
    uint256[3] amounts = [uint256(893_600_000e18), 10_000_000e18, 15_000_000e18];
    // The existing legacy convention is 365-day years; culture is 90 days.
    uint64[3] durations = [uint64(1095 days), 730 days, 90 days];

    function setUp() public {
        token = new ConfioToken(safe);
        for (uint256 i; i < 3; ++i) vesting[i] = new ConfioVestingVault(address(token), safe);
        uint256[] memory b = new uint256[](3);
        (b[0], b[1], b[2]) = (4_000_000e18, 24_000_000e18, 74_000_000e18);
        uint256[] memory p = new uint256[](4);
        (p[0], p[1], p[2], p[3]) = (0.2e18, 0.3e18, 0.7e18, 1.3e18);
        presale = new ConfioPresaleVault(safe, IERC20(address(new AllocationPayment())), b, p, 0, 0, 0, 0, sponsor);
        rewards = new ConfioRewardVault(address(token), sponsor, safe);
        vm.startPrank(safe);
        token.transfer(address(presale), 74_000_000e18);
        presale.setConfioToken(IERC20(address(token)));
        token.transfer(address(rewards), 7_400_000e18);
        for (uint256 i; i < 3; ++i) {
            token.transfer(address(vesting[i]), amounts[i]);
            vesting[i].addGrant(safe, amounts[i], durations[i]);
        }
        vm.stopPrank();
    }

    function test_all_five_allocations_match_tokenomics_without_starting_clocks() public view {
        uint256 total = token.balanceOf(address(presale)) + token.balanceOf(address(rewards));
        assertEq(token.balanceOf(address(presale)), 74_000_000e18);
        assertEq(token.balanceOf(address(rewards)), 7_400_000e18);
        assertFalse(presale.claimsUnlocked());
        assertFalse(rewards.claimsUnlocked());
        for (uint256 i; i < 3; ++i) {
            (uint128 allocated, uint128 claimed, uint64 start, uint64 duration) = vesting[i].grants(safe);
            assertEq(allocated, amounts[i]);
            assertEq(claimed, 0);
            assertEq(start, 0);
            assertEq(duration, durations[i]);
            assertEq(vesting[i].totalOwed(), amounts[i]);
            assertEq(vesting[i].surplus(), 0);
            assertEq(token.balanceOf(address(vesting[i])), amounts[i]);
            total += token.balanceOf(address(vesting[i]));
        }
        assertEq(total, 1_000_000_000e18);
        assertEq(token.totalSupply(), total);
        assertEq(token.balanceOf(safe), 0);
    }

    function test_decades_without_dex_do_not_vest_or_permit_claims() public {
        vm.warp(block.timestamp + 30 * 365 days);
        for (uint256 i; i < 3; ++i) {
            assertEq(vesting[i].vestedOf(safe), 0);
            assertEq(vesting[i].claimableOf(safe), 0);
            vm.prank(safe);
            vm.expectRevert("nothing to claim");
            vesting[i].claim();
            vm.prank(safe);
            vm.expectRevert("exceeds surplus");
            vesting[i].withdrawSurplus(safe, 1);
        }
    }

    function test_each_placeholder_can_move_without_starting_other_vaults() public {
        vm.warp(block.timestamp + 400 days);
        address beneficiary = makeAddr("confirmedBeneficiary");
        vm.prank(safe);
        vesting[1].changeBeneficiary(safe, beneficiary);
        (uint128 amount, uint128 claimed, uint64 start, uint64 duration) = vesting[1].grants(beneficiary);
        assertEq(amount, amounts[1]);
        assertEq(claimed, 0);
        assertEq(start, 0);
        assertEq(duration, durations[1]);
        assertEq(vesting[1].claimableOf(safe), 0);
        assertEq(vesting[1].totalOwed(), amounts[1]);
        vm.prank(safe);
        vesting[1].startGrant(beneficiary);
        vm.warp(block.timestamp + durations[1]);
        vm.prank(beneficiary);
        assertEq(vesting[1].claim(), amounts[1]);
        assertEq(vesting[0].claimableOf(safe), 0);
        assertEq(vesting[2].claimableOf(safe), 0);
    }

    function test_cultural_pool_can_split_before_start_without_double_allocation() public {
        ConfioVestingVault cultural = vesting[2];
        address first = makeAddr("culturalFirst");
        address second = makeAddr("culturalSecond");
        vm.startPrank(safe);
        cultural.revokeGrant(safe);
        cultural.addGrant(first, 6_000_000e18, 90 days);
        cultural.addGrant(second, 9_000_000e18, 90 days);
        vm.expectRevert("insufficient reserve");
        cultural.addGrant(makeAddr("extra"), 1, 90 days);
        vm.stopPrank();
        assertEq(cultural.totalOwed(), 15_000_000e18);
        assertEq(cultural.surplus(), 0);
        assertEq(cultural.claimableOf(first), 0);
        assertEq(cultural.claimableOf(second), 0);
    }

    function test_pending_owner_has_no_authority_until_acceptance() public {
        address nextOwner = makeAddr("replacementSafe");
        vm.prank(safe);
        vesting[0].transferOwnership(nextOwner);
        vm.prank(nextOwner);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, nextOwner));
        vesting[0].startGrant(safe);
        vm.prank(outsider);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, outsider));
        vesting[0].acceptOwnership();
        vm.prank(nextOwner);
        vesting[0].acceptOwnership();
        vm.prank(safe);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, safe));
        vesting[0].startGrant(safe);
        vm.prank(nextOwner);
        vesting[0].changeBeneficiary(safe, nextOwner);
        (,, uint64 start,) = vesting[0].grants(nextOwner);
        assertEq(start, 0);
    }

    function test_all_vesting_admin_paths_reject_outsiders() public {
        bytes memory denied = abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, outsider);
        vm.startPrank(outsider);
        vm.expectRevert(denied); vesting[0].addGrant(outsider, 1, 1);
        vm.expectRevert(denied); vesting[0].startGrant(safe);
        vm.expectRevert(denied); vesting[0].revokeGrant(safe);
        vm.expectRevert(denied); vesting[0].changeBeneficiary(safe, outsider);
        vm.expectRevert(denied); vesting[0].withdrawSurplus(outsider, 1);
        vm.expectRevert(denied); vesting[0].transferOwnership(outsider);
        vm.expectRevert(denied); vesting[0].renounceOwnership();
        vm.stopPrank();
    }

    function testFuzz_move_after_partial_claim_preserves_exact_entitlement(uint32 elapsedSeed) public {
        uint256 elapsed = bound(elapsedSeed, 1, durations[0] - 1);
        vm.prank(safe); vesting[0].startGrant(safe);
        vm.warp(block.timestamp + elapsed);
        vm.prank(safe); uint256 paid = vesting[0].claim();
        address recipient = makeAddr("finalFounder");
        vm.prank(safe); vesting[0].changeBeneficiary(safe, recipient);
        assertEq(vesting[0].totalOwed(), amounts[0] - paid);
        assertEq(vesting[0].claimableOf(recipient), 0);
        vm.prank(safe);
        vm.expectRevert("nothing to claim"); vesting[0].claim();
        vm.warp(block.timestamp + durations[0]);
        vm.prank(recipient); uint256 rest = vesting[0].claim();
        assertEq(paid + rest, amounts[0]);
        assertEq(vesting[0].totalOwed(), 0);
        assertEq(token.balanceOf(address(vesting[0])), 0);
    }

    function test_prestart_revocation_is_retained_but_active_revocation_is_blocked() public {
        vm.startPrank(safe);
        vesting[0].revokeGrant(safe);
        assertEq(vesting[0].surplus(), amounts[0]);
        vesting[0].addGrant(safe, amounts[0], durations[0]);
        vesting[0].startGrant(safe);
        vm.expectRevert("already started"); vesting[0].revokeGrant(safe);
        vm.stopPrank();
    }
}
