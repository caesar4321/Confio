// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable2StepUpgradeable} from "@openzeppelin/contracts-upgradeable/access/Ownable2StepUpgradeable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

/**
 * ConfioHeartbeat — on-chain liveness signal for Salida de emergencia.
 *
 * Confío posts `beat()` regularly while it operates. Emergency Exit opens
 * for every user only after the heartbeat has been silent for
 * `silenceRequired` (14 days at launch). The app puts `assertSilent()` as
 * the FIRST call of the exit batch it executes through ConfioBatchDelegate,
 * so the whole exit reverts on-chain while Confío is alive — regardless of
 * what RPC, DNS or server state the phone observed. Nothing a device can
 * see or fake opens the exit; only chain time past the last beat does.
 *
 * UUPS-upgradeable and owned by the Confío Safe, like the vaults: the
 * survivability narrative is about Confío failing as a company, not about
 * Confío acting against its users, so the owner keeps the ability to fix
 * or tune this contract.
 */
contract ConfioHeartbeat is Ownable2StepUpgradeable, UUPSUpgradeable {
    /// Floor for `silenceRequired`: a mis-set tiny value would open every
    /// exit (frozen accounts included) the moment a single beat is late.
    uint64 public constant MIN_SILENCE = 1 days;
    /// Ceiling: a fat-fingered value (milliseconds, max uint) would keep the
    /// exit shut forever — and after Confío dies nobody is left to fix it.
    uint64 public constant MAX_SILENCE = 365 days;

    // Storage is append-only. Every parent (OZ 5.x Ownable/Ownable2Step/
    // Initializable) uses ERC-7201 namespaced storage and UUPSUpgradeable has
    // none, so these plain slots cannot collide with a parent.

    /// Address allowed to post beats (the KMS-backed heartbeat signer).
    address public beater;
    /// Block timestamp of the most recent beat.
    uint64 public lastBeat;
    /// Silence after `lastBeat` that opens the exit.
    uint64 public silenceRequired;

    event Beat(uint64 at);
    event BeaterChanged(address indexed previous, address indexed current);
    event SilenceRequiredChanged(uint64 previous, uint64 current);

    error NotBeater();
    error ZeroAddress();
    error SilenceTooShort();
    error SilenceTooLong();
    /// The gate was read at an uninitialized address (the bare
    /// implementation, or a proxy deployed without init data).
    error NotInitialized();
    /// Exit attempted while Confío is alive; `opensAt` is the earliest
    /// timestamp at which it could succeed if no further beat arrives.
    error ConfioAlive(uint256 opensAt);

    constructor() {
        _disableInitializers();
    }

    function initialize(address owner_, address beater_, uint64 silenceRequired_) external initializer {
        if (owner_ == address(0) || beater_ == address(0)) revert ZeroAddress();
        _checkSilence(silenceRequired_);
        __Ownable_init(owner_);
        __Ownable2Step_init();
        beater = beater_;
        silenceRequired = silenceRequired_;
        // A fresh deployment counts as a beat: it must never start "silent".
        lastBeat = uint64(block.timestamp);
        emit BeaterChanged(address(0), beater_);
        emit SilenceRequiredChanged(0, silenceRequired_);
        emit Beat(lastBeat);
    }

    // ── liveness ────────────────────────────────────────────────────────

    function beat() external {
        if (msg.sender != beater) revert NotBeater();
        lastBeat = uint64(block.timestamp);
        emit Beat(lastBeat);
    }

    /// Earliest timestamp at which the exit opens, absent further beats.
    function opensAt() public view returns (uint256) {
        return uint256(lastBeat) + silenceRequired;
    }

    /// False on an uninitialized address: there the zeroed state would
    /// otherwise read as "silent since 1970" and open every exit.
    function isSilent() public view returns (bool) {
        return silenceRequired != 0 && block.timestamp >= opensAt();
    }

    /// Gate for the exit batch: reverts while Confío is alive, and fails
    /// closed if called on an uninitialized address.
    function assertSilent() external view {
        if (silenceRequired == 0) revert NotInitialized();
        if (block.timestamp < opensAt()) revert ConfioAlive(opensAt());
    }

    // ── admin ───────────────────────────────────────────────────────────

    function setBeater(address beater_) external onlyOwner {
        if (beater_ == address(0)) revert ZeroAddress();
        emit BeaterChanged(beater, beater_);
        beater = beater_;
    }

    /// Applies retroactively: lowering it opens the gate at once if the last
    /// beat is already older than the new value. Beat right before lowering.
    function setSilenceRequired(uint64 silenceRequired_) external onlyOwner {
        _checkSilence(silenceRequired_);
        emit SilenceRequiredChanged(silenceRequired, silenceRequired_);
        silenceRequired = silenceRequired_;
    }

    function _checkSilence(uint64 silence) private pure {
        if (silence < MIN_SILENCE) revert SilenceTooShort();
        if (silence > MAX_SILENCE) revert SilenceTooLong();
    }

    function _authorizeUpgrade(address) internal view override onlyOwner {}

    /// Ownerless would freeze the beater and the upgrade path forever.
    function renounceOwnership() public pure override {
        revert("renounce disabled");
    }
}
