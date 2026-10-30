// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ConfioToken — $CONFIO on BSC.
 *
 * The BEP-20 home of the token after the Algorand→BSC migration. Mirrors
 * the Algorand ASA (id 3351104258, unit CONFIO, 1B total) at the
 * EVM-native 18 decimals. The on-chain name is deliberately the ASCII
 * "Confio" (no accent): Etherscan-family explorers HTML-escape non-ASCII
 * token names ("Conf&#237;o") as anti-spoofing, and wallet/DEX rendering
 * varies — on-chain metadata stays plain ASCII, the accented "Confío"
 * lives in UI and branding.
 *
 * The entire fixed supply of 1,000,000,000 CONFIO is minted once, in the
 * constructor, to the treasury (the 3-of-5 Safe). There is NO minter, NO
 * global pause and NO upgrade path: supply can only fall, and the rules
 * below are the only privileged surface that will ever exist.
 *
 * Incident controls (added 2026-10 after the Binance hot-wallet theft,
 * where stolen tokens with no issuer control were dumped into thin pools):
 *
 *  - Freeze: a frozen address can neither send nor receive, until a
 *    timestamp. The guardian acts in minutes but is bounded to one
 *    MAX_GUARDIAN_FREEZE episode per address, then GUARDIAN_COOLDOWN, so a
 *    stolen guardian key can't hold an address indefinitely, and it cannot
 *    touch `isProtected` addresses (vaults, DEX pools). Only the owner can
 *    keep a freeze going. The owner is bounded to MAX_OWNER_FREEZE per call and may
 *    renew, so no freeze can outlive a renounced owner. No address is ever
 *    frozen forever by construction.
 *  - Recovery: the owner can return a frozen balance to its victim, the
 *    outcome of an issuer's burn-and-reissue without any mint path. Every
 *    recovery is proposed publicly and waits RECOVERY_DELAY; the source
 *    must still be frozen when it executes, and the guardian can cancel.
 *
 * ERC20Permit (EIP-2612) is included so approvals can ride a signature
 * (useful beyond the 7702 batch rail); ERC20Burnable lets any holder —
 * including the treasury — destroy their own tokens, and nothing else.
 * Renouncing ownership ends both controls permanently.
 */

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ERC20Burnable} from "@openzeppelin/contracts/token/ERC20/extensions/ERC20Burnable.sol";
import {ERC20Permit} from "@openzeppelin/contracts/token/ERC20/extensions/ERC20Permit.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";

