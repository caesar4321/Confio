// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ABI of a Cuenta inteligente account, implementation v2 (hands-off trades
 * and purchases). A strict superset of IConfioSmartAccount: every v1 value,
 * event and function is unchanged; RuleKind gains Trade and Purchase
 * (appended), and relayTrade, relayPurchase, bucketOf, VERSION and
 * initializeMigrated are added. A separate file so the deployed v1
 * implementation, which imports IConfioSmartAccount, stays byte-for-byte
 * reproducible. Specification:
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
interface IConfioSmartAccountV2 {
    enum Plan {
        None,
        Monthly,
        Annual
    }

    /// Card (decision 35), then Trade and Purchase (hands-off, v2) are
    /// appended: the values of the others are fixed.
    ///   Trade     tokenIn cUSD or cUSD+; amountUsd = buy cap per minimum gap
    ///             of `frequency` (leaky bucket); tokenOut 0 (any allowed
    ///             asset) or the one asset it may trade; payee 0, payoutRef 0.
    ///             Stocks need tokenIn cUSD+; with cUSD only bitcoin or gold.
    ///   Purchase  tokenIn cUSD or cUSD+; amountUsd = cap per minimum gap
    ///             (leaky bucket); payee = ESCROW (the implementation's
    ///             escrow); tokenOut 0, payoutRef 0.
    enum RuleKind {
        Send,
        Payout,
        Buy,
        Card,
        Trade,
        Purchase
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
    /// A hands-off trade on Trade rule `id` (also emits Traded). amountIn
    /// of tokenIn left the account, amountOut of tokenOut arrived.
    /// usdCounted, added to the rule's bucket: a buy's dollars spent (cUSD at
    /// par, cUSD+ shares at pPlus, rounded up); a sell's value out (bitcoin
    /// and gold at the Chainlink feed, stocks at the quote price).
    event RelayTraded(
        uint256 indexed id,
        address indexed venue,
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 amountOut,
        uint256 usdCounted
    );
    /// A hands-off purchase on Purchase rule `id`: `amount` cUSD deposited
    /// into the escrow for `orderId` (buyer = owner, refunds to this
    /// account), counted in full in the rule's bucket.
    event RelayPurchased(uint256 indexed id, bytes32 indexed orderId, uint256 amount, uint256 usdCounted);

    // ── Setup (factory only) ────────────────────────────────────────────
    function initialize(address owner_) external;
    /// Factory only, from factory.migrate(): the owner's previous account
    /// had a cancelled subscription paid until `paidUntil_` (in the future);
    /// this one starts Active on `plan_` until then (epoch 1), unpaid for
    /// that period; nextPlan_ (the old account's pending changePlan, None
    /// when none) takes effect at the first renewal as there. Emits
    /// Subscribed(plan_, 0, paidUntil_).
    function initializeMigrated(address owner_, Plan plan_, Plan nextPlan_, uint64 paidUntil_) external;

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

    /// Hands-off trade on live Trade rule `id`. Relayer only, billing
    /// Current, factory.tradePaused() false (unreadable = paused), at least
    /// RELAY_TRADE_MIN_GAP (60 s) after the rule's previous relay trade.
    /// `venue` is the stock router (buyWithSavings / sellToSavings) or the
    /// swap router (buy / sell, bitcoin or gold only); the pair is read from
    /// `data`. A buy spends the rule's tokenIn; its dollars count in the
    /// rule's bucket. A sell counts too, at the value of what went out (the
    /// feed, or the quote price for stocks), and must receive dollars within
    /// 1.5% plus the conversion fee of that value. The asset must be the
    /// rule's tokenOut when that is set. maxFeeBps in `data` <= 90; swap buys
    /// within 1.5% (plus the conversion fee) of the Chainlink feed; at most one
    /// cent of USDT may be left over; got >= minOut > 0.
    function relayTrade(uint256 id, address venue, bytes calldata data, uint256 maxIn, uint256 minOut) external;

    /// Hands-off purchase on live Purchase rule `id`. Relayer only, billing
    /// Current, factory.tradePaused() false. Pays exactly `amount` cUSD into
    /// ESCROW.depositFrom(orderId, owner(), merchant, cUSD, amount, feeBps,
    /// deadline, authSig) (a cUSD+ rule first unwraps amount + 5 bps; the
    /// excess stays here as cUSD). `amount` counts in the rule's bucket.
    function relayPurchase(
        uint256 id,
        bytes32 orderId,
        address merchant,
        uint256 amount,
        uint16 feeBps,
        uint256 deadline,
        bytes calldata authSig
    ) external;

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

    /// Trade or Purchase rule: `used` is the bucket's level now (after the
    /// leak of amountUsd per minimum gap since lastAt); `lastAt` is the
    /// time of the rule's last relay trade or purchase (0 = never). Room
    /// for a buy now = amountUsd - used.
    function bucketOf(uint256 id) external view returns (uint256 used, uint256 lastAt);
    /// 2 for this implementation (v1 has no VERSION).
    function VERSION() external view returns (uint256);
    /// The Comprar escrow relayPurchase pays (immutable).
    function ESCROW() external view returns (address);

    function confioSaleVenue() external view returns (address);
    function confioSalePriceRef() external view returns (address);

    /// Lifecycle: 0 Unsubscribed, 1 Active, 2 CancelPending, 3 Expired, 4 Inherited.
    function status() external view returns (uint8);
    /// Billing (meaningful in Active): 0 Current, 1 PaymentDue, 2 Notice, 3 SaleAllowed.
    function billingStatus() external view returns (uint8);
    /// Claim: 0 NoClaim, 1 ClaimPending, 2 Executable.
    function claimStatus() external view returns (uint8);
}
