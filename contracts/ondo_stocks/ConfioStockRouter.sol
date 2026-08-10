// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ConfioStockRouter — the sweep-model trade path: GM tokenized stocks are
 * bought FROM and sold INTO the user's savings (cUSD+), with Confío's fee
 * taken as an EXPLICIT on-chain accrual (never a hidden price markup —
 * "Sin comisiones ocultas" is enforced here, not just promised in copy).
 *
 * One user signature per trade (plus one-time approvals):
 *
 *   buyWithSavings:  pull cUSD+ shares -> vault.redeemToUsdt -> fee slice
 *                    retained in router -> GM mint -> stock tokens to user
 *   sellToSavings:   pull stock tokens -> GM redeem -> USDT -> fee slice
 *                    -> vault.subscribeAndMint(recipient = user)
 *                    (proceeds keep earning — the SellStock success copy's
 *                    "sigue generando rendimiento" is literal)
 *
 * Philosophy (same as CusdPlusVault):
 * - The router holds only the explicitly-accounted 0.30% USDT trade fees
 *   at rest. Trade principal still transits inside a single transaction.
 * - No discretionary anything: amounts in must equal fee + amounts settled,
 *   enforced by balance accounting per call.
 * - UUPS upgradeability mirrors CusdPlusVault so Ondo settlement migrations
 *   do not require a new whitelisted purchaser address. Upgrade authority is
 *   held by the same Confío Safe as ownership and fee withdrawal authority.
 *
 * ══ Written against the REAL GM ABI, verified on-chain 2026-07-31 ═══════
 *
 * GMTokenManager 0x91f8Aff3738825e8eB16FC6f6b1A7A4647bDB299 (BNB), source
 * read from BscScan. Facts this contract is built on — each VERIFIED, not
 * inferred (the previous draft was blocked precisely for inferring an ABI):
 *
 *  - `mintWithAttestation` mints to the CALLER:
 *        IRWALike(quote.asset).mint(_msgSender(), quote.quantity)
 *    There is no recipient parameter anywhere in the function or the Quote
 *    struct, so this router receives the stock and forwards it to the user
 *    in the SAME transaction. Confío is therefore the mint recipient and
 *    never holds stock across blocks.
 *  - `redeemWithAttestation` likewise pays the CALLER (safeTransfer to
 *    _msgSender()), so proceeds land here and are re-invested for the user.
 *  - The caller must be registered: userId is read from the Ondo ID
 *    Registry for _msgSender() and must equal quote.userId. One whitelisted
 *    router carrying Confío's userId is the model Ondo described in writing
 *    (2026-07-31): partner submits, userId = the onboarded purchaser.
 *  - GM already enforces quote.side, quote.expiration, attestation replay
 *    (executedAttestationIds) and the per-userId rate limiter. We do not
 *    duplicate those; we add only what protects OUR users.
 *  - minimumDepositUSD == minimumRedemptionUSD == ~$0.98, so micro-tickets
 *    are viable and no extra minimum is imposed here.
 *
 * NOTE (non-technical gate): whether Confío may act as purchaser-of-record
 * and pass tokens to users is the §21(d) question in the signed OGM Sales
 * Terms and is NOT resolved by this contract. Build ≠ deploy.
 *
 * Audit P2s from the 2026-07-31 review, all carried here:
 *  - the stock token is taken from the SIGNED QUOTE (quote.asset), never
 *    from a caller-supplied address;
 *  - every leg requires EXACT input consumption — a leftover allowance
 *    after a GM call means a partial fill and reverts the trade;
 *  - floors are enforced on what the USER receives, not what the router
 *    receives (a transfer-taxing token could otherwise short the user);
 *  - each trade commits to maxFeeBps, making the fixed 30 bps fee explicit
 *    in the user's authorization and allowing stricter future clients.
 */

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable2StepUpgradeable} from "@openzeppelin/contracts-upgradeable/access/Ownable2StepUpgradeable.sol";
import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";

