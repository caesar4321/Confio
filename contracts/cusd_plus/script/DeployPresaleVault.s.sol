// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * BSC deployment — ConfioPresaleVault (non-upgradeable, single contract).
 *
 * Curve "A" (locked decision): piecewise linear over 74M CONFIO,
 *   0 →  4M : $0.20 → $0.30  (avg 0.25 → $1M)
 *   4M → 24M : $0.30 → $0.70 (avg 0.50 → $10M)
 *  24M → 74M : $0.70 → $1.30 (avg 1.00 → $50M)
 * Full sale = $61M. Floored at 0.20 because Phase 1-1 buyers on Algorand
 * already paid 0.20 — nobody after them ever pays less.
 *
 * The four snapshot values preserve the predecessor's complete curve and
 * liability state: already-claimed allocations, unassigned Algorand credits,
 * and outstanding BSC allocations. The latter are imported with
 * creditLegacy(); the former Algorand pool continues through
 * creditMigrated() as address links materialize.
 *
 * PAYMENT_TOKEN is the universal cUSD proxy. Eligible users unwrap cUSD+
 * into cUSD through the fee-free internal boundary in the same sponsored
 * batch; no Presale purchase exits to raw USDT.
 *
 * Owner = the 3-of-5 Safe; sponsor = the KMS hot wallet that broadcasts
 * 7702 batches. The CONFIO BEP-20 is wired later via setConfioToken().
 *
 * Dry-run (fork, no broadcast):
 *   forge script script/DeployPresaleVault.s.sol --fork-url <bsc-rpc>
 * Broadcast: creation tx is built + KMS-signed server-side (sponsor key is
 * non-extractable in AWS KMS), same flow as DeployMainnet.s.sol.
 */
import {Script, console2} from "forge-std/Script.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ConfioPresaleVault} from "../ConfioPresaleVault.sol";

contract DeployPresaleVault is Script {
    // 3-of-5 Safe (owner)
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    // KMS sponsor hot wallet (BSC_SPONSOR_ADDRESS in settings)
    address constant SPONSOR = 0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D;

    function run() external {
        address payment = vm.envAddress("CUSD_VAULT_ADDRESS");
        // Snapshot the predecessor immediately after pausing new buys.
        // These four values MUST reconcile exactly in the constructor.
        uint256 initialSold = vm.envUint("PRESALE_INITIAL_SOLD_WEI");
        uint256 initialClaimed = vm.envUint("PRESALE_INITIAL_CLAIMED_WEI");
        uint256 initialMigratedPool = vm.envUint("PRESALE_INITIAL_MIGRATED_POOL_WEI");
        uint256 initialLegacyPool = vm.envUint("PRESALE_INITIAL_LEGACY_POOL_WEI");
        uint256[] memory soldBreakpoints = new uint256[](3);
        soldBreakpoints[0] = 4_000_000e18;
        soldBreakpoints[1] = 24_000_000e18;
        soldBreakpoints[2] = 74_000_000e18;

        uint256[] memory prices = new uint256[](4);
        prices[0] = 0.2e18;
        prices[1] = 0.3e18;
        prices[2] = 0.7e18;
        prices[3] = 1.3e18;

        uint256 pk = vm.envUint("DEPLOYER_KEY");
        vm.startBroadcast(pk);

        ConfioPresaleVault vault = new ConfioPresaleVault(
            SAFE,
            IERC20(payment),
            soldBreakpoints,
            prices,
            initialSold,
            initialClaimed,
            initialMigratedPool,
            initialLegacyPool,
            SPONSOR
        );

        vm.stopBroadcast();

        console2.log("PRESALE VAULT :", address(vault));
        console2.log("OWNER (SAFE)  :", SAFE);
        console2.log("SPONSOR       :", SPONSOR);
        console2.log("PAYMENT (cUSD):", payment);
        console2.log("INITIAL SOLD  :", initialSold);
        console2.log("INITIAL CLAIMED:", initialClaimed);
        console2.log("MIGRATED POOL :", initialMigratedPool);
        console2.log("LEGACY POOL   :", initialLegacyPool);
        // Post-deploy: BscScan verify; creditLegacy() for every outstanding
        // predecessor BSC allocation; creditMigrated() as Algorand->BSC links
        // appear; wire CONFIO via setConfioToken(), then unlock claims.
    }
}
