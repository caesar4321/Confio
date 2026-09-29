// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {StdInvariant} from "forge-std/StdInvariant.sol";
import {ConfioToken} from "../ConfioToken.sol";
import {ConfioVestingVault} from "../ConfioVestingVault.sol";

contract ConfioVestingAuditHandler is Test {
    ConfioToken public token;
    ConfioVestingVault public vault;
    uint256 public deposited;
    uint256 public paid;
    uint256 public withdrawn;
    address[8] public beneficiaries;

    constructor() {
        token = new ConfioToken(address(this));
        vault = new ConfioVestingVault(address(token), address(this));
        for (uint256 i; i < 8; ++i) beneficiaries[i] = address(uint160(0x10000 + i));
        token.transfer(address(vault), 893_600_000e18);
        deposited = 893_600_000e18;
        vault.addGrant(beneficiaries[0], 893_600_000e18, uint64(1095 days));
    }

    function add(uint8 seed, uint128 amountSeed, uint32 durationSeed) external {
        address who = beneficiaries[seed % 8];
        (uint128 allocated,,,) = vault.grants(who);
        uint256 available = vault.surplus();
        if (allocated != 0 || available == 0) return;
        uint256 amount = bound(amountSeed, 1, available);
        uint64 duration = uint64(bound(durationSeed, 1, 1095 days));
        vault.addGrant(who, amount, duration);
    }

    function start(uint8 seed) external {
        address who = beneficiaries[seed % 8];
        (uint128 amount,, uint64 began,) = vault.grants(who);
        if (amount == 0 || began != 0) return;
        vault.startGrant(who);
    }

    function revoke(uint8 seed) external {
        address who = beneficiaries[seed % 8];
        (uint128 amount,, uint64 began,) = vault.grants(who);
        if (amount == 0 || began != 0) return;
        vault.revokeGrant(who);
    }

    function move(uint8 fromSeed, uint8 toSeed) external {
        address from = beneficiaries[fromSeed % 8];
        address to = beneficiaries[toSeed % 8];
        (uint128 amount,,,) = vault.grants(from);
        (uint128 target,,,) = vault.grants(to);
        if (from == to || amount == 0 || target != 0) return;
        vault.changeBeneficiary(from, to);
    }

    function claim(uint8 seed) external {
        address who = beneficiaries[seed % 8];
        if (vault.claimableOf(who) == 0) return;
        vm.prank(who);
        paid += vault.claim();
    }

    function elapse(uint32 seed) external {
        vm.warp(block.timestamp + bound(seed, 1, 180 days));
    }

    function withdraw(uint128 seed) external {
        uint256 available = vault.surplus();
        if (available == 0) return;
        uint256 amount = bound(seed, 1, available);
        withdrawn += amount;
        vault.withdrawSurplus(address(this), amount);
    }

    function fund(uint128 seed) external {
        uint256 available = token.balanceOf(address(this));
        if (available == 0) return;
        uint256 amount = bound(seed, 1, available);
        deposited += amount;
        token.transfer(address(vault), amount);
    }
}

contract ConfioVestingInvariantTest is StdInvariant, Test {
    ConfioVestingAuditHandler handler;
    ConfioVestingVault vault;
    ConfioToken token;

    function setUp() public {
        handler = new ConfioVestingAuditHandler();
        vault = handler.vault();
        token = handler.token();
        bytes4[] memory selectors = new bytes4[](8);
        selectors[0] = handler.add.selector;
        selectors[1] = handler.start.selector;
        selectors[2] = handler.revoke.selector;
        selectors[3] = handler.move.selector;
        selectors[4] = handler.claim.selector;
        selectors[5] = handler.elapse.selector;
        selectors[6] = handler.withdraw.selector;
        selectors[7] = handler.fund.selector;
        targetSelector(FuzzSelector(address(handler), selectors));
        targetContract(address(handler));
    }

    function invariant_grants_remain_solvent_and_conserve_tokens() public view {
        uint256 owed;
        uint256 actualPaid;
        for (uint256 i; i < 8; ++i) {
            address who = handler.beneficiaries(i);
            (uint128 allocated, uint128 claimed, uint64 start,) = vault.grants(who);
            assertLe(claimed, allocated);
            owed += uint256(allocated) - claimed;
            actualPaid += token.balanceOf(who);
            if (start == 0) {
                assertEq(claimed, 0);
                assertEq(vault.claimableOf(who), 0);
            }
        }
        uint256 balance = token.balanceOf(address(vault));
        assertEq(vault.totalOwed(), owed);
        assertGe(balance, owed);
        assertEq(vault.surplus(), balance - owed);
        assertEq(actualPaid, handler.paid());
        assertEq(balance + handler.paid() + handler.withdrawn(), handler.deposited());
        assertEq(balance + actualPaid + token.balanceOf(address(handler)), token.totalSupply());
    }
}
