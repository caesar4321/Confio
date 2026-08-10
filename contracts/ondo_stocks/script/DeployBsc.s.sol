// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {ConfioStockRouter} from "../ConfioStockRouter.sol";

/// BSC mainnet deployment for the standalone Ondo Stocks router.
/// Deployment does not activate trading: Ondo must register the router in
/// its ID Registry and the Confío Safe must register it as a cUSD+ sponsor.
contract DeployBsc is Script {
    address constant CUSD_PLUS = 0x3C29417eb4314155e63d4C7D4507852b87763Ed1;
    address constant USDT = 0x55d398326f99059fF775485246999027B3197955;
    address constant USDON = 0x1f8955E640Cbd9abc3C3Bb408c9E2E1f5F20DfE6;
    address constant GM_TOKEN_MANAGER = 0x91f8Aff3738825e8eB16FC6f6b1A7A4647bDB299;
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;

    function run() external returns (ConfioStockRouter router) {
        require(block.chainid == 56, "BSC mainnet only");
        uint256 pk = vm.envUint("DEPLOYER_KEY");

        vm.startBroadcast(pk);
        ConfioStockRouter impl = new ConfioStockRouter(CUSD_PLUS, USDT, USDON, GM_TOKEN_MANAGER);
        router = ConfioStockRouter(
            address(new ERC1967Proxy(address(impl), abi.encodeCall(ConfioStockRouter.initialize, (SAFE))))
        );
        vm.stopBroadcast();

        console2.log("IMPL  :", address(impl));
        console2.log("ROUTER:", address(router), "(ERC1967 proxy)");
        console2.log("OWNER :", SAFE);
        console2.log("FEE   :", router.stockFeeBps(), "bps (fixed)");
    }
}
