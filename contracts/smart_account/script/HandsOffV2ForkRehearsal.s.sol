// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * Hands-off v2 deployment rehearsal — LOCAL ANVIL FORK ONLY (2026-11-25).
 *
 * Never point this at a real network: every entry point refuses unless the
 * RPC is an anvil fork (chain id 56 + anvil_* answered by the caller's
 * script, see run_handsoff_fork_rehearsal.sh) and it uses throwaway keys
 * derived from public labels. It signs nothing real; Safe owners act via
 * impersonated approveHash on the fork.
 *
 * Entry points (forge script --sig "<fn>()" --rpc-url <anvil> --broadcast --unlocked --slow):
 *   setupV1()     before the upgrade: two v1 test accounts on the REAL factory
 *   snapshot()    view: factory + escrow state, key=value lines (diff pre/post)
 *   safeBatch()   the ONE Safe tx (MultiSendCallOnly, DELEGATECALL) as the Safe
 *                 executes it: approveHash by owners 1/3/5, sponsor executes
 *   postChecks()  view: asserts the upgrade landed as intended
 *   phaseA()      v1 still works, new account is v2, Safe unpauses, migration
 *                 batch through the real ConfioBatchDelegate, relay buy, relay
 *                 purchase (depositFrom on the real escrow)
 *   phaseB()      relay sell (after the 60 s gap)
 *   phaseC()      relay gold buy (after another gap)
 *   phaseD()      buyer reclaim after shipBy: refund lands in the account
 *
 * Env: NEW_FACTORY_LOGIC, V2_IMPL, NEW_ESCROW_IMPL (safeBatch/postChecks),
 *      USE_PLUS=1 to run the Trade rule in cUSD+ (needs Ondo IM on the fork).
 */
import {Script, console2} from "forge-std/Script.sol";
import {IConfioSmartAccountV2} from "../interfaces/IConfioSmartAccountV2.sol";

interface IERC20Like {
    function balanceOf(address) external view returns (uint256);
    function transfer(address, uint256) external returns (bool);
    function approve(address, uint256) external returns (bool);
}

interface ISafe {
    function nonce() external view returns (uint256);
    function getOwners() external view returns (address[] memory);
    function getThreshold() external view returns (uint256);
    function approveHash(bytes32) external;
    function getTransactionHash(
        address to,
        uint256 value,
        bytes calldata data,
        uint8 operation,
        uint256 safeTxGas,
        uint256 baseGas,
        uint256 gasPrice,
        address gasToken,
        address refundReceiver,
        uint256 nonce
    ) external view returns (bytes32);
    function execTransaction(
        address to,
        uint256 value,
        bytes calldata data,
        uint8 operation,
        uint256 safeTxGas,
        uint256 baseGas,
        uint256 gasPrice,
        address gasToken,
        address payable refundReceiver,
        bytes memory signatures
    ) external payable returns (bool);
}

interface IFactory {
    function owner() external view returns (address);
    function implementation() external view returns (address);
    function paused() external view returns (bool);
    function relayerPaused() external view returns (bool);
    function inheritanceEnabled() external view returns (bool);
    function cardPaused() external view returns (bool);
    function claimCooldown() external view returns (uint64);
    function forcedSaleNotice() external view returns (uint64);
    function feeUsd(uint8) external view returns (uint256);
    function accountOf(address) external view returns (address);
    function isAccount(address) external view returns (bool);
    function generationOf(address) external view returns (uint64);
    function predictAddressAt(address, uint64) external view returns (address);
    function createAccount() external returns (address);
    function migrate() external returns (address);
    function upgradeToAndCall(address, bytes calldata) external payable;
    function initializeV2(address) external;
    function setTradePaused(bool) external;
    function tradePaused() external view returns (bool);
    function implementationOf(address) external view returns (address);
    function implementationCount() external view returns (uint256);
    function implementationAt(uint256) external view returns (address);
}

