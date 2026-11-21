// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * THE EXACT SAFE TRANSACTION that wires Cuenta inteligente into cUSD (spec
 * decision 32), replayed as the Safe against live BSC state:
 *
 *   cUSD.upgradeToAndCall(CUSD_IMPL, setSmartAccountFactory(SA_FACTORY, true))
 *
 * SAFE_TX_DATA is the literal calldata printed by
 * .kms-local/kms_evm_multisig/build_smart_account_cusd_upgrade.py (and shown
 * to the signers). This test checks those bytes are exactly that call, runs
 * THEM (operation CALL, msg.sender = Safe) against the DEPLOYED
 * implementation and factory, and asserts the outcome:
 *
 *   SA_FACTORY=<factory proxy> CUSD_IMPL=<new CusdVault impl> SAFE_TX_DATA=0x… \
 *     forge test --match-contract SafeTxSmartAccountFactoryForkTest \
 *     --fork-url https://bsc-dataseed.bnbchain.org -vv
 *
 * Skips (passes as a no-op) without --fork-url or without the three
 * variables.
 */
import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {CusdVault} from "../CusdVault.sol";

interface ISmartAccountFactoryLike {
    function createAccount() external returns (address);
    function isAccount(address) external view returns (bool);
    function owner() external view returns (address);
    function paused() external view returns (bool);
}

interface ISmartAccountLike {
    function FACTORY() external view returns (address);
    function owner() external view returns (address);
}

