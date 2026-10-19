// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ConfioSwapRouter — buy and sell listed BSC tokens (BTCB, ETH, XAUt, WBNB…)
 * with Confío dollars, through PancakeSwap.
 *
 *   buy:  pull the user's cUSD+ shares or cUSD
 *         -> cUSD+.redeemToUsdt / cUSD.redeemWithFee (Confío's 0.9% exit fee)
 *         -> PancakeSwap SmartRouter, ALL net USDT -> token straight to user
 *   sell: pull the user's token -> PancakeSwap -> USDT into this router
 *         -> cUSD+.subscribeAndMint / cUSD.mintWithFee (0.9% entry fee),
 *            minted straight to the user
 *
 * Philosophy (same as ConfioStockRouter v2):
 * - No product fee. Confío's single conversion fee is charged where every
 *   other exit from / entry into Confío Dollar pays it: in cUSD.
 * - The router holds nothing at rest. Every leg is measured by balance delta
 *   and requires exact consumption of what it approved; an owner `sweep`
 *   exists only for accidental transfers.
 * - The DEX call is built here, never forwarded from the caller: the only
 *   external target is the immutable PancakeSwap SmartRouter, the recipient
 *   is fixed by this contract, and the route's endpoints are checked.
 * - Floors are enforced on what the USER ends up holding, so transfer-taxing
 *   or rebasing tokens cannot short-change them silently.
 * - Every trade is originated by Confío's relay (tx.origin is a cUSD+
 *   sponsor), like stock trades. Holders never depend on this router to
 *   leave: their tokens sit in their own wallet and can be sent anywhere.
 *
 * PancakeSwap SmartRouter on BSC (0x13f4EA83D0bd40E75C8222255bc855a974568Dd4),
 * selectors verified in deployed bytecode 2026-10-19:
 *   exactInput((bytes,address,uint256,uint256))            0xb858183f (V3)
 *   swapExactTokensForTokens(uint256,uint256,address[],address) 0x472b43f3 (V2)
 * Neither takes a deadline; the sponsored intent's deadline (<= 30 min) and
 * the user's output floor bound execution instead.
 *
 * Deployment requirements (Safe): cUSD+.setSponsor(router, true) so it may
 * mint cUSD+ to the user on sells, and cUSD.setSponsor(router, true) so it
 * may mint cUSD to the user on sells.
 */

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable2StepUpgradeable} from "@openzeppelin/contracts-upgradeable/access/Ownable2StepUpgradeable.sol";
import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";

interface ISavingsVault {
    function redeemToUsdt(uint256 shares, uint256 minUsdtOut, address to) external returns (uint256);
    function subscribeAndMint(uint256 usdtIn, uint256 minUsdyOut, address recipient) external returns (uint256);
    function isSponsor(address account) external view returns (bool);
    function CUSD() external view returns (address);
    function USDT() external view returns (address);
}

interface ICusdPerimeter {
    function redeemWithFee(uint256 grossCusd, uint256 minUsdtOut, address recipient) external returns (uint256);
    function mintWithFee(uint256 grossUsdt, uint256 minCusdOut, address recipient) external returns (uint256);
    function feeBps() external view returns (uint256);
}

/// PancakeSwap SmartRouter (IV3SwapRouter + IV2SwapRouter subsets).
interface IPancakeSmartRouter {
    struct ExactInputParams {
        bytes path;
        address recipient;
        uint256 amountIn;
        uint256 amountOutMinimum;
    }

    function exactInput(ExactInputParams calldata params) external payable returns (uint256 amountOut);

    function swapExactTokensForTokens(uint256 amountIn, uint256 amountOutMin, address[] calldata path, address to)
        external
        payable
        returns (uint256 amountOut);
}

