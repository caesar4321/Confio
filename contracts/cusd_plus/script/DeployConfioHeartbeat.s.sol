// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {ConfioHeartbeat} from "../ConfioHeartbeat.sol";

/// Deploys ConfioHeartbeat behind a UUPS proxy, initialized IN THE SAME
/// transaction as the proxy (a separate initialize could be front-run with an
/// attacker's owner/beater). Dry-run with a BSC fork first (no --broadcast);
/// deploy with --broadcast and the deployer chosen on the CLI (--account /
/// --ledger / --sender). After deploying:
///   - bundle the PROXY address (never the implementation) in
///     apps/src/services/emergencyExit/heartbeat.ts BUNDLED_HEARTBEAT.address,
///   - set CONFIO_HEARTBEAT_ADDRESS in the server env,
///   - record both addresses in DEPLOYMENT.md.
contract DeployConfioHeartbeat is Script {
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    uint64 constant SILENCE = 14 days;

    function run() external returns (ConfioHeartbeat heartbeat) {
        require(block.chainid == 56, "BSC mainnet required");
        require(SAFE.code.length > 0, "Owner Safe must exist");
        address beater = vm.envAddress("CONFIO_HEARTBEAT_BEATER");
        require(beater != address(0), "beater required");

        vm.startBroadcast();
        ConfioHeartbeat impl = new ConfioHeartbeat();
        heartbeat = ConfioHeartbeat(
            address(
                new ERC1967Proxy(
                    address(impl), abi.encodeCall(ConfioHeartbeat.initialize, (SAFE, beater, SILENCE))
                )
            )
        );
        vm.stopBroadcast();

        require(heartbeat.owner() == SAFE, "owner");
        require(heartbeat.beater() == beater, "beater");
        require(heartbeat.silenceRequired() == SILENCE, "silence");
        require(!heartbeat.isSilent(), "must start alive");
        console2.log("Heartbeat proxy (bundle THIS):", address(heartbeat));
        console2.log("Implementation:", address(impl));
    }
}
