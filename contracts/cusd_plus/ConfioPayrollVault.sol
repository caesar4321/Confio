// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ConfioPayrollVault — per-business cUSD+ escrow with delegate-signed payouts.
 *
 * WHY A CONTRACT (and not a 7702 batch like send/pay): under EIP-7702 the
 * only key that can authorize calls FROM the business EOA is the business
 * key itself — an employee ("delegate") granted payroll rights in the app
 * has no way to sign for the business address. So the delegate model must
 * live on-chain: the business parks cUSD+ shares here, allowlists delegate
 * addresses, and each payout is executed against a delegate's EIP-712
 * signature over the exact payout — the caller (Confío's sponsor, paying
 * gas) is untrusted plumbing.
 *
 * DESIGN RULES (house invariants):
 *  - Escrow is cUSD+ SHARES, not USDT: yield keeps accruing to parked
 *    payroll float (share price rises; share count is what's accounted).
 *  - `withdraw` is NEVER pausable. Pause covers deposits and payouts only.
 *    Stricter than CusdPlusVault, where `redeemToUsdt` IS pause-gated on
 *    purpose: that vault carries oracle/backing risk worth a circuit
 *    breaker, while parked payroll shares carry none — there is no
 *    scenario where detaining a business's own escrow protects anyone.
 *  - Payout execution is permissionless: the signature IS the
 *    authorization, so a griefing caller can only do exactly what the
 *    business already approved.
 *  - Replay: one payout per (business, itemId), forever. Cancellation of a
 *    signed-but-unexecuted payout = business consumes the itemId first via
 *    `cancelItem`.
 *  - Non-upgradeable, no owner power over escrowed funds: owner can only
 *    rotate the fee recipient and pause new activity. Redeploy to change
 *    anything else.
 *
 * Recipient rails mirror send/bsc_flow.py's A/B split:
 *  - eligible recipient  → vault.transfer(recipient, netShares)  (stays cUSD+)
 *  - ineligible/external → CusdPlusVault.redeemToUsdt(netShares, minUsdtOut,
 *    recipient) — atomic burn → Ondo IM redeem → USDT lands directly at the
 *    recipient, no custody hop.
 * Fee shares STAY IN THIS CONTRACT (Julian, 07-31: fees sit in each
 * contract — accounting reads straight off the chain): `accruedFeeShares`
 * accumulates them and the owner (Safe) collects via collectFees. The
 * standing invariant: CUSD_PLUS.balanceOf(this) == Σ escrowShares +
 * accruedFeeShares.
 */

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

interface ICusdPlusVault is IERC20 {
    function redeemToUsdt(uint256 shares, uint256 minUsdtOut, address to)
        external
        returns (uint256 usdtOut);

    /// Per-address freeze on the underlying token.
    function frozen(address account) external view returns (bool);
}

contract ConfioPayrollVault is Ownable2Step, Pausable, ReentrancyGuardTransient {
    using SafeERC20 for IERC20;

    // ═════════════════════════ EIP-712 ══════════════════════════════════

    bytes32 private constant DOMAIN_TYPEHASH = keccak256(
        "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    );
    bytes32 private constant NAME_HASH = keccak256(bytes("ConfioPayrollVault"));
    bytes32 private constant VERSION_HASH = keccak256(bytes("1"));
    bytes32 public constant PAYOUT_TYPEHASH = keccak256(
        "Payout(address business,address recipient,uint256 netShares,uint256 feeShares,bool redeemToUsdt,uint256 minUsdtOut,bytes32 itemId,uint256 deadline)"
    );

    struct Payout {
        address business;     // whose escrow is debited; domain of the allowlist
        address recipient;    // employee wallet
        uint256 netShares;    // cUSD+ shares to the recipient (or burned for USDT)
        uint256 feeShares;    // cUSD+ shares to the fee recipient (may be 0)
        bool redeemToUsdt;    // false: transfer shares · true: atomic USDT exit
        uint256 minUsdtOut;   // slippage floor for the redeem branch (else 0)
        bytes32 itemId;       // server-derived payroll-item id; replay key
        uint256 deadline;     // unix seconds; signature dies after this
    }

    // ═════════════════════════ State ════════════════════════════════════

    ICusdPlusVault public immutable CUSD_PLUS;

    /// Payout fees accrued in-contract, collectible by the owner (Safe).
    uint256 public accruedFeeShares;
    /// Σ escrowShares — lets the invariant be CHECKED on-chain, and bounds
    /// what `rescueSurplus` may move (audit 2026-07-31, [P3]: shares sent
    /// here by direct transfer instead of `deposit` were unrecoverable).
    uint256 public totalEscrowShares;
    /// cUSD+ shares parked per business.
    mapping(address => uint256) public escrowShares;
    /// business => delegate => may sign payouts.
    mapping(address => mapping(address => bool)) public isDelegate;
    /// keccak256(business, itemId) => consumed (paid or cancelled).
    mapping(bytes32 => bool) public itemUsed;

    event Deposited(address indexed business, uint256 shares);
    event Withdrawn(address indexed business, address indexed to, uint256 shares);
    event DelegateSet(address indexed business, address indexed delegate, bool allowed);
    event ItemCancelled(address indexed business, bytes32 indexed itemId);
    event PaidOut(
        address indexed business,
        address indexed recipient,
        bytes32 indexed itemId,
        address signer,
        uint256 netShares,
        uint256 feeShares,
        bool redeemedToUsdt,
        uint256 usdtOut
    );
    event FeesCollected(address indexed to, uint256 shares);
    event SurplusRescued(address indexed to, uint256 shares);

    constructor(address cusdPlus, address owner_) Ownable(owner_) {
        require(cusdPlus != address(0), "zero address");
        CUSD_PLUS = ICusdPlusVault(cusdPlus);
    }

    // ═════════════════════════ Business ops ═════════════════════════════
    // All three are called BY the business EOA (via its 7702 sponsored
    // batch: approve + deposit, or a bare call) — msg.sender is the
    // authorization.

    function deposit(uint256 shares) external nonReentrant whenNotPaused {
        require(shares > 0, "zero shares");
        IERC20(address(CUSD_PLUS)).safeTransferFrom(msg.sender, address(this), shares);
        escrowShares[msg.sender] += shares;
        totalEscrowShares += shares;
        emit Deposited(msg.sender, shares);
    }

    /// NEVER pausable (exits are never gated) — but a business frozen on
    /// the underlying token stays frozen here too (audit 2026-07-31, [P2]:
    /// escrow is held under THIS contract's address, so the token's own
    /// freeze check sees an unfrozen sender and would let a frozen
    /// business exit through payroll).
    function withdraw(uint256 shares, address to) external nonReentrant {
        require(shares > 0, "zero shares");
        require(to != address(0), "zero recipient");
        require(!CUSD_PLUS.frozen(msg.sender), "business frozen");
        uint256 held = escrowShares[msg.sender];
        require(shares <= held, "insufficient escrow");
        escrowShares[msg.sender] = held - shares;
        totalEscrowShares -= shares;
        IERC20(address(CUSD_PLUS)).safeTransfer(to, shares);
        emit Withdrawn(msg.sender, to, shares);
    }

    function setDelegate(address delegate, bool allowed) external {
        require(delegate != address(0), "zero delegate");
        isDelegate[msg.sender][delegate] = allowed;
        emit DelegateSet(msg.sender, delegate, allowed);
    }

    /// Burn an itemId before anyone executes it — the only way to revoke a
    /// signature that has already left the building.
    function cancelItem(bytes32 itemId) external {
        bytes32 key = _itemKey(msg.sender, itemId);
        require(!itemUsed[key], "item consumed");
        itemUsed[key] = true;
        emit ItemCancelled(msg.sender, itemId);
    }

    // ═════════════════════════ Payout ═══════════════════════════════════

    /// Anyone may call (in practice Confío's sponsor, paying gas). The
    /// EIP-712 signature by the business or an allowlisted delegate is the
    /// sole authorization; every field the money movement depends on is
    /// under that signature.
    function payout(Payout calldata p, bytes calldata signature)
        external
        nonReentrant
        whenNotPaused
        returns (uint256 usdtOut)
    {
        require(p.recipient != address(0), "zero recipient");
        require(p.netShares > 0, "zero net");
        require(block.timestamp <= p.deadline, "expired");

        bytes32 key = _itemKey(p.business, p.itemId);
        require(!itemUsed[key], "item consumed");
        itemUsed[key] = true;

        address signer = ECDSA.recover(payoutDigest(p), signature);
        require(signer == p.business || isDelegate[p.business][signer], "bad signer");
        // Same freeze passthrough as withdraw: escrow must not be an
        // end-run around a token-level freeze of the paying business.
        require(!CUSD_PLUS.frozen(p.business), "business frozen");

        uint256 total = p.netShares + p.feeShares;
        uint256 held = escrowShares[p.business];
        require(total <= held, "insufficient escrow");
        escrowShares[p.business] = held - total;
        totalEscrowShares -= total;

        if (p.feeShares > 0) {
            // Fees never leave in the payout tx — they accrue here and the
            // owner collects (yield keeps accruing to them meanwhile too).
            accruedFeeShares += p.feeShares;
        }
        if (p.redeemToUsdt) {
            // Burns OUR shares; USDT lands directly at the recipient.
            usdtOut = CUSD_PLUS.redeemToUsdt(p.netShares, p.minUsdtOut, p.recipient);
        } else {
            IERC20(address(CUSD_PLUS)).safeTransfer(p.recipient, p.netShares);
        }
        emit PaidOut(
            p.business, p.recipient, p.itemId, signer,
            p.netShares, p.feeShares, p.redeemToUsdt, usdtOut
        );
    }

    /// Exposed so the backend and the signing client can assert digest
    /// parity against the chain (three-way vector pattern).
    function payoutDigest(Payout calldata p) public view returns (bytes32) {
        bytes32 domainSeparator = keccak256(
            abi.encode(DOMAIN_TYPEHASH, NAME_HASH, VERSION_HASH, block.chainid, address(this))
        );
        bytes32 structHash = keccak256(
            abi.encode(
                PAYOUT_TYPEHASH,
                p.business,
                p.recipient,
                p.netShares,
                p.feeShares,
                p.redeemToUsdt,
                p.minUsdtOut,
                p.itemId,
                p.deadline
            )
        );
        return keccak256(abi.encodePacked("\x19\x01", domainSeparator, structHash));
    }

    function _itemKey(address business, bytes32 itemId) private pure returns (bytes32) {
        return keccak256(abi.encodePacked(business, itemId));
    }

    // ═════════════════════════ Admin ════════════════════════════════════
    // Owner (the Safe) can collect ACCRUED FEES ONLY and freeze new
    // activity; it has no path to escrowed shares — collectFees is bounded
    // by the accrual counter, so escrow can never be drained through it.

    function collectFees(address to, uint256 shares) external onlyOwner nonReentrant {
        require(to != address(0), "zero recipient");
        require(shares > 0 && shares <= accruedFeeShares, "exceeds accrued fees");
        accruedFeeShares -= shares;
        IERC20(address(CUSD_PLUS)).safeTransfer(to, shares);
        emit FeesCollected(to, shares);
    }

    /// Shares that reached this contract WITHOUT going through `deposit`
    /// (a mistaken direct transfer) would otherwise be stranded forever.
    /// Bounded by the provable surplus, so escrow and accrued fees are
    /// untouchable by construction, not by trust.
    function surplusShares() public view returns (uint256) {
        uint256 balance = CUSD_PLUS.balanceOf(address(this));
        uint256 owed = totalEscrowShares + accruedFeeShares;
        return balance > owed ? balance - owed : 0;
    }

    function rescueSurplus(address to, uint256 shares) external onlyOwner nonReentrant {
        require(to != address(0), "zero recipient");
        require(shares > 0 && shares <= surplusShares(), "exceeds surplus");
        IERC20(address(CUSD_PLUS)).safeTransfer(to, shares);
        emit SurplusRescued(to, shares);
    }

    function pause() external onlyOwner { _pause(); }
    function unpause() external onlyOwner { _unpause(); }
}
