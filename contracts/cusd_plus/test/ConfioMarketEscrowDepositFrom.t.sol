// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {OwnableUpgradeable} from "@openzeppelin/contracts-upgradeable/access/OwnableUpgradeable.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";
import {ConfioMarketEscrow} from "../ConfioMarketEscrow.sol";
import {EscrowBase} from "./ConfioMarketEscrow.t.sol";

/// Stand-in for ConfioSmartAccountFactory: only isAccount is read.
contract MockAccountFactory {
    mapping(address => bool) public isAccount;

    function set(address a, bool v) external {
        isAccount[a] = v;
    }
}

/// Stand-in for a Cuenta inteligente: an owner() and an arbitrary call
/// (the real one reaches depositFrom through relayPurchase).
contract MockSmartAccount {
    address public owner;

    constructor(address owner_) {
        owner = owner_;
    }

    function setOwner(address o) external {
        owner = o;
    }

    function approve(IERC20 token, address spender, uint256 amount) external {
        token.approve(spender, amount);
    }

    function exec(address target, bytes calldata data) external returns (bytes memory) {
        (bool ok, bytes memory ret) = target.call(data);
        if (!ok) {
            assembly {
                revert(add(ret, 32), mload(ret))
            }
        }
        return ret;
    }
}

/// Token with an ERC-777-style hook: every transfer calls `hook` first.
contract CallbackToken is ERC20 {
    address public hookTarget;
    bytes public hookData;

    constructor() ERC20("CB", "CB") {}

    function mint(address to, uint256 amt) external {
        _mint(to, amt);
    }

    function arm(address target, bytes calldata data) external {
        hookTarget = target;
        hookData = data;
    }

    function _update(address from, address to, uint256 value) internal override {
        address t = hookTarget;
        if (t != address(0) && from != address(0)) {
            hookTarget = address(0); // one shot
            (bool ok, bytes memory ret) = t.call(hookData);
            if (!ok) {
                assembly {
                    revert(add(ret, 32), mload(ret))
                }
            }
        }
        super._update(from, to, value);
    }
}