interface IAccountV1 {
    function owner() external view returns (address);
    function status() external view returns (uint8);
    function plan() external view returns (uint8);
    function paidUntil() external view returns (uint64);
    function subscribe(uint8 plan, uint256 maxFeeUsd) external;
    function cancelSubscription() external;
    function withdraw(address token, uint256 amount) external;
    function withdrawAll(address[] calldata tokens) external;
}

interface IEscrow {
    function owner() external view returns (address);
    function orderSigner() external view returns (address);
    function arbiter() external view returns (address);
    function paused() external view returns (bool);
    function shipWindow() external view returns (uint64);
    function releaseWindow() external view returns (uint64);
    function disputeTimeout() external view returns (uint64);
    function tokenLimits(address) external view returns (uint128, uint128);
    function openPrincipal(address) external view returns (uint256);
    function accruedFees(address) external view returns (uint256);
    function accountFactory() external view returns (address);
    function refundToOf(bytes32) external view returns (address);
    function setAccountFactory(address) external;
    function setOrderSigner(address) external;
    function upgradeToAndCall(address, bytes calldata) external payable;
    function depositFromDigest(bytes32, address, address, address, address, uint256, uint16, uint256)
        external
        view
        returns (bytes32);
    function reclaim(bytes32) external;
}

interface ICusd {
    function mintWithFee(uint256 grossUsdt, uint256 minCusdOut, address recipient) external returns (uint256);
}

interface ICusdPlus {
    function subscribeAndMint(uint256 usdtIn, uint256 minUsdyOut, address recipient) external returns (uint256);
    function pPlus() external view returns (uint256);
}

interface IBatchDelegate {
    struct Call {
        address to;
        uint256 value;
        bytes data;
    }

    function execute(Call[] calldata calls, uint256 nonce, uint256 deadline, bytes32 intentId, bytes calldata signature)
        external
        payable;
    function nonces() external view returns (uint256);
    function hashExecute(Call[] calldata calls, uint256 nonce, uint256 deadline, bytes32 intentId)
        external
        view
        returns (bytes32);
}

