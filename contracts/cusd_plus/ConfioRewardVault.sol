// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ConfioRewardVault — BSC mirror of the Algorand CONFIO Rewards Vault
 * (contracts/rewards/confio_rewards.py).
 *
 * Escrows CONFIO (BEP-20) and lets eligible users self-claim rewards that
 * the Django backend attested off-chain. Same shape as Algorand:
 *  - a hot ATTESTOR key writes per-user eligibility (mirrors the Algorand
 *    admin/sponsor that could call mark_eligible);
 *  - the reward is denominated in cUSD and converted to CONFIO on-chain at
 *    a manually snapshotted price, so the backend locks the USD rate at
 *    attestation time;
 *  - an optional referrer payout is recorded against the referee and can
 *    be claimed exactly once, order-independent of the referee's own claim;
 *  - a solvency invariant guarantees the vault always holds enough CONFIO
 *    to cover every outstanding obligation before a new one is written;
 *  - the owner Safe can withdraw only the surplus above obligations.
 *
 * What the BSC version DROPS (Algorand-specific): boxes, per-box MBR, the
 * sponsor payment that funded box creation, and ASA opt-in checks. Mappings
 * replace boxes; nothing needs pre-funding.
 *
 * Two asymmetries carried over from the Algorand contract on purpose:
 *  - the MAIN reward is passed in cUSD and converted at the price; the
 *    REFERRAL amount is passed directly in CONFIO (confio_rewards.py does
 *    the same — args[1] is cUSD, args[3] is micro-CONFIO).
 *  - `pause` blocks claims as well as attestation. Unlike CusdPlusVault
 *    (exits never gated), these are treasury-funded rewards, not user
 *    principal — a paused reward is still owner-recoverable and re-
 *    attestable, so an emergency stop over claims is acceptable here.
 *
 * Roles: owner = the 3-of-5 Safe (price, attestor rotation, surplus
 * withdraw, pause). attestor = the backend hot key that writes eligibility
 * (high-frequency, cannot be a Safe op). Non-upgradeable — redeploy to
 * change logic; the app points at a new address.
 */

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";

