// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {IERC20Errors} from "@openzeppelin/contracts/interfaces/draft-IERC6093.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ConfioToken} from "../ConfioToken.sol";

contract ConfioTokenTest is Test {
    ConfioToken token;
    address treasury = makeAddr("treasurySafe");
    address user;
    uint256 userKey;

    function setUp() public {
        (user, userKey) = makeAddrAndKey("user");
        token = new ConfioToken(treasury);
    }

    function test_metadata_and_fixed_supply() public view {
        assertEq(token.name(), "Confio"); // ASCII by design: explorers escape accents
        assertEq(token.symbol(), "CONFIO");
        assertEq(token.decimals(), 18);
        assertEq(token.totalSupply(), 1_000_000_000e18);
        assertEq(token.balanceOf(treasury), 1_000_000_000e18);
    }

    function test_constructor_rejects_zero_treasury() public {
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableInvalidOwner.selector, address(0)));
        new ConfioToken(address(0));
    }

    function test_transfer_and_burn() public {
        vm.prank(treasury);
        token.transfer(user, 100e18);
        assertEq(token.balanceOf(user), 100e18);

        // holders can burn their own — supply shrinks, nothing can re-mint
        vm.prank(user);
        token.burn(40e18);
        assertEq(token.balanceOf(user), 60e18);
        assertEq(token.totalSupply(), 1_000_000_000e18 - 40e18);

        // burnFrom needs allowance like any transferFrom
        vm.prank(user);
        vm.expectRevert(
            abi.encodeWithSelector(
                IERC20Errors.ERC20InsufficientAllowance.selector, user, 0, 1e18
            )
        );
        token.burnFrom(treasury, 1e18);
    }

    function test_permit_signature_approval() public {
        vm.prank(treasury);
        token.transfer(user, 10e18);

        address spender = makeAddr("spender");
        uint256 deadline = block.timestamp + 1 hours;
        bytes32 structHash = keccak256(abi.encode(
            keccak256("Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)"),
            user, spender, 10e18, token.nonces(user), deadline
        ));
        bytes32 digest = keccak256(abi.encodePacked(hex"1901", token.DOMAIN_SEPARATOR(), structHash));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(userKey, digest);

        token.permit(user, spender, 10e18, deadline, v, r, s);
        assertEq(token.allowance(user, spender), 10e18);

        vm.prank(spender);
        token.transferFrom(user, spender, 10e18);
        assertEq(token.balanceOf(spender), 10e18);
    }

    function test_permit_cannot_be_replayed() public {
        address spender = makeAddr("spender");
        uint256 deadline = block.timestamp + 1 hours;
        bytes32 structHash = keccak256(abi.encode(
            keccak256("Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)"),
            user, spender, 10e18, token.nonces(user), deadline
        ));
        bytes32 digest = keccak256(abi.encodePacked(hex"1901", token.DOMAIN_SEPARATOR(), structHash));
        (uint8 v, bytes32 r, bytes32 sigS) = vm.sign(userKey, digest);
        token.permit(user, spender, 10e18, deadline, v, r, sigS);
        vm.expectRevert(); token.permit(user, spender, 10e18, deadline, v, r, sigS);
        assertEq(token.nonces(user), 1);
    }

    // ═════════════════════════ Incident controls ════════════════════════

    address hacker = makeAddr("hacker");
    address victim = makeAddr("victim");
    address fastKey = makeAddr("fastKey");
    address stranger = makeAddr("stranger");

    function _fundHacker() internal {
        vm.prank(treasury);
        token.transfer(hacker, 100e18);
    }

    function _freezeHacker() internal {
        vm.prank(treasury);
        token.freeze(hacker, uint64(block.timestamp + 30 days));
    }

    function test_treasury_starts_as_owner_and_guardian() public view {
        assertEq(token.owner(), treasury);
        assertEq(token.guardian(), treasury);
    }

    function test_frozen_address_cannot_send_receive_or_burn() public {
        _fundHacker();
        vm.prank(hacker);
        token.approve(stranger, type(uint256).max);
        _freezeHacker();

        vm.startPrank(hacker);
        vm.expectRevert(abi.encodeWithSelector(ConfioToken.AddressFrozen.selector, hacker));
        token.transfer(stranger, 1);
        vm.expectRevert(abi.encodeWithSelector(ConfioToken.AddressFrozen.selector, hacker));
        token.burn(1);
        vm.stopPrank();

        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(ConfioToken.AddressFrozen.selector, hacker));
        token.transferFrom(hacker, stranger, 1);

        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(ConfioToken.AddressFrozen.selector, hacker));
        token.transfer(hacker, 1);
    }

    function test_freeze_lapses_on_its_own_and_unfreeze_is_owner_only() public {
        _fundHacker();
        _freezeHacker();
        vm.prank(stranger);
        vm.expectRevert();
        token.unfreeze(hacker);

        vm.warp(block.timestamp + 30 days);
        assertFalse(token.isFrozen(hacker));
        vm.prank(hacker);
        token.transfer(stranger, 1);
    }

    function test_guardian_bounds() public {
        vm.prank(treasury);
        token.setGuardian(fastKey);
        vm.prank(treasury);
        token.setProtected(stranger, true);
        uint64 limit = uint64(block.timestamp) + token.MAX_GUARDIAN_FREEZE();

        vm.startPrank(fastKey);
        vm.expectRevert(abi.encodeWithSelector(ConfioToken.FreezeTooLong.selector, limit + 1, limit));
        token.freeze(hacker, limit + 1);
        vm.expectRevert(abi.encodeWithSelector(ConfioToken.ProtectedAddress.selector, stranger));
        token.freeze(stranger, limit);
        token.freeze(hacker, limit);
        vm.expectRevert();
        token.unfreeze(hacker);
        vm.expectRevert(abi.encodeWithSelector(ConfioToken.CannotShortenFreeze.selector, limit - 1, limit));
        token.freeze(hacker, limit - 1);
        vm.stopPrank();
        assertTrue(token.isFrozen(hacker));

        // The owner can reach a protected address; the guardian can't.
        vm.prank(treasury);
        token.freeze(stranger, limit);
        assertTrue(token.isFrozen(stranger));
    }

    function test_guardian_cannot_renew_past_one_episode() public {
        vm.prank(treasury);
        token.setGuardian(fastKey);
        uint64 limit = uint64(block.timestamp) + token.MAX_GUARDIAN_FREEZE();

        vm.prank(fastKey);
        token.freeze(hacker, limit);

        vm.warp(block.timestamp + 13 days);
        vm.prank(fastKey);
        vm.expectRevert(abi.encodeWithSelector(ConfioToken.FreezeTooLong.selector, limit + 1, limit));
        token.freeze(hacker, limit + 1);

        // Lapsed but still cooling down: nothing further.
        vm.warp(uint256(limit) + 1);
        assertFalse(token.isFrozen(hacker));
        vm.prank(fastKey);
        vm.expectRevert();
        token.freeze(hacker, uint64(block.timestamp + 1));

        vm.warp(uint256(limit) + token.GUARDIAN_COOLDOWN());
        vm.prank(fastKey);
        token.freeze(hacker, uint64(block.timestamp + 1));
        assertTrue(token.isFrozen(hacker));
    }

    function test_freeze_rejects_bad_input() public {
        vm.prank(stranger);
        vm.expectRevert(ConfioToken.NotFreezer.selector);
        token.freeze(hacker, uint64(block.timestamp + 1));

        vm.startPrank(treasury);
        vm.expectRevert(ConfioToken.ZeroAddress.selector);
        token.freeze(address(0), uint64(block.timestamp + 1));
        vm.expectRevert(abi.encodeWithSelector(ConfioToken.FreezeInPast.selector, uint64(block.timestamp)));
        token.freeze(hacker, uint64(block.timestamp));
        uint64 limit = uint64(block.timestamp) + token.MAX_OWNER_FREEZE();
        vm.expectRevert(abi.encodeWithSelector(ConfioToken.FreezeTooLong.selector, limit + 1, limit));
        token.freeze(hacker, limit + 1);
        vm.stopPrank();
    }

    function test_recovery_returns_balance_without_changing_supply() public {
        _fundHacker();
        _freezeHacker();
        vm.prank(treasury);
        uint256 id = token.proposeRecovery(hacker, victim, 60e18);

        vm.prank(treasury);
        vm.expectRevert();
        token.executeRecovery(id);

        vm.warp(block.timestamp + token.RECOVERY_DELAY());
        vm.prank(treasury);
        token.executeRecovery(id);

        assertEq(token.balanceOf(victim), 60e18);
        assertEq(token.balanceOf(hacker), 40e18);
        assertEq(token.totalSupply(), token.TOTAL_SUPPLY());

        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(ConfioToken.NoSuchRecovery.selector, id));
        token.executeRecovery(id);
    }

    function test_recovery_needs_a_frozen_source_for_its_whole_wait() public {
        _fundHacker();
        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(ConfioToken.NotFrozen.selector, hacker));
        token.proposeRecovery(hacker, victim, 1);

        _freezeHacker();
        vm.startPrank(treasury);
        uint256 id = token.proposeRecovery(hacker, victim, 1);
        token.unfreeze(hacker);
        vm.warp(block.timestamp + token.RECOVERY_DELAY());
        vm.expectRevert(abi.encodeWithSelector(ConfioToken.NotFrozen.selector, hacker));
        token.executeRecovery(id);
        vm.stopPrank();
    }

    function test_recovery_rejects_frozen_recipient_and_outsiders() public {
        _fundHacker();
        _freezeHacker();
        vm.prank(treasury);
        token.freeze(victim, uint64(block.timestamp + 30 days));
        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(ConfioToken.AddressFrozen.selector, victim));
        token.proposeRecovery(hacker, victim, 1);
        vm.prank(stranger);
        vm.expectRevert();
        token.proposeRecovery(hacker, stranger, 1);
    }

    function test_guardian_can_cancel_a_recovery() public {
        _fundHacker();
        _freezeHacker();
        vm.prank(treasury);
        uint256 id = token.proposeRecovery(hacker, victim, 1);
        vm.prank(treasury);
        token.setGuardian(fastKey);

        vm.prank(stranger);
        vm.expectRevert(ConfioToken.NotFreezer.selector);
        token.cancelRecovery(id);

        vm.prank(fastKey);
        token.cancelRecovery(id);
        vm.warp(block.timestamp + token.RECOVERY_DELAY());
        vm.prank(treasury);
        vm.expectRevert(abi.encodeWithSelector(ConfioToken.NoSuchRecovery.selector, id));
        token.executeRecovery(id);
    }

    function test_renounce_ends_every_control() public {
        _fundHacker();
        _freezeHacker();
        vm.prank(treasury);
        token.renounceOwnership();
        assertEq(token.owner(), address(0));
        assertEq(token.guardian(), address(0));

        vm.prank(treasury);
        vm.expectRevert(ConfioToken.NotFreezer.selector);
        token.freeze(stranger, uint64(block.timestamp + 1));

        vm.warp(block.timestamp + token.MAX_OWNER_FREEZE());
        vm.prank(hacker);
        token.transfer(stranger, 1);
    }

    function testFuzz_no_path_raises_supply(uint96 seed) public {
        uint256 amount = bound(uint256(seed), 1, 100e18);
        _fundHacker();
        _freezeHacker();
        vm.prank(treasury);
        uint256 id = token.proposeRecovery(hacker, victim, amount);
        vm.warp(block.timestamp + token.RECOVERY_DELAY());
        vm.prank(treasury);
        token.executeRecovery(id);
        vm.prank(victim);
        token.burn(amount);
        assertEq(token.totalSupply(), token.TOTAL_SUPPLY() - amount);
    }
}
