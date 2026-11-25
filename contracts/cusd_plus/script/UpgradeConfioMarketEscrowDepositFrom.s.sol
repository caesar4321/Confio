// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {ConfioMarketEscrow} from "../ConfioMarketEscrow.sol";

/// Deploys the depositFrom implementation of ConfioMarketEscrow and prints
/// the ONE Safe transaction that switches the live proxy to it and wires the
/// Cuenta inteligente factory atomically:
///
///   escrow.upgradeToAndCall(newImpl, setAccountFactory(FACTORY))
///
/// upgradeToAndCall delegatecalls setAccountFactory with msg.sender = the
/// Safe, so onlyOwner holds and depositFrom is never live with a zero
/// factory or a factory set by anyone else. Not run yet (2026-11-25).
///
/// Env (all optional, mainnet defaults):
///   MARKET_ESCROW_PROXY          default the live proxy
///   SMART_ACCOUNT_FACTORY        default the live factory proxy
///   MARKET_ESCROW_NEW_IMPL       skip the deploy, only print calldata
contract UpgradeConfioMarketEscrowDepositFrom is Script {
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    address constant ESCROW_PROXY = 0x2DFDC1fB809322c12f54beFE8CC98E0d103a99Fd;
    address constant FACTORY_PROXY = 0x339094A17605B842e0b2fc01441204E67020f953;

    function run() external returns (address impl, bytes memory safeCalldata) {
        address proxy = vm.envOr("MARKET_ESCROW_PROXY", ESCROW_PROXY);
        address factory = vm.envOr("SMART_ACCOUNT_FACTORY", FACTORY_PROXY);
        impl = vm.envOr("MARKET_ESCROW_NEW_IMPL", address(0));
        require(factory.code.length > 0 || block.chainid != 56, "factory has no code");

        if (impl == address(0)) {
            vm.startBroadcast();
            impl = address(new ConfioMarketEscrow());
            vm.stopBroadcast();
        }
        require(impl.code.length > 0, "impl has no code");

        safeCalldata = abi.encodeWithSignature(
            "upgradeToAndCall(address,bytes)",
            impl,
            abi.encodeCall(ConfioMarketEscrow.setAccountFactory, (factory))
        );

        console2.log("NEW_IMPL        :", impl);
        console2.log("ESCROW_PROXY    :", proxy);
        console2.log("ACCOUNT_FACTORY :", factory);
        console2.log("SAFE (owner)    :", SAFE);
        console2.log("Safe tx: to = ESCROW_PROXY, value = 0, operation = CALL, data =");
        console2.logBytes(safeCalldata);
        console2.log("After execution verify: ERC-1967 impl slot == NEW_IMPL, accountFactory() == FACTORY,");
        console2.log("owner/orderSigner/arbiter/windows/tokenLimits/openPrincipal unchanged.");
    }
}