contract ConfioRewardVault is Ownable2Step, Pausable, ReentrancyGuardTransient {
    using SafeERC20 for IERC20;

    uint256 private constant WAD = 1e18;

    IERC20 public immutable CONFIO;

    /// Writes eligibility. Owner-rotatable hot key (the backend attestor).
    address public attestor;

    /// CONFIO price in cUSD (WAD, i.e. USD per whole CONFIO). Must be
    /// active and non-zero for attestation — mirrors MANUAL_ACTIVE/PRICE.
    uint256 public manualPrice;
    bool public manualPriceActive;
    /// Bumped on every price set; stamped onto each reward as an audit
    /// trail of which price was in force when it was written.
    uint64 public priceRound;

    struct Reward {
        uint128 amount;     // CONFIO owed to the user (0 once claimed)
        uint128 refAmount;  // CONFIO owed to `referrer` (0 once claimed)
        address referrer;   // who may claim refAmount (0 if none)
        bool claimed;       // main reward taken
        bool refClaimed;    // referral portion taken (true when none)
        uint64 priceRound;  // price round in force at attestation
    }

    mapping(address => Reward) public rewards;

    // Aggregate obligation tracking (mirrors the Algorand global counters).
    uint256 public totalEligible;
    uint256 public totalClaimed;
    uint256 public totalRefEligible;
    uint256 public totalRefPaid;
    uint256 public eligibleCount;
    uint256 public claimCount;
    uint256 public refClaimCount;

    event AttestorSet(address indexed attestor);
    event ManualPriceSet(uint256 price, uint64 indexed round);
    event ManualPriceCleared(uint64 indexed round);
    event EligibilitySet(
        address indexed user,
        uint256 confioAmount,
        address indexed referrer,
        uint256 refConfioAmount,
        uint64 indexed priceRound
    );
    event Claimed(address indexed user, uint256 confioAmount);
    event ReferralClaimed(address indexed referrer, address indexed referee, uint256 confioAmount);
    event SurplusWithdrawn(address indexed to, uint256 amount);

    constructor(address confio, address attestor_, address owner_) Ownable(owner_) {
        require(confio != address(0) && attestor_ != address(0), "zero address");
        CONFIO = IERC20(confio);
        attestor = attestor_;
        emit AttestorSet(attestor_);
    }

    modifier onlyAttestor() {
        require(msg.sender == attestor, "not attestor");
        _;
    }

    // ═════════════════════════ Views ════════════════════════════════════

    /// CONFIO owed but not yet claimed (main + referral).
    function outstanding() public view returns (uint256) {
        return (totalEligible - totalClaimed) + (totalRefEligible - totalRefPaid);
    }

    /// CONFIO the owner could withdraw without touching any obligation.
    function surplus() public view returns (uint256) {
        uint256 bal = CONFIO.balanceOf(address(this));
        uint256 owed = outstanding();
        return bal > owed ? bal - owed : 0;
    }

    /// cUSD (WAD) → CONFIO (WAD) at the active price. Ceil-free floor
    /// division favors the vault, same as the Algorand WideRatio.
    function quoteConfio(uint256 cusdAmount) public view returns (uint256) {
        require(manualPriceActive && manualPrice > 0, "price not set");
        return Math.mulDiv(cusdAmount, WAD, manualPrice);
    }

    // ═════════════════════════ Attestation ══════════════════════════════

    /// Record a user's reward. `cusdAmount` is converted to CONFIO at the
    /// active price; `refConfioAmount` is CONFIO paid to `referrer` as-is
    /// (0 / address(0) for no referral). Cannot overwrite a still-pending
    /// allocation — the prior one must be claimed (or empty) first.
    function setEligible(
        address user,
        uint256 cusdAmount,
        address referrer,
        uint256 refConfioAmount
    ) external onlyAttestor whenNotPaused {
        require(user != address(0), "zero user");
        require(cusdAmount > 0, "zero reward");

        uint256 confioAmount = quoteConfio(cusdAmount);
        require(confioAmount > 0, "dust reward");
        require(confioAmount <= type(uint128).max, "amount overflow");

        Reward storage r = rewards[user];
        // No overwriting a live allocation (mirrors the Algorand assert
        // that a re-attested box has amount==0 and refAmount==0).
        require(r.amount == 0 && r.refAmount == 0, "pending allocation");

        if (refConfioAmount > 0) {
            require(referrer != address(0) && referrer != user, "bad referrer");
            require(refConfioAmount <= type(uint128).max, "ref overflow");
        } else {
            referrer = address(0);
        }

        // Solvency BEFORE writing: the vault must already hold every
        // outstanding obligation plus this new one.
        require(
            CONFIO.balanceOf(address(this)) >= outstanding() + confioAmount + refConfioAmount,
            "insufficient reserve"
        );

        r.amount = uint128(confioAmount);
        r.claimed = false;
        r.referrer = referrer;
        r.refAmount = uint128(refConfioAmount);
        r.refClaimed = refConfioAmount == 0; // nothing to claim ⇒ settled
        r.priceRound = priceRound;

        totalEligible += confioAmount;
        eligibleCount += 1;
        if (refConfioAmount > 0) totalRefEligible += refConfioAmount;

        emit EligibilitySet(user, confioAmount, referrer, refConfioAmount, priceRound);
    }

    // ═════════════════════════ Claims ═══════════════════════════════════

    /// The user takes their CONFIO. Sponsored gas under 7702 (msg.sender is
    /// the user's own EOA); the vault only cares who msg.sender is.
    function claim() external nonReentrant whenNotPaused returns (uint256 amount) {
        Reward storage r = rewards[msg.sender];
        amount = r.amount;
        require(amount > 0 && !r.claimed, "nothing to claim");

        r.amount = 0;
        r.claimed = true;
        totalClaimed += amount;
        claimCount += 1;

        CONFIO.safeTransfer(msg.sender, amount);
        emit Claimed(msg.sender, amount);
    }

    /// The referrer takes their bonus, order-independent from the referee's
    /// own claim (mirrors claim_referrer). Only the stored referrer may.
    function claimReferral(address referee) external nonReentrant whenNotPaused returns (uint256 amount) {
        Reward storage r = rewards[referee];
        require(r.referrer == msg.sender, "not referrer");
        amount = r.refAmount;
        require(amount > 0 && !r.refClaimed, "nothing to claim");

        r.refAmount = 0;
        r.refClaimed = true;
        totalRefPaid += amount;
        refClaimCount += 1;

        CONFIO.safeTransfer(msg.sender, amount);
        emit ReferralClaimed(msg.sender, referee, amount);
    }

    // ═════════════════════════ Admin (Safe) ═════════════════════════════

    function setManualPrice(uint256 price) external onlyOwner {
        require(price > 0, "zero price");
        manualPrice = price;
        manualPriceActive = true;
        priceRound += 1;
        emit ManualPriceSet(price, priceRound);
    }

    function clearManualPrice() external onlyOwner {
        manualPriceActive = false;
        emit ManualPriceCleared(priceRound);
    }

    function setAttestor(address attestor_) external onlyOwner {
        require(attestor_ != address(0), "zero attestor");
        attestor = attestor_;
        emit AttestorSet(attestor_);
    }

    /// Withdraw ONLY surplus above outstanding obligations — the promised
    /// rewards can never be swept out from under claimers.
    function withdrawSurplus(address to, uint256 amount) external onlyOwner nonReentrant {
        require(to != address(0), "zero recipient");
        require(amount > 0 && amount <= surplus(), "exceeds surplus");
        CONFIO.safeTransfer(to, amount);
        emit SurplusWithdrawn(to, amount);
    }

    function pause() external onlyOwner { _pause(); }
    function unpause() external onlyOwner { _unpause(); }
}
