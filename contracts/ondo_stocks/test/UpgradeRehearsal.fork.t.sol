// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * Router v3 (2026-11: the 0.30% legacy fee path deleted) release rehearsal
 * against the live BSC Stock Router proxy. Run with:
 *
 *   forge test --match-path test/UpgradeRehearsal.fork.t.sol \
 *     --fork-url https://bsc-dataseed.bnbchain.org -vv
 *
 * Executes the exact Safe call, upgradeToAndCall(v3, initializeV3()), as
 * the Safe, then proves: proxy state and wiring are preserved, the legacy
 * fee accrual is zero (and was required to be), a pre-v2 cap of 30 now
 * reverts even from the sponsor, the 0.9% cap still reaches settlement
 * checks, and the permissionless raw-USDT exit is still open. No Ondo trade
 * is attempted because that requires a fresh signed attestation.
 */
import {Test} from "forge-std/Test.sol";
import {ConfioStockRouter, GmQuote} from "../ConfioStockRouter.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

contract StockRouterUpgradeRehearsalForkTest is Test {
    address constant PROXY = 0x40c8e134BCAf44EEf9e7D184846F36c9862329c3;
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    address constant SPONSOR = 0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D;
    address constant CUSD_PLUS = 0x3C29417eb4314155e63d4C7D4507852b87763Ed1;
    address constant USDT = 0x55d398326f99059fF775485246999027B3197955;
    address constant USDON = 0x1f8955E640Cbd9abc3C3Bb408c9E2E1f5F20DfE6;
    address constant GM = 0x91f8Aff3738825e8eB16FC6f6b1A7A4647bDB299;
    bytes32 constant IMPL_SLOT = 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc;

    function _forked() private view returns (bool) {
        return PROXY.code.length > 0;
    }

    function _sellQuote() private view returns (GmQuote memory q) {
        q.chainId = block.chainid;
        q.quantity = 1;
        q.price = 1;
        q.side = 1; // SELL
    }

    function test_fork_upgradeToV3_deletesLegacyPath_preservesState() public {
        if (!_forked()) return;
        ConfioStockRouter router = ConfioStockRouter(PROXY);
        assertEq(router.owner(), SAFE, "unexpected pre-upgrade owner");
        assertEq(router.accruedUsdtFees(), 0, "legacy fees not yet withdrawn");
        bool pausedBefore = router.paused();

        ConfioStockRouter implementation = new ConfioStockRouter(CUSD_PLUS, USDT, USDON, GM);
        vm.prank(SAFE);
        router.upgradeToAndCall(address(implementation), abi.encodeCall(ConfioStockRouter.initializeV3, ()));

        assertEq(address(uint160(uint256(vm.load(PROXY, IMPL_SLOT)))), address(implementation), "impl not installed");
        assertEq(router.VERSION(), 3, "not v3");
        assertEq(router.owner(), SAFE, "owner changed");
        assertEq(router.accruedUsdtFees(), 0, "fee slot changed");
        assertEq(router.paused(), pausedBefore, "pause state changed");
        assertEq(address(router.CUSD_PLUS()), CUSD_PLUS, "cUSD+ wiring changed");
        assertEq(address(router.USDT()), USDT, "USDT wiring changed");
        assertEq(address(router.USDON()), USDON, "USDon wiring changed");
        assertEq(address(router.GM()), GM, "GM wiring changed");
        assertEq(router.stockFeeBps(), 0, "router own fee not zero");
        assertEq(router.conversionFeeBps(), 90, "live cUSD fee is not 0.9%");
        (bool ok, bytes memory ret) = CUSD_PLUS.staticcall(abi.encodeWithSignature("isSponsor(address)", PROXY));
        assertTrue(ok && abi.decode(ret, (bool)), "router not a cUSD+ sponsor");

        // The upgrade hook cannot be replayed.
        vm.expectRevert();
        router.initializeV3();

        // v2's fee withdrawal is gone.
        vm.prank(SAFE);
        (bool hasWithdraw,) = PROXY.call(abi.encodeWithSignature("withdrawFees(address,uint256)", SAFE, 0));
        assertFalse(hasWithdraw, "withdrawFees still present");

        GmQuote memory q = _sellQuote();
        // Even from Confío's own sponsor, a pre-v2 cap of 30 is refused.
        vm.prank(SPONSOR, SPONSOR);
        vm.expectRevert("fee above trade cap");
        router.sellToSavings(q, "", 0, 0, 30);
        // The live cap passes the fee check and reaches settlement: the
        // revert is the stock pull (the quote's asset is address(0)), which
        // comes after the fee check.
        vm.prank(SPONSOR, SPONSOR);
        vm.expectRevert(abi.encodeWithSelector(SafeERC20.SafeERC20FailedOperation.selector, address(0)));
        router.sellToSavings(q, "", 0, 0, 90);

        // cUSD+ settlement still rejects an unsponsored origin first.
        address outsider = makeAddr("advancedDirectCaller");
        GmQuote memory emptyQuote;
        vm.prank(outsider, outsider);
        vm.expectRevert("not sponsored");
        router.sellToSavings(emptyQuote, "", 0, 0, 90);

        // The permissionless raw-USDT exit stays open to anyone.
        vm.prank(outsider, outsider);
        vm.expectRevert("zero in");
        router.sellToUsdt(emptyQuote, "", 0, 0, 0);
    }
}
