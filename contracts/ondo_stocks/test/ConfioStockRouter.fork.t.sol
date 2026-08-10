// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * BSC MAINNET-FORK wiring test. Run:
 *
 *   forge test --match-path test/ConfioStockRouter.fork.t.sol \
 *     --fork-url https://bsc-dataseed.binance.org -vv
 *
 * This does not execute a stock trade because the new router address is not
 * registered in Ondo's ID Registry and has no live signed attestation. It does
 * prove the immutable production wiring and BSC transient-storage support.
 */
import {Test} from "forge-std/Test.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {ConfioStockRouter} from "../ConfioStockRouter.sol";

contract ConfioStockRouterForkTest is Test {
    address constant CUSD_PLUS = 0x3C29417eb4314155e63d4C7D4507852b87763Ed1;
    address constant USDT = 0x55d398326f99059fF775485246999027B3197955;
    address constant USDON = 0x1f8955E640Cbd9abc3C3Bb408c9E2E1f5F20DfE6;
    address constant GM = 0x91f8Aff3738825e8eB16FC6f6b1A7A4647bDB299;

    ConfioStockRouter router;

    function setUp() public {
        if (GM.code.length == 0) return;
        ConfioStockRouter impl = new ConfioStockRouter(CUSD_PLUS, USDT, USDON, GM);
        router = ConfioStockRouter(
            address(new ERC1967Proxy(address(impl), abi.encodeCall(ConfioStockRouter.initialize, (address(this)))))
        );
    }

    function _forked() private view returns (bool) {
        return address(router) != address(0);
    }

    function test_fork_productionWiring() public view {
        if (!_forked()) return;
        assertEq(block.chainid, 56);
        assertEq(address(router.CUSD_PLUS()), CUSD_PLUS);
        assertEq(address(router.USDT()), USDT);
        assertEq(address(router.USDON()), USDON);
        assertEq(address(router.GM()), GM);
        assertEq(router.stockFeeBps(), 30);
    }

    function test_fork_bscSupportsTransientReentrancyGuard() public {
        if (!_forked()) return;
        router.withdrawFees(address(this), 0);
        assertEq(router.accruedUsdtFees(), 0);
    }
}
