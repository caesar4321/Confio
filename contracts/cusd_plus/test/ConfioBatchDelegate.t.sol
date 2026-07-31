// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * Unit suite for the EIP-7702 sponsored-batch delegate.
 *
 * Delegation is modeled with `vm.etch(user, runtimeCode)`: identical to a
 * 7702 designation from this contract's point of view (code executing with
 * address(this) == the EOA). The designation mechanics themselves
 * (0xef0100 pointer, authorization tuples) are protocol-level and are
 * exercised by the client/server signing validators, not here — the pinned
 * solc 0.8.26 predates the `prague` target `vm.attachDelegation` needs.
 */
import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ConfioBatchDelegate} from "../ConfioBatchDelegate.sol";
import {MockToken} from "./CusdPlusVault.t.sol";

/// Emulates the vault's approve+pull pattern (subscribeAndMint).
contract PullSink {
    function pull(address token, address from, uint256 amount) external {
        IERC20(token).transferFrom(from, address(this), amount);
    }

    function alwaysReverts() external pure {
        revert("sink: nope");
    }

    // Reverts with NO returndata (plain assert-style failure).
    function silentRevert() external pure {
        assembly {
            revert(0, 0)
        }
    }
}

/// Malicious call target that reenters execute() with a pre-armed intent.
contract Reenterer {
    address public eoa;
    bytes public armedCalldata;

    function arm(address _eoa, bytes calldata _calldata) external {
        eoa = _eoa;
        armedCalldata = _calldata;
    }

    function hit() external {
        (bool ok, bytes memory ret) = eoa.call(armedCalldata);
        if (!ok) {
            assembly {
                revert(add(ret, 0x20), mload(ret))
            }
        }
    }
}

