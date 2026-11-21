// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {ConfioSmartAccount} from "../ConfioSmartAccount.sol";
import {ConfioSmartAccountFactory} from "../ConfioSmartAccountFactory.sol";
import {ConfioSmartAccountFeeCollector} from "../ConfioSmartAccountFeeCollector.sol";
import {IConfioSmartAccountFactory} from "../interfaces/IConfioSmartAccountFactory.sol";
import {SmartAccountBase} from "./Base.t.sol";
import {MockFeed, MockToken, SponsorContract} from "./Mocks.sol";

contract ConfioSmartAccountFactoryV2 is ConfioSmartAccountFactory {
    constructor(address cusdPlus, address stockRouter) ConfioSmartAccountFactory(cusdPlus, stockRouter) {}

    function version() external pure returns (uint256) {
        return 2;
    }
}

/// Spec 4.3 and 10.2 "Factory" (I-16, I-17), plus the fee collector (4.2).
contract ConfioSmartAccountFactoryTest is SmartAccountBase {
    event AccountCreated(address indexed owner, address indexed account);
    event FeeScheduled(uint8 plan, uint256 newFeeUsd, uint64 effectiveAt);
    event Swept(address indexed token, uint256 amount);
    event DesignationApproved(address indexed account, address indexed beneficiary, uint64 window, uint64 expiresAt);
    event AcceptanceApproved(address indexed account, address indexed beneficiary, uint64 expiresAt);

    // ── accounts ────────────────────────────────────────────────────────

    function test_initialState() public view {
        assertEq(factory.owner(), safe);
        assertEq(factory.implementation(), address(implementation));
        assertEq(factory.feeUsd(1), MONTHLY);
        assertEq(factory.feeUsd(2), ANNUAL);
        assertEq(factory.monthlyFeeUsd(), MONTHLY);
        assertEq(factory.annualFeeUsd(), ANNUAL);
        assertEq(factory.FEE_CHANGE_DELAY(), 30 days);
        assertTrue(factory.allowedChallengeWindows(90 days));
        assertTrue(factory.allowedChallengeWindows(180 days));
        assertTrue(factory.allowedChallengeWindows(365 days));
        assertFalse(factory.allowedChallengeWindows(30 days));
        assertEq(factory.claimCooldown(), 30 days);
        assertEq(factory.forcedSaleNotice(), 7 days);
        assertFalse(factory.inheritanceEnabled());
        assertFalse(factory.relayerPaused());
        (address venue, address priceRef) = factory.confioSale();
        assertEq(venue, address(0));
        assertEq(priceRef, address(0));
        (uint256 next, uint64 at) = factory.scheduledFee(1);
        assertEq(next, 0);
        assertEq(at, 0);
        // The account's hard-coded limits (9.3).
        assertEq(implementation.MAX_MONTHLY_FEE_USD(), 29.99e18);
        assertEq(implementation.MAX_ANNUAL_FEE_USD(), 299.99e18);
        assertEq(implementation.MIN_CHALLENGE_WINDOW(), 90 days);
        assertEq(implementation.MIN_FORCED_SALE_NOTICE(), 3 days);
    }

    function test_oneAccountPerOwner_predictedAddressEqualsDeployed() public {
        assertEq(factory.accountOf(alice), address(acct));
        assertEq(factory.predictAddress(alice), address(acct));
        assertTrue(factory.isAccount(address(acct)));
        assertEq(acct.owner(), alice);
        assertEq(acct.nextRuleId(), 1);

        address predicted = factory.predictAddress(bob);
        assertFalse(factory.isAccount(predicted));
        vm.expectEmit(true, true, false, false, address(factory));
        emit AccountCreated(bob, predicted);
        ConfioSmartAccount bobs = _create(bob);
        assertEq(address(bobs), predicted);
        assertTrue(address(bobs) != address(acct));

        // I-17: written once, never overwritten.
        vm.prank(alice);
        vm.expectRevert(bytes("account exists"));
        factory.createAccount();
        assertEq(factory.accountOf(alice), address(acct));
        assertFalse(factory.isAccount(address(implementation)));
        assertFalse(factory.isAccount(eve));
    }

    function test_createAccount_canBePaused_existingAccountsUnaffected() public {
        vm.expectRevert();
        factory.pause();
        vm.prank(safe);
        factory.pause();
        vm.prank(bob);
        vm.expectRevert();
        factory.createAccount();
        // An existing account keeps working.
        _subscribedMonthly(1e18);
        vm.prank(safe);
        factory.unpause();
        _create(bob);
    }

    function test_initialize_guards() public {
        ConfioSmartAccountFactory logic = _newFactoryLogic();
        vm.expectRevert();
        logic.initialize(safe, address(implementation), MONTHLY, ANNUAL);
        vm.expectRevert();
        factory.initialize(eve, address(implementation), MONTHLY, ANNUAL);
        // An implementation built for another factory is refused.
        vm.expectRevert(bytes("implementation factory"));
        new ERC1967Proxy(
            address(logic),
            abi.encodeCall(ConfioSmartAccountFactory.initialize, (safe, address(implementation), MONTHLY, ANNUAL))
        );
    }

    // ── prices (decision 24) ────────────────────────────────────────────

    function test_scheduleFee_needsThirtyDaysNotice_andAppliesAtEffectiveAt() public {
        uint64 soon = uint64(block.timestamp + 30 days - 1);
        uint64 ok = uint64(block.timestamp + 30 days);
        vm.expectRevert();
        factory.scheduleFee(1, 19.99e18, ok);

        vm.startPrank(safe);
        vm.expectRevert(bytes("notice too short"));
        factory.scheduleFee(1, 19.99e18, soon);
        vm.expectRevert(bytes("bad plan"));
        factory.scheduleFee(0, 19.99e18, ok);
        vm.expectRevert(bytes("bad plan"));
        factory.scheduleFee(3, 19.99e18, ok);
        vm.expectRevert(bytes("fee out of range"));
        factory.scheduleFee(1, 0, ok);
        // Above the account's hard maximum.
        vm.expectRevert(bytes("fee out of range"));
        factory.scheduleFee(1, 29.99e18 + 1, ok);
        vm.expectRevert(bytes("fee out of range"));
        factory.scheduleFee(2, 299.99e18 + 1, ok);
        vm.expectEmit(false, false, false, true, address(factory));
        emit FeeScheduled(1, 19.99e18, ok);
        factory.scheduleFee(1, 19.99e18, ok);
        vm.stopPrank();

        assertEq(factory.feeUsd(1), MONTHLY, "old price until effectiveAt");
        (uint256 next, uint64 at) = factory.scheduledFee(1);
        assertEq(next, 19.99e18);
        assertEq(at, ok);
        assertEq(factory.feeUsd(2), ANNUAL, "the other plan is untouched");

        vm.warp(ok - 1);
        assertEq(factory.feeUsd(1), MONTHLY);
        vm.warp(ok);
        assertEq(factory.feeUsd(1), 19.99e18);
        (next, at) = factory.scheduledFee(1);
        assertEq(next, 0, "nothing pending once in force");
        assertEq(at, 0);

        // A later change starts from the price in force.
        vm.prank(safe);
        factory.scheduleFee(1, 24.99e18, uint64(block.timestamp + 40 days));
        assertEq(factory.feeUsd(1), 19.99e18);
        // Rescheduling replaces a change still waiting; never sooner than 30 days.
        vm.prank(safe);
        factory.scheduleFee(1, 9.99e18, uint64(block.timestamp + 30 days));
        vm.warp(block.timestamp + 30 days);
        assertEq(factory.feeUsd(1), 9.99e18);
    }

    // ── setters ─────────────────────────────────────────────────────────

    function test_setters_onlySafe_andBounded() public {
        vm.startPrank(eve);
        vm.expectRevert();
        factory.setChallengeWindow(120 days, true);
        vm.expectRevert();
        factory.setClaimCooldown(10 days);
        vm.expectRevert();
        factory.setForcedSaleNotice(10 days);
        vm.expectRevert();
        factory.enableInheritance();
        vm.expectRevert();
        factory.setRelayerPaused(true);
        vm.expectRevert();
        factory.setConfioSale(address(dex), address(btcFeed));
        vm.expectRevert();
        factory.upgradeToAndCall(address(1), "");
        vm.stopPrank();

        vm.startPrank(safe);
        vm.expectRevert(bytes("window too short"));
        factory.setChallengeWindow(89 days, true);
        vm.expectRevert(bytes("window too long"));
        factory.setChallengeWindow(1825 days + 1, true);
        factory.setChallengeWindow(1825 days, true);
        assertEq(factory.MAX_CHALLENGE_WINDOW(), 1825 days);
        factory.setChallengeWindow(120 days, true);
        assertTrue(factory.allowedChallengeWindows(120 days));
        factory.setChallengeWindow(90 days, false);
        assertFalse(factory.allowedChallengeWindows(90 days));

        vm.expectRevert(bytes("cooldown out of range"));
        factory.setClaimCooldown(1 days - 1);
        vm.expectRevert(bytes("cooldown out of range"));
        factory.setClaimCooldown(90 days + 1);
        factory.setClaimCooldown(60 days);
        assertEq(factory.claimCooldown(), 60 days);

        vm.expectRevert(bytes("notice out of range"));
        factory.setForcedSaleNotice(3 days - 1);
        vm.expectRevert(bytes("notice out of range"));
        factory.setForcedSaleNotice(60 days + 1);
        factory.setForcedSaleNotice(3 days);
        assertEq(factory.forcedSaleNotice(), 3 days);

        factory.enableInheritance();
        assertTrue(factory.inheritanceEnabled());
        vm.expectRevert(bytes("already enabled"));
        factory.enableInheritance();

        factory.setRelayerPaused(true);
        assertTrue(factory.relayerPaused());
        factory.setRelayerPaused(false);

        vm.expectRevert(bytes("non-contract"));
        factory.setConfioSale(eve, address(btcFeed));
        vm.expectRevert(bytes("non-contract"));
        factory.setConfioSale(address(dex), address(0));
        vm.stopPrank();
    }

    function test_ownership_twoStep_renounceDisabled_upgradeBySafeOnly() public {
        vm.prank(safe);
        vm.expectRevert(bytes("renounce disabled"));
        factory.renounceOwnership();

        vm.prank(safe);
        factory.transferOwnership(carol);
        assertEq(factory.owner(), safe, "two-step");
        vm.prank(carol);
        factory.acceptOwnership();
        assertEq(factory.owner(), carol);

        ConfioSmartAccountFactoryV2 v2 = new ConfioSmartAccountFactoryV2(address(plus), address(stockRouter));
        vm.prank(safe);
        vm.expectRevert();
        factory.upgradeToAndCall(address(v2), "");
        vm.prank(carol);
        factory.upgradeToAndCall(address(v2), "");
        assertEq(ConfioSmartAccountFactoryV2(address(factory)).version(), 2);
        // State survives; an existing account is the same code as before.
        assertEq(factory.accountOf(alice), address(acct));
        assertEq(factory.feeUsd(1), MONTHLY);
        assertEq(factory.predictAddress(alice), address(acct));
    }

    /// I-16: the Safe has no function that moves an account's assets or
    /// changes its owner or beneficiary. Every Safe-callable function of the
    /// factory is exercised; the account's assets and roles do not move.
    function test_safe_hasNoFunctionOverAccountAssetsOwnerOrBeneficiary() public {
        _subscribedMonthly(100e18);
        btcb.mint(address(acct), 1e18);
        _withBeneficiary();

        vm.startPrank(safe, safe);
        factory.scheduleFee(1, 29.99e18, uint64(block.timestamp + 30 days));
        factory.scheduleFee(2, 299.99e18, uint64(block.timestamp + 30 days));
        factory.setChallengeWindow(90 days, false);
        factory.setClaimCooldown(1 days);
        factory.setForcedSaleNotice(3 days);
        factory.setRelayerPaused(true);
        factory.setConfioSale(address(dex), address(btcFeed));
        factory.pause();
        // On the account itself the Safe is nobody.
        vm.expectRevert(ConfioSmartAccount.NotOwner.selector);
        acct.withdraw(address(cusd), 1);
        vm.expectRevert(ConfioSmartAccount.NotOwner.selector);
        acct.withdraw(address(cusd), 1, safe);
        vm.expectRevert(ConfioSmartAccount.NotOwner.selector);
        acct.removeBeneficiary();
        vm.expectRevert(ConfioSmartAccount.NotOwner.selector);
        acct.setBeneficiary(safe, 180 days);
        vm.expectRevert(ConfioSmartAccount.NotBeneficiary.selector);
        acct.initiateClaim();
        vm.expectRevert(ConfioSmartAccount.NotBeneficiary.selector);
        acct.executeClaim();
        vm.expectRevert(ConfioSmartAccount.NotRelayer.selector);
        acct.collectFee();
        vm.expectRevert(ConfioSmartAccount.NotFactory.selector);
        acct.initialize(safe);
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.returnAsset(address(cusd));
        vm.stopPrank();

        assertEq(acct.owner(), alice);
        assertEq(acct.beneficiary(), bob);
        assertEq(acct.challengeWindow(), 90 days, "snapshotted at designation");
        assertEq(cusd.balanceOf(address(acct)), 100e18);
        assertEq(btcb.balanceOf(address(acct)), 1e18);
        // The factory cannot call an account either: initialize is one-shot.
        vm.prank(address(factory));
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.initialize(safe);
    }

    // ── designation approvals (decision 26, I-18) ───────────────────────

    function test_approvals_recordedByTheRelayerOnly_forAnAccount_forOneHour() public {
        assertEq(factory.APPROVAL_TTL(), 1 hours);
        assertEq(factory.CUSD_PLUS(), address(plus));
        assertEq(factory.STOCK_ROUTER(), address(stockRouter));
        bytes32 key = keccak256(abi.encode(bob, uint64(180 days)));
        uint64 until = uint64(block.timestamp + 1 hours);

        vm.expectEmit(true, true, false, true, address(factory));
        emit DesignationApproved(address(acct), bob, 180 days, until);
        vm.prank(relayer, relayer);
        factory.approveDesignation(address(acct), bob, 180 days);
        assertEq(factory.designationApprovedUntil(address(acct), key), until);
        assertEq(factory.designationApprovedUntil(address(acct), keccak256(abi.encode(bob, uint64(90 days)))), 0);

        vm.expectEmit(true, true, false, true, address(factory));
        emit AcceptanceApproved(address(acct), bob, until);
        vm.prank(relayer, relayer);
        factory.approveAcceptance(address(acct), bob);
        assertEq(factory.acceptanceApprovedUntil(address(acct), bob), until);
        assertEq(factory.acceptanceApprovedUntil(address(acct), carol), 0);

        // Not the relayer: a stranger, the Safe, the relayer key not as the
        // origin, and a sponsor that is a contract.
        SponsorContract sponsorContract = new SponsorContract();
        vm.prank(safe);
        plus.setSponsor(address(sponsorContract), true);
        address[3] memory callers = [eve, safe, relayer];
        address[3] memory origins = [eve, safe, alice];
        for (uint256 i = 0; i < callers.length; ++i) {
            vm.prank(callers[i], origins[i]);
            vm.expectRevert(bytes("not relayer"));
            factory.approveDesignation(address(acct), bob, 180 days);
            vm.prank(callers[i], origins[i]);
            vm.expectRevert(bytes("not relayer"));
            factory.approveAcceptance(address(acct), bob);
        }
        vm.prank(relayer, relayer);
        (bool ok, bytes memory ret) = sponsorContract.call(
            address(factory), abi.encodeCall(factory.approveDesignation, (address(acct), bob, 180 days))
        );
        assertFalse(ok);
        assertEq(ret, abi.encodeWithSignature("Error(string)", "not relayer"));

        // Only for an account of this factory.
        vm.startPrank(relayer, relayer);
        vm.expectRevert(bytes("not an account"));
        factory.approveDesignation(eve, bob, 180 days);
        vm.expectRevert(bytes("not an account"));
        factory.approveAcceptance(address(implementation), bob);
        vm.stopPrank();

        // Blocked while the relayer is paused.
        vm.prank(safe);
        factory.setRelayerPaused(true);
        vm.startPrank(relayer, relayer);
        vm.expectRevert(bytes("relayer paused"));
        factory.approveDesignation(address(acct), bob, 180 days);
        vm.expectRevert(bytes("relayer paused"));
        factory.approveAcceptance(address(acct), bob);
        vm.stopPrank();
    }

    /// The approvals are appended after every earlier slot (UUPS): slots 0
    /// to 7 keep their meaning (_confioSale is 6 and 7), the two mappings are
    /// 8 and 9 (`forge inspect ConfioSmartAccountFactory storage-layout`).
    function test_approvals_storageIsAppended() public {
        vm.prank(safe);
        factory.setConfioSale(address(dex), address(btcFeed));
        assertEq(address(uint160(uint256(vm.load(address(factory), bytes32(uint256(6)))))), address(dex));
        assertEq(address(uint160(uint256(vm.load(address(factory), bytes32(uint256(7)))))), address(btcFeed));
        vm.startPrank(relayer, relayer);
        factory.approveDesignation(address(acct), bob, 180 days);
        factory.approveAcceptance(address(acct), bob);
        vm.stopPrank();
        bytes32 key = keccak256(abi.encode(bob, uint64(180 days)));
        bytes32 outer = keccak256(abi.encode(address(acct), uint256(8)));
        assertEq(uint256(vm.load(address(factory), keccak256(abi.encode(key, outer)))), block.timestamp + 1 hours);
        outer = keccak256(abi.encode(address(acct), uint256(9)));
        assertEq(uint256(vm.load(address(factory), keccak256(abi.encode(bob, outer)))), block.timestamp + 1 hours);
    }

    // ── setConfioSale validation (audit P3) ─────────────────────────────

    function test_setConfioSale_refusesTheStockRouterZeroAndADeadPriceRef() public {
        MockFeed feed = new MockFeed(0.5e8, 8);
        vm.startPrank(safe);
        vm.expectRevert(bytes("bad venue"));
        factory.setConfioSale(address(stockRouter), address(feed));
        vm.expectRevert(bytes("bad venue"));
        factory.setConfioSale(address(0), address(feed));
        // No decimals().
        vm.expectRevert(bytes("price ref: decimals"));
        factory.setConfioSale(address(dex), address(dex));
        // decimals() but no latestRoundData().
        MockToken noRounds = new MockToken("X", 8);
        vm.expectRevert(bytes("price ref: round"));
        factory.setConfioSale(address(dex), address(noRounds));
        // A zero or negative answer.
        feed.set(0, block.timestamp);
        vm.expectRevert(bytes("price ref: stale"));
        factory.setConfioSale(address(dex), address(feed));
        feed.set(-1, block.timestamp);
        vm.expectRevert(bytes("price ref: stale"));
        factory.setConfioSale(address(dex), address(feed));
        // Older than 26 hours.
        feed.set(0.5e8, block.timestamp - 26 hours - 1);
        vm.expectRevert(bytes("price ref: stale"));
        factory.setConfioSale(address(dex), address(feed));
        // Exactly 26 hours old is accepted.
        feed.set(0.5e8, block.timestamp - 26 hours);
        factory.setConfioSale(address(dex), address(feed));
        vm.stopPrank();
        (address venue, address priceRef) = factory.confioSale();
        assertEq(venue, address(dex));
        assertEq(priceRef, address(feed));
    }

    // ── fee collector (4.2) ─────────────────────────────────────────────

    function test_collector_anyoneSweepsBothTokens_onlyToTheTreasury() public {
        assertEq(address(collector.cusd()), address(cusd));
        assertEq(address(collector.cusdPlus()), address(plus));
        assertEq(collector.treasury(), treasury);
        // Nothing to sweep: a no-op.
        collector.sweep();

        _giveCusd(address(collector), 14.99e18);
        _givePlus(address(collector), 3e18);
        btcb.mint(address(collector), 1e18);
        vm.expectEmit(true, false, false, true, address(collector));
        emit Swept(address(cusd), 14.99e18);
        vm.expectEmit(true, false, false, true, address(collector));
        emit Swept(address(plus), 3e18);
        vm.prank(eve);
        collector.sweep();
        assertEq(cusd.balanceOf(treasury), 14.99e18);
        assertEq(plus.balanceOf(treasury), 3e18);
        assertEq(cusd.balanceOf(eve) + plus.balanceOf(eve), 0);

        // No other token, no other destination.
        vm.expectRevert(ConfioSmartAccountFeeCollector.UnsupportedToken.selector);
        collector.sweep(IERC20(address(btcb)));
    }

    function test_collector_aPausedTokenDoesNotHoldTheOther() public {
        _giveCusd(address(collector), 5e18);
        _givePlus(address(collector), 5e18);
        vm.prank(safe);
        cusd.pause();
        vm.expectRevert();
        collector.sweep();
        collector.sweep(IERC20(address(plus)));
        assertEq(plus.balanceOf(treasury), 5e18);
        vm.prank(safe);
        cusd.unpause();
        collector.sweep(IERC20(address(cusd)));
        assertEq(cusd.balanceOf(treasury), 5e18);
    }

    function test_collector_constructorGuards() public {
        vm.expectRevert(ConfioSmartAccountFeeCollector.InvalidConfiguration.selector);
        new ConfioSmartAccountFeeCollector(IERC20(eve), IERC20(address(plus)), treasury);
        vm.expectRevert(ConfioSmartAccountFeeCollector.InvalidConfiguration.selector);
        new ConfioSmartAccountFeeCollector(IERC20(address(cusd)), IERC20(eve), treasury);
        vm.expectRevert(ConfioSmartAccountFeeCollector.InvalidConfiguration.selector);
        new ConfioSmartAccountFeeCollector(IERC20(address(cusd)), IERC20(address(cusd)), treasury);
        vm.expectRevert(ConfioSmartAccountFeeCollector.InvalidConfiguration.selector);
        new ConfioSmartAccountFeeCollector(IERC20(address(cusd)), IERC20(address(plus)), address(0));
    }
}
