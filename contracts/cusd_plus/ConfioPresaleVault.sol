// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ConfioPresaleVault — $CONFIO presale on BSC with an on-chain piecewise
 * linear price curve and sponsor-gated participation.
 *
 * Replaces the stepped Algorand presale (Phase 1-1 0.20 / 1-2 0.25 / 1-3
 * 0.30 … with manual admin repricing) with one continuous rule the contract
 * itself enforces — curve "A", chosen over a power curve because anyone can
 * verify it with three lines of arithmetic:
 *
 *   segment 1:  0 →  4M CONFIO   $0.20 → $0.30   (avg 0.25 → $1M)
 *   segment 2:  4M → 24M CONFIO  $0.30 → $0.70   (avg 0.50 → $10M)
 *   segment 3: 24M → 74M CONFIO  $0.70 → $1.30   (avg 1.00 → $50M)
 *                                        full sale = $61M
 *
 * Within each segment the price rises linearly with cumulative tokens sold.
 * The segment table is set in the constructor and there is NO function that
 * can change it — nobody, not even the owner, can reprice. That is the
 * point: "the rules are public and cannot change" is proven by code.
 *
 * Units: prices are PAYMENT-token base units per 1 whole CONFIO (1e18
 * CONFIO base units), so the math is agnostic to the payment token's
 * decimals. CONFIO allocations are recorded in 1e18 base units.
 *
 * Buying q tokens costs the exact integral under the curve (per-segment
 * closed form, rounded up, favoring the vault), charged atomically with
 * recording the allocation — payment verification, price computation and
 * cumulative-sold update all happen in one transaction.
 *
 * ACCESS CONTROL (the geo gate): `buy` executes only inside a transaction
 * originated by an approved sponsor (`tx.origin`) or called by one
 * directly. Confío's user EOAs delegate to ConfioBatchDelegate (EIP-7702);
 * the sponsor KMS wallet broadcasts the type-4 batch
 * [payment.approve(vault, cap), vault.buy(q, cap)], so inside the batch
 * msg.sender is the user's EOA (the buyer of record) and tx.origin is the
 * sponsor. The backend therefore decides WHO buys (geo/eligibility/limits
 * stay in Django) while the contract alone decides AT WHAT PRICE. The
 * sponsor set is owner-rotatable so a key incident cannot strand the sale.
 * Per-user purchase limits are deliberately an off-chain (backend) policy.
 *
 * ALGORAND MIGRATION: tokens already sold on the Algorand presale are
 * seeded at deploy time as `initialSold`, which (a) starts the curve at
 * the right price and (b) fills a `migratedPool` the owner assigns to
 * specific BSC addresses via `creditMigrated` as each user's Algorand→BSC
 * address link materializes (it is only created when the user opens the
 * app, which can be arbitrarily late — hence per-address admin credits
 * instead of a one-shot snapshot). Credits draw DOWN the pool, so the
 * owner can never conjure allocations beyond what the curve has already
 * accounted (and priced) — paid buyers' economics and the claim backing
 * are unaffected by migration mistakes. `uncreditMigrated` reverses a
 * mis-assigned, still-unclaimed credit; `expandMigratedPool` covers
 * Algorand sales that happen after this vault deploys.
 *
 * CLAIMS: allocations accrue in `purchased`; once the owner wires the
 * CONFIO BEP-20 (deployable after the token migration) and unlocks claims,
 * `claim()` is permissionless for each buyer — no sponsor gate on the way
 * out. CONFIO already promised to buyers — including the still-unassigned
 * migratedPool — can never be swept by the owner.
 *
 * Deliberately NOT upgradeable: a presale is finite and its one promise is
 * that the rules cannot move. Owner powers are limited to: sponsor
 * rotation, pausing new buys, migration credits (pool-bounded), wiring the
 * CONFIO token (once), unlocking claims, and withdrawing proceeds/excess.
 */

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";

