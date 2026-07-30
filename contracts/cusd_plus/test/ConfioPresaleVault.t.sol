// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ConfioPresaleVault} from "../ConfioPresaleVault.sol";

contract MockToken is ERC20 {
    constructor(string memory name_) ERC20(name_, name_) {}

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}

contract ConfioPresaleVaultTest is Test {
    // Production curve "A": 0-4M @ 0.20→0.30, 4-24M @ 0.30→0.70,
    // 24-74M @ 0.70→1.30. Full sale = $61M.
    uint256 constant S = 74_000_000e18;
    uint256 constant FULL_RAISE = 61_000_000e18;

    MockToken payment;
    MockToken confio;
    ConfioPresaleVault vault;

    address owner = makeAddr("ownerSafe");
    address sponsor = makeAddr("sponsor");
    address user = makeAddr("user");
    address user2 = makeAddr("user2");
    address algoBuyer = makeAddr("algoBuyer");

    function _breaks() internal pure returns (uint256[] memory b) {
        b = new uint256[](3);
        b[0] = 4_000_000e18;
        b[1] = 24_000_000e18;
        b[2] = 74_000_000e18;
    }

    function _prices() internal pure returns (uint256[] memory p) {
        p = new uint256[](4);
        p[0] = 0.2e18;
        p[1] = 0.3e18;
        p[2] = 0.7e18;
        p[3] = 1.3e18;
    }

    function _newVault(uint256 initialSold) internal returns (ConfioPresaleVault) {
        return new ConfioPresaleVault(
            owner, IERC20(address(payment)), _breaks(), _prices(), initialSold, sponsor
        );
    }

    function setUp() public {
        payment = new MockToken("cUSD");
        confio = new MockToken("CONFIO");
        vault = _newVault(0);

        payment.mint(user, 100_000_000e18);
        payment.mint(user2, 100_000_000e18);
    }

    /// Sponsored buy exactly as production: user EOA is msg.sender (7702
    /// batch executes as the EOA), sponsor KMS wallet is tx.origin.
    function _sponsoredBuy(ConfioPresaleVault v, address buyer, uint256 q, uint256 cap)
        internal
        returns (uint256 cost)
    {
        vm.prank(buyer, sponsor);
        payment.approve(address(v), cap);
        vm.prank(buyer, sponsor);
        cost = v.buy(q, cap);
    }

    function _sponsoredBuy(address buyer, uint256 q, uint256 cap) internal returns (uint256) {
        return _sponsoredBuy(vault, buyer, q, cap);
    }

    // ------------------------------------------------------------------
    // Constructor
    // ------------------------------------------------------------------

    function test_constructor_validation() public {
        IERC20 pt = IERC20(address(payment));
        uint256[] memory b = _breaks();
        uint256[] memory p = _prices();

        // zero starting price
        uint256[] memory pBad = _prices();
        pBad[0] = 0;
        vm.expectRevert(ConfioPresaleVault.BadCurveParams.selector);
        new ConfioPresaleVault(owner, pt, b, pBad, 0, sponsor);

        // non-increasing prices (flat segment) rejected
        pBad = _prices();
        pBad[1] = pBad[0];
        vm.expectRevert(ConfioPresaleVault.BadCurveParams.selector);
        new ConfioPresaleVault(owner, pt, b, pBad, 0, sponsor);

        // non-increasing breakpoints rejected
        uint256[] memory bBad = _breaks();
        bBad[1] = bBad[0];
        vm.expectRevert(ConfioPresaleVault.BadCurveParams.selector);
        new ConfioPresaleVault(owner, pt, bBad, p, 0, sponsor);

        // length mismatch
        uint256[] memory pShort = new uint256[](3);
        (pShort[0], pShort[1], pShort[2]) = (p[0], p[1], p[2]);
        vm.expectRevert(ConfioPresaleVault.BadCurveParams.selector);
        new ConfioPresaleVault(owner, pt, b, pShort, 0, sponsor);

        // initialSold beyond supply
        vm.expectRevert(ConfioPresaleVault.ExceedsTokensForSale.selector);
        new ConfioPresaleVault(owner, pt, b, p, S + 1, sponsor);

        vm.expectRevert(ConfioPresaleVault.ZeroAddress.selector);
        new ConfioPresaleVault(owner, pt, b, p, 0, address(0));
        vm.expectRevert(ConfioPresaleVault.ZeroAddress.selector);
        new ConfioPresaleVault(owner, IERC20(address(0)), b, p, 0, sponsor);
    }

    // ------------------------------------------------------------------
    // Sponsor gating
    // ------------------------------------------------------------------

    function test_buy_reverts_without_sponsor_in_tx() public {
        vm.prank(user, user); // user submits their own tx: no sponsor anywhere
        vm.expectRevert(ConfioPresaleVault.NotSponsoredTransaction.selector);
        vault.buy(1e18, type(uint256).max);
    }

    function test_buy_allows_sponsor_as_origin() public {
        uint256 cost = _sponsoredBuy(user, 100e18, type(uint256).max);
        assertEq(vault.purchased(user), 100e18);
        assertEq(payment.balanceOf(address(vault)), cost);
        assertEq(vault.totalRaised(), cost);
    }

    function test_buy_allows_sponsor_as_direct_caller() public {
        payment.mint(sponsor, 1_000e18);
        vm.startPrank(sponsor, sponsor);
        payment.approve(address(vault), type(uint256).max);
        vault.buy(10e18, type(uint256).max);
        vm.stopPrank();
        assertEq(vault.purchased(sponsor), 10e18);
    }

    function test_sponsor_rotation() public {
        address newSponsor = makeAddr("newSponsor");
        vm.prank(owner);
        vault.setSponsor(newSponsor, true);
        vm.prank(owner);
        vault.setSponsor(sponsor, false);

        vm.prank(user, sponsor);
        vm.expectRevert(ConfioPresaleVault.NotSponsoredTransaction.selector);
        vault.buy(1e18, type(uint256).max);

        vm.prank(user, sponsor);
        payment.approve(address(vault), type(uint256).max);
        vm.prank(user, newSponsor);
        vault.buy(1e18, type(uint256).max);
        assertEq(vault.purchased(user), 1e18);
    }

    function test_setSponsor_only_owner() public {
        vm.prank(user);
        vm.expectRevert();
        vault.setSponsor(user, true);
    }

    // ------------------------------------------------------------------
    // Curve math — the three-line audit anyone can do by hand
    // ------------------------------------------------------------------

    function test_price_nodes() public view {
        assertEq(vault.currentPrice(), 0.2e18);
        assertEq(vault.priceAt(4_000_000e18), 0.3e18);
        assertEq(vault.priceAt(24_000_000e18), 0.7e18);
        assertEq(vault.priceAt(S), 1.3e18);
        // segment midpoints
        assertEq(vault.priceAt(2_000_000e18), 0.25e18);
        assertEq(vault.priceAt(14_000_000e18), 0.5e18);
        assertEq(vault.priceAt(49_000_000e18), 1e18);
    }

    function test_segment_raises_match_tokenomics() public view {
        // 4M × avg 0.25 = $1M ; 20M × avg 0.50 = $10M ; 50M × avg 1.00 = $50M
        assertApproxEqAbs(vault.quoteCost(4_000_000e18), 1_000_000e18, 3);
        assertApproxEqAbs(vault.quoteCost(24_000_000e18), 11_000_000e18, 3);
        assertApproxEqAbs(vault.quoteCost(S), FULL_RAISE, 3);
    }

    function test_full_sale_costs_61M() public {
        uint256 cost = _sponsoredBuy(user, S, type(uint256).max);
        assertApproxEqAbs(cost, FULL_RAISE, 3); // per-segment ceil, ≤1 unit each
        assertGe(cost, FULL_RAISE);
        assertEq(vault.currentPrice(), 1.3e18);
        assertEq(vault.remainingTokens(), 0);
        assertEq(vault.totalRaised(), cost);
    }

    function test_first_purchase_priced_near_floor() public {
        // 1000 CONFIO on a 74M sale barely moves the curve: cost ≈ 0.2 each.
        uint256 cost = _sponsoredBuy(user, 1000e18, type(uint256).max);
        assertApproxEqRel(cost, 200e18, 0.001e18); // within 0.1%
        assertGe(cost, 200e18); // never below the floor price
    }

    function test_cross_segment_buy_equals_sum_of_parts() public view {
        // 3M..5M straddles the first breakpoint
        uint256 upTo3M = vault.quoteCost(3_000_000e18);
        uint256 upTo5M = vault.quoteCost(5_000_000e18);
        // [0,3M] @ avg 0.2375 = 712.5K
        assertApproxEqAbs(upTo3M, 712_500e18, 3);
        // [3M,4M] @ avg 0.2875 = 287.5K ; [4M,5M] @ avg 0.31 = 310K → 597.5K
        assertApproxEqAbs(upTo5M - upTo3M, 597_500e18, 5);
    }

    function test_buy_beyond_sale_reverts() public {
        _sponsoredBuy(user, S - 5e18, type(uint256).max);
        vm.prank(user, sponsor);
        vm.expectRevert(ConfioPresaleVault.ExceedsTokensForSale.selector);
        vault.buy(6e18, type(uint256).max);
        // exact fill OK
        _sponsoredBuy(user, 5e18, type(uint256).max);
        assertEq(vault.totalSold(), S);
    }

    function test_maxPayment_slippage_guard() public {
        uint256 cost = vault.quoteCost(1000e18);
        vm.prank(user, sponsor);
        payment.approve(address(vault), type(uint256).max);
        vm.prank(user, sponsor);
        vm.expectRevert(
            abi.encodeWithSelector(ConfioPresaleVault.CostExceedsMaxPayment.selector, cost, cost - 1)
        );
        vault.buy(1000e18, cost - 1);
    }

    function test_zero_amount_reverts() public {
        vm.prank(user, sponsor);
        vm.expectRevert(ConfioPresaleVault.ZeroAmount.selector);
        vault.buy(0, 0);
    }

    /// Splitting a buy can never be cheaper than one shot (ceil rounding).
    function testFuzz_no_discount_by_splitting(uint128 a, uint128 b) public {
        uint256 qa = bound(uint256(a), 1, S / 2);
        uint256 qb = bound(uint256(b), 1, S - qa);
        uint256 oneShot = vault.quoteCost(qa + qb);
        uint256 c1 = _sponsoredBuy(user, qa, type(uint256).max);
        uint256 c2 = _sponsoredBuy(user, qb, type(uint256).max);
        assertGe(c1 + c2, oneShot);
        assertLe(c1 + c2, oneShot + 8); // ceil drift ≤ 1 unit per segment touched
    }

    /// quoteTokens is a safe inverse: buying its answer never costs more
    /// than the payment budget it was asked about.
    function testFuzz_quoteTokens_inverse(uint96 budget, uint128 presold) public {
        uint256 pre = bound(uint256(presold), 0, S - 1e18);
        if (pre > 0) _sponsoredBuy(user2, pre, type(uint256).max);
        uint256 c = bound(uint256(budget), 1e6, 70_000_000e18);
        uint256 q = vault.quoteTokens(c);
        assertLe(q, vault.remainingTokens());
        if (q == 0) return;
        uint256 cost = vault.quoteCost(q);
        assertLe(cost, c);
        // and the quote is tight: one more whole token would break the budget
        // (only meaningful when not clamped by remaining supply)
        if (q + 1e18 <= vault.remainingTokens()) {
            assertGt(vault.quoteCost(q + 1e18), c);
        }
    }

    // ------------------------------------------------------------------
    // Algorand migration: seed, credits, revocation
    // ------------------------------------------------------------------

    function test_initialSold_seeds_curve_and_pool() public {
        // Algorand Phase 1-1 sold e.g. 500K CONFIO at 0.20
        ConfioPresaleVault v = _newVault(500_000e18);
        assertEq(v.totalSold(), 500_000e18);
        assertEq(v.migratedPool(), 500_000e18);
        // curve continues where Algorand left off, not at 0.20
        assertEq(v.currentPrice(), 0.2e18 + (0.1e18 * 500_000) / 4_000_000);
        // supply cap accounts for the seed
        assertEq(v.remainingTokens(), S - 500_000e18);
    }

    function test_creditMigrated_lifecycle() public {
        ConfioPresaleVault v = _newVault(500_000e18);

        address[] memory buyers = new address[](2);
        uint256[] memory amounts = new uint256[](2);
        (buyers[0], buyers[1]) = (algoBuyer, user2);
        (amounts[0], amounts[1]) = (300_000e18, 100_000e18);

        vm.prank(owner);
        v.creditMigrated(buyers, amounts);
        assertEq(v.purchased(algoBuyer), 300_000e18);
        assertEq(v.migratedCredited(algoBuyer), 300_000e18);
        assertEq(v.migratedPool(), 100_000e18);
        // crediting does NOT move the curve (already counted at deploy)
        assertEq(v.totalSold(), 500_000e18);

        // pool is a hard bound
        (buyers, amounts) = (new address[](1), new uint256[](1));
        buyers[0] = algoBuyer;
        amounts[0] = 100_001e18;
        vm.prank(owner);
        vm.expectRevert(
            abi.encodeWithSelector(
                ConfioPresaleVault.ExceedsMigratedPool.selector, 100_001e18, 100_000e18
            )
        );
        v.creditMigrated(buyers, amounts);

        // only owner
        amounts[0] = 1e18;
        vm.prank(user);
        vm.expectRevert();
        v.creditMigrated(buyers, amounts);

        // credited allocation claims like any purchase
        vm.startPrank(owner);
        v.setConfioToken(IERC20(address(confio)));
        v.setClaimsUnlocked(true);
        vm.stopPrank();
        confio.mint(address(v), 400_000e18);
        vm.prank(algoBuyer);
        assertEq(v.claim(), 300_000e18);
        assertEq(confio.balanceOf(algoBuyer), 300_000e18);
    }

    function test_uncreditMigrated_only_reverses_credits_not_purchases() public {
        ConfioPresaleVault v = _newVault(500_000e18);

        // algoBuyer gets 200K credit AND buys 50K with real money
        address[] memory buyers = new address[](1);
        uint256[] memory amounts = new uint256[](1);
        buyers[0] = algoBuyer;
        amounts[0] = 200_000e18;
        vm.prank(owner);
        v.creditMigrated(buyers, amounts);
        payment.mint(algoBuyer, 1_000_000e18);
        _sponsoredBuy(v, algoBuyer, 50_000e18, type(uint256).max);
        assertEq(v.purchased(algoBuyer), 250_000e18);

        // cannot claw back more than the migrated portion
        vm.prank(owner);
        vm.expectRevert(
            abi.encodeWithSelector(
                ConfioPresaleVault.ExceedsUnclaimedCredit.selector, 200_001e18, 200_000e18
            )
        );
        v.uncreditMigrated(algoBuyer, 200_001e18);

        // full credit reversal returns to pool; paid purchase untouched
        vm.prank(owner);
        v.uncreditMigrated(algoBuyer, 200_000e18);
        assertEq(v.purchased(algoBuyer), 50_000e18);
        assertEq(v.migratedCredited(algoBuyer), 0);
        assertEq(v.migratedPool(), 500_000e18);

        // after claiming, credit can no longer be revoked
        amounts[0] = 100_000e18;
        vm.prank(owner);
        v.creditMigrated(buyers, amounts);
        vm.startPrank(owner);
        v.setConfioToken(IERC20(address(confio)));
        v.setClaimsUnlocked(true);
        vm.stopPrank();
        confio.mint(address(v), 200_000e18);
        vm.prank(algoBuyer);
        v.claim();
        vm.prank(owner);
        vm.expectRevert(
            abi.encodeWithSelector(ConfioPresaleVault.ExceedsUnclaimedCredit.selector, 1, 0)
        );
        v.uncreditMigrated(algoBuyer, 1);
    }

    function test_expandMigratedPool_moves_curve() public {
        ConfioPresaleVault v = _newVault(500_000e18);
        uint256 priceBefore = v.currentPrice();
        vm.prank(owner);
        v.expandMigratedPool(100_000e18);
        assertEq(v.totalSold(), 600_000e18);
        assertEq(v.migratedPool(), 600_000e18);
        assertGt(v.currentPrice(), priceBefore);

        vm.prank(owner);
        vm.expectRevert(ConfioPresaleVault.ExceedsTokensForSale.selector);
        v.expandMigratedPool(S); // beyond remaining
    }

    function test_pool_reserved_from_confio_sweep() public {
        ConfioPresaleVault v = _newVault(500_000e18);
        vm.prank(owner);
        v.setConfioToken(IERC20(address(confio)));
        // fund exactly the outstanding (pool, nothing credited/claimed yet)
        confio.mint(address(v), 500_000e18);
        vm.prank(owner);
        vm.expectRevert(
            abi.encodeWithSelector(ConfioPresaleVault.ExceedsExcessConfio.selector, 1, 0)
        );
        v.sweepExcessConfio(owner, 1); // unassigned pool is NOT sweepable
    }

    // ------------------------------------------------------------------
    // Claims
    // ------------------------------------------------------------------

    function test_claim_lifecycle() public {
        _sponsoredBuy(user, 1000e18, type(uint256).max);

        // Locked before unlock
        vm.prank(user);
        vm.expectRevert(ConfioPresaleVault.ClaimsLocked.selector);
        vault.claim();

        // Cannot unlock before token wired
        vm.prank(owner);
        vm.expectRevert(ConfioPresaleVault.ConfioTokenNotSet.selector);
        vault.setClaimsUnlocked(true);

        vm.prank(owner);
        vault.setConfioToken(IERC20(address(confio)));
        vm.prank(owner);
        vm.expectRevert(ConfioPresaleVault.ConfioTokenAlreadySet.selector);
        vault.setConfioToken(IERC20(address(confio)));

        confio.mint(address(vault), 1_000_000e18);
        vm.prank(owner);
        vault.setClaimsUnlocked(true);

        assertEq(vault.claimableOf(user), 1000e18);
        vm.prank(user);
        uint256 got = vault.claim();
        assertEq(got, 1000e18);
        assertEq(confio.balanceOf(user), 1000e18);
        assertEq(vault.claimableOf(user), 0);

        vm.prank(user);
        vm.expectRevert(ConfioPresaleVault.NothingToClaim.selector);
        vault.claim();
    }

    function test_sweeps_and_guards() public {
        uint256 cost = _sponsoredBuy(user, 1000e18, type(uint256).max);

        // Proceeds sweep
        vm.prank(owner);
        vault.sweepPayment(owner, cost);
        assertEq(payment.balanceOf(owner), cost);

        // CONFIO owed to buyers is untouchable: fund exactly outstanding
        vm.prank(owner);
        vault.setConfioToken(IERC20(address(confio)));
        confio.mint(address(vault), 1000e18);
        vm.prank(owner);
        vm.expectRevert(
            abi.encodeWithSelector(ConfioPresaleVault.ExceedsExcessConfio.selector, 1, 0)
        );
        vault.sweepExcessConfio(owner, 1);

        // Overfund → only the excess is sweepable
        confio.mint(address(vault), 500e18);
        vm.prank(owner);
        vault.sweepExcessConfio(owner, 500e18);
        assertEq(confio.balanceOf(owner), 500e18);

        // rescueToken refuses CONFIO
        vm.prank(owner);
        vm.expectRevert(ConfioPresaleVault.UseSweepExcessConfio.selector);
        vault.rescueToken(IERC20(address(confio)), owner, 1);

        // but rescues strays
        MockToken stray = new MockToken("STRAY");
        stray.mint(address(vault), 7e18);
        vm.prank(owner);
        vault.rescueToken(IERC20(address(stray)), owner, 7e18);
        assertEq(stray.balanceOf(owner), 7e18);
    }

    function test_pause_blocks_buys_not_claims() public {
        _sponsoredBuy(user, 1000e18, type(uint256).max);
        vm.prank(owner);
        vault.pause();

        vm.prank(user, sponsor);
        vm.expectRevert();
        vault.buy(1e18, type(uint256).max);

        vm.prank(owner);
        vault.setConfioToken(IERC20(address(confio)));
        confio.mint(address(vault), 1000e18);
        vm.prank(owner);
        vault.setClaimsUnlocked(true);
        vm.prank(user);
        assertEq(vault.claim(), 1000e18); // claims unaffected by pause
    }

    // ------------------------------------------------------------------
    // Accounting invariants (seeded)
    // ------------------------------------------------------------------

    function testFuzz_payment_balance_covers_curve_integral(uint128 a, uint128 b, uint128 c) public {
        uint256[3] memory qs =
            [bound(uint256(a), 1, S / 4), bound(uint256(b), 1, S / 4), bound(uint256(c), 1, S / 4)];
        address[3] memory buyers = [user, user2, user];
        uint256 total;
        uint256 preSold = vault.totalSold();
        for (uint256 i; i < 3; ++i) {
            total += _sponsoredBuy(buyers[i], qs[i], type(uint256).max);
        }
        // Vault holds exactly what the curve charged; ledgers match.
        assertEq(payment.balanceOf(address(vault)), total);
        assertEq(vault.totalRaised(), total);
        assertEq(vault.totalSold(), preSold + qs[0] + qs[1] + qs[2]);
    }

    /// purchased-sum + unassigned pool always equals totalSold.
    function testFuzz_pool_purchase_ledger(uint128 seed, uint128 buyAmt, uint128 creditAmt) public {
        uint256 sd = bound(uint256(seed), 1e18, S / 2);
        ConfioPresaleVault v = _newVault(sd);
        uint256 qb = bound(uint256(buyAmt), 1, S - sd);
        _sponsoredBuy(v, user, qb, type(uint256).max);

        uint256 qc = bound(uint256(creditAmt), 1, sd);
        address[] memory buyers = new address[](1);
        uint256[] memory amounts = new uint256[](1);
        (buyers[0], amounts[0]) = (algoBuyer, qc);
        vm.prank(owner);
        v.creditMigrated(buyers, amounts);

        assertEq(v.purchased(user) + v.purchased(algoBuyer) + v.migratedPool(), v.totalSold());
    }
}
