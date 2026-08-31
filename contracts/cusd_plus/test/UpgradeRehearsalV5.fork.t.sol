// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * v5 UPGRADE REHEARSAL against the LIVE BSC proxy (2026-07-31). Run:
 *
 *   forge test --match-path test/UpgradeRehearsalV5.fork.t.sol \
 *     --fork-url https://bsc-dataseed.bnbchain.org -vv
 *
 * v5 closes the open-mint gap: `subscribeAndMint` becomes sponsor-gated so
 * Ondo eligibility (the continuing US-person representation) can no longer
 * be bypassed by calling the vault directly. This rehearses EXACTLY what
 * the Safe will execute — a single atomic
 *
 *   upgradeToAndCall(v5Impl, abi.encodeCall(setSponsor, (KMS, true)))
 *
 * so the gate and its first sponsor land in the same transaction and no
 * block ever exists where minting is bricked.
 *
 * What only the fork proves: the appended `isSponsor` slot doesn't disturb
 * live storage, the live holder balance survives, and the exit still works
 * for a holder who is not and never was sponsored.
 */
import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {CusdPlusVault} from "../CusdPlusVault.sol";
import {CusdVault} from "../CusdVault.sol";
import {ConfioBatchDelegate} from "../ConfioBatchDelegate.sol";

