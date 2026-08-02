// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ConfioPayContract} from "../ConfioPayContract.sol";

contract MockToken is ERC20 {
    constructor(string memory n) ERC20(n, n) {}
    function mint(address to, uint256 amt) external { _mint(to, amt); }
}

/// cUSD+ mock with the one extra behaviour the pay contract now relies on:
/// burn the shares it is given and pay USDT to `to`, like CusdPlusVault.
contract MockCusdPlus is ERC20 {
    MockToken public immutable USDT_;
    uint256 public rateBps = 10_000;  // 1 share -> 1 USDT by default
    constructor(address usdt_) ERC20("cUSD+", "cUSD+") { USDT_ = MockToken(usdt_); }
    function mint(address to, uint256 amt) external { _mint(to, amt); }
    function setRateBps(uint256 b) external { rateBps = b; }
    function redeemToUsdt(uint256 shares, uint256 minUsdtOut, address to)
        external returns (uint256 usdtOut)
    {
        _burn(msg.sender, shares);
        usdtOut = (shares * rateBps) / 10_000;
        require(usdtOut >= minUsdtOut, "slippage");
        USDT_.mint(to, usdtOut);
    }
}

/// Reports a plausible usdtOut, burns nothing, pays nobody. This is what a
/// hostile or broken UUPS upgrade of CusdPlusVault looks like from here.
contract LyingCusdPlus is ERC20 {
    constructor() ERC20("cUSD+", "cUSD+") {}
    function mint(address to, uint256 amt) external { _mint(to, amt); }
    function redeemToUsdt(uint256 shares, uint256, address)
        external pure returns (uint256) { return shares; }
}

