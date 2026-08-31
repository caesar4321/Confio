// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * Local/dev private-key deployment helper. Production uses the KMS-backed
 * `manage.py deploy_cusd_fee_system` command because the deployer key is
 * non-extractable.
 *
 * This package-local helper deploys cUSD and cUSD+ only. Production's
 * KMS-backed command also deploys the Stock Router implementation. It
 * deliberately does NOT mutate live proxies. The 3-of-5 Safe performs:
 *   1. cUSD.setSponsor(KMS, true)
 *   2. cUSD.setSavingsVault(CUSD_PLUS_PROXY)
 *   3. cUSD+.upgradeToAndCall(newImpl, initializeCusd(cUSD proxy))
 * then the Stock Router upgrade/authorization calls printed by the production
 * command.
 */
import {Script, console2} from "forge-std/Script.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {CusdVault} from "../CusdVault.sol";
import {CusdPlusVault} from "../CusdPlusVault.sol";

contract DeployCusdFeeSystem is Script {
    address constant USDY = 0x608593d17A2decBbc4399e4185bE4922F97eD32E;
    address constant USDT = 0x55d398326f99059fF775485246999027B3197955;
    address constant IM = 0x9bA360087075A4Cef548eeD71Eed197bf4cFA4E2;
    address constant ORACLE = 0x8aaa843b848c2E3c83956Bc09aFBE4D9Dcf297b7;
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    address constant CUSD_PLUS_PROXY = 0x3C29417eb4314155e63d4C7D4507852b87763Ed1;
    uint256 constant CONFIO_YIELD_SHARE_BPS = 1500;
    uint256 constant CONVERSION_FEE_BPS = 90;

    function run() external {
        uint256 pk = vm.envUint("DEPLOYER_KEY");
        vm.startBroadcast(pk);

        CusdVault cusdImpl = new CusdVault(USDT);
        CusdVault cusd = CusdVault(
            address(
                new ERC1967Proxy(address(cusdImpl), abi.encodeCall(CusdVault.initialize, (SAFE, CONVERSION_FEE_BPS)))
            )
        );
        CusdPlusVault plusImpl = new CusdPlusVault(USDY, USDT, IM, ORACLE, CONFIO_YIELD_SHARE_BPS);

        vm.stopBroadcast();

        console2.log("CUSD_IMPL       :", address(cusdImpl));
        console2.log("CUSD_PROXY      :", address(cusd));
        console2.log("CUSD_PLUS_IMPL  :", address(plusImpl));
        console2.log("CUSD_PLUS_PROXY :", CUSD_PLUS_PROXY);
        console2.log("OWNER_SAFE      :", SAFE);
        console2.log("SAFE call 1: cUSD.setSponsor(KMS, true)");
        console2.log("SAFE call 2: cUSD.setSavingsVault(cUSD+ proxy)");
        console2.log("SAFE call 3: cUSD+.upgradeToAndCall(plusImpl, initializeCusd(cUSD proxy))");
    }
}
