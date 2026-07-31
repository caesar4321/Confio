// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ConfioPayContract} from "../ConfioPayContract.sol";

contract MockToken is ERC20 {
    constructor(string memory n) ERC20(n, n) {}
    function mint(address to, uint256 amt) external { _mint(to, amt); }
}

contract ConfioPayContractTest is Test {
    MockToken cusdPlus;
    MockToken usdt;
    MockToken alien;
    ConfioPayContract pay;

    address safeOwner = makeAddr("safeOwner");
    address payer = makeAddr("payer");
    address merchant = makeAddr("merchant");
    address stranger = makeAddr("stranger");

    uint256 constant WAD = 1e18;

    function setUp() public {
        cusdPlus = new MockToken("cUSD+");
        usdt = new MockToken("USDT");
        alien = new MockToken("ALIEN");
        pay = new ConfioPayContract(address(cusdPlus), address(usdt), safeOwner);

        for (uint256 i = 0; i < 3; i++) {
            MockToken t = [cusdPlus, usdt, alien][i];
            t.mint(payer, 1_000e18);
            vm.prank(payer);
            t.approve(address(pay), type(uint256).max);
        }
    }

    // ── Fee math (parity with the Algorand builder + bsc_flow.py) ────

    function test_fee_ceiling_vectors() public view {
        assertEq(pay.feeFor(10_000), 90);      // exact multiple: flat 0.9%
        assertEq(pay.feeFor(10_001), 91);      // one unit over rounds UP
        assertEq(pay.feeFor(1), 1);            // dust pays a full unit
        assertEq(pay.feeFor(1_111), 10);       // ceil(9.999)
        assertEq(pay.feeFor(10 * WAD), (10 * WAD * 90 + 9_999) / 10_000);
    }

    function testFuzz_fee_never_exceeds_gross_and_never_underpays(uint256 gross) public view {
        gross = bound(gross, 1, 1e30);
        uint256 fee = pay.feeFor(gross);
        assertLe(fee, gross);
        assertGe(fee * 10_000, gross * 90); // ceiling: never under 0.9%
        assertLt((fee - 1) * 10_000, gross * 90); // minimal: one unit less would underpay
    }

    // ── pay() ────────────────────────────────────────────────────────

    function test_pay_splits_net_and_accrues_fee() public {
        vm.prank(payer);
        uint256 fee = pay.pay("inv-1", address(usdt), 10 * WAD, merchant);
        assertEq(usdt.balanceOf(merchant), 10 * WAD - fee);
        assertEq(usdt.balanceOf(address(pay)), fee);
        assertEq(pay.accruedFees(address(usdt)), fee);
        assertTrue(pay.paymentDone(
            pay.paymentKey("inv-1", payer, address(usdt), 10 * WAD, merchant)));
    }

    function test_pay_cusd_plus_token() public {
        vm.prank(payer);
        uint256 fee = pay.pay("inv-2", address(cusdPlus), 5 * WAD, merchant);
        assertEq(cusdPlus.balanceOf(merchant), 5 * WAD - fee);
        assertEq(pay.accruedFees(address(cusdPlus)), fee);
        assertEq(pay.accruedFees(address(usdt)), 0, "per-token accounting");
    }

    function test_pay_replay_rejected() public {
        vm.startPrank(payer);
        pay.pay("inv-3", address(usdt), 1e18, merchant);
        vm.expectRevert("payment done");
        pay.pay("inv-3", address(usdt), 1e18, merchant);
        vm.stopPrank();
    }

    /// AUDIT REGRESSION (2026-07-31 [P1]): keying the replay guard on the
    /// invoice id alone let ANY caller who learned an id burn it with a
    /// 1-wei self-payment and permanently brick the real payment.
    function test_griefer_cannot_brick_a_real_invoice() public {
        address griefer = makeAddr("griefer");
        usdt.mint(griefer, 10e18);
        vm.startPrank(griefer);
        usdt.approve(address(pay), type(uint256).max);
        // The old 1-wei brick is now impossible outright: the merchant must
        // receive something.
        vm.expectRevert("amount too small");
        pay.pay("inv-real", address(usdt), 1, merchant);
        // Even a well-formed spoiler on the same invoice id only consumes
        // its OWN terms key.
        pay.pay("inv-real", address(usdt), 2e18, merchant);
        vm.stopPrank();

        // The real payment still goes through untouched.
        vm.prank(payer);
        uint256 fee = pay.pay("inv-real", address(usdt), 10 * WAD, merchant);
        assertEq(usdt.balanceOf(merchant), (2e18 - pay.feeFor(2e18)) + (10 * WAD - fee));
    }

    function test_self_payment_rejected() public {
        vm.prank(payer);
        vm.expectRevert("self payment");
        pay.pay("inv-self", address(usdt), 1e18, payer);
    }

    function test_dust_payment_rejected() public {
        // gross == 1 → fee == 1 → merchant would receive zero.
        vm.prank(payer);
        vm.expectRevert("amount too small");
        pay.pay("inv-dust", address(usdt), 1, merchant);
    }

    function test_pay_alien_token_rejected() public {
        vm.prank(payer);
        vm.expectRevert("token not allowed");
        pay.pay("inv-4", address(alien), 1e18, merchant);
    }

    function test_pay_merchant_cannot_be_contract_itself() public {
        vm.prank(payer);
        vm.expectRevert("bad merchant");
        pay.pay("inv-5", address(usdt), 1e18, address(pay));
    }

    function test_pay_insufficient_allowance_reverts_whole_payment() public {
        address poor = makeAddr("poor");
        usdt.mint(poor, 1e18);
        vm.startPrank(poor);
        usdt.approve(address(pay), 1e18 - 1); // one wei short of gross
        vm.expectRevert();
        pay.pay("inv-6", address(usdt), 1e18, merchant);
        vm.stopPrank();
        assertEq(usdt.balanceOf(merchant), 0, "atomic: nothing moved");
        assertFalse(
            pay.paymentDone(pay.paymentKey("inv-6", poor, address(usdt), 1e18, merchant)),
            "replay key rolled back");
    }

    function test_pay_paused_rejected() public {
        vm.prank(safeOwner);
        pay.pause();
        vm.prank(payer);
        vm.expectRevert();
        pay.pay("inv-7", address(usdt), 1e18, merchant);
    }

    // ── collectFees ──────────────────────────────────────────────────

    function test_collect_owner_only_and_bounded() public {
        vm.prank(payer);
        uint256 fee = pay.pay("inv-8", address(usdt), 100 * WAD, merchant);

        vm.prank(stranger);
        vm.expectRevert();
        pay.collectFees(address(usdt), stranger, fee);

        vm.prank(safeOwner);
        vm.expectRevert("exceeds accrued fees");
        pay.collectFees(address(usdt), safeOwner, fee + 1);

        vm.prank(safeOwner);
        pay.collectFees(address(usdt), safeOwner, fee);
        assertEq(usdt.balanceOf(safeOwner), fee);
        assertEq(pay.accruedFees(address(usdt)), 0);
    }

    function test_stray_tokens_not_collectible() public {
        usdt.mint(address(pay), 50e18); // direct transfer, not a payment
        vm.prank(safeOwner);
        vm.expectRevert("exceeds accrued fees");
        pay.collectFees(address(usdt), safeOwner, 1);
    }
}
