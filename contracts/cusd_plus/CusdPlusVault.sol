// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * CusdPlusVault — Confío Dollar+ (cUSD+) on BSC.
 *
 * DESIGN DRAFT (uncompiled): the Solidity port of the architecture proven in
 * contracts/cusd/cusd.py (Algorand). Same trust story, EVM grammar:
 *
 *   cusd.py (Algorand)                     This contract (BSC)
 *   ───────────────────────────────────    ─────────────────────────────────
 *   mint only inside an atomic group       mint only inside a function that
 *   whose USDC axfer the contract          pulls/receives the USDY collateral
 *   verifies at a fixed index              in the SAME transaction
 *   ASA manager locked to zero             no owner/admin mint function
 *                                          exists anywhere in the bytecode
 *   clawback = app (contract controls      vault holds the USDY; shares are
 *   reserve movements)                     burned to release it
 *   1 cUSD : 1 USDC, fixed                 Σ cUSD+ value ≤ vault USDY value,
 *                                          enforced on every state change
 *
 * TOKEN MODEL (locked decision A): cUSD+ is an ACCUMULATING SHARE. A share's
 * USD price (`pPlus`, 1e18) starts at $1.00 and compounds at
 * (1 − CONFIO_YIELD_SHARE) of USDY's own oracle appreciation. Share counts
 * are an on-chain implementation detail — every Confío surface displays USD
 * value only (shares × pPlus).
 *
 * FEE MODEL: Confío never mints itself anything. Because pPlus grows slower
 * than USDY's price, the vault's USDY is progressively worth more than what
 * is owed to holders; that surplus — and ONLY that surplus — is withdrawable
 * by the treasury (collectFees). Backing can therefore never drop below 100%
 * of what holders are owed.
 *
 * TRANSFER POLICY (locked decision C): day-to-day restriction is soft —
 * plain ERC-20 on chain, the app UI simply doesn't surface transfers. The
 * ONE hard control is per-address freeze (parity with cusd.py's
 * freeze_address): a frozen address can neither transfer, receive, mint nor
 * redeem. Rationale beyond parity: USDY is a permissioned asset — if a
 * sanctioned actor moved through this vault, Ondo could blacklist the VAULT
 * address and strand every honest holder. Surgical per-address freeze is how
 * the pool protects itself.
 *
 * UPGRADEABILITY: UUPS, owner-gated, WITH AN IRREVERSIBLE LOCK — mirroring
 * what cusd.py actually ships: its @app.update allows admin updates during
 * maturation ("Once ... verified stable in production: Change this to return
 * Reject() and compile!"), and cUSD has in fact been updated several times.
 * Early vault versions integrate a not-yet-final Instant Manager ABI;
 * day-one immutability would strand funds behind the first bug. The honest
 * promise instead: upgradeable by the treasury multisig while maturing (put
 * a timelock on the owner before scale), then lockUpgrades() — a one-way,
 * publicly verifiable switch, cleaner than cUSD's recompile-to-Reject —
 * makes the vault permanently immutable. There is no delete/selfdestruct
 * (parity with cusd.py's permanent Reject on delete). Wiring addresses are
 * implementation immutables: an upgrade deploys a new implementation whose
 * constructor re-wires IM/oracle — exactly the escape hatch needed if Ondo
 * migrates its BNB contracts.
 *
 * WIRING (all confirmed by Ondo 2026-07-07 + on-chain reads; README.md):
 *  - USDY_InstantManager (BNB): 0x9bA360087075A4Cef548eeD71Eed197bf4cFA4E2
 *    (rwaToken() == USDY below; deposit/receive token is USDT on BNB)
 *  - USDY (BNB, accumulating, 18dp): 0x608593d17a2decbbc4399e4185be4922f97ed32e
 *  - USDY Price Oracle (BNB): 0x8aaa843b848c2E3c83956Bc09aFBE4D9Dcf297b7
 *    (getPrice() 1e18 semantics verified on-chain: 1.13863392 on 07-07)
 *  - USDT (Binance-Peg BSC-USD, 18dp): 0x55d398326f99059fF775485246999027B3197955
 *  REMAINING before deploy: Primary Purchaser whitelisting of the vault
 *  proxy address (contract whitelisting confirmed possible; USDY transfers
 *  out of the vault to non-whitelisted users confirmed permitted —
 *  whitelisting gates mint/redeem only).
 */

import {ERC20Upgradeable} from "@openzeppelin/contracts-upgradeable/token/ERC20/ERC20Upgradeable.sol";
import {Ownable2StepUpgradeable} from "@openzeppelin/contracts-upgradeable/access/Ownable2StepUpgradeable.sol";
import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
// Transient-storage guard (OZ 5.6 dropped the upgradeable variant): stateless,
// so proxy-safe with no initializer. Requires Cancun opcodes — BSC has them.
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// Ondo's dynamic oracle: deterministic accreting USD price for USDY, 1e18.
interface IRWADynamicOracle {
    function getPrice() external view returns (uint256);
}

/// OFFICIAL Instant Manager ABI — verified 2026-07-07 against the BNB
/// deployment (0x9bA360087075A4Cef548eeD71Eed197bf4cFA4E2, rwaToken() ==
/// USDY 0x608593d1...) and Ondo's integration guide (selectors 0x22d4a175 /
/// 0xd8780161). Per Ondo (Daniel, 2026-07-07): the BNB contract matches the
/// Ethereum one exactly except the rUSDY surface (absent on BNB — we never
/// used it), and the deposit/receive stablecoin on BNB is USDT
/// (0x55d398326f99059fF775485246999027B3197955).
interface IOndoInstantManager {
    /// deposit stablecoin -> receive USDY at oracle price.
    function subscribe(address depositToken, uint256 depositAmount, uint256 minimumRwaReceived)
        external
        returns (uint256 rwaAmountOut);
    /// burn USDY -> receive stablecoin at oracle price.
    function redeem(uint256 rwaAmount, address receivingToken, uint256 minimumTokenReceived)
        external
        returns (uint256 receiveTokenAmount);
}

contract CusdPlusVault is
    ERC20Upgradeable,
    Ownable2StepUpgradeable,
    PausableUpgradeable,
    ReentrancyGuardTransient,
    UUPSUpgradeable
{
    using SafeERC20 for IERC20;

    // ── Immutable wiring ────────────────────────────────────────────────
    IERC20 public immutable USDY; // backing asset (accumulating, 1e18)
    IERC20 public immutable USDT; // BSC USDT, 1e18 (Koywe rail in/out)
    IOndoInstantManager public immutable INSTANT_MANAGER;
    IRWADynamicOracle public immutable ORACLE;

    /// Confío's share of USDY yield, bps (locked: 1500 = 15%). Immutable —
    /// changing it requires a new vault, which is the point.
    uint256 public immutable CONFIO_YIELD_SHARE_BPS;
    uint256 private constant BPS = 10_000;
    uint256 private constant WAD = 1e18;

    /// Oracle sanity guard: a single accrual step moving more than this many
    /// bps freezes accrual (skip + event) until the owner re-baselines. USDY
    /// accretes a few bps/day; a 2% jump is a fault, not yield.
    uint256 public constant MAX_ACCRUAL_JUMP_BPS = 200;

    // ── Accrual state ───────────────────────────────────────────────────
    /// cUSD+ share price in USD, 1e18. Starts at $1.00, only ever rises.
    uint256 public pPlus;
    /// Oracle price at the last completed accrual.
    uint256 public lastOraclePrice;
    /// Set when the jump guard trips; accrual stays frozen (mints/redeems
    /// keep working at the frozen pPlus) until resetOracleBaseline().
    bool public oracleGuardTripped;

    /// One-way switch: once true, _authorizeUpgrade reverts forever. The
    /// on-chain equivalent of recompiling cusd.py's update() to Reject().
    bool public upgradesLocked;

    /// Per-address freeze (cusd.py freeze_address parity). Frozen addresses
    /// cannot transfer, receive, mint or redeem. Yield keeps accruing to
    /// their shares — freeze detains funds, it does not confiscate them.
    mapping(address => bool) public frozen;

    // ── Events ──────────────────────────────────────────────────────────
    event Accrued(uint256 oraclePrice, uint256 newPPlus);
    event OracleJumpGuard(uint256 lastPrice, uint256 newPrice);
    event OracleBaselineReset(uint256 oldPrice, uint256 newPrice);
    event Minted(address indexed recipient, uint256 shares, uint256 usdyIn, uint256 pPlusAt);
    event Redeemed(address indexed holder, address indexed to, uint256 shares, uint256 usdyOut, uint256 pPlusAt);
    event FeesCollected(address indexed to, uint256 usdyAmount, uint256 surplusBefore);
    event UpgradesLockedForever();
    event AddressFrozen(address indexed target);
    event AddressUnfrozen(address indexed target);

    /// Implementation constructor: wiring lives in implementation-level
    /// immutables (cheap reads; an upgrade = new implementation with new
    /// wiring). The proxy's state is set in initialize().
    constructor(
        address usdy,
        address usdt,
        address instantManager,
        address oracle,
        uint256 confioYieldShareBps
    ) {
        require(confioYieldShareBps <= 3_000, "share too high"); // hard ceiling 30%
        USDY = IERC20(usdy);
        USDT = IERC20(usdt);
        INSTANT_MANAGER = IOndoInstantManager(instantManager);
        ORACLE = IRWADynamicOracle(oracle);
        CONFIO_YIELD_SHARE_BPS = confioYieldShareBps;
        _disableInitializers(); // implementation is never used directly
    }

    function initialize(address treasury) external initializer {
        __ERC20_init("Confio Dollar+", "cUSD+");
        __Ownable_init(treasury);
        __Ownable2Step_init();
        __Pausable_init();
        pPlus = WAD; // $1.00 at genesis
        lastOraclePrice = ORACLE.getPrice();
    }

    /// cusd.py's update(): Assert(sender == admin) — here onlyOwner, plus the
    /// one-way lock. After lockUpgrades() this vault is permanently immutable.
    function _authorizeUpgrade(address) internal view override onlyOwner {
        require(!upgradesLocked, "upgrades locked forever");
    }

    /// Irreversible. Call when the vault has proven itself in production —
    /// the same milestone cusd.py marks with "change update() to Reject()".
    function lockUpgrades() external onlyOwner {
        upgradesLocked = true;
        emit UpgradesLockedForever();
    }

    // ═════════════════════════ Accrual ══════════════════════════════════
    /// Lazy compounding on every interaction (Compound-style): pPlus grows by
    /// (1 − fee share) of USDY's growth since the last accrual. The withheld
    /// slice is never minted anywhere — it simply makes the vault's USDY
    /// worth more than usdyOwed(), i.e. it becomes withdrawable surplus.
    function accrue() public {
        uint256 p = ORACLE.getPrice();
        uint256 last = lastOraclePrice;
        if (p == last || oracleGuardTripped) return;
        // USDY's oracle curve is monotonically increasing by construction; a
        // lower or wildly higher read is a fault. Freeze, don't revert —
        // reverting here would brick mints and redeems.
        if (p < last || ((p - last) * BPS) / last > MAX_ACCRUAL_JUMP_BPS) {
            oracleGuardTripped = true;
            emit OracleJumpGuard(last, p);
            return;
        }
        // growthWad = p/last − 1, in WAD; keep (1 − share) of it.
        uint256 growthWad = ((p - last) * WAD) / last;
        uint256 keptWad = (growthWad * (BPS - CONFIO_YIELD_SHARE_BPS)) / BPS;
        pPlus = (pPlus * (WAD + keptWad)) / WAD;
        lastOraclePrice = p;
        emit Accrued(p, pPlus);
    }

    /// After investigating an oracle fault, the owner re-baselines WITHOUT
    /// granting holders the anomalous jump (yield during the frozen window is
    /// forfeited to surplus — conservative by design).
    /// ONLY callable while the guard is tripped: on a healthy oracle a reset
    /// would skip pending sub-2% growth past accrue(), silently converting
    /// the holders' share into owner-collectable surplus.
    function resetOracleBaseline() external onlyOwner {
        require(oracleGuardTripped, "guard not tripped");
        uint256 p = ORACLE.getPrice();
        emit OracleBaselineReset(lastOraclePrice, p);
        lastOraclePrice = p;
        oracleGuardTripped = false;
    }

    // ═════════════════════════ Mint paths ═══════════════════════════════
    // There is deliberately NO other mint in this contract. Both paths take
    // custody of the USDY inside the same transaction that mints — the EVM
    // translation of cusd.py verifying the USDC axfer inside the atomic
    // group. (Solidity's guarantee is even simpler: one tx, one revert scope.)

    /// Primary rail: USDT (delivered by Koywe or bridged by treasury) →
    /// InstantManager subscribe → USDY into vault → shares to recipient.
    /// minUsdyOut is the slippage floor (IM's minimumRwaReceived).
    function subscribeAndMint(uint256 usdtIn, uint256 minUsdyOut, address recipient)
        external
        nonReentrant
        whenNotPaused
        returns (uint256 sharesOut)
    {
        require(usdtIn > 0, "zero in");
        accrue();
        USDT.safeTransferFrom(msg.sender, address(this), usdtIn);
        uint256 usdyOut = _imSubscribe(usdtIn, minUsdyOut);
        sharesOut = _mintAgainstUsdy(usdyOut, recipient);
    }

    /// Secondary rail: owner (treasury Safe) already holds USDY (bridge
    /// leg, secondary-market acquisition during IM outages).
    /// ONLY the owner: raw USDY never touches user wallets in either
    /// direction — Duende is Ondo's sole onboarded Purchaser, and the PP
    /// representations state USDY stays within Duende-controlled
    /// infrastructure. Users enter via subscribeAndMint (USDT).
    function depositAndMint(uint256 usdyIn, address recipient)
        external
        onlyOwner
        nonReentrant
        whenNotPaused
        returns (uint256 sharesOut)
    {
        require(usdyIn > 0, "zero in");
        accrue();
        USDY.safeTransferFrom(msg.sender, address(this), usdyIn);
        sharesOut = _mintAgainstUsdy(usdyIn, recipient);
    }

    function _mintAgainstUsdy(uint256 usdyIn, address recipient) internal returns (uint256 sharesOut) {
        uint256 p = ORACLE.getPrice();
        // shares = USD value in / share price; floor rounding favors backing.
        sharesOut = (usdyIn * p) / pPlus;
        require(sharesOut > 0, "dust");
        _mint(recipient, sharesOut);
        _assertFullyBacked(p);
        emit Minted(recipient, sharesOut, usdyIn, pPlus);
    }

    // ═════════════════════════ Redeem paths ═════════════════════════════

    /// Burn shares, receive raw USDY — owner (treasury Safe) ONLY.
    /// Holders exit exclusively via redeemToUsdt (USDY moves vault↔IM,
    /// never to a holder wallet). A public raw-USDY exit would be an
    /// on-chain direct claim to the underlying — contradicting the PP
    /// representations ("USDY is not transferred, resold, or distributed
    /// to cUSD+ holders"), regardless of what the UI exposes. Emergency
    /// liquidity during an IM outage is a treasury operation: the Safe
    /// acquires the shares, redeems raw, and makes holders whole off-rail.
    function redeem(uint256 shares, address to)
        external
        onlyOwner
        nonReentrant
        whenNotPaused
        returns (uint256 usdyOut)
    {
        accrue();
        uint256 p = ORACLE.getPrice();
        usdyOut = (shares * pPlus) / p; // floor favors backing
        require(usdyOut > 0, "dust");
        _burn(msg.sender, shares);
        USDY.safeTransfer(to, usdyOut);
        _assertFullyBacked(p);
        emit Redeemed(msg.sender, to, shares, usdyOut, pPlus);
    }

    /// Burn shares → IM redeem → USDT to `to` (the direct off-ramp rail:
    /// cUSD+ → USDT-BSC → Koywe, no hop through cUSD/Algorand).
    function redeemToUsdt(uint256 shares, uint256 minUsdtOut, address to)
        external
        nonReentrant
        whenNotPaused
        returns (uint256 usdtOut)
    {
        accrue();
        uint256 p = ORACLE.getPrice();
        uint256 usdyOut = (shares * pPlus) / p;
        require(usdyOut > 0, "dust");
        _burn(msg.sender, shares);
        usdtOut = _imRedeem(usdyOut, minUsdtOut);
        USDT.safeTransfer(to, usdtOut);
        _assertFullyBacked(p);
        emit Redeemed(msg.sender, to, shares, usdyOut, pPlus);
    }

    // ═════════════════════════ Fees ═════════════════════════════════════

    /// Withdraw ONLY the surplus above 100% backing (cusd.py's rule that the
    /// reserve is untouchable, expressed as an inequality instead of 1:1).
    function collectFees(address to, uint256 usdyAmount) external onlyOwner nonReentrant {
        accrue();
        uint256 p = ORACLE.getPrice();
        uint256 surplus = surplusUsdy(p);
        require(usdyAmount <= surplus, "exceeds surplus");
        USDY.safeTransfer(to, usdyAmount);
        _assertFullyBacked(p);
        emit FeesCollected(to, usdyAmount, surplus);
    }

    /// Rescue tokens sent by mistake. USDY is the backing and is NEVER
    /// sweepable — not even by the owner.
    function sweep(address token, address to, uint256 amount) external onlyOwner {
        require(token != address(USDY), "backing is sacred");
        IERC20(token).safeTransfer(to, amount);
    }

    function pause() external onlyOwner { _pause(); }
    function unpause() external onlyOwner { _unpause(); }

    // ═════════════════════════ Freeze (cusd.py parity) ══════════════════

    function freezeAddress(address target) external onlyOwner {
        require(target != address(this), "cannot freeze vault");
        frozen[target] = true;
        emit AddressFrozen(target);
    }

    function unfreezeAddress(address target) external onlyOwner {
        frozen[target] = false;
        emit AddressUnfrozen(target);
    }

    /// OZ v5 single choke point for mint/burn/transfer — the same property
    /// cusd.py gets from the ASA freeze bit: one flag stops every movement.
    function _update(address from, address to, uint256 value) internal override {
        require(!frozen[from] && !frozen[to], "address frozen");
        super._update(from, to, value);
    }

    // ═════════════════════════ Views (public verifiability) ═════════════
    // These four back the ProtectedSavings "verify it yourself" links.

    /// USDY the holders are collectively owed at oracle price `p`.
    function usdyOwed(uint256 p) public view returns (uint256) {
        return (totalSupply() * pPlus + (p - 1)) / p; // ceil — owe generously
    }

    /// Withdrawable surplus at oracle price `p` (0 if somehow underwater).
    function surplusUsdy(uint256 p) public view returns (uint256) {
        uint256 bal = USDY.balanceOf(address(this));
        uint256 owed = usdyOwed(p);
        return bal > owed ? bal - owed : 0;
    }

    /// Σ cUSD+ USD value (what the app shows as "cUSD+ en circulación").
    function totalOwedUsd() external view returns (uint256) {
        return (totalSupply() * pPlus) / WAD;
    }

    /// Backing ratio in bps (10_000 = exactly 100%). Public invariant:
    /// this must never read below 10_000.
    function backingRatioBps() external view returns (uint256) {
        uint256 owed = usdyOwed(ORACLE.getPrice());
        if (owed == 0) return BPS;
        return (USDY.balanceOf(address(this)) * BPS) / owed;
    }

    // ═════════════════════════ Internals ════════════════════════════════

    /// The invariant, checked after every state change (cusd.py asserts
    /// everything; so do we): vault USDY ≥ USDY owed to holders.
    function _assertFullyBacked(uint256 p) internal view {
        require(USDY.balanceOf(address(this)) >= usdyOwed(p), "backing violated");
    }

    /// IM plumbing against the official ABI. We measure the balance DELTA
    /// rather than trusting the return value — defense in depth against any
    /// future IM upgrade changing return semantics.
    function _imSubscribe(uint256 usdtIn, uint256 minUsdyOut) internal returns (uint256 usdyOut) {
        uint256 before = USDY.balanceOf(address(this));
        USDT.forceApprove(address(INSTANT_MANAGER), usdtIn);
        INSTANT_MANAGER.subscribe(address(USDT), usdtIn, minUsdyOut);
        usdyOut = USDY.balanceOf(address(this)) - before;
        require(usdyOut >= minUsdyOut, "im: insufficient out");
    }

    function _imRedeem(uint256 usdyIn, uint256 minUsdtOut) internal returns (uint256 usdtOut) {
        uint256 before = USDT.balanceOf(address(this));
        USDY.forceApprove(address(INSTANT_MANAGER), usdyIn);
        INSTANT_MANAGER.redeem(usdyIn, address(USDT), minUsdtOut);
        usdtOut = USDT.balanceOf(address(this)) - before;
        require(usdtOut >= minUsdtOut, "im: insufficient out");
    }
}
