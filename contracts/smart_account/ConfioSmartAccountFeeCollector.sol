// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @notice Receives Cuenta inteligente subscription fees: cUSD, and cUSD+
/// shares taken in kind (docs/designs/cuenta-inteligente-spec.md, 4.2, 5.1).
/// @dev Same shape as AccountActivationCollector, for two tokens. No signing
/// key, owner, upgrade path, refund, or arbitrary destination. Anyone may pay
/// the gas to sweep revenue; only the immutable treasury receives it. Each
/// token can be swept on its own, so a paused token never holds the other.
contract ConfioSmartAccountFeeCollector {
    using SafeERC20 for IERC20;

    IERC20 public immutable cusd;
    IERC20 public immutable cusdPlus;
    address public immutable treasury;

    error InvalidConfiguration();
    error UnsupportedToken();

    event Swept(address indexed token, uint256 amount);

    constructor(IERC20 cusd_, IERC20 cusdPlus_, address treasury_) {
        if (
            address(cusd_).code.length == 0 || address(cusdPlus_).code.length == 0 || cusd_ == cusdPlus_
                || treasury_ == address(0) || treasury_ == address(this)
        ) {
            revert InvalidConfiguration();
        }
        cusd = cusd_;
        cusdPlus = cusdPlus_;
        treasury = treasury_;
    }

    /// Sweeps both tokens.
    function sweep() external {
        _sweep(cusd);
        _sweep(cusdPlus);
    }

    /// Sweeps one of the two tokens.
    function sweep(IERC20 token) external {
        if (token != cusd && token != cusdPlus) revert UnsupportedToken();
        _sweep(token);
    }

    function _sweep(IERC20 token) private {
        uint256 amount = token.balanceOf(address(this));
        if (amount == 0) return;
        token.safeTransfer(treasury, amount);
        emit Swept(address(token), amount);
    }
}