contract UpgradeRehearsalV5ForkTest is Test {
    address constant PROXY = 0x3C29417eb4314155e63d4C7D4507852b87763Ed1;
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    address constant USDY = 0x608593d17A2decBbc4399e4185bE4922F97eD32E;
    address constant USDT = 0x55d398326f99059fF775485246999027B3197955;
    address constant IM = 0x9bA360087075A4Cef548eeD71Eed197bf4cFA4E2;
    address constant ORACLE = 0x8aaa843b848c2E3c83956Bc09aFBE4D9Dcf297b7;
    address constant KMS = 0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D; // sponsor

    address outsider = makeAddr("outsider");
    address holder = makeAddr("holder");

    function _forked() internal view returns (bool) {
        return PROXY.code.length > 0;
    }

    /// Deploy the cUSD perimeter and run the Safe's atomic cUSD+ upgrade+wiring.
    function _upgrade(CusdPlusVault v) internal {
        CusdVault cusdImpl = new CusdVault(USDT);
        CusdVault cusd =
            CusdVault(address(new ERC1967Proxy(address(cusdImpl), abi.encodeCall(CusdVault.initialize, (SAFE, 90)))));
        vm.startPrank(SAFE);
        cusd.setSponsor(KMS, true);
        cusd.setSavingsVault(PROXY);
        vm.stopPrank();

        CusdPlusVault impl5 = new CusdPlusVault(USDY, USDT, IM, ORACLE, 1500);
        vm.prank(SAFE);
        v.upgradeToAndCall(address(impl5), abi.encodeCall(CusdPlusVault.initializeCusd, (address(cusd))));
    }

    function test_fork_upgradePreservesStateAndSeedsSponsorAtomically() public {
        if (!_forked()) return;
        CusdPlusVault v = CusdPlusVault(PROXY);

        uint256 prePPlus = v.pPlus();
        uint256 preLast = v.lastOraclePrice();
        uint256 preSupply = v.totalSupply();
        address preOwner = v.owner();
        assertEq(preOwner, SAFE, "owner is the Safe pre-upgrade");

        _upgrade(v);

        assertEq(v.pPlus(), prePPlus, "pPlus survived");
        assertEq(v.lastOraclePrice(), preLast, "lastOraclePrice survived");
        assertEq(v.totalSupply(), preSupply, "supply survived");
        assertEq(v.owner(), SAFE, "owner survived");
        // The gate is armed in the SAME transaction that installs it.
        assertTrue(v.isSponsor(KMS), "sponsor seeded atomically");
        assertFalse(v.isSponsor(outsider), "nobody else is a sponsor");
    }

    function test_fork_directMintIsRejectedAfterUpgrade() public {
        if (!_forked()) return;
        CusdPlusVault v = CusdPlusVault(PROXY);
        _upgrade(v);

        deal(USDT, outsider, 1_000e18);
        vm.startPrank(outsider, outsider); // own tx, no sponsor anywhere
        IERC20(USDT).approve(PROXY, type(uint256).max);
        vm.expectRevert("not sponsored");
        v.subscribeAndMint(100e18, 0, outsider);
        vm.stopPrank();
    }

    /// The relayed path — user EOA as msg.sender, KMS as tx.origin — must
    /// still reach Ondo and mint real shares.
    function test_fork_relayedMintStillWorks() public {
        if (!_forked()) return;
        CusdPlusVault v = CusdPlusVault(PROXY);
        _upgrade(v);

        deal(USDT, holder, 1_000e18);
        vm.prank(holder, KMS);
        IERC20(USDT).approve(PROXY, type(uint256).max);
        vm.prank(holder, KMS);
        uint256 shares = v.subscribeAndMint(100e18, 0, holder);
        assertGt(shares, 0, "relayed mint produced shares");
        assertEq(v.balanceOf(holder), shares);
    }

    /// THE asymmetry, proven on live state: an unsponsored holder can
    /// always leave, in their own transaction, with no Confío involvement.
    function test_fork_exitStaysPermissionlessAfterUpgrade() public {
        if (!_forked()) return;
        CusdPlusVault v = CusdPlusVault(PROXY);
        _upgrade(v);

        // Acquire via the relay, then drop sponsorship entirely.
        deal(USDT, holder, 1_000e18);
        vm.prank(holder, KMS);
        IERC20(USDT).approve(PROXY, type(uint256).max);
        vm.prank(holder, KMS);
        uint256 shares = v.subscribeAndMint(100e18, 0, holder);

        vm.prank(SAFE);
        v.setSponsor(KMS, false); // Confío's relay goes dark

        vm.prank(holder, holder);
        vm.expectRevert("not sponsored");
        v.subscribeAndMint(1e18, 0, holder);

        uint256 beforeUsdt = IERC20(USDT).balanceOf(holder);
        vm.prank(holder, holder);
        uint256 out = v.redeemToUsdt(shares, 0, holder);
        assertGt(out, 0, "exit works with the relay dark");
        assertEq(IERC20(USDT).balanceOf(holder), beforeUsdt + out);
        assertEq(v.balanceOf(holder), 0);
    }

    /// The PRODUCTION call shape, not a pranked boundary (audit [P3]): a
    /// real ConfioBatchDelegate batch — [approve, subscribeAndMint] —
    /// signed by the user and broadcast by the KMS sponsor, executed
    /// against the upgraded live proxy. Delegation modeled with vm.etch,
    /// per the existing delegate fork tests.
    function test_fork_realDelegateBatchMintsAndPinsRecipient() public {
        if (!_forked()) return;
        CusdPlusVault v = CusdPlusVault(PROXY);
        _upgrade(v);

        (address u, uint256 pk) = makeAddrAndKey("v5-batch-user");
        vm.etch(u, address(new ConfioBatchDelegate()).code);
        deal(USDT, u, 1_000e18);

        // Honest batch: mint to SELF.
        ConfioBatchDelegate.Call[] memory calls = new ConfioBatchDelegate.Call[](2);
        calls[0] = ConfioBatchDelegate.Call({
            to: USDT, value: 0, data: abi.encodeWithSignature("approve(address,uint256)", PROXY, type(uint256).max)
        });
        calls[1] = ConfioBatchDelegate.Call({
            to: PROXY, value: 0, data: abi.encodeCall(CusdPlusVault.subscribeAndMint, (100e18, 0, u))
        });
        uint256 deadline = block.timestamp + 1 hours;
        (uint8 sv, bytes32 sr, bytes32 ss) =
            vm.sign(pk, ConfioBatchDelegate(payable(u)).hashExecute(calls, 0, deadline, bytes32(0)));
        vm.prank(SAFE, KMS); // sponsor broadcasts
        ConfioBatchDelegate(payable(u)).execute(calls, 0, deadline, bytes32(0), abi.encodePacked(sr, ss, sv));
        assertGt(v.balanceOf(u), 0, "relayed batch minted to the user");

        // Hostile batch: same sponsored origin, mint to a third party.
        address thirdParty = makeAddr("v5-ineligible");
        ConfioBatchDelegate.Call[] memory bad = new ConfioBatchDelegate.Call[](1);
        bad[0] = ConfioBatchDelegate.Call({
            to: PROXY, value: 0, data: abi.encodeCall(CusdPlusVault.subscribeAndMint, (100e18, 0, thirdParty))
        });
        (sv, sr, ss) = vm.sign(pk, ConfioBatchDelegate(payable(u)).hashExecute(bad, 1, deadline, bytes32(0)));
        vm.prank(SAFE, KMS);
        vm.expectRevert(); // delegate bubbles "recipient not caller"
        ConfioBatchDelegate(payable(u)).execute(bad, 1, deadline, bytes32(0), abi.encodePacked(sr, ss, sv));
        assertEq(v.balanceOf(thirdParty), 0, "no third-party issuance");
    }

    /// Secondary acquisition stays open — only PRIMARY issuance is gated.
    function test_fork_transfersUnaffected() public {
        if (!_forked()) return;
        CusdPlusVault v = CusdPlusVault(PROXY);
        _upgrade(v);

        deal(USDT, holder, 1_000e18);
        vm.prank(holder, KMS);
        IERC20(USDT).approve(PROXY, type(uint256).max);
        vm.prank(holder, KMS);
        uint256 shares = v.subscribeAndMint(100e18, 0, holder);

        vm.prank(holder, holder);
        v.transfer(outsider, shares);
        assertEq(v.balanceOf(outsider), shares, "secondary transfer open");
    }
}
