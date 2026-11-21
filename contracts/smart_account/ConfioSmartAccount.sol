// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ConfioSmartAccount — one user's "Cuenta inteligente".
 * Specification: docs/designs/cuenta-inteligente-spec.md, sections 4 to 6.
 *
 * A separate contract per user, owned by the user's personal wallet (an
 * EIP-7702 EOA). The user moves assets in by plain transfer. Assets inside
 * can be moved by rules the owner stored (automation) and pass to one named
 * beneficiary by an ownership transfer after a long challenge window
 * (inheritance). A subscription fee is taken from inside the account.
 *
 * Philosophy:
 * - Roles are decided by msg.sender only (4.1). The relayer is a cUSD+
 *   sponsor that is ALSO tx.origin: the sponsor set contains contracts (the
 *   routers), and a contract must never hold the relayer role here.
 * - Immutable (decision 23). Deployed as an EIP-1167 clone of one
 *   implementation; the implementation has no upgrade function and contains
 *   no DELEGATECALL, CALLCODE or SELFDESTRUCT (invariant 20). Every limit an
 *   account relies on is a constant below, and whatever the upgradeable
 *   factory returns is clamped to it.
 * - Moving assets to `owner` never depends on the factory: withdraw,
 *   withdrawAll, returnAsset, cancelClaim and the claim functions make no
 *   factory call that can revert them (invariant 20). Factory reads go
 *   through _factoryRead: a gas-capped staticcall whose failure is a value,
 *   never a revert.
 * - Every owner function "touches": it cancels a pending claim (6.4). No
 *   relayer or permissionless function changes claim state (invariant 8).
 * - The account calls only fixed targets (the two vaults, the two routers,
 *   and for CONFIO the venue latched once from the factory, 5.5), measures
 *   its own balance deltas, and leaves no allowance behind (invariant 14).
 */

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {IERC20Metadata} from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Metadata.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";
import {IConfioSmartAccount} from "./interfaces/IConfioSmartAccount.sol";
import {IConfioSmartAccountFactory} from "./interfaces/IConfioSmartAccountFactory.sol";

/// The cUSD+ vault (it IS the cUSD+ token). Only what the account calls.
/// Return values are left undeclared on purpose: the account measures its
/// own balance deltas and never trusts (or pays bytecode to decode) them.
interface ISmartAccountCusdPlus {
    function isSponsor(address account) external view returns (bool);
    function accrue() external;
    function pPlus() external view returns (uint256);
    function subscribeAndMint(uint256 usdtIn, uint256 minUsdyOut, address recipient) external;
    function wrapCusd(uint256 cusdIn, uint256 minUsdyOut, address recipient) external;
    function unwrapToCusd(uint256 shares, uint256 minCusdOut, address recipient) external;
    function redeemToUsdt(uint256 shares, uint256 minUsdtOut, address to) external;
}

/// The cUSD vault (it IS the cUSD token). Only what the account calls.
interface ISmartAccountCusd {
    function feeBps() external view returns (uint256);
    function mintWithFee(uint256 grossUsdt, uint256 minCusdOut, address recipient) external;
    function redeemWithFee(uint256 grossCusd, uint256 minUsdtOut, address recipient) external;
    function armReferral(address referrer, uint256 shareBps) external;
}

/// Chainlink AggregatorV3 subset.
interface ISmartAccountPriceFeed {
    function decimals() external view returns (uint8);
    function latestRoundData()
        external
        view
        returns (uint80 roundId, int256 answer, uint256 startedAt, uint256 updatedAt, uint80 answeredInRound);
}

/// ABI-identical to ConfioStockRouter's GmQuote. Declared here only so the
/// selectors below are derived from signatures, not typed as magic numbers;
/// the tests assert they equal the real routers' selectors.
struct SmartAccountGmQuote {
    uint256 chainId;
    uint256 attestationId;
    bytes32 userId;
    address asset;
    uint256 price;
    uint256 quantity;
    uint256 expiration;
    uint8 side;
    bytes32 additionalData;
}

interface ISmartAccountStockRouter {
    function buyWithSavings(
        SmartAccountGmQuote calldata quote,
        bytes calldata signature,
        uint256 sharesIn,
        uint256 usdtSpend,
        uint256 minUsdtOut,
        uint256 maxFeeBps
    ) external returns (uint256);

    function sellToSavings(
        SmartAccountGmQuote calldata quote,
        bytes calldata signature,
        uint256 minUsdtOut,
        uint256 minSharesOut,
        uint256 maxFeeBps
    ) external returns (uint256);
}

interface ISmartAccountSwapRouter {
    function buy(
        uint8 source,
        uint256 amountIn,
        uint256 minUsdtOut,
        bytes calldata route,
        address tokenOut,
        uint256 minTokenOut,
        uint256 maxFeeBps
    ) external returns (uint256);

    function sell(
        uint8 dest,
        address tokenIn,
        uint256 amountIn,
        bytes calldata route,
        uint256 minUsdtOut,
        uint256 minDestOut,
        uint256 maxFeeBps
    ) external returns (uint256);
}

