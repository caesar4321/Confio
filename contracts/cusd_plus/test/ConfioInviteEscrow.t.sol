// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ConfioInviteEscrow} from "../ConfioInviteEscrow.sol";

contract MockToken is ERC20 {
    constructor(string memory n) ERC20(n, n) {}

    function mint(address to, uint256 amt) external {
        _mint(to, amt);
    }
}

contract MockInviteCusdPlus is ERC20 {
    MockToken public immutable CUSD;

    constructor(MockToken cusd) ERC20("cUSD+", "cUSD+") {
        CUSD = cusd;
    }

    function mint(address to, uint256 amt) external {
        _mint(to, amt);
    }

    function unwrapToCusd(uint256 shares, uint256 minOut, address to) external returns (uint256) {
        _burn(msg.sender, shares);
        require(shares >= minOut, "slippage");
        CUSD.mint(to, shares);
        return shares;
    }

    function wrapCusd(uint256 amount, uint256 minOut, address to) external returns (uint256) {
        CUSD.transferFrom(msg.sender, address(this), amount);
        require(amount >= minOut, "slippage");
        _mint(to, amount);
        return amount;
    }
}

contract ConfioInviteEscrowTest is Test {
    MockInviteCusdPlus cusdPlus;
    MockToken cusd;
    MockToken confio;
    MockToken alien;
    ConfioInviteEscrow escrow;

    address safeOwner = makeAddr("safeOwner");
    address sponsor = makeAddr("sponsor");
    address inviter = makeAddr("inviter");
    address recipient = makeAddr("recipient");
    address stranger = makeAddr("stranger");

    bytes32 constant ID = keccak256("invite-1");

    function setUp() public {
        cusd = new MockToken("cUSD");
        cusdPlus = new MockInviteCusdPlus(cusd);
        confio = new MockToken("CONFIO");
        alien = new MockToken("ALIEN");
        escrow = new ConfioInviteEscrow(address(cusdPlus), address(cusd), address(confio), sponsor, safeOwner);
        for (uint256 i = 0; i < 3; i++) {
            MockToken t = [cusd, confio, alien][i];
            t.mint(inviter, 1_000e18);
            vm.prank(inviter);
            t.approve(address(escrow), type(uint256).max);
        }
        cusdPlus.mint(inviter, 1_000e18);
        vm.prank(inviter);
        cusdPlus.approve(address(escrow), type(uint256).max);
    }

    function _create(bytes32 id, IERC20 token, uint256 amt) internal {
        vm.prank(inviter);
        escrow.createInvitation(id, address(token), amt);
    }

    // ── Create ───────────────────────────────────────────────────────

    function test_create_locks_tokens() public {
        _create(ID, cusdPlus, 100e18);
        (address inv, address tok, uint128 amt,, bool settled) = escrow.invitations(escrow.invitationKey(inviter, ID));
        assertEq(inv, inviter);
        assertEq(tok, address(cusdPlus));
        assertEq(amt, 100e18);
        assertFalse(settled);
        assertEq(cusdPlus.balanceOf(address(escrow)), 100e18);
    }

    function test_create_confio_too() public {
        _create(ID, confio, 50e18);
        assertEq(confio.balanceOf(address(escrow)), 50e18);
    }

    function test_alien_token_rejected() public {
        vm.prank(inviter);
        vm.expectRevert("token not allowed");
        escrow.createInvitation(ID, address(alien), 100e18);
    }

    function test_no_duplicate_invite_id() public {
        _create(ID, cusdPlus, 100e18);
        vm.prank(inviter);
        vm.expectRevert("invite exists");
        escrow.createInvitation(ID, address(cusdPlus), 50e18);
    }

    function test_create_paused_rejected() public {
        vm.prank(safeOwner);
        escrow.pause();
        vm.prank(inviter);
        vm.expectRevert();
        escrow.createInvitation(ID, address(cusdPlus), 100e18);
    }

    // ── Claim ────────────────────────────────────────────────────────

    function test_sponsor_claims_to_recipient() public {
        _create(ID, cusdPlus, 100e18);
        vm.prank(sponsor);
        uint256 got = escrow.claimInvitation(ID, inviter, recipient, true, 0);
        assertEq(got, 100e18);
        assertEq(cusdPlus.balanceOf(recipient), 100e18);
        (,,,, bool settled) = escrow.invitations(escrow.invitationKey(inviter, ID));
        assertTrue(settled);
    }

    function test_plus_invite_unwraps_to_cusd_for_ineligible_recipient() public {
        _create(ID, cusdPlus, 100e18);
        vm.prank(sponsor);
        uint256 got = escrow.claimInvitation(ID, inviter, recipient, false, 100e18);
        assertEq(got, 100e18);
        assertEq(cusd.balanceOf(recipient), 100e18);
        assertEq(cusdPlus.balanceOf(recipient), 0);
    }

    function test_cusd_invite_wraps_for_eligible_recipient() public {
        _create(ID, cusd, 100e18);
        vm.prank(sponsor);
        uint256 got = escrow.claimInvitation(ID, inviter, recipient, true, 100e18);
        assertEq(got, 100e18);
        assertEq(cusdPlus.balanceOf(recipient), 100e18);
        assertEq(cusd.balanceOf(recipient), 0);
    }

    function test_cusd_invite_stays_cusd_for_ineligible_recipient() public {
        _create(ID, cusd, 100e18);
        vm.prank(sponsor);
        escrow.claimInvitation(ID, inviter, recipient, false, 0);
        assertEq(cusd.balanceOf(recipient), 100e18);
    }

    function test_only_sponsor_can_claim() public {
        _create(ID, cusdPlus, 100e18);
        vm.prank(stranger);
        vm.expectRevert("not sponsor");
        escrow.claimInvitation(ID, inviter, recipient, true, 0);
        // even the recipient cannot self-claim (backend-mediated flow)
        vm.prank(recipient);
        vm.expectRevert("not sponsor");
        escrow.claimInvitation(ID, inviter, recipient, true, 0);
    }

    function test_claim_recipient_cannot_be_inviter() public {
        _create(ID, cusdPlus, 100e18);
        vm.prank(sponsor);
        vm.expectRevert("recipient is inviter");
        escrow.claimInvitation(ID, inviter, inviter, true, 0);
    }

    function test_claim_after_expiry_rejected() public {
        _create(ID, cusdPlus, 100e18);
        vm.warp(block.timestamp + 7 days + 1);
        vm.prank(sponsor);
        vm.expectRevert("expired");
        escrow.claimInvitation(ID, inviter, recipient, true, 0);
    }

    function test_double_claim_rejected() public {
        _create(ID, cusdPlus, 100e18);
        vm.startPrank(sponsor);
        escrow.claimInvitation(ID, inviter, recipient, true, 0);
        vm.expectRevert("settled");
        escrow.claimInvitation(ID, inviter, recipient, true, 0);
        vm.stopPrank();
    }

    // ── Reclaim ──────────────────────────────────────────────────────

    function test_inviter_reclaims_after_expiry() public {
        _create(ID, cusdPlus, 100e18);
        uint256 before = cusdPlus.balanceOf(inviter);
        vm.warp(block.timestamp + 7 days + 1);
        vm.prank(inviter);
        uint256 got = escrow.reclaimInvitation(ID);
        assertEq(got, 100e18);
        assertEq(cusdPlus.balanceOf(inviter), before + 100e18);
    }

    function test_reclaim_before_expiry_rejected() public {
        _create(ID, cusdPlus, 100e18);
        vm.prank(inviter);
        vm.expectRevert("not expired");
        escrow.reclaimInvitation(ID);
    }

    function test_only_inviter_reclaims() public {
        _create(ID, cusdPlus, 100e18);
        vm.warp(block.timestamp + 7 days + 1);
        vm.prank(stranger);
        vm.expectRevert("not inviter");
        escrow.reclaimInvitation(ID);
    }

    function test_reclaim_works_while_paused() public {
        _create(ID, cusdPlus, 100e18);
        vm.prank(safeOwner);
        escrow.pause();
        vm.warp(block.timestamp + 7 days + 1);
        vm.prank(inviter);
        escrow.reclaimInvitation(ID); // exit is never gated
        assertEq(cusdPlus.balanceOf(address(escrow)), 0);
    }

    function test_cannot_claim_a_reclaimed_invite() public {
        _create(ID, cusdPlus, 100e18);
        vm.warp(block.timestamp + 7 days + 1);
        vm.prank(inviter);
        escrow.reclaimInvitation(ID);
        vm.prank(sponsor);
        vm.expectRevert("settled"); // settled is checked before expiry
        escrow.claimInvitation(ID, inviter, recipient, true, 0);
    }

    // ── Admin ────────────────────────────────────────────────────────

    function test_sponsor_rotation() public {
        _create(ID, cusdPlus, 100e18);
        address newSponsor = makeAddr("newSponsor");
        vm.prank(stranger);
        vm.expectRevert();
        escrow.setSponsor(newSponsor);
        vm.prank(safeOwner);
        escrow.setSponsor(newSponsor);
        vm.prank(sponsor);
        vm.expectRevert("not sponsor");
        escrow.claimInvitation(ID, inviter, recipient, true, 0);
        vm.prank(newSponsor);
        escrow.claimInvitation(ID, inviter, recipient, true, 0);
        assertEq(cusdPlus.balanceOf(recipient), 100e18);
    }

    function test_renounce_disabled() public {
        vm.prank(safeOwner);
        vm.expectRevert("renounce disabled");
        escrow.renounceOwnership();
    }

    // ── AUDIT REGRESSION (2026-07-31 [P3]) ───────────────────────────
    // The invite id is derived from the recipient's phone (public), so a
    // squatter must not be able to block a real inviter by front-running
    // the same id. Storage is namespaced by the actual creator.
    function test_squatter_cannot_block_real_invite() public {
        // Attacker front-runs the same id with 1 wei.
        confio.mint(stranger, 1e18);
        vm.prank(stranger);
        confio.approve(address(escrow), type(uint256).max);
        vm.prank(stranger);
        escrow.createInvitation(ID, address(confio), 1);

        // The real inviter's create still succeeds under THEIR key.
        _create(ID, cusdPlus, 100e18);
        (address inv,,,,) = escrow.invitations(escrow.invitationKey(inviter, ID));
        assertEq(inv, inviter, "real invite intact");

        // And the sponsor claims the real one (bound to the real inviter),
        // never the squatter's.
        vm.prank(sponsor);
        escrow.claimInvitation(ID, inviter, recipient, true, 0);
        assertEq(cusdPlus.balanceOf(recipient), 100e18);
        // The squatter's 1-wei entry is independent and untouched.
        (,, uint128 sqAmt,, bool sqSettled) = escrow.invitations(escrow.invitationKey(stranger, ID));
        assertEq(sqAmt, 1);
        assertFalse(sqSettled);
    }
}
