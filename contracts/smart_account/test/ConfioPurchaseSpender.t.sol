// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ConfioSmartAccount} from "../ConfioSmartAccount.sol";
import {ConfioPurchaseSpender} from "../ConfioPurchaseSpender.sol";
import {IConfioSmartAccount} from "../interfaces/IConfioSmartAccount.sol";
import {SmartAccountBase} from "./Base.t.sol";
import {ITokenCallback, MockToken} from "./Mocks.sol";

/// An operator that, called back while the payment is delivered (through its
/// `to`, a token with a hook), tries to pull again: the only caller that
/// passes the operator check. Records what the second pull got.
contract ReentrantOperator is ITokenCallback {
    ConfioPurchaseSpender public spender;
    address public account;
    uint256 public ruleId;
    bool public reentered;
    bool public reentrySucceeded;
    bytes public reentryError;

    function set(ConfioPurchaseSpender spender_) external {
        spender = spender_;
    }

    function pull(address account_, uint256 id, uint256 usdtOut, address to) external {
        account = account_;
        ruleId = id;
        spender.pullTo(account_, id, usdtOut, to, bytes32("first"));
    }

    function onTokenReceived(address, uint256) external {
        if (reentered) return;
        reentered = true;
        (bool ok, bytes memory ret) = address(spender).call(
            abi.encodeCall(ConfioPurchaseSpender.pullTo, (account, ruleId, 1e18, address(0xBEEF), bytes32("again")))
        );
        reentrySucceeded = ok;
        reentryError = ret;
    }
}

/// The payment's `to`: when paid, it hands the turn back to the operator.
contract BouncingDeposit is ITokenCallback {
    ITokenCallback public immutable operator;

    constructor(ITokenCallback operator_) {
        operator = operator_;
    }

    function onTokenReceived(address from, uint256 value) external {
        operator.onTokenReceived(from, value);
    }
}

/// Not an account: on cardPull it pays the caller `pay` USDT, whatever was asked.
contract MisbehavingAccount {
    MockToken public immutable usdt;
    uint256 public pay;

    constructor(MockToken usdt_) {
        usdt = usdt_;
    }

    function setPay(uint256 pay_) external {
        pay = pay_;
    }

    function cardPull(uint256, uint256) external {
        usdt.mint(msg.sender, pay);
    }
}

