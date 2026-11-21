// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ABI of a Cuenta inteligente account. Specification:
 * docs/designs/cuenta-inteligente-spec.md (sections 4 to 6). This file is the
 * contract between the Solidity implementation, the backend and the app:
 * change it only together with all three.
 *
 * Roles are decided by msg.sender only:
 *   owner        msg.sender == owner()
 *   beneficiary  msg.sender == beneficiary()
 *   relayer      CUSD_PLUS.isSponsor(msg.sender) && msg.sender == tx.origin
 *   anyone       no check
 */
interface IConfioSmartAccount {
    enum Plan {
        None,
        Monthly,
        Annual
    }

    /// Card (decision 35) is appended: the values of the others are fixed.
    enum RuleKind {
        Send,
        Payout,
        Buy,
        Card
    }

    enum Frequency {
        Daily,
        Weekly,
        Biweekly,
        Monthly
    }

    /// Which Confío dollar. Values match ConfioSwapRouter's source/dest.
    /// 0 = cUSD+ (Confío Dollar+), 1 = cUSD (Confío Dollar).
    // uint8 dollar

    struct RuleInput {
        RuleKind kind;
        Frequency frequency;
        /// cUSD or cUSD+.
        address tokenIn;
        /// Buy: the asset bought. Zero otherwise.
        address tokenOut;
        /// Send: the Confío user's wallet that is paid. Card: the card
        /// issuer's spender, allowlisted in the factory. Zero otherwise.
        address payee;
        /// Payout: hash of the saved bank destination. Zero otherwise.
        bytes32 payoutRef;
        /// Always US dollars, 18 decimals. Never token units. Card: the most
        /// the spender may take per period, gross of the exit fee.
        uint256 amountUsd;
        /// Earliest first run (unix seconds). Zero = now. Card: start of the
        /// first period.
        uint64 firstRunAt;
    }

    struct Rule {
        RuleKind kind;
        Frequency frequency;
        bool active;
        address tokenIn;
        address tokenOut;
        address payee;
        bytes32 payoutRef;
        uint256 amountUsd;
        /// Card: start of the current period, which ends one minimum gap of
        /// `frequency` later (1, 7, 14 or 28 days).
        uint64 nextRunAt;
        /// subscriptionEpoch() when the rule was created or last updated. A
        /// rule of an earlier epoch never runs; rule(id) reports it with
        /// active == false.
        uint64 epoch;
    }

    /// One leg of a forced sale. `data` is the venue calldata
    /// (ConfioStockRouter.sellToSavings or ConfioSwapRouter.sell).
    struct SaleLeg {
        address venue;
        address tokenIn;
        uint256 maxIn;
        bytes data;
    }

    // ── Events ──────────────────────────────────────────────────────────
    /// Every Subscribed starts a new subscription epoch: all earlier rules
    /// are dead, and the beneficiary and any designation are cleared (with
    /// DesignationWithdrawn / BeneficiaryRemoved when there was one).
    event Subscribed(Plan plan, uint256 feeUsd, uint64 paidUntil);
    event PlanChanged(Plan nextPlan);
    event SubscriptionCancelled(uint64 paidUntil);
    event CancelUndone();
    event FeeCollected(Plan plan, uint256 feeUsd, uint256 cusdAmount, uint256 cusdPlusShares, uint256 pPlus, uint64 paidUntil);
    event PaymentNoticeStarted(uint64 forPeriod, uint64 saleAllowedAt);
    event ForcedSale(address indexed tokenIn, uint256 amountIn, uint256 dollarsOut, uint64 forPeriod);
    event Withdrawn(address indexed token, address indexed to, uint256 amount);
    event AssetReturned(address indexed token, uint256 amount);
    event Traded(address indexed venue, address indexed tokenIn, address indexed tokenOut, uint256 amountIn, uint256 amountOut);
    event UsdtConverted(uint8 dollar, uint256 usdtIn, uint256 dollarsOut);
    event RuleCreated(uint256 indexed id, RuleKind kind);
    event RuleUpdated(uint256 indexed id);
    event RuleCancelled(uint256 indexed id);
    event RuleExecuted(uint256 indexed id, address tokenIn, address tokenOut, uint256 amountIn, uint256 amountOut);
    event PayoutSent(uint256 indexed id, bytes32 indexed payoutRef, address destination, address tokenIn, uint256 amountIn, uint256 usdtOut);
    event BeneficiaryNamed(address indexed pendingBeneficiary, uint64 challengeWindow, uint64 expiresAt);
    event BeneficiaryAccepted(address indexed beneficiary, uint64 challengeWindow);
    event DesignationWithdrawn(address indexed pendingBeneficiary);
    event BeneficiaryRemoved(address indexed beneficiary);
    event ClaimInitiated(address indexed beneficiary, uint64 executableAt);
    event ClaimCancelled(address indexed beneficiary, uint64 cooldownUntil);
    event ClaimExecuted(address indexed previousOwner, address indexed newOwner);
    event ConfioSaleLatched(address venue, address priceRef);
    /// `usdSpent` is the gross cUSD redeemed (the USDT plus the 0.9% exit
    /// fee), the amount counted against the rule's cap for the period.
    event CardPulled(uint256 indexed id, address indexed spender, uint256 usdtOut, uint256 usdSpent);

    // ── Setup (factory only) ────────────────────────────────────────────
    function initialize(address owner_) external;

    // ── Owner ───────────────────────────────────────────────────────────
    function subscribe(Plan plan_, uint256 maxFeeUsd) external;
    function changePlan(Plan plan_) external;
    function cancelSubscription() external;
    function undoCancel() external;

