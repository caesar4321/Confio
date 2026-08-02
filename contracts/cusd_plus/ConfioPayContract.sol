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
 * WHY SERVER-AUTHORIZED (2026-07-31 migration audit, [P1]): `pay` used to
 * be permissionless and replay-guarded on the FULL terms. That fixed
 * griefing but left an honest double-charge open — two people paying the
 * same invoice both succeed, because their (payer,…) keys differ. Keying
 * the guard on `invoiceId` ALONE instead reintroduces griefing: anyone who
 * learns an id burns it with a 1-wei self-payment.
 *
 * Resolution: the backend signs an EIP-712 authorization over the exact
 * terms {invoiceId, payer, token, gross, merchant, deadline}, and the
 * guard is GLOBAL on invoiceId. A griefer cannot forge the signature, so
 * cannot brick anything; and once ANY authorized payer settles invoiceId,
 * every other authorization for that id reverts — exactly one payment per
 * invoice, enforced on-chain, matching the DB's single-settlement model.
 *
 * Flow: the payer's 7702 batch is [token.approve(this, gross),
 * this.pay(invoiceId, token, gross, merchant, deadline, authSig)] — atomic
 * under ConfioBatchDelegate.execute, so the approval never outlives the
 * payment. pay() verifies the server authorization, computes
 * fee = ceil(gross * 90 / 10000) (exact integer parity with the Algorand
 * builder and payments/bsc_flow.py), sends net = gross − fee to the
 * merchant, pulls the fee into this contract, and consumes the invoiceId.
 *
 * House rules: token allowlist fixed at deploy (cUSD+ vault shares +
 * BSC-USDT + CONFIO); non-upgradeable; owner (Safe) can collect accrued
 * fees, rotate the payment signer, and pause NEW payments; no path to
 * anything but the fee accrual. Merchant payout is a direct transfer —
 * nothing but fees ever rests here.
 *
 * The allowlist is not the charge menu (2026-08-01, ChargeScreen migration).
 * A merchant charges in exactly two denominations — cUSD+ or CONFIO — and
 * USDT is here as the PAYER's funding fallback: someone holding raw USDT
 * (including anyone geo-ineligible to mint cUSD+) settles a dollar invoice
 * with it and the merchant receives that same token. Dropping USDT would
 * match the menu but lock ineligible payers out of paying merchants at all.
 */

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {SignatureChecker} from "@openzeppelin/contracts/utils/cryptography/SignatureChecker.sol";

interface ICusdPlusVault {
    function redeemToUsdt(uint256 shares, uint256 minUsdtOut, address to)
        external
        returns (uint256 usdtOut);
}


