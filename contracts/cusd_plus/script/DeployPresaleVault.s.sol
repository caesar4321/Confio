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
 * INITIAL_SOLD seeds the curve with what the Algorand presale already sold
 * (query the Algorand vault right before broadcast) and fills the
 * migratedPool the Safe later assigns to users' BSC addresses via
 * creditMigrated() as their Algorand→BSC links materialize.
 *
 * PAYMENT_TOKEN is a deploy-time decision (cUSD once it exists on BSC, or
 * USDT 18dp). Prices are payment base units per WHOLE CONFIO, so 18dp
 * tokens use 0.2e18 … 1.3e18 as below.
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
    // Payment token: set at deploy time (USDT shown; swap for cUSD on BSC)
    address constant PAYMENT = 0x55d398326f99059fF775485246999027B3197955;

    // CONFIO already sold on Algorand at broadcast time (1e18 units).
    // MUST be refreshed from the Algorand vault right before deploy.
    uint256 constant INITIAL_SOLD = 0;

    function run() external {
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
            SAFE, IERC20(PAYMENT), soldBreakpoints, prices, INITIAL_SOLD, SPONSOR
        );

        vm.stopBroadcast();

        console2.log("PRESALE VAULT :", address(vault));
        console2.log("OWNER (SAFE)  :", SAFE);
        console2.log("SPONSOR       :", SPONSOR);
        console2.log("INITIAL SOLD  :", INITIAL_SOLD);
        // Post-deploy: BscScan verify; creditMigrated() as Algorand->BSC
        // links appear; wire CONFIO via setConfioToken() after the token
        // migration, then setClaimsUnlocked(true) when claims open.
    }
}
