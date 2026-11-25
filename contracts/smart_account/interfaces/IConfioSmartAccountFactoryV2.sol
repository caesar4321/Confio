// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IConfioSmartAccountFactory} from "./IConfioSmartAccountFactory.sol";

/**
 * ABI of the Cuenta inteligente factory after the hands-off upgrade
 * (2026-11-25). A superset of IConfioSmartAccountFactory, in its own file so
 * the deployed v1 account implementation (which imports the v1 interface)
 * stays byte-for-byte reproducible.
 *
 * Implementations: `implementation()` is the one new accounts (createAccount
 * and migrate) are cloned from. Every implementation the factory has used is
 * listed in implementationAt(0 .. implementationCount() - 1), oldest first;
 * an account's own is implementationOf(account), read from its EIP-1167
 * code. predictAddressAt(owner, g) is the address of the account that exists
 * at generation g (whatever implementation it was cloned from) or, when none
 * exists yet, of the one createAccount or migrate would deploy there.
 */
interface IConfioSmartAccountFactoryV2 is IConfioSmartAccountFactory {
    event TradePausedSet(bool paused);
    event ImplementationAdded(address indexed implementation, uint256 index);
    /// The owner's live account `from` (an older implementation) was
    /// replaced as accountOf(owner) by `to`, at `generation`. `from` stays
    /// an account (isAccount) owned by the owner and keeps working.
    event AccountMigrated(address indexed owner, address indexed from, address indexed to, uint64 generation);

    /// Stops relayTrade and relayPurchase on every v2 account, and nothing
    /// else (the Safe's; it only withholds).
    function tradePaused() external view returns (bool);
    function setTradePaused(bool paused) external;

    /// For the caller's live account (not inherited, still theirs) when it
    /// is on an older implementation: opens a new account on
    /// `implementation()` at generationOf(caller) + 1 and points
    /// accountOf(caller) at it. Reverts while the old subscription is Active
    /// and not cancelled (status 1): cancel it first in the same batch. A
    /// cancelled one still paid (status 2) is carried: the new account is
    /// Active on the same plan (and pending plan change) until the same
    /// paidUntil, without a charge.
    /// Moves no asset: the owner's batch withdraws from the old account and
    /// deposits into the new one.
    function migrate() external returns (address account);

    /// EIP-1167 target of `account`; zero unless isAccount(account).
    function implementationOf(address account) external view returns (address);
    function implementationCount() external view returns (uint256);
    function implementationAt(uint256 index) external view returns (address);
}
