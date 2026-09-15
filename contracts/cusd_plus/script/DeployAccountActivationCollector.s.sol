// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {AccountActivationCollector} from "../AccountActivationCollector.sol";

/// Dry-run with a BSC fork before deployment. This script does not start broadcast.
contract DeployAccountActivationCollector is Script {
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;

    function run() external returns (AccountActivationCollector collector) {
        require(block.chainid == 56, "BSC mainnet required");
        require(SAFE.code.length > 0, "Treasury Safe must exist");
        collector = new AccountActivationCollector(IERC20(vm.envAddress("CUSD_VAULT_ADDRESS")), SAFE);
        console2.log("Collector:", address(collector));
        console2.log("Treasury:", collector.treasury());
    }
}
