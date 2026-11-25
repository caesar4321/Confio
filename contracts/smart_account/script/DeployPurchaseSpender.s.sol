// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/**
 * Deploys ConfioPurchaseSpender on BSC mainnet (Cuenta inteligente spec
 * decisions 38 to 42, open point P2): the card spender of the owners'
 * "Compras con Confío IA" Card rules.
 *
 * The contract is immutable and has no owner. Its two facts are fixed here:
 *
 *   operator  the only address that may call pullTo: Confío's BSC KMS
 *             sponsor (the relayer key of smart_account.relayer), passed as
 *             PURCHASE_SPENDER_OPERATOR, with no default, and checked
 *             against EXPECTED_PURCHASE_SPENDER_OPERATOR so a typo cannot
 *             become a contract nobody can use (or the wrong key's);
 *   usdt      BSC USDT, what cardPull pays out.
 *
 * Nothing moves until the Safe allowlists the deployed address in the
 * factory (factory.setCardSpender(spender, true)) and the server is given it
 * as SMART_ACCOUNT_PURCHASE_SPENDER_ADDRESS. A compromised operator is cut
 * at once by the Safe (setCardSpender(spender, false) or setCardPaused); a
 * new operator is a new deployment.
 *
 * NEVER broadcast from a laptop. Like every Confío deployment this runs on
 * the production host through the documented deploy path, which takes the
 * shared sponsor nonce lock (README.md, "Deploy"). A dry run:
 *
 *   forge script script/DeployPurchaseSpender.s.sol \
 *     --rpc-url https://bsc-dataseed.bnbchain.org --sender <deployer>
 *
 * Nothing here needs a private key in the environment: with --broadcast the
 * signer is whatever the caller passes to forge (--ledger, --account ...).
 */
import {Script, console2} from "forge-std/Script.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ConfioPurchaseSpender} from "../ConfioPurchaseSpender.sol";

contract DeployPurchaseSpender is Script {
    // BSC mainnet (contracts/cusd_plus/DEPLOYMENT.md).
    address constant USDT = 0x55d398326f99059fF775485246999027B3197955;

    function run() external {
        require(block.chainid == 56, "BSC mainnet only");
        address operator = vm.envAddress("PURCHASE_SPENDER_OPERATOR");
        require(operator == vm.envAddress("EXPECTED_PURCHASE_SPENDER_OPERATOR"), "operator != expected");
        // The operator signs its own transactions: an EOA, never a contract.
        require(operator != address(0) && operator.code.length == 0, "operator must be an EOA");
        require(USDT.code.length > 0, "USDT not a contract");

        vm.startBroadcast();
        ConfioPurchaseSpender spender = new ConfioPurchaseSpender(operator, IERC20(USDT));
        vm.stopBroadcast();

        require(spender.operator() == operator, "operator");
        require(address(spender.usdt()) == USDT, "usdt");

        console2.log("ConfioPurchaseSpender:", address(spender));
        console2.log("Operator:", operator);
        console2.log("Safe step next: factory.setCardSpender(spender, true)");
        console2.log("Server: SMART_ACCOUNT_PURCHASE_SPENDER_ADDRESS = the spender; ops label its");
        console2.log("  SmartAccountCardSpender row 'Compras con Confio IA' once reconcile mirrors it");
    }
}
