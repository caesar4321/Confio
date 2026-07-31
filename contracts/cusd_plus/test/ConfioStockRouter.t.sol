// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {CusdPlusVault} from "../CusdPlusVault.sol";
import {ConfioStockRouter, IGMTokenManager, GmQuote} from "../ConfioStockRouter.sol";
import {MockToken, MockOracle, MockInstantManager} from "./CusdPlusVault.t.sol";

/// Models the REAL GMTokenManager behavior verified on-chain 2026-07-31:
/// mint credits the CALLER (no recipient param exists), redeem pays the
/// CALLER, and a non-USDon deposit can refund surplus USDon to the caller.
contract MockGMTokenManager is IGMTokenManager {
    MockToken public usdt;
    MockToken public usdon;
    uint256 public priceUsd = 300e18; // $300/share

    /// Leaves 1 wei of the approval unconsumed — models a partial fill.
    bool public partialFill;
    /// Surplus USDon refunded to the caller after a non-USDon deposit.
    uint256 public usdonRefund;

    constructor(MockToken _usdt, MockToken _usdon) {
        usdt = _usdt;
        usdon = _usdon;
    }

    function setPartialFill(bool v) external { partialFill = v; }
    function setUsdonRefund(uint256 v) external { usdonRefund = v; }

    function mintWithAttestation(
        GmQuote calldata quote,
        bytes memory,
        address depositToken,
        uint256 depositTokenAmount
    ) external returns (uint256) {
        uint256 take = partialFill ? depositTokenAmount - 1 : depositTokenAmount;
        IERC20(depositToken).transferFrom(msg.sender, address(this), take);
        if (usdonRefund > 0) usdon.mint(msg.sender, usdonRefund);
        // The real contract: IRWALike(quote.asset).mint(_msgSender(), quote.quantity)
        MockToken(quote.asset).mint(msg.sender, quote.quantity);
        return quote.quantity;
    }

    function redeemWithAttestation(
        GmQuote calldata quote,
        bytes memory,
        address receiveToken,
        uint256 minimumReceiveAmount
    ) external returns (uint256) {
        uint256 take = partialFill ? quote.quantity - 1 : quote.quantity;
        MockToken(quote.asset).transferFrom(msg.sender, address(this), take);
        uint256 out = (quote.quantity * priceUsd) / 1e18;
        require(out >= minimumReceiveAmount, "gm: min receive");
        MockToken(receiveToken).transfer(msg.sender, out);
        return out;
    }
}

/// 1% fee-on-transfer stock — the user must still be floored on what THEY
/// receive, not on what the router received.
contract TaxedStock is ERC20 {
    constructor() ERC20("TAXon", "TAXon") {}
    function mint(address to, uint256 amt) external { _mint(to, amt); }
    function _update(address from, address to, uint256 value) internal override {
        if (from != address(0) && to != address(0)) {
            uint256 tax = value / 100;
            super._update(from, address(0xdead), tax);
            value -= tax;
        }
        super._update(from, to, value);
    }
}