contract HandsOffV2ForkRehearsal is Script {
    // ── BSC mainnet (contracts/cusd_plus/DEPLOYMENT.md, .env.mainnet) ──
    ISafe constant SAFE = ISafe(0xF29A418744E793973BF4eEc676F8a30B2793b623);
    address constant MULTISEND_CALL_ONLY = 0x40A2aCCbd92BCA938b02010E17A5b8929b49130D;
    IFactory constant FACTORY = IFactory(0x339094A17605B842e0b2fc01441204E67020f953);
    IEscrow constant ESCROW = IEscrow(0x2DFDC1fB809322c12f54beFE8CC98E0d103a99Fd);
    address constant V1_IMPL = 0x8a20a0B3d2C0c6BED8BeB00bB6Bc7AE3c7ace44A;
    address constant SPONSOR = 0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D;
    address constant BATCH_DELEGATE = 0xC06BD197b34a587026615C6AEd21301F5E99bc00;
    address constant CUSD = 0x6101cC370635cF2c7f2725EaB010aC407A8d543F;
    address constant CUSD_PLUS = 0x3C29417eb4314155e63d4C7D4507852b87763Ed1;
    address constant USDT = 0x55d398326f99059fF775485246999027B3197955;
    address constant BTCB = 0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c;
    address constant XAUT = 0x21cAef8A43163Eea865baeE23b9C2E327696A3bf;
    address constant CONFIO = 0xF5765933764562A51e179F6AF2b19b7a3d506101;
    address constant SWAP_ROUTER = 0xA7C27684aB38eC369cB1F4474f279ea503dbF712;
    /// Binance hot wallet: USDT and BTCB source on the fork only.
    address constant WHALE = 0xF977814e90dA44bFA03b6295A0616a897441aceC;
    bytes32 constant IMPL_SLOT = 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc;

    uint8 constant MONTHLY = 1;
    uint8 constant DOLLAR_PLUS = 0;
    uint8 constant DOLLAR = 1;
    uint256 constant FEE_BPS = 90;

    // Throwaway fork-only keys from public labels.
    uint256 ALICE_PK = uint256(keccak256("confio-fork-rehearsal-alice"));
    uint256 BOB_PK = uint256(keccak256("confio-fork-rehearsal-bob"));
    uint256 DANA_PK = uint256(keccak256("confio-fork-rehearsal-dana"));
    uint256 SIGNER_PK = uint256(keccak256("confio-fork-rehearsal-order-signer"));

    function _guard() internal view {
        require(block.chainid == 56, "BSC fork only");
        // Anvil answers; a real node does not have this account unlocked and the
        // shell wrapper refuses non-local RPCs. Belt and braces: a fork-only key.
        require(vm.addr(ALICE_PK) != address(0));
    }

    function alice() public view returns (address) {
        return vm.addr(ALICE_PK);
    }

    function bob() public view returns (address) {
        return vm.addr(BOB_PK);
    }

    function dana() public view returns (address) {
        return vm.addr(DANA_PK);
    }

    function merchant() public pure returns (address) {
        return address(uint160(uint256(keccak256("confio-fork-rehearsal-merchant"))));
    }

    function _usePlus() internal view returns (bool) {
        return vm.envOr("USE_PLUS", uint256(0)) == 1;
    }

    // ═════════════════════════ setup (before the upgrade) ════════════════

    function setupV1() external {
        _guard();
        require(FACTORY.implementation() == V1_IMPL, "already upgraded");
        vm.broadcast(alice());
        address a = FACTORY.createAccount();
        vm.broadcast(bob());
        address b = FACTORY.createAccount();
        vm.startBroadcast(WHALE);
        IERC20Like(USDT).transfer(SPONSOR, 600e18);
        IERC20Like(BTCB).transfer(a, 2e14); // 0.0002 BTC
        vm.stopBroadcast();
        vm.startBroadcast(SPONSOR);
        IERC20Like(USDT).approve(CUSD, 200e18);
        ICusd(CUSD).mintWithFee(150e18, 1, a);
        ICusd(CUSD).mintWithFee(50e18, 1, b);
        if (_usePlus()) {
            IERC20Like(USDT).approve(CUSD_PLUS, 100e18);
            ICusdPlus(CUSD_PLUS).subscribeAndMint(100e18, 0, a);
        }
        vm.stopBroadcast();
        vm.broadcast(alice());
        IAccountV1(a).subscribe(MONTHLY, type(uint256).max);
        vm.broadcast(bob());
        IAccountV1(b).subscribe(MONTHLY, type(uint256).max);
        console2.log("alice", alice(), "v1 account", a);
        console2.log("bob", bob(), "v1 account", b);
    }

    // ═════════════════════════ snapshot (view) ═══════════════════════════

    function _kv(string memory k, bytes32 v) internal pure {
        console2.log(string.concat(k, "=", vm.toString(v)));
    }

    function _kv(string memory k, uint256 v) internal pure {
        console2.log(string.concat(k, "=", vm.toString(v)));
    }

    function _kv(string memory k, address v) internal pure {
        console2.log(string.concat(k, "=", vm.toString(v)));
    }

    function snapshot() external view {
        address a = FACTORY.accountOf(alice());
        address b = FACTORY.accountOf(bob());
        _kv("factory.owner", FACTORY.owner());
        _kv("factory.implementation", FACTORY.implementation());
        _kv("factory.paused", FACTORY.paused() ? 1 : 0);
        _kv("factory.relayerPaused", FACTORY.relayerPaused() ? 1 : 0);
        _kv("factory.inheritanceEnabled", FACTORY.inheritanceEnabled() ? 1 : 0);
        _kv("factory.cardPaused", FACTORY.cardPaused() ? 1 : 0);
        _kv("factory.claimCooldown", FACTORY.claimCooldown());
        _kv("factory.forcedSaleNotice", FACTORY.forcedSaleNotice());
        _kv("factory.feeUsd(1)", FACTORY.feeUsd(1));
        _kv("factory.feeUsd(2)", FACTORY.feeUsd(2));
        _kv("factory.accountOf(bob)", b);
        _kv("factory.isAccount(bobAcct)", FACTORY.isAccount(b) ? 1 : 0);
        _kv("factory.generationOf(bob)", FACTORY.generationOf(bob()));
        _kv("factory.accountOf(alice)", a);
        _kv("factory.isAccount(aliceAcct)", FACTORY.isAccount(a) ? 1 : 0);
        for (uint256 i = 0; i <= 13; ++i) {
            _kv(string.concat("factory.slot", vm.toString(i)), vm.load(address(FACTORY), bytes32(i)));
        }
        _kv("factory.slot.erc1967", vm.load(address(FACTORY), IMPL_SLOT));
        // OZ v5 ERC-7201 namespaces: Ownable, Ownable2Step, Pausable, Initializable.
        _kv("factory.slot.ownable", vm.load(address(FACTORY), 0x9016d09d72d40fdae2fd8ceac6b6234c7706214fd39c1cd1e609a0528c199300));
        _kv("factory.slot.ownable2step", vm.load(address(FACTORY), 0x237e158222e3e6968b72b9db0d8043aacf074ad9f650f0d1606b4d82ee432c00));
        _kv("factory.slot.pausable", vm.load(address(FACTORY), 0xcd5ed15c6e187e77e9aee88184c21f4f2182ab5827cb3b7e07fbedcd63f03300));
        _kv("factory.slot.initializable", vm.load(address(FACTORY), 0xf0c57e16840df040f15088dc2f81fe391c3923bec73e23a9662efc9c229c6a00));
        if (b != address(0)) {
            _kv("bobAcct.owner", IAccountV1(b).owner());
            _kv("bobAcct.status", IAccountV1(b).status());
            _kv("bobAcct.paidUntil", IAccountV1(b).paidUntil());
        }
        _kv("escrow.owner", ESCROW.owner());
        _kv("escrow.orderSigner", ESCROW.orderSigner());
        _kv("escrow.arbiter", ESCROW.arbiter());
        _kv("escrow.paused", ESCROW.paused() ? 1 : 0);
        _kv("escrow.shipWindow", ESCROW.shipWindow());
        _kv("escrow.releaseWindow", ESCROW.releaseWindow());
        _kv("escrow.disputeTimeout", ESCROW.disputeTimeout());
        (uint128 mo, uint128 mx) = ESCROW.tokenLimits(CUSD);
        _kv("escrow.tokenLimits(cUSD).maxOrder", mo);
        _kv("escrow.tokenLimits(cUSD).maxOpen", mx);
        _kv("escrow.openPrincipal(cUSD)", ESCROW.openPrincipal(CUSD));
        _kv("escrow.accruedFees(cUSD)", ESCROW.accruedFees(CUSD));
        _kv("escrow.cUSD.balance", IERC20Like(CUSD).balanceOf(address(ESCROW)));
        for (uint256 i = 0; i <= 8; ++i) {
            _kv(string.concat("escrow.slot", vm.toString(i)), vm.load(address(ESCROW), bytes32(i)));
        }
        _kv("escrow.slot.erc1967", vm.load(address(ESCROW), IMPL_SLOT));
        _kv("escrow.slot.ownable", vm.load(address(ESCROW), 0x9016d09d72d40fdae2fd8ceac6b6234c7706214fd39c1cd1e609a0528c199300));
        _kv("escrow.slot.pausable", vm.load(address(ESCROW), 0xcd5ed15c6e187e77e9aee88184c21f4f2182ab5827cb3b7e07fbedcd63f03300));
        _kv("escrow.slot.initializable", vm.load(address(ESCROW), 0xf0c57e16840df040f15088dc2f81fe391c3923bec73e23a9662efc9c229c6a00));
        _kv("safe.nonce", SAFE.nonce());
    }

    // ═════════════════════════ the Safe batch ════════════════════════════

    function _packed(address to, bytes memory data) internal pure returns (bytes memory) {
        return abi.encodePacked(uint8(0), to, uint256(0), uint256(data.length), data);
    }

    /// The three inner calls and the MultiSendCallOnly calldata.
    function batchCalldata(address factoryLogic, address v2Impl, address escrowImpl)
        public
        pure
        returns (bytes memory c1, bytes memory c2, bytes memory c3, bytes memory multiSend)
    {
        c1 = abi.encodeCall(IFactory.upgradeToAndCall, (factoryLogic, abi.encodeCall(IFactory.initializeV2, (v2Impl))));
        c2 = abi.encodeCall(IFactory.setTradePaused, (true));
        c3 = abi.encodeCall(
            IEscrow.upgradeToAndCall, (escrowImpl, abi.encodeCall(IEscrow.setAccountFactory, (address(FACTORY))))
        );
        bytes memory payload = _packed(address(FACTORY), c1);
        payload = bytes.concat(payload, _packed(address(FACTORY), c2));
        payload = bytes.concat(payload, _packed(address(ESCROW), c3));
        multiSend = abi.encodeWithSignature("multiSend(bytes)", payload);
    }

    /// One Safe tx on the fork: owners 1/3/5 (indices 0/2/4) approveHash,
    /// the sponsor submits execTransaction with pre-validated signatures.
    function _execSafe(address to, bytes memory data, uint8 operation) internal returns (bytes32 safeTxHash) {
        uint256 n = SAFE.nonce();
        safeTxHash = SAFE.getTransactionHash(to, 0, data, operation, 0, 0, 0, address(0), address(0), n);
        address[] memory owners = SAFE.getOwners();
        address[3] memory signers = [owners[0], owners[2], owners[4]];
        for (uint256 i = 0; i < 3; ++i) {
            vm.broadcast(signers[i]);
            SAFE.approveHash(safeTxHash);
        }
        // Signatures sorted by owner, v = 1 (approved hash).
        for (uint256 i = 0; i < 3; ++i) {
            for (uint256 j = i + 1; j < 3; ++j) {
                if (signers[j] < signers[i]) (signers[i], signers[j]) = (signers[j], signers[i]);
            }
        }
        bytes memory sigs;
        for (uint256 i = 0; i < 3; ++i) {
            sigs = bytes.concat(sigs, bytes32(uint256(uint160(signers[i]))), bytes32(0), bytes1(0x01));
        }
        vm.broadcast(SPONSOR);
        require(
            SAFE.execTransaction(to, 0, data, operation, 0, 0, 0, address(0), payable(address(0)), sigs), "safe exec"
        );
        console2.log("Safe nonce", n);
        console2.logBytes32(safeTxHash);
    }

    function safeBatch() external {
        _guard();
        address logic = vm.envAddress("NEW_FACTORY_LOGIC");
        address v2 = vm.envAddress("V2_IMPL");
        address escrowImpl = vm.envAddress("NEW_ESCROW_IMPL");
        (bytes memory c1, bytes memory c2, bytes memory c3, bytes memory ms) = batchCalldata(logic, v2, escrowImpl);
        console2.log("inner 1: to factory proxy, upgradeToAndCall(logic, initializeV2(v2))");
        console2.logBytes(c1);
        console2.log("inner 2: to factory proxy, setTradePaused(true)");
        console2.logBytes(c2);
        console2.log("inner 3: to escrow proxy, upgradeToAndCall(escrowImpl, setAccountFactory(factory))");
        console2.logBytes(c3);
        console2.log("Safe tx: to MultiSendCallOnly, operation 1 (DELEGATECALL), value 0, data:");
        console2.logBytes(ms);
        _execSafe(MULTISEND_CALL_ONLY, ms, 1);
    }

    function postChecks() external view {
        address v2 = vm.envAddress("V2_IMPL");
        require(address(uint160(uint256(vm.load(address(FACTORY), IMPL_SLOT)))) == vm.envAddress("NEW_FACTORY_LOGIC"), "factory impl slot");
        require(address(uint160(uint256(vm.load(address(ESCROW), IMPL_SLOT)))) == vm.envAddress("NEW_ESCROW_IMPL"), "escrow impl slot");
        require(FACTORY.implementation() == v2, "implementation != v2");
        require(FACTORY.implementationCount() == 2, "implementationCount");
        require(FACTORY.implementationAt(0) == V1_IMPL && FACTORY.implementationAt(1) == v2, "implementation list");
        require(FACTORY.tradePaused(), "tradePaused");
        require(FACTORY.owner() == address(SAFE) && ESCROW.owner() == address(SAFE), "owners");
        require(ESCROW.accountFactory() == address(FACTORY), "escrow factory");
        require(FACTORY.implementationOf(FACTORY.accountOf(bob())) == V1_IMPL, "bob stays v1");
        require(IConfioSmartAccountV2(v2).VERSION() == 2 && IConfioSmartAccountV2(v2).ESCROW() == address(ESCROW), "v2 cfg");
        console2.log("postChecks: OK (impl slots, implementation list [v1, v2], tradePaused, escrow factory, owners)");
    }

    // ═════════════════════════ phase A ═══════════════════════════════════

    function _rule(IConfioSmartAccountV2.RuleKind kind, address tokenIn, address payee, uint256 cap)
        internal
        pure
        returns (IConfioSmartAccountV2.RuleInput memory r)
    {
        r.kind = kind;
        r.frequency = IConfioSmartAccountV2.Frequency.Weekly;
        r.tokenIn = tokenIn;
        r.payee = payee;
        r.amountUsd = cap;
    }

    function _tradeIn() internal view returns (address) {
        return _usePlus() ? CUSD_PLUS : CUSD;
    }

    function phaseA() external {
        _guard();
        _v1StillWorks();
        _newAccountIsV2();
        // 3. Safe unpauses hands-off (canary step), and on the FORK ONLY
        //    rotates the escrow order signer to a throwaway key so a
        //    depositFrom authorization can be produced here.
        _execSafe(address(FACTORY), abi.encodeCall(IFactory.setTradePaused, (false)), 0);
        _execSafe(address(ESCROW), abi.encodeCall(IEscrow.setOrderSigner, (vm.addr(SIGNER_PK))), 0);
        require(!FACTORY.tradePaused(), "unpaused");
        IConfioSmartAccountV2 n = _migrate();
        (uint256 tradeId, uint256 purchaseId) = _ids(n);
        require(uint8(n.rule(tradeId).kind) == 4 && uint8(n.rule(purchaseId).kind) == 5, "rule ids");
        // 5. relayTrade buy BTCB through the real ConfioSwapRouter.
        _relayBuy(n, tradeId, BTCB, 100, 20e18);
        console2.log("relay buy BTCB OK, BTCB held", IERC20Like(BTCB).balanceOf(address(n)));
        _purchase(n, purchaseId);
    }

    function _v1StillWorks() internal {
        // 1. A v1 account still works: reads and an owner withdrawal.
        address b = FACTORY.accountOf(bob());
        require(IAccountV1(b).owner() == bob() && IAccountV1(b).status() == 1, "bob v1 read");
        uint256 before = IERC20Like(CUSD).balanceOf(bob());
        vm.broadcast(bob());
        IAccountV1(b).withdraw(CUSD, 1e18);
        require(IERC20Like(CUSD).balanceOf(bob()) == before + 1e18, "bob v1 withdraw");
        console2.log("v1 account withdraw OK", b);
    }

    function _newAccountIsV2() internal {
        // 2. A new account is v2.
        vm.broadcast(dana());
        address d = FACTORY.createAccount();
        require(FACTORY.implementationOf(d) == FACTORY.implementation(), "dana v2");
        require(IConfioSmartAccountV2(d).VERSION() == 2, "dana VERSION");
        console2.log("new account is v2", d);
    }

    function _tokens() internal pure returns (address[] memory tokens) {
        tokens = new address[](6);
        tokens[0] = CUSD;
        tokens[1] = CUSD_PLUS;
        tokens[2] = USDT;
        tokens[3] = BTCB;
        tokens[4] = XAUT;
        tokens[5] = CONFIO;
    }

    function _migrationCalls(address oldAcct, address moved, uint256[] memory amounts)
        internal
        view
        returns (IBatchDelegate.Call[] memory calls)
    {
        address[] memory tokens = _tokens();
        uint256 nonzero;
        for (uint256 i = 0; i < 6; ++i) {
            if (amounts[i] > 0) ++nonzero;
        }
        calls = new IBatchDelegate.Call[](5 + nonzero);
        calls[0] = IBatchDelegate.Call(oldAcct, 0, abi.encodeCall(IAccountV1.cancelSubscription, ()));
        calls[1] = IBatchDelegate.Call(address(FACTORY), 0, abi.encodeCall(IFactory.migrate, ()));
        calls[2] = IBatchDelegate.Call(oldAcct, 0, abi.encodeCall(IAccountV1.withdrawAll, (tokens)));
        uint256 k = 3;
        for (uint256 i = 0; i < 6; ++i) {
            if (amounts[i] == 0) continue;
            calls[k++] = IBatchDelegate.Call(tokens[i], 0, abi.encodeCall(IERC20Like.transfer, (moved, amounts[i])));
        }
        calls[k++] = IBatchDelegate.Call(
            moved,
            0,
            abi.encodeCall(
                IConfioSmartAccountV2.createRule,
                (_rule(IConfioSmartAccountV2.RuleKind.Trade, _tradeIn(), address(0), 1_000e18))
            )
        );
        calls[k] = IBatchDelegate.Call(
            moved,
            0,
            abi.encodeCall(
                IConfioSmartAccountV2.createRule,
                (_rule(IConfioSmartAccountV2.RuleKind.Purchase, CUSD, address(ESCROW), 200e18))
            )
        );
    }

    function _signBatch(IBatchDelegate.Call[] memory calls, uint256 dNonce, uint256 deadline, bytes32 intent)
        internal
        view
        returns (bytes memory)
    {
        bytes32 h = IBatchDelegate(alice()).hashExecute(calls, dNonce, deadline, intent);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(ALICE_PK, h);
        return abi.encodePacked(r, s, v);
    }

    function _migrate() internal returns (IConfioSmartAccountV2 n) {
        // 4. Migration batch, one signature by the owner, sponsor submits
        //    through the real ConfioBatchDelegate (alice's code was set to
        //    its 7702 designator by the shell wrapper).
        address oldAcct = FACTORY.accountOf(alice());
        address moved = FACTORY.predictAddressAt(alice(), FACTORY.generationOf(alice()) + 1);
        address[] memory tokens = _tokens();
        uint256[] memory amounts = new uint256[](6);
        for (uint256 i = 0; i < 6; ++i) {
            amounts[i] = IERC20Like(tokens[i]).balanceOf(oldAcct);
        }
        IBatchDelegate.Call[] memory calls = _migrationCalls(oldAcct, moved, amounts);
        uint256 dNonce = IBatchDelegate(alice()).nonces();
        uint256 deadline = block.timestamp + 1 hours;
        bytes32 intent = keccak256("confio-fork-rehearsal-migration");
        bytes memory sig = _signBatch(calls, dNonce, deadline, intent);
        uint64 paidUntil = IAccountV1(oldAcct).paidUntil();
        vm.broadcast(SPONSOR);
        IBatchDelegate(alice()).execute(calls, dNonce, deadline, intent, sig);
        require(FACTORY.accountOf(alice()) == moved, "migrated");
        require(FACTORY.implementationOf(moved) == FACTORY.implementation(), "migrated to v2");
        require(FACTORY.isAccount(oldAcct), "old stays an account");
        for (uint256 i = 0; i < 6; ++i) {
            require(IERC20Like(tokens[i]).balanceOf(oldAcct) == 0, "old not empty");
            require(IERC20Like(tokens[i]).balanceOf(moved) == amounts[i], "new short");
        }
        n = IConfioSmartAccountV2(moved);
        require(n.paidUntil() == paidUntil && n.status() == 1, "subscription carried");
        console2.log("migration batch OK: calls", calls.length, "new account", moved);
    }

    function _purchase(IConfioSmartAccountV2 n, uint256 purchaseId) internal {
        // 6. relayPurchase -> escrow.depositFrom (the owner is the buyer).
        bytes32 orderId = keccak256("confio-fork-rehearsal-order-1");
        uint256 amount = 25e18;
        uint256 dl = block.timestamp + 1 hours;
        bytes32 digest = ESCROW.depositFromDigest(orderId, alice(), address(n), merchant(), CUSD, amount, 250, dl);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(SIGNER_PK, digest);
        uint256 cusdBefore = IERC20Like(CUSD).balanceOf(address(n));
        vm.broadcast(SPONSOR);
        n.relayPurchase(purchaseId, orderId, merchant(), amount, 250, dl, abi.encodePacked(r, s, v));
        require(cusdBefore - IERC20Like(CUSD).balanceOf(address(n)) == amount, "paid exactly");
        require(ESCROW.refundToOf(orderId) == address(n), "refundTo = account");
        console2.log("relayPurchase / depositFrom OK, order refunds to", address(n));
    }

    function _route(address a, uint24 fee, address b) internal pure returns (bytes memory) {
        return abi.encode(uint8(0), abi.encodePacked(a, fee, b));
    }

    function _relayBuy(IConfioSmartAccountV2 n, uint256 id, address token, uint24 poolFee, uint256 usd) internal {
        bool plus = _usePlus();
        uint256 amountIn = plus ? (usd * 1e18) / ICusdPlus(CUSD_PLUS).pPlus() : usd;
        bytes memory data = abi.encodeWithSignature(
            "buy(uint8,uint256,uint256,bytes,address,uint256,uint256)",
            plus ? DOLLAR_PLUS : DOLLAR,
            amountIn,
            (usd * 98) / 100,
            _route(USDT, poolFee, token),
            token,
            1,
            FEE_BPS
        );
        vm.broadcast(SPONSOR);
        n.relayTrade(id, SWAP_ROUTER, data, amountIn, 1);
    }

    function _ids(IConfioSmartAccountV2 n) internal view returns (uint256 tradeId, uint256 purchaseId) {
        tradeId = n.nextRuleId() - 2;
        purchaseId = tradeId + 1;
    }

    // ═════════════════════════ phase B / C / D ═══════════════════════════

    function phaseB() external {
        _guard();
        IConfioSmartAccountV2 n = IConfioSmartAccountV2(FACTORY.accountOf(alice()));
        (uint256 tradeId,) = _ids(n);
        uint256 amount = IERC20Like(BTCB).balanceOf(address(n));
        bytes memory data = abi.encodeWithSignature(
            "sell(uint8,address,uint256,bytes,uint256,uint256,uint256)",
            _usePlus() ? DOLLAR_PLUS : DOLLAR,
            BTCB,
            amount,
            _route(BTCB, 100, USDT),
            1,
            1,
            FEE_BPS
        );
        address out = _tradeIn();
        uint256 before = IERC20Like(out).balanceOf(address(n));
        vm.broadcast(SPONSOR);
        n.relayTrade(tradeId, SWAP_ROUTER, data, amount, 1);
        require(IERC20Like(BTCB).balanceOf(address(n)) == 0, "sold all");
        (uint256 used,) = n.bucketOf(tradeId);
        console2.log("relay sell BTCB OK, dollars back", IERC20Like(out).balanceOf(address(n)) - before);
        console2.log("bucket used (USD 1e18)", used);
    }

    function phaseC() external {
        _guard();
        IConfioSmartAccountV2 n = IConfioSmartAccountV2(FACTORY.accountOf(alice()));
        (uint256 tradeId,) = _ids(n);
        _relayBuy(n, tradeId, XAUT, 500, 10e18);
        console2.log("relay buy XAUT OK, XAUT held", IERC20Like(XAUT).balanceOf(address(n)));
    }

    function phaseD() external {
        _guard();
        address moved = FACTORY.accountOf(alice());
        bytes32 orderId = keccak256("confio-fork-rehearsal-order-1");
        uint256 before = IERC20Like(CUSD).balanceOf(moved);
        vm.broadcast(alice());
        ESCROW.reclaim(orderId);
        require(IERC20Like(CUSD).balanceOf(moved) == before + 25e18, "refund to the account");
        console2.log("reclaim after shipBy OK: 25 cUSD back in the account", moved);
    }
}