/// Spec decisions 38 to 42 and open point P2: the purchase spender pulls
/// exactly the approved amount from the owner's "Compras con Confío IA" Card
/// rule and forwards all of it to the payment's deposit in the same
/// transaction, holding nothing. Tested against the REAL account, factory and
/// vaults (Base.t.sol).
contract ConfioPurchaseSpenderTest is SmartAccountBase {
    IConfioSmartAccount.Frequency constant MONTHLY_GAP = IConfioSmartAccount.Frequency.Monthly;

    event Forwarded(
        address indexed account, uint256 indexed ruleId, address indexed to, uint256 usdtOut, bytes32 ref
    );
    event CardPulled(uint256 indexed id, address indexed spender, uint256 usdtOut, uint256 usdSpent);

    address operator = makeAddr("purchaseOperator");
    address deposit = makeAddr("relayDeposit");
    address otherCard = makeAddr("otherCardIssuer");
    ConfioPurchaseSpender spender;

    function setUp() public override {
        super.setUp();
        _subscribedMonthly(1_000e18);
        _givePlus(address(acct), 1_000e18);
        spender = new ConfioPurchaseSpender(operator, IERC20(address(usdt)));
        vm.startPrank(safe);
        factory.setCardSpender(address(spender), true);
        factory.setCardSpender(otherCard, true);
        vm.stopPrank();
    }

    // ── helpers ─────────────────────────────────────────────────────────

    /// The "Compras con Confío IA" rule: US$200 per 28 days, payee the spender.
    function _purchaseRule(address tokenIn, uint256 cap) internal returns (uint256 id) {
        IConfioSmartAccount.RuleInput memory r = _rule(IConfioSmartAccount.RuleKind.Card, tokenIn, cap);
        r.frequency = MONTHLY_GAP;
        r.payee = address(spender);
        vm.prank(alice, relayer);
        id = acct.createRule(r);
    }

    function _pullTo(uint256 id, uint256 usdtOut, address to) internal {
        vm.prank(operator, operator);
        spender.pullTo(address(acct), id, usdtOut, to, bytes32("order-1"));
    }

    function _pullReverts(bytes memory err, uint256 id, uint256 usdtOut, address to) internal {
        vm.prank(operator, operator);
        vm.expectRevert(err);
        spender.pullTo(address(acct), id, usdtOut, to, bytes32("order-1"));
    }

    function _grossFor(uint256 net) internal view returns (uint256) {
        uint256 bps = cusd.feeBps();
        return (net * 10_000 + (10_000 - bps) - 1) / (10_000 - bps);
    }

    function _sel(bytes4 s) internal pure returns (bytes memory) {
        return abi.encodeWithSelector(s);
    }

    // ── construction ────────────────────────────────────────────────────

    function test_constructor_refusesZeroes_andKeepsItsTwoFacts() public {
        vm.expectRevert(ConfioPurchaseSpender.BadTarget.selector);
        new ConfioPurchaseSpender(address(0), IERC20(address(usdt)));
        vm.expectRevert(ConfioPurchaseSpender.BadTarget.selector);
        new ConfioPurchaseSpender(operator, IERC20(address(0)));
        assertEq(spender.operator(), operator);
        assertEq(address(spender.usdt()), address(usdt));
    }

    // ── the pull: exact, forwarded, nothing kept ────────────────────────

    function test_pullTo_forwardsExactUsdt_keepsNothing_countsTheGross() public {
        uint256 id = _purchaseRule(address(cusd), 200e18);
        uint256 net = 99.1e18;
        uint256 fees = cusd.accruedExitFees();
        vm.expectEmit(true, true, false, true, address(acct));
        emit CardPulled(id, address(spender), net, 100e18);
        vm.expectEmit(true, true, true, true, address(spender));
        emit Forwarded(address(acct), id, deposit, net, bytes32("order-1"));
        _pullTo(id, net, deposit);

        assertEq(usdt.balanceOf(deposit), net, "exactly the approved amount reaches the deposit");
        assertEq(usdt.balanceOf(address(spender)), 0, "nothing stays with the spender");
        assertEq(usdt.balanceOf(operator), 0, "nothing reaches the operator");
        assertEq(acct.cardSpentUsd(id), 100e18, "the gross, exit fee included, counts against the cap");
        assertEq(cusd.balanceOf(address(acct)), 900e18, "the account paid the gross");
        assertEq(cusd.accruedExitFees() - fees, 0.9e18, "the normal 0.9% exit, once");
        assertEq(usdt.balanceOf(address(acct)), 0);
        _noAllowances(address(acct));
        assertEq(usdt.allowance(address(spender), deposit), 0, "no allowance is ever given");
    }

    function test_pullTo_fromCusdPlus_exactUsdt_keepsNothing() public {
        _growPPlus(150);
        uint256 id = _purchaseRule(address(plus), 200e18);
        uint256 net = 57.123456789e18;
        uint256 cusdBefore = cusd.balanceOf(address(acct));
        // The spender's transaction has no sponsor as origin (it is Confío's
        // operator, not a sponsor): cUSD+ exits through redeemToUsdt.
        _pullTo(id, net, deposit);
        assertEq(usdt.balanceOf(deposit), net);
        assertEq(usdt.balanceOf(address(spender)), 0);
        assertEq(cusd.balanceOf(address(acct)), cusdBefore, "the other dollar untouched");
        uint256 gross = acct.cardSpentUsd(id);
        assertEq(gross - cusd.feeFor(gross), net, "the counted gross nets the approved amount");
    }

    /// Any amount within the cap: exact out, nothing kept, the count is the
    /// gross; never more than the cap in one period.
    function testFuzz_pullTo_exact_andNeverAboveTheCap(uint256 net1, uint256 net2) public {
        uint256 cap = 200e18;
        uint256 id = _purchaseRule(address(cusd), cap);
        net1 = bound(net1, 1, 250e18);
        net2 = bound(net2, 1, 250e18);
        uint256 spent;
        uint256[2] memory nets = [net1, net2];
        for (uint256 i = 0; i < 2; ++i) {
            uint256 gross = _grossFor(nets[i]);
            uint256 before = usdt.balanceOf(deposit);
            vm.prank(operator, operator);
            (bool ok, bytes memory ret) =
                address(spender).call(abi.encodeCall(spender.pullTo, (address(acct), id, nets[i], deposit, bytes32(i))));
            if (spent + gross <= cap) {
                assertTrue(ok, "a pull inside the cap was refused");
                spent += gross;
                assertEq(usdt.balanceOf(deposit) - before, nets[i], "exact");
            } else {
                assertFalse(ok, "a pull above the cap went through");
                assertEq(bytes4(ret), ConfioSmartAccount.CapExceeded.selector);
                assertEq(usdt.balanceOf(deposit), before);
            }
            assertEq(acct.cardSpentUsd(id), spent);
            assertEq(usdt.balanceOf(address(spender)), 0);
        }
        assertLe(spent, cap);
    }

    // ── the owner's cap ─────────────────────────────────────────────────

    function test_pullTo_atTheCap_refused_nothingMoves_nextPeriodPays() public {
        uint256 id = _purchaseRule(address(cusd), 200e18);
        uint64 start = uint64(vm.getBlockTimestamp());
        _pullTo(id, 148.65e18, deposit); // gross 150
        // 50.0101 > 50 left: refused whole, nothing counted or moved.
        _pullReverts(_sel(ConfioSmartAccount.CapExceeded.selector), id, 49.56e18, deposit);
        assertEq(acct.cardSpentUsd(id), 150e18);
        assertEq(usdt.balanceOf(deposit), 148.65e18);
        _pullTo(id, 49.55e18, deposit); // gross exactly 50
        _pullReverts(_sel(ConfioSmartAccount.CapExceeded.selector), id, 1, deposit);
        // The period is 28 days from the rule's first run.
        vm.warp(start + 28 days - 1);
        _pullReverts(_sel(ConfioSmartAccount.CapExceeded.selector), id, 1, deposit);
        vm.warp(start + 28 days);
        _pullTo(id, 9.91e18, deposit);
        assertEq(acct.cardSpentUsd(id), 10e18);
    }

    function test_pullTo_moreThanTheAccountHolds_refused() public {
        uint256 id = _purchaseRule(address(cusd), 5_000e18);
        vm.prank(operator, operator);
        vm.expectRevert();
        spender.pullTo(address(acct), id, 1_500e18, deposit, bytes32(0));
        assertEq(acct.cardSpentUsd(id), 0);
        assertEq(usdt.balanceOf(deposit), 0);
    }

    // ── the Safe's switches and the account's own checks ────────────────

    function test_pullTo_notAllowlisted_refused_untilAllowedAgain() public {
        uint256 id = _purchaseRule(address(cusd), 200e18);
        vm.prank(safe);
        factory.setCardSpender(address(spender), false);
        _pullReverts(_sel(ConfioSmartAccount.SpenderNotAllowed.selector), id, 1e18, deposit);
        vm.prank(safe);
        factory.setCardSpender(address(spender), true);
        _pullTo(id, 1e18, deposit);
    }

    function test_pullTo_cardsPaused_refused() public {
        uint256 id = _purchaseRule(address(cusd), 200e18);
        vm.prank(safe);
        factory.setCardPaused(true);
        _pullReverts(_sel(ConfioSmartAccount.SpenderNotAllowed.selector), id, 1e18, deposit);
        assertEq(usdt.balanceOf(deposit), 0);
    }

    /// A Card rule whose payee is another spender is not this spender's,
    /// and a rule that is no Card at all is refused too.
    function test_pullTo_ruleOfAnotherPayee_orNotACard_refused() public {
        IConfioSmartAccount.RuleInput memory r = _rule(IConfioSmartAccount.RuleKind.Card, address(cusd), 200e18);
        r.frequency = MONTHLY_GAP;
        r.payee = otherCard;
        vm.prank(alice, relayer);
        uint256 others = acct.createRule(r);
        _pullReverts(_sel(ConfioSmartAccount.NotSpender.selector), others, 1e18, deposit);

        IConfioSmartAccount.RuleInput memory s = _rule(IConfioSmartAccount.RuleKind.Send, address(cusd), 10e18);
        s.payee = address(spender);
        vm.prank(alice, relayer);
        uint256 sendId = acct.createRule(s);
        _pullReverts(_sel(ConfioSmartAccount.BadRule.selector), sendId, 1e18, deposit);
        _pullReverts(_sel(ConfioSmartAccount.BadRule.selector), 999, 1e18, deposit);

        uint256 id = _purchaseRule(address(cusd), 200e18);
        vm.prank(alice, relayer);
        acct.cancelRule(id);
        _pullReverts(_sel(ConfioSmartAccount.BadRule.selector), id, 1e18, deposit);
    }

    function test_pullTo_paymentDue_refused() public {
        uint256 id = _purchaseRule(address(cusd), 200e18);
        vm.warp(acct.paidUntil());
        _pullReverts(_sel(ConfioSmartAccount.BadState.selector), id, 1e18, deposit);
    }

    // ── who may call, and where it may go ───────────────────────────────

    function test_pullTo_onlyTheOperator() public {
        uint256 id = _purchaseRule(address(cusd), 200e18);
        address[6] memory others = [alice, relayer, eve, safe, address(acct), deposit];
        for (uint256 i = 0; i < others.length; ++i) {
            vm.prank(others[i], others[i]);
            vm.expectRevert(ConfioPurchaseSpender.NotOperator.selector);
            spender.pullTo(address(acct), id, 1e18, others[i], bytes32(0));
        }
        // Nobody but the spender pulls from its rule either.
        vm.prank(operator, operator);
        vm.expectRevert(ConfioSmartAccount.NotSpender.selector);
        acct.cardPull(id, 1e18);
        assertEq(acct.cardSpentUsd(id), 0);
    }

    function test_pullTo_badTargets_andZero_refused() public {
        uint256 id = _purchaseRule(address(cusd), 200e18);
        _pullReverts(_sel(ConfioPurchaseSpender.BadTarget.selector), id, 1e18, address(0));
        _pullReverts(_sel(ConfioPurchaseSpender.BadTarget.selector), id, 1e18, address(spender));
        _pullReverts(_sel(ConfioPurchaseSpender.BadTarget.selector), id, 1e18, address(acct));
        _pullReverts(_sel(ConfioPurchaseSpender.BadTarget.selector), id, 1e18, operator);
        _pullReverts(_sel(ConfioPurchaseSpender.BadAmount.selector), id, 0, deposit);
        assertEq(acct.cardSpentUsd(id), 0);
    }

    // ── nothing held, ever ──────────────────────────────────────────────

    /// USDT someone sent the spender stays where it is: never forwarded, never
    /// counted as this pull's.
    function test_pullTo_preExistingDust_untouched() public {
        uint256 id = _purchaseRule(address(cusd), 200e18);
        usdt.mint(address(spender), 5e18);
        _pullTo(id, 19.82e18, deposit);
        assertEq(usdt.balanceOf(deposit), 19.82e18, "exactly the pull");
        assertEq(usdt.balanceOf(address(spender)), 5e18, "the dust stays");
        assertEq(acct.cardSpentUsd(id), 20e18);
    }

    /// Whatever the `account` argument names, the spender forwards only what
    /// arrived from it, exactly: short or long, the whole call reverts.
    function test_pullTo_anythingButTheExactAmountReceived_reverts() public {
        MisbehavingAccount fake = new MisbehavingAccount(usdt);
        fake.setPay(1e18 - 1);
        vm.prank(operator, operator);
        vm.expectRevert(ConfioPurchaseSpender.NotReceived.selector);
        spender.pullTo(address(fake), 1, 1e18, deposit, bytes32(0));
        fake.setPay(1e18 + 1);
        vm.prank(operator, operator);
        vm.expectRevert(ConfioPurchaseSpender.NotReceived.selector);
        spender.pullTo(address(fake), 1, 1e18, deposit, bytes32(0));
        fake.setPay(0);
        vm.prank(operator, operator);
        vm.expectRevert(ConfioPurchaseSpender.NotReceived.selector);
        spender.pullTo(address(fake), 1, 1e18, deposit, bytes32(0));
        assertEq(usdt.balanceOf(deposit), 0);
        assertEq(usdt.balanceOf(address(spender)), 0);
    }

    /// The operator called back while the payment is delivered (a token with
    /// a hook) tries a second pull: refused, and the first counts once.
    function test_pullTo_reentry_refused_outerCountsOnce() public {
        ReentrantOperator evil = new ReentrantOperator();
        ConfioPurchaseSpender guarded = new ConfioPurchaseSpender(address(evil), IERC20(address(usdt)));
        evil.set(guarded);
        vm.prank(safe);
        factory.setCardSpender(address(guarded), true);
        IConfioSmartAccount.RuleInput memory r = _rule(IConfioSmartAccount.RuleKind.Card, address(cusd), 200e18);
        r.frequency = MONTHLY_GAP;
        r.payee = address(guarded);
        vm.prank(alice, relayer);
        uint256 id = acct.createRule(r);
        BouncingDeposit bouncer = new BouncingDeposit(evil);
        usdt.setCallsBack(address(bouncer), true);

        evil.pull(address(acct), id, 9.91e18, address(bouncer));
        assertTrue(evil.reentered(), "the callback ran");
        assertFalse(evil.reentrySucceeded(), "re-entry got through");
        assertEq(bytes4(evil.reentryError()), ConfioPurchaseSpender.Reentered.selector);
        assertEq(usdt.balanceOf(address(bouncer)), 9.91e18);
        assertEq(usdt.balanceOf(address(guarded)), 0);
        assertEq(acct.cardSpentUsd(id), 10e18);
        // The guard is released after a pull: the next one goes through.
        evil.pull(address(acct), id, 9.91e18, address(0xBEEF));
        assertEq(usdt.balanceOf(address(0xBEEF)), 9.91e18);
        assertEq(acct.cardSpentUsd(id), 20e18);
    }
}
