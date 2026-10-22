// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {SignatureChecker} from "@openzeppelin/contracts/utils/cryptography/SignatureChecker.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";
import {Ownable2StepUpgradeable} from "@openzeppelin/contracts-upgradeable/access/Ownable2StepUpgradeable.sol";
import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import {EIP712Upgradeable} from "@openzeppelin/contracts-upgradeable/utils/cryptography/EIP712Upgradeable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

/**
 * ConfioMarketEscrow — buyer-protected payments for Comprar (marketplace).
 *
 * ONE shared contract for every store, not one per merchant (2026-10-22,
 * docs/designs/comprar-marketplace.md). Per-merchant clones would all run
 * the same code, so a logic bug hits every clone at once; isolation is
 * per ORDER here instead: an order's principal can only ever leave to that
 * order's merchant (minus the fee) or back to that order's buyer. No path
 * moves principal anywhere else, and the owner collects accrued fees only.
 *
 * Lifecycle (every call is a sponsored 7702 batch; the user never pays gas):
 *
 *   deposit   buyer, under a backend-signed authorization of the exact terms
 *             (orderId, buyer, merchant, token, amount, feeBps, deadline).
 *             Funded; the merchant has `shipWindow` to mark it shipped.
 *   markShipped  merchant. Shipped; auto-release opens `releaseWindow` later.
 *   confirm   buyer, any time before settlement → release.
 *   release   anyone, once a Shipped order is past releaseAt (keeper).
 *   dispute   buyer, while Funded, or Shipped before releaseAt. Freezes it.
 *   resolve   arbiter, Disputed only: release OR refund, nothing else.
 *             Unresolved after `disputeTimeout` → anyone may refund the buyer.
 *   refund    merchant, any time before settlement (cancel, return).
 *   reclaim   buyer, Funded and past shipBy — no Confío signature needed, so
 *             an unshipped order is recoverable even with the backend down.
 *
 * The fee (≤ MAX_FEE_BPS, 8% at launch) is fixed at deposit and taken only
 * on release; a refund returns the full amount. The partner revenue split
 * (Bolivia GTM) is off-chain accounting and never touches this contract.
 *
 * Blast-radius limits: a per-token max per order and max total open
 * principal (both 0 = token not accepted), and pause blocks NEW deposits
 * only — every exit (confirm, release, resolve, refund, reclaim) keeps
 * working while paused, so a pause can never strand funds.
 *
 * UUPS-upgradeable and owned by the Confío Safe (Julian's call, 2026-10-22),
 * like the cUSD+ vault: the owner can fix or extend the order flow. That
 * also means the Safe is the trust root for escrowed principal.
 *
 * Tokens: whatever the owner enables (universal cUSD at launch). A buyer
 * holding cUSD+ unwraps in the same batch before depositing; the escrow
 * holds plain, non-rebasing, fee-free tokens only — deposit asserts the
 * exact amount arrived.
 */