    /// Not inherited: pays `owner` only.
    function withdraw(address token, uint256 amount) external;
    function withdrawAll(address[] calldata tokens) external;

    /// Inherited only: `to` is the owner's wallet or the owner's own, still
    /// owned, non-inherited account in the same factory.
    function withdraw(address token, uint256 amount, address to) external;
    function withdrawAll(address[] calldata tokens, address to) external;

    /// `venue` is the stock router or the swap router; `data` is its buy or
    /// sell calldata. The account approves, calls, resets the approval and
    /// checks its own balance deltas.
    function trade(address venue, bytes calldata data, address tokenIn, address tokenOut, uint256 maxIn, uint256 minOut)
        external;

    function createRule(RuleInput calldata input) external returns (uint256 id);
    function updateRule(uint256 id, RuleInput calldata input) external;
    function cancelRule(uint256 id) external;

    /// Requires a live relayer approval in the factory for exactly
    /// (addr, window): designationApprovedUntil (invariant 18).
    function setBeneficiary(address addr, uint64 window) external;
    function withdrawDesignation() external;
    function removeBeneficiary() external;
    /// Explicit owner touch. A no-op success when no claim is pending.
    function cancelClaim() external;

    // ── Beneficiary ─────────────────────────────────────────────────────
    /// msg.sender == pendingBeneficiary; requires a live relayer approval in
    /// the factory: acceptanceApprovedUntil(account, msg.sender).
    function acceptBeneficiary() external;
    function initiateClaim() external;
    function executeClaim() external;

    // ── Relayer ─────────────────────────────────────────────────────────
    function collectFee() external;
    function startPaymentNotice() external;
    function forcedSale(SaleLeg[] calldata legs, uint256 minDollarsOut, address referrer, uint256 shareBps) external;

    /// `data` by rule kind:
    ///   Send    abi.encode(uint8 payeeDollar, uint256 minOut)
    ///   Payout  cUSD:  abi.encode(address destination, uint256 minUsdtOut)
    ///           cUSD+: abi.encode(address destination, uint256 usdtOut, uint256 grossCusd)
    ///           grossCusd <= the rule's amountUsd is redeemed through cUSD's
    ///           0.9% exit after a fee-free unwrap; usdtOut must be exactly
    ///           the USDT the destination receives (grossCusd less the fee).
    ///   Buy     abi.encode(address venue, bytes venueCalldata, uint256 minOut)
    function executeRule(uint256 id, bytes calldata data, address referrer, uint256 shareBps) external;

    function convertUsdt(uint8 dollar, uint256 minDollarsOut, address referrer, uint256 shareBps) external;

    // ── Card spender (decision 35) ──────────────────────────────────────
    /// msg.sender == rule(id).payee of an active Card rule, allowlisted in
    /// the factory (factory.cardSpenderAllowed). Delivers exactly `usdtOut`
    /// USDT to the caller through cUSD's fee-bearing exit (from cUSD+ after
    /// a fee-free unwrap) in this call; no allowance is ever given. The
    /// gross cUSD counts against amountUsd for the current period. Lifecycle
    /// Active and billing Current, like a rule run; not subject to the
    /// relayer pause.
    function cardPull(uint256 id, uint256 usdtOut) external;

    // ── Anyone ──────────────────────────────────────────────────────────
    function returnAsset(address token) external;
    function latchConfioSale() external;

    // ── Views ───────────────────────────────────────────────────────────
    /// The factory that created this account (immutable). Read by
    /// CusdVault.armReferral to recognise an account (decision 32).
    function FACTORY() external view returns (address);
    function owner() external view returns (address);
    function inherited() external view returns (bool);
    function plan() external view returns (Plan);
    function nextPlan() external view returns (Plan);
    function paidUntil() external view returns (uint64);
    function cancelRequested() external view returns (bool);
    function noticeStartedAt() external view returns (uint64);
    function forcedSaleForPeriod() external view returns (uint64);
    /// Fee of the next charge, in USD with 18 decimals, clamped.
    function feeUsd() external view returns (uint256);
    function periodSeconds() external view returns (uint64);
    /// USD value (18 decimals) of the account's cUSD plus cUSD+.
    function dollarsUsd() external view returns (uint256);

    function pendingBeneficiary() external view returns (address);
    function pendingChallengeWindow() external view returns (uint64);
    function pendingBeneficiaryExpiresAt() external view returns (uint64);
    function beneficiary() external view returns (address);
    function challengeWindow() external view returns (uint64);
    function claimStartedAt() external view returns (uint64);
    function claimExecutableAt() external view returns (uint64);
    function claimCooldownUntil() external view returns (uint64);

    function nextRuleId() external view returns (uint256);
    /// `active` is effective: false for a rule of an earlier epoch.
    function rule(uint256 id) external view returns (Rule memory);
    /// Bumped by every subscribe (never by a renewal). Zero before the
    /// first subscription.
    function subscriptionEpoch() external view returns (uint64);
    /// Card: gross USD taken in the period that starts at rule(id).nextRunAt.
    /// Stale (in effect zero) once that period has ended; the next pull
    /// resets it.
    function cardSpentUsd(uint256 id) external view returns (uint256);

    function confioSaleVenue() external view returns (address);
    function confioSalePriceRef() external view returns (address);

    /// Lifecycle: 0 Unsubscribed, 1 Active, 2 CancelPending, 3 Expired, 4 Inherited.
    function status() external view returns (uint8);
    /// Billing (meaningful in Active): 0 Current, 1 PaymentDue, 2 Notice, 3 SaleAllowed.
    function billingStatus() external view returns (uint8);
    /// Claim: 0 NoClaim, 1 ClaimPending, 2 Executable.
    function claimStatus() external view returns (uint8);
}
