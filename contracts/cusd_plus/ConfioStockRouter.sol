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
 *                    to treasury -> GM settle -> stock tokens to user
 *   sellToSavings:   pull stock tokens -> GM settle -> USDT -> fee slice
 *                    -> vault.subscribeAndMint(recipient = user)
 *                    (proceeds keep earning — the SellStock success copy's
 *                    "sigue generando rendimiento" is literal)
 *
 * Philosophy (same as CusdPlusVault):
 * - The router NEVER holds funds at rest — value only transits inside a
 *   single transaction. sweep() exists for accidents only.
 * - No discretionary anything: amounts in must equal fee + amounts settled,
 *   enforced by balance accounting per call.
 * - Fee is owner-settable BELOW A HARD CAP with an event — the rate is
 *   launch config (pending Ondo's GM fee schedule), never hardcoded.
 * - Replace-by-redeploy instead of upgradeable: the router is stateless,
 *   so pointing the app at a new address IS the upgrade path. (The vault
 *   holds user value and needed UUPS; the router does not.)
 *
 * PROVISIONAL (Ondo onboarding): IGmSettlement mirrors the pattern-C
 * attestation settle (binding quote signed off-chain, settled on-chain).
 * Exact ABI + whether GM on BNB pays/charges in USDT or USDY is an open
 * question in the Michael thread; every GM touchpoint is isolated in
 * _gmBuy/_gmSell so only those two bodies change.
 */

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable2Step, Ownable} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";

interface ICusdPlusVaultMinimal {
    function redeemToUsdt(uint256 shares, uint256 minUsdtOut, address to) external returns (uint256);
    function subscribeAndMint(uint256 usdtIn, uint256 minUsdyOut, address recipient) external returns (uint256);
}

/// PROVISIONAL — replace with the official GM settlement ABI at onboarding.
/// `attestation` carries Ondo's signed binding quote (pattern C).
interface IGmSettlement {
    function buy(
        address stockToken,
        uint256 paymentAmount,
        uint256 minStockOut,
        bytes calldata attestation
    ) external returns (uint256 stockOut);

    function sell(
        address stockToken,
        uint256 stockAmount,
        uint256 minPaymentOut,
        bytes calldata attestation
    ) external returns (uint256 paymentOut);
}

