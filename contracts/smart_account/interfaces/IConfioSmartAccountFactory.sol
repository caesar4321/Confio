// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ABI of the Cuenta inteligente factory. Specification:
 * docs/designs/cuenta-inteligente-spec.md (section 4.3). UUPS, owned by the
 * Confío Safe. Accounts clamp every value they read from here to limits
 * hard-coded in the account implementation.
 */
interface IConfioSmartAccountFactory {
    struct ConfioSale {
        address venue;
        address priceRef;
    }

    event AccountCreated(address indexed owner, address indexed account);
    event FeeScheduled(uint8 plan, uint256 newFeeUsd, uint64 effectiveAt);
    event ChallengeWindowSet(uint64 window, bool allowed);
    event ClaimCooldownSet(uint64 cooldown);
    event ForcedSaleNoticeSet(uint64 notice);
    event InheritanceEnabled();
    event RelayerPausedSet(bool paused);
    event ConfioSaleSet(address venue, address priceRef);

    /// The caller becomes the owner. Reverts ("account exists") while
    /// accountOf(caller) is still the caller's: active, cancelled or expired
    /// alike. Once that account has been inherited (or is otherwise no longer
    /// owned by the caller) it opens a new one at generationOf(caller) + 1
    /// and points accountOf(caller) at it.
    function createAccount() external returns (address account);
    /// Address of the next createAccount by `owner`: predictAddressAt(owner, 0)
    /// with no account, predictAddressAt(owner, generationOf(owner) + 1) once
    /// the current account is replaceable, and accountOf(owner) itself while
    /// createAccount would revert.
    function predictAddress(address owner) external view returns (address);
    /// CREATE2 address of `owner`'s account of `generation`
    /// (salt = keccak256(abi.encode(owner, generation))).
    function predictAddressAt(address owner, uint64 generation) external view returns (address);
    /// Generation of accountOf(owner); 0 also when the owner has none.
    function generationOf(address owner) external view returns (uint64);
    /// The owner's current account. Changes only when the previous one was
    /// inherited by someone else (invariant 17).
    function accountOf(address owner) external view returns (address);
    /// True for every account this factory ever created, inherited ones too.
    function isAccount(address account) external view returns (bool);
    function implementation() external view returns (address);

    /// Price in force now for a plan (1 Monthly, 2 Annual), USD 18 decimals.
    function feeUsd(uint8 plan) external view returns (uint256);
    /// A scheduled price not yet in force: (0, 0) when none.
    function scheduledFee(uint8 plan) external view returns (uint256 newFeeUsd, uint64 effectiveAt);
    function scheduleFee(uint8 plan, uint256 newFeeUsd, uint64 effectiveAt) external;

    function allowedChallengeWindows(uint64 window) external view returns (bool);
    function setChallengeWindow(uint64 window, bool allowed) external;
    function claimCooldown() external view returns (uint64);
    function setClaimCooldown(uint64 cooldown) external;
    function forcedSaleNotice() external view returns (uint64);
    function setForcedSaleNotice(uint64 notice) external;

    function inheritanceEnabled() external view returns (bool);
    /// One-way.
    function enableInheritance() external;

    function relayerPaused() external view returns (bool);
    function setRelayerPaused(bool paused) external;

    function confioSale() external view returns (address venue, address priceRef);
    /// Once only.
    function setConfioSale(address venue, address priceRef) external;

    // ── Designation approvals (audit fix to decision 26) ───────────────
    // A tx.origin gate on the account proves only that a sponsor started the
    // transaction, not that the relay checked THIS designation. The relayer
    // (a sponsor that is also tx.origin) records an approval for the exact
    // designation after the server's identity and residence checks; the
    // account requires a live approval. Approvals expire after
    // APPROVAL_TTL (1 hour) and are keyed by account, so reusing one only
    // repeats the same checked designation.
    event DesignationApproved(address indexed account, address indexed beneficiary, uint64 window, uint64 expiresAt);
    event AcceptanceApproved(address indexed account, address indexed beneficiary, uint64 expiresAt);

    function approveDesignation(address account, address beneficiary, uint64 window) external;
    function approveAcceptance(address account, address beneficiary) external;
    /// Expiry (unix seconds) of the approval for keccak256(abi.encode(beneficiary, window)); 0 = none.
    function designationApprovedUntil(address account, bytes32 key) external view returns (uint64);
    /// Expiry of the approval for `beneficiary` to accept on `account`; 0 = none.
    function acceptanceApprovedUntil(address account, address beneficiary) external view returns (uint64);
}
