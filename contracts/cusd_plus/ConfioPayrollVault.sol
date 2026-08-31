// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ConfioPayrollVault — per-business payroll escrow with delegate-signed payouts.
 *
 * WHY A CONTRACT (and not a 7702 batch like send/pay): under EIP-7702 the
 * only key that can authorize calls FROM the business EOA is the business
 * key itself — an employee ("delegate") granted payroll rights in the app
 * has no way to sign for the business address. So the delegate model must
 * live on-chain: the business parks payroll float here, allowlists delegate
 * addresses, and each payout is executed against a delegate's EIP-712
 * signature over the exact payout — the caller (Confío's sponsor, paying
 * gas) is untrusted plumbing.
 *
 * THREE ESCROW ASSETS. cUSD+ shares and universal cUSD are the active pools;
 * the old raw-USDT pool is retained so a replacement deployment can migrate
 * or drain previously parked payroll float without rewriting history. v1
 * escrowed cUSD+ SHARES only, which silently made Nómina an
 * ELIGIBLE-EMPLOYER-ONLY product: an Ondo-blocked business could not mint
 * shares and `deposit` took no non-yield Confío dollar —
 * so `fundableBalance` read 0 and funding failed "insufficient balance"
 * while the business plainly had money. v1 already paid INELIGIBLE employees
 * (atomic redeemToUsdt inside `payout`); nothing handled an ineligible
 * EMPLOYER. Now each business parks cUSD+ or cUSD — or both, which is the
 * normal state for anyone whose eligibility changed mid-life — and each
 * payout item names the asset it draws from.
 *
 * DESIGN RULES (house invariants):
 *  - Accounting is PER ASSET and never fungible across the pools. cUSD+ is
 *    accounted in SHARES (yield keeps accruing to parked float: share price
 *    rises, share count is what's stored); cUSD and legacy USDT are accounted
 *    in token units and earn NOTHING. That asymmetry is inherent — an
 *    employer who cannot legally hold the yield-bearing asset cannot be
 *    given yield by moving it into escrow.
 *  - `withdraw` is NEVER pausable, for either asset. Pause covers deposits
 *    and payouts only. Stricter than CusdPlusVault, where `redeemToUsdt` IS
 *    pause-gated on purpose: that vault carries oracle/backing risk worth a
 *    circuit breaker, while parked payroll float carries none — there is no
 *    scenario where detaining a business's own escrow protects anyone.
 *  - Payout execution is permissionless: the signature IS the
 *    authorization, so a griefing caller can only do exactly what the
 *    business already approved.
 *  - Replay: one payout per (business, itemId), forever — across BOTH
 *    assets, so re-signing the same item against the other pool is not a
 *    second payment. Cancellation of a signed-but-unexecuted payout =
 *    business consumes the itemId first via `cancelItem`.
 *  - Non-upgradeable, no owner power over escrowed funds: owner can only
 *    rotate the fee recipient and pause new activity. Redeploy to change
 *    anything else.
 *
 * Recipient rails mirror send/bsc_flow.py's A/B split. From cUSD+ escrow:
 *  - eligible recipient  → vault.transfer(recipient, netAmount)  (stays cUSD+)
 *  - ineligible recipient → CusdPlusVault.unwrapToCusd(netAmount, minUsdtOut,
 *    recipient) — atomic, sponsor-authorized internal conversion to cUSD,
 *    with no USDT-perimeter fee.
 * From cUSD escrow there is one rail: a plain cUSD transfer. The sponsor can
 * wrap an eligible recipient later for free. Legacy USDT escrow likewise
 * transfers USDT and exists only for migration/draining.
 *
 * Fee amounts STAY IN THIS CONTRACT (Julian, 07-31: fees sit in each
 * contract — accounting reads straight off the chain): `accruedFee*`
 * accumulates them per asset and the owner (Safe) collects via collectFees.
 * The standing invariants, one per asset:
 *   CUSD_PLUS.balanceOf(this) == Σ escrowShares + accruedFeeShares
 *   USDT.balanceOf(this)      == Σ escrowUsdt   + accruedFeeUsdt
 *   CUSD.balanceOf(this)      == Σ escrowCusd   + accruedFeeCusd
 */

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

interface ICusdPlusVault is IERC20 {
    function redeemToUsdt(uint256 shares, uint256 minUsdtOut, address to) external returns (uint256 usdtOut);

    function unwrapToCusd(uint256 shares, uint256 minCusdOut, address to) external returns (uint256 cusdOut);

    /// Per-address freeze on the underlying token.
    function frozen(address account) external view returns (bool);

    /// The USDT this vault redeems into. Read at construction so payroll's
    /// escrow token and the redeem branch's payout token cannot diverge.
    function USDT() external view returns (IERC20);

    /// Universal cUSD configured in the upgraded savings vault. Payroll's
    /// direct cUSD pool must be the same token unwrapToCusd actually emits.
    function CUSD() external view returns (address);
}

contract ConfioPayrollVault is Ownable2Step, Pausable, ReentrancyGuardTransient {
    using SafeERC20 for IERC20;

    /// Which pool an operation touches. Solidity rejects out-of-range enum
    /// values at the ABI boundary, so an unknown asset reverts rather than
    /// defaulting to one of them.
    enum Asset {
        CusdPlus, // 0 — shares; accrues yield while parked
        Usdt, // 1 — legacy raw-token pool; retained for draining
        Cusd // 2 — universal payment dollars; new non-yield pool
    }

    // ═════════════════════════ EIP-712 ══════════════════════════════════

    bytes32 private constant DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    bytes32 private constant NAME_HASH = keccak256(bytes("ConfioPayrollVault"));
    /// "2": the Payout struct gained `asset` and renamed shares→amount. The
    /// domain already separates deployments by verifyingContract, but a
    /// version that still said "1" would let a v1 vector look reviewable
    /// against v2 in the three-way parity check.
    bytes32 private constant VERSION_HASH = keccak256(bytes("2"));
    bytes32 public constant PAYOUT_TYPEHASH = keccak256(
        "Payout(address business,address recipient,uint8 asset,uint256 netAmount,uint256 feeAmount,bool redeemToUsdt,uint256 minUsdtOut,bytes32 itemId,uint256 deadline)"
    );

    struct Payout {
        address business; // whose escrow is debited; domain of the allowlist
        address recipient; // employee wallet
        Asset asset; // which pool pays — cUSD+, legacy USDT, or cUSD
        uint256 netAmount; // to the recipient, in the asset's own units
        uint256 feeAmount; // to the fee accrual, same units (may be 0)
        bool redeemToUsdt; // legacy name: cUSD+ -> cUSD internal routing
        uint256 minUsdtOut; // legacy name: minimum cUSD out (else 0)
        bytes32 itemId; // server-derived payroll-item id; replay key
        uint256 deadline; // unix seconds; signature dies after this
    }

    // ═════════════════════════ State ════════════════════════════════════

    ICusdPlusVault public immutable CUSD_PLUS;
    IERC20 public immutable USDT;
    IERC20 public immutable CUSD;

    /// Payout fees accrued in-contract, collectible by the owner (Safe).
    uint256 public accruedFeeShares;
    uint256 public accruedFeeUsdt;
    uint256 public accruedFeeCusd;
    /// Σ escrow per asset — lets each invariant be CHECKED on-chain, and
    /// bounds what `rescueSurplus` may move (audit 2026-07-31, [P3]: value
    /// sent here by direct transfer instead of `deposit` was unrecoverable).
    uint256 public totalEscrowShares;
    uint256 public totalEscrowUsdt;
    uint256 public totalEscrowCusd;
    /// Parked per business, per asset. Two mappings rather than one nested
    /// one: each asset's invariant then reads as its own line, and the
    /// getters stay the shape the server already indexes.
    mapping(address => uint256) public escrowShares;
    mapping(address => uint256) public escrowUsdt;
    mapping(address => uint256) public escrowCusd;
    /// business => delegate => may sign payouts. Asset-independent on
    /// purpose: delegation is "may pay this business's payroll", not "may
    /// pay it in one currency".
    mapping(address => mapping(address => bool)) public isDelegate;
    /// keccak256(business, itemId) => consumed (paid or cancelled).
    mapping(bytes32 => bool) public itemUsed;

    event Deposited(address indexed business, Asset indexed asset, uint256 amount);
    event Withdrawn(address indexed business, address indexed to, Asset indexed asset, uint256 amount);
    event DelegateSet(address indexed business, address indexed delegate, bool allowed);
    event ItemCancelled(address indexed business, bytes32 indexed itemId);
    event PaidOut(
        address indexed business,
        address indexed recipient,
        bytes32 indexed itemId,
        address signer,
        Asset asset,
        uint256 netAmount,
        uint256 feeAmount,
        bool redeemedToUsdt,
        uint256 usdtOut
    );
    event FeesCollected(address indexed to, Asset indexed asset, uint256 amount);
    event SurplusRescued(address indexed to, Asset indexed asset, uint256 amount);

    constructor(address cusdPlus, address cusd, address owner_) Ownable(owner_) {
        require(cusdPlus != address(0) && cusd != address(0), "zero address");
        require(cusdPlus.code.length > 0 && cusd.code.length > 0, "not contract");
        CUSD_PLUS = ICusdPlusVault(cusdPlus);
        require(ICusdPlusVault(cusdPlus).CUSD() == cusd, "cusd mismatch");
        CUSD = IERC20(cusd);
        IERC20 usdt = ICusdPlusVault(cusdPlus).USDT();
        require(address(usdt) != address(0), "zero usdt");
        USDT = usdt;
    }

    // ═════════════════════════ Business ops ═════════════════════════════
    // All are called BY the business EOA (via its 7702 sponsored batch:
    // approve + deposit, or a bare call) — msg.sender is the authorization.

    /// Freeze-gated like withdraw and payout (audit 2026-08-02, [P2]): those
    /// two reject a frozen business, so without this a frozen business could
    /// keep ADDING to an escrow it cannot withdraw from or pay out of —
    /// deepening a position it has no exit from. The freeze is a statement
    /// about the BUSINESS, so it covers both pools and every direction.
    function deposit(Asset asset, uint256 amount) external nonReentrant whenNotPaused {
        require(amount > 0, "zero amount");
        require(!CUSD_PLUS.frozen(msg.sender), "business frozen");
        _token(asset).safeTransferFrom(msg.sender, address(this), amount);
        if (asset == Asset.CusdPlus) {
            escrowShares[msg.sender] += amount;
            totalEscrowShares += amount;
        } else if (asset == Asset.Usdt) {
            escrowUsdt[msg.sender] += amount;
            totalEscrowUsdt += amount;
        } else {
            escrowCusd[msg.sender] += amount;
            totalEscrowCusd += amount;
        }
        emit Deposited(msg.sender, asset, amount);
    }

    /// NEVER pausable (exits are never gated) — but a business frozen on
    /// the cUSD+ token stays frozen here too, for BOTH assets (audit
    /// 2026-07-31, [P2]: escrow is held under THIS contract's address, so
    /// the token's own freeze check sees an unfrozen sender and would let a
    /// frozen business exit through payroll). The USDT leg is covered by
    /// the same rule deliberately: the freeze is a statement about the
    /// BUSINESS, and an escrow that honoured it in one currency only would
    /// be an end-run with an extra step.
    function withdraw(Asset asset, uint256 amount, address to) external nonReentrant {
        require(amount > 0, "zero amount");
        require(to != address(0), "zero recipient");
        require(!CUSD_PLUS.frozen(msg.sender), "business frozen");
        _debit(msg.sender, asset, amount);
        _token(asset).safeTransfer(to, amount);
        emit Withdrawn(msg.sender, to, asset, amount);
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
    /// under that signature — including which pool it drains.
    function payout(Payout calldata p, bytes calldata signature)
        external
        nonReentrant
        whenNotPaused
        returns (uint256 routedOut)
    {
        require(p.recipient != address(0), "zero recipient");
        require(p.netAmount > 0, "zero net");
        require(block.timestamp <= p.deadline, "expired");
        if (p.asset != Asset.CusdPlus) {
            // The compatibility rail burns cUSD+ shares; there is nothing to
            // burn for cUSD/legacy USDT. Both fields are pinned so
            // no signed-but-inert value can drift between the server's
            // vector, the signer's, and the chain's.
            require(!p.redeemToUsdt, "asset cannot redeem");
            require(p.minUsdtOut == 0, "min out unused");
        }

        // Consumed BEFORE any external call and shared across assets: one
        // payroll item is one payment, whichever pool it names.
        bytes32 key = _itemKey(p.business, p.itemId);
        require(!itemUsed[key], "item consumed");
        itemUsed[key] = true;

        address signer = ECDSA.recover(payoutDigest(p), signature);
        require(signer == p.business || isDelegate[p.business][signer], "bad signer");
        // Same freeze passthrough as withdraw: escrow must not be an
        // end-run around a token-level freeze of the paying business.
        require(!CUSD_PLUS.frozen(p.business), "business frozen");

        _debit(p.business, p.asset, p.netAmount + p.feeAmount);

        if (p.feeAmount > 0) {
            // Fees never leave in the payout tx — they accrue here and the
            // owner collects (cUSD+ fees keep accruing yield meanwhile too).
            if (p.asset == Asset.CusdPlus) {
                accruedFeeShares += p.feeAmount;
            } else if (p.asset == Asset.Usdt) {
                accruedFeeUsdt += p.feeAmount;
            } else {
                accruedFeeCusd += p.feeAmount;
            }
        }
        if (p.redeemToUsdt) {
            // Legacy ABI name, current semantics: burn OUR shares and route
            // fee-free universal cUSD directly to the ineligible recipient.
            // cUSD+ is upgradeable and its cUSD endpoint can be rotated. A
            // Payroll deployment is pinned to one cUSD pool, so fail closed
            // until Payroll is redeployed/coordinated with that rotation.
            require(CUSD_PLUS.CUSD() == address(CUSD), "cusd mismatch");
            uint256 recipientBefore = CUSD.balanceOf(p.recipient);
            uint256 sharesBefore = IERC20(address(CUSD_PLUS)).balanceOf(address(this));
            routedOut = CUSD_PLUS.unwrapToCusd(p.netAmount, p.minUsdtOut, p.recipient);
            require(CUSD.balanceOf(p.recipient) - recipientBefore >= p.minUsdtOut, "recipient not paid");
            require(
                sharesBefore - IERC20(address(CUSD_PLUS)).balanceOf(address(this)) == p.netAmount, "shares not consumed"
            );
        } else {
            _token(p.asset).safeTransfer(p.recipient, p.netAmount);
        }
        emit PaidOut(
            p.business, p.recipient, p.itemId, signer, p.asset, p.netAmount, p.feeAmount, p.redeemToUsdt, routedOut
        );
    }

    /// Exposed so the backend and the signing client can assert digest
    /// parity against the chain (three-way vector pattern).
    function payoutDigest(Payout calldata p) public view returns (bytes32) {
        bytes32 domainSeparator =
            keccak256(abi.encode(DOMAIN_TYPEHASH, NAME_HASH, VERSION_HASH, block.chainid, address(this)));
        bytes32 structHash = keccak256(
            abi.encode(
                PAYOUT_TYPEHASH,
                p.business,
                p.recipient,
                uint8(p.asset),
                p.netAmount,
                p.feeAmount,
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

    function _token(Asset asset) private view returns (IERC20) {
        if (asset == Asset.CusdPlus) return IERC20(address(CUSD_PLUS));
        if (asset == Asset.Usdt) return USDT;
        return CUSD;
    }

    /// The one place escrow decreases, so "you cannot spend what you have
    /// not parked, in the asset you parked it in" is enforced once.
    function _debit(address business, Asset asset, uint256 amount) private {
        if (asset == Asset.CusdPlus) {
            uint256 held = escrowShares[business];
            require(amount <= held, "insufficient escrow");
            escrowShares[business] = held - amount;
            totalEscrowShares -= amount;
        } else if (asset == Asset.Usdt) {
            uint256 held = escrowUsdt[business];
            require(amount <= held, "insufficient escrow");
            escrowUsdt[business] = held - amount;
            totalEscrowUsdt -= amount;
        } else {
            uint256 held = escrowCusd[business];
            require(amount <= held, "insufficient escrow");
            escrowCusd[business] = held - amount;
            totalEscrowCusd -= amount;
        }
    }

    // ═════════════════════════ Admin ════════════════════════════════════
    // Owner (the Safe) can collect ACCRUED FEES ONLY and freeze new
    // activity; it has no path to escrowed funds — collectFees is bounded
    // by the accrual counter, so escrow can never be drained through it.

    function collectFees(Asset asset, address to, uint256 amount) external onlyOwner nonReentrant {
        require(to != address(0), "zero recipient");
        uint256 accrued =
            asset == Asset.CusdPlus ? accruedFeeShares : (asset == Asset.Usdt ? accruedFeeUsdt : accruedFeeCusd);
        require(amount > 0 && amount <= accrued, "exceeds accrued fees");
        if (asset == Asset.CusdPlus) {
            accruedFeeShares = accrued - amount;
        } else if (asset == Asset.Usdt) {
            accruedFeeUsdt = accrued - amount;
        } else {
            accruedFeeCusd = accrued - amount;
        }
        _token(asset).safeTransfer(to, amount);
        emit FeesCollected(to, asset, amount);
    }

    /// Value that reached this contract WITHOUT going through `deposit`
    /// (a mistaken direct transfer) would otherwise be stranded forever.
    /// Bounded by the provable surplus of that asset, so escrow and accrued
    /// fees are untouchable by construction, not by trust.
    function surplus(Asset asset) public view returns (uint256) {
        uint256 balance = _token(asset).balanceOf(address(this));
        uint256 owed = asset == Asset.CusdPlus
            ? totalEscrowShares + accruedFeeShares
            : (asset == Asset.Usdt ? totalEscrowUsdt + accruedFeeUsdt : totalEscrowCusd + accruedFeeCusd);
        return balance > owed ? balance - owed : 0;
    }

    function rescueSurplus(Asset asset, address to, uint256 amount) external onlyOwner nonReentrant {
        require(to != address(0), "zero recipient");
        require(amount > 0 && amount <= surplus(asset), "exceeds surplus");
        _token(asset).safeTransfer(to, amount);
        emit SurplusRescued(to, asset, amount);
    }

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }
}
