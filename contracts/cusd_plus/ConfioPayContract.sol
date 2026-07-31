// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ConfioPayContract — invoice payments with the 0.9% merchant fee
 * enforced and ACCRUED ON-CHAIN.
 *
 * WHY A CONTRACT (2026-07-31, superseding the 2-transfer batch): fees sit
 * in each contract so revenue accounting reads straight off the chain
 * (accruedFees per token + FeesCollected events), and the fee math lives
 * in code — a bug or compromise in the server's batch builder cannot
 * misprice a fee or point it somewhere else. The extra gas over the bare
 * 2-transfer batch is ~half a cent on BSC, paid by the sponsor.
 *
 * Flow: the payer's 7702 batch is [token.approve(this, gross),
 * this.pay(invoiceId, token, gross, merchant)] — atomic under
 * ConfioBatchDelegate.execute, so the approval never outlives the
 * payment. pay() computes fee = ceil(gross * 90 / 10000) (exact integer
 * parity with the Algorand builder and payments/bsc_flow.py), sends
 * net = gross − fee to the merchant, pulls the fee into this contract,
 * and replay-guards the invoiceId.
 *
 * House rules: token allowlist fixed at deploy (cUSD+ vault shares +
 * BSC-USDT — the only two dollars in the system); non-upgradeable;
 * owner (Safe) can only collect accrued fees and pause NEW payments;
 * no path to anything but the fee accrual. Merchant payout is a direct
 * transfer — nothing but fees ever rests here.
 */

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";

contract ConfioPayContract is Ownable2Step, Pausable, ReentrancyGuardTransient {
    using SafeERC20 for IERC20;

    uint256 public constant FEE_BPS = 90; // 0.9%, ceiling division

    IERC20 public immutable CUSD_PLUS;
    IERC20 public immutable USDT;

    /// Fee revenue accrued in-contract, per token (the only funds at rest).
    mapping(address => uint256) public accruedFees;

    /// Replay guard keyed on the FULL payment terms, not the invoice id
    /// alone (audit 2026-07-31, [P1]): `pay` is permissionless, so keying
    /// on `invoiceId` by itself let anyone who learned an id burn it with a
    /// 1-wei self-payment and permanently brick the real payment. Keying on
    /// (invoiceId, payer, token, gross, merchant) still blocks an exact
    /// double-charge — the thing a replay guard is for — while a griefer's
    /// different terms consume a different key and cannot block anyone.
    /// A stranger paying a merchant on someone else's invoice id is just a
    /// gift; the DB remains the authority on whether an invoice is settled.
    mapping(bytes32 => bool) public paymentDone;

    function paymentKey(
        bytes32 invoiceId,
        address payer,
        address token,
        uint256 gross,
        address merchant
    ) public pure returns (bytes32) {
        return keccak256(abi.encode(invoiceId, payer, token, gross, merchant));
    }

    event PaymentMade(
        bytes32 indexed invoiceId,
        address indexed payer,
        address indexed merchant,
        address token,
        uint256 gross,
        uint256 fee
    );
    event FeesCollected(address indexed token, address indexed to, uint256 amount);

    constructor(address cusdPlus, address usdt, address owner_) Ownable(owner_) {
        require(cusdPlus != address(0) && usdt != address(0), "zero address");
        CUSD_PLUS = IERC20(cusdPlus);
        USDT = IERC20(usdt);
    }

    /// The exact fee rule shared by the Algorand builder and
    /// payments/bsc_flow.py: ceil(gross * 90 / 10000). mulDiv keeps the
    /// intermediate product from overflowing at absurd magnitudes.
    function feeFor(uint256 gross) public pure returns (uint256) {
        return Math.mulDiv(gross, FEE_BPS, 10_000, Math.Rounding.Ceil);
    }

    /// Called BY the payer (their EOA, via the sponsored 7702 batch that
    /// approved `gross` one call earlier). msg.sender is the payer.
    function pay(bytes32 invoiceId, address token, uint256 gross, address merchant)
        external
        nonReentrant
        whenNotPaused
        returns (uint256 fee)
    {
        require(token == address(CUSD_PLUS) || token == address(USDT), "token not allowed");
        require(merchant != address(0) && merchant != address(this), "bad merchant");
        require(merchant != msg.sender, "self payment");
        fee = feeFor(gross);
        // The merchant must actually receive something: at gross == 1 the
        // ceiling fee eats the whole payment, which is a "paid" event with
        // a zero transfer.
        require(gross > fee, "amount too small");

        bytes32 key = paymentKey(invoiceId, msg.sender, token, gross, merchant);
        require(!paymentDone[key], "payment done");
        paymentDone[key] = true;
        IERC20(token).safeTransferFrom(msg.sender, merchant, gross - fee);
        IERC20(token).safeTransferFrom(msg.sender, address(this), fee);
        accruedFees[token] += fee;

        emit PaymentMade(invoiceId, msg.sender, merchant, token, gross, fee);
    }

    // ═════════════════════════ Admin ════════════════════════════════════
    // Bounded by the accrual counters — stray tokens sent here directly
    // are not collectible (nothing else should ever rest here anyway).

    function collectFees(address token, address to, uint256 amount)
        external
        onlyOwner
        nonReentrant
    {
        require(to != address(0), "zero recipient");
        require(amount > 0 && amount <= accruedFees[token], "exceeds accrued fees");
        accruedFees[token] -= amount;
        IERC20(token).safeTransfer(to, amount);
        emit FeesCollected(token, to, amount);
    }

    function pause() external onlyOwner { _pause(); }
    function unpause() external onlyOwner { _unpause(); }
}
