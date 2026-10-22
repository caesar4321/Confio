// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * BSC MAINNET-FORK rehearsal: DeployConfioMarketEscrow against the LIVE
 * universal cUSD proxy and the LIVE 3-of-5 Safe (pranked). Run:
 *
 *   forge test --match-path test/ConfioMarketEscrow.fork.t.sol \
 *     --fork-url https://bsc-dataseed.bnbchain.org -vv
 *
 * What only the fork proves beyond the mock suite:
 *  - the deploy script's mainnet branch (owner forced to the Safe, no token
 *    enabled, impl slot, roles, windows) on the real chain
 *  - the real cUSD token through every exit, including its global pause:
 *    while cUSD is paused, escrow exits stall (they resume on unpause) —
 *    cUSD has no per-address freeze, so no single merchant can be frozen out
 *  - a Safe-driven UUPS upgrade with open orders on the real proxy layout
 */
import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ConfioMarketEscrow} from "../ConfioMarketEscrow.sol";
import {DeployConfioMarketEscrow} from "../script/DeployConfioMarketEscrow.s.sol";

interface IPausableToken {
    function pause() external;
    function unpause() external;
    function owner() external view returns (address);
}

contract ConfioMarketEscrowV2Fork is ConfioMarketEscrow {
    function version() external pure returns (uint256) {
        return 2;
    }
}

contract ConfioMarketEscrowForkTest is Test {
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    address constant CUSD = 0x6101cC370635cF2c7f2725EaB010aC407A8d543F;

    uint256 signerKey = 0x5161E7;
    address orderSigner;
    address arbiter = makeAddr("arbiter");
    address buyer = makeAddr("buyer");
    address merchant = makeAddr("merchant");

    ConfioMarketEscrow escrow;
    address impl;
    bool forked;

    function setUp() public {
        if (block.chainid != 56 || CUSD.code.length == 0) return; // skip cleanly without --fork-url
        forked = true;
        orderSigner = vm.addr(signerKey);
        vm.setEnv("MARKET_ESCROW_ORDER_SIGNER", vm.toString(orderSigner));
        vm.setEnv("MARKET_ESCROW_ARBITER", vm.toString(arbiter));
        // The script's own startBroadcast picks the sender (pranks and
        // broadcasts don't mix); on chain 56 the owner is forced to the Safe
        // whoever deploys.
        DeployConfioMarketEscrow script = new DeployConfioMarketEscrow();
        (escrow, impl) = script.run();
        deal(CUSD, buyer, 1_000e18);
    }

    function _sign(bytes32 id, uint256 amount, uint256 deadline) internal view returns (bytes memory) {
        bytes32 digest = escrow.depositDigest(id, buyer, merchant, CUSD, amount, 800, deadline);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(signerKey, digest);
        return abi.encodePacked(r, s, v);
    }

    function _deposit(bytes32 id, uint256 amount) internal {
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _sign(id, amount, deadline);
        vm.startPrank(buyer);
        IERC20(CUSD).approve(address(escrow), amount);
        escrow.deposit(id, merchant, CUSD, amount, 800, deadline, sig);
        vm.stopPrank();
    }

    function _enableCusd() internal {
        vm.prank(SAFE);
        escrow.setTokenLimits(CUSD, 300e18, 10_000e18);
    }

    function test_fork_deploy_shape() public {
        if (!forked) return;
        assertEq(escrow.owner(), SAFE);
        assertEq(escrow.orderSigner(), orderSigner);
        assertEq(escrow.arbiter(), arbiter);
        assertEq(escrow.shipWindow(), 3 days);
        assertEq(escrow.releaseWindow(), 4 days);
        assertEq(escrow.disputeTimeout(), 30 days);
        (uint128 maxOrder,) = escrow.tokenLimits(CUSD);
        assertEq(maxOrder, 0, "mainnet deploy must enable no token");

        // Nothing is accepted until the Safe enables cUSD.
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _sign(keccak256("early"), 50e18, deadline);
        vm.prank(buyer);
        vm.expectRevert(ConfioMarketEscrow.TokenNotAccepted.selector);
        escrow.deposit(keccak256("early"), merchant, CUSD, 50e18, 800, deadline, sig);
    }

    function test_fork_full_lifecycle_on_real_cusd() public {
        if (!forked) return;
        _enableCusd();

        // 1. Shipped + confirmed: 92 to the merchant, 8 accrued.
        _deposit(keccak256("a"), 100e18);
        vm.prank(merchant);
        escrow.markShipped(keccak256("a"));
        vm.prank(buyer);
        escrow.confirm(keccak256("a"));
        assertEq(IERC20(CUSD).balanceOf(merchant), 92e18);

        // 2. Disputed, arbiter refunds.
        _deposit(keccak256("b"), 50e18);
        vm.prank(buyer);
        escrow.dispute(keccak256("b"));
        vm.prank(arbiter);
        escrow.resolve(keccak256("b"), false);

        // 3. Never shipped, buyer reclaims after the ship window.
        _deposit(keccak256("c"), 40e18);
        // 4. Shipped, auto-released by a keeper after the release window.
        _deposit(keccak256("d"), 60e18);
        vm.prank(merchant);
        escrow.markShipped(keccak256("d"));
        vm.warp(block.timestamp + 4 days);
        escrow.release(keccak256("d"));
        vm.prank(buyer);
        escrow.reclaim(keccak256("c"));

        assertEq(IERC20(CUSD).balanceOf(merchant), 92e18 + 55.2e18);
        assertEq(IERC20(CUSD).balanceOf(buyer), 1_000e18 - 100e18 - 60e18);
        assertEq(escrow.openPrincipal(CUSD), 0);
        assertEq(escrow.accruedFees(CUSD), 8e18 + 4.8e18);
        assertEq(IERC20(CUSD).balanceOf(address(escrow)), 12.8e18);

        uint256 safeBefore = IERC20(CUSD).balanceOf(SAFE);
        vm.prank(SAFE);
        escrow.collectFees(CUSD, SAFE, 12.8e18);
        assertEq(IERC20(CUSD).balanceOf(SAFE) - safeBefore, 12.8e18);
        assertEq(IERC20(CUSD).balanceOf(address(escrow)), 0);
    }

    function test_fork_cusd_pause_stalls_then_resumes_exits() public {
        if (!forked) return;
        _enableCusd();
        _deposit(keccak256("p"), 100e18);
        address cusdOwner = IPausableToken(CUSD).owner();
        vm.prank(cusdOwner);
        IPausableToken(CUSD).pause();
        vm.prank(buyer);
        vm.expectRevert();
        escrow.confirm(keccak256("p"));
        vm.prank(cusdOwner);
        IPausableToken(CUSD).unpause();
        vm.prank(buyer);
        escrow.confirm(keccak256("p"));
        assertEq(IERC20(CUSD).balanceOf(merchant), 92e18);
    }

    function test_fork_safe_upgrade_keeps_open_orders() public {
        if (!forked) return;
        _enableCusd();
        _deposit(keccak256("u"), 100e18);
        ConfioMarketEscrowV2Fork v2 = new ConfioMarketEscrowV2Fork();
        vm.prank(SAFE);
        escrow.upgradeToAndCall(address(v2), "");
        assertEq(ConfioMarketEscrowV2Fork(address(escrow)).version(), 2);
        assertEq(escrow.getOrder(keccak256("u")).amount, 100e18);
        assertEq(escrow.owner(), SAFE);
        vm.prank(merchant);
        escrow.refund(keccak256("u"));
        assertEq(IERC20(CUSD).balanceOf(buyer), 1_000e18);
    }
}