contract ConfioSmartAccount is IConfioSmartAccount, ReentrancyGuardTransient {
    using SafeERC20 for IERC20;

    // ═════════════════════════ Hard-coded limits (9.3) ══════════════════
    // The factory is upgradeable; an account is not. Each value the account
    // reads from the factory is clamped to one of these.

    /// Ceiling no factory change can exceed for an existing account.
    uint256 public constant MAX_MONTHLY_FEE_USD = 29.99e18;
    uint256 public constant MAX_ANNUAL_FEE_USD = 299.99e18;
    uint64 internal constant MONTHLY_PERIOD = 30 days;
    uint64 internal constant ANNUAL_PERIOD = 365 days;

    /// Cooldown after a cancelled claim: clamp and fallback (invariant 9).
    uint64 internal constant MIN_CLAIM_COOLDOWN = 1 days;
    uint64 internal constant MAX_CLAIM_COOLDOWN = 90 days;
    uint64 internal constant FALLBACK_CLAIM_COOLDOWN = 30 days;

    /// Notice before a forced sale: floor, and the value used when the
    /// factory cannot be read.
    uint64 public constant MIN_FORCED_SALE_NOTICE = 3 days;
    uint64 internal constant FALLBACK_FORCED_SALE_NOTICE = 7 days;

    uint64 public constant MIN_CHALLENGE_WINDOW = 90 days;
    /// Ceiling on the window, so a factory that allows any value cannot
    /// make a claim wait for ever (or overflow its execution time).
    uint64 public constant MAX_CHALLENGE_WINDOW = 1825 days;
    uint64 internal constant PENDING_BENEFICIARY_TTL = 30 days;

    /// Forced-sale proceeds cap: shortfall + 5% + US$1 (5.3).
    uint256 internal constant FORCED_SALE_MARGIN_BPS = 500;
    uint256 internal constant FORCED_SALE_ROUNDING_USD = 1e18;
    /// Bitcoin/gold forced sale: at most 3% below the feed, after the entry
    /// fee (C2).
    uint256 internal constant FEED_TOLERANCE_BPS = 300;
    /// Chainlink BTC/USD and XAU/USD on BSC both run a 600 s heartbeat (and
    /// XAU/USD keeps updating on weekends), so each limit is several
    /// heartbeats. If Chainlink ever lengthens a heartbeat past its limit,
    /// only that token's forced sales stop (fee collection); no owner,
    /// beneficiary or rule path reads a feed.
    uint256 internal constant BTC_FEED_MAX_AGE = 1 hours;
    uint256 internal constant XAU_FEED_MAX_AGE = 2 hours;
    /// 5.5 fixes no age for the CONFIO price reference, which does not exist
    /// yet and may be a once-a-day reference: 26 hours accepts a 24-hour
    /// heartbeat with slack. It matters only once the Safe sets confioSale.
    uint256 internal constant CONFIO_FEED_MAX_AGE = 26 hours;

    /// convertUsdt: the relayer's floor may sit at most this far below the
    /// USDT amount less the live entry fee (4.6).
    uint256 internal constant CONVERT_TOLERANCE_BPS = 50;
    /// CusdVault.MAX_FEE_BPS. The live fee is read, never trusted above this.
    uint256 internal constant MAX_CONVERSION_FEE_BPS = 90;
    /// A Buy rule may leave at most one cent of USDT behind (stock rounding).
    uint256 internal constant USDT_EXCESS_MAX = 1e16;
    /// A cUSD+ Payout unwraps this much more than the gross cUSD it redeems,
    /// so rounding and a small gap between the vault's and Ondo's price
    /// cannot leave the unwrap short. The excess stays here as cUSD.
    uint256 internal constant PAYOUT_UNWRAP_MARGIN_BPS = 5;
    /// A cUSD+ card pull redeems this many wei more again, so the floor
    /// roundings of a very small pull (where 5 bps is zero) cannot leave it
    /// a wei short. It stays here as USDT with the margin.
    uint256 internal constant CARD_REDEEM_ROUNDING = 10;

    /// A factory read may burn at most this much gas, so a broken or hostile
    /// factory cannot starve an owner call (invariant 20).
    uint256 private constant FACTORY_READ_GAS = 100_000;

    uint256 private constant WAD = 1e18;
    uint256 private constant BPS = 10_000;
    uint8 private constant DOLLAR_PLUS = 0; // cUSD+, as in ConfioSwapRouter
    uint8 private constant DOLLAR = 1; // cUSD

    // ═════════════════════════ Immutable configuration (4.2) ════════════
    address public immutable FACTORY;
    /// keccak256 of the EIP-1167 runtime code of a clone of this
    /// implementation (OZ Clones). The inherited-withdraw destination is
    /// recognised by it, never read from the factory (6.6).
    bytes32 private immutable CLONE_CODEHASH;
    // The rest are private: eleven more getters would push the
    // implementation over the 24 KB code limit. They are the constructor
    // arguments of the verified implementation, and the tests pin each one
    // through behaviour.
    address private immutable CUSD;
    address private immutable CUSD_PLUS;
    address private immutable USDT;
    address private immutable CONFIO;
    address private immutable STOCK_ROUTER;
    address private immutable SWAP_ROUTER;
    address private immutable FEE_COLLECTOR;
    address private immutable BTCB;
    address private immutable BTC_FEED;
    address private immutable XAUT;
    address private immutable XAU_FEED;

    // ═════════════════════════ State (4.4) ══════════════════════════════
    address public owner;
    bool public inherited;
    Plan public plan;
    Plan public nextPlan;
    bool public cancelRequested;
    uint64 public paidUntil;

    uint64 public noticeStartedAt;
    uint64 public forcedSaleForPeriod;

    address public pendingBeneficiary;
    uint64 public pendingChallengeWindow;
    uint64 public pendingBeneficiaryExpiresAt;

    address public beneficiary;
    uint64 public challengeWindow;
    uint64 public claimStartedAt;
    uint64 public claimExecutableAt;
    uint64 public claimCooldownUntil;

    uint256 public nextRuleId;
    mapping(uint256 => Rule) private _rules;

    /// Zero until latched from the factory, then fixed (5.5).
    address public confioSaleVenue;
    address public confioSalePriceRef;

    /// Card rules (decision 35): gross USD taken in the period that starts
    /// at the rule's nextRunAt.
    mapping(uint256 => uint256) public cardSpentUsd;

    /// Bumped by every subscribe(), which is allowed only once the previous
    /// subscription has ended (Unsubscribed or Expired); renewals never bump
    /// it. A rule lives only in the epoch it was stored in, so a
    /// re-subscription never revives the rules of an ended one.
    uint64 public subscriptionEpoch;

    // ═════════════════════════ Errors ═══════════════════════════════════
    error NotFactory();
    error NotOwner();
    error NotBeneficiary();
    error NotRelayer();
    /// No live relayer approval in the factory for this designation or
    /// acceptance (invariant 18).
    error NotApproved();
    error RelayerPaused();
    /// Lifecycle, billing or claim state does not allow the call.
    error BadState();
    error IsInherited();
    error NotInherited();
    error BadPlan();
    error FeeAboveMax();
    error FactoryUnavailable();
    error DollarsShort();
    error DollarsCover();
    error AlreadySold();
    error CapExceeded();
    error BadVenue();
    error BadToken();
    /// Venue calldata is not an allowed call or disagrees with the arguments.
    error BadCall();
    error BadAmount();
    error BadDestination();
    error BadRule();
    error TooEarly();
    error Slippage();
    error OverSpent();
    error BalanceFell();
    error StaleFeed();
    error BelowFeed();
    error SelfReferral();
    error InheritanceOff();
    error BadBeneficiary();
    error BadWindow();
    error NoDesignation();
    error DesignationExpired();
    error ClaimAlreadyPending();
    error Cooldown();
    error ConfioSaleUnset();
    error AlreadyLatched();
    error NotSpender();
    /// The factory does not (or cannot be read to) allow this card spender.
    error SpenderNotAllowed();

    constructor(
        address factory,
        address cusd,
        address cusdPlus,
        address usdt,
        address confio,
        address stockRouter,
        address swapRouter,
        address feeCollector,
        address btcb,
        address btcFeed,
        address xaut,
        address xauFeed
    ) {
        require(factory != address(0) && feeCollector != address(0), "zero address");
        require(
            cusd.code.length > 0 && cusdPlus.code.length > 0 && usdt.code.length > 0 && confio.code.length > 0
                && stockRouter.code.length > 0 && swapRouter.code.length > 0 && btcb.code.length > 0
                && btcFeed.code.length > 0 && xaut.code.length > 0 && xauFeed.code.length > 0,
            "non-contract dependency"
        );
        // 5.1 and 4.4 treat the fee, cUSD, cUSD+ and USDT as 18-decimal.
        // Assert it instead of assuming it (X7).
        require(
            IERC20Metadata(cusd).decimals() == 18 && IERC20Metadata(cusdPlus).decimals() == 18
                && IERC20Metadata(usdt).decimals() == 18,
            "dollar decimals"
        );
        FACTORY = factory;
        CLONE_CODEHASH =
            keccak256(abi.encodePacked(hex"363d3d373d3d3d363d73", address(this), hex"5af43d82803e903d91602b57fd5bf3"));
        CUSD = cusd;
        CUSD_PLUS = cusdPlus;
        USDT = usdt;
        CONFIO = confio;
        STOCK_ROUTER = stockRouter;
        SWAP_ROUTER = swapRouter;
        FEE_COLLECTOR = feeCollector;
        BTCB = btcb;
        BTC_FEED = btcFeed;
        XAUT = xaut;
        XAU_FEED = xauFeed;
    }

    /// Called once by the factory right after cloning. The implementation
    /// itself is never initialized: its owner stays zero, so it is inert.
    function initialize(address owner_) external {
        if (msg.sender != FACTORY) revert NotFactory();
        if (owner != address(0) || owner_ == address(0)) revert BadState();
        owner = owner_;
        nextRuleId = 1;
    }

    // ═════════════════════════ Owner: subscription ══════════════════════

    /// First charge is taken here; `maxFeeUsd` is the price the owner signed
    /// (5.4). Allowed from Unsubscribed or Expired only.
    function subscribe(Plan plan_, uint256 maxFeeUsd) external nonReentrant {
        _ownerTouch();
        if (inherited) revert IsInherited();
        if (plan != Plan.None && !_expired()) revert BadState();
        if (plan_ == Plan.None) revert BadPlan();
        uint256 fee = _feeFor(plan_);
        if (fee > maxFeeUsd) revert FeeAboveMax();
        // A notice or sale record of an earlier subscription must never
        // count for this one (4.6); _charge clears the notice.
        cancelRequested = false;
        forcedSaleForPeriod = 0;
        // Every subscribe starts a new subscription (the previous one, if
        // any, has ended): the rules of the old epoch are dead, and the
        // beneficiary and any designation go with it. A new subscription
        // needs a new designation and acceptance. A claim pending on the
        // Expired account was already ended by the touch above.
        ++subscriptionEpoch;
        address pending = pendingBeneficiary;
        if (pending != address(0)) emit DesignationWithdrawn(pending);
        address removed = _dropBeneficiary();
        if (removed != address(0)) emit BeneficiaryRemoved(removed);
        _accrue();
        _charge(plan_, fee);
        emit Subscribed(plan_, fee, paidUntil);
    }

    /// Takes effect at the next renewal; the current period is untouched.
    function changePlan(Plan plan_) external {
        _ownerTouch();
        if (!_active() || !_current()) revert BadState();
        if (plan_ == Plan.None) revert BadPlan();
        // Naming the plan already in force withdraws a pending change.
        nextPlan = plan_ == plan ? Plan.None : plan_;
        emit PlanChanged(nextPlan);
    }

    /// With the period already ended unpaid this makes the account Expired
    /// at once: the return opens and the lapsed period is not charged.
    function cancelSubscription() external {
        _ownerTouch();
        if (!_active() || cancelRequested) revert BadState();
        cancelRequested = true;
        emit SubscriptionCancelled(paidUntil);
    }

    function undoCancel() external {
        _ownerTouch();
        if (!_active() || !cancelRequested) revert BadState();
        cancelRequested = false;
        emit CancelUndone();
    }

    // ═════════════════════════ Owner: assets out ════════════════════════

    /// Not inherited: the only destination is `owner` (3.3).
    function withdraw(address token, uint256 amount) external nonReentrant {
        _ownerTouch();
        if (inherited) revert IsInherited();
        _send(token, owner, amount);
    }

    function withdrawAll(address[] calldata tokens) external nonReentrant {
        _ownerTouch();
        if (inherited) revert IsInherited();
        _sendAll(tokens, owner);
    }

    /// Inherited only (6.6): to the new owner's wallet or the new owner's
    /// own, still owned, non-inherited account in the same factory.
    function withdraw(address token, uint256 amount, address to) external nonReentrant {
        _ownerTouch();
        _requireInheritedDestination(to);
        _send(token, to, amount);
    }

    function withdrawAll(address[] calldata tokens, address to) external nonReentrant {
        _ownerTouch();
        _requireInheritedDestination(to);
        _sendAll(tokens, to);
    }

    // ═════════════════════════ Owner: trade ═════════════════════════════

    /// `data` is the venue's own buy or sell calldata. The traded pair is
    /// read from that calldata, not trusted from the arguments, so through
    /// the swap router the account can only acquire a token it could later
    /// sell for a fee (one with a feed constant).
    function trade(address venue, bytes calldata data, address tokenIn, address tokenOut, uint256 maxIn, uint256 minOut)
        external
        nonReentrant
    {
        _ownerTouch();
        if (!_active() || !_current()) revert BadState();
        bool stock = venue == STOCK_ROUTER;
        if (!stock && venue != SWAP_ROUTER) revert BadVenue();
        (bool isBuy, address tIn, address tOut) = _decodeVenueCall(stock, data);
        if (tIn != tokenIn || tOut != tokenOut) revert BadCall();
        if (!stock && !_isFeedToken(isBuy ? tOut : tIn)) revert BadToken();
        (uint256 spent, uint256 got) = _venueCall(venue, data, tokenIn, tokenOut, maxIn);
        if (got == 0 || got < minOut) revert Slippage();
        emit Traded(venue, tokenIn, tokenOut, spent, got);
    }

    // ═════════════════════════ Owner: rules ═════════════════════════════

    function createRule(RuleInput calldata input) external returns (uint256 id) {
        _ownerTouch();
        if (!_active()) revert BadState();
        id = nextRuleId++;
        _storeRule(id, input);
        emit RuleCreated(id, input.kind);
    }

    function updateRule(uint256 id, RuleInput calldata input) external {
        _ownerTouch();
        if (!_active()) revert BadState();
        if (!_live(_rules[id])) revert BadRule();
        _storeRule(id, input);
        emit RuleUpdated(id);
    }

    /// Stopping a rule is always safe: any lifecycle state (Expired and
    /// payment due included) except Inherited.
    function cancelRule(uint256 id) external {
        _ownerTouch();
        if (inherited) revert IsInherited();
        if (!_live(_rules[id])) revert BadRule();
        _rules[id].active = false;
        emit RuleCancelled(id);
    }

    // ═════════════════════════ Owner: beneficiary ═══════════════════════

    /// Only a designation Confío's relay approved can be made (decision 26,
    /// invariant 18): the KYC and residence checks live in the relay, which
    /// records a one-hour approval for exactly (addr, window) in the factory.
    function setBeneficiary(address addr, uint64 window) external {
        _ownerTouch();
        if (!_active()) revert BadState();
        (bool ok, uint256 enabled) =
            _factoryRead(abi.encodeCall(IConfioSmartAccountFactory.inheritanceEnabled, ()), 0x20);
        if (!ok || enabled != 1) revert InheritanceOff();
        if (addr == address(0) || addr == owner || addr == address(this)) revert BadBeneficiary();
        uint256 allowed;
        (ok, allowed) = _factoryRead(abi.encodeCall(IConfioSmartAccountFactory.allowedChallengeWindows, (window)), 0x20);
        // The floor holds whatever the factory allows.
        if (window < MIN_CHALLENGE_WINDOW || window > MAX_CHALLENGE_WINDOW || !ok || allowed != 1) revert BadWindow();
        _requireApproval(
            abi.encodeCall(
                IConfioSmartAccountFactory.designationApprovedUntil, (address(this), keccak256(abi.encode(addr, window)))
            )
        );
        uint64 expiresAt = uint64(block.timestamp) + PENDING_BENEFICIARY_TTL;
        pendingBeneficiary = addr;
        pendingChallengeWindow = window;
        pendingBeneficiaryExpiresAt = expiresAt;
        emit BeneficiaryNamed(addr, window, expiresAt);
    }

    /// Clears only the unaccepted designation. The accepted beneficiary,
    /// their window and their cooldown stay.
    function withdrawDesignation() external {
        _ownerTouch();
        if (inherited) revert IsInherited();
        address pending = pendingBeneficiary;
        if (pending == address(0)) revert NoDesignation();
        _clearPending();
        emit DesignationWithdrawn(pending);
    }

    /// No sponsor gate: the owner can always remove. Ends the designation
    /// and any pending claim, and clears the cooldown with it.
    function removeBeneficiary() external {
        if (msg.sender != owner) revert NotOwner();
        if (inherited) revert IsInherited();
        emit BeneficiaryRemoved(_dropBeneficiary());
    }

    /// Explicit touch. A no-op success with no claim pending, so the relay
    /// can append it to any batch the owner signs (6.4).
    function cancelClaim() external {
        _ownerTouch();
        if (inherited) revert IsInherited();
    }

    // ═════════════════════════ Beneficiary ══════════════════════════════

    function acceptBeneficiary() external {
        address pending = pendingBeneficiary;
        if (pending == address(0) || msg.sender != pending) revert NotBeneficiary();
        if (!_active()) revert BadState();
        _requireApproval(abi.encodeCall(IConfioSmartAccountFactory.acceptanceApprovedUntil, (address(this), pending)));
        if (block.timestamp >= pendingBeneficiaryExpiresAt) revert DesignationExpired();
        address previous = beneficiary;
        if (previous != pending) {
            // The owner chose this replacement by signing setBeneficiary;
            // the acceptance only completes it. A claim the replaced
            // beneficiary started after the naming ends here.
            if (claimStartedAt != 0) {
                claimStartedAt = 0;
                claimExecutableAt = 0;
                emit ClaimCancelled(previous, 0);
            }
            claimCooldownUntil = 0;
            beneficiary = pending;
        }
        // Re-naming the same person changes only the window: their cooldown
        // and any pending claim (with its fixed execution time) are kept.
        uint64 window = pendingChallengeWindow;
        challengeWindow = window;
        _clearPending();
        emit BeneficiaryAccepted(pending, window);
    }

    /// No sponsor gate (decision 9): works as a plain self-paid transaction.
    function initiateClaim() external {
        _requireBeneficiary();
        if (!_active()) revert BadState();
        if (claimStartedAt != 0) revert ClaimAlreadyPending();
        if (block.timestamp < claimCooldownUntil) revert Cooldown();
        uint64 executableAt = uint64(block.timestamp) + challengeWindow;
        claimStartedAt = uint64(block.timestamp);
        // Fixed here and announced; nothing moves it afterwards (I-10).
        claimExecutableAt = executableAt;
        emit ClaimInitiated(msg.sender, executableAt);
    }

    /// Ownership transfer (6.5). Moves no token and never loops over rules.
    function executeClaim() external {
        _requireBeneficiary();
        // An Expired account returns to the owner's wallet instead (C6).
        if (!_active()) revert BadState();
        if (claimStartedAt == 0 || block.timestamp < claimExecutableAt) revert TooEarly();
        address previous = owner;
        owner = msg.sender;
        inherited = true;
        plan = Plan.None;
        nextPlan = Plan.None;
        paidUntil = 0;
        cancelRequested = false;
        noticeStartedAt = 0;
        forcedSaleForPeriod = 0;
        _clearPending();
        beneficiary = address(0);
        challengeWindow = 0;
        claimStartedAt = 0;
        claimExecutableAt = 0;
        claimCooldownUntil = 0;
        emit ClaimExecuted(previous, msg.sender);
    }

    // ═════════════════════════ Relayer: billing ═════════════════════════

    /// One fee per period: it requires the period to have ended and moves
    /// paidUntil a full period on from now (invariant 3).
    function collectFee() external nonReentrant {
        _requireRelayer();
        if (_current()) revert BadState();
        _accrue();
        Plan charged = _renewalPlan();
        _charge(charged, _feeFor(charged));
    }

    function startPaymentNotice() external {
        _requireRelayer();
        if (_current() || noticeStartedAt != 0) revert BadState();
        _accrue();
        if (_covers(_dollarsUsd(), _feeFor(_renewalPlan()))) revert DollarsCover();
        noticeStartedAt = uint64(block.timestamp);
        emit PaymentNoticeStarted(paidUntil, uint64(block.timestamp + _forcedSaleNotice()));
    }

    /// One atomic operation (5.3): runs the legs, then collects the fee. If
    /// the dollars still fall short the fee collection reverts the whole
    /// call, so nothing is sold without the fee being paid by it.
    function forcedSale(SaleLeg[] calldata legs, uint256 minDollarsOut, address referrer, uint256 shareBps)
        external
        nonReentrant
    {
        _requireRelayer();
        uint64 period = paidUntil;
        uint256 notice = noticeStartedAt;
        if (_current() || notice == 0 || block.timestamp < notice + _forcedSaleNotice()) revert BadState();
        if (forcedSaleForPeriod == period) revert AlreadySold();
        _arm(referrer, shareBps);
        _accrue();
        Plan charged = _renewalPlan();
        uint256 fee = _feeFor(charged);
        uint256 dollarsBefore = _dollarsUsd();
        if (_covers(dollarsBefore, fee)) revert DollarsCover();

        for (uint256 i = 0; i < legs.length; ++i) {
            _saleLeg(legs[i], period);
        }

        uint256 dollarsAfter = _dollarsUsd();
        uint256 shortfall = fee - dollarsBefore;
        uint256 gross = dollarsAfter > dollarsBefore ? dollarsAfter - dollarsBefore : 0;
        if (gross < shortfall) revert DollarsShort();
        if (gross < minDollarsOut) revert Slippage();
        // One cap for the whole operation, however many legs it has.
        if (gross > shortfall + (shortfall * FORCED_SALE_MARGIN_BPS) / BPS + FORCED_SALE_ROUNDING_USD) {
            revert CapExceeded();
        }
        // The period that was unpaid, not the new one.
        forcedSaleForPeriod = period;
        _charge(charged, fee);
    }

    // ═════════════════════════ Relayer: rules ═══════════════════════════

    /// The relayer triggers; payee, token, amount and frequency come from
    /// the rule the owner stored (decisions 16 and 29). Missed runs are not
    /// caught up: the next run is one minimum gap from now.
    function executeRule(uint256 id, bytes calldata data, address referrer, uint256 shareBps) external nonReentrant {
        _requireRelayer();
        if (!_current()) revert BadState();
        Rule storage r = _rules[id];
        if (!_live(r)) revert BadRule();
        if (block.timestamp < r.nextRunAt) revert TooEarly();
        r.nextRunAt = uint64(block.timestamp) + _minGap(r.frequency);
        _arm(referrer, shareBps);
        _accrue();
        address tokenIn = r.tokenIn;
        // The rule amount is dollars. For cUSD+ the share limit is computed
        // here from pPlus, never supplied by the relayer (4.4).
        uint256 limit = tokenIn == CUSD ? r.amountUsd : _toShares(r.amountUsd, _pPlus());
        RuleKind kind = r.kind;
        if (kind == RuleKind.Send) {
            _runSend(id, tokenIn, r.payee, limit, data);
        } else if (kind == RuleKind.Payout) {
            _runPayout(id, r, limit, data);
        } else if (kind == RuleKind.Buy) {
            _runBuy(id, tokenIn, r.tokenOut, limit, data);
        } else {
            // A Card rule is pulled by its spender, never run by the relayer.
            revert BadRule();
        }
    }

    /// USDT never stays as USDT (decision 31). The whole balance enters the
    /// owner's dollar through the normal fee-bearing entry, recipient fixed
    /// to this account. Allowed in any billing state so a USDT deposit can
    /// cure a missed payment.
    function convertUsdt(uint8 dollar, uint256 minDollarsOut, address referrer, uint256 shareBps)
        external
        nonReentrant
    {
        _requireRelayer();
        uint256 usdtIn = _balance(USDT);
        if (usdtIn == 0) revert BadAmount();
        // The vault's own floor is in USDY units, so the account enforces
        // the dollar floor itself and bounds how low the relayer may set it.
        if (minDollarsOut < (usdtIn * (BPS - _conversionFeeBps() - CONVERT_TOLERANCE_BPS)) / BPS) revert Slippage();
        _arm(referrer, shareBps);
        if (dollar > DOLLAR) revert BadCall();
        address token = dollar == DOLLAR ? CUSD : CUSD_PLUS;
        uint256 before = _balance(token);
        IERC20(USDT).forceApprove(token, usdtIn);
        if (dollar == DOLLAR) {
            _call(CUSD, abi.encodeCall(ISmartAccountCusd.mintWithFee, (usdtIn, minDollarsOut, address(this))));
        } else {
            _call(CUSD_PLUS, abi.encodeCall(ISmartAccountCusdPlus.subscribeAndMint, (usdtIn, 0, address(this))));
        }
        IERC20(USDT).forceApprove(token, 0);
        // cUSD at par; cUSD+ shares gained times pPlus.
        uint256 dollarsOut = _balance(token) - before;
        if (dollar == DOLLAR_PLUS) dollarsOut = (dollarsOut * _pPlus()) / WAD;
        if (dollarsOut < minDollarsOut) revert Slippage();
        emit UsdtConverted(dollar, usdtIn, dollarsOut);
    }

    // ═════════════════════════ Card spender (decision 35) ═══════════════

    /// The card issuer's spender pulls exactly `usdtOut` USDT, pushed to it
    /// in this call through the normal 0.9% exit. The gross (USDT plus the
    /// exit fee) counts against the rule's amount for the period: fixed
    /// periods of the frequency's minimum gap from the rule's first run, as
    /// many pulls per period as fit. Not a relayer function, so the relayer
    /// pause does not stop it; the factory's spender allowlist and card
    /// pause do.
    function cardPull(uint256 id, uint256 usdtOut) external nonReentrant {
        Rule storage r = _rules[id];
        if (!_live(r) || r.kind != RuleKind.Card) revert BadRule();
        if (msg.sender != r.payee) revert NotSpender();
        // As a rule run: Active (CancelPending included, claim pending or
        // not, decision 25) and Current. Inherited is never Active.
        if (!_active() || !_current()) revert BadState();
        if (!_cardSpenderAllowed(msg.sender)) revert SpenderNotAllowed();
        if (usdtOut == 0) revert BadAmount();
        uint64 start = r.nextRunAt;
        if (block.timestamp < start) revert TooEarly();
        uint64 gap = _minGap(r.frequency);
        uint256 spent = cardSpentUsd[id];
        if (block.timestamp >= start + gap) {
            // Missed periods are skipped; the cap never carries over.
            r.nextRunAt = start + ((uint64(block.timestamp) - start) / gap) * gap;
            spent = 0;
        }
        _accrue();
        // The smallest gross whose net after cUSD's ceil-rounded fee is
        // exactly usdtOut: ceil(usdtOut * BPS / (BPS - feeBps)).
        uint256 feeBps = _conversionFeeBps();
        uint256 gross = (usdtOut * BPS + (BPS - feeBps) - 1) / (BPS - feeBps);
        spent += gross;
        // Counted before any token moves: no pull, re-entrant or not, can
        // see room that an earlier one already used.
        if (spent > r.amountUsd) revert CapExceeded();
        cardSpentUsd[id] = spent;
        // Both dollars exit through their own 0.9% exit to this account, and
        // exactly usdtOut is pushed on; no allowance is ever given. cUSD+
        // cannot take the Payout path: unwrapToCusd is sponsor-gated and a
        // spender's transaction has no sponsor as origin. cUSD+'s own
        // redeemToUsdt is sized like the Payout unwrap (gross plus the
        // margin); its excess, about the margin, stays as USDT for
        // convertUsdt. USDT the account already held is never used.
        uint256 usdtBefore = _balance(USDT);
        uint256 outBefore = _balanceOf(USDT, msg.sender);
        if (r.tokenIn == CUSD_PLUS) {
            _call(
                CUSD_PLUS,
                abi.encodeCall(
                    ISmartAccountCusdPlus.redeemToUsdt,
                    (
                        _toShares(gross + (gross * PAYOUT_UNWRAP_MARGIN_BPS) / BPS + CARD_REDEEM_ROUNDING, _pPlus()),
                        usdtOut,
                        address(this)
                    )
                )
            );
        } else {
            _call(CUSD, abi.encodeCall(ISmartAccountCusd.redeemWithFee, (gross, usdtOut, address(this))));
        }
        if (_balance(USDT) < usdtBefore + usdtOut) revert BalanceFell();
        IERC20(USDT).safeTransfer(msg.sender, usdtOut);
        uint256 delivered = _balanceOf(USDT, msg.sender) - outBefore;
        if (delivered != usdtOut) revert Slippage();
        emit CardPulled(id, msg.sender, usdtOut, gross);
    }

    // ═════════════════════════ Anyone ═══════════════════════════════════

    /// Per asset, so one failing token cannot block the rest (decision 7).
    /// Opens only after an owner-signed cancellation has run out (I-7).
    function returnAsset(address token) external nonReentrant {
        if (inherited) revert IsInherited();
        if (!_expired()) revert BadState();
        uint256 amount = _balance(token);
        IERC20(token).safeTransfer(owner, amount);
        emit AssetReturned(token, amount);
    }

    /// Copies the CONFIO sale venue and price reference from the factory
    /// once; from then on they are as fixed as this account's code (5.5).
    function latchConfioSale() external {
        if (inherited) revert IsInherited();
        if (confioSaleVenue != address(0)) revert AlreadyLatched();
        if (!_latchConfioSale()) revert ConfioSaleUnset();
    }

    // ═════════════════════════ Views ════════════════════════════════════

    /// Fee of the next charge: the factory's price for the renewal plan,
    /// clamped. The single source for every use of the fee (4.4).
    function feeUsd() external view returns (uint256) {
        return _feeFor(_renewalPlan());
    }

    function periodSeconds() external view returns (uint64) {
        return _period(plan);
    }

    function dollarsUsd() external view returns (uint256) {
        return _dollarsUsd();
    }

    /// `active` is the effective state: false for a rule of an earlier
    /// subscription epoch, whatever was stored.
    function rule(uint256 id) external view returns (Rule memory r) {
        r = _rules[id];
        r.active = _live(_rules[id]);
    }

    /// 0 Unsubscribed, 1 Active, 2 CancelPending, 3 Expired, 4 Inherited.
    function status() external view returns (uint8) {
        if (inherited) return 4;
        if (plan == Plan.None) return 0;
        if (_expired()) return 3;
        return cancelRequested ? 2 : 1;
    }

    /// 0 Current, 1 PaymentDue, 2 Notice, 3 SaleAllowed. Zero outside Active.
    function billingStatus() external view returns (uint8) {
        if (!_active() || _current()) return 0;
        uint256 notice = noticeStartedAt;
        if (notice == 0) return 1;
        return block.timestamp >= notice + _forcedSaleNotice() ? 3 : 2;
    }

    /// 0 NoClaim, 1 ClaimPending, 2 Executable.
    function claimStatus() external view returns (uint8) {
        if (claimStartedAt == 0) return 0;
        return block.timestamp >= claimExecutableAt ? 2 : 1;
    }

    // ═════════════════════════ Internals: roles and state ═══════════════

    /// Every owner function starts here: only `owner`, and any call the
    /// owner signs cancels a pending claim with cooldown (6.4, I-9).
    function _ownerTouch() private {
        if (msg.sender != owner) revert NotOwner();
        _endClaim(true);
    }

    function _endClaim(bool withCooldown) private {
        if (claimStartedAt == 0) return;
        uint64 until = withCooldown ? uint64(block.timestamp) + _claimCooldown() : 0;
        claimStartedAt = 0;
        claimExecutableAt = 0;
        claimCooldownUntil = until;
        emit ClaimCancelled(beneficiary, until);
    }

    /// isCardSpender && !cardPaused in one read. An unreadable factory
    /// fails closed: only card pulls (and Card rule creation) stop.
    function _cardSpenderAllowed(address spender) private view returns (bool) {
        (bool ok, uint256 allowed) =
            _factoryRead(abi.encodeCall(IConfioSmartAccountFactory.cardSpenderAllowed, (spender)), 0x20);
        return ok && allowed == 1;
    }

    function _requireBeneficiary() private view {
        if (msg.sender != beneficiary || msg.sender == address(0)) revert NotBeneficiary();
    }

    /// A relayer approval read from the factory must be live. An unreadable
    /// factory fails closed: only designation and acceptance stop.
    function _requireApproval(bytes memory callData) private view {
        (bool ok, uint256 until) = _factoryRead(callData, 0x20);
        if (!ok || until <= block.timestamp) revert NotApproved();
    }

    /// Relayer functions: a sponsor that is itself the transaction origin,
    /// lifecycle Active (which excludes inherited), and not paused by the
    /// Safe. An unreadable factory counts as paused: only the relayer
    /// functions stop (I-15).
    function _requireRelayer() private view {
        if (
            msg.sender != tx.origin
                || _read(CUSD_PLUS, abi.encodeCall(ISmartAccountCusdPlus.isSponsor, (msg.sender))) != 1
        ) revert NotRelayer();
        if (!_active()) revert BadState();
        (bool ok, uint256 paused) = _factoryRead(abi.encodeCall(IConfioSmartAccountFactory.relayerPaused, ()), 0x20);
        if (!ok || paused != 0) revert RelayerPaused();
    }

    function _expired() private view returns (bool) {
        return cancelRequested && block.timestamp >= paidUntil;
    }

    function _active() private view returns (bool) {
        return plan != Plan.None && !inherited && !_expired();
    }

    function _current() private view returns (bool) {
        return block.timestamp < paidUntil;
    }

    function _clearPending() private {
        pendingBeneficiary = address(0);
        pendingChallengeWindow = 0;
        pendingBeneficiaryExpiresAt = 0;
    }

    /// Ends any claim (no cooldown), the designation and the accepted
    /// beneficiary with their window and cooldown. Returns the beneficiary.
    function _dropBeneficiary() private returns (address removed) {
        _endClaim(false);
        removed = beneficiary;
        _clearPending();
        beneficiary = address(0);
        challengeWindow = 0;
        claimCooldownUntil = 0;
    }

    /// A stored rule runs only while active and of the current
    /// subscription epoch.
    function _live(Rule storage r) private view returns (bool) {
        return r.active && r.epoch == subscriptionEpoch;
    }

    // ═════════════════════════ Internals: factory reads ═════════════════

    /// A staticcall to the factory that cannot revert this call, cannot
    /// burn more than FACTORY_READ_GAS and copies at most two words back.
    /// (A Solidity try/catch would still revert on a factory without code
    /// or on malformed return data.)
    function _factoryRead(bytes memory callData, uint256 minReturn) private view returns (bool ok, uint256 value) {
        (ok, value,) = _factoryRead2(callData, minReturn);
    }

    function _factoryRead2(bytes memory callData, uint256 minReturn)
        private
        view
        returns (bool ok, uint256 first, uint256 second)
    {
        address factory = FACTORY;
        uint256 gasCap = FACTORY_READ_GAS;
        assembly ("memory-safe") {
            ok := staticcall(gasCap, factory, add(callData, 0x20), mload(callData), 0x00, 0x40)
            ok := and(ok, iszero(lt(returndatasize(), minReturn)))
            first := mload(0x00)
            second := mload(0x20)
        }
    }

    function _claimCooldown() private view returns (uint64) {
        (bool ok, uint256 value) = _factoryRead(abi.encodeCall(IConfioSmartAccountFactory.claimCooldown, ()), 0x20);
        if (!ok) return FALLBACK_CLAIM_COOLDOWN;
        if (value < MIN_CLAIM_COOLDOWN) return MIN_CLAIM_COOLDOWN;
        if (value > MAX_CLAIM_COOLDOWN) return MAX_CLAIM_COOLDOWN;
        return uint64(value);
    }

    function _forcedSaleNotice() private view returns (uint256) {
        (bool ok, uint256 value) = _factoryRead(abi.encodeCall(IConfioSmartAccountFactory.forcedSaleNotice, ()), 0x20);
        if (!ok) return FALLBACK_FORCED_SALE_NOTICE;
        if (value < MIN_FORCED_SALE_NOTICE) return MIN_FORCED_SALE_NOTICE;
        // Bounded so the sum with a timestamp cannot overflow.
        return value > type(uint64).max ? type(uint64).max : value;
    }

    function _latchConfioSale() private returns (bool) {
        (bool ok, uint256 venue, uint256 priceRef) =
            _factoryRead2(abi.encodeCall(IConfioSmartAccountFactory.confioSale, ()), 0x40);
        if (!ok || venue == 0 || priceRef == 0 || (venue | priceRef) >> 160 != 0) return false;
        confioSaleVenue = address(uint160(venue));
        confioSalePriceRef = address(uint160(priceRef));
        emit ConfioSaleLatched(address(uint160(venue)), address(uint160(priceRef)));
        return true;
    }

    // ═════════════════════════ Internals: fee ═══════════════════════════

    function _renewalPlan() private view returns (Plan) {
        return nextPlan != Plan.None ? nextPlan : plan;
    }

    function _period(Plan p) private pure returns (uint64) {
        if (p == Plan.Monthly) return MONTHLY_PERIOD;
        if (p == Plan.Annual) return ANNUAL_PERIOD;
        return 0;
    }

    /// The factory's price in force now for `p`, clamped to the hard
    /// maximum. A fee cannot be charged while the factory is unreadable;
    /// nothing an owner or beneficiary needs depends on this.
    function _feeFor(Plan p) private view returns (uint256) {
        if (p == Plan.None) return 0;
        (bool ok, uint256 fee) = _factoryRead(abi.encodeCall(IConfioSmartAccountFactory.feeUsd, (uint8(p))), 0x20);
        if (!ok) revert FactoryUnavailable();
        uint256 max = p == Plan.Monthly ? MAX_MONTHLY_FEE_USD : MAX_ANNUAL_FEE_USD;
        return fee > max ? max : fee;
    }

    /// 5.1: cUSD first, then cUSD+ shares in kind (transferred, never
    /// redeemed, so the user pays no conversion fee on the subscription).
    /// Nothing is taken partially. Then the period starts from now.
    function _charge(Plan charged, uint256 fee) private {
        uint256 cusdAmount = _balance(CUSD);
        if (cusdAmount > fee) cusdAmount = fee;
        uint256 rest = fee - cusdAmount;
        uint256 shares;
        uint256 p;
        if (rest > 0) {
            p = _pPlus();
            shares = _toShares(rest, p);
            if (shares > _balance(CUSD_PLUS)) revert DollarsShort();
        }
        if (cusdAmount > 0) IERC20(CUSD).safeTransfer(FEE_COLLECTOR, cusdAmount);
        if (shares > 0) IERC20(CUSD_PLUS).safeTransfer(FEE_COLLECTOR, shares);

        uint64 until = uint64(block.timestamp) + _period(charged);
        // nextPlan taking effect is the owner's signed instruction, not a
        // relayer choice (4.6).
        plan = charged;
        nextPlan = Plan.None;
        paidUntil = until;
        // The next missed payment needs a fresh notice (I-5).
        noticeStartedAt = 0;
        emit FeeCollected(charged, fee, cusdAmount, shares, p, until);
    }

    /// accrue() is a keeper poke that may be paused or guarded; a revert
    /// only means the stored pPlus is used.
    function _accrue() private {
        try ISmartAccountCusdPlus(CUSD_PLUS).accrue() {} catch {}
    }

    function _pPlus() private view returns (uint256 p) {
        p = _read(CUSD_PLUS, abi.encodeCall(ISmartAccountCusdPlus.pPlus, ()));
        if (p == 0) revert BadAmount();
    }

    /// cUSD at par plus cUSD+ shares at pPlus, 18 decimals. "Covers the fee"
    /// is exactly `_dollarsUsd() >= fee`: floor(shares * pPlus) >= rest is
    /// the same condition as shares >= ceil(rest / pPlus) in _charge.
    function _dollarsUsd() private view returns (uint256) {
        uint256 shares = _balance(CUSD_PLUS);
        uint256 cusd = _balance(CUSD);
        return shares == 0 ? cusd : cusd + (shares * _pPlus()) / WAD;
    }

    /// No notice and no forced sale while the dollars, or the dollars plus
    /// the USDT convertUsdt would turn into dollars (net of the cUSD entry
    /// fee), cover the fee: the relayer converts the USDT first. USDT short
    /// of the gap (dust) does not block a sale.
    function _covers(uint256 dollars, uint256 fee) private view returns (bool) {
        return dollars >= fee || (_balance(USDT) * (BPS - _conversionFeeBps())) / BPS >= fee - dollars;
    }

    /// Shares worth `usd` at share price `p`, rounded up (5.1, 4.4). Plain
    /// checked arithmetic: dollar amounts are far below the overflow bound.
    function _toShares(uint256 usd, uint256 p) private pure returns (uint256) {
        return (usd * WAD + p - 1) / p;
    }

    function _conversionFeeBps() private view returns (uint256 fee) {
        fee = _read(CUSD, abi.encodeCall(ISmartAccountCusd.feeBps, ()));
        if (fee > MAX_CONVERSION_FEE_BPS) fee = MAX_CONVERSION_FEE_BPS;
    }

    /// Optional fee referral (decision 32). The referee is the account; the
    /// owner can never be their own referrer.
    function _arm(address referrer, uint256 shareBps) private {
        if (referrer == address(0)) return;
        if (referrer == owner) revert SelfReferral();
        _call(CUSD, abi.encodeCall(ISmartAccountCusd.armReferral, (referrer, shareBps)));
    }

    // ═════════════════════════ Internals: transfers ═════════════════════

    // Calls to the fixed vaults and plain reads go through these two
    // helpers instead of typed high-level calls: each typed call site costs
    // its own code-size check and return decoding, and together they were
    // about 2 KB of the 24 KB limit. Behaviour is the same for every target
    // here. _call targets only CUSD and CUSD_PLUS, which the constructor
    // requires to have code (a proxy's code cannot be removed), returns are
    // never used (balances are measured), and a revert is bubbled as is.
    // _read requires a full word back, so a target without code (no
    // return data) reverts as a typed call would; callers compare words
    // strictly (a flag must equal 1, an address its 160-bit value).

    function _call(address target, bytes memory data) private {
        (bool ok, bytes memory ret) = target.call(data);
        if (!ok) {
            assembly ("memory-safe") {
                revert(add(ret, 0x20), mload(ret))
            }
        }
    }

    function _read(address target, bytes memory data) private view returns (uint256 word) {
        (bool ok, bytes memory ret) = target.staticcall(data);
        if (!ok || ret.length < 32) {
            assembly ("memory-safe") {
                revert(add(ret, 0x20), mload(ret))
            }
        }
        assembly ("memory-safe") {
            word := mload(add(ret, 0x20))
        }
    }

    function _balance(address token) private view returns (uint256) {
        return _balanceOf(token, address(this));
    }

    function _balanceOf(address token, address who) private view returns (uint256) {
        return _read(token, abi.encodeCall(IERC20.balanceOf, (who)));
    }

    function _send(address token, address to, uint256 amount) private {
        IERC20(token).safeTransfer(to, amount);
        emit Withdrawn(token, to, amount);
    }

    function _sendAll(address[] calldata tokens, address to) private {
        for (uint256 i = 0; i < tokens.length; ++i) {
            _send(tokens[i], to, _balance(tokens[i]));
        }
    }

    /// `to == owner` reads nothing. The own-account form reads no factory
    /// and derives no address (an owner may have several generations, 3.1):
    /// `to` must be a clone of this implementation, owned by the new owner
    /// and not itself inherited. Only FACTORY can initialize a clone, so a
    /// look-alike clone deployed by anyone else reports owner() == 0. A
    /// clone is owned by someone other than its opener only after a claim,
    /// which marks it inherited, so the one match is the new owner's
    /// current account (factory.accountOf).
    function _requireInheritedDestination(address to) private view {
        if (!inherited) revert NotInherited();
        address newOwner = owner;
        if (to == newOwner) return;
        if (
            to.codehash != CLONE_CODEHASH || _read(to, abi.encodeCall(IConfioSmartAccount.owner, ())) != uint160(newOwner)
                || _read(to, abi.encodeCall(IConfioSmartAccount.inherited, ())) != 0
        ) revert BadDestination();
    }

    // ═════════════════════════ Internals: rules ═════════════════════════

    function _minGap(Frequency f) private pure returns (uint64) {
        if (f == Frequency.Daily) return 1 days;
        if (f == Frequency.Weekly) return 7 days;
        if (f == Frequency.Biweekly) return 14 days;
        return 28 days;
    }

    function _isDollar(address token) private view returns (bool) {
        return token == CUSD || token == CUSD_PLUS;
    }

    /// The tokens with a feed constant: the only ones the swap router may
    /// trade for this account.
    function _isFeedToken(address token) private view returns (bool) {
        return token == BTCB || token == XAUT;
    }

    function _storeRule(uint256 id, RuleInput calldata input) private {
        if (!_isDollar(input.tokenIn) || input.amountUsd == 0) revert BadRule();
        bool ok;
        if (input.kind == RuleKind.Send) {
            ok = input.payee != address(0) && input.payee != address(this) && input.tokenOut == address(0)
                && input.payoutRef == bytes32(0);
        } else if (input.kind == RuleKind.Payout) {
            ok = input.payoutRef != bytes32(0) && input.payee == address(0) && input.tokenOut == address(0);
        } else if (input.kind == RuleKind.Card) {
            // The spender must be allowlisted now and on every pull. The
            // factory refuses to allowlist zero; this account could never
            // pull from itself, since it never calls cardPull.
            ok = input.tokenOut == address(0) && input.payoutRef == bytes32(0) && _cardSpenderAllowed(input.payee);
        } else {
            // Buy: bitcoin or gold through the swap router from either
            // dollar; anything else is a stock, which takes cUSD+ only.
            address out = input.tokenOut;
            ok = out != address(0) && !_isDollar(out) && out != USDT && input.payee == address(0)
                && input.payoutRef == bytes32(0) && (_isFeedToken(out) || input.tokenIn == CUSD_PLUS);
        }
        if (!ok) revert BadRule();
        uint64 firstRun = input.firstRunAt > block.timestamp ? input.firstRunAt : uint64(block.timestamp);
        _rules[id] = Rule({
            kind: input.kind,
            frequency: input.frequency,
            active: true,
            tokenIn: input.tokenIn,
            tokenOut: input.tokenOut,
            payee: input.payee,
            payoutRef: input.payoutRef,
            amountUsd: input.amountUsd,
            nextRunAt: firstRun,
            epoch: subscriptionEpoch
        });
    }

    /// Send (4.7): `limit` of tokenIn is delivered to the stored payee in
    /// the payee's own dollar. The relayer chooses only the form; the
    /// conversion is the vault's fee-free one, minted straight to the payee,
    /// so this account never holds the other dollar (decision 17).
    function _runSend(uint256 id, address tokenIn, address payee, uint256 limit, bytes calldata data) private {
        (uint8 payeeDollar, uint256 minOut) = abi.decode(data, (uint8, uint256));
        if (payeeDollar > DOLLAR) revert BadCall();
        address tokenOut = payeeDollar == DOLLAR_PLUS ? CUSD_PLUS : CUSD;
        uint256 inBefore = _balance(tokenIn);
        uint256 outBefore = _balanceOf(tokenOut, payee);
        if (tokenOut == tokenIn) {
            IERC20(tokenIn).safeTransfer(payee, limit);
        } else if (tokenIn == CUSD_PLUS) {
            _call(CUSD_PLUS, abi.encodeCall(ISmartAccountCusdPlus.unwrapToCusd, (limit, minOut, payee)));
        } else {
            IERC20(CUSD).forceApprove(CUSD_PLUS, limit);
            // The vault's floor is in USDY units; the share floor is below.
            _call(CUSD_PLUS, abi.encodeCall(ISmartAccountCusdPlus.wrapCusd, (limit, 0, payee)));
            IERC20(CUSD).forceApprove(CUSD_PLUS, 0);
        }
        uint256 spent = _spent(tokenIn, inBefore, limit);
        uint256 got = _balanceOf(tokenOut, payee) - outBefore;
        if (got == 0 || got < minOut) revert Slippage();
        emit RuleExecuted(id, tokenIn, tokenOut, spent, got);
    }

    /// Payout (4.7): exit tokenIn to USDT through cUSD's normal fee-bearing
    /// exit, paid to the address the relayer names for this run. That
    /// address is a per-transfer bridge deposit address and is the one exit
    /// this contract does not bind (decision 29, C7).
    /// cUSD: redeems `limit` (the rule amount). cUSD+: the bridge needs an
    /// exact USDT amount, which a cUSD+ exit priced at inclusion cannot
    /// give. So the relayer names a gross cUSD amount up to the rule amount;
    /// the account unwraps (fee-free) shares computed here to cover it plus
    /// the margin, never more than `limit`, then redeems exactly that gross,
    /// and the USDT delivered must equal the relayer's figure. The unwrap
    /// excess stays here as cUSD; the owner's own cUSD is never spent.
    function _runPayout(uint256 id, Rule storage r, uint256 limit, bytes calldata data) private {
        (address destination, uint256 minUsdtOut) = abi.decode(data, (address, uint256));
        if (destination == address(0) || destination == address(this)) revert BadDestination();
        address tokenIn = r.tokenIn;
        bool plusIn = tokenIn == CUSD_PLUS;
        uint256 inBefore = _balance(tokenIn);
        uint256 outBefore = _balanceOf(USDT, destination);
        uint256 gross = limit;
        uint256 cusdBefore;
        if (plusIn) {
            (,, gross) = abi.decode(data, (address, uint256, uint256));
            if (gross == 0 || gross > r.amountUsd) revert BadAmount();
            cusdBefore = _balance(CUSD);
            uint256 shares = _toShares(gross + (gross * PAYOUT_UNWRAP_MARGIN_BPS) / BPS, _pPlus());
            _call(
                CUSD_PLUS,
                abi.encodeCall(ISmartAccountCusdPlus.unwrapToCusd, (shares > limit ? limit : shares, gross, address(this)))
            );
        }
        _call(CUSD, abi.encodeCall(ISmartAccountCusd.redeemWithFee, (gross, minUsdtOut, destination)));
        if (_balance(CUSD) < cusdBefore) revert BalanceFell();
        uint256 usdtOut = _balanceOf(USDT, destination) - outBefore;
        uint256 spent = _spent(tokenIn, inBefore, limit);
        if (usdtOut == 0 || usdtOut < minUsdtOut || (plusIn && usdtOut != minUsdtOut)) revert Slippage();
        emit PayoutSent(id, r.payoutRef, destination, tokenIn, spent, usdtOut);
        emit RuleExecuted(id, tokenIn, USDT, spent, usdtOut);
    }

    /// Buy (4.7): venue and selector fixed by the rule's tokenOut; the pair
    /// in the venue calldata must be the rule's pair; spend at most `limit`.
    function _runBuy(uint256 id, address tokenIn, address tokenOut, uint256 limit, bytes calldata data) private {
        (address venue, bytes memory venueData, uint256 minOut) = abi.decode(data, (address, bytes, uint256));
        _requireBuyCall(venue, venueData, tokenIn, tokenOut);
        uint256 usdtBefore = _balance(USDT);
        (uint256 spent, uint256 got) = _venueCall(venue, venueData, tokenIn, tokenOut, limit);
        // A stock buy returns its unspent USDT. More than a cent of it would
        // let the relayer redeem the rule amount, buy a sliver and force a
        // second entry fee through convertUsdt.
        if (got == 0 || got < minOut || _balance(USDT) > usdtBefore + USDT_EXCESS_MAX) revert Slippage();
        emit RuleExecuted(id, tokenIn, tokenOut, spent, got);
    }

    function _requireBuyCall(address venue, bytes memory venueData, address tokenIn, address tokenOut) private view {
        bool stock = !_isFeedToken(tokenOut);
        if (venue != (stock ? STOCK_ROUTER : SWAP_ROUTER)) revert BadVenue();
        (bool isBuy, address tIn, address tOut) = _decodeVenueCall(stock, venueData);
        if (!isBuy || tIn != tokenIn || tOut != tokenOut) revert BadCall();
    }

    function _spent(address token, uint256 before, uint256 limit) private view returns (uint256 spent) {
        uint256 nowBalance = _balance(token);
        spent = before > nowBalance ? before - nowBalance : 0;
        if (spent > limit) revert OverSpent();
    }

    // ═════════════════════════ Internals: forced sale ═══════════════════

    /// One leg: the token must have a price reference. A stock's is the
    /// Ondo-signed quote the stock router settles at; bitcoin, gold and
    /// (once latched) CONFIO are checked here against their feed.
    function _saleLeg(SaleLeg calldata leg, uint64 period) private {
        address token = leg.tokenIn;
        if (_isDollar(token) || token == USDT) revert BadToken();
        bool stock = leg.venue == STOCK_ROUTER;
        address feed;
        uint256 maxAge;
        if (stock) {
            if (_isFeedToken(token) || token == CONFIO) revert BadVenue();
        } else {
            address venue;
            (venue, feed, maxAge) = _saleReference(token);
            if (leg.venue != venue) revert BadVenue();
        }
        (bool isBuy, address tIn, address tOut) = _decodeVenueCall(stock, leg.data);
        if (isBuy || tIn != token) revert BadCall();

        uint256 dollarsBefore = _dollarsUsd();
        (uint256 sold,) = _venueCall(leg.venue, leg.data, token, tOut, leg.maxIn);
        uint256 dollarsAfter = _dollarsUsd();
        uint256 got = dollarsAfter > dollarsBefore ? dollarsAfter - dollarsBefore : 0;
        if (sold == 0 || got == 0) revert Slippage();
        if (!stock) _requireFeedPrice(token, feed, maxAge, sold, got);
        emit ForcedSale(token, sold, got, period);
    }

    /// Venue, feed and maximum feed age for a non-stock token. CONFIO reads
    /// the latched slot, latching it first if the Safe has set it (5.5).
    function _saleReference(address token) private returns (address venue, address feed, uint256 maxAge) {
        if (token == BTCB) return (SWAP_ROUTER, BTC_FEED, BTC_FEED_MAX_AGE);
        if (token == XAUT) return (SWAP_ROUTER, XAU_FEED, XAU_FEED_MAX_AGE);
        if (token != CONFIO) revert BadToken();
        if (confioSaleVenue == address(0) && !_latchConfioSale()) revert ConfioSaleUnset();
        return (confioSaleVenue, confioSalePriceRef, CONFIO_FEED_MAX_AGE);
    }

    /// C2: the route is the relayer's choice, so the dollars received per
    /// unit sold are held to the feed. A feed older than its maximum age
    /// (a Chainlink outage, or a lengthened heartbeat) refuses the sale; it
    /// is retried later like any failed sale.
    function _requireFeedPrice(address token, address feed, uint256 maxAge, uint256 sold, uint256 got) private view {
        (, int256 answer,, uint256 updatedAt,) = ISmartAccountPriceFeed(feed).latestRoundData();
        if (answer <= 0 || block.timestamp > updatedAt + maxAge) revert StaleFeed();
        // Checked: absurd decimals overflow and revert.
        uint256 scale = 10
            ** (
                _read(token, abi.encodeCall(IERC20Metadata.decimals, ()))
                    + _read(feed, abi.encodeCall(ISmartAccountPriceFeed.decimals, ()))
            );
        uint256 refUsd = (sold * uint256(answer) * WAD) / scale;
        uint256 floor = (refUsd * (BPS - _conversionFeeBps()) * (BPS - FEED_TOLERANCE_BPS)) / (BPS * BPS);
        if (got < floor) revert BelowFeed();
    }

    // ═════════════════════════ Internals: venue calls ═══════════════════

    /// Reads the traded pair out of a router call. `stock` selects the
    /// stock router's ABI; otherwise the swap router's (the CONFIO venue
    /// must speak the swap router's `sell`). Any other selector reverts.
    function _decodeVenueCall(bool stock, bytes memory data)
        private
        view
        returns (bool isBuy, address tokenIn, address tokenOut)
    {
        bytes4 selector = bytes4(data);
        if (stock) {
            // GmQuote is static, so quote.asset is the fourth head word.
            address asset = _addressAt(data, 3);
            if (selector == ISmartAccountStockRouter.buyWithSavings.selector) return (true, CUSD_PLUS, asset);
            if (selector == ISmartAccountStockRouter.sellToSavings.selector) return (false, asset, CUSD_PLUS);
        } else {
            uint256 dollar = _wordAt(data, 0);
            if (dollar > DOLLAR) revert BadCall();
            address dollarToken = dollar == DOLLAR_PLUS ? CUSD_PLUS : CUSD;
            if (selector == ISmartAccountSwapRouter.buy.selector) return (true, dollarToken, _addressAt(data, 4));
            if (selector == ISmartAccountSwapRouter.sell.selector) return (false, _addressAt(data, 1), dollarToken);
        }
        revert BadCall();
    }

    function _wordAt(bytes memory data, uint256 index) private pure returns (uint256 word) {
        if (data.length < 36 + 32 * index) revert BadCall();
        assembly ("memory-safe") {
            word := mload(add(data, add(36, mul(32, index))))
        }
    }

    function _addressAt(bytes memory data, uint256 index) private pure returns (address) {
        uint256 word = _wordAt(data, index);
        if (word >> 160 != 0) revert BadCall();
        return address(uint160(word));
    }

    /// Approve `maxIn`, call the venue, reset the approval to zero, and
    /// measure this account's own balances: tokenIn fell by at most maxIn,
    /// and neither dollar nor USDT fell unless it is tokenIn (4.6, I-6).
    function _venueCall(address venue, bytes memory data, address tokenIn, address tokenOut, uint256 maxIn)
        private
        returns (uint256 spent, uint256 got)
    {
        uint256 cusdBefore = _balance(CUSD);
        uint256 plusBefore = _balance(CUSD_PLUS);
        uint256 usdtBefore = _balance(USDT);
        uint256 inBefore = _balance(tokenIn);
        uint256 outBefore = _balance(tokenOut);

        IERC20(tokenIn).forceApprove(venue, maxIn);
        (bool ok, bytes memory returndata) = venue.call(data);
        if (!ok) {
            assembly ("memory-safe") {
                revert(add(returndata, 0x20), mload(returndata))
            }
        }
        IERC20(tokenIn).forceApprove(venue, 0);

        spent = _spent(tokenIn, inBefore, maxIn);
        uint256 outAfter = _balance(tokenOut);
        got = outAfter > outBefore ? outAfter - outBefore : 0;
        if (
            (tokenIn != CUSD && _balance(CUSD) < cusdBefore)
                || (tokenIn != CUSD_PLUS && _balance(CUSD_PLUS) < plusBefore) || _balance(USDT) < usdtBefore
        ) revert BalanceFell();
    }
}
