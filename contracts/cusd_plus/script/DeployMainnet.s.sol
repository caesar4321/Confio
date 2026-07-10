// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * BSC MAINNET deployment — CusdPlusVault ONLY (impl + ERC1967 proxy).
 *
 * Wired to the REAL Ondo contracts (verified on-chain + fork-rehearsed
 * 2026-07-10). Owner/treasury is the 3-of-5 Safe from block one via
 * initialize() — no transfer ceremony.
 *
 * The router is intentionally NOT deployed here: its GM settlement path
 * (mintWithAttestation) is not yet wired to the real attestation ABI, and
 * stock trading is gated on per-user PP onboarding regardless. Deploy the
 * router in a separate step once GM attestation lands.
 *
 * Dry-run (fork, no broadcast):
 *   forge script script/DeployMainnet.s.sol --fork-url <bsc-rpc>
 * Broadcast (only with explicit go; deployer = KMS sponsor, see deploy notes):
 *   the two creation txns are built + KMS-signed server-side, NOT via
 *   --private-key (the sponsor key is non-extractable in AWS KMS).
 */
import {Script, console2} from "forge-std/Script.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {CusdPlusVault} from "../CusdPlusVault.sol";

contract DeployMainnet is Script {
    // Real BSC mainnet addresses (Ondo, 2026-07-07 confirmation + on-chain)
    address constant USDY = 0x608593d17A2decBbc4399e4185bE4922F97eD32E;
    address constant USDT = 0x55d398326f99059fF775485246999027B3197955;
    address constant IM = 0x9bA360087075A4Cef548eeD71Eed197bf4cFA4E2;
    address constant ORACLE = 0x8aaa843b848c2E3c83956Bc09aFBE4D9Dcf297b7;
    // 3-of-5 Safe (owner + treasury)
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    uint256 constant CONFIO_YIELD_SHARE_BPS = 1500; // 15%

    function run() external {
        uint256 pk = vm.envUint("DEPLOYER_KEY");
        vm.startBroadcast(pk);

        CusdPlusVault impl = new CusdPlusVault(USDY, USDT, IM, ORACLE, CONFIO_YIELD_SHARE_BPS);
        CusdPlusVault vault = CusdPlusVault(address(new ERC1967Proxy(
            address(impl), abi.encodeCall(CusdPlusVault.initialize, (SAFE))
        )));

        vm.stopBroadcast();

        console2.log("IMPL  :", address(impl));
        console2.log("VAULT :", address(vault));
        console2.log("OWNER :", SAFE);
        // Post-deploy: BscScan verify, then send VAULT to Ondo for PP whitelisting.
    }
}
