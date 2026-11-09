// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ConfioStockRouter — the sweep-model trade path: GM tokenized stocks are
 * bought FROM and sold INTO the user's savings (cUSD+). Since v2 (2026-10)
 * the router charges NO fee of its own, and since v3 (2026-11) it has no
 * fee path at all (the transitional 0.30% legacy path is deleted): Confío's single 0.9% conversion fee
 * is taken by cUSD when the dollars leave (buy) or re-enter (sell) savings,
 * through the same public cUSD+ exit/entry every withdrawal and deposit
 * uses. There is no per-product rate and no hidden price markup.
 *
 * One user signature per trade (plus one-time approvals):
 *
 *   buyWithSavings:  pull cUSD+ shares -> vault.redeemToUsdt (cUSD exit
 *                    fee) -> GM mint -> stock tokens to user
 *   sellToSavings:   pull stock tokens -> GM redeem -> USDT
 *                    -> vault.subscribeAndMint(recipient = user) (cUSD
 *                    entry fee)
 *                    (proceeds keep earning — the SellStock success copy's
 *                    "sigue generando rendimiento" is literal)
 *   sellToUsdt:      pull stock tokens -> GM redeem -> raw USDT to user
 *                    (permissionless, user pays gas; never touches cUSD,
 *                    so no conversion fee)
 *
 * Philosophy (same as CusdPlusVault):
 * - The router holds nothing at rest. Trade principal transits inside a
 *   single transaction. (v1 and the v2 legacy path accrued a 0.30% fee
 *   here; it was withdrawn to the Safe before v3, and initializeV3 refuses
 *   to run unless that accrual is zero.)
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
 *  - each trade commits to maxFeeBps, which since v2 binds cUSD's live
 *    conversion fee (conversionFeeBps), so the fee charged can never exceed
 *    what the user signed.
 */

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable2StepUpgradeable} from "@openzeppelin/contracts-upgradeable/access/Ownable2StepUpgradeable.sol";
import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";

interface ICusdPlusVaultMinimal {
    /// Public, fee-bearing exit: cUSD+ -> USDT through cUSD's 0.9% perimeter.
    function redeemToUsdt(uint256 shares, uint256 minUsdtOut, address to) external returns (uint256);
    /// Sponsor-gated, fee-bearing entry: USDT -> cUSD+ through the same perimeter.
    function subscribeAndMint(uint256 usdtIn, uint256 minUsdyOut, address recipient) external returns (uint256);
    function isSponsor(address account) external view returns (bool);
    function CUSD() external view returns (address);
}

/// cUSD owns the single Confío conversion fee (feeBps, Safe-set, bounded).
interface ICusdFeePerimeter {
    function feeBps() external view returns (uint256);
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
    uint256 private constant WAD = 1e18;
    /// The router's OWN fee. Zero since v2 (2026-10): stock trades pay the
    /// same cUSD perimeter fee as every other exit/entry of Confío dollars
    /// (see conversionFeeBps), with no per-product exception. Kept as a
    /// public constant for ABI compatibility with existing readers. Fixed in
    /// bytecode so neither the owner nor a compromised key can raise it.
    uint256 public constant stockFeeBps = 0;

    /// Implementation generation, for on-chain verification of an upgrade.
    uint256 public constant VERSION = 3;

    /// GM converts the full USDT deposit to USDon, consumes quote cost, and
    /// refunds the remainder. A live BSC trade differed from quantity*price
    /// by 112 wei. One micro-USDT leaves ample arithmetic headroom without
    /// turning the remainder into a second, hidden percentage fee.
    uint256 public constant MAX_QUOTE_REMAINDER = 1e12;

    uint8 private constant BUY = 0;
    uint8 private constant SELL = 1;

    /// Storage slot 0, kept for the proxy's layout and for existing readers.
    /// It held the 0.30% fee accrued by v1 and the v2 legacy path; since v3
    /// nothing writes it, and initializeV3 requires it to be zero, so it
    /// reads 0 forever.
    uint256 public accruedUsdtFees;

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
    event StockSoldToUsdt(
        address indexed user,
        address indexed stockToken,
        uint256 attestationId,
        uint256 stockIn,
        uint256 usdtProceeds,
        uint256 feeUsdt,
        uint256 usdtOut
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

    /// v2 -> v3 upgrade hook (Safe: upgradeToAndCall(v3, initializeV3())).
    /// Refuses to install v3 while any legacy router fee is still accrued:
    /// v3 has no way to withdraw it apart from sweep, so it must be
    /// collected with v2's withdrawFees first.
    function initializeV3() external reinitializer(3) {
        require(accruedUsdtFees == 0, "withdraw legacy fees first");
    }

    function _authorizeUpgrade(address) internal view override onlyOwner {}

    /// Confío's relay must ORIGINATE any trade that mints or spends cUSD+.
    /// Raw-USDT redemption is deliberately excluded so sponsor availability
    /// can never block a holder from selling stock and leaving the system.
    ///
    /// Deliberately `tx.origin`: checking `isSponsor(address(this))` would
    /// always be true because the router needs that role for settlement.
    /// This modifier belongs on cUSD+ buys and sells. `sellToUsdt` is the
    /// separate permissionless exit.
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
        _requireFeeCap(maxFeeBps);

        uint256 userStockBefore = IERC20(quote.asset).balanceOf(msg.sender);
        uint256 usdonBefore = USDON.balanceOf(address(this));

        // Pull the savings shares and redeem them here through cUSD+'s public
        // exit, which pays cUSD's conversion fee like any other exit. Trade
        // principal is spent in this tx; nothing stays behind.
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

        // The conversion fee was already taken by the exit above; the router
        // charges nothing (the event's fee field stays for ABI readers: 0).
        _returnRedemptionExcess(usdt, usdtSpend, msg.sender);
        stockOut = _deliverBoughtStock(quote, signature, usdtSpend, msg.sender, userStockBefore);

        _forwardUsdonRefund(usdonBefore, msg.sender);

        emit StockBought(msg.sender, quote.asset, quote.attestationId, sharesIn, usdtSpend, 0, stockOut);
    }

