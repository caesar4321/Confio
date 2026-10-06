// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {OwnableUpgradeable} from "@openzeppelin/contracts-upgradeable/access/OwnableUpgradeable.sol";
import {Ownable2StepUpgradeable} from "@openzeppelin/contracts-upgradeable/access/Ownable2StepUpgradeable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {ConfioHeartbeat} from "../ConfioHeartbeat.sol";
import {ConfioBatchDelegate} from "../ConfioBatchDelegate.sol";
import {MockToken} from "./CusdPlusVault.t.sol";

contract ConfioHeartbeatV2 is ConfioHeartbeat {
    function version() external pure returns (uint256) {
        return 2;
    }
}

/// An upgrade that drops assertSilent entirely: the gate call then hits an
/// unknown selector, which must revert the batch, never pass it.
contract NoGate is Ownable2StepUpgradeable, UUPSUpgradeable {
    function _authorizeUpgrade(address) internal view override onlyOwner {}
}

contract ConfioHeartbeatTest is Test {
    uint64 constant SILENCE = 14 days;

    ConfioHeartbeat hb;
    address safe = makeAddr("safe");
    address beater = makeAddr("beater");

    // Exit integration
    ConfioBatchDelegate delegate;
    MockToken usdt;
    address user;
    uint256 userPk;

    event Beat(uint64 at);
    event BeaterChanged(address indexed previous, address indexed current);
    event SilenceRequiredChanged(uint64 previous, uint64 current);
    address dest = makeAddr("dest");

    function setUp() public {
        vm.warp(1_800_000_000);
        ConfioHeartbeat impl = new ConfioHeartbeat();
        hb = ConfioHeartbeat(
            address(new ERC1967Proxy(address(impl), abi.encodeCall(ConfioHeartbeat.initialize, (safe, beater, SILENCE))))
        );

        delegate = new ConfioBatchDelegate();
        usdt = new MockToken("USDT");
        (user, userPk) = makeAddrAndKey("user");
        vm.etch(user, address(delegate).code); // model the 7702 designation
        usdt.mint(user, 500e18);
    }

    // ── initialization ──────────────────────────────────────────────────

    function test_InitStartsAlive() public view {
        assertEq(hb.owner(), safe);
        assertEq(hb.beater(), beater);
        assertEq(hb.silenceRequired(), SILENCE);
        assertEq(hb.lastBeat(), block.timestamp);
        assertFalse(hb.isSilent());
    }

    function test_ImplementationCannotBeInitialized() public {
        ConfioHeartbeat impl = new ConfioHeartbeat();
        vm.expectRevert();
        impl.initialize(safe, beater, SILENCE);
    }

    function test_InitRejectsBadParams() public {
        ConfioHeartbeat impl = new ConfioHeartbeat();
        vm.expectRevert(ConfioHeartbeat.ZeroAddress.selector);
        new ERC1967Proxy(address(impl), abi.encodeCall(ConfioHeartbeat.initialize, (address(0), beater, SILENCE)));
        vm.expectRevert(ConfioHeartbeat.ZeroAddress.selector);
        new ERC1967Proxy(address(impl), abi.encodeCall(ConfioHeartbeat.initialize, (safe, address(0), SILENCE)));
        vm.expectRevert(ConfioHeartbeat.SilenceTooShort.selector);
        new ERC1967Proxy(address(impl), abi.encodeCall(ConfioHeartbeat.initialize, (safe, beater, 1 hours)));
        vm.expectRevert(ConfioHeartbeat.SilenceTooLong.selector);
        new ERC1967Proxy(address(impl), abi.encodeCall(ConfioHeartbeat.initialize, (safe, beater, 365 days + 1)));
    }

    /// Audit P2: the bare implementation (and an uninitialized proxy) must
    /// never read as silent — bundling the wrong address would otherwise
    /// open every exit while Confío is alive.
    function test_UninitializedGateFailsClosed() public {
        ConfioHeartbeat impl = new ConfioHeartbeat();
        assertFalse(impl.isSilent());
        vm.expectRevert(ConfioHeartbeat.NotInitialized.selector);
        impl.assertSilent();
        // (An uninitialized proxy cannot exist: OZ 5.6 ERC1967Proxy reverts
        // ERC1967ProxyUninitialized when deployed without init data.)
    }

    function test_ExitThroughImplementationReverts() public {
        ConfioHeartbeat impl = new ConfioHeartbeat();
        ConfioBatchDelegate.Call[] memory calls = _exitBatch();
        calls[0].to = address(impl);
        vm.expectRevert(ConfioHeartbeat.NotInitialized.selector);
        _selfExecute(calls);
        assertEq(usdt.balanceOf(dest), 0);
    }

    function test_InitEmits() public {
        ConfioHeartbeat impl = new ConfioHeartbeat();
        vm.expectEmit(true, true, false, true);
        emit BeaterChanged(address(0), beater);
        vm.expectEmit(false, false, false, true);
        emit SilenceRequiredChanged(0, SILENCE);
        vm.expectEmit(false, false, false, true);
        emit Beat(uint64(block.timestamp));
        new ERC1967Proxy(address(impl), abi.encodeCall(ConfioHeartbeat.initialize, (safe, beater, SILENCE)));
    }

    // ── liveness ────────────────────────────────────────────────────────

    function test_SilenceBoundaryIsExact() public {
        uint256 opens = hb.opensAt();
        vm.warp(opens - 1);
        vm.expectRevert(abi.encodeWithSelector(ConfioHeartbeat.ConfioAlive.selector, opens));
        hb.assertSilent();

        vm.warp(opens);
        hb.assertSilent(); // does not revert
        assertTrue(hb.isSilent());
    }

    function test_BeatResetsTheClock() public {
        vm.warp(block.timestamp + SILENCE - 1);
        vm.expectEmit(false, false, false, true);
        emit Beat(uint64(block.timestamp));
        vm.prank(beater);
        hb.beat();
        assertEq(hb.lastBeat(), block.timestamp);
        vm.warp(block.timestamp + SILENCE - 1);
        assertFalse(hb.isSilent());
    }

    function test_BeatAfterSilenceClosesTheExitAgain() public {
        vm.warp(block.timestamp + SILENCE);
        assertTrue(hb.isSilent());
        vm.prank(beater);
        hb.beat();
        assertFalse(hb.isSilent());
    }

    function test_OnlyBeaterCanBeat() public {
        vm.expectRevert(ConfioHeartbeat.NotBeater.selector);
        hb.beat();
        vm.prank(safe); // not even the owner
        vm.expectRevert(ConfioHeartbeat.NotBeater.selector);
        hb.beat();
    }

    // ── admin ───────────────────────────────────────────────────────────

    function test_OwnerRotatesBeater() public {
        address next = makeAddr("next");
        vm.expectEmit(true, true, false, true);
        emit BeaterChanged(beater, next);
        vm.prank(safe);
        hb.setBeater(next);
        vm.prank(beater);
        vm.expectRevert(ConfioHeartbeat.NotBeater.selector);
        hb.beat();
        vm.prank(next);
        hb.beat();
    }

    function test_SilenceRequiredBoundedAndOwnerOnly() public {
        vm.expectRevert(abi.encodeWithSelector(OwnableUpgradeable.OwnableUnauthorizedAccount.selector, address(this)));
        hb.setSilenceRequired(30 days);
        vm.startPrank(safe);
        vm.expectRevert(ConfioHeartbeat.SilenceTooShort.selector);
        hb.setSilenceRequired(1 days - 1);
        vm.expectRevert(ConfioHeartbeat.SilenceTooLong.selector);
        hb.setSilenceRequired(365 days + 1);
        vm.expectEmit(false, false, false, true);
        emit SilenceRequiredChanged(SILENCE, 30 days);
        hb.setSilenceRequired(30 days);
        vm.stopPrank();
        assertEq(hb.opensAt(), uint256(hb.lastBeat()) + 30 days);
    }

    function test_SilenceChangeAppliesRetroactively() public {
        vm.warp(block.timestamp + SILENCE);
        assertTrue(hb.isSilent());
        vm.prank(safe);
        hb.setSilenceRequired(30 days); // raising re-closes an open gate
        assertFalse(hb.isSilent());
        vm.prank(safe);
        hb.setSilenceRequired(2 days); // lowering opens it at once
        assertTrue(hb.isSilent());
    }

    function test_OwnershipTwoStepHandoff() public {
        address next = makeAddr("nextSafe");
        vm.prank(safe);
        hb.transferOwnership(next);
        assertEq(hb.owner(), safe); // not until accepted
        vm.prank(next);
        hb.acceptOwnership();
        assertEq(hb.owner(), next);
        vm.prank(safe);
        vm.expectRevert(abi.encodeWithSelector(OwnableUpgradeable.OwnableUnauthorizedAccount.selector, safe));
        hb.setBeater(makeAddr("x"));
    }

    function test_AdminIsOwnerOnly() public {
        vm.expectRevert(abi.encodeWithSelector(OwnableUpgradeable.OwnableUnauthorizedAccount.selector, address(this)));
        hb.setBeater(address(this));
        vm.prank(safe);
        vm.expectRevert(ConfioHeartbeat.ZeroAddress.selector);
        hb.setBeater(address(0));
    }

    function test_RenounceDisabled() public {
        vm.prank(safe);
        vm.expectRevert("renounce disabled");
        hb.renounceOwnership();
    }

    function test_UpgradeOwnerOnlyAndPreservesState() public {
        vm.warp(block.timestamp + 3 days);
        vm.prank(beater);
        hb.beat();
        uint64 beatAt = hb.lastBeat();

        ConfioHeartbeatV2 v2 = new ConfioHeartbeatV2();
        vm.expectRevert(abi.encodeWithSelector(OwnableUpgradeable.OwnableUnauthorizedAccount.selector, address(this)));
        hb.upgradeToAndCall(address(v2), "");

        vm.prank(safe);
        hb.upgradeToAndCall(address(v2), "");
        assertEq(ConfioHeartbeatV2(address(hb)).version(), 2);
        assertEq(hb.lastBeat(), beatAt);
        assertEq(hb.beater(), beater);
        assertEq(hb.silenceRequired(), SILENCE);
        assertEq(hb.owner(), safe);
    }

    // ── exit batch through the 7702 delegate ────────────────────────────

    function _exitBatch() internal view returns (ConfioBatchDelegate.Call[] memory calls) {
        calls = new ConfioBatchDelegate.Call[](2);
        calls[0] = ConfioBatchDelegate.Call(address(hb), 0, abi.encodeCall(ConfioHeartbeat.assertSilent, ()));
        calls[1] = ConfioBatchDelegate.Call(address(usdt), 0, abi.encodeCall(usdt.transfer, (dest, 500e18)));
    }

    function _selfExecute(ConfioBatchDelegate.Call[] memory calls) internal {
        // Self-signed tx: the EOA calls its own delegated code.
        vm.prank(user);
        ConfioBatchDelegate(payable(user)).execute(calls, 0, 0, bytes32(0), "");
    }

    function test_ExitRevertsAtomicallyWhileAlive() public {
        vm.warp(hb.opensAt() - 1);
        ConfioBatchDelegate.Call[] memory calls = _exitBatch();
        vm.expectRevert(abi.encodeWithSelector(ConfioHeartbeat.ConfioAlive.selector, hb.opensAt()));
        _selfExecute(calls);
        assertEq(usdt.balanceOf(user), 500e18);
        assertEq(usdt.balanceOf(dest), 0);
    }

    function test_ExitSucceedsAfterSilence() public {
        vm.warp(hb.opensAt());
        _selfExecute(_exitBatch());
        assertEq(usdt.balanceOf(user), 0);
        assertEq(usdt.balanceOf(dest), 500e18);
    }

    function test_LateBeatBlocksAPendingExit() public {
        vm.warp(hb.opensAt());
        vm.prank(beater);
        hb.beat(); // Confío came back before the exit landed
        ConfioBatchDelegate.Call[] memory calls = _exitBatch();
        vm.expectRevert(abi.encodeWithSelector(ConfioHeartbeat.ConfioAlive.selector, hb.opensAt()));
        _selfExecute(calls);
        assertEq(usdt.balanceOf(dest), 0);
    }

    function test_ExitRelayedWithSignatureIsGatedToo() public {
        ConfioBatchDelegate.Call[] memory calls = _exitBatch();
        uint256 deadline = hb.opensAt() + 1 days;
        bytes32 digest = ConfioBatchDelegate(payable(user)).hashExecute(calls, 0, deadline, bytes32(0));
        (uint8 v, bytes32 r, bytes32 s_) = vm.sign(userPk, digest);
        bytes memory sig = abi.encodePacked(r, s_, v);
        address relayer = makeAddr("relayer");

        vm.warp(hb.opensAt() - 1);
        vm.prank(relayer);
        vm.expectRevert(abi.encodeWithSelector(ConfioHeartbeat.ConfioAlive.selector, hb.opensAt()));
        ConfioBatchDelegate(payable(user)).execute(calls, 0, deadline, bytes32(0), sig);

        vm.warp(hb.opensAt());
        vm.prank(relayer);
        ConfioBatchDelegate(payable(user)).execute(calls, 0, deadline, bytes32(0), sig);
        assertEq(usdt.balanceOf(dest), 500e18);
    }

    function test_UpgradeDroppingTheGateRevertsExits() public {
        NoGate ng = new NoGate();
        vm.prank(safe);
        hb.upgradeToAndCall(address(ng), "");
        vm.warp(block.timestamp + 400 days);
        ConfioBatchDelegate.Call[] memory calls = _exitBatch();
        vm.expectRevert(abi.encodeWithSelector(ConfioBatchDelegate.CallFailed.selector, 0));
        _selfExecute(calls);
        assertEq(usdt.balanceOf(dest), 0);
    }

    function testFuzz_GateAnySilenceAndBeats(uint64 silence, uint32 beatGap, uint64 elapsed) public {
        silence = uint64(bound(silence, 1 days, 365 days));
        beatGap = uint32(bound(beatGap, 0, 400 days));
        elapsed = uint64(bound(elapsed, 0, 800 days));
        vm.prank(safe);
        hb.setSilenceRequired(silence);
        vm.warp(block.timestamp + beatGap);
        vm.prank(beater);
        hb.beat();
        uint256 beatAt = block.timestamp;
        vm.warp(beatAt + elapsed);
        assertEq(hb.isSilent(), elapsed >= silence);
        if (elapsed < silence) {
            vm.expectRevert(abi.encodeWithSelector(ConfioHeartbeat.ConfioAlive.selector, beatAt + silence));
        }
        hb.assertSilent();
    }

    function testFuzz_GateMatchesChainTime(uint64 elapsed) public {
        elapsed = uint64(bound(elapsed, 0, 365 days));
        uint256 start = hb.lastBeat();
        vm.warp(start + elapsed);
        if (elapsed < SILENCE) {
            vm.expectRevert(abi.encodeWithSelector(ConfioHeartbeat.ConfioAlive.selector, start + SILENCE));
        }
        hb.assertSilent();
    }
}
