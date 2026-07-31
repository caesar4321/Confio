// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ConfioVestingVault} from "../ConfioVestingVault.sol";

contract MockConfio is ERC20 {
    constructor() ERC20("Confio", "CONFIO") {}
    function mint(address to, uint256 amt) external { _mint(to, amt); }
}

contract ConfioVestingVaultTest is Test {
    MockConfio confio;
    ConfioVestingVault vault;

    address safeOwner = makeAddr("safeOwner");
    address founder = makeAddr("founder");
    address stranger = makeAddr("stranger");

    function setUp() public {
        confio = new MockConfio();
        vault = new ConfioVestingVault(address(confio), safeOwner);
        confio.mint(address(vault), 1_000_000_000e18); // treasury funds it
    }

    function _grant(address b, uint256 amt, uint64 dur) internal {
        vm.prank(safeOwner);
        vault.addGrant(b, amt, dur);
    }

    // ── Grant + linear vesting ───────────────────────────────────────

    function test_linear_vesting_half_then_full() public {
        _grant(founder, 360e18, 360 days);
        vm.prank(safeOwner);
        vault.startGrant(founder);

        assertEq(vault.claimableOf(founder), 0);
        vm.warp(block.timestamp + 180 days);
        assertEq(vault.claimableOf(founder), 180e18); // half

        vm.prank(founder);
        assertEq(vault.claim(), 180e18);
        assertEq(confio.balanceOf(founder), 180e18);

        vm.warp(block.timestamp + 180 days);
        assertEq(vault.claimableOf(founder), 180e18); // the rest
        vm.prank(founder);
        vault.claim();
        assertEq(confio.balanceOf(founder), 360e18);
        assertEq(vault.claimableOf(founder), 0);
    }

    function test_nothing_vests_before_start() public {
        _grant(founder, 360e18, 360 days);
        vm.warp(block.timestamp + 1000 days);
        assertEq(vault.claimableOf(founder), 0, "start==0 means nothing vests");
        vm.prank(founder);
        vm.expectRevert("nothing to claim");
        vault.claim();
    }

    function test_per_grant_durations_independent() public {
        address coBuilder = makeAddr("coBuilder");
        _grant(founder, 360e18, 360 days);
        _grant(coBuilder, 240e18, 240 days);
        vm.startPrank(safeOwner);
        vault.startGrant(founder);
        vault.startGrant(coBuilder);
        vm.stopPrank();
        vm.warp(block.timestamp + 240 days);
        assertEq(vault.claimableOf(coBuilder), 240e18, "co-builder fully vested");
        assertEq(vault.claimableOf(founder), 240e18, "founder 2/3");
    }

    // ── Solvency ─────────────────────────────────────────────────────

    function test_grant_requires_reserve() public {
        vm.prank(safeOwner);
        vault.withdrawSurplus(safeOwner, 1_000_000_000e18); // empty it
        vm.prank(safeOwner);
        vm.expectRevert("insufficient reserve");
        vault.addGrant(founder, 1e18, 100 days);
    }

    function test_surplus_bounded_by_obligations() public {
        _grant(founder, 360e18, 360 days);
        assertEq(vault.totalOwed(), 360e18);
        assertEq(vault.surplus(), 1_000_000_000e18 - 360e18);
        vm.prank(safeOwner);
        vm.expectRevert("exceeds surplus");
        vault.withdrawSurplus(safeOwner, 1_000_000_000e18 - 359e18);
    }

    function test_claim_reduces_owed() public {
        _grant(founder, 360e18, 360 days);
        vm.prank(safeOwner);
        vault.startGrant(founder);
        vm.warp(block.timestamp + 360 days);
        vm.prank(founder);
        vault.claim();
        assertEq(vault.totalOwed(), 0);
    }

    // ── Admin ────────────────────────────────────────────────────────

    function test_change_beneficiary_carries_progress() public {
        _grant(founder, 360e18, 360 days);
        vm.prank(safeOwner);
        vault.startGrant(founder);
        vm.warp(block.timestamp + 180 days);
        vm.prank(founder);
        vault.claim(); // 180 claimed

        address newAddr = makeAddr("founderNew");
        vm.prank(safeOwner);
        vault.changeBeneficiary(founder, newAddr);
        (uint128 alloc, uint128 claimed,,) = vault.grants(newAddr);
        assertEq(alloc, 360e18);
        assertEq(claimed, 180e18);
        (uint128 oldAlloc,,,) = vault.grants(founder);
        assertEq(oldAlloc, 0, "old address cleared");

        vm.warp(block.timestamp + 180 days);
        vm.prank(newAddr);
        assertEq(vault.claim(), 180e18); // the rest, to the new address
    }

    function test_revoke_only_before_start() public {
        _grant(founder, 360e18, 360 days);
        vm.prank(safeOwner);
        vault.revokeGrant(founder);
        assertEq(vault.totalOwed(), 0);
        assertEq(vault.surplus(), 1_000_000_000e18);

        _grant(founder, 360e18, 360 days);
        vm.prank(safeOwner);
        vault.startGrant(founder);
        vm.prank(safeOwner);
        vm.expectRevert("already started");
        vault.revokeGrant(founder);
    }

    function test_cannot_start_twice_or_missing() public {
        vm.prank(safeOwner);
        vm.expectRevert("no grant");
        vault.startGrant(founder);
        _grant(founder, 1e18, 100 days);
        vm.startPrank(safeOwner);
        vault.startGrant(founder);
        vm.expectRevert("already started");
        vault.startGrant(founder);
        vm.stopPrank();
    }

    function test_no_duplicate_grant() public {
        _grant(founder, 1e18, 100 days);
        vm.prank(safeOwner);
        vm.expectRevert("grant exists");
        vault.addGrant(founder, 1e18, 100 days);
    }

    function test_admin_functions_owner_only() public {
        vm.startPrank(stranger);
        vm.expectRevert();
        vault.addGrant(founder, 1e18, 100 days);
        vm.expectRevert();
        vault.withdrawSurplus(stranger, 1e18);
        vm.stopPrank();
    }

    function test_renounce_disabled() public {
        vm.prank(safeOwner);
        vm.expectRevert("renounce disabled");
        vault.renounceOwnership();
    }
}
