// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {OwnableUpgradeable} from "@openzeppelin/contracts-upgradeable/access/OwnableUpgradeable.sol";
import {Initializable} from "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import {ConfioMarketEscrow} from "../ConfioMarketEscrow.sol";
import {MockToken} from "./CusdPlusVault.t.sol";

/// Keeps 1% of every transfer — what the escrow must refuse to hold.
contract FeeOnTransferToken is ERC20 {
    constructor() ERC20("FOT", "FOT") {}

    function mint(address to, uint256 amt) external {
        _mint(to, amt);
    }

    function _update(address from, address to, uint256 value) internal override {
        if (from != address(0) && to != address(0)) {
            uint256 cut = value / 100;
            super._update(from, address(0xdead), cut);
            value -= cut;
        }
        super._update(from, to, value);
    }
}

contract ConfioMarketEscrowV2 is ConfioMarketEscrow {
    function version() external pure returns (uint256) {
        return 2;
    }
}

abstract contract EscrowBase is Test {
    ConfioMarketEscrow escrow;
    MockToken cusd;

    address safe = makeAddr("safe");
    address arbiter = makeAddr("arbiter");
    uint256 signerKey = 0xA11CE;
    address orderSigner = vm.addr(0xA11CE);

    uint64 constant SHIP = 3 days;
    uint64 constant RELEASE = 4 days;
    uint64 constant DISPUTE_TIMEOUT = 30 days;
    uint16 constant FEE = 800; // 8%
    uint128 constant MAX_ORDER = 300e18;
    uint128 constant MAX_OPEN = 10_000e18;

    bytes32 constant DEPOSIT_TYPEHASH = keccak256(
        "Deposit(bytes32 orderId,address buyer,address merchant,address token,uint256 amount,uint16 feeBps,uint256 deadline)"
    );

    function _deployEscrow() internal {
        cusd = new MockToken("cUSD");
        ConfioMarketEscrow impl = new ConfioMarketEscrow();
        escrow = ConfioMarketEscrow(
            address(
                new ERC1967Proxy(
                    address(impl),
                    abi.encodeCall(
                        ConfioMarketEscrow.initialize, (safe, orderSigner, arbiter, SHIP, RELEASE, DISPUTE_TIMEOUT)
                    )
                )
            )
        );
        vm.prank(safe);
        escrow.setTokenLimits(address(cusd), MAX_ORDER, MAX_OPEN);
    }

    /// Recomputed independently of the contract's own depositDigest.
    function _sign(
        bytes32 orderId,
        address buyer,
        address merchant,
        address token,
        uint256 amount,
        uint16 feeBps,
        uint256 deadline
    ) internal view returns (bytes memory) {
        bytes32 domain = keccak256(
            abi.encode(
                keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
                keccak256("ConfioMarketEscrow"),
                keccak256("1"),
                block.chainid,
                address(escrow)
            )
        );
        bytes32 structHash =
            keccak256(abi.encode(DEPOSIT_TYPEHASH, orderId, buyer, merchant, token, amount, feeBps, deadline));
        (uint8 v, bytes32 r, bytes32 s) =
            vm.sign(signerKey, keccak256(abi.encodePacked("\x19\x01", domain, structHash)));
        return abi.encodePacked(r, s, v);
    }

    function _deposit(bytes32 orderId, address buyer, address merchant, uint256 amount) internal {
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _sign(orderId, buyer, merchant, address(cusd), amount, FEE, deadline);
        vm.startPrank(buyer);
        cusd.approve(address(escrow), amount);
        escrow.deposit(orderId, merchant, address(cusd), amount, FEE, deadline, sig);
        vm.stopPrank();
    }
}