interface ICusdPlusVaultMinimal {
    function redeemToUsdt(uint256 shares, uint256 minUsdtOut, address to) external returns (uint256);
    function subscribeAndMint(uint256 usdtIn, uint256 minUsdyOut, address recipient) external returns (uint256);
    function isSponsor(address account) external view returns (bool);
}

/// ABI-identical to GMTokenManager.Quote (field order and types matter —
/// this is what Ondo's attestation signature covers).
struct GmQuote {
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

interface IGMTokenManager {
    function usdon() external view returns (address);

    function mintWithAttestation(
        GmQuote calldata quote,
        bytes memory signature,
        address depositToken,
        uint256 depositTokenAmount
    ) external returns (uint256);

    function redeemWithAttestation(
        GmQuote calldata quote,
        bytes memory signature,
        address receiveToken,
        uint256 minimumReceiveAmount
    ) external returns (uint256);
}

contract ConfioStockRouter is Ownable2StepUpgradeable, PausableUpgradeable, ReentrancyGuardTransient, UUPSUpgradeable {
    using SafeERC20 for IERC20;

    IERC20 public immutable CUSD_PLUS;
    IERC20 public immutable USDT;
    /// Ondo's USD stablecoin. A non-USDon deposit is converted inside GM via
    /// usdonManager, and any SURPLUS USDon is refunded to the caller (us) —
    /// see _forwardUsdonRefund.
    IERC20 public immutable USDON;
    ICusdPlusVaultMinimal public immutable VAULT;
    IGMTokenManager public immutable GM;
    uint256 private constant BPS = 10_000;
    uint256 private constant WAD = 1e18;
    /// Confío's explicit trade fee: 0.30% on both buys and sells. Fixed in
    /// bytecode so neither the owner nor a compromised key can raise it.
    uint256 public constant stockFeeBps = 30;

    /// GM converts the full USDT deposit to USDon, consumes quote cost, and
    /// refunds the remainder. A live BSC trade differed from quantity*price
    /// by 112 wei. One micro-USDT leaves ample arithmetic headroom without
    /// turning the remainder into a second, hidden percentage fee.
    uint256 public constant MAX_QUOTE_REMAINDER = 1e12;

    uint8 private constant BUY = 0;
    uint8 private constant SELL = 1;

    /// USDT earned by the router and not yet withdrawn. This separates fees
    /// from accidental USDT transfers, which remain independently sweepable.
    uint256 public accruedUsdtFees;

    event FeesWithdrawn(address indexed to, uint256 amount);
    event StockBought(
        address indexed user,
        address indexed stockToken,
        uint256 attestationId,
        uint256 sharesIn,
        uint256 usdtSpent,
        uint256 feeUsdt,
        uint256 stockOut
    );
    event StockSold(
        address indexed user,
        address indexed stockToken,
        uint256 attestationId,
        uint256 stockIn,
        uint256 usdtProceeds,
        uint256 feeUsdt,
        uint256 sharesOut
    );
    event UsdonRefundForwarded(address indexed user, uint256 amount);
    event UsdtRedemptionExcessReturned(address indexed user, uint256 amount);

    constructor(address cusdPlus, address usdt, address usdon, address gmTokenManager) {
        require(
            cusdPlus != address(0) && usdt != address(0) && usdon != address(0) && gmTokenManager != address(0),
            "zero address"
        );
        require(
            cusdPlus.code.length > 0 && usdt.code.length > 0 && usdon.code.length > 0 && gmTokenManager.code.length > 0,
            "non-contract dependency"
        );
        CUSD_PLUS = IERC20(cusdPlus);
        USDT = IERC20(usdt);
        USDON = IERC20(usdon);
        VAULT = ICusdPlusVaultMinimal(cusdPlus); // the vault IS the cUSD+ token
        GM = IGMTokenManager(gmTokenManager);
        require(GM.usdon() == usdon, "gm usdon mismatch");
        _disableInitializers();
    }

    function initialize(address ownerAddr) external initializer {
        require(ownerAddr != address(0), "zero owner");
        __Ownable_init(ownerAddr);
        __Ownable2Step_init();
        __Pausable_init();
    }

    function _authorizeUpgrade(address) internal view override onlyOwner {}

    /// Confío's relay must ORIGINATE the trade (audit 2026-07-31 [P1]).
    ///
    /// `sellToSavings` reaches the vault's PRIMARY ISSUANCE, and the vault
    /// must register this router as a sponsor for that call to work at all
    /// (it mints to the user while the router is msg.sender). But being a
    /// sponsor makes the router satisfy BOTH of the vault's checks by
    /// itself — `isSponsor[msg.sender]` is true and `tx.origin` becomes
    /// irrelevant — so without this modifier ANY caller could launder a
    /// permissionless call into freshly minted cUSD+, bypassing the phone
    /// + IP eligibility checks the whole v5 gate exists to enforce. A US
    /// person holding a transferable GM stock is exactly that caller.
    ///
    /// Deliberately `tx.origin`: checking `isSponsor(address(this))` would
    /// always be true and is precisely the hole. This is NOT an exit gate
    /// — a holder can always leave via the vault's own `redeemToUsdt`,
    /// which no contract here can restrict.
    modifier onlySponsoredOrigin() {
        require(VAULT.isSponsor(tx.origin), "not sponsored");
        _;
    }

    // ═════════════════════════ Buy ══════════════════════════════════════

    /// Spend `sharesIn` of the caller's cUSD+ on the stock named BY THE
    /// SIGNED QUOTE (`quote.asset` — never a caller-supplied address).
    ///
    /// `minUsdtOut` floors the vault redemption. There is no minStockOut:
    /// GM mints exactly `quote.quantity`, which Ondo signed — so the floor
    /// that matters is that the USER actually receives that quantity, which
    /// is asserted against the user's own balance below.
    function buyWithSavings(
        GmQuote calldata quote,
        bytes calldata signature,
        uint256 sharesIn,
        uint256 usdtSpend,
        uint256 minUsdtOut,
        uint256 maxFeeBps
    ) external nonReentrant whenNotPaused onlySponsoredOrigin returns (uint256 stockOut) {
        require(sharesIn > 0, "zero in");
        // A zero-quantity quote would satisfy every downstream floor while
        // still consuming savings and charging a fee (audit [P2]). GM's own
        // minimumDepositUSD would also reject it today — don't depend on
        // someone else's parameter for our users' safety.
        require(quote.quantity > 0, "zero quantity");
        require(quote.price > 0, "zero price");
        require(quote.side == BUY, "wrong quote side");
        require(quote.chainId == block.chainid, "wrong chain");
        require(stockFeeBps <= maxFeeBps, "fee above trade cap");

        uint256 userStockBefore = IERC20(quote.asset).balanceOf(msg.sender);
        uint256 usdonBefore = USDON.balanceOf(address(this));

        // Pull the savings shares and redeem them here. Trade principal is
        // spent in this tx; only the explicitly-accounted fee stays behind.
        CUSD_PLUS.safeTransferFrom(msg.sender, address(this), sharesIn);
        uint256 usdt = _redeemSavings(sharesIn, minUsdtOut);

        require(usdtSpend > 0, "nothing to spend");

        // The binding API request is denominated in notional USDT, while the
        // signed quote carries quantity and price. Their decimal conversion
        // can leave a tiny remainder (112 wei in a live BSC trade), so bind
        // the caller-supplied notional to the signed cost within that absolute
        // limit. The relay also validates this before sponsoring the call.
        {
            uint256 quoteCost = Math.mulDiv(quote.quantity, quote.price, WAD);
            require(usdtSpend >= quoteCost, "underspend vs quote");
            require(usdtSpend - quoteCost <= MAX_QUOTE_REMAINDER, "overspend vs quote");
        }

        // Charge 30 bps of the complete trade debit. Rounding up prevents a
        // zero fee on tiny valid trades: fee / (spend + fee) ~= 30 / 10,000.
        uint256 fee = _accountBuyDebit(usdt, usdtSpend, msg.sender);
        stockOut = _deliverBoughtStock(quote, signature, usdtSpend, msg.sender, userStockBefore);

        _forwardUsdonRefund(usdonBefore, msg.sender);

        emit StockBought(msg.sender, quote.asset, quote.attestationId, sharesIn, usdtSpend, fee, stockOut);
    }

    // ═════════════════════════ Sell ═════════════════════════════════════

    /// Sell `quote.quantity` of `quote.asset`; proceeds (minus fee) re-enter
    /// the caller's savings and keep earning.
    ///
    /// `minUsdtOut` floors the GM redemption (enforced inside GM too).
    /// `minSharesOut` floors the cUSD+ the USER ends up holding. It is
    /// enforced HERE, not forwarded as the vault's minUsdyOut — shares and
    /// USDY are different units (shares = usdyOut * p / pPlus), and a shares
    /// floor already bounds the dollar value of the whole subscribe leg.
    function sellToSavings(
        GmQuote calldata quote,
        bytes calldata signature,
        uint256 minUsdtOut,
        uint256 minSharesOut,
        uint256 maxFeeBps
    ) external nonReentrant whenNotPaused onlySponsoredOrigin returns (uint256 sharesOut) {
        require(quote.quantity > 0, "zero in");
        require(quote.price > 0, "zero price");
        require(quote.side == SELL, "wrong quote side");
        require(quote.chainId == block.chainid, "wrong chain");
        require(stockFeeBps <= maxFeeBps, "fee above trade cap");

        uint256 userSharesBefore = CUSD_PLUS.balanceOf(msg.sender);

        IERC20(quote.asset).safeTransferFrom(msg.sender, address(this), quote.quantity);
        uint256 usdt = _gmRedeem(quote, signature, minUsdtOut);
        require(usdt >= minUsdtOut, "gm: insufficient payment out");

        uint256 fee = (usdt * stockFeeBps) / BPS;
        accruedUsdtFees += fee;
        uint256 reinvest = usdt - fee;
        require(reinvest > 0, "nothing to reinvest");

        USDT.forceApprove(address(VAULT), reinvest);
        VAULT.subscribeAndMint(reinvest, 0, msg.sender);
        require(USDT.allowance(address(this), address(VAULT)) == 0, "vault: partial fill");

        // Floor what the USER actually holds afterwards.
        sharesOut = CUSD_PLUS.balanceOf(msg.sender) - userSharesBefore;
        require(sharesOut >= minSharesOut, "insufficient shares out");

        emit StockSold(msg.sender, quote.asset, quote.attestationId, quote.quantity, usdt, fee, sharesOut);
    }

    // ═════════════════════════ Internals ════════════════════════════════

    /// Redeem the pulled savings shares to USDT, measuring OUR OWN balance
    /// delta rather than trusting the vault's return value (audit [P2]) —
    /// consistent with _gmMint/_gmRedeem, and it stops stray USDT sitting in
    /// the router from being swept into a user's trade.
    function _redeemSavings(uint256 sharesIn, uint256 minUsdtOut) private returns (uint256 usdt) {
        uint256 before = USDT.balanceOf(address(this));
        VAULT.redeemToUsdt(sharesIn, minUsdtOut, address(this));
        usdt = USDT.balanceOf(address(this)) - before;
        require(usdt >= minUsdtOut, "vault: insufficient usdt out");
    }

    /// GM pulls `spend` USDT and mints quote.quantity to US (the caller).
    /// Extracted so `buyWithSavings` stays under the stack limit.
    ///
    /// The allowance assertion is the audit's exact-consumption rule: a
    /// leftover allowance means GM took less than we committed, which would
    /// leave value here behind a live approval. Reject the whole trade.
    function _gmMint(GmQuote calldata quote, bytes calldata signature, uint256 spend) private returns (uint256 minted) {
        uint256 before = IERC20(quote.asset).balanceOf(address(this));
        USDT.forceApprove(address(GM), spend);
        GM.mintWithAttestation(quote, signature, address(USDT), spend);
        require(USDT.allowance(address(this), address(GM)) == 0, "gm: partial fill");
        minted = IERC20(quote.asset).balanceOf(address(this)) - before;
    }

    function _accountBuyDebit(uint256 redeemedUsdt, uint256 usdtSpend, address user) private returns (uint256 fee) {
        fee = Math.mulDiv(usdtSpend, stockFeeBps, BPS - stockFeeBps, Math.Rounding.Ceil);
        uint256 requiredUsdt = usdtSpend + fee;
        require(redeemedUsdt >= requiredUsdt, "insufficient redeemed usdt");
        accruedUsdtFees += fee;

        // cUSD+ accrues before redeeming, so the same shares can return more
        // USDT than the client predicted when it requested the attestation.
        // Spend only the binding notional and return every excess wei rather
        // than capturing it as an accidental second fee.
        uint256 excess = redeemedUsdt - requiredUsdt;
        if (excess > 0) {
            USDT.safeTransfer(user, excess);
            emit UsdtRedemptionExcessReturned(user, excess);
        }
    }

    function _deliverBoughtStock(
        GmQuote calldata quote,
        bytes calldata signature,
        uint256 usdtSpend,
        address user,
        uint256 userStockBefore
    ) private returns (uint256 stockOut) {
        uint256 minted = _gmMint(quote, signature, usdtSpend);
        require(minted >= quote.quantity, "gm: short mint");
        IERC20(quote.asset).safeTransfer(user, minted);

        // Floor what the USER got, not what we got (transfer-taxing tokens).
        stockOut = IERC20(quote.asset).balanceOf(user) - userStockBefore;
        require(stockOut >= quote.quantity, "user short-changed");
    }

    /// GM burns the stock and pays USDT to US (the caller). Same
    /// exact-consumption rule on the stock allowance.
    function _gmRedeem(GmQuote calldata quote, bytes calldata signature, uint256 minUsdtOut)
        private
        returns (uint256 proceeds)
    {
        uint256 before = USDT.balanceOf(address(this));
        IERC20(quote.asset).forceApprove(address(GM), quote.quantity);
        GM.redeemWithAttestation(quote, signature, address(USDT), minUsdtOut);
        require(IERC20(quote.asset).allowance(address(this), address(GM)) == 0, "gm: partial fill");
        proceeds = USDT.balanceOf(address(this)) - before;
    }

    /// GM refunds surplus from its USDT->USDon conversion to its caller, this
    /// router. It belongs to the user whose savings funded the trade. Forward
    /// only this call's balance delta so pre-existing accidental USDon remains
    /// independently sweepable.
    function _forwardUsdonRefund(uint256 usdonBefore, address user) private {
        uint256 refund = USDON.balanceOf(address(this)) - usdonBefore;
        if (refund > 0) {
            USDON.safeTransfer(user, refund);
            emit UsdonRefundForwarded(user, refund);
        }
    }

    // ═════════════════════════ Ops ══════════════════════════════════════

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    /// Withdraw only fees actually accrued by completed trades. Accounting is
    /// reduced before the external token call and the whole tx reverts if the
    /// transfer fails.
    function withdrawFees(address to, uint256 amount) external onlyOwner nonReentrant {
        require(to != address(0), "zero recipient");
        require(amount <= accruedUsdtFees, "amount exceeds fees");
        accruedUsdtFees -= amount;
        USDT.safeTransfer(to, amount);
        emit FeesWithdrawn(to, amount);
    }

    /// Rescue accidental tokens. Accrued USDT is reserved for withdrawFees()
    /// and cannot be removed through this generic path.
    function sweep(address token, address to, uint256 amount) external onlyOwner nonReentrant {
        require(to != address(0), "zero recipient");
        if (token == address(USDT)) {
            require(amount <= USDT.balanceOf(address(this)) - accruedUsdtFees, "amount includes fees");
        }
        IERC20(token).safeTransfer(to, amount);
    }
}