contract ConfioMarketEscrowDepositFromTest is EscrowBase {
    address owner_ = makeAddr("owner");
    address merchant = makeAddr("merchant");
    address stranger = makeAddr("stranger");
    MockAccountFactory factory;
    MockSmartAccount account;
    bytes32 constant ID = keccak256("order-df-1");
    uint256 constant AMT = 100e18;

    function setUp() public {
        _deployEscrow();
        factory = new MockAccountFactory();
        account = new MockSmartAccount(owner_);
        factory.set(address(account), true);
        vm.prank(safe);
        escrow.setAccountFactory(address(factory));
        cusd.mint(address(account), 1_000e18);
        cusd.mint(owner_, 1_000e18);
    }

    bytes32 constant DEPOSIT_FROM_TYPEHASH = keccak256(
        "DepositFrom(bytes32 orderId,address buyer,address payer,address merchant,address token,uint256 amount,uint16 feeBps,uint256 deadline)"
    );

    /// depositFrom authorization, recomputed independently of the contract.
    function _signFrom(
        bytes32 id,
        address buyer,
        address payer,
        address merchant_,
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
        bytes32 structHash = keccak256(
            abi.encode(DEPOSIT_FROM_TYPEHASH, id, buyer, payer, merchant_, token, amount, feeBps, deadline)
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(signerKey, keccak256(abi.encodePacked("\x19\x01", domain, structHash)));
        return abi.encodePacked(r, s, v);
    }

    function _callData(bytes32 id, address buyer, address token, uint256 amount, bytes memory sig, uint256 deadline)
        internal
        view
        returns (bytes memory)
    {
        return abi.encodeCall(
            ConfioMarketEscrow.depositFrom, (id, buyer, merchant, token, amount, FEE, deadline, sig)
        );
    }

    function _depositFrom(MockSmartAccount acct, bytes32 id, address buyer) internal {
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signFrom(id, buyer, address(acct), merchant, address(cusd), AMT, FEE, deadline);
        acct.approve(IERC20(address(cusd)), address(escrow), AMT);
        acct.exec(address(escrow), _callData(id, buyer, address(cusd), AMT, sig, deadline));
    }

    function _state(bytes32 id) internal view returns (ConfioMarketEscrow.State) {
        return escrow.getOrder(id).state;
    }

    // ── happy path ──────────────────────────────────────────────────────

    function test_depositFrom_records_owner_as_buyer_and_pulls_from_account() public {
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signFrom(ID, owner_, address(account), merchant, address(cusd), AMT, FEE, deadline);
        account.approve(IERC20(address(cusd)), address(escrow), AMT);

        vm.expectEmit(address(escrow));
        emit ConfioMarketEscrow.Deposited(ID, owner_, merchant, address(cusd), AMT, FEE, uint64(block.timestamp) + SHIP);
        vm.expectEmit(address(escrow));
        emit ConfioMarketEscrow.DepositedFrom(ID, address(account), owner_);
        account.exec(address(escrow), _callData(ID, owner_, address(cusd), AMT, sig, deadline));

        ConfioMarketEscrow.Order memory o = escrow.getOrder(ID);
        assertEq(o.buyer, owner_);
        assertEq(o.merchant, merchant);
        assertEq(o.amount, AMT);
        assertEq(uint8(o.state), uint8(ConfioMarketEscrow.State.Funded));
        assertEq(escrow.refundToOf(ID), address(account));
        assertEq(cusd.balanceOf(address(account)), 1_000e18 - AMT);
        assertEq(cusd.balanceOf(owner_), 1_000e18, "owner's EOA untouched");
        assertEq(escrow.openPrincipal(address(cusd)), AMT);
    }

    function test_reclaim_by_owner_refunds_the_account() public {
        _depositFrom(account, ID, owner_);
        vm.warp(block.timestamp + SHIP + 1);
        // The account itself is not the buyer.
        vm.prank(address(account));
        vm.expectRevert(ConfioMarketEscrow.NotBuyer.selector);
        escrow.reclaim(ID);

        vm.expectEmit(address(escrow));
        emit ConfioMarketEscrow.Refunded(ID, address(account), AMT, owner_);
        vm.prank(owner_);
        escrow.reclaim(ID);
        assertEq(cusd.balanceOf(address(account)), 1_000e18);
        assertEq(cusd.balanceOf(owner_), 1_000e18);
        assertEq(escrow.openPrincipal(address(cusd)), 0);
    }

    function test_dispute_refund_by_arbiter_goes_to_the_account() public {
        _depositFrom(account, ID, owner_);
        vm.prank(owner_);
        escrow.dispute(ID);
        vm.prank(arbiter);
        escrow.resolve(ID, false);
        assertEq(uint8(_state(ID)), uint8(ConfioMarketEscrow.State.Refunded));
        assertEq(cusd.balanceOf(address(account)), 1_000e18);
        assertEq(cusd.balanceOf(owner_), 1_000e18);
    }

    function test_expired_dispute_refund_goes_to_the_account() public {
        _depositFrom(account, ID, owner_);
        vm.prank(owner_);
        escrow.dispute(ID);
        vm.warp(block.timestamp + DISPUTE_TIMEOUT);
        vm.prank(stranger);
        escrow.refundExpiredDispute(ID);
        assertEq(cusd.balanceOf(address(account)), 1_000e18);
    }

    function test_merchant_refund_goes_to_the_account() public {
        _depositFrom(account, ID, owner_);
        vm.prank(merchant);
        escrow.refund(ID);
        assertEq(cusd.balanceOf(address(account)), 1_000e18);
    }

    function test_owner_confirm_pays_merchant() public {
        _depositFrom(account, ID, owner_);
        vm.prank(owner_);
        escrow.confirm(ID);
        uint256 fee = escrow.feeFor(AMT, FEE);
        assertEq(cusd.balanceOf(merchant), AMT - fee);
        assertEq(escrow.accruedFees(address(cusd)), fee);
    }

    function test_plain_deposit_still_refunds_the_buyer() public {
        _deposit(ID, owner_, merchant, AMT);
        assertEq(escrow.refundToOf(ID), address(0));
        vm.prank(merchant);
        escrow.refund(ID);
        assertEq(cusd.balanceOf(owner_), 1_000e18);
    }

    // ── refusals ────────────────────────────────────────────────────────

    function test_refused_when_caller_is_not_an_account() public {
        MockSmartAccount rogue = new MockSmartAccount(owner_); // not in the factory
        cusd.mint(address(rogue), AMT);
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signFrom(ID, owner_, address(rogue), merchant, address(cusd), AMT, FEE, deadline);
        rogue.approve(IERC20(address(cusd)), address(escrow), AMT);
        vm.expectRevert(ConfioMarketEscrow.NotAccount.selector);
        rogue.exec(address(escrow), _callData(ID, owner_, address(cusd), AMT, sig, deadline));

        // An EOA (the owner itself) cannot use depositFrom either.
        vm.prank(owner_);
        vm.expectRevert(ConfioMarketEscrow.NotAccount.selector);
        escrow.depositFrom(ID, owner_, merchant, address(cusd), AMT, FEE, deadline, sig);
    }

    function test_refused_while_factory_unset() public {
        vm.prank(safe);
        escrow.setAccountFactory(address(0));
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signFrom(ID, owner_, address(account), merchant, address(cusd), AMT, FEE, deadline);
        account.approve(IERC20(address(cusd)), address(escrow), AMT);
        vm.expectRevert(ConfioMarketEscrow.NotAccount.selector);
        account.exec(address(escrow), _callData(ID, owner_, address(cusd), AMT, sig, deadline));
    }

    function test_refused_on_owner_mismatch() public {
        address other = makeAddr("other");
        uint256 deadline = block.timestamp + 1 hours;
        // Backend signed for `other`, account is owned by owner_.
        bytes memory sig = _signFrom(ID, other, address(account), merchant, address(cusd), AMT, FEE, deadline);
        account.approve(IERC20(address(cusd)), address(escrow), AMT);
        vm.expectRevert(ConfioMarketEscrow.NotAccountOwner.selector);
        account.exec(address(escrow), _callData(ID, other, address(cusd), AMT, sig, deadline));

        // An inherited account (owner changed) no longer pays for the old owner.
        sig = _signFrom(ID, owner_, address(account), merchant, address(cusd), AMT, FEE, deadline);
        account.setOwner(other);
        vm.expectRevert(ConfioMarketEscrow.NotAccountOwner.selector);
        account.exec(address(escrow), _callData(ID, owner_, address(cusd), AMT, sig, deadline));

        // owner() == 0 is never a buyer.
        account.setOwner(address(0));
        vm.expectRevert(ConfioMarketEscrow.NotAccountOwner.selector);
        account.exec(address(escrow), _callData(ID, address(0), address(cusd), AMT, sig, deadline));
    }

    function test_refused_with_signature_for_a_different_buyer() public {
        address other = makeAddr("other");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sigForOther = _signFrom(ID, other, address(account), merchant, address(cusd), AMT, FEE, deadline);
        account.approve(IERC20(address(cusd)), address(escrow), AMT);
        vm.expectRevert(ConfioMarketEscrow.BadAuthorization.selector);
        account.exec(address(escrow), _callData(ID, owner_, address(cusd), AMT, sigForOther, deadline));

        // A signature binding buyer = the account (plain deposit terms) is not
        // valid for depositFrom with buyer = owner either.
        bytes memory sigForAccount = _sign(ID, address(account), merchant, address(cusd), AMT, FEE, deadline);
        vm.expectRevert(ConfioMarketEscrow.BadAuthorization.selector);
        account.exec(address(escrow), _callData(ID, owner_, address(cusd), AMT, sigForAccount, deadline));
    }

    function test_owner_signature_cannot_be_spent_by_another_owners_account() public {
        address other = makeAddr("other");
        MockSmartAccount otherAccount = new MockSmartAccount(other);
        factory.set(address(otherAccount), true);
        cusd.mint(address(otherAccount), AMT);
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signFrom(ID, owner_, address(account), merchant, address(cusd), AMT, FEE, deadline);
        otherAccount.approve(IERC20(address(cusd)), address(escrow), AMT);
        vm.expectRevert(ConfioMarketEscrow.NotAccountOwner.selector);
        otherAccount.exec(address(escrow), _callData(ID, owner_, address(cusd), AMT, sig, deadline));
    }

    function test_order_id_replay_refused_both_paths() public {
        _depositFrom(account, ID, owner_);
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signFrom(ID, owner_, address(account), merchant, address(cusd), AMT, FEE, deadline);
        account.approve(IERC20(address(cusd)), address(escrow), AMT);
        vm.expectRevert(ConfioMarketEscrow.OrderExists.selector);
        account.exec(address(escrow), _callData(ID, owner_, address(cusd), AMT, sig, deadline));

        // Nor through plain deposit by the owner.
        vm.startPrank(owner_);
        cusd.approve(address(escrow), AMT);
        vm.expectRevert(ConfioMarketEscrow.OrderExists.selector);
        escrow.deposit(ID, merchant, address(cusd), AMT, FEE, deadline, sig);
        vm.stopPrank();

        // A settled order's id stays burned and refundTo stays the account.
        vm.prank(merchant);
        escrow.refund(ID);
        vm.expectRevert(ConfioMarketEscrow.OrderExists.selector);
        account.exec(address(escrow), _callData(ID, owner_, address(cusd), AMT, sig, deadline));
        assertEq(escrow.refundToOf(ID), address(account));
    }

    function test_plain_deposit_id_cannot_be_hijacked_into_account_refund() public {
        _deposit(ID, owner_, merchant, AMT);
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signFrom(ID, owner_, address(account), merchant, address(cusd), AMT, FEE, deadline);
        account.approve(IERC20(address(cusd)), address(escrow), AMT);
        vm.expectRevert(ConfioMarketEscrow.OrderExists.selector);
        account.exec(address(escrow), _callData(ID, owner_, address(cusd), AMT, sig, deadline));
        assertEq(escrow.refundToOf(ID), address(0), "failed depositFrom rolled back");
    }

    function test_self_purchase_rejected() public {
        uint256 deadline = block.timestamp + 1 hours;
        account.approve(IERC20(address(cusd)), address(escrow), AMT);
        // merchant = the owner
        bytes memory sig = _signFrom(ID, owner_, address(account), owner_, address(cusd), AMT, FEE, deadline);
        vm.expectRevert(ConfioMarketEscrow.BadMerchant.selector);
        account.exec(
            address(escrow),
            abi.encodeCall(ConfioMarketEscrow.depositFrom, (ID, owner_, owner_, address(cusd), AMT, FEE, deadline, sig))
        );
        // merchant = the paying account
        sig = _signFrom(ID, owner_, address(account), address(account), address(cusd), AMT, FEE, deadline);
        vm.expectRevert(ConfioMarketEscrow.BadMerchant.selector);
        account.exec(
            address(escrow),
            abi.encodeCall(
                ConfioMarketEscrow.depositFrom, (ID, owner_, address(account), address(cusd), AMT, FEE, deadline, sig)
            )
        );
    }

    function test_paused_blocks_depositFrom_not_exits() public {
        _depositFrom(account, ID, owner_);
        vm.prank(safe);
        escrow.pause();
        bytes32 id2 = keccak256("order-df-2");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signFrom(id2, owner_, address(account), merchant, address(cusd), AMT, FEE, deadline);
        account.approve(IERC20(address(cusd)), address(escrow), AMT);
        vm.expectRevert();
        account.exec(address(escrow), _callData(id2, owner_, address(cusd), AMT, sig, deadline));
        vm.prank(merchant);
        escrow.refund(ID);
        assertEq(cusd.balanceOf(address(account)), 1_000e18);
    }

    function test_expired_and_caps_apply_to_depositFrom() public {
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signFrom(ID, owner_, address(account), merchant, address(cusd), AMT, FEE, deadline);
        account.approve(IERC20(address(cusd)), address(escrow), AMT);
        vm.warp(deadline + 1);
        vm.expectRevert(ConfioMarketEscrow.AuthorizationExpired.selector);
        account.exec(address(escrow), _callData(ID, owner_, address(cusd), AMT, sig, deadline));

        deadline = block.timestamp + 1 hours;
        uint256 big = uint256(MAX_ORDER) + 1;
        sig = _signFrom(ID, owner_, address(account), merchant, address(cusd), big, FEE, deadline);
        vm.expectRevert(ConfioMarketEscrow.OrderTooLarge.selector);
        account.exec(address(escrow), _callData(ID, owner_, address(cusd), big, sig, deadline));
    }

    function test_setAccountFactory_owner_only() public {
        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(OwnableUpgradeable.OwnableUnauthorizedAccount.selector, stranger));
        escrow.setAccountFactory(stranger);
        vm.expectEmit(address(escrow));
        emit ConfioMarketEscrow.AccountFactoryChanged(address(factory), stranger);
        vm.prank(safe);
        escrow.setAccountFactory(stranger);
        assertEq(address(escrow.accountFactory()), stranger);
    }

    // ── reentrancy through token callbacks ──────────────────────────────

    function _cbToken() internal returns (CallbackToken cb) {
        cb = new CallbackToken();
        vm.prank(safe);
        escrow.setTokenLimits(address(cb), MAX_ORDER, MAX_OPEN);
        cb.mint(address(account), 1_000e18);
    }

    function test_reentrant_depositFrom_during_pull_reverts() public {
        CallbackToken cb = _cbToken();
        uint256 deadline = block.timestamp + 1 hours;
        bytes32 id2 = keccak256("order-df-2");
        bytes memory sig1 = _signFrom(ID, owner_, address(account), merchant, address(cb), AMT, FEE, deadline);
        bytes memory sig2 = _signFrom(id2, owner_, address(account), merchant, address(cb), AMT, FEE, deadline);
        account.approve(IERC20(address(cb)), address(escrow), 2 * AMT);
        // During the escrow's transferFrom, the account tries a second depositFrom.
        cb.arm(
            address(account),
            abi.encodeCall(MockSmartAccount.exec, (address(escrow), _callData(id2, owner_, address(cb), AMT, sig2, deadline)))
        );
        vm.expectRevert(ReentrancyGuardTransient.ReentrancyGuardReentrantCall.selector);
        account.exec(address(escrow), _callData(ID, owner_, address(cb), AMT, sig1, deadline));
        assertEq(cb.balanceOf(address(escrow)), 0);
        assertEq(escrow.refundToOf(ID), address(0));
    }

    function test_reentrant_reclaim_during_refund_cannot_double_pay() public {
        CallbackToken cb = _cbToken();
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signFrom(ID, owner_, address(account), merchant, address(cb), AMT, FEE, deadline);
        account.approve(IERC20(address(cb)), address(escrow), AMT);
        account.exec(address(escrow), _callData(ID, owner_, address(cb), AMT, sig, deadline));
        vm.warp(block.timestamp + SHIP + 1);

        // While the merchant's refund transfers, the owner's EOA reclaims again.
        cb.arm(address(escrow), abi.encodeCall(ConfioMarketEscrow.reclaim, (ID)));
        vm.prank(merchant);
        vm.expectRevert(ReentrancyGuardTransient.ReentrancyGuardReentrantCall.selector);
        escrow.refund(ID);
        assertEq(cb.balanceOf(address(escrow)), AMT, "nothing left");

        // The revert rolled back the one-shot disarm too; disarm explicitly.
        cb.arm(address(0), "");
        vm.prank(owner_);
        escrow.reclaim(ID);
        assertEq(cb.balanceOf(address(account)), 1_000e18);
        assertEq(cb.balanceOf(address(escrow)), 0);
    }

    // ── payer binding (audit L1) ────────────────────────────────────────

    function test_eoa_order_signature_refused_by_depositFrom() public {
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory eoaSig = _sign(ID, owner_, merchant, address(cusd), AMT, FEE, deadline);
        account.approve(IERC20(address(cusd)), address(escrow), AMT);
        vm.expectRevert(ConfioMarketEscrow.BadAuthorization.selector);
        account.exec(address(escrow), _callData(ID, owner_, address(cusd), AMT, eoaSig, deadline));
    }

    function test_account_order_signature_refused_by_plain_deposit() public {
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory accSig = _signFrom(ID, owner_, address(account), merchant, address(cusd), AMT, FEE, deadline);
        vm.startPrank(owner_);
        cusd.approve(address(escrow), AMT);
        vm.expectRevert(ConfioMarketEscrow.BadAuthorization.selector);
        escrow.deposit(ID, merchant, address(cusd), AMT, FEE, deadline, accSig);
        vm.stopPrank();
    }

    function test_account_order_signature_refused_by_another_account_of_same_owner() public {
        // e.g. the owner's older/newer generation account
        MockSmartAccount second = new MockSmartAccount(owner_);
        factory.set(address(second), true);
        cusd.mint(address(second), AMT);
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory accSig = _signFrom(ID, owner_, address(account), merchant, address(cusd), AMT, FEE, deadline);
        second.approve(IERC20(address(cusd)), address(escrow), AMT);
        vm.expectRevert(ConfioMarketEscrow.BadAuthorization.selector);
        second.exec(address(escrow), _callData(ID, owner_, address(cusd), AMT, accSig, deadline));
        // and the right account can still spend it
        account.approve(IERC20(address(cusd)), address(escrow), AMT);
        account.exec(address(escrow), _callData(ID, owner_, address(cusd), AMT, accSig, deadline));
        assertEq(escrow.refundToOf(ID), address(account));
    }

    function test_depositFrom_digest_matches_independent_encoding() public view {
        bytes32 want = keccak256(
            abi.encodePacked(
                "\x19\x01",
                keccak256(
                    abi.encode(
                        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
                        keccak256("ConfioMarketEscrow"),
                        keccak256("1"),
                        block.chainid,
                        address(escrow)
                    )
                ),
                keccak256(
                    abi.encode(DEPOSIT_FROM_TYPEHASH, ID, owner_, address(account), merchant, address(cusd), AMT, FEE, uint256(7))
                )
            )
        );
        assertEq(escrow.depositFromDigest(ID, owner_, address(account), merchant, address(cusd), AMT, FEE, 7), want);
        assertTrue(want != escrow.depositDigest(ID, owner_, merchant, address(cusd), AMT, FEE, 7));
    }

    // ── upgrade: existing orders keep refunding the buyer ───────────────

    function test_upgrade_with_factory_call_keeps_plain_orders() public {
        // A plain order from before the upgrade.
        _deposit(ID, owner_, merchant, AMT);
        ConfioMarketEscrow newImpl = new ConfioMarketEscrow();
        MockAccountFactory f2 = new MockAccountFactory();
        vm.prank(safe);
        escrow.upgradeToAndCall(address(newImpl), abi.encodeCall(ConfioMarketEscrow.setAccountFactory, (address(f2))));
        assertEq(address(escrow.accountFactory()), address(f2));
        vm.prank(merchant);
        escrow.refund(ID);
        assertEq(cusd.balanceOf(owner_), 1_000e18);
    }

    function testFuzz_refund_goes_to_payer(bool viaAccount, uint96 amount) public {
        uint256 amt = bound(uint256(amount), 1e18, MAX_ORDER);
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = viaAccount
            ? _signFrom(ID, owner_, address(account), merchant, address(cusd), amt, FEE, deadline)
            : _sign(ID, owner_, merchant, address(cusd), amt, FEE, deadline);
        address payer;
        if (viaAccount) {
            payer = address(account);
            account.approve(IERC20(address(cusd)), address(escrow), amt);
            account.exec(address(escrow), _callData(ID, owner_, address(cusd), amt, sig, deadline));
        } else {
            payer = owner_;
            vm.startPrank(owner_);
            cusd.approve(address(escrow), amt);
            escrow.deposit(ID, merchant, address(cusd), amt, FEE, deadline, sig);
            vm.stopPrank();
        }
        uint256 before = cusd.balanceOf(payer);
        vm.prank(merchant);
        escrow.refund(ID);
        assertEq(cusd.balanceOf(payer), before + amt);
    }
}
