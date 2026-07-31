// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ConfioRewardVault} from "../ConfioRewardVault.sol";

contract MockConfio is ERC20 {
    constructor() ERC20("Confio", "CONFIO") {}
    function mint(address to, uint256 amt) external { _mint(to, amt); }
}

contract ConfioRewardVaultTest is Test {
    MockConfio confio;
    ConfioRewardVault vault;

    address safeOwner = makeAddr("safeOwner");
    uint256 signerKey = 0x51617E; // backend signer
    address signer;
    address user;
    address stranger = makeAddr("stranger");

    // NB: _sig() makes an external staticcall (claimDigest), so every test
    // computes its signature on its OWN line BEFORE any vm.prank/expectRevert
    // — otherwise the cheatcode latches onto the digest call, not the claim.
    function setUp() public {
        signer = vm.addr(signerKey);
        user = makeAddr("user");
        confio = new MockConfio();
        vault = new ConfioRewardVault(address(confio), signer, safeOwner);
        confio.mint(address(vault), 1_000_000e18); // treasury funds a tranche
    }

    function _sig(address who, uint256 cumulative, uint256 deadline, uint256 key)
        internal
        view
        returns (bytes memory)
    {
        (uint8 v, bytes32 r, bytes32 s) =
            vm.sign(key, vault.claimDigest(who, cumulative, deadline));
        return abi.encodePacked(r, s, v);
    }

    function _unlock() internal {
        vm.prank(safeOwner);
        vault.unlockClaims();
    }

    // ── Lock gate ────────────────────────────────────────────────────

    function test_claim_locked_before_dex() public {
        uint256 dl = block.timestamp + 1 hours;
        bytes memory sig = _sig(user, 100e18, dl, signerKey);
        vm.prank(user);
        vm.expectRevert("claims locked");
        vault.claim(100e18, dl, sig);
    }

    function test_unlock_is_one_way_and_owner_only() public {
        vm.prank(stranger);
        vm.expectRevert();
        vault.unlockClaims();

        _unlock();
        assertTrue(vault.claimsUnlocked());

        vm.prank(safeOwner);
        vm.expectRevert("already unlocked");
        vault.unlockClaims();
    }

    // ── Signed claim ─────────────────────────────────────────────────

    function test_claim_pays_signed_cumulative() public {
        _unlock();
        uint256 dl = block.timestamp + 1 hours;
        bytes memory sig = _sig(user, 100e18, dl, signerKey);
        vm.prank(user);
        uint256 paid = vault.claim(100e18, dl, sig);
        assertEq(paid, 100e18);
        assertEq(confio.balanceOf(user), 100e18);
        assertEq(vault.claimed(user), 100e18);
        assertEq(vault.totalClaimed(), 100e18);
    }

    function test_cumulative_pays_only_the_delta() public {
        _unlock();
        uint256 dl = block.timestamp + 1 hours;
        bytes memory sig1 = _sig(user, 100e18, dl, signerKey);
        bytes memory sig2 = _sig(user, 150e18, dl, signerKey);
        vm.startPrank(user);
        vault.claim(100e18, dl, sig1);
        uint256 paid2 = vault.claim(150e18, dl, sig2); // earned more later
        vm.stopPrank();
        assertEq(paid2, 50e18);
        assertEq(confio.balanceOf(user), 150e18);
        assertEq(vault.claimed(user), 150e18);
    }

    function test_resubmitting_same_signature_reverts() public {
        _unlock();
        uint256 dl = block.timestamp + 1 hours;
        bytes memory sig = _sig(user, 100e18, dl, signerKey);
        vm.startPrank(user);
        vault.claim(100e18, dl, sig);
        vm.expectRevert("nothing to claim"); // claimed == cumulative now
        vault.claim(100e18, dl, sig);
        vm.stopPrank();
    }

    function test_lower_cumulative_reverts() public {
        _unlock();
        uint256 dl = block.timestamp + 1 hours;
        bytes memory sig1 = _sig(user, 100e18, dl, signerKey);
        bytes memory sigLow = _sig(user, 80e18, dl, signerKey);
        vm.startPrank(user);
        vault.claim(100e18, dl, sig1);
        vm.expectRevert("nothing to claim");
        vault.claim(80e18, dl, sigLow); // stale/lower
        vm.stopPrank();
    }

    function test_wrong_signer_rejected() public {
        _unlock();
        uint256 dl = block.timestamp + 1 hours;
        bytes memory badSig = _sig(user, 100e18, dl, 0xBAD5); // not the signer
        vm.prank(user);
        vm.expectRevert("bad signature");
        vault.claim(100e18, dl, badSig);
    }

    function test_cannot_claim_someone_elses_signature() public {
        _unlock();
        uint256 dl = block.timestamp + 1 hours;
        // Signature is bound to `user`; the digest recovers over msg.sender,
        // so a different caller yields a different digest → not the signer.
        bytes memory sig = _sig(user, 100e18, dl, signerKey);
        vm.prank(stranger);
        vm.expectRevert("bad signature");
        vault.claim(100e18, dl, sig);
    }

    function test_expired_signature_rejected() public {
        _unlock();
        uint256 dl = block.timestamp + 1 hours;
        bytes memory sig = _sig(user, 100e18, dl, signerKey);
        vm.warp(block.timestamp + 2 hours);
        vm.prank(user);
        vm.expectRevert("expired");
        vault.claim(100e18, dl, sig);
    }

    function test_claim_reverts_if_vault_underfunded() public {
        _unlock();
        uint256 dl = block.timestamp + 1 hours;
        bytes memory sig = _sig(user, 100e18, dl, signerKey);
        vm.prank(safeOwner);
        vault.withdraw(safeOwner, 1_000_000e18); // drain the pool
        vm.prank(user);
        vm.expectRevert(); // ERC20 insufficient balance
        vault.claim(100e18, dl, sig);
    }

    // ── Admin ────────────────────────────────────────────────────────

    function test_signer_rotation() public {
        _unlock();
        uint256 newKey = 0x51E2;
        address newSigner = vm.addr(newKey);

        vm.prank(stranger);
        vm.expectRevert();
        vault.setSigner(newSigner);

        vm.prank(safeOwner);
        vault.setSigner(newSigner);
        assertEq(vault.signer(), newSigner);

        uint256 dl = block.timestamp + 1 hours;
        bytes memory oldSig = _sig(user, 100e18, dl, signerKey);
        bytes memory newSig = _sig(user, 100e18, dl, newKey);
        vm.startPrank(user);
        vm.expectRevert("bad signature");
        vault.claim(100e18, dl, oldSig); // old signer no longer valid
        vault.claim(100e18, dl, newSig);
        vm.stopPrank();
        assertEq(confio.balanceOf(user), 100e18);
    }

    function test_pause_blocks_claims_withdraw_open() public {
        _unlock();
        uint256 dl = block.timestamp + 1 hours;
        bytes memory sig = _sig(user, 100e18, dl, signerKey);
        vm.prank(safeOwner);
        vault.pause();
        vm.prank(user);
        vm.expectRevert();
        vault.claim(100e18, dl, sig);
        // Fund management still works while paused.
        vm.prank(safeOwner);
        vault.withdraw(safeOwner, 1e18);
    }

    function test_withdraw_owner_only() public {
        vm.prank(stranger);
        vm.expectRevert();
        vault.withdraw(stranger, 1e18);
    }

    function test_renounce_disabled() public {
        vm.prank(safeOwner);
        vm.expectRevert("renounce disabled");
        vault.renounceOwnership();
        assertEq(vault.owner(), safeOwner);
    }
}
