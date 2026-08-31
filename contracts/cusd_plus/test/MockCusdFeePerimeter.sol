// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ICusdVault} from "../CusdPlusVault.sol";

/// Test-only cUSD perimeter. A zero fee preserves the pre-fee cUSD+ unit
/// tests; integration tests use the real CusdVault at 90 bps.
contract MockCusdFeePerimeter is ERC20, ICusdVault {
    using SafeERC20 for IERC20;

    IERC20 public immutable usdt;
    uint256 public immutable feeBps;

    constructor(IERC20 usdt_, uint256 feeBps_) ERC20("Mock cUSD", "mcUSD") {
        usdt = usdt_;
        feeBps = feeBps_;
    }

    function _fee(uint256 gross) internal view returns (uint256) {
        if (gross == 0 || feeBps == 0) return 0;
        return Math.mulDiv(gross, feeBps, 10_000, Math.Rounding.Ceil);
    }

    function backingToken() external view returns (address) {
        return address(usdt);
    }

    function settleSavingsEntry(uint256 gross, uint256 minOut) external returns (uint256 net) {
        net = gross - _fee(gross);
        require(net >= minOut, "insufficient out");
        usdt.safeTransferFrom(msg.sender, address(this), gross);
        usdt.safeTransfer(msg.sender, net);
    }

    function settleSavingsExit(uint256 gross, uint256 minOut, address recipient) external returns (uint256 net) {
        net = gross - _fee(gross);
        require(net >= minOut, "insufficient out");
        usdt.safeTransferFrom(msg.sender, address(this), gross);
        usdt.safeTransfer(recipient, net);
    }

    function redeemForSavings(uint256 amount, address recipient) external returns (uint256) {
        _burn(msg.sender, amount);
        usdt.safeTransfer(recipient, amount);
        return amount;
    }

    function mintForSavings(uint256 amount, address recipient) external returns (uint256) {
        usdt.safeTransferFrom(msg.sender, address(this), amount);
        _mint(recipient, amount);
        return amount;
    }

    function seed(address to, uint256 amount) external {
        _mint(to, amount);
    }
}
