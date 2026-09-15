// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {AccountActivationCollector} from "../AccountActivationCollector.sol";

contract ActivationTestToken is ERC20 {
    constructor() ERC20("Confio Dollar", "cUSD") {}
    function mint(address to, uint256 amount) external { _mint(to, amount); }
}

contract AccountActivationCollectorTest is Test {
    ActivationTestToken token;
    AccountActivationCollector collector;
    address treasury = address(0x1234);
    address payer = address(0x5678);

    function setUp() public {
        token = new ActivationTestToken();
        collector = new AccountActivationCollector(token, treasury);
    }

    function testReceiveFeeAndPermissionlessSweepToFixedTreasury() public {
        token.mint(payer, 10 ether);
        vm.prank(payer);
        token.transfer(address(collector), 10 ether);
        assertEq(token.balanceOf(address(collector)), 10 ether);
        vm.prank(address(0xBAD));
        collector.sweep();
        assertEq(token.balanceOf(treasury), 10 ether);
        assertEq(token.balanceOf(address(0xBAD)), 0);
        assertEq(token.balanceOf(address(collector)), 0);
        collector.sweep();
        assertEq(token.balanceOf(treasury), 10 ether);
    }

    function testFuzzSweepNeverPaysCaller(address caller, uint128 amount) public {
        vm.assume(caller != treasury && caller != address(collector));
        token.mint(address(collector), amount);
        vm.prank(caller);
        collector.sweep();
        assertEq(token.balanceOf(treasury), amount);
        assertEq(token.balanceOf(caller), 0);
    }

    function testNoRefundOrArbitraryWithdrawalOrUpgrade() public {
        token.mint(address(collector), 10 ether);
        (bool refund,) = address(collector).call(abi.encodeWithSignature("refund(address,uint256)", payer, 10 ether));
        (bool withdraw,) = address(collector).call(abi.encodeWithSignature("withdraw(address,uint256)", payer, 10 ether));
        (bool redirect,) = address(collector).call(abi.encodeWithSignature("setTreasury(address)", payer));
        (bool upgrade,) = address(collector).call(abi.encodeWithSignature("upgradeToAndCall(address,bytes)", payer, ""));
        assertFalse(refund); assertFalse(withdraw); assertFalse(redirect); assertFalse(upgrade);
        assertEq(token.balanceOf(address(collector)), 10 ether);
    }

    function testRejectInvalidConfiguration() public {
        vm.expectRevert(AccountActivationCollector.InvalidConfiguration.selector);
        new AccountActivationCollector(token, address(0));
        vm.expectRevert(AccountActivationCollector.InvalidConfiguration.selector);
        new AccountActivationCollector(ActivationTestToken(address(0xBAD)), treasury);
    }
}
