// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ConfioVestingVault — BSC mirror of the Algorand CONFIO vesting pool
 * (contracts/vesting/confio_vesting_pool.py + the per-beneficiary
 * confio_vesting apps).
 *
 * Linear vesting of CONFIO to many beneficiaries. Unlike the Algorand
 * pool's single global duration, each grant carries its OWN start and
 * duration, so the founder (36mo), the co-builder (24mo) and the cultural
 * fund (90d) all live in one vault. No cliff (linear from start, matching
 * the tokenomics). Owner = the 3-of-5 Safe; beneficiaries self-claim the
 * vested-minus-claimed amount. Non-upgradeable.
 *
 * A grant's `start` is 0 until the owner starts it (the tokenomics
 * "trigger"): before then nothing vests and the owner may still adjust or
 * reclaim it. `changeBeneficiary` moves a grant intact to a new address
 * (Algorand change_member parity). Escrow solvency is enforced on every
 * grant: the vault must already hold what it owes plus the new grant.
 */

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";

contract ConfioVestingVault is Ownable2Step, ReentrancyGuardTransient {
    using SafeERC20 for IERC20;

    IERC20 public immutable CONFIO;

    struct Grant {
        uint128 allocated;
        uint128 claimed;
        uint64 start;    // 0 until started
        uint64 duration; // seconds
    }

    mapping(address => Grant) public grants;

    /// Σ (allocated − claimed) over all grants — lets solvency be checked
    /// on-chain and bounds what the owner can withdraw as surplus.
    uint256 public totalOwed;

    event GrantAdded(address indexed beneficiary, uint256 allocated, uint64 duration);
    event GrantStarted(address indexed beneficiary, uint64 start);
    event GrantMoved(address indexed from, address indexed to);
    event Claimed(address indexed beneficiary, uint256 amount);
    event GrantRevoked(address indexed beneficiary, uint256 unvestedReturned);
    event SurplusWithdrawn(address indexed to, uint256 amount);

    constructor(address confio, address owner_) Ownable(owner_) {
        require(confio != address(0), "zero address");
        CONFIO = IERC20(confio);
    }

    // ═════════════════════════ Views ════════════════════════════════════

    /// Vested amount of a grant at the current time (linear, capped).
    function vestedOf(address beneficiary) public view returns (uint256) {
        Grant memory g = grants[beneficiary];
        if (g.start == 0 || block.timestamp <= g.start) return 0;
        uint256 elapsed = block.timestamp - g.start;
        if (elapsed >= g.duration) return g.allocated;
        return (uint256(g.allocated) * elapsed) / g.duration;
    }

    function claimableOf(address beneficiary) public view returns (uint256) {
        uint256 vested = vestedOf(beneficiary);
        uint256 claimed = grants[beneficiary].claimed;
        return vested > claimed ? vested - claimed : 0;
    }

    function surplus() public view returns (uint256) {
        uint256 bal = CONFIO.balanceOf(address(this));
        return bal > totalOwed ? bal - totalOwed : 0;
    }

    // ═════════════════════════ Owner (Safe) ═════════════════════════════

    /// The vault must already hold every outstanding obligation plus this
    /// new grant before it can be added (the CONFIO is funded by a plain
    /// transfer from the Safe — no separate fund() needed).
    function addGrant(address beneficiary, uint256 allocated, uint64 duration)
        external
        onlyOwner
    {
        require(beneficiary != address(0), "zero beneficiary");
        require(allocated > 0 && allocated <= type(uint128).max, "bad amount");
        require(duration > 0, "zero duration");
        require(grants[beneficiary].allocated == 0, "grant exists");
        require(
            CONFIO.balanceOf(address(this)) >= totalOwed + allocated,
            "insufficient reserve"
        );
        grants[beneficiary] = Grant({
            allocated: uint128(allocated),
            claimed: 0,
            start: 0,
            duration: duration
        });
        totalOwed += allocated;
        emit GrantAdded(beneficiary, allocated, duration);
    }

    /// Start the clock (the tokenomics "trigger"). Once started, a grant
    /// can no longer be revoked — vesting is in motion.
    function startGrant(address beneficiary) external onlyOwner {
        Grant storage g = grants[beneficiary];
        require(g.allocated > 0, "no grant");
        require(g.start == 0, "already started");
        g.start = uint64(block.timestamp);
        emit GrantStarted(beneficiary, g.start);
    }

    /// Move a grant intact to a new address (Algorand change_member). Both
    /// vesting progress and claimed carry over.
    function changeBeneficiary(address from, address to) external onlyOwner {
        require(to != address(0) && to != from, "bad target");
        Grant memory g = grants[from];
        require(g.allocated > 0, "no grant");
        require(grants[to].allocated == 0, "target has a grant");
        grants[to] = g;
        delete grants[from];
        emit GrantMoved(from, to);
    }

    /// Cancel a grant that has NOT started yet, returning its allocation to
    /// surplus. Never touches a started grant (vesting is a promise once in
    /// motion) or already-claimed tokens.
    function revokeGrant(address beneficiary) external onlyOwner {
        Grant memory g = grants[beneficiary];
        require(g.allocated > 0, "no grant");
        require(g.start == 0, "already started");
        uint256 unvested = g.allocated - g.claimed; // start==0 ⇒ claimed==0
        delete grants[beneficiary];
        totalOwed -= unvested;
        emit GrantRevoked(beneficiary, unvested);
    }

    /// Withdraw only CONFIO above outstanding obligations.
    function withdrawSurplus(address to, uint256 amount) external onlyOwner nonReentrant {
        require(to != address(0), "zero recipient");
        require(amount > 0 && amount <= surplus(), "exceeds surplus");
        CONFIO.safeTransfer(to, amount);
        emit SurplusWithdrawn(to, amount);
    }

    /// Disabled: renouncing would strand every grant with no admin.
    function renounceOwnership() public view override onlyOwner {
        revert("renounce disabled");
    }

    // ═════════════════════════ Beneficiary ══════════════════════════════

    /// Claim the vested-minus-claimed amount. Sponsored gas under 7702
    /// (msg.sender is the beneficiary's own EOA).
    function claim() external nonReentrant returns (uint256 amount) {
        amount = claimableOf(msg.sender);
        require(amount > 0, "nothing to claim");
        grants[msg.sender].claimed += uint128(amount);
        totalOwed -= amount;
        CONFIO.safeTransfer(msg.sender, amount);
        emit Claimed(msg.sender, amount);
    }
}