contract ConfioMarketEscrowTest is EscrowBase {
    address buyer = makeAddr("buyer");
    address merchant = makeAddr("merchant");
    address stranger = makeAddr("stranger");
    bytes32 constant ID = keccak256("order-1");
    uint256 constant AMT = 100e18;

    function setUp() public {
        _deployEscrow();
        cusd.mint(buyer, 1_000e18);
    }

    function _state(bytes32 id) internal view returns (ConfioMarketEscrow.State) {
        return escrow.getOrder(id).state;
    }

    // ── happy paths ─────────────────────────────────────────────────────

    function test_deposit_records_order_and_pulls_funds() public {
        _deposit(ID, buyer, merchant, AMT);
        ConfioMarketEscrow.Order memory o = escrow.getOrder(ID);
        assertEq(o.buyer, buyer);
        assertEq(o.merchant, merchant);
        assertEq(o.amount, AMT);
        assertEq(o.feeBps, FEE);
        assertEq(o.shipBy, block.timestamp + SHIP);
        assertEq(uint8(o.state), uint8(ConfioMarketEscrow.State.Funded));
        assertEq(cusd.balanceOf(address(escrow)), AMT);
        assertEq(escrow.openPrincipal(address(cusd)), AMT);
    }

    function test_confirm_pays_merchant_net_and_accrues_fee() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.prank(merchant);
        escrow.markShipped(ID);
        vm.prank(buyer);
        escrow.confirm(ID);
        assertEq(cusd.balanceOf(merchant), 92e18);
        assertEq(escrow.accruedFees(address(cusd)), 8e18);
        assertEq(escrow.openPrincipal(address(cusd)), 0);
        assertEq(uint8(_state(ID)), uint8(ConfioMarketEscrow.State.Released));
    }

    function test_buyer_can_confirm_an_order_never_marked_shipped() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.prank(buyer);
        escrow.confirm(ID);
        assertEq(cusd.balanceOf(merchant), 92e18);
    }

    function test_auto_release_after_window_by_anyone() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.prank(merchant);
        escrow.markShipped(ID);
        uint256 releaseAt = block.timestamp + RELEASE;
        vm.expectRevert(abi.encodeWithSelector(ConfioMarketEscrow.TooEarly.selector, releaseAt));
        vm.prank(stranger);
        escrow.release(ID);
        vm.warp(releaseAt);
        vm.prank(stranger);
        escrow.release(ID);
        assertEq(cusd.balanceOf(merchant), 92e18);
    }

    function test_release_requires_shipped() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.warp(block.timestamp + 365 days);
        vm.expectRevert(
            abi.encodeWithSelector(ConfioMarketEscrow.WrongState.selector, ConfioMarketEscrow.State.Funded)
        );
        escrow.release(ID);
    }

    // ── refunds ─────────────────────────────────────────────────────────

    function test_merchant_refund_returns_full_amount_no_fee() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.prank(merchant);
        escrow.markShipped(ID);
        vm.prank(merchant);
        escrow.refund(ID);
        assertEq(cusd.balanceOf(buyer), 1_000e18);
        assertEq(escrow.accruedFees(address(cusd)), 0);
        assertEq(uint8(_state(ID)), uint8(ConfioMarketEscrow.State.Refunded));
    }

    function test_reclaim_only_after_ship_deadline() public {
        _deposit(ID, buyer, merchant, AMT);
        uint256 shipBy = block.timestamp + SHIP;
        vm.warp(shipBy);
        vm.expectRevert(abi.encodeWithSelector(ConfioMarketEscrow.TooEarly.selector, shipBy + 1));
        vm.prank(buyer);
        escrow.reclaim(ID);
        vm.warp(shipBy + 1);
        vm.prank(buyer);
        escrow.reclaim(ID);
        assertEq(cusd.balanceOf(buyer), 1_000e18);
    }

    function test_reclaim_blocked_once_shipped() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.prank(merchant);
        escrow.markShipped(ID);
        vm.warp(block.timestamp + SHIP + 1);
        vm.expectRevert(
            abi.encodeWithSelector(ConfioMarketEscrow.WrongState.selector, ConfioMarketEscrow.State.Shipped)
        );
        vm.prank(buyer);
        escrow.reclaim(ID);
    }

    function test_late_mark_shipped_cannot_front_run_reclaim() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.warp(block.timestamp + SHIP + 1);
        vm.expectRevert(ConfioMarketEscrow.TooLate.selector);
        vm.prank(merchant);
        escrow.markShipped(ID);
    }

    function test_only_buyer_reclaims_only_merchant_refunds() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.warp(block.timestamp + SHIP + 1);
        vm.expectRevert(ConfioMarketEscrow.NotBuyer.selector);
        vm.prank(stranger);
        escrow.reclaim(ID);
        vm.expectRevert(ConfioMarketEscrow.NotMerchant.selector);
        vm.prank(buyer);
        escrow.refund(ID);
    }

    // ── disputes ────────────────────────────────────────────────────────

    function test_dispute_freezes_auto_release_and_arbiter_refunds() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.prank(merchant);
        escrow.markShipped(ID);
        vm.prank(buyer);
        escrow.dispute(ID);
        vm.warp(block.timestamp + RELEASE);
        vm.expectRevert(
            abi.encodeWithSelector(ConfioMarketEscrow.WrongState.selector, ConfioMarketEscrow.State.Disputed)
        );
        escrow.release(ID);
        vm.prank(arbiter);
        escrow.resolve(ID, false);
        assertEq(cusd.balanceOf(buyer), 1_000e18);
    }

    function test_arbiter_can_release_disputed_order() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.prank(buyer);
        escrow.dispute(ID);
        vm.prank(arbiter);
        escrow.resolve(ID, true);
        assertEq(cusd.balanceOf(merchant), 92e18);
        assertEq(escrow.accruedFees(address(cusd)), 8e18);
    }

    function test_arbiter_cannot_touch_undisputed_orders() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.expectRevert(
            abi.encodeWithSelector(ConfioMarketEscrow.WrongState.selector, ConfioMarketEscrow.State.Funded)
        );
        vm.prank(arbiter);
        escrow.resolve(ID, false);
        vm.expectRevert(ConfioMarketEscrow.NotArbiter.selector);
        vm.prank(safe);
        escrow.resolve(ID, false);
    }

    function test_dispute_closes_at_release_time() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.prank(merchant);
        escrow.markShipped(ID);
        vm.warp(block.timestamp + RELEASE);
        vm.expectRevert(ConfioMarketEscrow.TooLate.selector);
        vm.prank(buyer);
        escrow.dispute(ID);
    }

    function test_unanswered_dispute_refunds_buyer_after_timeout() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.prank(buyer);
        escrow.dispute(ID);
        uint256 at = block.timestamp + DISPUTE_TIMEOUT;
        vm.expectRevert(abi.encodeWithSelector(ConfioMarketEscrow.TooEarly.selector, at));
        escrow.refundExpiredDispute(ID);
        vm.warp(at);
        vm.prank(stranger);
        escrow.refundExpiredDispute(ID);
        assertEq(cusd.balanceOf(buyer), 1_000e18);
    }

    function test_buyer_withdraws_dispute_by_confirming() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.prank(buyer);
        escrow.dispute(ID);
        vm.prank(buyer);
        escrow.confirm(ID);
        assertEq(cusd.balanceOf(merchant), 92e18);
    }

    function test_settled_orders_are_final() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.prank(buyer);
        escrow.confirm(ID);
        vm.expectRevert(
            abi.encodeWithSelector(ConfioMarketEscrow.WrongState.selector, ConfioMarketEscrow.State.Released)
        );
        vm.prank(merchant);
        escrow.refund(ID);
        vm.expectRevert(
            abi.encodeWithSelector(ConfioMarketEscrow.WrongState.selector, ConfioMarketEscrow.State.Released)
        );
        vm.prank(buyer);
        escrow.dispute(ID);
    }

    // ── deposit guards ──────────────────────────────────────────────────

    function test_signature_is_bound_to_the_buyer() public {
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _sign(ID, buyer, merchant, address(cusd), AMT, FEE, deadline);
        cusd.mint(stranger, AMT);
        vm.startPrank(stranger);
        cusd.approve(address(escrow), AMT);
        vm.expectRevert(ConfioMarketEscrow.BadAuthorization.selector);
        escrow.deposit(ID, merchant, address(cusd), AMT, FEE, deadline, sig);
        vm.stopPrank();
    }

    function test_signature_covers_fee_and_merchant() public {
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _sign(ID, buyer, merchant, address(cusd), AMT, FEE, deadline);
        vm.startPrank(buyer);
        cusd.approve(address(escrow), AMT);
        vm.expectRevert(ConfioMarketEscrow.BadAuthorization.selector);
        escrow.deposit(ID, merchant, address(cusd), AMT, 0, deadline, sig);
        vm.expectRevert(ConfioMarketEscrow.BadAuthorization.selector);
        escrow.deposit(ID, stranger, address(cusd), AMT, FEE, deadline, sig);
        vm.stopPrank();
    }

    function test_order_id_cannot_be_reused() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.prank(buyer);
        escrow.confirm(ID);
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _sign(ID, buyer, merchant, address(cusd), AMT, FEE, deadline);
        vm.startPrank(buyer);
        cusd.approve(address(escrow), AMT);
        vm.expectRevert(ConfioMarketEscrow.OrderExists.selector);
        escrow.deposit(ID, merchant, address(cusd), AMT, FEE, deadline, sig);
        vm.stopPrank();
    }

    function test_expired_authorization() public {
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _sign(ID, buyer, merchant, address(cusd), AMT, FEE, deadline);
        vm.warp(deadline + 1);
        vm.prank(buyer);
        vm.expectRevert(ConfioMarketEscrow.AuthorizationExpired.selector);
        escrow.deposit(ID, merchant, address(cusd), AMT, FEE, deadline, sig);
    }

    function test_fee_cap_is_hard() public {
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _sign(ID, buyer, merchant, address(cusd), AMT, 1_001, deadline);
        vm.prank(buyer);
        vm.expectRevert(ConfioMarketEscrow.FeeTooHigh.selector);
        escrow.deposit(ID, merchant, address(cusd), AMT, 1_001, deadline, sig);
    }

    function test_self_purchase_rejected() public {
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _sign(ID, buyer, buyer, address(cusd), AMT, FEE, deadline);
        vm.prank(buyer);
        vm.expectRevert(ConfioMarketEscrow.BadMerchant.selector);
        escrow.deposit(ID, buyer, address(cusd), AMT, FEE, deadline, sig);
    }

    function test_amount_must_exceed_fee() public {
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _sign(ID, buyer, merchant, address(cusd), 1, FEE, deadline);
        vm.prank(buyer);
        vm.expectRevert(ConfioMarketEscrow.AmountTooSmall.selector);
        escrow.deposit(ID, merchant, address(cusd), 1, FEE, deadline, sig);
    }

    function test_token_must_be_enabled() public {
        MockToken alien = new MockToken("ALIEN");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _sign(ID, buyer, merchant, address(alien), AMT, FEE, deadline);
        vm.prank(buyer);
        vm.expectRevert(ConfioMarketEscrow.TokenNotAccepted.selector);
        escrow.deposit(ID, merchant, address(alien), AMT, FEE, deadline, sig);
    }

    function test_per_order_and_open_caps() public {
        uint256 deadline = block.timestamp + 1 hours;
        uint256 big = uint256(MAX_ORDER) + 1;
        bytes memory sig = _sign(ID, buyer, merchant, address(cusd), big, FEE, deadline);
        vm.prank(buyer);
        vm.expectRevert(ConfioMarketEscrow.OrderTooLarge.selector);
        escrow.deposit(ID, merchant, address(cusd), big, FEE, deadline, sig);

        vm.prank(safe);
        escrow.setTokenLimits(address(cusd), MAX_ORDER, 150e18);
        _deposit(ID, buyer, merchant, AMT);
        bytes32 id2 = keccak256("order-2");
        sig = _sign(id2, buyer, merchant, address(cusd), AMT, FEE, deadline);
        vm.startPrank(buyer);
        cusd.approve(address(escrow), AMT);
        vm.expectRevert(ConfioMarketEscrow.OpenCapExceeded.selector);
        escrow.deposit(id2, merchant, address(cusd), AMT, FEE, deadline, sig);
        vm.stopPrank();
    }

    function test_disabling_a_token_still_lets_open_orders_settle() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.prank(safe);
        escrow.setTokenLimits(address(cusd), 0, 0);
        vm.prank(buyer);
        escrow.confirm(ID);
        assertEq(cusd.balanceOf(merchant), 92e18);
    }

    function test_fee_on_transfer_token_rejected() public {
        FeeOnTransferToken fot = new FeeOnTransferToken();
        fot.mint(buyer, AMT);
        vm.prank(safe);
        escrow.setTokenLimits(address(fot), MAX_ORDER, MAX_OPEN);
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _sign(ID, buyer, merchant, address(fot), AMT, FEE, deadline);
        vm.startPrank(buyer);
        fot.approve(address(escrow), AMT);
        vm.expectRevert(ConfioMarketEscrow.AmountMismatch.selector);
        escrow.deposit(ID, merchant, address(fot), AMT, FEE, deadline, sig);
        vm.stopPrank();
    }

    // ── pause ───────────────────────────────────────────────────────────

    function test_pause_blocks_deposits_but_never_exits() public {
        _deposit(ID, buyer, merchant, AMT);
        bytes32 id2 = keccak256("order-2");
        _deposit(id2, buyer, merchant, AMT);
        vm.prank(safe);
        escrow.pause();

        uint256 deadline = block.timestamp + 1 hours;
        bytes32 id3 = keccak256("order-3");
        bytes memory sig = _sign(id3, buyer, merchant, address(cusd), AMT, FEE, deadline);
        vm.prank(buyer);
        vm.expectRevert(PausableUpgradeable.EnforcedPause.selector);
        escrow.deposit(id3, merchant, address(cusd), AMT, FEE, deadline, sig);

        vm.prank(merchant);
        escrow.markShipped(ID);
        vm.prank(buyer);
        escrow.confirm(ID);
        vm.warp(block.timestamp + SHIP + 1);
        vm.prank(buyer);
        escrow.reclaim(id2);
        assertEq(escrow.openPrincipal(address(cusd)), 0);
    }

    // ── admin ───────────────────────────────────────────────────────────

    function test_collect_fees_bounded_by_accrual() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.prank(buyer);
        escrow.confirm(ID);
        _deposit(keccak256("open"), buyer, merchant, AMT);
        vm.prank(safe);
        vm.expectRevert(ConfioMarketEscrow.NothingToCollect.selector);
        escrow.collectFees(address(cusd), safe, 8e18 + 1);
        vm.prank(safe);
        escrow.collectFees(address(cusd), safe, 8e18);
        assertEq(cusd.balanceOf(safe), 8e18);
        assertEq(cusd.balanceOf(address(escrow)), AMT);
    }

    function test_sweep_stray_never_reaches_principal_or_fees() public {
        _deposit(ID, buyer, merchant, AMT);
        vm.prank(safe);
        vm.expectRevert(ConfioMarketEscrow.NothingToCollect.selector);
        escrow.sweepStray(address(cusd), safe);
        cusd.mint(address(escrow), 5e18);
        vm.prank(safe);
        escrow.sweepStray(address(cusd), safe);
        assertEq(cusd.balanceOf(safe), 5e18);
        assertEq(cusd.balanceOf(address(escrow)), AMT);
    }

    function test_admin_is_owner_only() public {
        bytes memory notOwner = abi.encodeWithSelector(OwnableUpgradeable.OwnableUnauthorizedAccount.selector, stranger);
        vm.startPrank(stranger);
        vm.expectRevert(notOwner);
        escrow.setOrderSigner(stranger);
        vm.expectRevert(notOwner);
        escrow.setArbiter(stranger);
        vm.expectRevert(notOwner);
        escrow.setTokenLimits(address(cusd), 1, 1);
        vm.expectRevert(notOwner);
        escrow.setWindows(SHIP, RELEASE, DISPUTE_TIMEOUT);
        vm.expectRevert(notOwner);
        escrow.collectFees(address(cusd), stranger, 1);
        vm.expectRevert(notOwner);
        escrow.pause();
        vm.stopPrank();
    }

    function test_window_bounds() public {
        vm.startPrank(safe);
        vm.expectRevert(ConfioMarketEscrow.BadWindow.selector);
        escrow.setWindows(59 minutes, RELEASE, DISPUTE_TIMEOUT);
        vm.expectRevert(ConfioMarketEscrow.BadWindow.selector);
        escrow.setWindows(SHIP, 31 days, DISPUTE_TIMEOUT);
        vm.expectRevert(ConfioMarketEscrow.BadWindow.selector);
        escrow.setWindows(SHIP, RELEASE, 91 days);
        vm.stopPrank();
    }

    function test_windows_are_snapshotted_per_order() public {
        _deposit(ID, buyer, merchant, AMT);
        uint256 shipBy = block.timestamp + SHIP;
        vm.prank(safe);
        escrow.setWindows(1 hours, 1 hours, DISPUTE_TIMEOUT);
        assertEq(escrow.getOrder(ID).shipBy, shipBy);
        vm.prank(merchant);
        escrow.markShipped(ID);
        assertEq(escrow.getOrder(ID).releaseAt, block.timestamp + RELEASE);
    }

    // ── upgrades ────────────────────────────────────────────────────────

    function test_upgrade_owner_only_and_keeps_orders() public {
        _deposit(ID, buyer, merchant, AMT);
        ConfioMarketEscrowV2 v2 = new ConfioMarketEscrowV2();
        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(OwnableUpgradeable.OwnableUnauthorizedAccount.selector, stranger));
        escrow.upgradeToAndCall(address(v2), "");
        vm.prank(safe);
        escrow.upgradeToAndCall(address(v2), "");
        assertEq(ConfioMarketEscrowV2(address(escrow)).version(), 2);
        assertEq(escrow.getOrder(ID).amount, AMT);
        vm.prank(buyer);
        escrow.confirm(ID);
        assertEq(cusd.balanceOf(merchant), 92e18);
    }

    function test_implementation_cannot_be_initialized() public {
        ConfioMarketEscrow impl = new ConfioMarketEscrow();
        vm.expectRevert(Initializable.InvalidInitialization.selector);
        impl.initialize(safe, orderSigner, arbiter, SHIP, RELEASE, DISPUTE_TIMEOUT);
    }

    function test_initialize_rejects_zero_roles() public {
        ConfioMarketEscrow impl = new ConfioMarketEscrow();
        vm.expectRevert(ConfioMarketEscrow.ZeroAddress.selector);
        new ERC1967Proxy(
            address(impl),
            abi.encodeCall(ConfioMarketEscrow.initialize, (safe, address(0), arbiter, SHIP, RELEASE, DISPUTE_TIMEOUT))
        );
    }

    function test_digest_matches_independent_encoding() public view {
        uint256 deadline = 123;
        bytes32 structHash =
            keccak256(abi.encode(DEPOSIT_TYPEHASH, ID, buyer, merchant, address(cusd), AMT, FEE, deadline));
        bytes32 domain = keccak256(
            abi.encode(
                keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
                keccak256("ConfioMarketEscrow"),
                keccak256("1"),
                block.chainid,
                address(escrow)
            )
        );
        assertEq(
            escrow.depositDigest(ID, buyer, merchant, address(cusd), AMT, FEE, deadline),
            keccak256(abi.encodePacked("\x19\x01", domain, structHash))
        );
    }

    // ── fuzz ────────────────────────────────────────────────────────────

    function testFuzz_release_conserves_amount(uint256 amount, uint16 feeBps) public {
        feeBps = uint16(bound(feeBps, 0, 1_000));
        amount = bound(amount, 1, MAX_ORDER);
        vm.assume(amount > escrow.feeFor(amount, feeBps));
        cusd.mint(buyer, amount);
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _sign(ID, buyer, merchant, address(cusd), amount, feeBps, deadline);
        vm.startPrank(buyer);
        cusd.approve(address(escrow), amount);
        escrow.deposit(ID, merchant, address(cusd), amount, feeBps, deadline, sig);
        escrow.confirm(ID);
        vm.stopPrank();
        uint256 fee = escrow.accruedFees(address(cusd));
        assertEq(cusd.balanceOf(merchant) + fee, amount);
        assertEq(fee, escrow.feeFor(amount, feeBps));
        assertEq(cusd.balanceOf(address(escrow)), fee);
    }
}

