// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ConfioSmartAccount} from "../ConfioSmartAccount.sol";
import {IConfioSmartAccount} from "../interfaces/IConfioSmartAccount.sol";
import {SmartAccountBase} from "./Base.t.sol";

/// Spec 10.2, property tests: fuzzed sequences of calls by the owner, the
/// beneficiary, the relayer and a stranger. Invariants 1, 2, 3, 8, 9 and 14
/// (section 4.10) are checked after EVERY call of every sequence.
///
/// Each step picks one action from the seed, snapshots the account and the
/// wallets around it, performs the call (it may revert), and then checks
/// what changed against what that kind of caller is allowed to change.
contract ConfioSmartAccountPropertyTest is SmartAccountBase {
    uint256 constant STEPS = 48;
    uint256 constant TOKENS = 5;

    enum Class {
        Neutral, // time passing, deposits
        Owner,
        Trade,
        InheritedWithdraw,
        Accept,
        Initiate,
        ExecuteClaim,
        Collect,
        Notice,
        ForcedSale,
        ExecuteRule,
        Convert,
        Return,
        Latch,
        Stranger
    }

    struct Snap {
        address owner;
        address beneficiary;
        uint64 claimStartedAt;
        uint64 claimCooldownUntil;
        uint64 paidUntil;
        uint64 forcedSaleForPeriod;
        uint8 plan;
        uint8 nextPlan;
        bool inherited;
        uint256 fee;
        uint256[TOKENS] account;
        uint256[TOKENS] aliceWallet;
        uint256[TOKENS] bobWallet;
        uint256[TOKENS] carolWallet;
        uint256[TOKENS] collectorWallet;
    }

    address bridge = makeAddr("bridge");
    mapping(uint64 => bool) collectedForPaidUntil;
    mapping(uint64 => bool) soldForPeriod;
    uint256 successfulCollects;
    uint256 successfulClaims;
    uint256 successfulSales;
    uint256 ownerCallsEndingAClaim;

    function _token(uint256 i) internal view returns (IERC20) {
        if (i == 0) return IERC20(address(cusd));
        if (i == 1) return IERC20(address(plus));
        if (i == 2) return IERC20(address(usdt));
        if (i == 3) return IERC20(address(btcb));
        return IERC20(address(tsla));
    }

    function _balances(address who) internal view returns (uint256[TOKENS] memory b) {
        for (uint256 i = 0; i < TOKENS; ++i) {
            b[i] = _token(i).balanceOf(who);
        }
    }

    function _snap() internal view returns (Snap memory s) {
        s.owner = acct.owner();
        s.beneficiary = acct.beneficiary();
        s.claimStartedAt = acct.claimStartedAt();
        s.claimCooldownUntil = acct.claimCooldownUntil();
        s.paidUntil = acct.paidUntil();
        s.forcedSaleForPeriod = acct.forcedSaleForPeriod();
        s.plan = uint8(acct.plan());
        s.nextPlan = uint8(acct.nextPlan());
        s.inherited = acct.inherited();
        s.fee = acct.feeUsd();
        s.account = _balances(address(acct));
        s.aliceWallet = _balances(alice);
        s.bobWallet = _balances(bob);
        s.carolWallet = _balances(carol);
        s.collectorWallet = _balances(address(collector));
    }

    function setUp() public override {
        super.setUp();
        _enableInheritance();
        _giveCusd(address(acct), 120e18);
        _givePlus(address(acct), 60e18);
        btcb.mint(address(acct), 0.01e18);
        tsla.mint(address(acct), 1e18);
    }

    function testFuzz_invariants_1_2_3_8_9_14_holdAfterEveryCall(uint256 seed) public {
        for (uint256 i = 0; i < STEPS; ++i) {
            _step(uint256(keccak256(abi.encode(seed, i))));
        }
    }

    /// A fixed sequence that is known to reach the deep states (payment
    /// due, notice, forced sale, renewals, an executed claim, an inherited
    /// withdrawal), so the checks are known to run there and not only where
    /// the fuzzer happens to wander. Pairs are (action, argument).
    function test_invariants_holdAlongAScriptedLife() public {
        uint256 all = 6 << 8;
        uint256[2][24] memory script = [
            [uint256(2), 0], // subscribe, monthly
            [uint256(10), 0], // a daily send rule to carol
            [uint256(14), 1], // name bob
            [uint256(18), 1], // bob accepts
            [uint256(25), 0], // the relayer runs the rule
            [uint256(7), all + 4], // the owner takes all cUSD out (1540 % 5 == 0)
            [uint256(7), all], // and all cUSD+ (1536 % 5 == 1)
            [uint256(0), 30 days], // the period ends unpaid
            [uint256(22), 0], // collectFee: short, reverts
            [uint256(27), 0], // notice
            [uint256(21), 0], // bob initiates; the owner never signs again
            [uint256(0), 7 days],
            [uint256(28), 0], // forced sale of bitcoin, fee collected
            [uint256(0), 30 days],
            [uint256(17), 20], // a deposit of 20 cUSD
            [uint256(22), 0], // renewal
            [uint256(0), 30 days],
            [uint256(17), 20],
            [uint256(22), 0], // renewal
            [uint256(0), 24 days], // the challenge window is over
            [uint256(23), 0], // bob executes
            [uint256(24), (5 << 8) | 3], // and withdraws some bitcoin
            [uint256(30), 0], // a stranger tries
            [uint256(31), 0] // returnAsset on an inherited account
        ];
        for (uint256 i = 0; i < script.length; ++i) {
            uint256 action = script[i][0];
            // Time steps take seconds; _perform adds one.
            _stepWith(action, action == 0 ? script[i][1] - 1 : script[i][1]);
        }
        assertEq(successfulCollects, 2, "renewals");
        assertEq(successfulSales, 1, "forced sale");
        assertEq(successfulClaims, 1, "executed claim");
        assertTrue(acct.inherited());
        assertEq(acct.owner(), bob);
        assertEq(btcb.balanceOf(bob), 5);
    }

    /// I-9 along a script: each owner call, including updateRule, ends the
    /// claim pending before it.
    function test_invariant9_alongAScript() public {
        uint256[2][12] memory script = [
            [uint256(2), 0], // subscribe
            [uint256(10), 0], // a send rule
            [uint256(14), 1], // name bob (approved)
            [uint256(18), 1], // bob accepts (approved)
            [uint256(21), 0], // bob initiates
            [uint256(11), 0], // the owner updates rule 1: claim ends, cooldown
            [uint256(0), 31 days],
            [uint256(22), 0], // renewal
            [uint256(21), 0], // bob initiates again
            [uint256(9), 0], // removeBeneficiary: claim ends, no cooldown
            [uint256(14), 7], // naming without an approval fails
            [uint256(21), 0] // bob is no beneficiary
        ];
        for (uint256 i = 0; i < script.length; ++i) {
            uint256 action = script[i][0];
            _stepWith(action, action == 0 ? script[i][1] - 1 : script[i][1]);
        }
        assertEq(ownerCallsEndingAClaim, 2);
        assertEq(acct.beneficiary(), address(0));
        assertEq(acct.pendingBeneficiary(), address(0), "the unapproved naming did not happen");
    }

    // ── one step ────────────────────────────────────────────────────────

    function _step(uint256 r) internal {
        _stepWith(r % 32, r >> 16);
    }

    function _stepWith(uint256 action, uint256 arg) internal {
        Snap memory s = _snap();
        (Class class, bool ok) = _perform(action, arg);
        _check(class, ok, s);
    }

    function _perform(uint256 action, uint256 arg) internal returns (Class class, bool ok) {
        if (action <= 1) {
            // Time passes: up to 40 days. Feeds keep updating.
            vm.warp(block.timestamp + 1 + (arg % 40 days));
            _freshFeeds();
            return (Class.Neutral, true);
        }
        if (action == 2 || action == 3) return (Class.Owner, _ownerSubscribe(arg));
        if (action == 4) return (Class.Owner, _try(alice, abi.encodeCall(acct.changePlan, (_plan(arg)))));
        if (action == 5) return (Class.Owner, _try(alice, abi.encodeCall(acct.cancelSubscription, ())));
        if (action == 6) return (Class.Owner, _try(alice, abi.encodeCall(acct.undoCancel, ())));
        if (action == 7) {
            IERC20 t = _token(arg % TOKENS);
            uint256 held = t.balanceOf(address(acct));
            uint256 amount = (arg >> 8) % 7 == 6 ? held : (arg >> 8) % (held / 4 + 1);
            return (Class.Owner, _try(alice, abi.encodeWithSignature("withdraw(address,uint256)", address(t), amount)));
        }
        if (action == 8) return (Class.Owner, _try(alice, abi.encodeCall(acct.cancelClaim, ())));
        if (action == 9) return (Class.Owner, _try(alice, abi.encodeCall(acct.removeBeneficiary, ())));
        if (action == 10) return (Class.Owner, _ownerCreateRule(arg));
        if (action == 11) return (Class.Owner, _ownerUpdateRule(arg));
        if (action == 12) return (Class.Owner, _try(alice, abi.encodeCall(acct.cancelRule, (1 + (arg % 4)))));
        if (action == 13) return (Class.Trade, _ownerTrade(arg));
        if (action == 14 || action == 15) {
            address named = arg % 5 == 0 ? carol : bob;
            // The relay approves first (I-18), except now and then, when the
            // call must then fail.
            if (arg % 7 != 0) _relayerApprove(abi.encodeCall(factory.approveDesignation, (address(acct), named, 90 days)));
            return (Class.Owner, _try(alice, abi.encodeCall(acct.setBeneficiary, (named, 90 days))));
        }
        if (action == 16) return (Class.Owner, _try(alice, abi.encodeCall(acct.withdrawDesignation, ())));
        if (action == 17) {
            // Deposits are plain transfers.
            _giveCusd(address(acct), (arg % 30) * 1e18);
            if (arg % 3 == 0) usdt.mint(address(acct), 1e18 + (arg % 5e18));
            return (Class.Neutral, true);
        }
        if (action == 18 || action == 19 || action == 20) {
            address who = arg % 6 == 0 ? carol : bob;
            if (arg % 7 != 0) _relayerApprove(abi.encodeCall(factory.approveAcceptance, (address(acct), who)));
            return (Class.Accept, _tryFrom(who, relayer, abi.encodeCall(acct.acceptBeneficiary, ())));
        }
        if (action == 21) return (Class.Initiate, _tryFrom(bob, bob, abi.encodeCall(acct.initiateClaim, ())));
        if (action == 23) return (Class.ExecuteClaim, _tryFrom(bob, bob, abi.encodeCall(acct.executeClaim, ())));
        if (action == 24) return (Class.InheritedWithdraw, _bobWithdraw(arg));
        if (action == 22) return (Class.Collect, _tryFrom(relayer, relayer, abi.encodeCall(acct.collectFee, ())));
        if (action == 27) {
            return (Class.Notice, _tryFrom(relayer, relayer, abi.encodeCall(acct.startPaymentNotice, ())));
        }
        if (action == 28 || action == 29) return (Class.ForcedSale, _relayerForcedSale(arg));
        if (action == 25) {
            bytes memory data = abi.encode(arg % 2 == 0 ? CUSD_ : PLUS, uint256(1));
            return (
                Class.ExecuteRule,
                _tryFrom(relayer, relayer, abi.encodeCall(acct.executeRule, (1 + (arg % 4), data, address(0), 0)))
            );
        }
        if (action == 26) {
            uint256 held = usdt.balanceOf(address(acct));
            return (
                Class.Convert,
                _tryFrom(
                    relayer,
                    relayer,
                    abi.encodeCall(acct.convertUsdt, (uint8(arg % 2), (held * 9_860) / 10_000, address(0), 0))
                )
            );
        }
        if (action == 30) return (Class.Stranger, _strangerAttempt(arg));
        // 31: permissionless functions, called by the stranger.
        if (arg % 2 == 0) {
            return (
                Class.Return,
                _tryFrom(eve, eve, abi.encodeCall(acct.returnAsset, (address(_token((arg >> 4) % TOKENS)))))
            );
        }
        return (Class.Latch, _tryFrom(eve, eve, abi.encodeCall(acct.latchConfioSale, ())));
    }

    function _plan(uint256 arg) internal pure returns (IConfioSmartAccount.Plan) {
        return arg % 2 == 0 ? IConfioSmartAccount.Plan.Monthly : IConfioSmartAccount.Plan.Annual;
    }

    function _try(address who, bytes memory data) internal returns (bool ok) {
        return _tryFrom(who, relayer, data);
    }

    function _tryFrom(address who, address origin, bytes memory data) internal returns (bool ok) {
        vm.prank(who, origin);
        (ok,) = address(acct).call(data);
    }

    function _ownerSubscribe(uint256 arg) internal returns (bool) {
        return _try(alice, abi.encodeCall(acct.subscribe, (_plan(arg), type(uint256).max)));
    }

    function _sendRuleInput(uint256 arg) internal view returns (IConfioSmartAccount.RuleInput memory r) {
        r = _rule(IConfioSmartAccount.RuleKind.Send, arg % 2 == 0 ? address(cusd) : address(plus), 1e18 + (arg % 3e18));
        r.payee = carol;
        r.frequency = IConfioSmartAccount.Frequency(arg % 4);
        r.firstRunAt = uint64(block.timestamp + ((arg >> 8) % 3) * 1 days);
    }

    function _ownerCreateRule(uint256 arg) internal returns (bool) {
        return _try(alice, abi.encodeCall(acct.createRule, (_sendRuleInput(arg))));
    }

    function _ownerUpdateRule(uint256 arg) internal returns (bool) {
        return _try(alice, abi.encodeCall(acct.updateRule, (1 + ((arg >> 4) % 4), _sendRuleInput(arg))));
    }

    /// A relayer approval in the factory. It may fail (the account is not
    /// one yet, say); the account's own call then fails too.
    function _relayerApprove(bytes memory data) internal {
        vm.prank(relayer, relayer);
        (bool ok,) = address(factory).call(data);
        ok;
    }

    function _ownerTrade(uint256 arg) internal returns (bool) {
        uint256 amount = 1e18 + (arg % 4e18);
        bytes memory data = _swapBuyData(CUSD_, address(btcb), amount);
        return
            _try(
                alice, abi.encodeCall(acct.trade, (address(swapRouter), data, address(cusd), address(btcb), amount, 1))
            );
    }

    function _bobWithdraw(uint256 arg) internal returns (bool) {
        IERC20 t = _token(arg % TOKENS);
        uint256 amount = (arg >> 8) % (t.balanceOf(address(acct)) / 2 + 1);
        return _tryFrom(bob, bob, abi.encodeWithSignature("withdraw(address,uint256,address)", address(t), amount, bob));
    }

    function _relayerForcedSale(uint256 arg) internal returns (bool) {
        uint256 fee = acct.feeUsd();
        uint256 dollars = acct.dollarsUsd();
        // Sized for the shortfall when there is one; otherwise an arbitrary
        // sale that must be refused.
        uint256 net = fee > dollars ? fee - dollars + 0.01e18 : 1e18 + (arg % 20e18);
        IConfioSmartAccount.SaleLeg[] memory legs = _legs(_cryptoLeg(btcb, BTC_PRICE, uint8(arg % 2), net));
        return _tryFrom(relayer, relayer, abi.encodeCall(acct.forcedSale, (legs, 0, address(0), 0)));
    }

    /// The stranger tries the functions that are not theirs. Each must fail.
    function _strangerAttempt(uint256 arg) internal returns (bool ok) {
        uint256 which = arg % 10;
        address origin = (arg >> 8) % 2 == 0 ? eve : relayer;
        bytes memory data;
        if (which == 0) data = abi.encodeWithSignature("withdraw(address,uint256)", address(cusd), 1);
        else if (which == 1) data = abi.encodeWithSignature("withdraw(address,uint256,address)", address(cusd), 1, eve);
        else if (which == 2) data = abi.encodeCall(acct.setBeneficiary, (eve, 90 days));
        else if (which == 3) data = abi.encodeCall(acct.acceptBeneficiary, ());
        else if (which == 4) data = abi.encodeCall(acct.initiateClaim, ());
        else if (which == 5) data = abi.encodeCall(acct.executeClaim, ());
        else if (which == 6) data = abi.encodeCall(acct.collectFee, ());
        else if (which == 7) data = abi.encodeCall(acct.cancelClaim, ());
        else if (which == 8) data = abi.encodeCall(acct.initialize, (eve));
        else data = abi.encodeCall(acct.removeBeneficiary, ());
        ok = _tryFrom(eve, origin, data);
        assertFalse(ok, "a stranger's call succeeded");
    }

    // ── the checks ──────────────────────────────────────────────────────

    function _check(Class class, bool ok, Snap memory s) internal {
        Snap memory n = _snap();

        // I-14: no allowance is left behind by any call.
        _noAllowances(address(acct));

        // The relayer and the stranger never end up holding anything.
        for (uint256 i = 0; i < TOKENS; ++i) {
            assertEq(_token(i).balanceOf(eve), 0, "stranger holds a token");
            assertEq(_token(i).balanceOf(relayer), 0, "relayer holds a token");
            assertEq(_token(i).balanceOf(bridge), 0, "bridge holds a token");
        }

        // I-2: owner changes only in executeClaim, only to the stored
        // beneficiary.
        if (n.owner != s.owner) {
            assertTrue(class == Class.ExecuteClaim && ok, "owner changed outside executeClaim");
            assertEq(n.owner, s.beneficiary, "owner became someone other than the beneficiary");
            assertTrue(s.beneficiary != address(0));
            assertTrue(n.inherited);
            ++successfulClaims;
        }
        if (s.inherited) assertTrue(n.inherited, "inherited is terminal");

        // I-9: every successful owner-signed call leaves no claim pending.
        // One that ended a claim set the cooldown, except removeBeneficiary,
        // which clears it together with the designation.
        if (ok && (class == Class.Owner || class == Class.Trade || class == Class.InheritedWithdraw)) {
            assertEq(n.claimStartedAt, 0, "I-9: an owner call left a claim pending");
            if (s.claimStartedAt != 0) {
                ++ownerCallsEndingAClaim;
                if (n.claimCooldownUntil == 0) {
                    assertEq(n.beneficiary, address(0), "I-9: claim ended without a cooldown");
                } else {
                    assertEq(n.claimCooldownUntil, block.timestamp + 30 days, "I-9: cooldown length");
                }
            }
        }

        // I-8: no relayer function and no permissionless function changes
        // claimStartedAt, claimCooldownUntil or beneficiary.
        if (
            class == Class.Collect || class == Class.Notice || class == Class.ForcedSale || class == Class.ExecuteRule
                || class == Class.Convert || class == Class.Return || class == Class.Latch || class == Class.Stranger
                || class == Class.Neutral
        ) {
            assertEq(n.claimStartedAt, s.claimStartedAt, "claimStartedAt changed");
            assertEq(n.claimCooldownUntil, s.claimCooldownUntil, "claimCooldownUntil changed");
            assertEq(n.beneficiary, s.beneficiary, "beneficiary changed");
            assertEq(n.owner, s.owner);
            // I-4, in passing: the plan moves only to the nextPlan the owner
            // signed, and nextPlan is never set by these callers.
            if (n.plan != s.plan) assertEq(n.plan, s.nextPlan, "plan changed to something the owner did not sign");
            if (n.nextPlan != s.nextPlan) assertEq(n.nextPlan, 0);
        }

        // I-3: one fee per paidUntil value, a full period from now, never
        // more than feeUsd, and feeUsd never above the hard maximum.
        assertLe(n.fee, n.plan == 2 || n.nextPlan == 2 ? 299.99e18 : 29.99e18, "fee above the hard maximum");
        if (class == Class.Collect && ok) {
            assertGe(block.timestamp, s.paidUntil, "collected before the period ended");
            assertFalse(collectedForPaidUntil[s.paidUntil], "two fees for one paidUntil");
            collectedForPaidUntil[s.paidUntil] = true;
            ++successfulCollects;
            assertEq(n.paidUntil, block.timestamp + (n.plan == 2 ? 365 days : 30 days), "period length");
            uint256 p = plus.pPlus();
            uint256 cusdTaken = n.collectorWallet[0] - s.collectorWallet[0];
            uint256 sharesTaken = n.collectorWallet[1] - s.collectorWallet[1];
            uint256 value = cusdTaken + (sharesTaken * p) / 1e18;
            assertLe(value, s.fee + p / 1e18 + 1, "collected more than the fee");
            assertGe(value + 1, s.fee, "collected less than the fee");
            assertEq(s.account[0] - n.account[0], cusdTaken);
            assertEq(s.account[1] - n.account[1], sharesTaken);
            // Straight away again: refused.
            assertFalse(_tryFrom(relayer, relayer, abi.encodeCall(acct.collectFee, ())), "second collect in a period");
        } else if (class == Class.Collect) {
            assertEq(n.paidUntil, s.paidUntil);
        }
        if (class == Class.ForcedSale && ok) {
            // I-5, in passing: once per unpaid period.
            assertFalse(soldForPeriod[s.paidUntil], "two forced sales for one period");
            soldForPeriod[s.paidUntil] = true;
            ++successfulSales;
            assertEq(n.forcedSaleForPeriod, s.paidUntil);
            assertGt(n.paidUntil, s.paidUntil);
        }
        if (n.paidUntil != s.paidUntil) {
            assertTrue(
                ((class == Class.Collect || class == Class.ForcedSale || class == Class.Owner) && ok)
                    || class == Class.ExecuteClaim,
                "paidUntil moved"
            );
        }

        // I-1: a balance of the account falls only towards an allowed sink.
        for (uint256 i = 0; i < TOKENS; ++i) {
            if (n.account[i] >= s.account[i]) continue;
            uint256 fell = s.account[i] - n.account[i];
            assertTrue(ok, "a reverted call moved a balance");
            if (class == Class.Owner) {
                // To the owner's wallet, or the first fee to the collector.
                uint256 toOwner = n.aliceWallet[i] - s.aliceWallet[i];
                uint256 toCollector = n.collectorWallet[i] - s.collectorWallet[i];
                assertEq(fell, toOwner + toCollector, "owner call: unexplained outflow");
                assertFalse(s.inherited);
            } else if (class == Class.Trade) {
                assertEq(i, 0, "trade: only the dollar spent may fall");
                assertGt(n.account[3], s.account[3], "trade: nothing bought");
            } else if (class == Class.InheritedWithdraw) {
                assertTrue(s.inherited);
                assertEq(fell, n.bobWallet[i] - s.bobWallet[i], "inherited withdraw: not to the new owner");
            } else if (class == Class.Collect) {
                assertEq(fell, n.collectorWallet[i] - s.collectorWallet[i], "fee: not to the collector");
            } else if (class == Class.ForcedSale) {
                if (i == 3) {
                    // The sold token, pulled by the swap router.
                    assertGt(n.collectorWallet[0] + n.collectorWallet[1], s.collectorWallet[0] + s.collectorWallet[1]);
                } else {
                    assertLe(i, 1, "forced sale: only bitcoin and the fee dollars move");
                    assertLe(fell, n.collectorWallet[i] - s.collectorWallet[i], "forced sale: fee not to the collector");
                }
            } else if (class == Class.ExecuteRule) {
                assertLe(i, 1, "send rule: only a dollar moves");
                // In kind or converted, the stored payee received it.
                assertGt(n.carolWallet[0] + n.carolWallet[1], s.carolWallet[0] + s.carolWallet[1], "payee not paid");
                assertLe(fell, 4e18 + 1, "send rule: more than the rule's amount");
            } else if (class == Class.Convert) {
                assertEq(i, 2, "convertUsdt: only USDT falls");
                assertGt(n.account[0] + n.account[1], s.account[0] + s.account[1], "convertUsdt: no dollars back");
            } else if (class == Class.Return) {
                assertEq(fell, n.aliceWallet[i] - s.aliceWallet[i], "return: not to the owner");
                assertEq(s.owner, alice);
            } else {
                assertTrue(false, "a balance fell in a call that may not move assets");
            }
        }

        // The old owner's wallet gains only through alice's own calls or the
        // permissionless return; the beneficiary's only as the new owner.
        for (uint256 i = 0; i < TOKENS; ++i) {
            if (n.aliceWallet[i] > s.aliceWallet[i]) {
                assertTrue(class == Class.Owner || class == Class.Return, "old owner's wallet gained");
            }
            if (n.bobWallet[i] > s.bobWallet[i]) {
                assertTrue(class == Class.InheritedWithdraw, "beneficiary's wallet gained");
            }
            if (n.collectorWallet[i] > s.collectorWallet[i]) {
                assertTrue(
                    class == Class.Collect || class == Class.ForcedSale || class == Class.Owner, "collector gained"
                );
            }
        }
    }
}