contract ConfioStockRouter is Ownable2Step, Pausable, ReentrancyGuardTransient {
    using SafeERC20 for IERC20;

    IERC20 public immutable CUSD_PLUS;
    IERC20 public immutable USDT;
    ICusdPlusVaultMinimal public immutable VAULT;
    IGmSettlement public immutable GM;
    address public immutable FEE_TREASURY;

    uint256 private constant BPS = 10_000;
    /// Hard ceiling: 1%. The actual rate is launch config, set after Ondo's
    /// GM fee schedule is known — never anchor on any number in code.
    uint256 public constant MAX_FEE_BPS = 100;

    uint256 public stockFeeBps; // starts at 0; owner sets at launch

    event StockFeeSet(uint256 oldBps, uint256 newBps);
    event StockBought(
        address indexed user,
        address indexed stockToken,
        uint256 sharesIn,
        uint256 usdtSpent,
        uint256 feeUsdt,
        uint256 stockOut
    );
    event StockSold(
        address indexed user,
        address indexed stockToken,
        uint256 stockIn,
        uint256 usdtProceeds,
        uint256 feeUsdt,
        uint256 sharesOut
    );

    constructor(
        address cusdPlus,
        address usdt,
        address gmSettlement,
        address feeTreasury,
        address ownerAddr
    ) Ownable(ownerAddr) {
        CUSD_PLUS = IERC20(cusdPlus);
        USDT = IERC20(usdt);
        VAULT = ICusdPlusVaultMinimal(cusdPlus); // vault IS the cUSD+ token
        GM = IGmSettlement(gmSettlement);
        FEE_TREASURY = feeTreasury;
    }

    function setStockFeeBps(uint256 newBps) external onlyOwner {
        require(newBps <= MAX_FEE_BPS, "fee above hard cap");
        emit StockFeeSet(stockFeeBps, newBps);
        stockFeeBps = newBps;
    }

    // ═════════════════════════ Buy ══════════════════════════════════════

    /// Spend `sharesIn` of the caller's cUSD+ on `stockToken`.
    /// minUsdtOut floors the vault redemption; minStockOut floors the GM
    /// settle — both come from the client's accepted quote.
    function buyWithSavings(
        address stockToken,
        uint256 sharesIn,
        uint256 minUsdtOut,
        uint256 minStockOut,
        bytes calldata attestation
    ) external nonReentrant whenNotPaused returns (uint256 stockOut) {
        require(sharesIn > 0, "zero in");

        // Pull the savings shares and redeem them here (router is a pipe:
        // everything received is spent or forwarded within this tx).
        CUSD_PLUS.safeTransferFrom(msg.sender, address(this), sharesIn);
        uint256 usdt = VAULT.redeemToUsdt(sharesIn, minUsdtOut, address(this));

        uint256 fee = (usdt * stockFeeBps) / BPS;
        if (fee > 0) USDT.safeTransfer(FEE_TREASURY, fee);
        uint256 spend = usdt - fee;

        stockOut = _gmBuy(stockToken, spend, minStockOut, attestation);
        IERC20(stockToken).safeTransfer(msg.sender, stockOut);

        emit StockBought(msg.sender, stockToken, sharesIn, spend, fee, stockOut);
    }

    // ═════════════════════════ Sell ═════════════════════════════════════

    /// Sell `stockAmount` of `stockToken`; proceeds (minus fee) re-enter the
    /// caller's savings and keep earning.
    function sellToSavings(
        address stockToken,
        uint256 stockAmount,
        uint256 minPaymentOut,
        uint256 minSharesOut,
        bytes calldata attestation
    ) external nonReentrant whenNotPaused returns (uint256 sharesOut) {
        require(stockAmount > 0, "zero in");

        IERC20(stockToken).safeTransferFrom(msg.sender, address(this), stockAmount);
        uint256 usdt = _gmSell(stockToken, stockAmount, minPaymentOut, attestation);

        uint256 fee = (usdt * stockFeeBps) / BPS;
        if (fee > 0) USDT.safeTransfer(FEE_TREASURY, fee);
        uint256 reinvest = usdt - fee;

        USDT.forceApprove(address(VAULT), reinvest);
        sharesOut = VAULT.subscribeAndMint(reinvest, minSharesOut, msg.sender);

        emit StockSold(msg.sender, stockToken, stockAmount, usdt, fee, sharesOut);
    }

    // ═════════════════════════ GM plumbing (PROVISIONAL) ════════════════
    // The ONLY two bodies that change when the official GM ABI lands.

    function _gmBuy(
        address stockToken,
        uint256 paymentAmount,
        uint256 minStockOut,
        bytes calldata attestation
    ) internal returns (uint256 stockOut) {
        uint256 before = IERC20(stockToken).balanceOf(address(this));
        USDT.forceApprove(address(GM), paymentAmount);
        GM.buy(stockToken, paymentAmount, minStockOut, attestation);
        stockOut = IERC20(stockToken).balanceOf(address(this)) - before;
        require(stockOut >= minStockOut, "gm: insufficient stock out");
    }

    function _gmSell(
        address stockToken,
        uint256 stockAmount,
        uint256 minPaymentOut,
        bytes calldata attestation
    ) internal returns (uint256 paymentOut) {
        uint256 before = USDT.balanceOf(address(this));
        IERC20(stockToken).forceApprove(address(GM), stockAmount);
        GM.sell(stockToken, stockAmount, minPaymentOut, attestation);
        paymentOut = USDT.balanceOf(address(this)) - before;
        require(paymentOut >= minPaymentOut, "gm: insufficient payment out");
    }

    // ═════════════════════════ Ops ══════════════════════════════════════

    function pause() external onlyOwner { _pause(); }
    function unpause() external onlyOwner { _unpause(); }

    /// The router holds nothing at rest, so anything found here is an
    /// accident — rescuable without a backing-exclusion (unlike the vault).
    function sweep(address token, address to, uint256 amount) external onlyOwner {
        IERC20(token).safeTransfer(to, amount);
    }
}