/// Drives random but always-legitimate order traffic; with fail_on_revert
/// every call here must succeed, so every legal exit is proven reachable.
contract EscrowHandler is Test {
    ConfioMarketEscrow public escrow;
    MockToken public cusd;
    address public arbiter;
    uint256 signerKey;

    address[] public actors;
    bytes32[] public openIds;
    uint256 public nonce;
    uint256 public totalDeposited;
    uint256 public totalReleasedNet;
    uint256 public totalRefunded;

    bytes32 constant DEPOSIT_TYPEHASH = keccak256(
        "Deposit(bytes32 orderId,address buyer,address merchant,address token,uint256 amount,uint16 feeBps,uint256 deadline)"
    );

    constructor(ConfioMarketEscrow escrow_, MockToken cusd_, address arbiter_, uint256 signerKey_) {
        escrow = escrow_;
        cusd = cusd_;
        arbiter = arbiter_;
        signerKey = signerKey_;
        for (uint256 i = 0; i < 4; i++) {
            actors.push(makeAddr(string.concat("actor", vm.toString(i))));
        }
    }

    function openCount() external view returns (uint256) {
        return openIds.length;
    }

    function deposit(uint256 buyerSeed, uint256 merchantSeed, uint256 amount, uint16 feeBps) external {
        uint256 b = buyerSeed % actors.length;
        address buyer = actors[b];
        address merchant = actors[(b + 1 + merchantSeed % (actors.length - 1)) % actors.length];
        feeBps = uint16(bound(feeBps, 0, 1_000));
        (uint128 maxOrder, uint128 maxOpen) = escrow.tokenLimits(address(cusd));
        uint256 room = maxOpen - escrow.openPrincipal(address(cusd));
        uint256 cap = room < maxOrder ? room : maxOrder;
        if (cap < 20) return; // full: nothing legitimate to deposit
        amount = bound(amount, 20, cap);
        bytes32 id = keccak256(abi.encode("order", nonce++));
        _signedDeposit(id, buyer, merchant, amount, feeBps);
        openIds.push(id);
        totalDeposited += amount;
    }

    function _signedDeposit(bytes32 id, address buyer, address merchant, uint256 amount, uint16 feeBps) private {
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _sig(escrow.depositDigest(id, buyer, merchant, address(cusd), amount, feeBps, deadline));
        cusd.mint(buyer, amount);
        vm.startPrank(buyer);
        cusd.approve(address(escrow), amount);
        escrow.deposit(id, merchant, address(cusd), amount, feeBps, deadline, sig);
        vm.stopPrank();
    }

    function _sig(bytes32 digest) private view returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(signerKey, digest);
        return abi.encodePacked(r, s, v);
    }

    /// Picks an open order and performs one action that is legal for its
    /// current state and time.
    function act(uint256 idSeed, uint256 choice, uint256 warpBy) external {
        if (openIds.length == 0) return;
        vm.warp(block.timestamp + bound(warpBy, 0, 5 days));
        uint256 idx = idSeed % openIds.length;
        bytes32 id = openIds[idx];
        ConfioMarketEscrow.Order memory o = escrow.getOrder(id);
        uint256 c = choice % 4;

        if (o.state == ConfioMarketEscrow.State.Funded) {
            if (c == 0 && block.timestamp <= o.shipBy) {
                vm.prank(o.merchant);
                escrow.markShipped(id);
                return;
            } else if (c == 1) {
                vm.prank(o.buyer);
                escrow.dispute(id);
                return;
            } else if (c == 2 && block.timestamp > o.shipBy) {
                vm.prank(o.buyer);
                escrow.reclaim(id);
                _settledRefund(idx, o.amount);
            } else if (c == 3) {
                vm.prank(o.merchant);
                escrow.refund(id);
                _settledRefund(idx, o.amount);
            } else {
                vm.prank(o.buyer);
                escrow.confirm(id);
                _settledRelease(idx, o);
            }
        } else if (o.state == ConfioMarketEscrow.State.Shipped) {
            if (block.timestamp >= o.releaseAt) {
                escrow.release(id);
                _settledRelease(idx, o);
            } else if (c == 0) {
                vm.prank(o.buyer);
                escrow.dispute(id);
            } else if (c == 1) {
                vm.prank(o.merchant);
                escrow.refund(id);
                _settledRefund(idx, o.amount);
            } else {
                vm.prank(o.buyer);
                escrow.confirm(id);
                _settledRelease(idx, o);
            }
        } else {
            // Disputed
            if (block.timestamp >= uint256(o.disputedAt) + escrow.disputeTimeout() && c == 0) {
                escrow.refundExpiredDispute(id);
                _settledRefund(idx, o.amount);
            } else if (c <= 1) {
                vm.prank(arbiter);
                escrow.resolve(id, c == 1);
                if (c == 1) _settledRelease(idx, o);
                else _settledRefund(idx, o.amount);
            } else {
                vm.prank(o.buyer);
                escrow.confirm(id);
                _settledRelease(idx, o);
            }
        }
    }

    function _settledRelease(uint256 idx, ConfioMarketEscrow.Order memory o) private {
        totalReleasedNet += o.amount - escrow.feeFor(o.amount, o.feeBps);
        _drop(idx);
    }

    function _settledRefund(uint256 idx, uint256 amount) private {
        totalRefunded += amount;
        _drop(idx);
    }

    function _drop(uint256 idx) private {
        openIds[idx] = openIds[openIds.length - 1];
        openIds.pop();
    }
}

