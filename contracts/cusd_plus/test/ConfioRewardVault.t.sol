// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ConfioRewardVault} from "../ConfioRewardVault.sol";

contract MockConfio is ERC20 {
    constructor() ERC20("Confio", "CONFIO") {}
    function mint(address to, uint256 amt) external { _mint(to, amt); }
}

contract ConfioRewardVaultTest is Test {
    MockConfio confio;
    ConfioRewardVault vault;

    address safeOwner = makeAddr("safeOwner");
    address attestor = makeAddr("attestor");
    address user = makeAddr("user");
    address referrer = makeAddr("referrer");
    address stranger = makeAddr("stranger");

    uint256 constant WAD = 1e18;

    function setUp() public {
        confio = new MockConfio();
        vault = new ConfioRewardVault(address(confio), attestor, safeOwner);
        confio.mint(address(vault), 10_000_000e18); // treasury funds the vault
        vm.prank(safeOwner);
        vault.setManualPrice(0.25e18); // $0.25 per CONFIO
    }

    function _setEligible(address u, uint256 cusd, address ref, uint256 refConfio) internal {
        uint64 round = vault.priceRound(); // read BEFORE prank (it's a call)
        vm.prank(attestor);
        vault.setEligible(u, cusd, round, ref, refConfio);
    }

    // ── Attestation + conversion ─────────────────────────────────────

    function test_setEligible_converts_cusd_to_confio() public {
        _setEligible(user, 10e18, address(0), 0); // $10 at $0.25 = 40 CONFIO
        (uint128 amount,,, bool claimed,,) = vault.rewards(user);
        assertEq(amount, 40e18);
        assertFalse(claimed);
        assertEq(vault.totalEligible(), 40e18);
        assertEq(vault.eligibleCount(), 1);
    }

    function test_quote_matches_manual_price() public view {
        assertEq(vault.quoteConfio(10e18), 40e18);
        assertEq(vault.quoteConfio(1e18), 4e18);
    }

    function test_setEligible_onlyAttestor() public {
        uint64 r = vault.priceRound();
        vm.prank(stranger);
        vm.expectRevert("not attestor");
        vault.setEligible(user, 10e18, r, address(0), 0);
    }

    function test_setEligible_requires_active_price() public {
        vm.prank(safeOwner);
        vault.clearManualPrice();
        uint64 r = vault.priceRound();
        vm.prank(attestor);
        vm.expectRevert("price not set");
        vault.setEligible(user, 10e18, r, address(0), 0);
    }

    function test_cannot_overwrite_pending_allocation() public {
        _setEligible(user, 10e18, address(0), 0);
        uint64 r = vault.priceRound();
        vm.prank(attestor);
        vm.expectRevert("pending allocation");
        vault.setEligible(user, 5e18, r, address(0), 0);
    }

    function test_can_reattest_after_claim() public {
        _setEligible(user, 10e18, address(0), 0);
        vm.prank(user);
        vault.claim();
        _setEligible(user, 20e18, address(0), 0); // $20 → 80 CONFIO
        (uint128 amount,,, bool claimed,,) = vault.rewards(user);
        assertEq(amount, 80e18);
        assertFalse(claimed);
        assertEq(vault.totalEligible(), 40e18 + 80e18);
    }

    // ── Solvency invariant ───────────────────────────────────────────

    function test_setEligible_reverts_when_reserve_insufficient() public {
        // Drain the vault to almost nothing via surplus withdrawal.
        vm.prank(safeOwner);
        vault.withdrawSurplus(safeOwner, 10_000_000e18 - 30e18); // 30 CONFIO left
        uint64 r = vault.priceRound();
        vm.prank(attestor);
        vm.expectRevert("insufficient reserve");
        vault.setEligible(user, 10e18, r, address(0), 0); // needs 40
    }

    function test_reserve_accounts_for_prior_obligations() public {
        vm.prank(safeOwner);
        vault.withdrawSurplus(safeOwner, 10_000_000e18 - 60e18); // 60 CONFIO
        _setEligible(user, 10e18, address(0), 0);    // 40 owed
        uint64 r = vault.priceRound();
        vm.prank(attestor);
        vm.expectRevert("insufficient reserve");
        vault.setEligible(stranger, 10e18, r, address(0), 0); // needs another 40, only 20 free
    }

    // ── Claim ────────────────────────────────────────────────────────

    function test_claim_transfers_and_settles() public {
        _setEligible(user, 10e18, address(0), 0);
        vm.prank(user);
        uint256 got = vault.claim();
        assertEq(got, 40e18);
        assertEq(confio.balanceOf(user), 40e18);
        (uint128 amount,,, bool claimed,,) = vault.rewards(user);
        assertEq(amount, 0);
        assertTrue(claimed);
        assertEq(vault.totalClaimed(), 40e18);
        assertEq(vault.claimCount(), 1);
    }

    function test_double_claim_rejected() public {
        _setEligible(user, 10e18, address(0), 0);
        vm.startPrank(user);
        vault.claim();
        vm.expectRevert("nothing to claim");
        vault.claim();
        vm.stopPrank();
    }

    function test_claim_with_no_allocation_rejected() public {
        vm.prank(stranger);
        vm.expectRevert("nothing to claim");
        vault.claim();
    }

    // ── Referral ─────────────────────────────────────────────────────

    function test_referral_recorded_and_claimed() public {
        _setEligible(user, 10e18, referrer, 5e18); // 40 to user, 5 CONFIO to referrer
        assertEq(vault.totalRefEligible(), 5e18);

        // Order-independent: referrer can claim before the referee.
        vm.prank(referrer);
        uint256 got = vault.claimReferral(user);
        assertEq(got, 5e18);
        assertEq(confio.balanceOf(referrer), 5e18);
        assertEq(vault.totalRefPaid(), 5e18);

        // Referee still claims their own part.
        vm.prank(user);
        assertEq(vault.claim(), 40e18);
    }

    function test_only_stored_referrer_may_claim() public {
        _setEligible(user, 10e18, referrer, 5e18);
        vm.prank(stranger);
        vm.expectRevert("not referrer");
        vault.claimReferral(user);
    }

    function test_referral_claimed_once() public {
        _setEligible(user, 10e18, referrer, 5e18);
        vm.startPrank(referrer);
        vault.claimReferral(user);
        vm.expectRevert("nothing to claim");
        vault.claimReferral(user);
        vm.stopPrank();
    }

    function test_no_referral_when_amount_zero() public {
        _setEligible(user, 10e18, address(0), 0);
        (,, address ref,, bool refClaimed,) = vault.rewards(user);
        assertEq(ref, address(0));
        assertTrue(refClaimed, "settled when there is nothing to pay");
        // No referrer is stored, so nobody can claim a referral on this user.
        vm.prank(referrer);
        vm.expectRevert("not referrer");
        vault.claimReferral(user);
    }

    function test_referrer_cannot_be_self() public {
        uint64 r = vault.priceRound();
        vm.prank(attestor);
        vm.expectRevert("bad referrer");
        vault.setEligible(user, 10e18, r, user, 5e18);
    }

    // ── Surplus withdrawal ───────────────────────────────────────────

    function test_withdraw_surplus_bounded_by_obligations() public {
        _setEligible(user, 10e18, referrer, 5e18); // 45 CONFIO owed total
        assertEq(vault.outstanding(), 45e18);
        assertEq(vault.surplus(), 10_000_000e18 - 45e18);

        vm.prank(safeOwner);
        vm.expectRevert("exceeds surplus");
        vault.withdrawSurplus(safeOwner, 10_000_000e18 - 44e18); // would eat 1 of the obligation

        vm.prank(safeOwner);
        vault.withdrawSurplus(safeOwner, 10_000_000e18 - 45e18); // exactly the surplus
        assertEq(vault.surplus(), 0);

        // Both claims still fully funded.
        vm.prank(user);
        vault.claim();
        vm.prank(referrer);
        vault.claimReferral(user);
        assertEq(confio.balanceOf(user), 40e18);
        assertEq(confio.balanceOf(referrer), 5e18);
    }

    function test_withdraw_surplus_owner_only() public {
        vm.prank(stranger);
        vm.expectRevert();
        vault.withdrawSurplus(stranger, 1e18);
    }

    // ── Pause + admin ────────────────────────────────────────────────

    function test_pause_blocks_attest_and_claim() public {
        _setEligible(user, 10e18, address(0), 0);
        vm.prank(safeOwner);
        vault.pause();

        uint64 r = vault.priceRound();
        vm.prank(attestor);
        vm.expectRevert();
        vault.setEligible(stranger, 10e18, r, address(0), 0);

        vm.prank(user);
        vm.expectRevert();
        vault.claim();

        // Surplus withdrawal is NOT pausable (owner recovery always open).
        vm.prank(safeOwner);
        vault.withdrawSurplus(safeOwner, 1e18);
    }

    function test_attestor_rotation() public {
        address newAttestor = makeAddr("newAttestor");
        vm.prank(stranger);
        vm.expectRevert();
        vault.setAttestor(newAttestor);

        vm.prank(safeOwner);
        vault.setAttestor(newAttestor);
        assertEq(vault.attestor(), newAttestor);

        uint64 r = vault.priceRound();
        vm.prank(attestor);
        vm.expectRevert("not attestor");
        vault.setEligible(user, 10e18, r, address(0), 0);
        vm.prank(newAttestor);
        vault.setEligible(user, 10e18, r, address(0), 0);
        (uint128 amount,,,,,) = vault.rewards(user);
        assertEq(amount, 40e18);
    }

    function test_price_round_stamped_on_reward() public {
        uint64 round1 = vault.priceRound();
        _setEligible(user, 10e18, address(0), 0);
        (,,,,, uint64 stamped) = vault.rewards(user);
        assertEq(stamped, round1);

        vm.prank(safeOwner);
        vault.setManualPrice(0.5e18); // round bumps
        assertEq(vault.priceRound(), round1 + 1);
    }

    // ── AUDIT P3 fixes (2026-07-31) ──────────────────────────────────

    /// Stale-price race: if the Safe re-prices between the attestor signing
    /// and inclusion, the attestation must revert, not mint at the new rate.
    function test_stale_price_round_rejected() public {
        uint64 signedRound = vault.priceRound();
        vm.prank(safeOwner);
        vault.setManualPrice(0.5e18); // round moves under the attestor
        vm.prank(attestor);
        vm.expectRevert("stale price round");
        vault.setEligible(user, 10e18, signedRound, address(0), 0);
    }

    /// cancelEligibility corrects a mistaken allocation AND keeps the
    /// counters exact, so the freed CONFIO returns to surplus.
    function test_cancel_eligibility_frees_obligation() public {
        _setEligible(user, 10e18, referrer, 5e18); // 45 owed
        assertEq(vault.outstanding(), 45e18);

        vm.prank(stranger);
        vm.expectRevert(); // owner-only
        vault.cancelEligibility(user);

        vm.prank(safeOwner);
        vault.cancelEligibility(user);
        assertEq(vault.outstanding(), 0, "obligation released");
        assertEq(vault.surplus(), 10_000_000e18);
        (uint128 amount, uint128 refAmount,,,,) = vault.rewards(user);
        assertEq(amount, 0);
        assertEq(refAmount, 0);

        // The user can be freshly re-attested afterward.
        _setEligible(user, 1e18, address(0), 0);
        vm.prank(user);
        assertEq(vault.claim(), 4e18);
    }

    function test_cancel_only_frees_unclaimed_portion() public {
        _setEligible(user, 10e18, referrer, 5e18);
        vm.prank(user);
        vault.claim(); // main gone, referral still pending
        assertEq(vault.outstanding(), 5e18);

        vm.prank(safeOwner);
        vault.cancelEligibility(user); // frees only the 5 referral
        assertEq(vault.outstanding(), 0);
        // The claimed 40 CONFIO stays with the user; nothing clawed back.
        assertEq(confio.balanceOf(user), 40e18);
    }

    function test_cancel_reverts_when_nothing_pending() public {
        _setEligible(user, 10e18, address(0), 0);
        vm.prank(user);
        vault.claim();
        vm.prank(safeOwner);
        vm.expectRevert("nothing pending");
        vault.cancelEligibility(user);
    }

    /// Renounce is disabled so a paused vault can always be unpaused.
    function test_renounce_ownership_disabled() public {
        vm.prank(safeOwner);
        vm.expectRevert("renounce disabled");
        vault.renounceOwnership();
        assertEq(vault.owner(), safeOwner);
    }

    function test_price_change_affects_new_rewards_only() public {
        _setEligible(user, 10e18, address(0), 0); // 40 at $0.25
        vm.prank(safeOwner);
        vault.setManualPrice(0.5e18);
        _setEligible(stranger, 10e18, address(0), 0); // 20 at $0.50
        (uint128 a1,,,,,) = vault.rewards(user);
        (uint128 a2,,,,,) = vault.rewards(stranger);
        assertEq(a1, 40e18);
        assertEq(a2, 20e18);
    }
}
