// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {IERC20Errors} from "@openzeppelin/contracts/interfaces/draft-IERC6093.sol";
import {ConfioToken} from "../ConfioToken.sol";

contract ConfioTokenTest is Test {
    ConfioToken token;
    address treasury = makeAddr("treasurySafe");
    address user;
    uint256 userKey;

    function setUp() public {
        (user, userKey) = makeAddrAndKey("user");
        token = new ConfioToken(treasury);
    }

    function test_metadata_and_fixed_supply() public view {
        assertEq(token.name(), unicode"Confío");
        assertEq(token.symbol(), "CONFIO");
        assertEq(token.decimals(), 18);
        assertEq(token.totalSupply(), 1_000_000_000e18);
        assertEq(token.balanceOf(treasury), 1_000_000_000e18);
    }

    function test_constructor_rejects_zero_treasury() public {
        vm.expectRevert(ConfioToken.ZeroAddress.selector);
        new ConfioToken(address(0));
    }

    function test_transfer_and_burn() public {
        vm.prank(treasury);
        token.transfer(user, 100e18);
        assertEq(token.balanceOf(user), 100e18);

        // holders can burn their own — supply shrinks, nothing can re-mint
        vm.prank(user);
        token.burn(40e18);
        assertEq(token.balanceOf(user), 60e18);
        assertEq(token.totalSupply(), 1_000_000_000e18 - 40e18);

        // burnFrom needs allowance like any transferFrom
        vm.prank(user);
        vm.expectRevert(
            abi.encodeWithSelector(
                IERC20Errors.ERC20InsufficientAllowance.selector, user, 0, 1e18
            )
        );
        token.burnFrom(treasury, 1e18);
    }

    function test_permit_signature_approval() public {
        vm.prank(treasury);
        token.transfer(user, 10e18);

        address spender = makeAddr("spender");
        uint256 deadline = block.timestamp + 1 hours;
        bytes32 structHash = keccak256(abi.encode(
            keccak256("Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)"),
            user, spender, 10e18, token.nonces(user), deadline
        ));
        bytes32 digest = keccak256(abi.encodePacked(hex"1901", token.DOMAIN_SEPARATOR(), structHash));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(userKey, digest);

        token.permit(user, spender, 10e18, deadline, v, r, s);
        assertEq(token.allowance(user, spender), 10e18);

        vm.prank(spender);
        token.transferFrom(user, spender, 10e18);
        assertEq(token.balanceOf(spender), 10e18);
    }
}