contract ConfioMarketEscrowInvariantTest is EscrowBase {
    EscrowHandler handler;

    function setUp() public {
        _deployEscrow();
        vm.prank(safe);
        escrow.setTokenLimits(address(cusd), 300e18, 3_000e18);
        handler = new EscrowHandler(escrow, cusd, arbiter, signerKey);
        bytes4[] memory selectors = new bytes4[](2);
        selectors[0] = EscrowHandler.deposit.selector;
        selectors[1] = EscrowHandler.act.selector;
        targetSelector(FuzzSelector(address(handler), selectors));
        targetContract(address(handler));
    }

    /// The contract holds exactly the open principal plus accrued fees.
    function invariant_balance_equals_open_principal_plus_fees() public view {
        assertEq(
            cusd.balanceOf(address(escrow)), escrow.openPrincipal(address(cusd)) + escrow.accruedFees(address(cusd))
        );
    }

    /// Every deposited unit is either still open, paid to a merchant, a fee,
    /// or back with its buyer — nothing leaks anywhere else.
    function invariant_deposits_fully_accounted() public view {
        assertEq(
            handler.totalDeposited(),
            escrow.openPrincipal(address(cusd)) + escrow.accruedFees(address(cusd)) + handler.totalReleasedNet()
                + handler.totalRefunded()
        );
    }

    function invariant_open_principal_within_cap() public view {
        (, uint128 maxOpen) = escrow.tokenLimits(address(cusd));
        assertLe(escrow.openPrincipal(address(cusd)), maxOpen);
    }
}