    // ═════════════════════════ Sell ═════════════════════════════════════

    /// Sell `quote.quantity` of `quote.asset`; the proceeds re-enter the
    /// caller's savings (paying cUSD's entry fee) and keep earning.
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
        _requireFeeCap(maxFeeBps);

        uint256 userSharesBefore = CUSD_PLUS.balanceOf(msg.sender);

        IERC20(quote.asset).safeTransferFrom(msg.sender, address(this), quote.quantity);
        uint256 usdt = _gmRedeem(quote, signature, minUsdtOut);
        require(usdt >= minUsdtOut, "gm: insufficient payment out");

        // No router fee: the proceeds re-enter savings through cUSD+'s
        // ordinary sponsored entry, which pays cUSD's conversion fee like any
        // other USDT -> cUSD+ entry. The router is a registered relay, so
        // the vault accepts it minting to the user.
        require(usdt > 0, "nothing to reinvest");

        USDT.forceApprove(address(VAULT), usdt);
        VAULT.subscribeAndMint(usdt, 0, msg.sender);
        require(USDT.allowance(address(this), address(VAULT)) == 0, "vault: partial fill");

        // Floor what the USER actually holds afterwards.
        sharesOut = CUSD_PLUS.balanceOf(msg.sender) - userSharesBefore;
        require(sharesOut >= minSharesOut, "insufficient shares out");

        emit StockSold(msg.sender, quote.asset, quote.attestationId, quote.quantity, usdt, 0, sharesOut);
    }

    /// Sell stock directly to raw USDT. This is the permissionless exit: it
    /// never calls the cUSD+ vault, never needs a sponsor, and charges
    /// no fee (it never crosses the cUSD perimeter). `minUsdtOut` protects the
    /// GM redemption; `minNetUsdtOut` independently protects what reaches
    /// the user.
    function sellToUsdt(
        GmQuote calldata quote,
        bytes calldata signature,
        uint256 minUsdtOut,
        uint256 minNetUsdtOut,
        uint256 maxFeeBps
    ) external nonReentrant whenNotPaused returns (uint256 netUsdtOut) {
        require(quote.quantity > 0, "zero in");
        require(quote.price > 0, "zero price");
        require(quote.side == SELL, "wrong quote side");
        require(quote.chainId == block.chainid, "wrong chain");
        require(stockFeeBps <= maxFeeBps, "fee above trade cap");

        IERC20(quote.asset).safeTransferFrom(msg.sender, address(this), quote.quantity);
        uint256 usdt = _gmRedeem(quote, signature, minUsdtOut);
        require(usdt >= minUsdtOut, "gm: insufficient payment out");

        // Never touches Confío dollars, so no perimeter fee applies, and the
        // router's own fee is zero.
        uint256 fee = 0;
        netUsdtOut = usdt;
        require(netUsdtOut > 0, "nothing to redeem");
        require(netUsdtOut >= minNetUsdtOut, "insufficient net usdt out");
        USDT.safeTransfer(msg.sender, netUsdtOut);

        emit StockSoldToUsdt(msg.sender, quote.asset, quote.attestationId, quote.quantity, usdt, fee, netUsdtOut);
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

    function _returnRedemptionExcess(uint256 redeemedUsdt, uint256 usdtSpend, address user) private {
        require(redeemedUsdt >= usdtSpend, "insufficient redeemed usdt");

        // cUSD+ accrues before redeeming, so the same shares can return more
        // USDT than the client predicted when it requested the attestation.
        // Spend only the binding notional and return every excess wei rather
        // than capturing it as an accidental second fee. The excess already
        // paid cUSD's exit fee, so returning it is an ordinary withdrawal.
        uint256 excess = redeemedUsdt - usdtSpend;
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

    /// Confío's single conversion fee, read live from cUSD (the perimeter
    /// that actually charges it). Buys pay it once on the cUSD+ exit and
    /// sells once on the cUSD+ entry, exactly like a USDT withdrawal or
    /// deposit.
    function conversionFeeBps() public view returns (uint256) {
        return ICusdFeePerimeter(VAULT.CUSD()).feeBps();
    }

    /// The user's signed cap binds the fee that will actually be charged, so
    /// a Safe fee change cannot apply to an intent signed at a lower fee.
    /// Since v3 there is no other settlement: a cap below the live fee
    /// (including a pre-v2 build's 30) reverts.
    function _requireFeeCap(uint256 maxFeeBps) private view {
        require(conversionFeeBps() <= maxFeeBps, "fee above trade cap");
    }

    // ═════════════════════════ Ops ══════════════════════════════════════

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    /// Rescue tokens sent here by accident. The router keeps nothing at rest
    /// and has no fee balance, so every token held is stray.
    function sweep(address token, address to, uint256 amount) external onlyOwner nonReentrant {
        require(to != address(0), "zero recipient");
        IERC20(token).safeTransfer(to, amount);
    }
}
