// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {IConfioSmartAccount} from "./interfaces/IConfioSmartAccount.sol";

/// The card spender for purchases by the assistant (Cuenta inteligente spec
/// decisions 38 to 42, open point P2).
///
/// An owner's "Compras con Confío IA" Card rule names this contract as its
/// payee; the Safe allowlists it in the factory. For one purchase the owner
/// approved in the chat, Confío's operator calls `pullTo`: the account's own
/// `cardPull` sends exactly `usdtOut` USDT here (through the normal 0.9% exit,
/// counted against the owner's signed cap for the period), and in the same
/// transaction all of it goes on to `to`, the bridge deposit for that one
/// payment. Nothing stays here: Confío never holds the money.
///
/// What bounds a compromised operator key is the owner's signed cap per
/// period (at worst twice the cap around a period boundary: the whole cap
/// just before it and again just after), the factory's spender allowlist and its card pause (both the
/// Safe's), never this contract. Nothing here is upgradeable or ownable; a
/// new operator means a new deployment allowlisted by the Safe.
contract ConfioPurchaseSpender {
    using SafeERC20 for IERC20;

    /// Confío's relayer for purchases: the only caller.
    address public immutable operator;
    /// The token `cardPull` pays out (BSC USDT).
    IERC20 public immutable usdt;

    bool private _entered;

    /// `ref` is the server's id for that payment (its bridge transfer), so a
    /// pull is tied to one approved purchase in the records.
    event Forwarded(
        address indexed account, uint256 indexed ruleId, address indexed to, uint256 usdtOut, bytes32 ref
    );

    error NotOperator();
    error BadTarget();
    error BadAmount();
    error NotReceived();
    error Reentered();

    constructor(address operator_, IERC20 usdt_) {
        if (operator_ == address(0) || address(usdt_) == address(0)) revert BadTarget();
        operator = operator_;
        usdt = usdt_;
    }

    /// Pull `usdtOut` from `account`'s Card rule `ruleId` and forward all of it
    /// to `to`. Reverts as a whole when anything differs: the account's own
    /// checks (rule, payee, cap, state, allowlist, pause), a short receipt, or
    /// anything left behind.
    function pullTo(address account, uint256 ruleId, uint256 usdtOut, address to, bytes32 ref) external {
        // Only a transaction the operator key itself signed: even if that EOA ever carried an EIP-7702
        // delegation, code running as it for someone else never passes (same rule as the account's relayer).
        if (msg.sender != operator || tx.origin != operator) revert NotOperator();
        if (_entered) revert Reentered();
        _entered = true;
        // Never back to the account, never to Confío's own operator key: Confío never holds the money.
        if (to == address(0) || to == address(this) || to == account || to == operator) revert BadTarget();
        if (usdtOut == 0) revert BadAmount();
        uint256 before = usdt.balanceOf(address(this));
        IConfioSmartAccount(account).cardPull(ruleId, usdtOut);
        if (usdt.balanceOf(address(this)) != before + usdtOut) revert NotReceived();
        usdt.safeTransfer(to, usdtOut);
        // All of it left: what was here before (dust someone sent) is untouched, nothing of this pull stays.
        if (usdt.balanceOf(address(this)) != before) revert NotReceived();
        emit Forwarded(account, ruleId, to, usdtOut, ref);
        _entered = false;
    }
}
