// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * Hands-off upgrade (2026-11-25), NOT RUN. Deploys:
 *
 *   1. ConfioSmartAccountV2 implementation, FACTORY = the EXISTING factory
 *      proxy (SMART_ACCOUNT_FACTORY_ADDRESS), ESCROW = the Comprar escrow
 *      proxy (CONFIO_MARKET_ESCROW_ADDRESS, already upgraded with
 *      depositFrom and setAccountFactory(factory)).
 *   2. ConfioSmartAccountFactory logic (the upgraded factory).
 *
 * and prints the ONE Safe transaction that switches the factory:
 *
 *   factory.upgradeToAndCall(logic, initializeV2(implementationV2))
 *
 * initializeV2 lists the v1 implementation (implementationAt(0)) and makes
 * v2 the implementation for createAccount and migrate. Existing accounts are
 * untouched; tradePaused starts false (the Safe may set it in the same
 * batch: setTradePaused(true) until the server is live).
 *
 * The constructor arguments other than the escrow MUST equal the v1
 * implementation's (same vaults, routers, collector, feeds, CONFIO): they
 * are passed in from the v1 deployment record and the script refuses to run
 * unless the v1 implementation's address is stated (V1_IMPLEMENTATION) and
 * equals factory.implementation().
 *
 * NEVER broadcast from a laptop (README.md, "Deploy"). Dry run:
 *   forge script script/DeploySmartAccountV2.s.sol --rpc-url https://bsc-dataseed.bnbchain.org --sender <deployer>
 */
import {Script, console2} from "forge-std/Script.sol";
import {ConfioSmartAccountV2} from "../ConfioSmartAccountV2.sol";
import {ConfioSmartAccountFactory} from "../ConfioSmartAccountFactory.sol";

contract DeploySmartAccountV2 is Script {
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    address constant CUSD = 0x6101cC370635cF2c7f2725EaB010aC407A8d543F;
    address constant CUSD_PLUS = 0x3C29417eb4314155e63d4C7D4507852b87763Ed1;
    address constant USDT = 0x55d398326f99059fF775485246999027B3197955;
    address constant STOCK_ROUTER = 0x40c8e134BCAf44EEf9e7D184846F36c9862329c3;
    address constant BTCB = 0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c;
    address constant XAUT = 0x21cAef8A43163Eea865baeE23b9C2E327696A3bf;
    address constant BTC_USD_FEED = 0x264990fbd0A4796A3E3d8E37C4d5F87a3aCa5Ebf;
    address constant XAU_USD_FEED = 0x86896fEB19D8A607c3b11f2aF50A0f239Bd71CD0;

    function run() external {
        require(block.chainid == 56, "BSC mainnet only");
        ConfioSmartAccountFactory factory = ConfioSmartAccountFactory(vm.envAddress("SMART_ACCOUNT_FACTORY_ADDRESS"));
        address escrow = vm.envAddress("CONFIO_MARKET_ESCROW_ADDRESS");
        address swapRouter = vm.envAddress("CRYPTO_SWAP_ROUTER_ADDRESS");
        address confio = vm.envAddress("CONFIO_TOKEN_ADDRESS");
        address collector = vm.envAddress("SMART_ACCOUNT_FEE_COLLECTOR_ADDRESS");
        address v1 = vm.envAddress("V1_IMPLEMENTATION");

        require(factory.owner() == SAFE, "factory not Safe-owned");
        require(factory.implementation() == v1, "V1_IMPLEMENTATION != factory.implementation()");
        require(factory.CUSD_PLUS() == CUSD_PLUS && factory.STOCK_ROUTER() == STOCK_ROUTER, "factory immutables");
        require(escrow.code.length > 0 && collector.code.length > 0, "escrow / collector");

        vm.startBroadcast();
        ConfioSmartAccountV2 implementationV2 = new ConfioSmartAccountV2(
            address(factory),
            CUSD,
            CUSD_PLUS,
            USDT,
            confio,
            STOCK_ROUTER,
            swapRouter,
            collector,
            BTCB,
            BTC_USD_FEED,
            XAUT,
            XAU_USD_FEED,
            escrow
        );
        // Same immutables as the live logic (an upgrade must pass them).
        ConfioSmartAccountFactory logic = new ConfioSmartAccountFactory(CUSD_PLUS, STOCK_ROUTER);
        vm.stopBroadcast();

        require(implementationV2.FACTORY() == address(factory), "implementation factory");
        require(implementationV2.ESCROW() == escrow && implementationV2.VERSION() == 2, "implementation config");
        require(address(implementationV2).code.length <= 24_576, "EIP-170");

        bytes memory safeCall = abi.encodeCall(
            factory.upgradeToAndCall,
            (address(logic), abi.encodeCall(ConfioSmartAccountFactory.initializeV2, (address(implementationV2))))
        );
        console2.log("ConfioSmartAccountV2 (implementation):", address(implementationV2));
        console2.log("ConfioSmartAccountFactory (new logic):", address(logic));
        console2.log("Safe tx: to = factory proxy", address(factory));
        console2.logBytes(safeCall);
        console2.log("Optional, same Safe batch: factory.setTradePaused(true)");
        console2.logBytes(abi.encodeCall(ConfioSmartAccountFactory.setTradePaused, (true)));
    }
}