contract ConfioStockRouterTest is Test {
    MockToken usdt;
    MockToken usdy;
    MockToken usdon;
    MockToken tsla;
    MockOracle oracle;
    MockInstantManager im;
    MockGMTokenManager gm;
    CusdPlusVault vault;
    ConfioStockRouter router;

    address treasury = makeAddr("treasury");
    address feeTreasury = makeAddr("feeTreasury");
    address user = makeAddr("user");

    bytes32 constant CONFIO_USER_ID = keccak256("confio-purchaser");
    uint256 constant PRICE = 300e18;
    uint256 nextAttestationId = 1;

    function setUp() public {
        usdt = new MockToken("USDT");
        usdy = new MockToken("USDY");
        usdon = new MockToken("USDon");
        tsla = new MockToken("TSLAon");
        oracle = new MockOracle();
        im = new MockInstantManager(usdt, usdy, oracle);
        usdt.mint(address(im), 100_000_000e18);
        usdy.mint(address(im), 100_000_000e18);

        CusdPlusVault impl = new CusdPlusVault(
            address(usdy), address(usdt), address(im), address(oracle), 1500
        );
        vault = CusdPlusVault(address(new ERC1967Proxy(
            address(impl), abi.encodeCall(CusdPlusVault.initialize, (treasury))
        )));
        // Two DIFFERENT registrations, easy to conflate:
        //  1. the router, so the vault accepts it minting FOR a user;
        //  2. the default tx.origin, standing in for Confío's KMS relay.
        // Forge keeps tx.origin as the default sender under vm.prank, so
        // ordinary tests below model a properly relayed trade. Tests that
        // want an UNRELAYED caller use vm.prank(x, x) to set origin too.
        vm.prank(treasury);
        vault.setSponsor(tx.origin, true);

        gm = new MockGMTokenManager(usdt, usdon);
        usdt.mint(address(gm), 10_000_000e18);

        router = new ConfioStockRouter(
            address(vault), address(usdt), address(usdon),
            address(gm), feeTreasury, treasury
        );
        // sellToSavings mints TO THE USER while the router is msg.sender,
        // so the router must be a registered relay (2026-07-31 gate). This
        // is a DEPLOYMENT REQUIREMENT: setSponsor(router, true) or every
        // sell-into-savings reverts "recipient not caller".
        vm.prank(treasury);
        vault.setSponsor(address(router), true);
        vm.prank(treasury);
        router.setStockFeeBps(30); // launch-config placeholder for tests only

        // User saves $3,000 first (sweep model: cUSD+ is the buying power)
        usdt.mint(user, 3000e18);
        vm.startPrank(user);
        usdt.approve(address(vault), type(uint256).max);
        vault.subscribeAndMint(3000e18, 0, user);
        vault.approve(address(router), type(uint256).max);
        tsla.approve(address(router), type(uint256).max);
        vm.stopPrank();
    }

    // ── quote helpers (the server builds these from Ondo's attestation) ──

    function _quote(address asset, uint256 quantity, uint8 side)
        internal
        returns (GmQuote memory q)
    {
        q = GmQuote({
            chainId: block.chainid,
            attestationId: nextAttestationId++,
            userId: CONFIO_USER_ID,
            asset: asset,
            price: PRICE,
            quantity: quantity,
            expiration: block.timestamp + 300,
            side: side,
            additionalData: bytes32(0)
        });
    }

    /// Quote for spending `sharesIn` of savings at par, net of the fee.
    function _buyQuote(address asset, uint256 sharesIn) internal returns (GmQuote memory) {
        uint256 spend = sharesIn - (sharesIn * router.stockFeeBps()) / 10_000;
        return _quote(asset, (spend * 1e18) / PRICE, 0);
    }

    function _sellQuote(address asset, uint256 quantity) internal returns (GmQuote memory) {
        return _quote(asset, quantity, 1);
    }

    // ── core behavior ───────────────────────────────────────────────────

    function test_buy_takesExplicitFee_deliversStock() public {
        uint256 sharesIn = 600e18; // $600 of savings at par
        GmQuote memory q = _buyQuote(address(tsla), sharesIn);

        vm.prank(user);
        uint256 stockOut = router.buyWithSavings(q, "", sharesIn, 0, 100);

        // fee = 0.30% of the redeemed USDT, as an explicit transfer
        uint256 expectedFee = (600e18 * 30) / 10_000;
        assertEq(usdt.balanceOf(feeTreasury), expectedFee, "explicit fee to treasury");
        assertEq(stockOut, q.quantity, "user receives exactly the signed quantity");
        assertEq(tsla.balanceOf(user), stockOut, "stock delivered to user");
        assertEq(vault.balanceOf(user), 3000e18 - sharesIn, "savings reduced");
        // router is a pipe: nothing rests
        assertEq(usdt.balanceOf(address(router)), 0);
        assertEq(tsla.balanceOf(address(router)), 0);
        assertEq(vault.balanceOf(address(router)), 0);
    }

    function test_sell_reinvestsProceedsIntoSavings() public {
        GmQuote memory bq = _buyQuote(address(tsla), 600e18);
        vm.prank(user);
        uint256 stockOut = router.buyWithSavings(bq, "", 600e18, 0, 100);
        uint256 sharesBefore = vault.balanceOf(user);

        GmQuote memory sq = _sellQuote(address(tsla), stockOut);
        vm.prank(user);
        uint256 sharesOut = router.sellToSavings(sq, "", 0, 0, 100);

        assertEq(tsla.balanceOf(user), 0);
        assertEq(vault.balanceOf(user), sharesBefore + sharesOut, "proceeds keep earning");
        // round trip cost = buy fee + sell fee on the 600 that traded; the
        // untouched 2,400 of savings is unaffected (mock GM is spread-free)
        uint256 endValue = vault.balanceOf(user); // pPlus == 1e18 (no accrual)
        uint256 expected = 2400e18 + (600e18 * 9970 / 10_000) * 9970 / 10_000;
        assertApproxEqRel(endValue, expected, 0.0001e18);
        assertEq(usdt.balanceOf(address(router)), 0, "router keeps nothing");
        assertGe(vault.backingRatioBps(), 10_000, "vault invariant holds through trades");
    }

    /// Regression: minSharesOut used to be forwarded as the vault's
    /// minUsdyOut. With USDY above par (p > pPlus, always true live) an
    /// honest shares floor exceeds the achievable USDY out, so every sell
    /// reverted "im slippage". The floor must be enforced on shares, here.
    function test_sell_sharesFloor_enforced_whenUsdyAbovePar() public {
        GmQuote memory bq = _buyQuote(address(tsla), 600e18);
        vm.prank(user);
        uint256 stockOut = router.buyWithSavings(bq, "", 600e18, 0, 100);

        // USDY appreciates 1.9% (inside the 2% oracle jump guard)
        oracle.setPrice(1.019e18);

        // Mirror the contract's integer math to derive the exact shares the
        // sell should mint, then demand exactly that as the floor.
        uint256 proceeds = (stockOut * PRICE) / 1e18;
        uint256 reinvest = proceeds - (proceeds * 30) / 10_000;
        uint256 p = 1.019e18;
        uint256 pPlusAfter = 1e18 + (0.019e18 * 8500) / 10_000; // accrues in-tx
        uint256 usdyOut = (reinvest * 1e18) / p;
        uint256 expectedShares = (usdyOut * p) / pPlusAfter;
        assertGt(expectedShares, usdyOut, "scenario needs shares > USDY units");

        GmQuote memory sq = _sellQuote(address(tsla), stockOut);
        vm.prank(user);
        uint256 sharesOut = router.sellToSavings(sq, "", 0, expectedShares, 100);
        assertEq(sharesOut, expectedShares, "tight shares floor satisfied");
        assertEq(vault.pPlus(), pPlusAfter, "accrual math mirrored correctly");
    }

    function test_sell_sharesFloor_reverts_whenUnmet() public {
        GmQuote memory bq = _buyQuote(address(tsla), 600e18);
        vm.prank(user);
        uint256 stockOut = router.buyWithSavings(bq, "", 600e18, 0, 100);

        GmQuote memory sq = _sellQuote(address(tsla), stockOut);
        vm.prank(user);
        vm.expectRevert(bytes("insufficient shares out"));
        router.sellToSavings(sq, "", 0, type(uint256).max, 100);
    }

    function test_fee_capped_and_ownerOnly() public {
        vm.prank(treasury);
        vm.expectRevert(bytes("fee above hard cap"));
        router.setStockFeeBps(101);

        vm.prank(user);
        vm.expectRevert(); // non-owner
        router.setStockFeeBps(10);
    }

    function test_zeroFee_isCleanPassThrough() public {
        vm.prank(treasury);
        router.setStockFeeBps(0);
        GmQuote memory q = _buyQuote(address(tsla), 300e18);
        vm.prank(user);
        uint256 stockOut = router.buyWithSavings(q, "", 300e18, 0, 100);
        assertEq(stockOut, 1e18, "exactly one share at $300, no fee");
        assertEq(usdt.balanceOf(feeTreasury), 0);
    }

    function test_pause_blocks_trades() public {
        vm.prank(treasury);
        router.pause();
        GmQuote memory q = _buyQuote(address(tsla), 300e18);
        vm.prank(user);
        vm.expectRevert();
        router.buyWithSavings(q, "", 300e18, 0, 100);
    }

    function test_frozen_vault_user_cannot_trade() public {
        vm.prank(treasury);
        vault.freezeAddress(user);
        GmQuote memory q = _buyQuote(address(tsla), 300e18);
        vm.prank(user);
        vm.expectRevert(bytes("address frozen"));
        router.buyWithSavings(q, "", 300e18, 0, 100);
    }

    // ── AUDIT P2s (2026-07-31) ──────────────────────────────────────────

    /// The traded asset comes from the SIGNED quote — there is no
    /// caller-supplied token address to substitute, so a user cannot point
    /// the router at an arbitrary contract.
    function test_asset_comesFromSignedQuote() public {
        MockToken other = new MockToken("NVDAon");
        GmQuote memory q = _buyQuote(address(other), 300e18);
        vm.prank(user);
        uint256 stockOut = router.buyWithSavings(q, "", 300e18, 0, 100);
        assertEq(other.balanceOf(user), stockOut, "settled in the quoted asset");
        assertEq(tsla.balanceOf(user), 0, "untouched asset stays untouched");
    }

    /// A fee raise cannot be slipped in front of an already-signed trade.
    function test_maxFeeBps_blocksFeeRaiseAheadOfTrade() public {
        GmQuote memory q = _buyQuote(address(tsla), 300e18);
        vm.prank(treasury);
        router.setStockFeeBps(100); // owner raises to the cap

        vm.prank(user);
        vm.expectRevert(bytes("fee above trade cap"));
        router.buyWithSavings(q, "", 300e18, 0, 30); // trade committed to 0.30%
    }

    /// A partial fill would leave value here behind a live allowance.
    function test_partialFill_reverts_onBuy() public {
        gm.setPartialFill(true);
        GmQuote memory q = _buyQuote(address(tsla), 300e18);
        vm.prank(user);
        vm.expectRevert(bytes("gm: partial fill"));
        router.buyWithSavings(q, "", 300e18, 0, 100);
    }

    function test_partialFill_reverts_onSell() public {
        GmQuote memory bq = _buyQuote(address(tsla), 600e18);
        vm.prank(user);
        uint256 stockOut = router.buyWithSavings(bq, "", 600e18, 0, 100);

        gm.setPartialFill(true);
        GmQuote memory sq = _sellQuote(address(tsla), stockOut);
        vm.prank(user);
        vm.expectRevert(bytes("gm: partial fill"));
        router.sellToSavings(sq, "", 0, 0, 100);
    }

    /// A transfer-taxing stock lands the USER under the signed quantity even
    /// though the ROUTER received it in full — the floor must catch that.
    function test_userShortChanged_reverts_onTaxingToken() public {
        TaxedStock taxed = new TaxedStock();
        GmQuote memory q = _buyQuote(address(taxed), 300e18);
        vm.prank(user);
        vm.expectRevert(bytes("user short-changed"));
        router.buyWithSavings(q, "", 300e18, 0, 100);
    }

    /// GM refunds surplus USDon to the CALLER after a non-USDon deposit;
    /// the router must not silently accumulate it.
    function test_usdonDust_forwardedToTreasury() public {
        gm.setUsdonRefund(1234);
        GmQuote memory q = _buyQuote(address(tsla), 300e18);
        vm.prank(user);
        router.buyWithSavings(q, "", 300e18, 0, 100);

        assertEq(usdon.balanceOf(feeTreasury), 1234, "dust swept to treasury");
        assertEq(usdon.balanceOf(address(router)), 0, "router holds nothing at rest");
    }

    function test_wrongChainId_reverts() public {
        GmQuote memory q = _buyQuote(address(tsla), 300e18);
        q.chainId = block.chainid + 1;
        vm.prank(user);
        vm.expectRevert(bytes("wrong chain"));
        router.buyWithSavings(q, "", 300e18, 0, 100);
    }

    // ── AUDIT REGRESSION (2026-07-31 [P1]) ───────────────────────────
    // Registering the router as a vault sponsor makes it satisfy BOTH of
    // the vault's mint checks on its own, so without a gate of its own the
    // router launders any permissionless call into fresh cUSD+ — exactly
    // the eligibility bypass the v5 vault gate exists to prevent.

    function test_sell_rejectsUnrelayedCaller() public {
        // An ineligible holder with a real stock balance, acting alone.
        address ineligible = makeAddr("ineligibleHolder");
        tsla.mint(ineligible, 10e18);
        vm.prank(ineligible, ineligible); // own tx: Confío not in it
        tsla.approve(address(router), type(uint256).max);

        assertTrue(vault.isSponsor(address(router)), "router IS a vault sponsor");
        GmQuote memory sq = _sellQuote(address(tsla), 10e18);
        vm.prank(ineligible, ineligible);
        vm.expectRevert("not sponsored");
        router.sellToSavings(sq, "", 0, 0, 100);
        assertEq(vault.balanceOf(ineligible), 0, "no cUSD+ was issued");
    }

    function test_buy_rejectsUnrelayedCaller() public {
        GmQuote memory q = _buyQuote(address(tsla), 1e18);
        vm.prank(user, user);
        vm.expectRevert("not sponsored");
        router.buyWithSavings(q, "", 1e18, 0, 100);
    }

    /// The gate must read the ORIGIN, not the router's own registration —
    /// isSponsor(address(this)) is always true and is precisely the hole.
    function test_gate_follows_origin_registration() public {
        address relay = makeAddr("otherRelay");
        tsla.mint(user, 10e18);
        vm.prank(user, relay);
        tsla.approve(address(router), type(uint256).max);

        GmQuote memory sq1 = _sellQuote(address(tsla), 1e18);
        vm.prank(user, relay);
        vm.expectRevert("not sponsored");
        router.sellToSavings(sq1, "", 0, 0, 100);

        vm.prank(treasury);
        vault.setSponsor(relay, true); // relay becomes Confío-operated
        GmQuote memory sq2 = _sellQuote(address(tsla), 1e18);
        vm.prank(user, relay);
        uint256 sharesOut = router.sellToSavings(sq2, "", 0, 0, 100);
        assertGt(sharesOut, 0, "same call succeeds once the origin is a relay");
    }
}