contract ConfioSwapRouter is Ownable2StepUpgradeable, PausableUpgradeable, ReentrancyGuardTransient, UUPSUpgradeable {
    using SafeERC20 for IERC20;

    /// Where the dollars come from (buy) or go back to (sell).
    uint8 public constant DOLLAR_PLUS = 0; // cUSD+ (Confío Dollar+)
    uint8 public constant DOLLAR = 1; // cUSD (Confío Dollar)

    uint8 public constant ROUTE_V3 = 0; // bytes path: token(20) fee(3) token(20) ...
    uint8 public constant ROUTE_V2 = 1; // address[] path

    ISavingsVault public immutable VAULT; // cUSD+
    IERC20 public immutable USDT;
    IPancakeSmartRouter public immutable SMART_ROUTER;

    event CryptoBought(
        address indexed user,
        address indexed token,
        uint8 source,
        uint256 amountIn,
        uint256 usdtSpent,
        uint256 tokenOut
    );
    event CryptoSold(
        address indexed user,
        address indexed token,
        uint8 dest,
        uint256 amountIn,
        uint256 usdtProceeds,
        uint256 destOut
    );
    event Swept(address indexed token, address indexed to, uint256 amount);

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor(address vault, address smartRouter) {
        require(vault.code.length > 0 && smartRouter.code.length > 0, "non-contract dependency");
        VAULT = ISavingsVault(vault);
        USDT = IERC20(ISavingsVault(vault).USDT());
        require(address(USDT).code.length > 0, "non-contract usdt");
        require(ISavingsVault(vault).CUSD() != address(0), "cusd not configured");
        SMART_ROUTER = IPancakeSmartRouter(smartRouter);
        _disableInitializers();
    }

    function initialize(address ownerAddr) external initializer {
        __Ownable_init(ownerAddr);
        __Ownable2Step_init();
        __Pausable_init();
    }

    function _authorizeUpgrade(address) internal view override onlyOwner {}

    /// Confío's relay must originate every trade (same rule as stocks).
    modifier onlySponsoredOrigin() {
        require(VAULT.isSponsor(tx.origin), "not sponsored");
        _;
    }

    // ═════════════════════════ Buy ══════════════════════════════════════

    /// Spend `amountIn` of the caller's cUSD+ shares (source 0) or cUSD
    /// (source 1) on `tokenOut`. `minUsdtOut` floors the net USDT after the
    /// exit fee; ALL of it is swapped, so nothing is left to refund.
    /// `minTokenOut` floors what the user's own balance gains.
    function buy(
        uint8 source,
        uint256 amountIn,
        uint256 minUsdtOut,
        bytes calldata route,
        address tokenOut,
        uint256 minTokenOut,
        uint256 maxFeeBps
    ) external nonReentrant whenNotPaused onlySponsoredOrigin returns (uint256 tokenOutAmount) {
        require(amountIn > 0, "zero in");
        require(minUsdtOut > 0 && minTokenOut > 0, "zero floor");
        _requireListedShape(tokenOut);
        _requireFeeCap(maxFeeBps);
        _requireRouteEnds(route, address(USDT), tokenOut);

        uint256 userBefore = IERC20(tokenOut).balanceOf(msg.sender);
        uint256 usdt = _exitDollars(source, amountIn, minUsdtOut);
        _swap(route, address(USDT), usdt, minTokenOut, msg.sender);

        tokenOutAmount = IERC20(tokenOut).balanceOf(msg.sender) - userBefore;
        require(tokenOutAmount >= minTokenOut, "user short-changed");
        emit CryptoBought(msg.sender, tokenOut, source, amountIn, usdt, tokenOutAmount);
    }

    // ═════════════════════════ Sell ═════════════════════════════════════

    /// Sell `amountIn` of `tokenIn`; proceeds re-enter the caller's cUSD+
    /// (dest 0) or cUSD (dest 1) through the ordinary entry fee.
    /// `minUsdtOut` floors the swap; `minDestOut` floors what the user's own
    /// dollar balance gains.
    function sell(
        uint8 dest,
        address tokenIn,
        uint256 amountIn,
        bytes calldata route,
        uint256 minUsdtOut,
        uint256 minDestOut,
        uint256 maxFeeBps
    ) external nonReentrant whenNotPaused onlySponsoredOrigin returns (uint256 destOut) {
        require(amountIn > 0, "zero in");
        require(minUsdtOut > 0 && minDestOut > 0, "zero floor");
        _requireListedShape(tokenIn);
        _requireFeeCap(maxFeeBps);
        _requireRouteEnds(route, tokenIn, address(USDT));

        // Swap what actually arrived (a transfer-taxing token delivers less).
        uint256 tokenBefore = IERC20(tokenIn).balanceOf(address(this));
        IERC20(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);
        uint256 received = IERC20(tokenIn).balanceOf(address(this)) - tokenBefore;
        require(received > 0, "nothing received");

        uint256 usdtBefore = USDT.balanceOf(address(this));
        _swap(route, tokenIn, received, minUsdtOut, address(this));
        uint256 usdt = USDT.balanceOf(address(this)) - usdtBefore;
        require(usdt >= minUsdtOut, "dex: insufficient usdt out");

        destOut = _enterDollars(dest, usdt, minDestOut, msg.sender);
        emit CryptoSold(msg.sender, tokenIn, dest, amountIn, usdt, destOut);
    }

    // ═════════════════════════ Views ════════════════════════════════════

    /// Confío's single conversion fee, read live from cUSD.
    function conversionFeeBps() public view returns (uint256) {
        return ICusdPerimeter(VAULT.CUSD()).feeBps();
    }

    // ═════════════════════════ Internals ════════════════════════════════

    function _cusd() private view returns (address) {
        return VAULT.CUSD();
    }

    /// The signed cap binds the fee actually charged: a Safe fee change can
    /// never apply to an intent signed at a lower fee.
    function _requireFeeCap(uint256 maxFeeBps) private view {
        require(conversionFeeBps() <= maxFeeBps, "fee above trade cap");
    }

    /// The traded token can never be one of Confío's own dollars or USDT:
    /// those move only through the perimeter, never through a DEX here.
    function _requireListedShape(address token) private view {
        require(token != address(0) && token.code.length > 0, "bad token");
        require(token != address(USDT) && token != address(VAULT) && token != _cusd(), "dollar token");
    }

    /// Pull the user's dollars and exit through cUSD's fee perimeter.
    /// Measures the router's own USDT delta, never trusts return values.
    function _exitDollars(uint8 source, uint256 amountIn, uint256 minUsdtOut) private returns (uint256 usdt) {
        uint256 before = USDT.balanceOf(address(this));
        if (source == DOLLAR_PLUS) {
            IERC20(address(VAULT)).safeTransferFrom(msg.sender, address(this), amountIn);
            VAULT.redeemToUsdt(amountIn, minUsdtOut, address(this));
        } else if (source == DOLLAR) {
            address cusd = _cusd();
            IERC20(cusd).safeTransferFrom(msg.sender, address(this), amountIn);
            ICusdPerimeter(cusd).redeemWithFee(amountIn, minUsdtOut, address(this));
        } else {
            revert("bad source");
        }
        usdt = USDT.balanceOf(address(this)) - before;
        require(usdt >= minUsdtOut, "insufficient usdt out");
    }

    /// Enter the user's dollars through cUSD's fee perimeter, minting
    /// straight to the user; floors the user's own balance delta.
    function _enterDollars(uint8 dest, uint256 usdt, uint256 minDestOut, address user)
        private
        returns (uint256 destOut)
    {
        address target;
        address token;
        if (dest == DOLLAR_PLUS) {
            target = address(VAULT);
            token = address(VAULT);
        } else if (dest == DOLLAR) {
            target = _cusd();
            token = target;
        } else {
            revert("bad dest");
        }
        uint256 before = IERC20(token).balanceOf(user);
        USDT.forceApprove(target, usdt);
        if (dest == DOLLAR_PLUS) {
            VAULT.subscribeAndMint(usdt, 0, user);
        } else {
            ICusdPerimeter(target).mintWithFee(usdt, minDestOut, user);
        }
        require(USDT.allowance(address(this), target) == 0, "perimeter: partial fill");
        destOut = IERC20(token).balanceOf(user) - before;
        require(destOut >= minDestOut, "insufficient dollars out");
    }

    /// Route endpoints must be exactly (from, to). Hop tokens are whatever
    /// PancakeSwap pools the server's catalog chose; only the ends bind the
    /// user's assets.
    function _requireRouteEnds(bytes calldata route, address from, address to) private pure {
        (uint8 kind, bytes memory data) = abi.decode(route, (uint8, bytes));
        address first;
        address last;
        if (kind == ROUTE_V3) {
            require(data.length >= 43 && (data.length - 20) % 23 == 0, "bad v3 path");
            first = _addressAt(data, 0);
            last = _addressAt(data, data.length - 20);
        } else if (kind == ROUTE_V2) {
            address[] memory path = abi.decode(data, (address[]));
            require(path.length >= 2, "bad v2 path");
            first = path[0];
            last = path[path.length - 1];
        } else {
            revert("bad route kind");
        }
        require(first == from && last == to, "route endpoints");
    }

    function _addressAt(bytes memory data, uint256 offset) private pure returns (address a) {
        assembly {
            a := shr(96, mload(add(add(data, 32), offset)))
        }
    }

    /// Swap exactly `amountIn` of `tokenIn` on the SmartRouter, delivering to
    /// `recipient`. The leftover-allowance check is the exact-consumption
    /// rule: a partial pull would leave value here behind a live approval.
    function _swap(bytes calldata route, address tokenIn, uint256 amountIn, uint256 minOut, address recipient)
        private
    {
        (uint8 kind, bytes memory data) = abi.decode(route, (uint8, bytes));
        IERC20(tokenIn).forceApprove(address(SMART_ROUTER), amountIn);
        if (kind == ROUTE_V3) {
            SMART_ROUTER.exactInput(
                IPancakeSmartRouter.ExactInputParams({
                    path: data, recipient: recipient, amountIn: amountIn, amountOutMinimum: minOut
                })
            );
        } else {
            address[] memory path = abi.decode(data, (address[]));
            SMART_ROUTER.swapExactTokensForTokens(amountIn, minOut, path, recipient);
        }
        require(IERC20(tokenIn).allowance(address(this), address(SMART_ROUTER)) == 0, "dex: partial fill");
    }

    // ═════════════════════════ Ops ══════════════════════════════════════

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    /// The router never holds value at rest; this only rescues accidental
    /// transfers.
    function sweep(address token, address to, uint256 amount) external onlyOwner nonReentrant {
        require(to != address(0), "zero to");
        IERC20(token).safeTransfer(to, amount);
        emit Swept(token, to, amount);
    }
}
