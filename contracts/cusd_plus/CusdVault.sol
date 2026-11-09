// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20Upgradeable} from "@openzeppelin/contracts-upgradeable/token/ERC20/ERC20Upgradeable.sol";
import {Ownable2StepUpgradeable} from "@openzeppelin/contracts-upgradeable/access/Ownable2StepUpgradeable.sol";
import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/**
 * @title CusdVault
 * @notice Universal BSC payment dollar backed 1:1 by USDT.
 *
 * Every external USDT <-> cUSD conversion pays the same bounded fee. The
 * registered savings vault may move value between cUSD and cUSD+ without a
 * fee, but only inside a Confio-sponsored transaction. Holder exits to USDT
 * remain permissionless and always fee-bearing.
 *
 * Fee referral: a Confio-sponsored transaction may arm a referrer once
 * (armReferral). Every perimeter fee charged later in that same
 * transaction, including ones reached through routers or cUSD+, mints the
 * armed share of the fee to the referrer as cUSD. The fee USDT already in
 * the vault backs that cUSD, so 1:1 backing is unchanged. The arm lives in
 * transient storage (EIP-1153) and vanishes when the transaction ends.
 */
contract CusdVault is
    ERC20Upgradeable,
    Ownable2StepUpgradeable,
    PausableUpgradeable,
    ReentrancyGuardTransient,
    UUPSUpgradeable
{
    using SafeERC20 for IERC20;

    IERC20 public immutable USDT;

    uint256 public constant BPS = 10_000;
    uint256 public constant MAX_FEE_BPS = 90;
    /// Hard ceiling on the referrer's share of a fee: half.
    uint256 public constant MAX_REFERRAL_SHARE_BPS = 5_000;

    // Transient slots for the per-transaction referral arm.
    bytes32 private constant _REFERRER_SLOT = keccak256("confio.cusd.referral.referrer");
    bytes32 private constant _REFEREE_SLOT = keccak256("confio.cusd.referral.referee");
    bytes32 private constant _SHARE_SLOT = keccak256("confio.cusd.referral.shareBps");

    uint256 public feeBps;
    uint256 public accruedEntryFees;
    uint256 public accruedExitFees;
    mapping(address => bool) public isSponsor;
    address public savingsVault;
    /// Per-address freeze, cUSD+ parity. Appended: layout above must stay.
    mapping(address => bool) public frozen;
    /// Owner-set ceiling (<= MAX_REFERRAL_SHARE_BPS) for armed shares.
    /// Zero disables referral payouts. Appended: layout above must stay.
    uint256 public referralShareCapBps;
    /// ConfioBatchDelegate: only an EIP-7702 account delegated to it (a
    /// Confío member's own account) may arm a referral. Without it, any
    /// contract reached during a sponsored batch (a token hook, a router
    /// target) could arm itself. Zero disables arming. Appended.
    address public batchDelegate;

    event SponsorSet(address indexed sponsor, bool allowed);
    event SavingsVaultSet(address indexed previousVault, address indexed newVault);
    event FeeBpsSet(uint256 previousFeeBps, uint256 newFeeBps);
    event MintedWithFee(
        address indexed payer,
        address indexed recipient,
        uint256 grossUsdt,
        uint256 feeUsdt,
        uint256 netCusd,
        uint256 appliedFeeBps
    );
    event RedeemedWithFee(
        address indexed holder,
        address indexed recipient,
        uint256 grossCusd,
        uint256 feeUsdt,
        uint256 netUsdt,
        uint256 appliedFeeBps
    );
    event SavingsMinted(address indexed recipient, uint256 amount);
    event SavingsRedeemed(address indexed recipient, uint256 amount);
    event SavingsEntrySettled(uint256 grossUsdt, uint256 feeUsdt, uint256 netUsdt, uint256 appliedFeeBps);
    event SavingsExitSettled(
        address indexed recipient, uint256 grossUsdt, uint256 feeUsdt, uint256 netUsdt, uint256 appliedFeeBps
    );
    event ConversionFeesCollected(address indexed treasury, uint256 entryFees, uint256 exitFees);
    event SurplusUsdtRescued(address indexed treasury, uint256 amount);
    event AddressFrozen(address indexed target);
    event AddressUnfrozen(address indexed target);
    event ReferralShareCapSet(uint256 previousCapBps, uint256 newCapBps);
    event BatchDelegateSet(address indexed previousDelegate, address indexed newDelegate);
    event ReferralPaid(
        address indexed referee, address indexed referrer, uint256 feeUsdt, uint256 shareCusd, uint256 shareBps
    );

    constructor(address usdt) {
        require(usdt != address(0), "zero usdt");
        USDT = IERC20(usdt);
        _disableInitializers();
    }

    function initialize(address treasury, uint256 initialFeeBps) external initializer {
        require(treasury != address(0), "zero treasury");
        require(initialFeeBps <= MAX_FEE_BPS, "fee too high");
        __ERC20_init("Confio Dollar", "cUSD");
        __Ownable_init(treasury);
        __Ownable2Step_init();
        __Pausable_init();
        feeBps = initialFeeBps;
    }

    function _authorizeUpgrade(address) internal view override onlyOwner {}

    /// A zero owner would permanently remove every recovery/configuration
    /// path (upgrade, unpause, sponsor rotation and fee collection). The Safe
    /// may transfer ownership through Ownable2Step, but cannot burn it.
    function renounceOwnership() public pure override {
        revert("renounce disabled");
    }

    modifier onlySponsored() {
        require(isSponsor[msg.sender] || isSponsor[tx.origin], "not sponsored");
        _;
    }

    modifier onlySavingsVault() {
        require(msg.sender == savingsVault, "not savings vault");
        _;
    }

    function feeFor(uint256 gross) public view returns (uint256) {
        if (gross == 0 || feeBps == 0) return 0;
        return Math.mulDiv(gross, feeBps, BPS, Math.Rounding.Ceil);
    }

    function previewMint(uint256 grossUsdt) public view returns (uint256 feeUsdt, uint256 netCusd) {
        feeUsdt = feeFor(grossUsdt);
        netCusd = grossUsdt - feeUsdt;
    }

    function previewRedeem(uint256 grossCusd) public view returns (uint256 feeUsdt, uint256 netUsdt) {
        feeUsdt = feeFor(grossCusd);
        netUsdt = grossCusd - feeUsdt;
    }

    /// @notice Sponsor-gated entry from external USDT into cUSD.
    function mintWithFee(uint256 grossUsdt, uint256 minCusdOut, address recipient)
        external
        nonReentrant
        whenNotPaused
        onlySponsored
        returns (uint256 netCusd)
    {
        require(grossUsdt > 0, "zero amount");
        require(recipient != address(0), "zero recipient");
        require(recipient == msg.sender || isSponsor[msg.sender], "recipient not caller");
        (uint256 feeUsdt, uint256 net) = previewMint(grossUsdt);
        require(net > 0, "fee consumes amount");
        require(net >= minCusdOut, "insufficient out");

        USDT.safeTransferFrom(msg.sender, address(this), grossUsdt);
        accruedEntryFees += _payReferral(feeUsdt);
        _mint(recipient, net);
        _assertFullyBacked();
        emit MintedWithFee(msg.sender, recipient, grossUsdt, feeUsdt, net, feeBps);
        return net;
    }

    /// @notice Permissionless holder exit. There is no fee-free public exit.
    function redeemWithFee(uint256 grossCusd, uint256 minUsdtOut, address recipient)
        external
        nonReentrant
        whenNotPaused
        returns (uint256 netUsdt)
    {
        require(grossCusd > 0, "zero amount");
        require(recipient != address(0), "zero recipient");
        (uint256 feeUsdt, uint256 net) = previewRedeem(grossCusd);
        require(net > 0, "fee consumes amount");
        require(net >= minUsdtOut, "insufficient out");

        _burn(msg.sender, grossCusd);
        accruedExitFees += _payReferral(feeUsdt);
        USDT.safeTransfer(recipient, net);
        _assertFullyBacked();
        emit RedeemedWithFee(msg.sender, recipient, grossCusd, feeUsdt, net, feeBps);
        return net;
    }

    /// @notice Fee-free cUSD creation after cUSD+ has redeemed USDY to USDT.
    function mintForSavings(uint256 usdtAmount, address recipient)
        external
        nonReentrant
        whenNotPaused
        onlySavingsVault
        onlySponsored
        returns (uint256 cusdOut)
    {
        require(usdtAmount > 0, "zero amount");
        require(recipient != address(0), "zero recipient");
        USDT.safeTransferFrom(msg.sender, address(this), usdtAmount);
        _mint(recipient, usdtAmount);
        _assertFullyBacked();
        emit SavingsMinted(recipient, usdtAmount);
        return usdtAmount;
    }

    /// @notice Fee-free cUSD redemption by cUSD+ after it has received cUSD.
    function redeemForSavings(uint256 cusdAmount, address recipient)
        external
        nonReentrant
        whenNotPaused
        onlySavingsVault
        onlySponsored
        returns (uint256 usdtOut)
    {
        require(cusdAmount > 0, "zero amount");
        require(recipient != address(0), "zero recipient");
        _burn(msg.sender, cusdAmount);
        USDT.safeTransfer(recipient, cusdAmount);
        _assertFullyBacked();
        emit SavingsRedeemed(recipient, cusdAmount);
        return cusdAmount;
    }

    /// @notice Applies the entry fee for a direct USDT -> cUSD+ conversion.
    /// @dev cUSD+ transfers gross USDT in and receives net USDT back for IM.
    function settleSavingsEntry(uint256 grossUsdt, uint256 minUsdtOut)
        external
        nonReentrant
        whenNotPaused
        onlySavingsVault
        onlySponsored
        returns (uint256 netUsdt)
    {
        require(grossUsdt > 0, "zero amount");
        (uint256 feeUsdt, uint256 net) = previewMint(grossUsdt);
        require(net > 0, "fee consumes amount");
        require(net >= minUsdtOut, "insufficient out");
        USDT.safeTransferFrom(msg.sender, address(this), grossUsdt);
        accruedEntryFees += _payReferral(feeUsdt);
        USDT.safeTransfer(msg.sender, net);
        _assertFullyBacked();
        emit SavingsEntrySettled(grossUsdt, feeUsdt, net, feeBps);
        return net;
    }

    /// @notice Applies the exit fee for a permissionless cUSD+ -> USDT exit.
    /// @dev Intentionally does not require a sponsor; only cUSD+ may call it.
    function settleSavingsExit(uint256 grossUsdt, uint256 minUsdtOut, address recipient)
        external
        nonReentrant
        whenNotPaused
        onlySavingsVault
        returns (uint256 netUsdt)
    {
        require(grossUsdt > 0, "zero amount");
        require(recipient != address(0), "zero recipient");
        (uint256 feeUsdt, uint256 net) = previewRedeem(grossUsdt);
        require(net > 0, "fee consumes amount");
        require(net >= minUsdtOut, "insufficient out");
        USDT.safeTransferFrom(msg.sender, address(this), grossUsdt);
        accruedExitFees += _payReferral(feeUsdt);
        USDT.safeTransfer(recipient, net);
        _assertFullyBacked();
        emit SavingsExitSettled(recipient, grossUsdt, feeUsdt, net, feeBps);
        return net;
    }

    // ═════════════════════════ Fee referral ═══════════════════════════════

    /// @notice Arms the referrer for the rest of this transaction. Only a
    /// Confio-sponsored transaction may arm, and only once; the sponsor's
    /// policy decides who the referrer is and the share. A share above the
    /// owner cap arms nothing (never reverts the batch).
    /// msg.sender (the user's 7702 account) is recorded as the referee.
    function armReferral(address referrer, uint256 shareBps) external whenNotPaused {
        require(isSponsor[tx.origin], "not sponsored");
        require(_isConfioAccount(msg.sender), "not a Confio account");
        require(_tload(_REFERRER_SLOT) == 0, "already armed");
        require(referrer != address(0), "zero referrer");
        require(referrer != msg.sender, "self referral");
        require(referrer != address(this) && referrer != savingsVault, "bad referrer");
        require(!isSponsor[referrer], "bad referrer");
        require(shareBps > 0 && shareBps <= MAX_REFERRAL_SHARE_BPS, "bad share");
        // Above the live cap (lowered or zeroed by the Safe while servers or
        // prepared batches still carry the old share): no arm, whole fee
        // kept, and the member's conversion still goes through.
        if (shareBps > referralShareCapBps) return;
        _tstore(_REFERRER_SLOT, uint256(uint160(referrer)));
        _tstore(_REFEREE_SLOT, uint256(uint160(msg.sender)));
        _tstore(_SHARE_SLOT, shareBps);
    }

    /// @notice The referral armed in the current transaction (zero if none).
    function armedReferral() external view returns (address referrer, address referee, uint256 shareBps) {
        referrer = address(uint160(_tload(_REFERRER_SLOT)));
        referee = address(uint160(_tload(_REFEREE_SLOT)));
        shareBps = _tload(_SHARE_SLOT);
    }

    function setBatchDelegate(address newDelegate) external onlyOwner {
        address previous = batchDelegate;
        batchDelegate = newDelegate;
        emit BatchDelegateSet(previous, newDelegate);
    }

    /// EIP-7702: a delegated EOA's code is the 23-byte designator
    /// 0xef0100 || delegate.
    function _isConfioAccount(address account) internal view returns (bool) {
        address delegate = batchDelegate;
        if (delegate == address(0)) return false;
        return keccak256(account.code) == keccak256(abi.encodePacked(hex"ef0100", delegate));
    }

    function setReferralShareCapBps(uint256 newCapBps) external onlyOwner {
        require(newCapBps <= MAX_REFERRAL_SHARE_BPS, "cap too high");
        uint256 previous = referralShareCapBps;
        referralShareCapBps = newCapBps;
        emit ReferralShareCapSet(previous, newCapBps);
    }

    /// @dev Mints the armed share of `feeUsdt` to the referrer as cUSD and
    /// returns what the vault keeps as fee. Never reverts the user's
    /// conversion: no arm, no sponsor, a frozen referrer, a lowered cap or
    /// a share that rounds to zero all simply keep the whole fee.
    function _payReferral(uint256 feeUsdt) internal returns (uint256 kept) {
        if (feeUsdt == 0) return 0;
        address referrer = address(uint160(_tload(_REFERRER_SLOT)));
        if (referrer == address(0) || !isSponsor[tx.origin] || frozen[referrer]) return feeUsdt;
        uint256 shareBps = _tload(_SHARE_SLOT);
        if (shareBps > referralShareCapBps) return feeUsdt;
        uint256 share = Math.mulDiv(feeUsdt, shareBps, BPS);
        if (share == 0) return feeUsdt;
        _mint(referrer, share);
        emit ReferralPaid(address(uint160(_tload(_REFEREE_SLOT))), referrer, feeUsdt, share, shareBps);
        return feeUsdt - share;
    }

    function _tload(bytes32 slot) private view returns (uint256 value) {
        assembly ("memory-safe") {
            value := tload(slot)
        }
    }

    function _tstore(bytes32 slot, uint256 value) private {
        assembly ("memory-safe") {
            tstore(slot, value)
        }
    }

    function setSponsor(address sponsor, bool allowed) external onlyOwner {
        require(sponsor != address(0), "zero sponsor");
        isSponsor[sponsor] = allowed;
        emit SponsorSet(sponsor, allowed);
    }

    function setSavingsVault(address newSavingsVault) external onlyOwner {
        require(newSavingsVault != address(0), "zero savings vault");
        require(newSavingsVault.code.length > 0, "savings vault not contract");
        address previous = savingsVault;
        savingsVault = newSavingsVault;
        emit SavingsVaultSet(previous, newSavingsVault);
    }

    function setFeeBps(uint256 newFeeBps) external onlyOwner {
        require(newFeeBps <= MAX_FEE_BPS, "fee too high");
        uint256 previous = feeBps;
        feeBps = newFeeBps;
        emit FeeBpsSet(previous, newFeeBps);
    }

    function collectFees(uint256 entryAmount, uint256 exitAmount)
        external
        onlyOwner
        nonReentrant
        returns (uint256 totalCollected)
    {
        require(entryAmount <= accruedEntryFees, "entry exceeds accrued");
        require(exitAmount <= accruedExitFees, "exit exceeds accrued");
        totalCollected = entryAmount + exitAmount;
        require(totalCollected > 0, "zero amount");
        accruedEntryFees -= entryAmount;
        accruedExitFees -= exitAmount;
        USDT.safeTransfer(msg.sender, totalCollected);
        _assertFullyBacked();
        emit ConversionFeesCollected(msg.sender, entryAmount, exitAmount);
    }

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    function freezeAddress(address target) external onlyOwner {
        require(target != address(this), "cannot freeze vault");
        require(target != savingsVault, "cannot freeze savings vault");
        // frozen[0] would brick every mint (from=0) and burn (to=0) via
        // _update — pause() is the intentional full-stop, not this.
        require(target != address(0), "cannot freeze zero");
        frozen[target] = true;
        emit AddressFrozen(target);
    }

    function unfreezeAddress(address target) external onlyOwner {
        frozen[target] = false;
        emit AddressUnfrozen(target);
    }

    function backingUsdt() public view returns (uint256) {
        uint256 balance = USDT.balanceOf(address(this));
        uint256 fees = accruedEntryFees + accruedExitFees;
        return balance > fees ? balance - fees : 0;
    }

    /// @notice The reserve excess left by accidental direct USDT transfers.
    /// Explicit fee counters remain separate and cannot be rescued here.
    function surplusUsdt() public view returns (uint256) {
        uint256 balance = USDT.balanceOf(address(this));
        uint256 obligations = totalSupply() + accruedEntryFees + accruedExitFees;
        return balance > obligations ? balance - obligations : 0;
    }

    function rescueSurplusUsdt(uint256 amount) external onlyOwner nonReentrant {
        require(amount > 0 && amount <= surplusUsdt(), "exceeds surplus");
        USDT.safeTransfer(msg.sender, amount);
        _assertFullyBacked();
        emit SurplusUsdtRescued(msg.sender, amount);
    }

    function backingToken() external view returns (address) {
        return address(USDT);
    }

    function isFullyBacked() external view returns (bool) {
        return backingUsdt() >= totalSupply();
    }

    function _assertFullyBacked() internal view {
        require(backingUsdt() >= totalSupply(), "backing violated");
    }

    /// @dev The approved pause is global, including ordinary transfers.
    function _update(address from, address to, uint256 value) internal override {
        require(!paused(), "Pausable: paused");
        require(!frozen[from] && !frozen[to], "address frozen");
        super._update(from, to, value);
    }
}
