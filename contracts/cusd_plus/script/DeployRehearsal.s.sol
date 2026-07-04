// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * BSC TESTNET REHEARSAL deployment (chainId 97) — vault + router with the
 * same mocks the unit tests use, so the app's own signer (evmWallet.ts) can
 * run real mint/trade/redeem transactions against a live network before any
 * Ondo dependency exists. NOT a production script: the rehearsal deployer
 * is treasury/owner/feeTreasury all at once, and fee bps are exercised at
 * a placeholder 30 (test-only; pricing remains an open decision).
 *
 *   DEPLOYER_KEY=0x... forge script script/DeployRehearsal.s.sol \
 *     --rpc-url https://data-seed-prebsc-1-s1.bnbchain.org:8545 --broadcast
 */

import {Script, console2} from "forge-std/Script.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {CusdPlusVault} from "../CusdPlusVault.sol";
import {ConfioStockRouter} from "../ConfioStockRouter.sol";
import {MockToken, MockOracle, MockInstantManager} from "../test/CusdPlusVault.t.sol";
import {MockGmSettlement} from "../test/ConfioStockRouter.t.sol";

contract DeployRehearsal is Script {
    function run() external {
        uint256 pk = vm.envUint("DEPLOYER_KEY");
        address deployer = vm.addr(pk);
        vm.startBroadcast(pk);

        MockToken usdt = new MockToken("USDT");
        MockToken usdy = new MockToken("USDY");
        MockToken tsla = new MockToken("TSLAon");
        MockOracle oracle = new MockOracle();
        MockInstantManager im = new MockInstantManager(usdt, usdy, oracle);
        usdt.mint(address(im), 1_000_000e18);
        usdy.mint(address(im), 1_000_000e18);

        CusdPlusVault impl = new CusdPlusVault(
            address(usdy), address(usdt), address(im), address(oracle), 1500
        );
        CusdPlusVault vault = CusdPlusVault(address(new ERC1967Proxy(
            address(impl), abi.encodeCall(CusdPlusVault.initialize, (deployer))
        )));

        MockGmSettlement gm = new MockGmSettlement(usdt);
        usdt.mint(address(gm), 1_000_000e18);

        ConfioStockRouter router = new ConfioStockRouter(
            address(vault), address(usdt), address(gm), deployer, deployer
        );
        router.setStockFeeBps(30); // rehearsal-only placeholder

        vm.stopBroadcast();

        console2.log("USDT   :", address(usdt));
        console2.log("USDY   :", address(usdy));
        console2.log("TSLAon :", address(tsla));
        console2.log("ORACLE :", address(oracle));
        console2.log("IM     :", address(im));
        console2.log("VAULT  :", address(vault));
        console2.log("GM     :", address(gm));
        console2.log("ROUTER :", address(router));
    }
}