contract ConfioToken is ERC20, ERC20Burnable, ERC20Permit, Ownable2Step {
    uint256 public constant TOTAL_SUPPLY = 1_000_000_000e18;
    uint64 public constant MAX_GUARDIAN_FREEZE = 14 days;
    uint64 public constant GUARDIAN_COOLDOWN = 14 days;
    uint64 public constant MAX_OWNER_FREEZE = 365 days;
    uint64 public constant RECOVERY_DELAY = 7 days;

    struct Recovery {
        address from;
        address to;
        uint256 amount;
        uint64 executableAt;
    }

    /// May freeze within the guardian bounds. Starts as the treasury and
    /// moves to a separate fast key without a redeploy.
    address public guardian;
    /// Address is frozen while block.timestamp < frozenUntil[address].
    mapping(address => uint64) public frozenUntil;
    /// When the guardian's current freeze episode on an address began.
    mapping(address => uint64) public guardianEpisodeStart;
    /// Out of the guardian's reach; only the owner can freeze these.
    mapping(address => bool) public isProtected;
    mapping(uint256 => Recovery) public recoveries;
    uint256 public nextRecoveryId;

    event GuardianSet(address indexed guardian);
    event ProtectedSet(address indexed account, bool isProtected);
    event Frozen(address indexed account, uint64 until, address indexed by);
    event Unfrozen(address indexed account, address indexed by);
    event RecoveryProposed(
        uint256 indexed id, address indexed from, address indexed to, uint256 amount, uint64 executableAt
    );
    event RecoveryCancelled(uint256 indexed id, address indexed by);
    event RecoveryExecuted(uint256 indexed id, address indexed from, address indexed to, uint256 amount);

    error ZeroAddress();
    error NotFreezer();
    error AddressFrozen(address account);
    error ProtectedAddress(address account);
    error FreezeTooLong(uint64 until, uint64 limit);
    error FreezeInPast(uint64 until);
    error CannotShortenFreeze(uint64 until, uint64 current);
    error NotFrozen(address account);
    error ZeroAmount();
    error NoSuchRecovery(uint256 id);
    error RecoveryNotReady(uint64 executableAt);

    constructor(address treasury)
        ERC20("Confio", "CONFIO")
        ERC20Permit("Confio")
        Ownable(treasury)
    {
        guardian = treasury;
        emit GuardianSet(treasury);
        _mint(treasury, TOTAL_SUPPLY);
    }

    function isFrozen(address account) public view returns (bool) {
        return block.timestamp < frozenUntil[account];
    }

    // ═════════════════════════ Freeze ═══════════════════════════════════

    /// Sets the freeze end, extending or shortening one already running.
    /// The guardian may only lengthen: it can't release what the owner froze.
    function freeze(address account, uint64 until) external {
        if (account == address(0)) revert ZeroAddress();
        if (until <= block.timestamp) revert FreezeInPast(until);
        if (msg.sender == owner()) {
            uint64 limit = uint64(block.timestamp) + MAX_OWNER_FREEZE;
            if (until > limit) revert FreezeTooLong(until, limit);
        } else if (msg.sender == guardian) {
            if (isProtected[account]) revert ProtectedAddress(account);
            uint64 start = guardianEpisodeStart[account];
            if (start == 0 || block.timestamp >= uint256(start) + MAX_GUARDIAN_FREEZE + GUARDIAN_COOLDOWN) {
                start = uint64(block.timestamp);
                guardianEpisodeStart[account] = start;
            }
            uint64 limit = start + MAX_GUARDIAN_FREEZE;
            if (until > limit) revert FreezeTooLong(until, limit);
            if (until < frozenUntil[account]) revert CannotShortenFreeze(until, frozenUntil[account]);
        } else {
            revert NotFreezer();
        }
        frozenUntil[account] = until;
        emit Frozen(account, until, msg.sender);
    }

    function unfreeze(address account) external onlyOwner {
        frozenUntil[account] = 0;
        emit Unfrozen(account, msg.sender);
    }

    // ═════════════════════════ Recovery ═════════════════════════════════

    function proposeRecovery(address from, address to, uint256 amount) external onlyOwner returns (uint256 id) {
        if (to == address(0)) revert ZeroAddress();
        if (amount == 0) revert ZeroAmount();
        if (!isFrozen(from)) revert NotFrozen(from);
        if (isFrozen(to)) revert AddressFrozen(to);
        id = nextRecoveryId++;
        uint64 executableAt = uint64(block.timestamp) + RECOVERY_DELAY;
        recoveries[id] = Recovery(from, to, amount, executableAt);
        emit RecoveryProposed(id, from, to, amount, executableAt);
    }

    function cancelRecovery(uint256 id) external {
        if (msg.sender != owner() && msg.sender != guardian) revert NotFreezer();
        if (recoveries[id].executableAt == 0) revert NoSuchRecovery(id);
        delete recoveries[id];
        emit RecoveryCancelled(id, msg.sender);
    }

    function executeRecovery(uint256 id) external onlyOwner {
        Recovery memory r = recoveries[id];
        if (r.executableAt == 0) revert NoSuchRecovery(id);
        if (block.timestamp < r.executableAt) revert RecoveryNotReady(r.executableAt);
        if (!isFrozen(r.from)) revert NotFrozen(r.from);
        if (isFrozen(r.to)) revert AddressFrozen(r.to);
        delete recoveries[id];
        // ERC20._update directly: the one path that may debit a frozen
        // address. Supply is untouched.
        super._update(r.from, r.to, r.amount);
        emit RecoveryExecuted(id, r.from, r.to, r.amount);
    }

    // ═════════════════════════ Admin ════════════════════════════════════

    function setGuardian(address guardian_) external onlyOwner {
        guardian = guardian_;
        emit GuardianSet(guardian_);
    }

    function setProtected(address account, bool protected_) external onlyOwner {
        isProtected[account] = protected_;
        emit ProtectedSet(account, protected_);
    }

    /// One-way exit from the incident controls: with no owner and no
    /// guardian nothing can freeze or recover, and running freezes lapse
    /// within MAX_OWNER_FREEZE.
    function renounceOwnership() public override onlyOwner {
        guardian = address(0);
        emit GuardianSet(address(0));
        super.renounceOwnership();
    }

    // ═════════════════════════ Internals ════════════════════════════════

    function _update(address from, address to, uint256 value) internal override {
        if (isFrozen(from)) revert AddressFrozen(from);
        if (isFrozen(to)) revert AddressFrozen(to);
        super._update(from, to, value);
    }
}