contract ConfioPresaleVault is Ownable2Step, Pausable, ReentrancyGuardTransient {
    using SafeERC20 for IERC20;

    uint256 private constant ONE_CONFIO = 1e18;
    uint256 private constant MAX_SEGMENTS = 8;

    /// Token the vault charges (e.g. cUSD on BSC once bridged, or USDT).
    IERC20 public immutable PAYMENT_TOKEN;

    /// Curve: cumulative-sold breakpoints (strictly increasing; the last
    /// one IS the total supply on sale) and the price at each node.
    /// prices.length == soldBreakpoints.length + 1: prices[i] is the price
    /// at the start of segment i, prices[last] the price at sell-out.
    /// Written once in the constructor; no setter exists.
    uint256[] public soldBreakpoints;
    uint256[] public prices;
    uint256 public immutable TOKENS_FOR_SALE;

    /// CONFIO BEP-20; zero until the migrated token exists. Settable once.
    IERC20 public confioToken;
    /// Master switch for claim(); flips only after confioToken is wired.
    bool public claimsUnlocked;

    /// Cumulative CONFIO sold (1e18) — the curve's independent variable.
    /// Includes the Algorand-migrated seed and pool expansions.
    uint256 public totalSold;
    /// Cumulative CONFIO already claimed (1e18).
    uint256 public totalClaimed;
    /// Cumulative payment pulled by buys on THIS chain (excludes the
    /// Algorand raise; display layers add that offset off-chain).
    uint256 public totalRaised;
    /// Algorand-sold CONFIO not yet assigned to a BSC address.
    uint256 public migratedPool;

    mapping(address => uint256) public purchased;
    mapping(address => uint256) public claimed;
    /// Portion of `purchased` that came from migration credits (bounds
    /// uncreditMigrated so paid purchases can never be revoked).
    mapping(address => uint256) public migratedCredited;
    mapping(address => bool) public isSponsor;

    event SponsorSet(address indexed sponsor, bool allowed);
    event Purchased(address indexed buyer, uint256 confioAmount, uint256 paymentCost, uint256 newTotalSold);
    event MigratedCredited(address indexed buyer, uint256 confioAmount);
    event MigratedUncredited(address indexed buyer, uint256 confioAmount);
    event MigratedPoolExpanded(uint256 confioAmount, uint256 newTotalSold);
    event Claimed(address indexed buyer, uint256 confioAmount);
    event ConfioTokenSet(address indexed token);
    event ClaimsUnlockedSet(bool unlocked);
    event PaymentSwept(address indexed to, uint256 amount);
    event ExcessConfioSwept(address indexed to, uint256 amount);
    event TokenRescued(address indexed token, address indexed to, uint256 amount);

    error NotSponsoredTransaction();
    error ZeroAmount();
    error ZeroAddress();
    error ExceedsTokensForSale();
    error CostExceedsMaxPayment(uint256 cost, uint256 maxPayment);
    error ConfioTokenAlreadySet();
    error ConfioTokenNotSet();
    error ClaimsLocked();
    error NothingToClaim();
    error BadCurveParams();
    error LengthMismatch();
    error ExceedsMigratedPool(uint256 requested, uint256 pool);
    error ExceedsUnclaimedCredit(uint256 requested, uint256 available);
    error ExceedsExcessConfio(uint256 requested, uint256 excess);
    error UseSweepExcessConfio();
    error ClaimsAlreadyUnlocked();
    error InsufficientBacking(uint256 held, uint256 owed);

    constructor(
        address owner_,
        IERC20 paymentToken_,
        uint256[] memory soldBreakpoints_,
        uint256[] memory prices_,
        uint256 initialSold_,
        address sponsor_
    ) Ownable(owner_) {
        if (address(paymentToken_) == address(0) || sponsor_ == address(0)) revert ZeroAddress();
        uint256 n = soldBreakpoints_.length;
        if (n == 0 || n > MAX_SEGMENTS || prices_.length != n + 1) revert BadCurveParams();
        // Strictly increasing breakpoints AND prices (every quote solves a
        // quadratic with the segment slope in a denominator), price > 0,
        // and magnitude bounds that keep every intermediate product below
        // clear of uint256 overflow.
        if (prices_[0] == 0 || prices_[n] > type(uint96).max) revert BadCurveParams();
        for (uint256 i; i < n; ++i) {
            if (prices_[i + 1] <= prices_[i]) revert BadCurveParams();
            if (soldBreakpoints_[i] <= (i == 0 ? 0 : soldBreakpoints_[i - 1])) revert BadCurveParams();
        }
        if (soldBreakpoints_[n - 1] > type(uint128).max) revert BadCurveParams();
        if (initialSold_ > soldBreakpoints_[n - 1]) revert ExceedsTokensForSale();

        PAYMENT_TOKEN = paymentToken_;
        soldBreakpoints = soldBreakpoints_;
        prices = prices_;
        TOKENS_FOR_SALE = soldBreakpoints_[n - 1];
        totalSold = initialSold_;
        migratedPool = initialSold_;
        isSponsor[sponsor_] = true;
        emit SponsorSet(sponsor_, true);
    }

    // ---------------------------------------------------------------------
    // Curve views
    // ---------------------------------------------------------------------

    function segmentCount() external view returns (uint256) {
        return soldBreakpoints.length;
    }

    /// Spot price (payment base units per whole CONFIO) at the current sold mark.
    function currentPrice() public view returns (uint256) {
        return priceAt(totalSold);
    }

    function priceAt(uint256 sold) public view returns (uint256) {
        uint256 n = soldBreakpoints.length;
        if (sold >= TOKENS_FOR_SALE) return prices[n];
        (uint256 i, uint256 s0) = _segmentOf(sold);
        uint256 len = soldBreakpoints[i] - s0;
        return prices[i] + Math.mulDiv(prices[i + 1] - prices[i], sold - s0, len);
    }

    function remainingTokens() public view returns (uint256) {
        return TOKENS_FOR_SALE - totalSold;
    }

    /// Exact payment charged for buying `confioAmount` at the current mark
    /// (integral under the curve, rounded up per segment in the vault's favor).
    function quoteCost(uint256 confioAmount) public view returns (uint256) {
        return _costFor(totalSold, confioAmount);
    }

    /**
     * Inverse quote for UIs: how much CONFIO `paymentAmount` buys right now.
     * Every rounding pushes the answer DOWN (never over-promises;
     * quoteCost(quoteTokens(c)) ≤ c always). Clamped to remaining supply.
     */
    function quoteTokens(uint256 paymentAmount) external view returns (uint256 q) {
        uint256 sold = totalSold;
        uint256 budget = paymentAmount;
        uint256 n = soldBreakpoints.length;
        while (budget > 0 && sold < TOKENS_FOR_SALE) {
            (uint256 i, uint256 s0) = _segmentOf(sold);
            uint256 len = soldBreakpoints[i] - s0;
            uint256 x = sold - s0;
            uint256 segRestCost = _segCost(prices[i], prices[i + 1], len, x, len - x);
            if (budget >= segRestCost) {
                q += len - x;
                sold = soldBreakpoints[i];
                budget -= segRestCost;
                if (i == n - 1) break;
            } else {
                q += _segQuote(prices[i], prices[i + 1], len, x, budget);
                break;
            }
        }
    }

    /// Segment index containing `sold` (sold < TOKENS_FOR_SALE) and its start.
    function _segmentOf(uint256 sold) internal view returns (uint256 i, uint256 s0) {
        uint256 n = soldBreakpoints.length;
        for (i = 0; i < n; ++i) {
            if (sold < soldBreakpoints[i]) {
                return (i, i == 0 ? 0 : soldBreakpoints[i - 1]);
            }
        }
        revert ExceedsTokensForSale();
    }

    /// Integral under the whole curve from `sold` over `confioAmount`,
    /// walking segments; each segment's closed form is ceil-rounded.
    function _costFor(uint256 sold, uint256 confioAmount) internal view returns (uint256 cost) {
        uint256 left = confioAmount;
        while (left > 0) {
            (uint256 i, uint256 s0) = _segmentOf(sold);
            uint256 len = soldBreakpoints[i] - s0;
            uint256 x = sold - s0;
            uint256 q = Math.min(left, len - x);
            cost += _segCost(prices[i], prices[i + 1], len, x, q);
            sold += q;
            left -= q;
        }
    }

    /// Exact integral within one segment (prices pA→pB over length L),
    /// buying q starting at offset x: q·(2·L·pA + (pB−pA)·(2x+q)) / (2·L·1e18), ceil.
    function _segCost(uint256 pA, uint256 pB, uint256 L, uint256 x, uint256 q)
        internal
        pure
        returns (uint256)
    {
        uint256 inner = 2 * L * pA + (pB - pA) * (2 * x + q);
        return Math.mulDiv(q, inner, 2 * L * ONE_CONFIO, Math.Rounding.Ceil);
    }

    /**
     * Inverse within one segment: largest q with segCost(x, q) ≤ c.
     * Solves (k/2L)·q² + p(x)·q = c·1e18 with k = pB−pA. The spot price is
     * CEIL-rounded: sqrt(p²+X)−p is decreasing in p, so overstating p —
     * like the floor on sqrt and the final mulDiv — can only shrink q,
     * the safe direction for a quote.
     */
    function _segQuote(uint256 pA, uint256 pB, uint256 L, uint256 x, uint256 c)
        internal
        pure
        returns (uint256)
    {
        uint256 k = pB - pA;
        uint256 p = pA + Math.mulDiv(k, x, L, Math.Rounding.Ceil);
        uint256 disc = p * p + Math.mulDiv(2 * k * ONE_CONFIO, c, L);
        uint256 root = Math.sqrt(disc); // floor sqrt
        if (root <= p) return 0;
        uint256 q = Math.mulDiv(L, root - p, k);
        return Math.min(q, L - x);
    }

    // ---------------------------------------------------------------------
    // Buy (sponsor-gated) & claim (permissionless once unlocked)
    // ---------------------------------------------------------------------

    /**
     * Record a purchase of `confioAmount` (1e18) for msg.sender, pulling the
     * exact curve cost in PAYMENT_TOKEN (must be approved; the 7702 batch
     * pairs the approval with this call). `maxPayment` is the buyer's
     * signed slippage cap: concurrent buys move the curve, and the tx
     * reverts rather than charge more than the buyer agreed to.
     */
    function buy(uint256 confioAmount, uint256 maxPayment)
        external
        whenNotPaused
        nonReentrant
        returns (uint256 cost)
    {
        if (!isSponsor[msg.sender] && !isSponsor[tx.origin]) revert NotSponsoredTransaction();
        if (confioAmount == 0) revert ZeroAmount();
        uint256 sold = totalSold;
        if (confioAmount > TOKENS_FOR_SALE - sold) revert ExceedsTokensForSale();

        cost = _costFor(sold, confioAmount);
        if (cost > maxPayment) revert CostExceedsMaxPayment(cost, maxPayment);

        totalSold = sold + confioAmount;
        totalRaised += cost;
        purchased[msg.sender] += confioAmount;
        _assertBacked();
        emit Purchased(msg.sender, confioAmount, cost, sold + confioAmount);

        PAYMENT_TOKEN.safeTransferFrom(msg.sender, address(this), cost);
    }

    /// Once claims are open, no new obligation may exceed the CONFIO
    /// actually held (audit 2026-07-31, [P1]): otherwise a late buyer could
    /// claim immediately and drain collateral reserved for earlier buyers,
    /// making claim ORDER decide who gets frozen out. Before unlock this is
    /// a no-op — the vault is allowed to sell ahead of funding.
    function _assertBacked() private view {
        if (!claimsUnlocked) return;
        uint256 owed = totalSold - totalClaimed;
        uint256 held = confioToken.balanceOf(address(this));
        if (held < owed) revert InsufficientBacking(held, owed);
    }

    /// Send msg.sender's entire unclaimed allocation. No sponsor gate:
    /// once claims open, exit is user-sovereign.
    function claim() external nonReentrant returns (uint256 amount) {
        if (!claimsUnlocked) revert ClaimsLocked();
        IERC20 token = confioToken;
        if (address(token) == address(0)) revert ConfioTokenNotSet();
        amount = purchased[msg.sender] - claimed[msg.sender];
        if (amount == 0) revert NothingToClaim();

        claimed[msg.sender] += amount;
        totalClaimed += amount;
        // A claim consumes the migration credit for good (audit
        // 2026-07-31, [P1]): leaving it standing let `uncreditMigrated`
        // later revoke an amount the buyer had actually PAID for, since
        // that function only compares against the unclaimed balance.
        // Safe to zero outright because a claim always takes everything.
        migratedCredited[msg.sender] = 0;
        emit Claimed(msg.sender, amount);

        token.safeTransfer(msg.sender, amount);
    }

    function claimableOf(address account) external view returns (uint256) {
        return purchased[account] - claimed[account];
    }

    // ---------------------------------------------------------------------
    // Algorand-migration credits (owner, bounded by migratedPool)
    // ---------------------------------------------------------------------

    /**
     * Assign already-priced Algorand purchases to their BSC addresses as
     * the address links materialize. Draws down migratedPool, so total
     * credits can never exceed what the curve seed/expansions accounted for.
     */
    function creditMigrated(address[] calldata buyers, uint256[] calldata amounts)
        external
        onlyOwner
    {
        if (buyers.length != amounts.length) revert LengthMismatch();
        uint256 pool = migratedPool;
        for (uint256 i; i < buyers.length; ++i) {
            address buyer = buyers[i];
            uint256 amount = amounts[i];
            if (buyer == address(0)) revert ZeroAddress();
            if (amount == 0) revert ZeroAmount();
            if (amount > pool) revert ExceedsMigratedPool(amount, pool);
            pool -= amount;
            purchased[buyer] += amount;
            migratedCredited[buyer] += amount;
            emit MigratedCredited(buyer, amount);
        }
        migratedPool = pool;
    }

    /// Reverse a mis-assigned credit (manual mapping ⇒ mistakes happen).
    /// Only migration credit — never paid purchases — and only while the
    /// buyer still has that much unclaimed. Returns the amount to the pool.
    function uncreditMigrated(address buyer, uint256 amount) external onlyOwner {
        if (amount == 0) revert ZeroAmount();
        uint256 unclaimed = purchased[buyer] - claimed[buyer];
        uint256 available = Math.min(migratedCredited[buyer], unclaimed);
        if (amount > available) revert ExceedsUnclaimedCredit(amount, available);
        migratedCredited[buyer] -= amount;
        purchased[buyer] -= amount;
        migratedPool += amount;
        emit MigratedUncredited(buyer, amount);
    }

    /// Account for Algorand sales that happened AFTER this vault deployed:
    /// moves the curve forward and reserves the allocation for credits.
    function expandMigratedPool(uint256 amount) external onlyOwner {
        if (amount == 0) revert ZeroAmount();
        uint256 sold = totalSold;
        if (amount > TOKENS_FOR_SALE - sold) revert ExceedsTokensForSale();
        totalSold = sold + amount;
        migratedPool += amount;
        _assertBacked();
        emit MigratedPoolExpanded(amount, sold + amount);
    }

    // ---------------------------------------------------------------------
    // Owner (Safe) operations
    // ---------------------------------------------------------------------

    function setSponsor(address sponsor, bool allowed) external onlyOwner {
        if (sponsor == address(0)) revert ZeroAddress();
        isSponsor[sponsor] = allowed;
        emit SponsorSet(sponsor, allowed);
    }

    /// One-shot wiring of the migrated CONFIO BEP-20.
    function setConfioToken(IERC20 token) external onlyOwner {
        if (address(token) == address(0)) revert ZeroAddress();
        if (address(confioToken) != address(0)) revert ConfioTokenAlreadySet();
        confioToken = token;
        emit ConfioTokenSet(address(token));
    }

    /// ONE-WAY (audit 2026-07-31, [P1]): the previous boolean setter let
    /// the owner re-lock claims after opening them, i.e. freeze every
    /// unclaimed buyer at will — exactly the power `pause()` was designed
    /// NOT to have over claims. Unlocking also requires that every
    /// outstanding allocation is already funded, so "claims are open"
    /// cannot mean "open for whoever arrives first".
    function unlockClaims() external onlyOwner {
        if (claimsUnlocked) revert ClaimsAlreadyUnlocked();
        IERC20 token = confioToken;
        if (address(token) == address(0)) revert ConfioTokenNotSet();
        uint256 owed = totalSold - totalClaimed;
        uint256 held = token.balanceOf(address(this));
        if (held < owed) revert InsufficientBacking(held, owed);
        claimsUnlocked = true;
        emit ClaimsUnlockedSet(true);
    }

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    /// Withdraw sale proceeds to the treasury.
    function sweepPayment(address to, uint256 amount) external onlyOwner {
        if (to == address(0)) revert ZeroAddress();
        emit PaymentSwept(to, amount);
        PAYMENT_TOKEN.safeTransfer(to, amount);
    }

    /// Withdraw CONFIO beyond what buyers are still owed (unsold inventory,
    /// over-funding). Outstanding allocations — including the not-yet-
    /// assigned migratedPool, which lives inside totalSold — are untouchable.
    function sweepExcessConfio(address to, uint256 amount) external onlyOwner {
        if (to == address(0)) revert ZeroAddress();
        IERC20 token = confioToken;
        if (address(token) == address(0)) revert ConfioTokenNotSet();
        uint256 outstanding = totalSold - totalClaimed;
        uint256 balance = token.balanceOf(address(this));
        uint256 excess = balance > outstanding ? balance - outstanding : 0;
        if (amount > excess) revert ExceedsExcessConfio(amount, excess);
        emit ExcessConfioSwept(to, amount);
        token.safeTransfer(to, amount);
    }

    /// Rescue stray tokens. CONFIO must go through sweepExcessConfio so the
    /// outstanding-claims guard cannot be bypassed.
    function rescueToken(IERC20 token, address to, uint256 amount) external onlyOwner {
        if (to == address(0)) revert ZeroAddress();
        if (address(token) == address(confioToken)) revert UseSweepExcessConfio();
        emit TokenRescued(address(token), to, amount);
        token.safeTransfer(to, amount);
    }
}