contract ConfioPayContractTest is Test {
    MockCusdPlus cusdPlus;
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
        usdt = new MockToken("USDT");
        cusdPlus = new MockCusdPlus(address(usdt));
        confio = new MockToken("CONFIO");
        alien = new MockToken("ALIEN");
        pay = new ConfioPayContract(
            address(cusdPlus), address(usdt), address(confio), paymentSigner, safeOwner);
        deadline = block.timestamp + 3600;

        // cusdPlus is its own mock type now, so fund it separately.
        cusdPlus.mint(payer, 1_000e18);
        vm.prank(payer);
        cusdPlus.approve(address(pay), type(uint256).max);
        for (uint256 i = 0; i < 3; i++) {
            MockToken t = [usdt, confio, alien][i];
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
        bytes32 digest = pay.payDigest(invoiceId, who, token, gross, to, false, 0, dl);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, digest);
        return abi.encodePacked(r, s, v);
    }

    /// Routing-aware variant: signs redeemToUsdt/minUsdtOut too.
    function _signAs(
        uint256 key,
        bytes32 invoiceId,
        address who,
        address token,
        uint256 gross,
        address to,
        bool redeem,
        uint256 minOut,
        uint256 dl
    ) internal view returns (bytes memory) {
        bytes32 digest = pay.payDigest(invoiceId, who, token, gross, to, redeem, minOut, dl);
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

    // ── merchant routing, mirroring ConfioPayrollVault.payout() ──────────

    function test_pay_redeems_to_usdt_for_an_ineligible_merchant() public {
        uint256 gross = 100 * WAD;
        cusdPlus.mint(payer, gross);
        vm.prank(payer);
        cusdPlus.approve(address(pay), type(uint256).max);

        uint256 fee = pay.feeFor(gross);
        uint256 net = gross - fee;
        bytes memory sig = _signAs(
            signerKey, "inv-redeem", payer, address(cusdPlus), gross, merchant, true, net, deadline);

        vm.prank(payer);
        pay.pay("inv-redeem", address(cusdPlus), gross, merchant, true, net, deadline, sig);

        // The merchant holds USDT and NO shares — the whole point.
        assertEq(usdt.balanceOf(merchant), net, "merchant not paid in USDT");
        assertEq(cusdPlus.balanceOf(merchant), 0, "merchant received shares");
        assertEq(cusdPlus.balanceOf(address(pay)), fee, "fee not accrued in cUSD+");
        assertEq(pay.accruedFees(address(cusdPlus)), fee);
    }

    function test_redeem_routing_is_signed_not_caller_chosen() public {
        uint256 gross = 100 * WAD;
        cusdPlus.mint(payer, gross);
        vm.prank(payer);
        cusdPlus.approve(address(pay), type(uint256).max);
        uint256 net = gross - pay.feeFor(gross);

        // Authorization says "transfer shares"; the caller asks for a redeem.
        bytes memory sig = _signAs(
            signerKey, "inv-flip", payer, address(cusdPlus), gross, merchant, false, 0, deadline);
        vm.prank(payer);
        vm.expectRevert("bad authorization");
        pay.pay("inv-flip", address(cusdPlus), gross, merchant, true, net, deadline, sig);
    }

    function test_redeem_slippage_floor_is_enforced() public {
        uint256 gross = 100 * WAD;
        cusdPlus.mint(payer, gross);
        vm.prank(payer);
        cusdPlus.approve(address(pay), type(uint256).max);
        uint256 net = gross - pay.feeFor(gross);
        cusdPlus.setRateBps(9_000);  // vault returns 10% less than asked

        bytes memory sig = _signAs(
            signerKey, "inv-slip", payer, address(cusdPlus), gross, merchant, true, net, deadline);
        vm.prank(payer);
        vm.expectRevert("slippage");
        pay.pay("inv-slip", address(cusdPlus), gross, merchant, true, net, deadline, sig);
    }

    function test_redeem_requires_cusd_plus() public {
        uint256 gross = 100 * WAD;
        usdt.mint(payer, gross);
        vm.prank(payer);
        usdt.approve(address(pay), type(uint256).max);
        bytes memory sig = _signAs(
            signerKey, "inv-wrong", payer, address(usdt), gross, merchant, true, 1, deadline);
        vm.prank(payer);
        vm.expectRevert("redeem needs cUSD+");
        pay.pay("inv-wrong", address(usdt), gross, merchant, true, 1, deadline, sig);
    }

    function test_a_lying_vault_cannot_consume_the_invoice() public {
        LyingCusdPlus liar = new LyingCusdPlus();
        ConfioPayContract p2 = new ConfioPayContract(
            address(liar), address(usdt), address(confio), paymentSigner, safeOwner);
        uint256 gross = 100 * WAD;
        liar.mint(payer, gross);
        vm.prank(payer);
        liar.approve(address(p2), type(uint256).max);
        uint256 net = gross - p2.feeFor(gross);

        bytes32 digest = p2.payDigest(
            "inv-liar", payer, address(liar), gross, merchant, true, net, deadline);
        (uint8 v, bytes32 r, bytes32 sg) = vm.sign(signerKey, digest);
        bytes memory sig = abi.encodePacked(r, sg, v);

        vm.prank(payer);
        vm.expectRevert("merchant not paid");
        p2.pay("inv-liar", address(liar), gross, merchant, true, net, deadline, sig);

        // and the invoice is still open, the payer still holds their money
        assertFalse(p2.invoiceDone("inv-liar"), "invoice consumed by a failed pay");
        assertEq(liar.balanceOf(payer), gross, "payer lost funds");
    }

    function test_redeem_requires_a_minimum_out() public {
        uint256 gross = 100 * WAD;
        bytes memory sig = _signAs(
            signerKey, "inv-nomin", payer, address(cusdPlus), gross, merchant, true, 0, deadline);
        vm.prank(payer);
        vm.expectRevert("minOut required");
        pay.pay("inv-nomin", address(cusdPlus), gross, merchant, true, 0, deadline, sig);
    }

    function test_pay_splits_net_and_accrues_fee() public {
        bytes memory sig = _sig("inv-1", address(usdt), 10 * WAD, merchant);
        vm.prank(payer);
        uint256 fee = pay.pay("inv-1", address(usdt), 10 * WAD, merchant, false, 0, deadline, sig);
        assertEq(usdt.balanceOf(merchant), 10 * WAD - fee);
        assertEq(usdt.balanceOf(address(pay)), fee);
        assertEq(pay.accruedFees(address(usdt)), fee);
        assertTrue(pay.invoiceDone("inv-1"));
    }

    function test_pay_cusd_plus_token() public {
        bytes memory sig = _sig("inv-2", address(cusdPlus), 5 * WAD, merchant);
        vm.prank(payer);
        uint256 fee = pay.pay("inv-2", address(cusdPlus), 5 * WAD, merchant, false, 0, deadline, sig);
        assertEq(cusdPlus.balanceOf(merchant), 5 * WAD - fee);
        assertEq(pay.accruedFees(address(cusdPlus)), fee);
        assertEq(pay.accruedFees(address(usdt)), 0, "per-token accounting");
    }

    /// The second charge denomination (2026-08-01): a CONFIO invoice is a
    /// token COUNT, but settles through the identical fee/guard path.
    function test_pay_confio_token() public {
        bytes memory sig = _sig("inv-confio", address(confio), 250 * WAD, merchant);
        vm.prank(payer);
        uint256 fee = pay.pay("inv-confio", address(confio), 250 * WAD, merchant, false, 0, deadline, sig);
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
        pay.pay("inv-3", address(usdt), 1e18, merchant, false, 0, deadline, sig);
        vm.prank(payer);
        vm.expectRevert("invoice done");
        pay.pay("inv-3", address(usdt), 1e18, merchant, false, 0, deadline, sig);
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
        pay.pay("inv-dup", address(usdt), 2e18, merchant, false, 0, deadline, sig1);

        bytes memory sig2 = _auth(signerKey, "inv-dup", payer2, address(usdt), 2e18, merchant, deadline);
        vm.prank(payer2);
        vm.expectRevert("invoice done");
        pay.pay("inv-dup", address(usdt), 2e18, merchant, false, 0, deadline, sig2);
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
        pay.pay("inv-real", address(usdt), 2e18, merchant, false, 0, deadline, forged);
        vm.stopPrank();

        // The real, backend-authorized payment still settles untouched.
        // (Build the sig BEFORE prank — payDigest is a staticcall that would
        // otherwise consume the prank.)
        bytes memory realSig = _sig("inv-real", address(usdt), 10 * WAD, merchant);
        vm.prank(payer);
        uint256 fee = pay.pay("inv-real", address(usdt), 10 * WAD, merchant, false, 0, deadline, realSig);
        assertEq(usdt.balanceOf(merchant), 10 * WAD - fee);
    }

    function test_forged_authorization_rejected() public {
        bytes memory forged = _auth(0xBAD, "inv-forge", payer, address(usdt), 1e18, merchant, deadline);
        vm.prank(payer);
        vm.expectRevert("bad authorization");
        pay.pay("inv-forge", address(usdt), 1e18, merchant, false, 0, deadline, forged);
    }

    function test_authorization_for_other_payer_rejected() public {
        // Signed for `stranger`, presented by `payer` → digest binds payer,
        // so the recovered signer won't match.
        bytes memory sig = _auth(signerKey, "inv-x", stranger, address(usdt), 1e18, merchant, deadline);
        vm.prank(payer);
        vm.expectRevert("bad authorization");
        pay.pay("inv-x", address(usdt), 1e18, merchant, false, 0, deadline, sig);
    }

    function test_tampered_amount_rejected() public {
        // Authorized for 1e18 but the payer submits 2e18.
        bytes memory sig = _sig("inv-t", address(usdt), 1e18, merchant);
        vm.prank(payer);
        vm.expectRevert("bad authorization");
        pay.pay("inv-t", address(usdt), 2e18, merchant, false, 0, deadline, sig);
    }

    function test_expired_authorization_rejected() public {
        uint256 past = block.timestamp + 10;
        bytes memory sig = _auth(signerKey, "inv-exp", payer, address(usdt), 1e18, merchant, past);
        vm.warp(past + 1);
        vm.prank(payer);
        vm.expectRevert("authorization expired");
        pay.pay("inv-exp", address(usdt), 1e18, merchant, false, 0, past, sig);
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
        pay.pay("inv-rot", address(usdt), 1e18, merchant, false, 0, deadline, oldSig);

        // …the new one does.
        bytes memory sig = _auth(newKey, "inv-rot", payer, address(usdt), 1e18, merchant, deadline);
        vm.prank(payer);
        pay.pay("inv-rot", address(usdt), 1e18, merchant, false, 0, deadline, sig);
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
        pay.pay("inv-self", address(usdt), 1e18, payer, false, 0, deadline, sig);
    }

    function test_dust_payment_rejected() public {
        // gross == 1 → fee == 1 → merchant would receive zero.
        bytes memory sig = _sig("inv-dust", address(usdt), 1, merchant);
        vm.prank(payer);
        vm.expectRevert("amount too small");
        pay.pay("inv-dust", address(usdt), 1, merchant, false, 0, deadline, sig);
    }

    function test_pay_alien_token_rejected() public {
        bytes memory sig = _auth(signerKey, "inv-4", payer, address(alien), 1e18, merchant, deadline);
        vm.prank(payer);
        vm.expectRevert("token not allowed");
        pay.pay("inv-4", address(alien), 1e18, merchant, false, 0, deadline, sig);
    }

    function test_pay_merchant_cannot_be_contract_itself() public {
        bytes memory sig = _auth(signerKey, "inv-5", payer, address(usdt), 1e18, address(pay), deadline);
        vm.prank(payer);
        vm.expectRevert("bad merchant");
        pay.pay("inv-5", address(usdt), 1e18, address(pay), false, 0, deadline, sig);
    }

    function test_pay_insufficient_allowance_reverts_whole_payment() public {
        address poor = makeAddr("poor");
        usdt.mint(poor, 1e18);
        vm.startPrank(poor);
        usdt.approve(address(pay), 1e18 - 1); // one wei short of gross
        bytes memory sig = _auth(signerKey, "inv-6", poor, address(usdt), 1e18, merchant, deadline);
        vm.expectRevert();
        pay.pay("inv-6", address(usdt), 1e18, merchant, false, 0, deadline, sig);
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
        pay.pay("inv-7", address(usdt), 1e18, merchant, false, 0, deadline, sig);
    }

    // ── collectFees ──────────────────────────────────────────────────

    function test_collect_owner_only_and_bounded() public {
        bytes memory sig = _sig("inv-8", address(usdt), 100 * WAD, merchant);
        vm.prank(payer);
        uint256 fee = pay.pay("inv-8", address(usdt), 100 * WAD, merchant, false, 0, deadline, sig);

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
