// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ConfioRewardVault — CONFIO reward claims, LOCKED until DEX launch.
 *
 * Design (Julian, 2026-07-31): CONFIO has no liquidity before the DEX
 * launch, so letting users move reward CONFIO early is useless. Rewards
 * therefore accrue OFF-CHAIN in Confío's database — the single source of
 * truth for who earned what — and nothing touches the chain until a user
 * claims. Claims are LOCKED until the owner Safe opens them at DEX launch
 * (one-way), matching the tokenomics lock ("bloqueados hasta el evento de
 * lanzamiento/desbloqueo en DEX").
 *
 * Authorization is an EIP-712 signature by the backend SIGNER over the
 * user's CUMULATIVE earned CONFIO. The user submits it and receives
 * (cumulative − alreadyClaimed); the on-chain `claimed` mapping is BOTH the
 * running total and the replay guard, so continued accrual just means the
 * backend signs a larger cumulative later. No per-reward on-chain
 * attestation; no price on-chain (the backend converts $ → CONFIO at the
 * live presale-curve price when it computes the cumulative).
 *
 * Trust model — be honest (audit 2026-07-31): this is a fully
 * treasury-controlled reward pool, NOT a trustless escrow. Rewards are
 * discretionary treasury obligations. The owner Safe can, at any time
 * including after DEX unlock, pause() and withdraw() the whole balance and
 * never unpause — `unlockClaims` being one-way does NOT guarantee claims
 * stay available, and bounding withdraw wouldn't fix that (the owner could
 * rotate the signer and drain through signed claims). Users trust the
 * 3-of-5 Safe to honor the DB obligations. A compromised SIGNER is bounded
 * by the funded balance (fund a working tranche, top up), and — because
 * there is no on-chain record of what is owed — the SIGNER must sign with
 * SHORT deadlines: a corrected-down entitlement can't revoke an already
 * issued higher-cumulative signature before its deadline, only outlast it.
 */

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

contract ConfioRewardVault is Ownable2Step, Pausable, ReentrancyGuardTransient {
    using SafeERC20 for IERC20;

    // ═════════════════════════ EIP-712 ══════════════════════════════════

    bytes32 private constant DOMAIN_TYPEHASH = keccak256(
        "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    );
    bytes32 private constant NAME_HASH = keccak256(bytes("ConfioRewardVault"));
    bytes32 private constant VERSION_HASH = keccak256(bytes("1"));
    bytes32 public constant CLAIM_TYPEHASH = keccak256(
        "Claim(address user,uint256 cumulativeAmount,uint256 deadline)"
    );

    // ═════════════════════════ State ════════════════════════════════════

    IERC20 public immutable CONFIO;

    /// Backend key that authorizes claims. Owner-rotatable hot key.
    address public signer;

    /// Claims are shut until DEX launch; one-way once opened.
    bool public claimsUnlocked;

    /// Cumulative CONFIO each user has already pulled — running total AND
    /// replay guard (a re-submitted signature pays 0 and reverts).
    mapping(address => uint256) public claimed;
    uint256 public totalClaimed;

    event SignerSet(address indexed signer);
    event ClaimsUnlocked();
    event Claimed(address indexed user, uint256 amount, uint256 cumulative);
    event Withdrawn(address indexed to, uint256 amount);

    constructor(address confio, address signer_, address owner_) Ownable(owner_) {
        require(confio != address(0) && signer_ != address(0), "zero address");
        CONFIO = IERC20(confio);
        signer = signer_;
        emit SignerSet(signer_);
    }

    // ═════════════════════════ Claim ════════════════════════════════════

    /// Pull everything newly earned. `cumulativeAmount` is the user's total
    /// lifetime reward CONFIO as of signing; the vault pays the delta over
    /// what they've already claimed. Sponsored gas under 7702 (msg.sender
    /// is the user's own EOA).
    function claim(uint256 cumulativeAmount, uint256 deadline, bytes calldata signature)
        external
        nonReentrant
        whenNotPaused
        returns (uint256 paid)
    {
        require(claimsUnlocked, "claims locked");
        require(block.timestamp <= deadline, "expired");

        address recovered = ECDSA.recover(claimDigest(msg.sender, cumulativeAmount, deadline), signature);
        require(recovered == signer, "bad signature");

        uint256 already = claimed[msg.sender];
        require(cumulativeAmount > already, "nothing to claim");

        paid = cumulativeAmount - already;
        claimed[msg.sender] = cumulativeAmount;
        totalClaimed += paid;

        CONFIO.safeTransfer(msg.sender, paid);
        emit Claimed(msg.sender, paid, cumulativeAmount);
    }

    /// Exposed so the backend signer and clients assert digest parity.
    function claimDigest(address user, uint256 cumulativeAmount, uint256 deadline)
        public
        view
        returns (bytes32)
    {
        bytes32 domainSeparator = keccak256(
            abi.encode(DOMAIN_TYPEHASH, NAME_HASH, VERSION_HASH, block.chainid, address(this))
        );
        bytes32 structHash = keccak256(
            abi.encode(CLAIM_TYPEHASH, user, cumulativeAmount, deadline)
        );
        return keccak256(abi.encodePacked("\x19\x01", domainSeparator, structHash));
    }

    // ═════════════════════════ Admin (Safe) ═════════════════════════════

    function setSigner(address signer_) external onlyOwner {
        require(signer_ != address(0), "zero signer");
        signer = signer_;
        emit SignerSet(signer_);
    }

    /// One-way: opening claims is a launch event, not a toggle — no path
    /// re-locks `claimsUnlocked`. NOTE this is not the same as guaranteed
    /// availability: pause()+withdraw() can still suspend and defund claims
    /// (see the trust-model note in the header). One-way unlock only means
    /// the DEX-launch signal itself is irreversible.
    function unlockClaims() external onlyOwner {
        require(!claimsUnlocked, "already unlocked");
        claimsUnlocked = true;
        emit ClaimsUnlocked();
    }

    /// The reward pool is the treasury's own CONFIO; outstanding
    /// obligations live in the DB, which the Safe reconciles before moving
    /// funds. Not the claim path — this is fund management, not a claimer's
    /// exit.
    function withdraw(address to, uint256 amount) external onlyOwner nonReentrant {
        require(to != address(0), "zero recipient");
        require(amount > 0, "zero amount");
        CONFIO.safeTransfer(to, amount);
        emit Withdrawn(to, amount);
    }

    function pause() external onlyOwner { _pause(); }
    function unpause() external onlyOwner { _unpause(); }

    /// Disabled: renouncing while paused would strand every claimer with no
    /// way to unpause. The Safe must always be able to operate the vault.
    function renounceOwnership() public view override onlyOwner {
        revert("renounce disabled");
    }
}
