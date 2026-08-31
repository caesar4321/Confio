// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {CusdPlusVault, IRWADynamicOracle, IOndoInstantManager} from "../CusdPlusVault.sol";
import {ConfioPayrollVault} from "../ConfioPayrollVault.sol";
import {MockCusdFeePerimeter} from "./MockCusdFeePerimeter.sol";

// ── Mocks (CusdPlusVault.t.sol pattern: real vault, mocked Ondo edge) ────

contract MockToken is ERC20 {
    constructor(string memory n) ERC20(n, n) {}

    function mint(address to, uint256 amt) external {
        _mint(to, amt);
    }
}

contract MockOracle is IRWADynamicOracle {
    uint256 public price = 1e18;

    function setPrice(uint256 p) external {
        price = p;
    }

    function getPrice() external view returns (uint256) {
        return price;
    }
}

contract MockInstantManager is IOndoInstantManager {
    MockToken public usdt;
    MockToken public usdy;
    MockOracle public oracle;

    constructor(MockToken _usdt, MockToken _usdy, MockOracle _oracle) {
        usdt = _usdt;
        usdy = _usdy;
        oracle = _oracle;
    }

    function subscribe(address depositToken, uint256 depositAmount, uint256 minimumRwaReceived)
        external
        returns (uint256 rwaAmountOut)
    {
        require(depositToken == address(usdt), "im: unsupported deposit token");
        usdt.transferFrom(msg.sender, address(this), depositAmount);
        rwaAmountOut = (depositAmount * 1e18) / oracle.price();
        require(rwaAmountOut >= minimumRwaReceived, "im slippage");
        usdy.transfer(msg.sender, rwaAmountOut);
    }

    function redeem(uint256 rwaAmount, address receivingToken, uint256 minimumTokenReceived)
        external
        returns (uint256 receiveTokenAmount)
    {
        require(receivingToken == address(usdt), "im: unsupported receive token");
        usdy.transferFrom(msg.sender, address(this), rwaAmount);
        receiveTokenAmount = (rwaAmount * oracle.price()) / 1e18;
        require(receiveTokenAmount >= minimumTokenReceived, "im slippage");
        usdt.transfer(msg.sender, receiveTokenAmount);
    }
}

// ── Tests ────────────────────────────────────────────────────────────────

