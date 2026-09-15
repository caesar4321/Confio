// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @notice Receives earned activation fees via ordinary cUSD transfers.
/// @dev No signing key, owner, upgrade path, refund, or arbitrary destination.
/// Anyone may pay the gas to sweep revenue; only the immutable treasury receives it.
contract AccountActivationCollector {
    using SafeERC20 for IERC20;

    IERC20 public immutable token;
    address public immutable treasury;

    error InvalidConfiguration();
    event Swept(uint256 amount);

    constructor(IERC20 token_, address treasury_) {
        if (address(token_).code.length == 0 || treasury_ == address(0) || treasury_ == address(this)) {
            revert InvalidConfiguration();
        }
        token = token_;
        treasury = treasury_;
    }

    function sweep() external {
        uint256 amount = token.balanceOf(address(this));
        if (amount == 0) return;
        token.safeTransfer(treasury, amount);
        emit Swept(amount);
    }
}