contract ConfioMarketEscrow is
    Ownable2StepUpgradeable,
    PausableUpgradeable,
    ReentrancyGuardTransient,
    EIP712Upgradeable,
    UUPSUpgradeable
{
    using SafeERC20 for IERC20;

    /// Hard ceiling on any order's fee, whatever the owner configures.
    uint16 public constant MAX_FEE_BPS = 1_000; // 10%

    uint64 public constant MIN_WINDOW = 1 hours;
    uint64 public constant MAX_WINDOW = 30 days;
    uint64 public constant MIN_DISPUTE_TIMEOUT = 1 days;
    uint64 public constant MAX_DISPUTE_TIMEOUT = 90 days;

    enum State {
        None,
        Funded,
        Shipped,
        Disputed,
        Released,
        Refunded
    }

    struct Order {
        address buyer;
        uint64 shipBy;
        uint16 feeBps;
        State state;
        address merchant;
        uint64 releaseAt; // set at markShipped
        uint32 releaseWindow; // snapshotted at deposit
        address token;
        uint64 disputedAt;
        uint256 amount;
    }

    struct TokenLimits {
        uint128 maxOrder; // 0 = token not accepted for new deposits
        uint128 maxOpen;
    }

    bytes32 private constant DEPOSIT_TYPEHASH = keccak256(
        "Deposit(bytes32 orderId,address buyer,address merchant,address token,uint256 amount,uint16 feeBps,uint256 deadline)"
    );

    // Storage is append-only. Every parent (OZ 5.x Ownable/Ownable2Step/
    // Pausable/EIP712/Initializable) uses ERC-7201 namespaced storage,
    // ReentrancyGuardTransient uses a transient slot and UUPSUpgradeable has
    // none, so these plain slots cannot collide with a parent.

    /// Backend authorizer for deposits (KMS). Rotate via setOrderSigner.
    address public orderSigner;
    /// Dispute resolver (backend, may equal orderSigner). Can only choose
    /// release-to-merchant or refund-to-buyer for a Disputed order.
    address public arbiter;

    uint64 public shipWindow;
    uint64 public releaseWindow;
    uint64 public disputeTimeout;

    mapping(bytes32 => Order) private _orders;
    mapping(address => TokenLimits) public tokenLimits;
    /// Principal of unsettled orders, per token.
    mapping(address => uint256) public openPrincipal;
    /// Fees from released orders, per token — the only owner-collectible funds.
    mapping(address => uint256) public accruedFees;

    event Deposited(
        bytes32 indexed orderId,
        address indexed buyer,
        address indexed merchant,
        address token,
        uint256 amount,
        uint16 feeBps,
        uint64 shipBy
    );
    event Shipped(bytes32 indexed orderId, uint64 releaseAt);
    event Disputed(bytes32 indexed orderId);
    event Released(bytes32 indexed orderId, address indexed merchant, uint256 net, uint256 fee, address by);
    event Refunded(bytes32 indexed orderId, address indexed buyer, uint256 amount, address by);
    event FeesCollected(address indexed token, address indexed to, uint256 amount);
    event OrderSignerChanged(address indexed previous, address indexed current);
    event ArbiterChanged(address indexed previous, address indexed current);
    event WindowsChanged(uint64 shipWindow, uint64 releaseWindow, uint64 disputeTimeout);
    event TokenLimitsChanged(address indexed token, uint128 maxOrder, uint128 maxOpen);
    event StrayTokensSwept(address indexed token, address indexed to, uint256 amount);

    error ZeroAddress();
    error AuthorizationExpired();
    error BadAuthorization();
    error OrderExists();
    error TokenNotAccepted();
    error OrderTooLarge();
    error OpenCapExceeded();
    error BadMerchant();
    error FeeTooHigh();
    error AmountTooSmall();
    error AmountMismatch();
    error WrongState(State actual);
    error NotBuyer();
    error NotMerchant();
    error NotArbiter();
    error TooEarly(uint256 at);
    error TooLate();
    error BadWindow();
    error NothingToCollect();

    constructor() {
        _disableInitializers();
    }

    function initialize(
        address owner_,
        address orderSigner_,
        address arbiter_,
        uint64 shipWindow_,
        uint64 releaseWindow_,
        uint64 disputeTimeout_
    ) external initializer {
        if (owner_ == address(0) || orderSigner_ == address(0) || arbiter_ == address(0)) revert ZeroAddress();
        __Ownable_init(owner_);
        __Ownable2Step_init();
        __Pausable_init();
        __EIP712_init("ConfioMarketEscrow", "1");
        orderSigner = orderSigner_;
        arbiter = arbiter_;
        emit OrderSignerChanged(address(0), orderSigner_);
        emit ArbiterChanged(address(0), arbiter_);
        _setWindows(shipWindow_, releaseWindow_, disputeTimeout_);
    }

    // ═════════════════════════ Views ════════════════════════════════════

    function getOrder(bytes32 orderId) external view returns (Order memory) {
        return _orders[orderId];
    }

    /// ceil(amount * feeBps / 10000), the same rounding as ConfioPayContract.
    function feeFor(uint256 amount, uint16 feeBps) public pure returns (uint256) {
        return Math.mulDiv(amount, feeBps, 10_000, Math.Rounding.Ceil);
    }

    /// The EIP-712 digest the backend signs to authorize one deposit.
    function depositDigest(
        bytes32 orderId,
        address buyer,
        address merchant,
        address token,
        uint256 amount,
        uint16 feeBps,
        uint256 deadline
    ) public view returns (bytes32) {
        return _hashTypedDataV4(
            keccak256(abi.encode(DEPOSIT_TYPEHASH, orderId, buyer, merchant, token, amount, feeBps, deadline))
        );
    }

    // ═════════════════════════ Order flow ═══════════════════════════════

    /// Called BY the buyer (their EOA, via the sponsored 7702 batch that
    /// approved `amount` one call earlier).
    function deposit(
        bytes32 orderId,
        address merchant,
        address token,
        uint256 amount,
        uint16 feeBps,
        uint256 deadline,
        bytes calldata authSig
    ) external nonReentrant whenNotPaused {
        if (block.timestamp > deadline) revert AuthorizationExpired();
        if (_orders[orderId].state != State.None) revert OrderExists();
        if (merchant == address(0) || merchant == address(this) || merchant == msg.sender) revert BadMerchant();
        if (feeBps > MAX_FEE_BPS) revert FeeTooHigh();

        TokenLimits memory limits = tokenLimits[token];
        if (limits.maxOrder == 0) revert TokenNotAccepted();
        if (amount > limits.maxOrder) revert OrderTooLarge();
        if (openPrincipal[token] + amount > limits.maxOpen) revert OpenCapExceeded();
        // The merchant must receive something on release.
        if (amount <= feeFor(amount, feeBps)) revert AmountTooSmall();

        bytes32 digest = depositDigest(orderId, msg.sender, merchant, token, amount, feeBps, deadline);
        if (!SignatureChecker.isValidSignatureNow(orderSigner, digest, authSig)) revert BadAuthorization();

        uint64 shipBy = uint64(block.timestamp) + shipWindow;
        _orders[orderId] = Order({
            buyer: msg.sender,
            shipBy: shipBy,
            feeBps: feeBps,
            state: State.Funded,
            merchant: merchant,
            releaseAt: 0,
            releaseWindow: uint32(releaseWindow),
            token: token,
            disputedAt: 0,
            amount: amount
        });
        openPrincipal[token] += amount;

        uint256 before = IERC20(token).balanceOf(address(this));
        IERC20(token).safeTransferFrom(msg.sender, address(this), amount);
        if (IERC20(token).balanceOf(address(this)) - before != amount) revert AmountMismatch();

        emit Deposited(orderId, msg.sender, merchant, token, amount, feeBps, shipBy);
    }

    function markShipped(bytes32 orderId) external {
        Order storage o = _orders[orderId];
        if (msg.sender != o.merchant) revert NotMerchant();
        if (o.state != State.Funded) revert WrongState(o.state);
        // Past shipBy the buyer's reclaim right is live; a late "shipped"
        // must not be able to front-run it. The buyer can still confirm.
        if (block.timestamp > o.shipBy) revert TooLate();
        uint64 releaseAt = uint64(block.timestamp) + o.releaseWindow;
        o.state = State.Shipped;
        o.releaseAt = releaseAt;
        emit Shipped(orderId, releaseAt);
    }

    /// Buyer says it arrived (or withdraws a dispute by accepting it).
    function confirm(bytes32 orderId) external nonReentrant {
        Order storage o = _orders[orderId];
        if (msg.sender != o.buyer) revert NotBuyer();
        _requireOpen(o);
        _release(orderId, o);
    }

    /// Auto-release: anyone (the keeper) once a Shipped order is past releaseAt.
    function release(bytes32 orderId) external nonReentrant {
        Order storage o = _orders[orderId];
        if (o.state != State.Shipped) revert WrongState(o.state);
        if (block.timestamp < o.releaseAt) revert TooEarly(o.releaseAt);
        _release(orderId, o);
    }

    function dispute(bytes32 orderId) external {
        Order storage o = _orders[orderId];
        if (msg.sender != o.buyer) revert NotBuyer();
        if (o.state == State.Shipped) {
            if (block.timestamp >= o.releaseAt) revert TooLate();
        } else if (o.state != State.Funded) {
            revert WrongState(o.state);
        }
        o.state = State.Disputed;
        o.disputedAt = uint64(block.timestamp);
        emit Disputed(orderId);
    }

    function resolve(bytes32 orderId, bool toMerchant) external nonReentrant {
        if (msg.sender != arbiter) revert NotArbiter();
        Order storage o = _orders[orderId];
        if (o.state != State.Disputed) revert WrongState(o.state);
        if (toMerchant) _release(orderId, o);
        else _refund(orderId, o);
    }

    /// An arbiter that never answers must not freeze funds forever: past the
    /// timeout an unresolved dispute refunds the buyer, callable by anyone.
    function refundExpiredDispute(bytes32 orderId) external nonReentrant {
        Order storage o = _orders[orderId];
        if (o.state != State.Disputed) revert WrongState(o.state);
        uint256 at = uint256(o.disputedAt) + disputeTimeout;
        if (block.timestamp < at) revert TooEarly(at);
        _refund(orderId, o);
    }

    /// Merchant gives the money back: cancel before shipping, or a return.
    function refund(bytes32 orderId) external nonReentrant {
        Order storage o = _orders[orderId];
        if (msg.sender != o.merchant) revert NotMerchant();
        _requireOpen(o);
        _refund(orderId, o);
    }

    /// Buyer takes back an order the merchant never marked shipped.
    function reclaim(bytes32 orderId) external nonReentrant {
        Order storage o = _orders[orderId];
        if (msg.sender != o.buyer) revert NotBuyer();
        if (o.state != State.Funded) revert WrongState(o.state);
        if (block.timestamp <= o.shipBy) revert TooEarly(uint256(o.shipBy) + 1);
        _refund(orderId, o);
    }

    // ═════════════════════════ Internals ════════════════════════════════

    function _requireOpen(Order storage o) private view {
        State s = o.state;
        if (s != State.Funded && s != State.Shipped && s != State.Disputed) revert WrongState(s);
    }

    function _release(bytes32 orderId, Order storage o) private {
        uint256 amount = o.amount;
        address token = o.token;
        address merchant = o.merchant;
        uint256 fee = feeFor(amount, o.feeBps);
        o.state = State.Released;
        openPrincipal[token] -= amount;
        accruedFees[token] += fee;
        IERC20(token).safeTransfer(merchant, amount - fee);
        emit Released(orderId, merchant, amount - fee, fee, msg.sender);
    }

    function _refund(bytes32 orderId, Order storage o) private {
        uint256 amount = o.amount;
        address token = o.token;
        address buyer = o.buyer;
        o.state = State.Refunded;
        openPrincipal[token] -= amount;
        IERC20(token).safeTransfer(buyer, amount);
        emit Refunded(orderId, buyer, amount, msg.sender);
    }

    function _setWindows(uint64 ship, uint64 release_, uint64 disputeTimeout_) private {
        if (ship < MIN_WINDOW || ship > MAX_WINDOW) revert BadWindow();
        if (release_ < MIN_WINDOW || release_ > MAX_WINDOW) revert BadWindow();
        if (disputeTimeout_ < MIN_DISPUTE_TIMEOUT || disputeTimeout_ > MAX_DISPUTE_TIMEOUT) revert BadWindow();
        shipWindow = ship;
        releaseWindow = release_;
        disputeTimeout = disputeTimeout_;
        emit WindowsChanged(ship, release_, disputeTimeout_);
    }

    // ═════════════════════════ Admin (Safe) ═════════════════════════════

    function setOrderSigner(address signer_) external onlyOwner {
        if (signer_ == address(0)) revert ZeroAddress();
        emit OrderSignerChanged(orderSigner, signer_);
        orderSigner = signer_;
    }

    function setArbiter(address arbiter_) external onlyOwner {
        if (arbiter_ == address(0)) revert ZeroAddress();
        emit ArbiterChanged(arbiter, arbiter_);
        arbiter = arbiter_;
    }

    /// Applies to orders deposited afterwards (ship/release windows are
    /// snapshotted per order); the dispute timeout applies to open disputes.
    function setWindows(uint64 ship, uint64 release_, uint64 disputeTimeout_) external onlyOwner {
        _setWindows(ship, release_, disputeTimeout_);
    }

    /// maxOrder == 0 stops new deposits in `token`; open orders still settle.
    function setTokenLimits(address token, uint128 maxOrder, uint128 maxOpen) external onlyOwner {
        if (token == address(0)) revert ZeroAddress();
        tokenLimits[token] = TokenLimits(maxOrder, maxOpen);
        emit TokenLimitsChanged(token, maxOrder, maxOpen);
    }

    function collectFees(address token, address to, uint256 amount) external onlyOwner nonReentrant {
        if (to == address(0)) revert ZeroAddress();
        if (amount == 0 || amount > accruedFees[token]) revert NothingToCollect();
        accruedFees[token] -= amount;
        IERC20(token).safeTransfer(to, amount);
        emit FeesCollected(token, to, amount);
    }

    /// Tokens sent here directly (not via deposit). Never reaches principal
    /// or fees: only the balance above openPrincipal + accruedFees.
    function sweepStray(address token, address to) external onlyOwner nonReentrant {
        if (to == address(0)) revert ZeroAddress();
        uint256 held = IERC20(token).balanceOf(address(this));
        uint256 owed = openPrincipal[token] + accruedFees[token];
        if (held <= owed) revert NothingToCollect();
        IERC20(token).safeTransfer(to, held - owed);
        emit StrayTokensSwept(token, to, held - owed);
    }

    /// Blocks NEW deposits only; every exit keeps working.
    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    function _authorizeUpgrade(address) internal override onlyOwner {}
}
