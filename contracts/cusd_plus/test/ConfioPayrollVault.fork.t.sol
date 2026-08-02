// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * BSC MAINNET-FORK: ConfioPayrollVault against the LIVE CusdPlusVault
 * (0x3C29…3Ed1, WHITELISTED in OndoIDRegistry 2026-07-30). Run:
 *
 *   forge test --match-path test/ConfioPayrollVault.fork.t.sol \
 *     --fork-url https://bsc-dataseed.bnbchain.org -vv
 *
 * What only the fork proves beyond the mock suite:
 *  - shares minted by the REAL vault flow through deposit/escrow/payout
 *  - the redeem branch drives the real vault → real Ondo IM → real BSC
 *    USDT landing at the recipient (registry gate included, no mocks)
 */
import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ConfioPayrollVault} from "../ConfioPayrollVault.sol";
import {CusdPlusVault} from "../CusdPlusVault.sol";

contract ConfioPayrollVaultForkTest is Test {
    address constant VAULT = 0x3C29417eb4314155e63d4C7D4507852b87763Ed1;
    address constant USDT = 0x55d398326f99059fF775485246999027B3197955;

    address safeOwner = makeAddr("safeOwner");
    address employee = makeAddr("employee");
    address sponsor = makeAddr("sponsor");

    uint256 delegateKey = 0xDE1;
    uint256 businessKey = 0xB0B;
    address business;
    address delegate;

    ConfioPayrollVault payroll;
    CusdPlusVault vault;

    function setUp() public {
        if (VAULT.code.length == 0) return; // skip cleanly without --fork-url
        business = vm.addr(businessKey);
        delegate = vm.addr(delegateKey);
        vault = CusdPlusVault(VAULT);
        payroll = new ConfioPayrollVault(VAULT, safeOwner);

        // Fund the business with real USDT, mint real cUSD+, park it.
        // minUsdyOut is in USDY terms: at the live USDY price (~$1.14)
        // 500 USDT buys ~438 USDY, so the floor must sit BELOW that.
        deal(USDT, business, 1_000e18);
        vm.startPrank(business);
        IERC20(USDT).approve(VAULT, type(uint256).max);
        uint256 shares = vault.subscribeAndMint(500e18, 400e18, business);
        vault.approve(address(payroll), type(uint256).max);
        payroll.deposit(ConfioPayrollVault.Asset.CusdPlus, shares);
        // Real USDT escrow too: the leg an Ondo-blocked employer lives on,
        // against the real BSC token rather than a mock.
        IERC20(USDT).approve(address(payroll), type(uint256).max);
        payroll.deposit(ConfioPayrollVault.Asset.Usdt, 200e18);
        payroll.setDelegate(delegate, true);
        vm.stopPrank();
    }

    function _forked() internal view returns (bool) {
        return VAULT.code.length > 0 && address(payroll) != address(0);
    }

    function _signedPayout(bool redeem)
        internal
        view
        returns (ConfioPayrollVault.Payout memory p, bytes memory sig)
    {
        p = ConfioPayrollVault.Payout({
            business: business,
            recipient: employee,
            asset: ConfioPayrollVault.Asset.CusdPlus,
            netAmount: 100e18,
            feeAmount: 1e18,
            redeemToUsdt: redeem,
            minUsdtOut: redeem ? 98e18 : 0,
            itemId: bytes32("fork-item"),
            deadline: block.timestamp + 1 hours
        });
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(delegateKey, payroll.payoutDigest(p));
        sig = abi.encodePacked(r, s, v);
    }

    function test_fork_payout_transfer_realShares() public {
        if (!_forked()) return;
        (ConfioPayrollVault.Payout memory p, bytes memory sig) = _signedPayout(false);
        vm.prank(sponsor);
        payroll.payout(p, sig);
        assertEq(vault.balanceOf(employee), 100e18, "real vault shares moved");
        assertEq(payroll.accruedFeeShares(), 1e18);
    }

    /// The Ondo-blocked employer's rail, end to end on real tokens: USDT
    /// parked, USDT paid, no vault share involved anywhere.
    function test_fork_payout_from_usdt_escrow() public {
        if (!_forked()) return;
        ConfioPayrollVault.Payout memory p = ConfioPayrollVault.Payout({
            business: business,
            recipient: employee,
            asset: ConfioPayrollVault.Asset.Usdt,
            netAmount: 100e18,
            feeAmount: 1e18,
            redeemToUsdt: false,
            minUsdtOut: 0,
            itemId: bytes32("fork-usdt-item"),
            deadline: block.timestamp + 1 hours
        });
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(delegateKey, payroll.payoutDigest(p));
        vm.prank(sponsor);
        payroll.payout(p, abi.encodePacked(r, s, v));
        assertEq(IERC20(USDT).balanceOf(employee), 100e18, "real USDT paid");
        assertEq(vault.balanceOf(employee), 0, "no shares involved");
        assertEq(payroll.accruedFeeUsdt(), 1e18);
        assertEq(payroll.escrowUsdt(business), 200e18 - 101e18);
    }

    function test_fork_payout_redeem_realOndoRail() public {
        if (!_forked()) return;
        (ConfioPayrollVault.Payout memory p, bytes memory sig) = _signedPayout(true);
        vm.prank(sponsor);
        uint256 usdtOut = payroll.payout(p, sig);
        assertGe(usdtOut, 98e18, "live IM honored minOut");
        assertEq(IERC20(USDT).balanceOf(employee), usdtOut, "USDT landed at employee");
        assertEq(vault.balanceOf(employee), 0, "no shares on redeem branch");
    }
}
