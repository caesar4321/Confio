// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ConfioStockRouter — the sweep-model trade path: GM tokenized stocks are
 * bought FROM and sold INTO the user's savings (cUSD+), with Confío's fee
 * taken as an EXPLICIT on-chain transfer (never a hidden price markup —
 * "Sin comisiones ocultas" is enforced here, not just promised in copy).
 *
 * One user signature per trade (plus one-time approvals):
 *
 *   buyWithSavings:  pull cUSD+ shares -> vault.redeemToUsdt -> fee slice
 *                    to treasury -> GM mint -> stock tokens to user
 *   sellToSavings:   pull stock tokens -> GM redeem -> USDT -> fee slice
 *                    -> vault.subscribeAndMint(recipient = user)
 *                    (proceeds keep earning — the SellStock success copy's
 *                    "sigue generando rendimiento" is literal)
 *
 * Philosophy (same as CusdPlusVault):
 * - The router NEVER holds funds at rest — value only transits inside a
 *   single transaction. sweep() exists for accidents only.
 * - No discretionary anything: amounts in must equal fee + amounts settled,
 *   enforced by balance accounting per call.
 * - Replace-by-redeploy instead of upgradeable: the router is stateless,
 *   so pointing the app at a new address IS the upgrade path.
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
 *  - each trade commits to a maxFeeBps, so a fee change cannot be slipped
 *    in front of an already-signed trade.
 */

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable2Step, Ownable} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";

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

