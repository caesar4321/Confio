// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {CusdVault} from "../CusdVault.sol";
import {CusdMockUsdt, MockSavingsVault} from "./CusdVault.t.sol";

/// Stand-in for ConfioSmartAccountFactory: only isAccount.
contract MockSmartAccountFactory {
    mapping(address => bool) public isAccount;

    function setAccount(address account, bool yes) external {
        isAccount[account] = yes;
    }
}

/// Stand-in for a Cuenta inteligente: reports a factory and can arm and
/// convert as itself, the way the account's relayer functions do.
contract MockSmartAccount {
    address public FACTORY;

    constructor(address factory) {
        FACTORY = factory;
    }

    function arm(CusdVault vault, address referrer, uint256 shareBps) external {
        vault.armReferral(referrer, shareBps);
    }

    function mint(CusdVault vault, CusdMockUsdt usdt, uint256 amount) external returns (uint256) {
        usdt.approve(address(vault), amount);
        return vault.mintWithFee(amount, 0, address(this));
    }
}

/// A contract with no FACTORY() at all.
contract PlainContract {
    function arm(CusdVault vault, address referrer, uint256 shareBps) external {
        vault.armReferral(referrer, shareBps);
    }
}

/// Decision 32 (docs/designs/cuenta-inteligente-spec.md, 7.4): armReferral
/// also accepts an account created by a recognised factory. Everything else
/// in armReferral and _payReferral is unchanged.
contract CusdVaultSmartAccountReferralTest is Test {
    CusdMockUsdt usdt;
    CusdVault vault;
    MockSmartAccountFactory factory;
    MockSmartAccount account;

    address treasury = makeAddr("treasury");
    address sponsor = makeAddr("sponsor");
    address user = makeAddr("user");
    address referrer = makeAddr("referrer");
    address delegate = makeAddr("batchDelegate");

    event SmartAccountFactorySet(address indexed factory, bool allowed);
    event ReferralPaid(
        address indexed referee, address indexed referrer, uint256 feeUsdt, uint256 shareCusd, uint256 shareBps
    );

    function setUp() public {
        usdt = new CusdMockUsdt();
        vault = CusdVault(
            address(
                new ERC1967Proxy(address(new CusdVault(address(usdt))), abi.encodeCall(CusdVault.initialize, (treasury, 90)))
            )
        );
        factory = new MockSmartAccountFactory();
        account = new MockSmartAccount(address(factory));
        factory.setAccount(address(account), true);

        vm.startPrank(treasury);
        vault.setSponsor(sponsor, true);
        vault.setSavingsVault(address(new MockSavingsVault()));
        vault.setReferralShareCapBps(5_000);
        vault.setBatchDelegate(delegate);
        vault.setSmartAccountFactory(address(factory), true);
        vm.stopPrank();

        vm.etch(user, abi.encodePacked(hex"ef0100", delegate));
        usdt.mint(address(account), 1_000e18);
        usdt.mint(user, 1_000e18);
        vm.prank(user);
        usdt.approve(address(vault), type(uint256).max);
    }

    function test_accountOfRecognisedFactory_armsAndReferrerIsPaid() public {
        vm.prank(sponsor, sponsor);
        account.arm(vault, referrer, 5_000);
        (address armed, address referee, uint256 share) = vault.armedReferral();
        assertEq(armed, referrer);
        assertEq(referee, address(account), "the account is the referee");
        assertEq(share, 5_000);

        vm.expectEmit(true, true, false, true, address(vault));
        emit ReferralPaid(address(account), referrer, 0.9e18, 0.45e18, 5_000);
        vm.prank(sponsor, sponsor);
        uint256 net = account.mint(vault, usdt, 100e18);
        assertEq(net, 99.1e18, "the account's cost is unchanged");
        assertEq(vault.balanceOf(referrer), 0.45e18);
        assertEq(vault.accruedEntryFees(), 0.45e18);
        assertTrue(vault.isFullyBacked());
    }

    function test_unrecognisedFactory_cannotArm() public {
        vm.prank(treasury);
        vault.setSmartAccountFactory(address(factory), false);
        vm.prank(sponsor, sponsor);
        vm.expectRevert(bytes("not a Confio account"));
        account.arm(vault, referrer, 5_000);
    }

    /// Naming a real, recognised factory is not enough: the factory must
    /// confirm it created the caller.
    function test_contractNamingARealFactory_cannotArm() public {
        MockSmartAccount impostor = new MockSmartAccount(address(factory));
        vm.prank(sponsor, sponsor);
        vm.expectRevert(bytes("not a Confio account"));
        impostor.arm(vault, referrer, 5_000);
    }

    function test_arbitraryContract_cannotArm() public {
        PlainContract plain = new PlainContract();
        vm.prank(sponsor, sponsor);
        vm.expectRevert(bytes("not a Confio account"));
        plain.arm(vault, referrer, 5_000);
    }

    function test_plainEoa_cannotArm() public {
        vm.prank(makeAddr("eoa"), sponsor);
        vm.expectRevert(bytes("not a Confio account"));
        vault.armReferral(referrer, 5_000);
    }

    function test_account_stillNeedsSponsorOrigin() public {
        vm.prank(user, user);
        vm.expectRevert(bytes("not sponsored"));
        account.arm(vault, referrer, 5_000);
    }

    function test_account_otherChecksUnchanged() public {
        vm.startPrank(sponsor, sponsor);
        vm.expectRevert(bytes("self referral"));
        account.arm(vault, address(account), 5_000);
        vm.expectRevert(bytes("bad share"));
        account.arm(vault, referrer, 5_001);
        vm.expectRevert(bytes("zero referrer"));
        account.arm(vault, address(0), 5_000);
        account.arm(vault, referrer, 5_000);
        vm.expectRevert(bytes("already armed"));
        account.arm(vault, referrer, 5_000);
        vm.stopPrank();
    }

    function test_existingEoaArming_unchanged() public {
        vm.prank(user, sponsor);
        vault.armReferral(referrer, 5_000);
        vm.prank(user, sponsor);
        vault.mintWithFee(100e18, 0, user);
        assertEq(vault.balanceOf(referrer), 0.45e18);
    }

    function test_setSmartAccountFactory_onlyOwner_andEvent() public {
        address other = address(new MockSmartAccountFactory());
        vm.expectRevert();
        vault.setSmartAccountFactory(other, true);

        vm.startPrank(treasury);
        vm.expectRevert(bytes("zero factory"));
        vault.setSmartAccountFactory(address(0), true);
        vm.expectRevert(bytes("factory not contract"));
        vault.setSmartAccountFactory(makeAddr("noCode"), true);
        vm.expectEmit(true, false, false, true, address(vault));
        emit SmartAccountFactorySet(other, true);
        vault.setSmartAccountFactory(other, true);
        vm.stopPrank();
        assertTrue(vault.isSmartAccountFactory(other));
    }

    /// The new mapping is appended: the slot after batchDelegate.
    function test_storage_newMappingIsAppendedAfterBatchDelegate() public view {
        // OZ v5 upgradeable parents use namespaced storage, so the vault's
        // own variables start at slot 0: feeBps 0, accruedEntryFees 1,
        // accruedExitFees 2, isSponsor 3, savingsVault 4, frozen 5,
        // referralShareCapBps 6, batchDelegate 7, isSmartAccountFactory 8.
        assertEq(uint256(vm.load(address(vault), bytes32(uint256(0)))), 90, "feeBps slot");
        assertEq(uint256(vm.load(address(vault), bytes32(uint256(6)))), 5_000, "cap slot");
        assertEq(address(uint160(uint256(vm.load(address(vault), bytes32(uint256(7)))))), delegate, "delegate slot");
        bytes32 slot = keccak256(abi.encode(address(factory), uint256(8)));
        assertEq(uint256(vm.load(address(vault), slot)), 1, "isSmartAccountFactory at slot 8");
    }
}
