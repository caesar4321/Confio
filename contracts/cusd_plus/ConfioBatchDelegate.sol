// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ConfioBatchDelegate — EIP-7702 delegate for sponsored batch execution.
 *
 * Every Confío user EOA designates THIS one shared contract via a 7702
 * authorization. From then on, the Confío sponsor can broadcast a type-4
 * transaction to the user's own address, paying all gas, and the code below
 * executes the batch AS the EOA — but only a batch the EOA's key signed.
 * The user keeps their plain EOA: same key, same address, same balances,
 * and normal self-signed transactions keep working unchanged.
 *
 * Security model:
 *  - `execute` from anyone (the sponsor, in practice) requires an EIP-712
 *    signature by the EOA itself (`address(this)`) over the exact calls,
 *    a single-use nonce, and a deadline. The relayer can execute what the
 *    user signed — nothing else, not even reordered or resized batches.
 *  - The EOA calling itself (a self-signed tx) skips the signature check:
 *    possession of the key is strictly stronger authorization.
 *  - The nonce lives in an ERC-7201 namespaced slot so a future
 *    re-delegation to some other contract that uses slot 0 cannot collide.
 *  - `receive()` keeps plain BNB transfers to the EOA working — without it
 *    a delegated EOA would REVERT bare value transfers (mis-deposits,
 *    exchange withdrawals) — and `fallback()` tolerates unknown calldata
 *    the way a plain EOA silently would.
 *
 * Deliberately immutable: no owner, no upgrade path, no constructor args.
 * Changing behavior means deploying a new delegate and users re-designating.
 *
 * The EIP-712 domain binds `block.chainid` and `address(this)` LIVE at call
 * time (never cached at deploy time — under 7702 this code runs at every
 * user's address, not at its own deployment address).
 */
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";

contract ConfioBatchDelegate is ReentrancyGuardTransient {
    struct Call {
        address to;
        uint256 value;
        bytes data;
    }

    /// @custom:storage-location erc7201:confio.storage.BatchDelegate
    /// keccak256(abi.encode(uint256(keccak256("confio.storage.BatchDelegate")) - 1)) & ~bytes32(uint256(0xff))
    bytes32 private constant STORAGE_SLOT =
        0x90a10e3e6e0ef9c0307c0baf881893473293514cc333083b3696b5a0aa5eb100;

    bytes32 private constant DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    bytes32 private constant CALL_TYPEHASH =
        keccak256("Call(address to,uint256 value,bytes data)");
    // intentId binds the signature to a specific server-defined intent
    // (2026-07-31 migration audit): the server derives it as
    // keccak(kind:sourceId) — the flow purpose AND the domain row — and the
    // user's signature commits to it. The delegate does not act on it beyond
    // the digest; it exists so an intent for one flow/row cannot be presented
    // as another. A bare EOA self-call still bypasses the whole check.
    bytes32 private constant EXECUTE_TYPEHASH =
        keccak256("Execute(Call[] calls,uint256 nonce,uint256 deadline,bytes32 intentId)Call(address to,uint256 value,bytes data)");
    bytes32 private constant NAME_HASH = keccak256(bytes("ConfioBatchDelegate"));
    bytes32 private constant VERSION_HASH = keccak256(bytes("1"));

    event BatchExecuted(uint256 indexed nonce, uint256 numCalls);

    error EmptyBatch();
    error Expired();
    error BadNonce();
    error BadSignature();
    error CallFailed(uint256 index);

    /**
     * Execute `calls` as this EOA. Callable by anyone carrying a valid
     * signature by the EOA's key; callable by the EOA itself without one.
     * Atomic: any inner failure reverts the whole batch (nonce included).
     */
    function execute(
        Call[] calldata calls,
        uint256 nonce,
        uint256 deadline,
        bytes32 intentId,
        bytes calldata signature
    )
        external
        payable
        nonReentrant
    {
        if (calls.length == 0) revert EmptyBatch();

        uint256 current = _nonce();
        if (msg.sender != address(this)) {
            if (block.timestamp > deadline) revert Expired();
            if (nonce != current) revert BadNonce();
            if (ECDSA.recover(hashExecute(calls, nonce, deadline, intentId), signature) != address(this)) {
                revert BadSignature();
            }
        }
        // Consume a nonce on every path (self-calls too): an outstanding
        // signed-but-unsent intent is invalidated by ANY later action, so a
        // stale intent can never resurrect after the user moved on.
        _setNonce(current + 1);

        for (uint256 i; i < calls.length; ++i) {
            (bool ok, bytes memory ret) = calls[i].to.call{value: calls[i].value}(calls[i].data);
            if (!ok) {
                if (ret.length == 0) revert CallFailed(i);
                assembly ("memory-safe") {
                    revert(add(ret, 0x20), mload(ret))
                }
            }
        }
        emit BatchExecuted(current, calls.length);
    }

    /// Next expected intent nonce for this EOA.
    function nonces() external view returns (uint256) {
        return _nonce();
    }

    /**
     * EIP-712 digest the EOA must sign for `execute`. Public so clients,
     * the server's simulator, and tests can ask the chain for the exact
     * bytes instead of trusting a reimplementation.
     */
    function hashExecute(Call[] calldata calls, uint256 nonce, uint256 deadline, bytes32 intentId)
        public
        view
        returns (bytes32)
    {
        bytes32[] memory callHashes = new bytes32[](calls.length);
        for (uint256 i; i < calls.length; ++i) {
            callHashes[i] = keccak256(
                abi.encode(CALL_TYPEHASH, calls[i].to, calls[i].value, keccak256(calls[i].data))
            );
        }
        bytes32 domainSeparator = keccak256(
            abi.encode(DOMAIN_TYPEHASH, NAME_HASH, VERSION_HASH, block.chainid, address(this))
        );
        bytes32 structHash = keccak256(
            abi.encode(EXECUTE_TYPEHASH, keccak256(abi.encodePacked(callHashes)), nonce, deadline, intentId)
        );
        return keccak256(abi.encodePacked(hex"1901", domainSeparator, structHash));
    }

    /// Plain BNB transfers to a delegated EOA must keep working.
    receive() external payable {}

    /// Unknown calldata is tolerated (a bare EOA would silently accept it).
    fallback() external payable {}

    function _nonce() private view returns (uint256 n) {
        assembly ("memory-safe") {
            n := sload(STORAGE_SLOT)
        }
    }

    function _setNonce(uint256 n) private {
        assembly ("memory-safe") {
            sstore(STORAGE_SLOT, n)
        }
    }
}
