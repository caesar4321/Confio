// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {StdInvariant} from "forge-std/StdInvariant.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ConfioToken} from "../ConfioToken.sol";
import {ConfioPresaleVault} from "../ConfioPresaleVault.sol";

contract PresaleAuditPayment is ERC20 {
    constructor() ERC20("audit cUSD", "cUSD") {}
    function mint(address to, uint256 amount) external { _mint(to, amount); }
}

contract ConfioPresaleAuditHandler is Test {
    ConfioToken public token;
    PresaleAuditPayment public payment;
    ConfioPresaleVault public vault;
    address[6] public buyers;
    uint256 public funded;
    uint256 public swept;
    uint256 public paymentSwept;
    uint256 public paid;

    constructor() {
        token = new ConfioToken(address(this));
        payment = new PresaleAuditPayment();
        uint256[] memory b = new uint256[](3);
        (b[0], b[1], b[2]) = (4_000_000e18, 24_000_000e18, 74_000_000e18);
        uint256[] memory p = new uint256[](4);
        (p[0], p[1], p[2], p[3]) = (0.2e18, 0.3e18, 0.7e18, 1.3e18);
        vault = new ConfioPresaleVault(address(this), IERC20(address(payment)), b, p,
            18_000e18, 0, 17_000e18, 1_000e18, address(this));
        vault.setConfioToken(IERC20(address(token)));
        token.transfer(address(vault), 74_000_000e18);
        funded = 74_000_000e18;
        for (uint256 i; i < 6; ++i) {
            buyers[i] = address(uint160(0x20000 + i));
            payment.mint(buyers[i], 100_000_000e18);
            vm.prank(buyers[i]); payment.approve(address(vault), type(uint256).max);
        }
    }

    function _topUp(uint256 needed) internal {
        uint256 held = token.balanceOf(address(vault));
        if (held < needed) {
            funded += needed - held;
            token.transfer(address(vault), needed - held);
        }
    }

    function buy(uint8 who, uint128 seed) external {
        uint256 left = vault.remainingTokens();
        if (left == 0 || vault.paused()) return;
        uint256 amount = bound(seed, 1, left);
        // Mirror the proposed fully funded operation even before unlock.
        _topUp(vault.totalSold() - vault.totalClaimed() + amount);
        vm.prank(buyers[who % 6], address(this));
        vault.buy(amount, type(uint256).max);
    }

    function credit(uint8 who, uint128 seed, bool legacy) external {
        uint256 pool = legacy ? vault.legacyPool() : vault.migratedPool();
        if (pool == 0) return;
        address[] memory targets = new address[](1);
        uint256[] memory amounts = new uint256[](1);
        targets[0] = buyers[who % 6];
        amounts[0] = bound(seed, 1, pool);
        if (legacy) vault.creditLegacy(targets, amounts);
        else vault.creditMigrated(targets, amounts);
    }

    function uncredit(uint8 who, uint128 seed) external {
        address buyer = buyers[who % 6];
        uint256 available = vault.migratedCredited(buyer);
        if (available == 0) return;
        vault.uncreditMigrated(buyer, bound(seed, 1, available));
    }

    function expand(uint128 seed) external {
        uint256 left = vault.remainingTokens();
        if (left == 0) return;
        uint256 amount = bound(seed, 1, left);
        _topUp(vault.totalSold() - vault.totalClaimed() + amount);
        vault.expandMigratedPool(amount);
    }

    function claim(uint8 who) external {
        address buyer = buyers[who % 6];
        if (!vault.claimsUnlocked() || vault.claimableOf(buyer) == 0) return;
        vm.prank(buyer); paid += vault.claim();
    }

    function unlock() external {
        if (vault.claimsUnlocked()) return;
        vault.unlockClaims();
    }

    function togglePause() external {
        if (vault.paused()) vault.unpause();
        else vault.pause();
    }

    function sweep(uint128 seed) external {
        uint256 excess = token.balanceOf(address(vault)) - (vault.totalSold() - vault.totalClaimed());
        if (excess == 0) return;
        uint256 amount = bound(seed, 1, excess);
        swept += amount;
        vault.sweepExcessConfio(address(this), amount);
    }

    function sweepPayment(uint128 seed) external {
        uint256 balance = payment.balanceOf(address(vault));
        if (balance == 0) return;
        uint256 amount = bound(seed, 1, balance);
        paymentSwept += amount;
        vault.sweepPayment(address(this), amount);
    }
}

contract ConfioPresaleInvariantTest is StdInvariant, Test {
    ConfioPresaleAuditHandler handler;
    ConfioPresaleVault vault;
    ConfioToken token;
    PresaleAuditPayment payment;

    function setUp() public {
        handler = new ConfioPresaleAuditHandler();
        vault = handler.vault(); token = handler.token(); payment = handler.payment();
        bytes4[] memory selectors = new bytes4[](9);
        selectors[0] = handler.buy.selector;
        selectors[1] = handler.credit.selector;
        selectors[2] = handler.uncredit.selector;
        selectors[3] = handler.expand.selector;
        selectors[4] = handler.claim.selector;
        selectors[5] = handler.unlock.selector;
        selectors[6] = handler.togglePause.selector;
        selectors[7] = handler.sweep.selector;
        selectors[8] = handler.sweepPayment.selector;
        targetSelector(FuzzSelector(address(handler), selectors));
        targetContract(address(handler));
    }

    function invariant_all_obligations_are_accounted_and_claims_conserve_tokens() public view {
        uint256 debt = vault.migratedPool() + vault.legacyPool();
        uint256 received;
        for (uint256 i; i < 6; ++i) {
            address buyer = handler.buyers(i);
            uint256 bought = vault.purchased(buyer);
            uint256 claimed = vault.claimed(buyer);
            assertLe(claimed, bought);
            assertLe(vault.migratedCredited(buyer), bought - claimed);
            debt += bought - claimed;
            received += token.balanceOf(buyer);
        }
        assertEq(vault.totalSold() - vault.totalClaimed(), debt);
        assertLe(vault.totalSold(), 74_000_000e18);
        uint256 balance = token.balanceOf(address(vault));
        assertGe(balance, debt);
        assertEq(balance + received + handler.swept(), handler.funded());
        assertEq(received, vault.totalClaimed());
        assertEq(received, handler.paid());
        assertEq(payment.balanceOf(address(vault)) + handler.paymentSwept(), vault.totalRaised());
        assertEq(received + balance + token.balanceOf(address(handler)), token.totalSupply());
    }
}
