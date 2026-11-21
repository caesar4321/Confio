// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ConfioSmartAccountFactory — deploys one Cuenta inteligente per owner and
 * holds the global configuration. Specification:
 * docs/designs/cuenta-inteligente-spec.md, section 4.3.
 *
 * - UUPS, Ownable2Step, owned by the Confío Safe, renounce disabled (as in
 *   CusdVault and CusdPlusVault).
 * - Accounts are EIP-1167 clones of one immutable implementation, at a
 *   CREATE2 address derived from (owner, generation). `accountOf[owner]`
 *   points at the owner's current account and changes only when that one
 *   has been inherited by someone else (or is no longer owned by them);
 *   every account the factory ever created stays in `isAccount`
 *   (invariant 17).
 * - The Safe has no function here that moves an account's assets or changes
 *   its owner or beneficiary (invariant 16). What it can change is listed
 *   below, and every value an account reads from here is clamped by limits
 *   hard-coded in the account, because this contract is upgradeable and an
 *   account is not.
 * - Prices change only through scheduleFee, at least FEE_CHANGE_DELAY ahead,
 *   so every subscriber can be told before a renewal at the new price
 *   (decision 24).
 * - The relayer (not the Safe) records one-hour approvals for a designation
 *   or an acceptance after the server's checks; an account refuses either
 *   step without one (decision 26, invariant 18).
 */

import {Ownable2StepUpgradeable} from "@openzeppelin/contracts-upgradeable/access/Ownable2StepUpgradeable.sol";
import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {Clones} from "@openzeppelin/contracts/proxy/Clones.sol";
import {IConfioSmartAccountFactory} from "./interfaces/IConfioSmartAccountFactory.sol";

/// What the factory reads from the cUSD+ vault: its sponsor set defines the
/// relayer, exactly as in the account.
interface ISmartAccountFactoryCusdPlus {
    function isSponsor(address account) external view returns (bool);
}

/// Chainlink AggregatorV3 subset, to check a CONFIO price reference.
interface ISmartAccountFactoryPriceRef {
    function decimals() external view returns (uint8);
    function latestRoundData()
        external
        view
        returns (uint80 roundId, int256 answer, uint256 startedAt, uint256 updatedAt, uint80 answeredInRound);
}

/// What the factory reads from the account implementation.
interface ISmartAccountImplementation {
    function FACTORY() external view returns (address);
    function MAX_MONTHLY_FEE_USD() external view returns (uint256);
    function MAX_ANNUAL_FEE_USD() external view returns (uint256);
    function initialize(address owner_) external;
    function owner() external view returns (address);
    function inherited() external view returns (bool);
}