contract ConfioStockRouter is Ownable2Step, Pausable, ReentrancyGuardTransient {
    using SafeERC20 for IERC20;

    IERC20 public immutable CUSD_PLUS;
    IERC20 public immutable USDT;
    /// Ondo's USD stablecoin. A non-USDon deposit is converted inside GM via
    /// usdonManager, and any SURPLUS USDon is refunded to the caller (us) —
    /// see _forwardUsdonDust.
    IERC20 public immutable USDON;
    ICusdPlusVaultMinimal public immutable VAULT;
    IGMTokenManager public immutable GM;
    address public immutable FEE_TREASURY;

    uint256 private constant BPS = 10_000;
    /// Hard ceiling: 1%. The actual rate is launch config, set once Ondo's
    /// GM fee/spread arrangement is known — never anchor on a number in code.
    uint256 public constant MAX_FEE_BPS = 100;

    uint256 public stockFeeBps; // starts at 0; owner sets at launch

    event StockFeeSet(uint256 oldBps, uint256 newBps);
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
    /// Sub-cent USDon left over from GM's internal USDT->USDon conversion.
    /// Surfaced as its own event so the leak is auditable rather than silent.
    event UsdonDustForwarded(address indexed user, uint256 amount);

    constructor(
        address cusdPlus,
        address usdt,
        address usdon,
        address gmTokenManager,
        address feeTreasury,
        address ownerAddr
    ) Ownable(ownerAddr) {
        require(
            cusdPlus != address(0) && usdt != address(0) && usdon != address(0)
                && gmTokenManager != address(0) && feeTreasury != address(0),
            "zero address"
        );
        CUSD_PLUS = IERC20(cusdPlus);
        USDT = IERC20(usdt);
        USDON = IERC20(usdon);
        VAULT = ICusdPlusVaultMinimal(cusdPlus); // the vault IS the cUSD+ token
        GM = IGMTokenManager(gmTokenManager);
        FEE_TREASURY = feeTreasury;
    }

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

    function setStockFeeBps(uint256 newBps) external onlyOwner {
        require(newBps <= MAX_FEE_BPS, "fee above hard cap");
        emit StockFeeSet(stockFeeBps, newBps);
        stockFeeBps = newBps;
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
        uint256 minUsdtOut,
        uint256 maxFeeBps
    ) external nonReentrant whenNotPaused onlySponsoredOrigin returns (uint256 stockOut) {
        require(sharesIn > 0, "zero in");
        require(quote.chainId == block.chainid, "wrong chain");
        require(stockFeeBps <= maxFeeBps, "fee above trade cap");

        uint256 userStockBefore = IERC20(quote.asset).balanceOf(msg.sender);
        uint256 usdonBefore = USDON.balanceOf(address(this));

        // Pull the savings shares and redeem them here (router is a pipe:
        // everything received is spent or forwarded within this tx).
        CUSD_PLUS.safeTransferFrom(msg.sender, address(this), sharesIn);
        uint256 usdt = VAULT.redeemToUsdt(sharesIn, minUsdtOut, address(this));

        uint256 fee = (usdt * stockFeeBps) / BPS;
        if (fee > 0) USDT.safeTransfer(FEE_TREASURY, fee);
        uint256 spend = usdt - fee;
        require(spend > 0, "nothing to spend");

        uint256 minted = _gmMint(quote, signature, spend);
        require(minted >= quote.quantity, "gm: short mint");
        IERC20(quote.asset).safeTransfer(msg.sender, minted);

        // Floor what the USER got, not what we got (transfer-taxing tokens).
        stockOut = IERC20(quote.asset).balanceOf(msg.sender) - userStockBefore;
        require(stockOut >= quote.quantity, "user short-changed");

        _forwardUsdonDust(usdonBefore);

        emit StockBought(
            msg.sender, quote.asset, quote.attestationId, sharesIn, spend, fee, stockOut
        );
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
        require(quote.chainId == block.chainid, "wrong chain");
        require(stockFeeBps <= maxFeeBps, "fee above trade cap");

        uint256 userSharesBefore = CUSD_PLUS.balanceOf(msg.sender);

        IERC20(quote.asset).safeTransferFrom(msg.sender, address(this), quote.quantity);
        uint256 usdt = _gmRedeem(quote, signature, minUsdtOut);
        require(usdt >= minUsdtOut, "gm: insufficient payment out");

        uint256 fee = (usdt * stockFeeBps) / BPS;
        if (fee > 0) USDT.safeTransfer(FEE_TREASURY, fee);
        uint256 reinvest = usdt - fee;
        require(reinvest > 0, "nothing to reinvest");

        USDT.forceApprove(address(VAULT), reinvest);
        VAULT.subscribeAndMint(reinvest, 0, msg.sender);
        require(USDT.allowance(address(this), address(VAULT)) == 0, "vault: partial fill");

        // Floor what the USER actually holds afterwards.
        sharesOut = CUSD_PLUS.balanceOf(msg.sender) - userSharesBefore;
        require(sharesOut >= minSharesOut, "insufficient shares out");

        emit StockSold(
            msg.sender, quote.asset, quote.attestationId, quote.quantity, usdt, fee, sharesOut
        );
    }

    // ═════════════════════════ Internals ════════════════════════════════

    /// GM pulls `spend` USDT and mints quote.quantity to US (the caller).
    /// Extracted so `buyWithSavings` stays under the stack limit.
    ///
    /// The allowance assertion is the audit's exact-consumption rule: a
    /// leftover allowance means GM took less than we committed, which would
    /// leave value here behind a live approval. Reject the whole trade.
    function _gmMint(GmQuote calldata quote, bytes calldata signature, uint256 spend)
        private
        returns (uint256 minted)
    {
        uint256 before = IERC20(quote.asset).balanceOf(address(this));
        USDT.forceApprove(address(GM), spend);
        GM.mintWithAttestation(quote, signature, address(USDT), spend);
        require(USDT.allowance(address(this), address(GM)) == 0, "gm: partial fill");
        minted = IERC20(quote.asset).balanceOf(address(this)) - before;
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
        require(
            IERC20(quote.asset).allowance(address(this), address(GM)) == 0,
            "gm: partial fill"
        );
        proceeds = USDT.balanceOf(address(this)) - before;
    }

    /// GM converts a non-USDon deposit through usdonManager and refunds any
    /// SURPLUS USDon to the caller — us. That surplus is conversion-rounding
    /// dust denominated in a token the user cannot spend in this app, so it
    /// goes to the fee treasury with its own event rather than being left to
    /// accumulate silently in a contract that is supposed to hold nothing.
    /// If it is ever material, switch to depositing USDon directly (held as
    /// router working capital) so no refund leg exists at all.
    function _forwardUsdonDust(uint256 usdonBefore) private {
        uint256 dust = USDON.balanceOf(address(this)) - usdonBefore;
        if (dust > 0) {
            USDON.safeTransfer(FEE_TREASURY, dust);
            emit UsdonDustForwarded(msg.sender, dust);
        }
    }

    // ═════════════════════════ Ops ══════════════════════════════════════

    function pause() external onlyOwner { _pause(); }
    function unpause() external onlyOwner { _unpause(); }

    /// The router holds nothing at rest, so anything found here is an
    /// accident — rescuable without a backing-exclusion (unlike the vault).
    function sweep(address token, address to, uint256 amount) external onlyOwner {
        require(to != address(0), "zero recipient");
        IERC20(token).safeTransfer(to, amount);
    }
}