contract ConfioPayContract is Ownable2Step, Pausable, ReentrancyGuardTransient, EIP712 {
    using SafeERC20 for IERC20;

    uint256 public constant FEE_BPS = 90; // 0.9%, ceiling division

    IERC20 public immutable CUSD_PLUS;
    IERC20 public immutable USDT;
    /// CONFIO (BEP-20, re-issued 2026-07-31). A charge denomination in its
    /// own right — amounts are a token COUNT, not USD — settled through the
    /// same fee/guard path so CONFIO revenue accrues on-chain like the rest.
    IERC20 public immutable CONFIO;

    /// Backend authorizer. Every pay() carries this signer's EIP-712
    /// authorization over the exact terms; rotate via setPaymentSigner
    /// (Safe-only) if the backend key ever changes.
    address public paymentSigner;

    /// Fee revenue accrued in-contract, per token (the only funds at rest).
    mapping(address => uint256) public accruedFees;

    /// GLOBAL single-settlement guard keyed on invoiceId alone. Safe to key
    /// on the id here — unlike the old permissionless design — because only
    /// the backend can authorize a payment, so no one can grief-consume an
    /// id, and exactly one authorized payment per invoice may settle.
    mapping(bytes32 => bool) public invoiceDone;

    bytes32 private constant PAY_TYPEHASH = keccak256(
        "Pay(bytes32 invoiceId,address payer,address token,uint256 gross,address merchant,bool redeemToUsdt,uint256 minUsdtOut,uint256 deadline)"
    );

    event PaymentMade(
        bytes32 indexed invoiceId,
        address indexed payer,
        address indexed merchant,
        address token,
        uint256 gross,
        uint256 fee,
        bool redeemedToUsdt,
        uint256 usdtOut
    );
    event FeesCollected(address indexed token, address indexed to, uint256 amount);
    event PaymentSignerChanged(address indexed previous, address indexed current);

    constructor(address cusdPlus, address usdt, address confio, address signer_, address owner_)
        Ownable(owner_)
        EIP712("ConfioPay", "1")
    {
        require(
            cusdPlus != address(0) && usdt != address(0) && confio != address(0),
            "zero address"
        );
        require(signer_ != address(0), "zero signer");
        CUSD_PLUS = IERC20(cusdPlus);
        USDT = IERC20(usdt);
        CONFIO = IERC20(confio);
        paymentSigner = signer_;
        emit PaymentSignerChanged(address(0), signer_);
    }

    /// The exact fee rule shared by the Algorand builder and
    /// payments/bsc_flow.py: ceil(gross * 90 / 10000). mulDiv keeps the
    /// intermediate product from overflowing at absurd magnitudes.
    function feeFor(uint256 gross) public pure returns (uint256) {
        return Math.mulDiv(gross, FEE_BPS, 10_000, Math.Rounding.Ceil);
    }

    /// The EIP-712 digest the backend signs to authorize one payment.
    /// Exposed so the server and tests can recompute it byte-for-byte.
    function payDigest(
        bytes32 invoiceId,
        address payer,
        address token,
        uint256 gross,
        address merchant,
        bool redeemToUsdt,
        uint256 minUsdtOut,
        uint256 deadline
    ) public view returns (bytes32) {
        return _hashTypedDataV4(keccak256(abi.encode(
            PAY_TYPEHASH, invoiceId, payer, token, gross, merchant,
            redeemToUsdt, minUsdtOut, deadline
        )));
    }

    /// Called BY the payer (their EOA, via the sponsored 7702 batch that
    /// approved `gross` one call earlier). msg.sender is the payer, and the
    /// server authorization is bound to exactly this payer.
    function pay(
        bytes32 invoiceId,
        address token,
        uint256 gross,
        address merchant,
        bool redeemToUsdt,
        uint256 minUsdtOut,
        uint256 deadline,
        bytes calldata authSig
    )
        external
        nonReentrant
        whenNotPaused
        returns (uint256 fee)
    {
        require(block.timestamp <= deadline, "authorization expired");
        require(
            token == address(CUSD_PLUS) || token == address(USDT) || token == address(CONFIO),
            "token not allowed"
        );
        require(merchant != address(0) && merchant != address(this), "bad merchant");
        require(merchant != msg.sender, "self payment");
        require(!invoiceDone[invoiceId], "invoice done");

        // The backend must have authorized THESE exact terms for THIS payer.
        bytes32 digest = payDigest(invoiceId, msg.sender, token, gross, merchant,
                                   redeemToUsdt, minUsdtOut, deadline);
        require(
            SignatureChecker.isValidSignatureNow(paymentSigner, digest, authSig),
            "bad authorization"
        );

        fee = feeFor(gross);
        // The merchant must actually receive something: at gross == 1 the
        // ceiling fee eats the whole payment, which is a "paid" event with
        // a zero transfer.
        require(gross > fee, "amount too small");

        invoiceDone[invoiceId] = true;
        IERC20(token).safeTransferFrom(msg.sender, address(this), fee);
        accruedFees[token] += fee;

        // Merchant leg. Mirrors ConfioPayrollVault.payout(): the routing is a
        // SIGNED parameter, so the backend decides eligibility and the chain
        // enforces that the decision was authorized. A merchant who cannot
        // hold cUSD+ is paid in USDT atomically, in this one call — no
        // sibling redeem in the caller's batch, nothing for a validator to
        // police.
        uint256 net = gross - fee;
        uint256 usdtOut;
        if (redeemToUsdt) {
            require(token == address(CUSD_PLUS), "redeem needs cUSD+");
            require(minUsdtOut > 0, "minOut required");
            IERC20(token).safeTransferFrom(msg.sender, address(this), net);

            // Trust the OUTCOME, not the return value. CUSD_PLUS is a UUPS
            // proxy: a faulty or hostile implementation could return a
            // plausible usdtOut while paying the merchant nothing and leaving
            // `net` here — where collectFees, bounded by accruedFees, could
            // never retrieve it. Measure what the merchant actually received
            // and what we actually spent, and revert unless both hold.
            uint256 merchantBefore = USDT.balanceOf(merchant);
            uint256 sharesBefore = IERC20(token).balanceOf(address(this));
            usdtOut = ICusdPlusVault(address(CUSD_PLUS)).redeemToUsdt(net, minUsdtOut, merchant);
            require(USDT.balanceOf(merchant) - merchantBefore >= minUsdtOut,
                    "merchant not paid");
            require(sharesBefore - IERC20(token).balanceOf(address(this)) == net,
                    "shares not consumed");
        } else {
            require(minUsdtOut == 0, "minOut without redeem");
            IERC20(token).safeTransferFrom(msg.sender, merchant, net);
        }

        emit PaymentMade(invoiceId, msg.sender, merchant, token, gross, fee,
                         redeemToUsdt, usdtOut);
    }

    // ═════════════════════════ Admin ════════════════════════════════════
    // Bounded by the accrual counters — stray tokens sent here directly
    // are not collectible (nothing else should ever rest here anyway).

    function setPaymentSigner(address signer_) external onlyOwner {
        require(signer_ != address(0), "zero signer");
        emit PaymentSignerChanged(paymentSigner, signer_);
        paymentSigner = signer_;
    }

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
