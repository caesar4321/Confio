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
    MockToken confio;
    MockToken alien;
    ConfioPayContract pay;

    address safeOwner = makeAddr("safeOwner");
    address payer = makeAddr("payer");
    address merchant = makeAddr("merchant");
    address stranger = makeAddr("stranger");

    // The backend authorizer (the sponsor KMS key on-chain).
    uint256 signerKey = 0xA11CE;
    address paymentSigner = vm.addr(0xA11CE);

    bytes32 constant PAY_TYPEHASH = keccak256(
        "Pay(bytes32 invoiceId,address payer,address token,uint256 gross,address merchant,uint256 deadline)"
    );

    uint256 constant WAD = 1e18;
    uint256 deadline;

    function setUp() public {
        cusdPlus = new MockToken("cUSD+");
        usdt = new MockToken("USDT");
        confio = new MockToken("CONFIO");
        alien = new MockToken("ALIEN");
        pay = new ConfioPayContract(
            address(cusdPlus), address(usdt), address(confio), paymentSigner, safeOwner);
        deadline = block.timestamp + 3600;

        for (uint256 i = 0; i < 4; i++) {
            MockToken t = [cusdPlus, usdt, confio, alien][i];
            t.mint(payer, 1_000e18);
            vm.prank(payer);
            t.approve(address(pay), type(uint256).max);
        }
    }

    // ── EIP-712 authorization helper ─────────────────────────────────────

    function _auth(
        uint256 key,
        bytes32 invoiceId,
        address who,
        address token,
        uint256 gross,
        address to,
        uint256 dl
    ) internal view returns (bytes memory) {
        bytes32 digest = pay.payDigest(invoiceId, who, token, gross, to, dl);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, digest);
        return abi.encodePacked(r, s, v);
    }

    // A correctly-signed authorization for `payer` from the real signer.
    function _sig(bytes32 invoiceId, address token, uint256 gross, address to)
        internal view returns (bytes memory)
    {
        return _auth(signerKey, invoiceId, payer, token, gross, to, deadline);
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
        bytes memory sig = _sig("inv-1", address(usdt), 10 * WAD, merchant);
        vm.prank(payer);
        uint256 fee = pay.pay("inv-1", address(usdt), 10 * WAD, merchant, deadline, sig);
        assertEq(usdt.balanceOf(merchant), 10 * WAD - fee);
        assertEq(usdt.balanceOf(address(pay)), fee);
        assertEq(pay.accruedFees(address(usdt)), fee);
        assertTrue(pay.invoiceDone("inv-1"));
    }

    function test_pay_cusd_plus_token() public {
        bytes memory sig = _sig("inv-2", address(cusdPlus), 5 * WAD, merchant);
        vm.prank(payer);
        uint256 fee = pay.pay("inv-2", address(cusdPlus), 5 * WAD, merchant, deadline, sig);
        assertEq(cusdPlus.balanceOf(merchant), 5 * WAD - fee);
        assertEq(pay.accruedFees(address(cusdPlus)), fee);
        assertEq(pay.accruedFees(address(usdt)), 0, "per-token accounting");
    }

    /// The second charge denomination (2026-08-01): a CONFIO invoice is a
    /// token COUNT, but settles through the identical fee/guard path.
    function test_pay_confio_token() public {
        bytes memory sig = _sig("inv-confio", address(confio), 250 * WAD, merchant);
        vm.prank(payer);
        uint256 fee = pay.pay("inv-confio", address(confio), 250 * WAD, merchant, deadline, sig);
        assertEq(fee, pay.feeFor(250 * WAD), "same 0.9% ceiling rule");
        assertEq(confio.balanceOf(merchant), 250 * WAD - fee);
        assertEq(pay.accruedFees(address(confio)), fee);
        assertEq(pay.accruedFees(address(cusdPlus)), 0, "per-token accounting");
        assertTrue(pay.invoiceDone("inv-confio"));
    }

    /// AUDIT ([P1], 2026-07-31): the global invoiceDone guard means exactly
    /// ONE authorized payment per invoice id ever settles — no honest
    /// double-charge, even from two different (authorized) payers.
    function test_invoice_single_settlement() public {
        bytes memory sig = _sig("inv-3", address(usdt), 1e18, merchant);
        vm.prank(payer);
        pay.pay("inv-3", address(usdt), 1e18, merchant, deadline, sig);
        vm.prank(payer);
        vm.expectRevert("invoice done");
        pay.pay("inv-3", address(usdt), 1e18, merchant, deadline, sig);
    }

    /// A second payer, even with a valid authorization for the SAME invoice,
    /// cannot double-charge it once it is settled.
    function test_second_authorized_payer_cannot_double_settle() public {
        address payer2 = makeAddr("payer2");
        usdt.mint(payer2, 100e18);
        vm.prank(payer2);
        usdt.approve(address(pay), type(uint256).max);

        bytes memory sig1 = _sig("inv-dup", address(usdt), 2e18, merchant);
        vm.prank(payer);
        pay.pay("inv-dup", address(usdt), 2e18, merchant, deadline, sig1);

        bytes memory sig2 = _auth(signerKey, "inv-dup", payer2, address(usdt), 2e18, merchant, deadline);
        vm.prank(payer2);
        vm.expectRevert("invoice done");
        pay.pay("inv-dup", address(usdt), 2e18, merchant, deadline, sig2);
    }

    /// AUDIT REGRESSION ([P1]): a griefer cannot brick an invoice, because
    /// consuming invoiceDone now REQUIRES the backend's authorization — which
    /// a griefer cannot forge. Their unsigned/self-signed call just reverts.
    function test_griefer_cannot_brick_a_real_invoice() public {
        address griefer = makeAddr("griefer");
        usdt.mint(griefer, 10e18);
        vm.startPrank(griefer);
        usdt.approve(address(pay), type(uint256).max);
        // Griefer forges their own authorization with a key they control.
        uint256 fakeKey = 0xBAD;
        bytes memory forged = _auth(fakeKey, "inv-real", griefer, address(usdt), 2e18, merchant, deadline);
        vm.expectRevert("bad authorization");
        pay.pay("inv-real", address(usdt), 2e18, merchant, deadline, forged);
        vm.stopPrank();

        // The real, backend-authorized payment still settles untouched.
        // (Build the sig BEFORE prank — payDigest is a staticcall that would
        // otherwise consume the prank.)
        bytes memory realSig = _sig("inv-real", address(usdt), 10 * WAD, merchant);
        vm.prank(payer);
        uint256 fee = pay.pay("inv-real", address(usdt), 10 * WAD, merchant, deadline, realSig);
        assertEq(usdt.balanceOf(merchant), 10 * WAD - fee);
    }

    function test_forged_authorization_rejected() public {
        bytes memory forged = _auth(0xBAD, "inv-forge", payer, address(usdt), 1e18, merchant, deadline);
        vm.prank(payer);
        vm.expectRevert("bad authorization");
        pay.pay("inv-forge", address(usdt), 1e18, merchant, deadline, forged);
    }

    function test_authorization_for_other_payer_rejected() public {
        // Signed for `stranger`, presented by `payer` → digest binds payer,
        // so the recovered signer won't match.
        bytes memory sig = _auth(signerKey, "inv-x", stranger, address(usdt), 1e18, merchant, deadline);
        vm.prank(payer);
        vm.expectRevert("bad authorization");
        pay.pay("inv-x", address(usdt), 1e18, merchant, deadline, sig);
    }

    function test_tampered_amount_rejected() public {
        // Authorized for 1e18 but the payer submits 2e18.
        bytes memory sig = _sig("inv-t", address(usdt), 1e18, merchant);
        vm.prank(payer);
        vm.expectRevert("bad authorization");
        pay.pay("inv-t", address(usdt), 2e18, merchant, deadline, sig);
    }

    function test_expired_authorization_rejected() public {
        uint256 past = block.timestamp + 10;
        bytes memory sig = _auth(signerKey, "inv-exp", payer, address(usdt), 1e18, merchant, past);
        vm.warp(past + 1);
        vm.prank(payer);
        vm.expectRevert("authorization expired");
        pay.pay("inv-exp", address(usdt), 1e18, merchant, past, sig);
    }

    function test_signer_rotation() public {
        uint256 newKey = 0xB0B;
        address newSigner = vm.addr(newKey);
        vm.prank(safeOwner);
        pay.setPaymentSigner(newSigner);
        assertEq(pay.paymentSigner(), newSigner);

        // Old signer no longer works…
        bytes memory oldSig = _sig("inv-rot", address(usdt), 1e18, merchant);
        vm.prank(payer);
        vm.expectRevert("bad authorization");
        pay.pay("inv-rot", address(usdt), 1e18, merchant, deadline, oldSig);

        // …the new one does.
        bytes memory sig = _auth(newKey, "inv-rot", payer, address(usdt), 1e18, merchant, deadline);
        vm.prank(payer);
        pay.pay("inv-rot", address(usdt), 1e18, merchant, deadline, sig);
        assertTrue(pay.invoiceDone("inv-rot"));
    }

    function test_set_signer_owner_only() public {
        vm.prank(stranger);
        vm.expectRevert();
        pay.setPaymentSigner(stranger);
    }

    function test_self_payment_rejected() public {
        bytes memory sig = _auth(signerKey, "inv-self", payer, address(usdt), 1e18, payer, deadline);
        vm.prank(payer);
        vm.expectRevert("self payment");
        pay.pay("inv-self", address(usdt), 1e18, payer, deadline, sig);
    }

    function test_dust_payment_rejected() public {
        // gross == 1 → fee == 1 → merchant would receive zero.
        bytes memory sig = _sig("inv-dust", address(usdt), 1, merchant);
        vm.prank(payer);
        vm.expectRevert("amount too small");
        pay.pay("inv-dust", address(usdt), 1, merchant, deadline, sig);
    }

    function test_pay_alien_token_rejected() public {
        bytes memory sig = _auth(signerKey, "inv-4", payer, address(alien), 1e18, merchant, deadline);
        vm.prank(payer);
        vm.expectRevert("token not allowed");
        pay.pay("inv-4", address(alien), 1e18, merchant, deadline, sig);
    }

    function test_pay_merchant_cannot_be_contract_itself() public {
        bytes memory sig = _auth(signerKey, "inv-5", payer, address(usdt), 1e18, address(pay), deadline);
        vm.prank(payer);
        vm.expectRevert("bad merchant");
        pay.pay("inv-5", address(usdt), 1e18, address(pay), deadline, sig);
    }

    function test_pay_insufficient_allowance_reverts_whole_payment() public {
        address poor = makeAddr("poor");
        usdt.mint(poor, 1e18);
        vm.startPrank(poor);
        usdt.approve(address(pay), 1e18 - 1); // one wei short of gross
        bytes memory sig = _auth(signerKey, "inv-6", poor, address(usdt), 1e18, merchant, deadline);
        vm.expectRevert();
        pay.pay("inv-6", address(usdt), 1e18, merchant, deadline, sig);
        vm.stopPrank();
        assertEq(usdt.balanceOf(merchant), 0, "atomic: nothing moved");
        assertFalse(pay.invoiceDone("inv-6"), "invoice guard rolled back");
    }

    function test_pay_paused_rejected() public {
        vm.prank(safeOwner);
        pay.pause();
        bytes memory sig = _sig("inv-7", address(usdt), 1e18, merchant);
        vm.prank(payer);
        vm.expectRevert();
        pay.pay("inv-7", address(usdt), 1e18, merchant, deadline, sig);
    }

    // ── collectFees ──────────────────────────────────────────────────

    function test_collect_owner_only_and_bounded() public {
        bytes memory sig = _sig("inv-8", address(usdt), 100 * WAD, merchant);
        vm.prank(payer);
        uint256 fee = pay.pay("inv-8", address(usdt), 100 * WAD, merchant, deadline, sig);

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