contract ConfioBatchDelegateTest is Test {
    bytes32 constant STORAGE_SLOT =
        0x90a10e3e6e0ef9c0307c0baf881893473293514cc333083b3696b5a0aa5eb100;
    bytes32 constant CALL_TYPEHASH = keccak256("Call(address to,uint256 value,bytes data)");
    bytes32 constant EXECUTE_TYPEHASH = keccak256(
        "Execute(Call[] calls,uint256 nonce,uint256 deadline,bytes32 intentId)Call(address to,uint256 value,bytes data)"
    );
    // A fixed intentId for the behavior tests (the delegate treats it as an
    // opaque binding value); the shared-vector test pins bytes32(0).
    bytes32 constant INTENT = keccak256("test-intent");
    bytes32 constant DOMAIN_TYPEHASH = keccak256(
        "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    );

    ConfioBatchDelegate delegate;
    MockToken usdt;
    PullSink sink;

    uint256 userPk;
    address user; // the "delegated EOA"
    address sponsor = makeAddr("sponsor");

    event BatchExecuted(uint256 indexed nonce, uint256 numCalls);

    function setUp() public {
        delegate = new ConfioBatchDelegate();
        usdt = new MockToken("USDT");
        sink = new PullSink();

        (user, userPk) = makeAddrAndKey("user");
        vm.etch(user, address(delegate).code); // model the 7702 designation
        usdt.mint(user, 1_000e18);
    }

    // ── helpers ──────────────────────────────────────────────────────────

    function _asDelegate(address eoa) internal pure returns (ConfioBatchDelegate) {
        return ConfioBatchDelegate(payable(eoa));
    }

    /// Independent EIP-712 implementation (parity check vs hashExecute).
    /// The 4-arg overload uses INTENT so the behavior tests read unchanged.
    function _digest(
        address eoa,
        ConfioBatchDelegate.Call[] memory calls,
        uint256 nonce,
        uint256 deadline
    ) internal view returns (bytes32) {
        return _digest(eoa, calls, nonce, deadline, INTENT);
    }

    function _digest(
        address eoa,
        ConfioBatchDelegate.Call[] memory calls,
        uint256 nonce,
        uint256 deadline,
        bytes32 intentId
    ) internal view returns (bytes32) {
        bytes32[] memory hashes = new bytes32[](calls.length);
        for (uint256 i; i < calls.length; ++i) {
            hashes[i] = keccak256(
                abi.encode(CALL_TYPEHASH, calls[i].to, calls[i].value, keccak256(calls[i].data))
            );
        }
        bytes32 ds = keccak256(
            abi.encode(
                DOMAIN_TYPEHASH,
                keccak256(bytes("ConfioBatchDelegate")),
                keccak256(bytes("1")),
                block.chainid,
                eoa
            )
        );
        bytes32 sh = keccak256(
            abi.encode(EXECUTE_TYPEHASH, keccak256(abi.encodePacked(hashes)), nonce, deadline, intentId)
        );
        return keccak256(abi.encodePacked(hex"1901", ds, sh));
    }

    function _sign(uint256 pk, bytes32 digest) internal pure returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(pk, digest);
        return abi.encodePacked(r, s, v);
    }

    /// The canonical deposit-shaped batch: approve + pull.
    function _depositBatch(uint256 amount)
        internal
        view
        returns (ConfioBatchDelegate.Call[] memory calls)
    {
        calls = new ConfioBatchDelegate.Call[](2);
        calls[0] = ConfioBatchDelegate.Call(
            address(usdt), 0, abi.encodeCall(IERC20.approve, (address(sink), amount))
        );
        calls[1] = ConfioBatchDelegate.Call(
            address(sink), 0, abi.encodeCall(PullSink.pull, (address(usdt), user, amount))
        );
    }

    // ── core behavior ────────────────────────────────────────────────────

    function test_sponsorExecutesSignedBatch() public {
        ConfioBatchDelegate.Call[] memory calls = _depositBatch(100e18);
        bytes memory sig = _sign(userPk, _digest(user, calls, 0, block.timestamp + 600));

        vm.expectEmit(true, false, false, true, user);
        emit BatchExecuted(0, 2);

        vm.prank(sponsor);
        _asDelegate(user).execute(calls, 0, block.timestamp + 600, INTENT, sig);

        assertEq(usdt.balanceOf(address(sink)), 100e18, "sink pulled the funds");
        assertEq(usdt.balanceOf(user), 900e18);
        assertEq(_asDelegate(user).nonces(), 1, "nonce consumed");
    }

    function test_digestParity_localVsOnchain() public view {
        ConfioBatchDelegate.Call[] memory calls = _depositBatch(42e18);
        assertEq(
            _asDelegate(user).hashExecute(calls, 3, 12345, INTENT),
            _digest(user, calls, 3, 12345),
            "hashExecute must match the independent implementation"
        );
    }

    /// Cross-stack anchor: same constant is asserted by the Python policy
    /// tests and the ethers-v6 validator script. Never change one alone.
    function test_sharedEip712Vector() public {
        address eoa = address(0xAA);
        vm.etch(eoa, address(delegate).code);
        vm.chainId(56);

        ConfioBatchDelegate.Call[] memory calls = new ConfioBatchDelegate.Call[](2);
        calls[0] = ConfioBatchDelegate.Call(
            0x1111111111111111111111111111111111111111, 0, hex"deadbeef"
        );
        calls[1] = ConfioBatchDelegate.Call(
            0x2222222222222222222222222222222222222222, 1_000_000, ""
        );
        assertEq(
            _asDelegate(eoa).hashExecute(calls, 7, 1_900_000_000, bytes32(0)),
            0xf955b9171a0a662c24b602836539fb8a7bdd57272ea2aed94e41917ebd2bd2d2,
            "shared vector drifted"
        );
    }

    // ── rejections ───────────────────────────────────────────────────────

    function test_replayRejected() public {
        ConfioBatchDelegate.Call[] memory calls = _depositBatch(10e18);
        uint256 deadline = block.timestamp + 600;
        bytes memory sig = _sign(userPk, _digest(user, calls, 0, deadline));

        vm.prank(sponsor);
        _asDelegate(user).execute(calls, 0, deadline, INTENT, sig);

        vm.prank(sponsor);
        vm.expectRevert(ConfioBatchDelegate.BadNonce.selector);
        _asDelegate(user).execute(calls, 0, deadline, INTENT, sig);
    }

    function test_expiredRejected() public {
        ConfioBatchDelegate.Call[] memory calls = _depositBatch(10e18);
        uint256 deadline = block.timestamp + 600;
        bytes memory sig = _sign(userPk, _digest(user, calls, 0, deadline));

        vm.warp(deadline + 1);
        vm.prank(sponsor);
        vm.expectRevert(ConfioBatchDelegate.Expired.selector);
        _asDelegate(user).execute(calls, 0, deadline, INTENT, sig);
    }

    function test_wrongKeyRejected() public {
        ConfioBatchDelegate.Call[] memory calls = _depositBatch(10e18);
        uint256 deadline = block.timestamp + 600;
        (, uint256 malloryPk) = makeAddrAndKey("mallory");
        bytes memory sig = _sign(malloryPk, _digest(user, calls, 0, deadline));

        vm.prank(sponsor);
        vm.expectRevert(ConfioBatchDelegate.BadSignature.selector);
        _asDelegate(user).execute(calls, 0, deadline, INTENT, sig);
    }

    function test_tamperedBatchRejected() public {
        ConfioBatchDelegate.Call[] memory calls = _depositBatch(10e18);
        uint256 deadline = block.timestamp + 600;
        bytes memory sig = _sign(userPk, _digest(user, calls, 0, deadline));

        // Sponsor tries to inflate the pull after the user signed.
        ConfioBatchDelegate.Call[] memory tampered = _depositBatch(999e18);
        vm.prank(sponsor);
        vm.expectRevert(ConfioBatchDelegate.BadSignature.selector);
        _asDelegate(user).execute(tampered, 0, deadline, INTENT, sig);
    }

    function test_emptyBatchRejected() public {
        ConfioBatchDelegate.Call[] memory calls = new ConfioBatchDelegate.Call[](0);
        vm.prank(sponsor);
        vm.expectRevert(ConfioBatchDelegate.EmptyBatch.selector);
        _asDelegate(user).execute(calls, 0, block.timestamp + 600, INTENT, "");
    }

    // ── atomicity & failure surfacing ────────────────────────────────────

    function test_atomicity_innerRevertRollsBackEverything() public {
        ConfioBatchDelegate.Call[] memory calls = new ConfioBatchDelegate.Call[](2);
        calls[0] = ConfioBatchDelegate.Call(
            address(usdt), 0, abi.encodeCall(IERC20.approve, (address(sink), 50e18))
        );
        calls[1] =
            ConfioBatchDelegate.Call(address(sink), 0, abi.encodeCall(PullSink.alwaysReverts, ()));
        bytes memory sig = _sign(userPk, _digest(user, calls, 0, block.timestamp + 600));

        vm.prank(sponsor);
        vm.expectRevert(bytes("sink: nope")); // inner revert data bubbles
        _asDelegate(user).execute(calls, 0, block.timestamp + 600, INTENT, sig);

        assertEq(usdt.allowance(user, address(sink)), 0, "approve rolled back");
        assertEq(_asDelegate(user).nonces(), 0, "nonce rolled back");
    }

    function test_silentInnerRevertGetsIndexedError() public {
        ConfioBatchDelegate.Call[] memory calls = new ConfioBatchDelegate.Call[](1);
        calls[0] =
            ConfioBatchDelegate.Call(address(sink), 0, abi.encodeCall(PullSink.silentRevert, ()));
        bytes memory sig = _sign(userPk, _digest(user, calls, 0, block.timestamp + 600));

        vm.prank(sponsor);
        vm.expectRevert(abi.encodeWithSelector(ConfioBatchDelegate.CallFailed.selector, 0));
        _asDelegate(user).execute(calls, 0, block.timestamp + 600, INTENT, sig);
    }

    // ── self-call path ───────────────────────────────────────────────────

    function test_selfCallSkipsSignature() public {
        ConfioBatchDelegate.Call[] memory calls = _depositBatch(25e18);
        vm.prank(user); // the EOA's own key sent a normal tx to itself
        _asDelegate(user).execute(calls, 999, 0, INTENT, ""); // nonce/deadline/sig ignored
        assertEq(usdt.balanceOf(address(sink)), 25e18);
        assertEq(_asDelegate(user).nonces(), 1, "self-call still consumes a nonce");
    }

    function test_selfCallInvalidatesOutstandingIntent() public {
        ConfioBatchDelegate.Call[] memory calls = _depositBatch(10e18);
        uint256 deadline = block.timestamp + 600;
        bytes memory sig = _sign(userPk, _digest(user, calls, 0, deadline));

        vm.prank(user);
        _asDelegate(user).execute(_depositBatch(1e18), 0, 0, INTENT, "");

        vm.prank(sponsor);
        vm.expectRevert(ConfioBatchDelegate.BadNonce.selector);
        _asDelegate(user).execute(calls, 0, deadline, INTENT, sig);
    }

    // ── EOA behavior preservation ────────────────────────────────────────

    function test_plainBnbTransferStillWorks() public {
        vm.deal(sponsor, 2 ether);
        vm.prank(sponsor);
        (bool ok,) = user.call{value: 1 ether}("");
        assertTrue(ok, "receive() accepts bare value");
        assertEq(user.balance, 1 ether);

        // Value with junk calldata lands in fallback(), like a bare EOA.
        vm.prank(sponsor);
        (ok,) = user.call{value: 0.5 ether}(hex"12345678");
        assertTrue(ok, "fallback tolerates unknown calldata");
        assertEq(user.balance, 1.5 ether);
    }

    function test_valueForwardingFromEoaBalance() public {
        vm.deal(user, 3 ether);
        address payee = makeAddr("payee");

        ConfioBatchDelegate.Call[] memory calls = new ConfioBatchDelegate.Call[](1);
        calls[0] = ConfioBatchDelegate.Call(payee, 1 ether, "");
        bytes memory sig = _sign(userPk, _digest(user, calls, 0, block.timestamp + 600));

        vm.prank(sponsor);
        _asDelegate(user).execute(calls, 0, block.timestamp + 600, INTENT, sig);
        assertEq(payee.balance, 1 ether, "EOA value forwarded only under user signature");
        assertEq(user.balance, 2 ether);
    }

    // ── reentrancy ───────────────────────────────────────────────────────

    function test_reentrancyBlocked() public {
        Reenterer evil = new Reenterer();

        // Arm a perfectly valid, correctly signed intent for the NEXT nonce…
        ConfioBatchDelegate.Call[] memory inner = _depositBatch(5e18);
        uint256 deadline = block.timestamp + 600;
        bytes memory innerSig = _sign(userPk, _digest(user, inner, 1, deadline));
        evil.arm(
            user,
            abi.encodeCall(ConfioBatchDelegate.execute, (inner, 1, deadline, INTENT, innerSig))
        );

        // …and try to run it from inside a batch. Transient guard stops it.
        ConfioBatchDelegate.Call[] memory outer = new ConfioBatchDelegate.Call[](1);
        outer[0] = ConfioBatchDelegate.Call(address(evil), 0, abi.encodeCall(Reenterer.hit, ()));
        bytes memory outerSig = _sign(userPk, _digest(user, outer, 0, deadline));

        vm.prank(sponsor);
        vm.expectRevert(); // ReentrancyGuardReentrantCall, bubbled
        _asDelegate(user).execute(outer, 0, deadline, INTENT, outerSig);
    }

    // ── storage discipline ───────────────────────────────────────────────

    function test_storageStaysInNamespacedSlot() public {
        // The constant matches the ERC-7201 formula.
        bytes32 expected = keccak256(
            abi.encode(uint256(keccak256("confio.storage.BatchDelegate")) - 1)
        ) & ~bytes32(uint256(0xff));
        assertEq(STORAGE_SLOT, expected, "ERC-7201 slot formula");

        ConfioBatchDelegate.Call[] memory calls = _depositBatch(10e18);
        bytes memory sig = _sign(userPk, _digest(user, calls, 0, block.timestamp + 600));
        vm.prank(sponsor);
        _asDelegate(user).execute(calls, 0, block.timestamp + 600, INTENT, sig);

        assertEq(uint256(vm.load(user, STORAGE_SLOT)), 1, "nonce lives in the namespaced slot");
        assertEq(uint256(vm.load(user, bytes32(0))), 0, "slot 0 untouched");
    }

    // ── fuzz: signature binds every field ────────────────────────────────

    function testFuzz_digestBindsFields(
        address to,
        uint256 value,
        bytes memory data,
        uint256 nonce,
        uint256 deadline
    ) public view {
        ConfioBatchDelegate.Call[] memory calls = new ConfioBatchDelegate.Call[](1);
        calls[0] = ConfioBatchDelegate.Call(to, value, data);
        bytes32 base = _asDelegate(user).hashExecute(calls, nonce, deadline, INTENT);
        assertEq(base, _digest(user, calls, nonce, deadline));

        // Any nonce/deadline drift changes the digest.
        if (deadline < type(uint256).max) {
            assertTrue(base != _asDelegate(user).hashExecute(calls, nonce, deadline + 1, INTENT));
        }
        if (nonce < type(uint256).max) {
            assertTrue(base != _asDelegate(user).hashExecute(calls, nonce + 1, deadline, INTENT));
        }
    }
}
