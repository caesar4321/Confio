// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {CusdPlusVault, IRWADynamicOracle, IOndoInstantManager} from "../CusdPlusVault.sol";
import {ConfioPayrollVault} from "../ConfioPayrollVault.sol";

// ── Mocks (CusdPlusVault.t.sol pattern: real vault, mocked Ondo edge) ────

contract MockToken is ERC20 {
    constructor(string memory n) ERC20(n, n) {}
    function mint(address to, uint256 amt) external { _mint(to, amt); }
}

contract MockOracle is IRWADynamicOracle {
    uint256 public price = 1e18;
    function setPrice(uint256 p) external { price = p; }
    function getPrice() external view returns (uint256) { return price; }
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

        CusdPlusVault impl = new CusdPlusVault(
            address(usdy), address(usdt), address(im), address(oracle), 1500
        );
        ERC1967Proxy proxy = new ERC1967Proxy(
            address(impl),
            abi.encodeCall(CusdPlusVault.initialize, (treasury))
        );
        vault = CusdPlusVault(address(proxy));

        payroll = new ConfioPayrollVault(address(vault), safeOwner);

        // Business funds its payroll float: mint cUSD+ then park it.
        usdt.mint(business, 1_000_000e18);
        vm.startPrank(business);
        usdt.approve(address(vault), type(uint256).max);
        vault.subscribeAndMint(10_000e18, 9_900e18, business);
        vault.approve(address(payroll), type(uint256).max);
        payroll.deposit(5_000e18);
        payroll.setDelegate(delegate, true);
        vm.stopPrank();
    }

    function _payout(bytes32 itemId, bool redeem)
        internal
        view
        returns (ConfioPayrollVault.Payout memory)
    {
        return ConfioPayrollVault.Payout({
            business: business,
            recipient: employee,
            netShares: 100e18,
            feeShares: 1e18,
            redeemToUsdt: redeem,
            minUsdtOut: redeem ? 99e18 : 0,
            itemId: itemId,
            deadline: block.timestamp + 1 hours
        });
    }

    function _sign(ConfioPayrollVault.Payout memory p, uint256 key)
        internal
        view
        returns (bytes memory)
    {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, payroll.payoutDigest(p));
        return abi.encodePacked(r, s, v);
    }

    // ── Escrow accounting ────────────────────────────────────────────

    function test_deposit_withdraw_roundtrip() public {
        assertEq(payroll.escrowShares(business), 5_000e18);
        vm.prank(business);
        payroll.withdraw(2_000e18, business);
        assertEq(payroll.escrowShares(business), 3_000e18);
        assertEq(vault.balanceOf(business), 7_000e18);
    }

    function test_withdraw_beyond_escrow_reverts() public {
        vm.prank(business);
        vm.expectRevert("insufficient escrow");
        payroll.withdraw(5_001e18, business);
    }

    function test_withdraw_isolated_per_business() public {
        // A second business cannot touch the first one's float.
        address other = makeAddr("other");
        vm.prank(other);
        vm.expectRevert("insufficient escrow");
        payroll.withdraw(1, other);
    }

    function test_withdraw_works_while_paused() public {
        vm.prank(safeOwner);
        payroll.pause();
        vm.prank(business);
        payroll.withdraw(1_000e18, business);
        assertEq(vault.balanceOf(business), 6_000e18);
    }

    function test_deposit_paused_reverts() public {
        vm.prank(safeOwner);
        payroll.pause();
        vm.prank(business);
        vm.expectRevert();
        payroll.deposit(1e18);
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
        assertEq(vault.balanceOf(address(payroll)),
                 payroll.escrowShares(business) + payroll.accruedFeeShares());
    }

    function test_payout_transfer_by_business_itself() public {
        ConfioPayrollVault.Payout memory p = _payout("item-2", false);
        vm.prank(sponsor);
        payroll.payout(p, _sign(p, businessKey));
        assertEq(vault.balanceOf(employee), 100e18);
    }

    // ── Payout: redeem branch ────────────────────────────────────────

    function test_payout_redeem_lands_usdt_at_recipient() public {
        ConfioPayrollVault.Payout memory p = _payout("item-3", true);
        vm.prank(sponsor);
        uint256 usdtOut = payroll.payout(p, _sign(p, delegateKey));
        assertEq(vault.balanceOf(employee), 0, "no shares on redeem branch");
        assertEq(usdt.balanceOf(employee), usdtOut);
        assertGe(usdtOut, 99e18, "minOut honored");
        assertEq(payroll.accruedFeeShares(), 1e18, "fee accrues in shares");
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
        p.netShares = 5_000e18; // + 1e18 fee > 5_000e18 escrow
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
        payroll.withdraw(5_000e18, business); // the exit survives the pause
    }

    // ── Yield accrual on parked float ────────────────────────────────

    function test_parked_shares_gain_value_not_count() public {
        uint256 before = payroll.escrowShares(business);
        oracle.setPrice(1.01e18); // USDY appreciates (within the drift guard)
        vault.accrue();
        assertEq(payroll.escrowShares(business), before, "share count fixed");
        // The same 100-share payout now redeems to MORE USDT.
        ConfioPayrollVault.Payout memory p = _payout("item-15", true);
        vm.prank(sponsor);
        uint256 usdtOut = payroll.payout(p, _sign(p, delegateKey));
        assertGt(usdtOut, 100e18, "yield accrued to escrowed float");
    }

    // ── EIP-712 parity anchor ────────────────────────────────────────
    // Shared vector with payroll/bsc_flow.py (test_payout_digest_parity)
    // and the client signer. Never change one side alone.

    function test_payoutDigest_sharedVector() public {
        address fixedAddr = 0x7777777777777777777777777777777777777777;
        vm.etch(fixedAddr, address(payroll).code);
        vm.chainId(56);
        ConfioPayrollVault.Payout memory p = ConfioPayrollVault.Payout({
            business: 0x1111111111111111111111111111111111111111,
            recipient: 0x2222222222222222222222222222222222222222,
            netShares: 100e18,
            feeShares: 1e18,
            redeemToUsdt: true,
            minUsdtOut: 99e18,
            itemId: keccak256("item-vector"),
            deadline: 1_800_000_000
        });
        assertEq(
            ConfioPayrollVault(fixedAddr).payoutDigest(p),
            0xef818ab5751bd3f46c0459e4afd2f4b2802562771dd9e2a96a63bbfa36295e9c,
            "digest drifted from the shared Python/client vector"
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
        payroll.collectFees(stranger, 1e18);
        vm.prank(safeOwner);
        payroll.collectFees(safeOwner, 1e18);
        assertEq(vault.balanceOf(safeOwner), 1e18);
        assertEq(payroll.accruedFeeShares(), 0);
    }

    function test_collect_fees_bounded_by_accrual() public {
        // Escrow can never be drained through collectFees: the bound is
        // the accrual counter, not the contract's token balance.
        _accrueOneFee();
        vm.prank(safeOwner);
        vm.expectRevert("exceeds accrued fees");
        payroll.collectFees(safeOwner, 1e18 + 1);
    }

    function test_stray_shares_not_collectible() public {
        // Shares sent directly to the contract don't inflate the accrual.
        vm.prank(business);
        vault.transfer(address(payroll), 50e18);
        assertEq(payroll.accruedFeeShares(), 0);
        vm.prank(safeOwner);
        vm.expectRevert("exceeds accrued fees");
        payroll.collectFees(safeOwner, 1);
    }
}
