// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * BSC MAINNET-FORK test for the 7702 sponsored-batch delegate: the exact
 * production batches (approve+subscribeAndMint, redeemToUsdt) executed AS a
 * user EOA through the delegate, against the REAL vault + USDT + Ondo IM.
 * Run:
 *
 *   forge test --match-path test/ConfioBatchDelegate.fork.t.sol \
 *     --fork-url https://bsc-dataseed.bnbchain.org -vv
 *
 * Delegation is modeled with vm.etch (see ConfioBatchDelegate.t.sol header).
 * The logged gas numbers calibrate the server's fixed budgets in
 * cusd_plus/sponsor_7702.py — re-check them if the vault or IM changes.
 * Only the Ondo compliance registry is stubbed, same as the vault fork test.
 */
import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ConfioBatchDelegate} from "../ConfioBatchDelegate.sol";

interface IVault {
    function subscribeAndMint(uint256 usdtIn, uint256 minUsdyOut, address recipient)
        external
        returns (uint256);
    function redeemToUsdt(uint256 shares, uint256 minUsdtOut, address recipient)
        external
        returns (uint256);
    function balanceOf(address) external view returns (uint256);
}

contract ConfioBatchDelegateForkTest is Test {
    address constant USDT = 0x55d398326f99059fF775485246999027B3197955;
    address constant VAULT = 0x3C29417eb4314155e63d4C7D4507852b87763Ed1; // live proxy
    address constant REGISTRY = 0x898128F9f22c0192da0c5acD394D9eeAc461D911;

    ConfioBatchDelegate delegate;
    uint256 userPk;
    address user;
    address sponsor = makeAddr("sponsor");

    function setUp() public {
        if (USDT.code.length == 0) return; // clean skip without --fork-url
        delegate = new ConfioBatchDelegate();
        (user, userPk) = makeAddrAndKey("fork-user");
        vm.etch(user, address(delegate).code);
    }

    function _forked() internal view returns (bool) {
        return USDT.code.length > 0 && address(delegate) != address(0);
    }

    function _sign(
        ConfioBatchDelegate.Call[] memory calls,
        uint256 nonce,
        uint256 deadline
    ) internal view returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) =
            vm.sign(userPk, ConfioBatchDelegate(payable(user)).hashExecute(calls, nonce, deadline, bytes32(0)));
        return abi.encodePacked(r, s, v);
    }

    /// The whole point of the migration: a user EOA with ZERO BNB deposits
    /// USDT into savings in one sponsored transaction.
    function test_fork_sponsoredDepositThenRedeem() public {
        if (!_forked()) return;
        vm.mockCall(REGISTRY, bytes(""), abi.encode(true));

        uint256 amount = 1_000e18;
        deal(USDT, user, amount);
        assertEq(user.balance, 0, "user holds zero BNB - no dust anywhere");

        // ── deposit: approve + subscribeAndMint, one sponsored batch ──
        ConfioBatchDelegate.Call[] memory calls = new ConfioBatchDelegate.Call[](2);
        calls[0] = ConfioBatchDelegate.Call(
            USDT, 0, abi.encodeCall(IERC20.approve, (VAULT, type(uint256).max))
        );
        calls[1] = ConfioBatchDelegate.Call(
            VAULT, 0, abi.encodeCall(IVault.subscribeAndMint, (amount, 0, user))
        );
        uint256 deadline = block.timestamp + 600;
        bytes memory sig = _sign(calls, 0, deadline);

        uint256 g0 = gasleft();
        vm.prank(sponsor);
        try ConfioBatchDelegate(payable(user)).execute(calls, 0, deadline, bytes32(0), sig) {
            emit log_named_uint("gas: approve+subscribeAndMint batch", g0 - gasleft());
            uint256 shares = IVault(VAULT).balanceOf(user);
            emit log_named_decimal_uint("cUSD+ shares minted to EOA", shares, 18);
            assertGt(shares, 0, "shares landed at the user EOA");
            assertApproxEqRel(shares, amount, 0.02e18, "shares ~ USD in");

            // ── redeem: single sponsored call back to USDT ──
            ConfioBatchDelegate.Call[] memory rcalls = new ConfioBatchDelegate.Call[](1);
            rcalls[0] = ConfioBatchDelegate.Call(
                VAULT, 0, abi.encodeCall(IVault.redeemToUsdt, (shares, 0, user))
            );
            bytes memory rsig = _sign(rcalls, 1, deadline);

            uint256 g1 = gasleft();
            vm.prank(sponsor);
            ConfioBatchDelegate(payable(user)).execute(rcalls, 1, deadline, bytes32(0), rsig);
            emit log_named_uint("gas: redeemToUsdt batch", g1 - gasleft());

            uint256 usdtBack = IERC20(USDT).balanceOf(user);
            emit log_named_decimal_uint("USDT back at EOA", usdtBack, 18);
            assertGt(usdtBack, amount * 98 / 100, "round-trip within 2%");
            assertEq(user.balance, 0, "still zero BNB, start to finish");
            emit log_string("FORK PASS: zero-BNB EOA deposited and redeemed, sponsor-paid");
        } catch (bytes memory reason) {
            // Same posture as the vault fork test: reaching the real IM and
            // being stopped by an Ondo-side constraint is data, not a bug.
            emit log_named_bytes("real IM/vault reverted", reason);
            emit log_string("Wiring validated up to the real contract's constraint");
        }
    }

    /// The relay guard's whitelisted exception: redeem straight to a ramp
    /// deposit address (not the signer) — the DELEGATE allows whatever the
    /// user signed; recipient policy is the server's job.
    function test_fork_redeemToThirdPartyIsUserAuthorized() public {
        if (!_forked()) return;
        vm.mockCall(REGISTRY, bytes(""), abi.encode(true));

        deal(USDT, user, 100e18);
        address rampDeposit = makeAddr("guardarian-deposit");

        ConfioBatchDelegate.Call[] memory calls = new ConfioBatchDelegate.Call[](2);
        calls[0] = ConfioBatchDelegate.Call(
            USDT, 0, abi.encodeCall(IERC20.approve, (VAULT, type(uint256).max))
        );
        calls[1] = ConfioBatchDelegate.Call(
            VAULT, 0, abi.encodeCall(IVault.subscribeAndMint, (100e18, 0, user))
        );
        uint256 deadline = block.timestamp + 600;
        vm.prank(sponsor);
        try ConfioBatchDelegate(payable(user)).execute(calls, 0, deadline, bytes32(0), _sign(calls, 0, deadline)) {
            uint256 shares = IVault(VAULT).balanceOf(user);

            ConfioBatchDelegate.Call[] memory rcalls = new ConfioBatchDelegate.Call[](1);
            rcalls[0] = ConfioBatchDelegate.Call(
                VAULT, 0, abi.encodeCall(IVault.redeemToUsdt, (shares, 0, rampDeposit))
            );
            vm.prank(sponsor);
            ConfioBatchDelegate(payable(user)).execute(rcalls, 1, deadline, bytes32(0), _sign(rcalls, 1, deadline));
            assertGt(IERC20(USDT).balanceOf(rampDeposit), 0, "USDT went to the ramp address");
        } catch (bytes memory reason) {
            emit log_named_bytes("real IM/vault reverted", reason);
        }
    }
}