contract ConfioPayrollVaultTest is Test {
    MockToken usdt;
    MockToken usdy;
    MockOracle oracle;
    MockInstantManager im;
    CusdPlusVault vault; // via proxy
    ConfioPayrollVault payroll;
    MockCusdFeePerimeter cusd;

    address treasury = makeAddr("treasury");
    address safeOwner = makeAddr("safeOwner");
    address employee = makeAddr("employee");
    address sponsor = makeAddr("sponsor"); // untrusted payout caller

    // Signing actors need known private keys.
    uint256 businessKey = 0xB0B;
    uint256 delegateKey = 0xDE1;
    uint256 strangerKey = 0xBAD;
    address business;
    address delegate;
    address stranger;

    uint256 constant WAD = 1e18;

    function setUp() public {
        business = vm.addr(businessKey);
        delegate = vm.addr(delegateKey);
        stranger = vm.addr(strangerKey);

        usdt = new MockToken("USDT");
        usdy = new MockToken("USDY");
        oracle = new MockOracle();
        im = new MockInstantManager(usdt, usdy, oracle);
        usdt.mint(address(im), 100_000_000e18);
        usdy.mint(address(im), 100_000_000e18);

        CusdPlusVault impl = new CusdPlusVault(address(usdy), address(usdt), address(im), address(oracle), 1500);
        ERC1967Proxy proxy = new ERC1967Proxy(address(impl), abi.encodeCall(CusdPlusVault.initialize, (treasury)));
        vault = CusdPlusVault(address(proxy));
        cusd = new MockCusdFeePerimeter(usdt, 0);
        vm.prank(treasury);
        vault.initializeCusd(address(cusd));
        // Mints are sponsor-gated (2026-07-31). Forge leaves tx.origin as
        // the default sender under vm.prank, which mirrors production:
        // user EOA = msg.sender, Confio's KMS sponsor = tx.origin.
        vm.prank(treasury);
        vault.setSponsor(tx.origin, true);

        payroll = new ConfioPayrollVault(address(vault), address(cusd), safeOwner);

        // Business funds its payroll float in BOTH assets — the normal state
        // for an employer whose Ondo eligibility changed mid-life, and the
        // one v1 could not represent at all.
        usdt.mint(business, 1_000_000e18);
        vm.startPrank(business);
        usdt.approve(address(vault), type(uint256).max);
        vault.subscribeAndMint(10_000e18, 9_900e18, business);
        vault.approve(address(payroll), type(uint256).max);
        payroll.deposit(CUSD_PLUS, 5_000e18);
        usdt.approve(address(payroll), type(uint256).max);
        payroll.deposit(USDT_ASSET, 2_000e18);
        payroll.setDelegate(delegate, true);
        vm.stopPrank();
    }

    function test_constructor_rejects_cusd_mismatch() public {
        MockCusdFeePerimeter other = new MockCusdFeePerimeter(usdt, 0);
        vm.expectRevert("cusd mismatch");
        new ConfioPayrollVault(address(vault), address(other), safeOwner);
    }

    ConfioPayrollVault.Asset constant CUSD_PLUS = ConfioPayrollVault.Asset.CusdPlus;
    ConfioPayrollVault.Asset constant USDT_ASSET = ConfioPayrollVault.Asset.Usdt;
    ConfioPayrollVault.Asset constant CUSD_ASSET = ConfioPayrollVault.Asset.Cusd;

    function _payout(bytes32 itemId, bool redeem) internal view returns (ConfioPayrollVault.Payout memory) {
        return ConfioPayrollVault.Payout({
            business: business,
            recipient: employee,
            asset: CUSD_PLUS,
            netAmount: 100e18,
            feeAmount: 1e18,
            redeemToUsdt: redeem,
            minUsdtOut: redeem ? 99e18 : 0,
            itemId: itemId,
            deadline: block.timestamp + 1 hours
        });
    }

    /// Same payout, drawn from the raw-USDT pool. There is only one rail
    /// out of it, so `redeemToUsdt`/`minUsdtOut` are pinned to zero.
    function _usdtPayout(bytes32 itemId) internal view returns (ConfioPayrollVault.Payout memory) {
        ConfioPayrollVault.Payout memory p = _payout(itemId, false);
        p.asset = USDT_ASSET;
        return p;
    }

    function _cusdPayout(bytes32 itemId) internal view returns (ConfioPayrollVault.Payout memory) {
        ConfioPayrollVault.Payout memory p = _payout(itemId, false);
        p.asset = CUSD_ASSET;
        return p;
    }

    function _sign(ConfioPayrollVault.Payout memory p, uint256 key) internal view returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, payroll.payoutDigest(p));
        return abi.encodePacked(r, s, v);
    }

    // ── Escrow accounting ────────────────────────────────────────────

    function test_deposit_withdraw_roundtrip() public {
        assertEq(payroll.escrowShares(business), 5_000e18);
        vm.prank(business);
        payroll.withdraw(CUSD_PLUS, 2_000e18, business);
        assertEq(payroll.escrowShares(business), 3_000e18);
        assertEq(vault.balanceOf(business), 7_000e18);
    }

    function test_cusd_pool_deposit_payout_and_fee_invariant() public {
        deal(address(cusd), business, 1_000e18);
        vm.startPrank(business);
        IERC20(address(cusd)).approve(address(payroll), type(uint256).max);
        payroll.deposit(CUSD_ASSET, 1_000e18);
        vm.stopPrank();

        ConfioPayrollVault.Payout memory p = _cusdPayout(bytes32("cusd-pay"));
        vm.prank(sponsor);
        payroll.payout(p, _sign(p, delegateKey));

        assertEq(IERC20(address(cusd)).balanceOf(employee), 100e18);
        assertEq(payroll.escrowCusd(business), 899e18);
        assertEq(payroll.accruedFeeCusd(), 1e18);
        assertEq(
            IERC20(address(cusd)).balanceOf(address(payroll)), payroll.totalEscrowCusd() + payroll.accruedFeeCusd()
        );
    }

    function test_withdraw_beyond_escrow_reverts() public {
        vm.prank(business);
        vm.expectRevert("insufficient escrow");
        payroll.withdraw(CUSD_PLUS, 5_001e18, business);
    }

    function test_withdraw_isolated_per_business() public {
        // A second business cannot touch the first one's float.
        address other = makeAddr("other");
        vm.prank(other);
        vm.expectRevert("insufficient escrow");
        payroll.withdraw(CUSD_PLUS, 1, other);
    }

    function test_withdraw_works_while_paused() public {
        vm.prank(safeOwner);
        payroll.pause();
        vm.prank(business);
        payroll.withdraw(CUSD_PLUS, 1_000e18, business);
        assertEq(vault.balanceOf(business), 6_000e18);
    }

    function test_deposit_paused_reverts() public {
        vm.prank(safeOwner);
        payroll.pause();
        vm.prank(business);
        vm.expectRevert();
        payroll.deposit(CUSD_PLUS, 1e18);
    }

    // ── Payout: transfer branch ──────────────────────────────────────

    function test_payout_transfer_by_delegate() public {
        ConfioPayrollVault.Payout memory p = _payout("item-1", false);
        bytes memory sig = _sign(p, delegateKey);
        vm.prank(sponsor);
        payroll.payout(p, sig);
        assertEq(vault.balanceOf(employee), 100e18);
        assertEq(payroll.accruedFeeShares(), 1e18, "fee accrues in-contract");
        assertEq(payroll.escrowShares(business), 5_000e18 - 101e18);
        // The standing invariant: contract balance = Σ escrow + accrued fees.
        assertEq(vault.balanceOf(address(payroll)), payroll.escrowShares(business) + payroll.accruedFeeShares());
    }

    function test_payout_transfer_by_business_itself() public {
        ConfioPayrollVault.Payout memory p = _payout("item-2", false);
        vm.prank(sponsor);
        payroll.payout(p, _sign(p, businessKey));
        assertEq(vault.balanceOf(employee), 100e18);
    }

    // ── Payout: cUSD compatibility branch (legacy ABI names) ─────────

    function test_payout_route_lands_cusd_at_recipient() public {
        ConfioPayrollVault.Payout memory p = _payout("item-3", true);
        vm.prank(sponsor);
        uint256 cusdOut = payroll.payout(p, _sign(p, delegateKey));
        assertEq(vault.balanceOf(employee), 0, "no shares on route branch");
        assertEq(cusd.balanceOf(employee), cusdOut);
        assertGe(cusdOut, 99e18, "minOut honored");
        assertEq(usdt.balanceOf(employee), 0, "internal route must not deliver USDT");
        assertEq(payroll.accruedFeeShares(), 1e18, "fee accrues in shares");
    }

    function test_payout_route_fails_closed_after_cusd_rotation() public {
        MockCusdFeePerimeter other = new MockCusdFeePerimeter(usdt, 0);
        vm.prank(treasury);
        vault.setCusdVault(address(other));

        ConfioPayrollVault.Payout memory p = _payout("item-rotated-cusd", true);
        bytes memory sig = _sign(p, delegateKey);
        vm.expectRevert("cusd mismatch");
        vm.prank(sponsor);
        payroll.payout(p, sig);
        assertEq(payroll.escrowShares(business), 5_000e18);
        assertFalse(payroll.itemUsed(keccak256(abi.encodePacked(business, bytes32("item-rotated-cusd")))));
    }

    function test_payout_redeem_slippage_reverts_whole_payout() public {
        ConfioPayrollVault.Payout memory p = _payout("item-4", true);
        p.minUsdtOut = 101e18; // impossible at $1.00
        bytes memory sig = _sign(p, delegateKey);
        vm.prank(sponsor);
        vm.expectRevert();
        payroll.payout(p, sig);
        // Atomicity: fee accrual rolled back with it, item NOT consumed
        // forever... actually it IS consumed pre-transfer — but the revert
        // rolls that back too. Item stays payable after a re-sign.
        assertEq(payroll.accruedFeeShares(), 0);
        assertEq(payroll.escrowShares(business), 5_000e18);
        assertFalse(payroll.itemUsed(keccak256(abi.encodePacked(business, bytes32("item-4")))));
    }

    // ── Authorization ────────────────────────────────────────────────

    function test_payout_stranger_signature_rejected() public {
        ConfioPayrollVault.Payout memory p = _payout("item-5", false);
        bytes memory sig = _sign(p, strangerKey);
        vm.prank(sponsor);
        vm.expectRevert("bad signer");
        payroll.payout(p, sig);
    }

    function test_payout_revoked_delegate_rejected() public {
        vm.prank(business);
        payroll.setDelegate(delegate, false);
        ConfioPayrollVault.Payout memory p = _payout("item-6", false);
        bytes memory sig = _sign(p, delegateKey);
        vm.prank(sponsor);
        vm.expectRevert("bad signer");
        payroll.payout(p, sig);
    }

    function test_payout_delegate_of_other_business_rejected() public {
        // delegate is allowlisted for `business`, signs a payout debiting a
        // DIFFERENT business — the allowlist is per-business.
        ConfioPayrollVault.Payout memory p = _payout("item-7", false);
        p.business = stranger;
        bytes memory sig = _sign(p, delegateKey);
        vm.prank(sponsor);
        vm.expectRevert("bad signer");
        payroll.payout(p, sig);
    }

    function test_payout_tampered_field_breaks_signature() public {
        ConfioPayrollVault.Payout memory p = _payout("item-8", false);
        bytes memory sig = _sign(p, delegateKey);
        p.recipient = stranger; // sponsor swaps recipient after signing
        vm.prank(sponsor);
        vm.expectRevert("bad signer");
        payroll.payout(p, sig);
    }

    // ── Replay / lifecycle ───────────────────────────────────────────

    function test_payout_replay_rejected() public {
        ConfioPayrollVault.Payout memory p = _payout("item-9", false);
        bytes memory sig = _sign(p, delegateKey);
        vm.prank(sponsor);
        payroll.payout(p, sig);
        vm.prank(sponsor);
        vm.expectRevert("item consumed");
        payroll.payout(p, sig);
    }

    function test_payout_expired_rejected() public {
        ConfioPayrollVault.Payout memory p = _payout("item-10", false);
        bytes memory sig = _sign(p, delegateKey);
        vm.warp(block.timestamp + 2 hours);
        vm.prank(sponsor);
        vm.expectRevert("expired");
        payroll.payout(p, sig);
    }

    function test_cancel_consumes_item() public {
        ConfioPayrollVault.Payout memory p = _payout("item-11", false);
        bytes memory sig = _sign(p, delegateKey);
        vm.prank(business);
        payroll.cancelItem("item-11");
        vm.prank(sponsor);
        vm.expectRevert("item consumed");
        payroll.payout(p, sig);
    }

    function test_cancel_scoped_to_canceller() public {
        // A stranger cancelling the same itemId burns THEIR key, not the
        // business's — item stays payable.
        ConfioPayrollVault.Payout memory p = _payout("item-12", false);
        bytes memory sig = _sign(p, delegateKey);
        vm.prank(stranger);
        payroll.cancelItem("item-12");
        vm.prank(sponsor);
        payroll.payout(p, sig);
        assertEq(vault.balanceOf(employee), 100e18);
    }

    function test_payout_beyond_escrow_reverts() public {
        ConfioPayrollVault.Payout memory p = _payout("item-13", false);
        p.netAmount = 5_000e18; // + 1e18 fee > 5_000e18 escrow
        bytes memory sig = _sign(p, delegateKey);
        vm.prank(sponsor);
        vm.expectRevert("insufficient escrow");
        payroll.payout(p, sig);
    }

    function test_payout_paused_reverts_withdraw_still_open() public {
        vm.prank(safeOwner);
        payroll.pause();
        ConfioPayrollVault.Payout memory p = _payout("item-14", false);
        bytes memory sig = _sign(p, delegateKey);
        vm.prank(sponsor);
        vm.expectRevert();
        payroll.payout(p, sig);
        vm.prank(business);
        payroll.withdraw(CUSD_PLUS, 5_000e18, business); // the exit survives the pause
    }

    // ── Yield accrual on parked float ────────────────────────────────

    function test_parked_shares_gain_value_not_count() public {
        uint256 before = payroll.escrowShares(business);
        oracle.setPrice(1.01e18); // USDY appreciates (within the drift guard)
        vault.accrue();
        assertEq(payroll.escrowShares(business), before, "share count fixed");
        // The same 100-share payout now unwraps to MORE cUSD.
        ConfioPayrollVault.Payout memory p = _payout("item-15", true);
        vm.prank(sponsor);
        uint256 cusdOut = payroll.payout(p, _sign(p, delegateKey));
        assertGt(cusdOut, 100e18, "yield accrued to escrowed float");
    }

    // ── USDT escrow: the Ondo-blocked employer's rail ────────────────
    // v1 had none of this, which is what made Nómina eligible-employers-only.

    function test_usdt_deposit_withdraw_roundtrip() public {
        assertEq(payroll.escrowUsdt(business), 2_000e18);
        uint256 before = usdt.balanceOf(business);
        vm.prank(business);
        payroll.withdraw(USDT_ASSET, 500e18, business);
        assertEq(payroll.escrowUsdt(business), 1_500e18);
        assertEq(usdt.balanceOf(business), before + 500e18);
    }

    function test_usdt_payout_pays_raw_usdt() public {
        ConfioPayrollVault.Payout memory p = _usdtPayout("usdt-1");
        vm.prank(sponsor);
        uint256 usdtOut = payroll.payout(p, _sign(p, delegateKey));
        assertEq(usdtOut, 0, "no redeem happened, so nothing to report");
        assertEq(usdt.balanceOf(employee), 100e18, "employee paid in USDT");
        assertEq(vault.balanceOf(employee), 0, "no shares involved");
        assertEq(payroll.accruedFeeUsdt(), 1e18, "fee accrues in USDT");
        assertEq(payroll.escrowUsdt(business), 2_000e18 - 101e18);
    }

    /// The two pools are separate money. A USDT payout must not be payable
    /// out of parked shares, nor the reverse — otherwise an employer with
    /// yield-bearing float could be drained by a USDT-denominated item.
    function test_pools_do_not_cross_subsidize() public {
        uint256 sharesBefore = payroll.escrowShares(business);
        ConfioPayrollVault.Payout memory p = _usdtPayout("usdt-2");
        vm.prank(sponsor);
        payroll.payout(p, _sign(p, delegateKey));
        assertEq(payroll.escrowShares(business), sharesBefore, "shares untouched");

        // Drain the USDT pool, then a USDT item fails even though the
        // business still has thousands in shares. (Read the balance BEFORE
        // the prank: a view call in the argument list consumes it.)
        uint256 parked = payroll.escrowUsdt(business);
        vm.prank(business);
        payroll.withdraw(USDT_ASSET, parked, business);
        ConfioPayrollVault.Payout memory q = _usdtPayout("usdt-3");
        bytes memory sig = _sign(q, delegateKey);
        vm.prank(sponsor);
        vm.expectRevert("insufficient escrow");
        payroll.payout(q, sig);
        assertGt(payroll.escrowShares(business), 0, "and the shares are still there");
    }

    function test_usdt_payout_cannot_redeem() public {
        ConfioPayrollVault.Payout memory p = _usdtPayout("usdt-4");
        p.redeemToUsdt = true; // nothing to burn; the money is already USDT
        p.minUsdtOut = 99e18;
        bytes memory sig = _sign(p, delegateKey);
        vm.prank(sponsor);
        vm.expectRevert("asset cannot redeem");
        payroll.payout(p, sig);
    }

    function test_usdt_payout_rejects_inert_min_out() public {
        // A signed field that does nothing is a field the three-way vector
        // check can disagree on silently.
        ConfioPayrollVault.Payout memory p = _usdtPayout("usdt-5");
        p.minUsdtOut = 1;
        bytes memory sig = _sign(p, delegateKey);
        vm.prank(sponsor);
        vm.expectRevert("min out unused");
        payroll.payout(p, sig);
    }

    /// One payroll item is one payment, whichever pool it names — otherwise
    /// re-signing a paid item against the other asset pays it twice.
    function test_item_replay_across_assets_rejected() public {
        ConfioPayrollVault.Payout memory p = _payout("shared-item", false);
        vm.prank(sponsor);
        payroll.payout(p, _sign(p, delegateKey));

        ConfioPayrollVault.Payout memory q = _usdtPayout("shared-item");
        bytes memory sig = _sign(q, delegateKey);
        vm.prank(sponsor);
        vm.expectRevert("item consumed");
        payroll.payout(q, sig);
    }

    /// The asset is under the signature: a sponsor cannot repoint a payout
    /// at the other pool after the delegate signed it.
    function test_asset_swap_after_signing_breaks_signature() public {
        ConfioPayrollVault.Payout memory p = _payout("swap-item", false);
        bytes memory sig = _sign(p, delegateKey);
        p.asset = USDT_ASSET;
        vm.prank(sponsor);
        vm.expectRevert("bad signer");
        payroll.payout(p, sig);
    }

    function test_usdt_escrow_earns_no_yield() public {
        uint256 before = payroll.escrowUsdt(business);
        oracle.setPrice(1.01e18);
        vault.accrue();
        assertEq(payroll.escrowUsdt(business), before, "raw USDT is not a yield-bearing position, in escrow or out");
    }

    function test_usdt_withdraw_works_while_paused() public {
        vm.prank(safeOwner);
        payroll.pause();
        vm.prank(business);
        payroll.withdraw(USDT_ASSET, 2_000e18, business); // exits are never gated
        assertEq(payroll.escrowUsdt(business), 0);
    }

    /// [P2 2026-08-02] A frozen business could still DEPOSIT, deepening a
    /// position it cannot withdraw from or pay out of.
    function test_frozen_business_cannot_deposit_either() public {
        vm.prank(treasury);
        vault.freezeAddress(business);

        vm.prank(business);
        vm.expectRevert("business frozen");
        payroll.deposit(CUSD_PLUS, 1e18);

        vm.prank(business);
        vm.expectRevert("business frozen");
        payroll.deposit(USDT_ASSET, 1e18);

        // Unfreezing restores it — the gate is the freeze, not the pool.
        vm.prank(treasury);
        vault.unfreezeAddress(business);
        vm.prank(business);
        payroll.deposit(USDT_ASSET, 1e18);
        assertEq(payroll.escrowUsdt(business), 2_000e18 + 1e18);
    }

    function test_frozen_business_blocked_on_usdt_leg_too() public {
        // The freeze is a statement about the BUSINESS. An escrow that
        // honoured it in one currency only would be an end-run with an
        // extra step.
        vm.prank(treasury);
        vault.freezeAddress(business);

        vm.prank(business);
        vm.expectRevert("business frozen");
        payroll.withdraw(USDT_ASSET, 1e18, business);

        ConfioPayrollVault.Payout memory p = _usdtPayout("frozen-usdt");
        bytes memory sig = _sign(p, delegateKey);
        vm.prank(sponsor);
        vm.expectRevert("business frozen");
        payroll.payout(p, sig);
    }

    function test_usdt_fees_and_surplus_are_bounded() public {
        ConfioPayrollVault.Payout memory p = _usdtPayout("usdt-fee");
        vm.prank(sponsor);
        payroll.payout(p, _sign(p, delegateKey));

        vm.prank(safeOwner);
        vm.expectRevert("exceeds accrued fees");
        payroll.collectFees(USDT_ASSET, safeOwner, 1e18 + 1);
        vm.prank(safeOwner);
        payroll.collectFees(USDT_ASSET, safeOwner, 1e18);
        assertEq(usdt.balanceOf(safeOwner), 1e18);

        // A mistaken direct transfer is rescuable; escrow never is.
        vm.prank(business);
        usdt.transfer(address(payroll), 7e18);
        assertEq(payroll.surplus(USDT_ASSET), 7e18);
        vm.prank(safeOwner);
        vm.expectRevert("exceeds surplus");
        payroll.rescueSurplus(USDT_ASSET, safeOwner, 7e18 + 1);
        vm.prank(safeOwner);
        payroll.rescueSurplus(USDT_ASSET, safeOwner, 7e18);

        // ...and the business's own float is still fully withdrawable.
        uint256 parked = payroll.escrowUsdt(business);
        vm.prank(business);
        payroll.withdraw(USDT_ASSET, parked, business);
    }

    function test_usdt_invariant_balance_equals_escrow_plus_fees() public {
        ConfioPayrollVault.Payout memory p = _usdtPayout("usdt-inv");
        vm.prank(sponsor);
        payroll.payout(p, _sign(p, delegateKey));
        assertEq(payroll.totalEscrowUsdt(), payroll.escrowUsdt(business));
        assertEq(usdt.balanceOf(address(payroll)), payroll.totalEscrowUsdt() + payroll.accruedFeeUsdt());
    }

    function test_usdt_address_derived_from_the_vault() public view {
        // Read from CUSD_PLUS at construction so the escrow token and the
        // token the redeem branch pays out can never diverge.
        assertEq(address(payroll.USDT()), address(usdt));
    }

    // ── EIP-712 parity anchor ────────────────────────────────────────
    // Shared vector with payroll/bsc_flow.py (test_payout_digest_parity)
    // and the client signer. Never change one side alone. Both assets are
    // pinned: `asset` sits inside the struct hash, so a client that dropped
    // it would still produce a plausible-looking digest for the other pool.

    function _vectorPayout(ConfioPayrollVault.Asset asset) internal pure returns (ConfioPayrollVault.Payout memory) {
        bool redeem = asset == ConfioPayrollVault.Asset.CusdPlus;
        return ConfioPayrollVault.Payout({
            business: 0x1111111111111111111111111111111111111111,
            recipient: 0x2222222222222222222222222222222222222222,
            asset: asset,
            netAmount: 100e18,
            feeAmount: 1e18,
            redeemToUsdt: redeem,
            minUsdtOut: redeem ? 99e18 : 0,
            itemId: keccak256("item-vector"),
            deadline: 1_800_000_000
        });
    }

    function test_payoutDigest_sharedVector() public {
        address fixedAddr = 0x7777777777777777777777777777777777777777;
        vm.etch(fixedAddr, address(payroll).code);
        vm.chainId(56);
        assertEq(
            ConfioPayrollVault(fixedAddr).payoutDigest(_vectorPayout(CUSD_PLUS)),
            0x2c40c42f0c28313ecc1797a92bdcdb90ba02269f2637e7a9df46d019696aa62e,
            "cUSD+ digest drifted from the shared Python/client vector"
        );
        assertEq(
            ConfioPayrollVault(fixedAddr).payoutDigest(_vectorPayout(USDT_ASSET)),
            0x442f16cf1636af9d2af1a59a731d45e2f1fc2638767f9532844e128d62b2644f,
            "USDT digest drifted from the shared Python/client vector"
        );
    }

    // ── Admin surface ────────────────────────────────────────────────

    function _accrueOneFee() internal {
        ConfioPayrollVault.Payout memory p = _payout("fee-item", false);
        vm.prank(sponsor);
        payroll.payout(p, _sign(p, delegateKey));
    }

    function test_collect_fees_owner_only() public {
        _accrueOneFee();
        vm.prank(stranger);
        vm.expectRevert();
        payroll.collectFees(CUSD_PLUS, stranger, 1e18);
        vm.prank(safeOwner);
        payroll.collectFees(CUSD_PLUS, safeOwner, 1e18);
        assertEq(vault.balanceOf(safeOwner), 1e18);
        assertEq(payroll.accruedFeeShares(), 0);
    }

    function test_collect_fees_bounded_by_accrual() public {
        // Escrow can never be drained through collectFees: the bound is
        // the accrual counter, not the contract's token balance.
        _accrueOneFee();
        vm.prank(safeOwner);
        vm.expectRevert("exceeds accrued fees");
        payroll.collectFees(CUSD_PLUS, safeOwner, 1e18 + 1);
    }

    function test_stray_shares_not_collectible() public {
        // Shares sent directly to the contract don't inflate the accrual.
        vm.prank(business);
        vault.transfer(address(payroll), 50e18);
        assertEq(payroll.accruedFeeShares(), 0);
        vm.prank(safeOwner);
        vm.expectRevert("exceeds accrued fees");
        payroll.collectFees(CUSD_PLUS, safeOwner, 1);
    }

    // ── AUDIT REGRESSIONS (2026-07-31) ───────────────────────────────

    /// [P2] Escrow must not be an end-run around a token-level freeze: the
    /// shares sit under THIS contract's address, so cUSD+'s own check sees
    /// an unfrozen sender and would happily let a frozen business exit.
    function test_frozen_business_cannot_withdraw_or_pay_out() public {
        vm.prank(treasury); // vault owner
        vault.freezeAddress(business);

        vm.prank(business);
        vm.expectRevert("business frozen");
        payroll.withdraw(CUSD_PLUS, 100e18, business);

        ConfioPayrollVault.Payout memory p = _payout("frozen-item", false);
        bytes memory sig = _sign(p, delegateKey);
        vm.prank(sponsor);
        vm.expectRevert("business frozen");
        payroll.payout(p, sig);

        // Unfreezing restores both paths.
        vm.prank(treasury);
        vault.unfreezeAddress(business);
        vm.prank(sponsor);
        payroll.payout(p, sig);
        assertEq(vault.balanceOf(employee), 100e18);
    }

    /// [P3] Shares that arrive by direct transfer instead of deposit were
    /// stranded forever. They're now rescuable — but only the provable
    /// surplus, never escrow or accrued fees.
    function test_rescue_surplus_bounded_by_obligations() public {
        vm.prank(business);
        vault.transfer(address(payroll), 50e18); // mistaken direct transfer
        assertEq(payroll.surplus(CUSD_PLUS), 50e18);

        vm.prank(safeOwner);
        vm.expectRevert("exceeds surplus");
        payroll.rescueSurplus(CUSD_PLUS, safeOwner, 50e18 + 1);

        vm.prank(safeOwner);
        payroll.rescueSurplus(CUSD_PLUS, safeOwner, 50e18);
        assertEq(vault.balanceOf(safeOwner), 50e18);
        assertEq(payroll.surplus(CUSD_PLUS), 0);

        // Escrow is untouched and still fully withdrawable.
        vm.prank(business);
        payroll.withdraw(CUSD_PLUS, 5_000e18, business);
    }

    function test_invariant_balance_equals_escrow_plus_fees() public {
        ConfioPayrollVault.Payout memory p = _payout("inv-item", false);
        vm.prank(sponsor);
        payroll.payout(p, _sign(p, delegateKey));
        assertEq(payroll.totalEscrowShares(), payroll.escrowShares(business));
        assertEq(vault.balanceOf(address(payroll)), payroll.totalEscrowShares() + payroll.accruedFeeShares());
    }
}