contract SafeTxSmartAccountFactoryForkTest is Test {
    CusdVault constant CUSD = CusdVault(0x6101cC370635cF2c7f2725EaB010aC407A8d543F);
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    address constant SPONSOR = 0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D;
    bytes32 constant IMPL_SLOT = 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc;
    /// Own variables 0..7 of the live layout (feeBps .. batchDelegate);
    /// isSmartAccountFactory is appended at slot 8.
    uint256 constant LIVE_SLOTS = 8;

    // Snapshot of live state, in storage to keep the stack small.
    address factory;
    address impl;
    address usdt;
    bytes32[8] raw;
    uint256 supply;
    uint256 backing;
    bool backed;
    bool sponsored;
    uint256 cap;
    address delegate;
    uint256 feeBps;

    function test_fork_safeTxUpgradesCusdAndRecognisesTheFactory() public {
        if (address(CUSD).code.length == 0) return; // no --fork-url
        factory = vm.envOr("SA_FACTORY", address(0));
        impl = vm.envOr("CUSD_IMPL", address(0));
        bytes memory data = vm.envOr("SAFE_TX_DATA", bytes(""));
        if (factory == address(0) || impl == address(0) || data.length == 0) {
            vm.skip(true);
            return;
        }
        assertGt(factory.code.length, 0, "factory deployed");
        assertGt(impl.code.length, 0, "new cUSD implementation deployed");
        assertEq(ISmartAccountFactoryLike(factory).owner(), SAFE, "factory owned by the Safe");

        // The bytes are exactly the call we claim, nothing more.
        assertEq(
            data,
            abi.encodeCall(
                CUSD.upgradeToAndCall, (impl, abi.encodeCall(CusdVault.setSmartAccountFactory, (factory, true)))
            ),
            "SAFE_TX_DATA is upgradeToAndCall(impl, setSmartAccountFactory(factory, true))"
        );

        _snapshot();

        // The Safe transaction: literal bytes, CALL, as the Safe.
        vm.prank(SAFE);
        (bool ok,) = address(CUSD).call(data);
        assertTrue(ok, "Safe transaction succeeds");

        _assertUpgradedAndUnchanged();
        _assertMemberMintAndRedeem();
        _assertSmartAccountArmsReferral();
    }

    function _snapshot() internal {
        for (uint256 i; i < LIVE_SLOTS; ++i) {
            raw[i] = vm.load(address(CUSD), bytes32(i));
        }
        usdt = address(CUSD.USDT());
        supply = CUSD.totalSupply();
        backing = CUSD.backingUsdt();
        backed = CUSD.isFullyBacked();
        sponsored = CUSD.isSponsor(SPONSOR);
        cap = CUSD.referralShareCapBps();
        delegate = CUSD.batchDelegate();
        feeBps = CUSD.feeBps();
        assertEq(CUSD.owner(), SAFE);
        assertFalse(CUSD.paused(), "cUSD live and unpaused");
    }

    function _assertUpgradedAndUnchanged() internal {
        assertEq(address(uint160(uint256(vm.load(address(CUSD), IMPL_SLOT)))), impl, "impl slot updated");
        assertTrue(CUSD.isSmartAccountFactory(factory), "factory recognised");
        assertFalse(CUSD.isSmartAccountFactory(makeAddr("other")), "only that factory");
        bytes32 slot = keccak256(abi.encode(factory, uint256(8)));
        assertEq(uint256(vm.load(address(CUSD), slot)), 1, "mapping at slot 8");
        for (uint256 i; i < LIVE_SLOTS; ++i) {
            assertEq(vm.load(address(CUSD), bytes32(i)), raw[i], "own storage slot unchanged");
        }
        assertEq(CUSD.owner(), SAFE, "owner");
        assertEq(CUSD.pendingOwner(), address(0), "no pending owner");
        assertEq(CUSD.totalSupply(), supply, "supply");
        assertEq(CUSD.backingUsdt(), backing, "backing");
        assertEq(CUSD.isFullyBacked(), backed, "fully backed");
        assertEq(CUSD.isSponsor(SPONSOR), sponsored, "sponsor");
        assertTrue(sponsored, "the relayer is a cUSD sponsor");
        assertEq(CUSD.referralShareCapBps(), cap, "referral cap");
        assertEq(CUSD.batchDelegate(), delegate, "batch delegate");
        assertEq(CUSD.feeBps(), feeBps, "fee");
        assertEq(address(CUSD.USDT()), usdt, "USDT");
        assertFalse(CUSD.paused(), "still unpaused");
    }

    /// A member's mint and redeem still work (7702 account, sponsored).
    function _assertMemberMintAndRedeem() internal {
        address member = makeAddr("member");
        vm.etch(member, abi.encodePacked(hex"ef0100", delegate));
        deal(usdt, member, 100e18);
        vm.startPrank(member, SPONSOR);
        IERC20(usdt).approve(address(CUSD), type(uint256).max);
        uint256 net = CUSD.mintWithFee(100e18, 0, member);
        assertEq(net, 100e18 - CUSD.feeFor(100e18), "mint net of fee");
        uint256 before = IERC20(usdt).balanceOf(member);
        CUSD.redeemWithFee(net, 0, member);
        vm.stopPrank();
        assertGt(IERC20(usdt).balanceOf(member), before, "redeem pays USDT");
        assertEq(CUSD.balanceOf(member), 0);
        assertTrue(CUSD.isFullyBacked(), "1:1 backing after mint and redeem");
    }

    /// A real account of the deployed factory arms and pays a referral.
    function _assertSmartAccountArmsReferral() internal {
        if (ISmartAccountFactoryLike(factory).paused() || cap < 5_000) return;
        address owner_ = makeAddr("smart-account-owner");
        vm.prank(owner_);
        address account = ISmartAccountFactoryLike(factory).createAccount();
        assertTrue(ISmartAccountFactoryLike(factory).isAccount(account));
        assertEq(ISmartAccountLike(account).FACTORY(), factory);
        assertEq(ISmartAccountLike(account).owner(), owner_);
        address referrer = makeAddr("referrer");
        deal(usdt, account, 100e18);
        vm.startPrank(account, SPONSOR); // msg.sender = account, tx.origin = relayer
        IERC20(usdt).approve(address(CUSD), type(uint256).max);
        CUSD.armReferral(referrer, 5_000);
        (, address referee,) = CUSD.armedReferral();
        assertEq(referee, account, "the account is the referee");
        CUSD.mintWithFee(100e18, 0, account);
        vm.stopPrank();
        assertEq(CUSD.balanceOf(referrer), CUSD.feeFor(100e18) / 2, "referrer paid half the fee");
        assertTrue(CUSD.isFullyBacked(), "backing holds");

        // An unrelated contract still cannot arm.
        vm.prank(address(this), SPONSOR);
        vm.expectRevert("not a Confio account");
        CUSD.armReferral(referrer, 5_000);
    }
}
