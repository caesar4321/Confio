// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * Coordinated cUSD release rehearsal against the existing BSC Stock Router
 * proxy. Run with:
 *
 *   forge test --match-path test/UpgradeRehearsal.fork.t.sol \
 *     --fork-url https://bsc-dataseed.bnbchain.org -vv
 *
 * No Ondo trade is attempted because that requires a fresh signed
 * attestation. The test proves the exact Safe upgrade preserves proxy state,
 * keeps cUSD+ settlement sponsor-gated, and installs the contract-only
 * permissionless raw-USDT redemption selector.
 */
import {Test} from "forge-std/Test.sol";
import {ConfioStockRouter, GmQuote} from "../ConfioStockRouter.sol";

contract StockRouterUpgradeRehearsalForkTest is Test {
    address constant PROXY = 0x40c8e134BCAf44EEf9e7D184846F36c9862329c3;
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    address constant CUSD_PLUS = 0x3C29417eb4314155e63d4C7D4507852b87763Ed1;
    address constant USDT = 0x55d398326f99059fF775485246999027B3197955;
    address constant USDON = 0x1f8955E640Cbd9abc3C3Bb408c9E2E1f5F20DfE6;
    address constant GM = 0x91f8Aff3738825e8eB16FC6f6b1A7A4647bDB299;

    function _forked() private view returns (bool) {
        return PROXY.code.length > 0;
    }

    function test_fork_upgradeExistingProxy_preservesStateAndInstallsExitBoundary() public {
        if (!_forked()) return;
        ConfioStockRouter router = ConfioStockRouter(PROXY);
        assertEq(router.owner(), SAFE, "unexpected pre-upgrade owner");

        uint256 feesBefore = router.accruedUsdtFees();
        bool pausedBefore = router.paused();

        ConfioStockRouter implementation = new ConfioStockRouter(CUSD_PLUS, USDT, USDON, GM);
        vm.prank(SAFE);
        router.upgradeToAndCall(address(implementation), "");

        assertEq(router.owner(), SAFE, "owner changed");
        assertEq(router.accruedUsdtFees(), feesBefore, "fee accounting changed");
        assertEq(router.paused(), pausedBefore, "pause state changed");
        assertEq(address(router.CUSD_PLUS()), CUSD_PLUS, "cUSD+ wiring changed");
        assertEq(address(router.USDT()), USDT, "USDT wiring changed");
        assertEq(address(router.USDON()), USDON, "USDon wiring changed");
        assertEq(address(router.GM()), GM, "GM wiring changed");
        assertEq(router.stockFeeBps(), 30, "fee changed");

        GmQuote memory emptyQuote;
        address outsider = makeAddr("advancedDirectCaller");

        // cUSD+ settlement rejects the unsponsored origin before inspecting
        // quote fields. This remains a Confío app-only route.
        vm.prank(outsider, outsider);
        vm.expectRevert("not sponsored");
        router.sellToSavings(emptyQuote, "", 0, 0, 30);

        // Raw redemption has no sponsor gate. Reaching its first input check
        // proves the selector is installed and callable by an arbitrary EOA.
        vm.prank(outsider, outsider);
        vm.expectRevert("zero in");
        router.sellToUsdt(emptyQuote, "", 0, 0, 30);
    }
}
