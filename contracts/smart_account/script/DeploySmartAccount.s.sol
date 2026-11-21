// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * Deploys the Cuenta inteligente package on BSC mainnet:
 *
 *   1. ConfioSmartAccountFeeCollector (immutable; treasury = the Safe)
 *   2. ConfioSmartAccount implementation, built against the factory proxy's
 *      PREDICTED address (the account's FACTORY is an immutable)
 *   3. ConfioSmartAccountFactory logic
 *   4. ERC1967Proxy(factory logic, initialize(Safe, implementation, prices))
 *
 * The factory's initialize refuses an implementation whose FACTORY is not
 * the proxy, so a wrong prediction fails the deployment instead of
 * producing a mismatched pair.
 *
 * NEVER broadcast from a laptop. Like every Confío deployment this runs on
 * the production host through the documented deploy path, which takes the
 * shared sponsor nonce lock (see README.md, "Deploy"). A dry run:
 *
 *   forge script script/DeploySmartAccount.s.sol \
 *     --rpc-url https://bsc-dataseed.bnbchain.org --sender <deployer>
 *
 * Nothing here needs a private key in the environment: with --broadcast the
 * signer is whatever the caller passes to forge (--ledger, --account ...).
 *
 * The two Chainlink feed addresses were measured on-chain on 2026-11-20
 * (spec 9.2, C2) and MUST be matched against Chainlink's published BSC list
 * before this is broadcast: they become constants of every account.
 *
 * The CONFIO token address is also a constant of every account, and accounts
 * are immutable. The run refuses to start unless EXPECTED_CONFIO_TOKEN (no
 * default) names the token it is about to bake in, so a re-issue after the
 * last review cannot slip through. Deploy only once the token is final.
 */
import {Script, console2} from "forge-std/Script.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {ConfioSmartAccount} from "../ConfioSmartAccount.sol";
import {ConfioSmartAccountFactory} from "../ConfioSmartAccountFactory.sol";
import {ConfioSmartAccountFeeCollector} from "../ConfioSmartAccountFeeCollector.sol";

interface IDeployChecks {
    function description() external view returns (string memory);
    function VAULT() external view returns (address);
    function CUSD() external view returns (address);
    function owner() external view returns (address);
}

contract DeploySmartAccount is Script {
    // BSC mainnet (contracts/cusd_plus/DEPLOYMENT.md).
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    address constant CUSD = 0x6101cC370635cF2c7f2725EaB010aC407A8d543F;
    address constant CUSD_PLUS = 0x3C29417eb4314155e63d4C7D4507852b87763Ed1;
    address constant USDT = 0x55d398326f99059fF775485246999027B3197955;
    address constant CONFIO = 0xF5765933764562A51e179F6AF2b19b7a3d506101;
    address constant STOCK_ROUTER = 0x40c8e134BCAf44EEf9e7D184846F36c9862329c3;
    address constant BTCB = 0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c;
    address constant XAUT = 0x21cAef8A43163Eea865baeE23b9C2E327696A3bf;
    // To be matched against Chainlink's published list (open point C2).
    address constant BTC_USD_FEED = 0x264990fbd0A4796A3E3d8E37C4d5F87a3aCa5Ebf;
    address constant XAU_USD_FEED = 0x86896fEB19D8A607c3b11f2aF50A0f239Bd71CD0;

    uint256 constant MONTHLY_FEE_USD = 14.99e18;
    uint256 constant ANNUAL_FEE_USD = 149.99e18;

    function run() external {
        require(block.chainid == 56, "BSC mainnet only");
        // The swap router is not in DEPLOYMENT.md; it is the
        // CRYPTO_SWAP_ROUTER_ADDRESS setting. Passed in, then checked.
        address swapRouter = vm.envAddress("CRYPTO_SWAP_ROUTER_ADDRESS");
        // Confío's token was re-issued once (v2); allow an override rather
        // than baking a token that may be re-issued again before launch.
        address confio = vm.envOr("CONFIO_TOKEN_ADDRESS", CONFIO);
        // Required, no default: the operator states the final token.
        require(confio == vm.envAddress("EXPECTED_CONFIO_TOKEN"), "CONFIO token != EXPECTED_CONFIO_TOKEN");
        require(confio.code.length > 0, "CONFIO token not a contract");

        require(IDeployChecks(swapRouter).VAULT() == CUSD_PLUS, "swap router: wrong vault");
        require(IDeployChecks(swapRouter).owner() == SAFE, "swap router: not Safe-owned");
        require(IDeployChecks(STOCK_ROUTER).VAULT() == CUSD_PLUS, "stock router: wrong vault");
        require(IDeployChecks(CUSD_PLUS).CUSD() == CUSD, "cUSD+ / cUSD mismatch");
        require(_same(IDeployChecks(BTC_USD_FEED).description(), "BTC / USD"), "BTC feed");
        require(_same(IDeployChecks(XAU_USD_FEED).description(), "XAU / USD"), "XAU feed");

        vm.startBroadcast();
        (, address deployer,) = vm.readCallers();
        ConfioSmartAccountFeeCollector collector =
            new ConfioSmartAccountFeeCollector(IERC20(CUSD), IERC20(CUSD_PLUS), SAFE);
        // Next three creations: implementation, factory logic, proxy.
        address predictedFactory = vm.computeCreateAddress(deployer, vm.getNonce(deployer) + 2);
        ConfioSmartAccount implementation = new ConfioSmartAccount(
            predictedFactory,
            CUSD,
            CUSD_PLUS,
            USDT,
            confio,
            STOCK_ROUTER,
            swapRouter,
            address(collector),
            BTCB,
            BTC_USD_FEED,
            XAUT,
            XAU_USD_FEED
        );
        ConfioSmartAccountFactory logic = new ConfioSmartAccountFactory(CUSD_PLUS, STOCK_ROUTER);
        ERC1967Proxy proxy = new ERC1967Proxy(
            address(logic),
            abi.encodeCall(
                ConfioSmartAccountFactory.initialize, (SAFE, address(implementation), MONTHLY_FEE_USD, ANNUAL_FEE_USD)
            )
        );
        vm.stopBroadcast();

        require(address(proxy) == predictedFactory, "factory address prediction");
        ConfioSmartAccountFactory factory = ConfioSmartAccountFactory(address(proxy));
        require(factory.owner() == SAFE, "factory not Safe-owned");
        require(implementation.FACTORY() == address(factory), "implementation factory");
        require(!factory.inheritanceEnabled(), "inheritance must start off");
        require(factory.CUSD_PLUS() == CUSD_PLUS && factory.STOCK_ROUTER() == STOCK_ROUTER, "factory immutables");

        console2.log("ConfioSmartAccountFeeCollector:", address(collector));
        console2.log("ConfioSmartAccount (implementation):", address(implementation));
        console2.log("ConfioSmartAccountFactory (logic):", address(logic));
        console2.log("ConfioSmartAccountFactory (proxy):", address(factory));
        console2.log("Safe steps next (README.md): cUSD upgrade, then");
        console2.log("  cUSD.setSmartAccountFactory(factory, true)");
    }

    function _same(string memory a, string memory b) private pure returns (bool) {
        return keccak256(bytes(a)) == keccak256(bytes(b));
    }
}