contract ConfioSmartAccountFactory is
    IConfioSmartAccountFactory,
    Ownable2StepUpgradeable,
    PausableUpgradeable,
    UUPSUpgradeable
{
    /// Notice before a price change takes effect (9.3).
    uint64 public constant FEE_CHANGE_DELAY = 30 days;

    // Bounds for the Safe's setters. They mirror the account's hard-coded
    // clamps so a value set here is the value an account uses.
    uint64 public constant MIN_CHALLENGE_WINDOW = 90 days;
    uint64 public constant MAX_CHALLENGE_WINDOW = 1825 days;
    uint64 public constant MIN_CLAIM_COOLDOWN = 1 days;
    uint64 public constant MAX_CLAIM_COOLDOWN = 90 days;
    uint64 public constant MIN_FORCED_SALE_NOTICE = 3 days;
    uint64 public constant MAX_FORCED_SALE_NOTICE = 60 days;

    /// Life of a relayer approval for one designation or acceptance.
    uint64 public constant APPROVAL_TTL = 1 hours;
    /// The account's CONFIO_FEED_MAX_AGE: a price reference older than this
    /// would refuse every CONFIO forced sale.
    uint256 public constant CONFIO_PRICE_REF_MAX_AGE = 26 hours;

    /// Constructor immutables of the logic contract, not proxy storage. An
    /// upgrade must pass the same values (they are the account's).
    address public immutable CUSD_PLUS;
    address public immutable STOCK_ROUTER;

    uint8 private constant PLAN_MONTHLY = 1;
    uint8 private constant PLAN_ANNUAL = 2;

    struct FeeSchedule {
        /// Price in force until `effectiveAt`.
        uint256 current;
        /// Price in force from `effectiveAt` on. Meaningful when it is set.
        uint256 next;
        uint64 effectiveAt;
    }

    /// The account implementation every clone points at.
    address public implementation;
    mapping(address => address) public accountOf;
    mapping(address => bool) public isAccount;
    mapping(uint8 => FeeSchedule) private _fees;
    mapping(uint64 => bool) public allowedChallengeWindows;
    uint64 public claimCooldown;
    uint64 public forcedSaleNotice;
    /// One-way (rollout step 2). setBeneficiary reverts while false.
    bool public inheritanceEnabled;
    /// Blocks relayer functions on every account, and nothing else (I-15).
    bool public relayerPaused;
    ConfioSale private _confioSale;
    // Appended (storage is append-only): relayer approvals, by account.
    mapping(address => mapping(bytes32 => uint64)) public designationApprovedUntil;
    mapping(address => mapping(address => uint64)) public acceptanceApprovedUntil;
    /// Generation of accountOf[owner]: 0 for the first account, +1 for each
    /// account opened after the previous one was inherited (salt 3.1).
    mapping(address => uint64) public generationOf;
    // Appended for decision 35: card spenders.
    mapping(address => bool) public isCardSpender;
    /// Stops every card pull on every account, and nothing else.
    bool public cardPaused;

    event CreationPausedSet(bool paused);

    /// @custom:oz-upgrades-unsafe-allow constructor
    /// @custom:oz-upgrades-unsafe-allow state-variable-immutable
    constructor(address cusdPlus, address stockRouter) {
        require(cusdPlus.code.length > 0 && stockRouter.code.length > 0, "non-contract dependency");
        CUSD_PLUS = cusdPlus;
        STOCK_ROUTER = stockRouter;
        _disableInitializers();
    }

    /// `implementation_` must already name this proxy as its FACTORY: the
    /// account is deployed first, against this proxy's predicted address.
    function initialize(address owner_, address implementation_, uint256 monthlyFeeUsd_, uint256 annualFeeUsd_)
        external
        initializer
    {
        require(owner_ != address(0), "zero owner");
        require(implementation_.code.length > 0, "implementation not contract");
        require(ISmartAccountImplementation(implementation_).FACTORY() == address(this), "implementation factory");
        __Ownable_init(owner_);
        __Ownable2Step_init();
        __Pausable_init();
        implementation = implementation_;
        _requireFeeInRange(PLAN_MONTHLY, monthlyFeeUsd_);
        _requireFeeInRange(PLAN_ANNUAL, annualFeeUsd_);
        _fees[PLAN_MONTHLY].current = monthlyFeeUsd_;
        _fees[PLAN_ANNUAL].current = annualFeeUsd_;
        allowedChallengeWindows[90 days] = true;
        allowedChallengeWindows[180 days] = true;
        allowedChallengeWindows[365 days] = true;
        claimCooldown = 30 days;
        forcedSaleNotice = 7 days;
    }

    function _authorizeUpgrade(address) internal view override onlyOwner {}

    /// A zero owner would freeze prices and the relayer pause forever.
    function renounceOwnership() public pure override {
        revert("renounce disabled");
    }

    // ═════════════════════════ Accounts ═════════════════════════════════

    /// The caller becomes the owner. One current account per owner, per
    /// factory. A caller whose current account passed to a beneficiary
    /// through an executed claim opens a new one, one generation on.
    function createAccount() external whenNotPaused returns (address account) {
        address current = accountOf[msg.sender];
        uint64 generation = generationOf[msg.sender];
        if (current != address(0)) {
            require(_replaceable(current, msg.sender), "account exists");
            generationOf[msg.sender] = ++generation;
        }
        account = Clones.cloneDeterministic(implementation, _salt(msg.sender, generation));
        accountOf[msg.sender] = account;
        // Never cleared: an inherited account keeps working for its heir.
        isAccount[account] = true;
        ISmartAccountImplementation(account).initialize(msg.sender);
        emit AccountCreated(msg.sender, account);
    }

    /// Where the next createAccount by `owner_` deploys: generation 0 with
    /// no account, the next generation once the current one is replaceable.
    /// While the current account is still the owner's (active, cancelled or
    /// expired alike) createAccount reverts and this returns that account.
    function predictAddress(address owner_) external view returns (address) {
        address current = accountOf[owner_];
        uint64 generation = generationOf[owner_];
        if (current != address(0)) {
            if (!_replaceable(current, owner_)) return current;
            ++generation;
        }
        return predictAddressAt(owner_, generation);
    }

    function predictAddressAt(address owner_, uint64 generation) public view returns (address) {
        return Clones.predictDeterministicAddress(implementation, _salt(owner_, generation), address(this));
    }

    /// Inherited, or (equivalently, since only a claim changes the owner)
    /// no longer owned by the one who opened it.
    function _replaceable(address account, address owner_) private view returns (bool) {
        return
            ISmartAccountImplementation(account).inherited() || ISmartAccountImplementation(account).owner() != owner_;
    }

    function _salt(address owner_, uint64 generation) private pure returns (bytes32) {
        return keccak256(abi.encode(owner_, generation));
    }

    // ═════════════════════════ Designation approvals (decision 26) ══════

    /// The relayer records that the server checked this exact designation
    /// (identity, residence, disclosure) right before relaying it. The
    /// account refuses setBeneficiary(beneficiary, window) without it.
    function approveDesignation(address account, address beneficiary, uint64 window) external {
        uint64 until = _approvalExpiry(account);
        designationApprovedUntil[account][keccak256(abi.encode(beneficiary, window))] = until;
        emit DesignationApproved(account, beneficiary, window, until);
    }

    /// The same, for `beneficiary` accepting on `account`.
    function approveAcceptance(address account, address beneficiary) external {
        uint64 until = _approvalExpiry(account);
        acceptanceApprovedUntil[account][beneficiary] = until;
        emit AcceptanceApproved(account, beneficiary, until);
    }

    /// Relayer only: a cUSD+ sponsor that is itself the transaction origin
    /// (the account's own definition; a sponsor contract never qualifies).
    function _approvalExpiry(address account) private view returns (uint64) {
        require(
            msg.sender == tx.origin && ISmartAccountFactoryCusdPlus(CUSD_PLUS).isSponsor(msg.sender), "not relayer"
        );
        require(!relayerPaused, "relayer paused");
        require(isAccount[account], "not an account");
        return uint64(block.timestamp) + APPROVAL_TTL;
    }

    // ═════════════════════════ Prices ═══════════════════════════════════

    /// Price in force now for a plan (1 Monthly, 2 Annual), USD 18 decimals.
    function feeUsd(uint8 plan) public view returns (uint256) {
        FeeSchedule storage s = _fees[plan];
        return s.effectiveAt != 0 && block.timestamp >= s.effectiveAt ? s.next : s.current;
    }

    function monthlyFeeUsd() external view returns (uint256) {
        return feeUsd(PLAN_MONTHLY);
    }

    function annualFeeUsd() external view returns (uint256) {
        return feeUsd(PLAN_ANNUAL);
    }

    /// A scheduled price not yet in force: (0, 0) when none.
    function scheduledFee(uint8 plan) external view returns (uint256 newFeeUsd, uint64 effectiveAt) {
        FeeSchedule storage s = _fees[plan];
        if (s.effectiveAt == 0 || block.timestamp >= s.effectiveAt) return (0, 0);
        return (s.next, s.effectiveAt);
    }

    /// Replaces any change still waiting; a change already in force becomes
    /// the current price first.
    function scheduleFee(uint8 plan, uint256 newFeeUsd, uint64 effectiveAt) external onlyOwner {
        _requireFeeInRange(plan, newFeeUsd);
        require(effectiveAt >= block.timestamp + FEE_CHANGE_DELAY, "notice too short");
        FeeSchedule storage s = _fees[plan];
        s.current = feeUsd(plan);
        s.next = newFeeUsd;
        s.effectiveAt = effectiveAt;
        emit FeeScheduled(plan, newFeeUsd, effectiveAt);
    }

    /// An account clamps to its hard-coded maximum anyway; refusing a higher
    /// price here keeps the price shown equal to the price charged.
    function _requireFeeInRange(uint8 plan, uint256 fee) private view {
        require(plan == PLAN_MONTHLY || plan == PLAN_ANNUAL, "bad plan");
        uint256 max = plan == PLAN_MONTHLY
            ? ISmartAccountImplementation(implementation).MAX_MONTHLY_FEE_USD()
            : ISmartAccountImplementation(implementation).MAX_ANNUAL_FEE_USD();
        require(fee > 0 && fee <= max, "fee out of range");
    }

    // ═════════════════════════ Inheritance settings ═════════════════════

    function setChallengeWindow(uint64 window, bool allowed) external onlyOwner {
        require(!allowed || window >= MIN_CHALLENGE_WINDOW, "window too short");
        require(!allowed || window <= MAX_CHALLENGE_WINDOW, "window too long");
        allowedChallengeWindows[window] = allowed;
        emit ChallengeWindowSet(window, allowed);
    }

    function setClaimCooldown(uint64 cooldown) external onlyOwner {
        require(cooldown >= MIN_CLAIM_COOLDOWN && cooldown <= MAX_CLAIM_COOLDOWN, "cooldown out of range");
        claimCooldown = cooldown;
        emit ClaimCooldownSet(cooldown);
    }

    /// One-way.
    function enableInheritance() external onlyOwner {
        require(!inheritanceEnabled, "already enabled");
        inheritanceEnabled = true;
        emit InheritanceEnabled();
    }

    // ═════════════════════════ Billing settings ═════════════════════════

    function setForcedSaleNotice(uint64 notice) external onlyOwner {
        require(notice >= MIN_FORCED_SALE_NOTICE && notice <= MAX_FORCED_SALE_NOTICE, "notice out of range");
        forcedSaleNotice = notice;
        emit ForcedSaleNoticeSet(notice);
    }

    function setRelayerPaused(bool paused_) external onlyOwner {
        relayerPaused = paused_;
        emit RelayerPausedSet(paused_);
    }

    function confioSale() external view returns (address venue, address priceRef) {
        return (_confioSale.venue, _confioSale.priceRef);
    }

    /// Once only (5.5): after it is set it cannot be changed or cleared.
    /// Each account copies it on first use and never reads it again.
    function setConfioSale(address venue, address priceRef) external onlyOwner {
        require(_confioSale.venue == address(0), "already set");
        // The stock router would pass the account's venue check for a token
        // it never sells; zero would read as "unset" in the account.
        require(venue != address(0) && venue != STOCK_ROUTER, "bad venue");
        require(venue.code.length > 0 && priceRef.code.length > 0, "non-contract");
        _requireLivePriceRef(priceRef);
        _confioSale = ConfioSale({venue: venue, priceRef: priceRef});
        emit ConfioSaleSet(venue, priceRef);
    }

    /// A reference the account could never use would block every CONFIO
    /// sale for good once latched: it must answer both calls, with a
    /// positive price updated within the account's maximum age.
    function _requireLivePriceRef(address priceRef) private view {
        try ISmartAccountFactoryPriceRef(priceRef).decimals() returns (uint8) {}
        catch {
            revert("price ref: decimals");
        }
        try ISmartAccountFactoryPriceRef(priceRef).latestRoundData() returns (
            uint80, int256 answer, uint256, uint256 updatedAt, uint80
        ) {
            require(answer > 0 && updatedAt + CONFIO_PRICE_REF_MAX_AGE >= block.timestamp, "price ref: stale");
        } catch {
            revert("price ref: round");
        }
    }

    // ═════════════════════════ Card spenders (decision 35) ═════════════

    /// A spender may be added or removed at any time; a removal stops its
    /// pulls on every account at once, mid-period included.
    function setCardSpender(address spender, bool allowed) external onlyOwner {
        require(spender != address(0), "zero spender");
        isCardSpender[spender] = allowed;
        emit CardSpenderSet(spender, allowed);
    }

    function setCardPaused(bool paused_) external onlyOwner {
        cardPaused = paused_;
        emit CardPausedSet(paused_);
    }

    function cardSpenderAllowed(address spender) external view returns (bool) {
        return isCardSpender[spender] && !cardPaused;
    }

    // ═════════════════════════ Ops ══════════════════════════════════════

    /// Pauses account creation only. Existing accounts are unaffected.
    function pause() external onlyOwner {
        _pause();
        emit CreationPausedSet(true);
    }

    function unpause() external onlyOwner {
        _unpause();
        emit CreationPausedSet(false);
    }
}
