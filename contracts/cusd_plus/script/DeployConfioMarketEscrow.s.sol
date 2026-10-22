// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {ConfioMarketEscrow} from "../ConfioMarketEscrow.sol";

/// Deploys ConfioMarketEscrow (Comprar) behind a UUPS proxy, initialized IN
/// THE SAME transaction as the proxy (a separate initialize could be
/// front-run with an attacker's owner/signer).
///
/// Mainnet (chain 56): the owner is always the Safe, and the deployer
/// cannot set token limits, so the escrow starts accepting NOTHING until a
/// Safe tx calls setTokenLimits(cUSD, …). The production deploy goes through
/// `manage.py deploy_confio_market_escrow` (KMS sponsor); this script is the
/// rehearsal / testnet path and the fork test drives it.
///
/// Elsewhere (fork, testnet): MARKET_ESCROW_OWNER is the owner, and if it is
/// the broadcaster and MARKET_ESCROW_TOKEN is set, the token limits are set
/// in the same run.
///
/// Env:
///   MARKET_ESCROW_ORDER_SIGNER  backend deposit authorizer (required)
///   MARKET_ESCROW_ARBITER       dispute resolver (required)
///   MARKET_ESCROW_OWNER         non-mainnet owner (required off chain 56)
///   MARKET_ESCROW_TOKEN         non-mainnet: token to enable (optional)
///   MARKET_ESCROW_MAX_ORDER     default 300e18
///   MARKET_ESCROW_MAX_OPEN      default 10_000e18
///
/// After a mainnet deploy: record proxy + implementation in DEPLOYMENT.md,
/// set CONFIO_MARKET_ESCROW_ADDRESS on the server, queue the Safe
/// setTokenLimits tx.
contract DeployConfioMarketEscrow is Script {
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    uint64 constant SHIP_WINDOW = 3 days;
    uint64 constant RELEASE_WINDOW = 4 days;
    uint64 constant DISPUTE_TIMEOUT = 30 days;

    function run() external returns (ConfioMarketEscrow escrow, address impl) {
        address signer = vm.envAddress("MARKET_ESCROW_ORDER_SIGNER");
        address arbiter = vm.envAddress("MARKET_ESCROW_ARBITER");
        address owner_;
        if (block.chainid == 56) {
            require(SAFE.code.length > 0, "Owner Safe must exist");
            owner_ = SAFE;
        } else {
            owner_ = vm.envAddress("MARKET_ESCROW_OWNER");
        }
        require(owner_ != address(0) && signer != address(0) && arbiter != address(0), "zero role");

        address token = block.chainid == 56 ? address(0) : vm.envOr("MARKET_ESCROW_TOKEN", address(0));
        uint256 maxOrderRaw = vm.envOr("MARKET_ESCROW_MAX_ORDER", uint256(300e18));
        uint256 maxOpenRaw = vm.envOr("MARKET_ESCROW_MAX_OPEN", uint256(10_000e18));
        // A silent uint128 wrap could turn a cap into 0 (token disabled).
        require(maxOrderRaw <= type(uint128).max && maxOpenRaw <= type(uint128).max, "limit overflows uint128");
        uint128 maxOrder = uint128(maxOrderRaw);
        uint128 maxOpen = uint128(maxOpenRaw);

        vm.startBroadcast();
        impl = address(new ConfioMarketEscrow());
        escrow = ConfioMarketEscrow(
            address(
                new ERC1967Proxy(
                    impl,
                    abi.encodeCall(
                        ConfioMarketEscrow.initialize,
                        (owner_, signer, arbiter, SHIP_WINDOW, RELEASE_WINDOW, DISPUTE_TIMEOUT)
                    )
                )
            )
        );
        if (token != address(0) && escrow.owner() == msg.sender) {
            escrow.setTokenLimits(token, maxOrder, maxOpen);
        }
        vm.stopBroadcast();

        require(escrow.owner() == owner_, "owner");
        require(escrow.orderSigner() == signer, "signer");
        require(escrow.arbiter() == arbiter, "arbiter");
        require(escrow.shipWindow() == SHIP_WINDOW, "ship window");
        require(escrow.releaseWindow() == RELEASE_WINDOW, "release window");
        require(escrow.disputeTimeout() == DISPUTE_TIMEOUT, "dispute timeout");
        require(!escrow.paused(), "paused");
        // ERC-1967 implementation slot points at the fresh implementation.
        bytes32 slot = vm.load(address(escrow), 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc);
        require(address(uint160(uint256(slot))) == impl, "impl slot");

        console2.log("MarketEscrow proxy (use THIS):", address(escrow));
        console2.log("Implementation:", impl);
        console2.log("Owner:", owner_);
    }
}
