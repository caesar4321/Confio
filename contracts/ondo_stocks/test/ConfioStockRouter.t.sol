// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {CusdPlusVault} from "cusd-plus/CusdPlusVault.sol";
import {ConfioStockRouter, IGMTokenManager, GmQuote} from "../ConfioStockRouter.sol";
import {MockToken, MockOracle, MockInstantManager} from "cusd-plus/test/CusdPlusVault.t.sol";

/// Models the REAL GMTokenManager behavior verified on-chain 2026-07-31:
/// mint credits the CALLER (no recipient param exists), redeem pays the
/// CALLER, and a non-USDon deposit can refund surplus USDon to the caller.
contract MockGMTokenManager is IGMTokenManager {
    MockToken public usdt;
    MockToken internal usdonToken;
    uint256 public priceUsd = 300e18; // $300/share

    /// Leaves 1 wei of the approval unconsumed — models a partial fill.
    bool public partialFill;
    /// Surplus USDon refunded to the caller after a non-USDon deposit.
    uint256 public usdonRefund;

    constructor(MockToken _usdt, MockToken _usdon) {
        usdt = _usdt;
        usdonToken = _usdon;
    }

    function usdon() external view returns (address) {
        return address(usdonToken);
    }

    function setPartialFill(bool v) external {
        partialFill = v;
    }

    function setUsdonRefund(uint256 v) external {
        usdonRefund = v;
    }

    function mintWithAttestation(GmQuote calldata quote, bytes memory, address depositToken, uint256 depositTokenAmount)
        external
        returns (uint256)
    {
        uint256 take = partialFill ? depositTokenAmount - 1 : depositTokenAmount;
        require(IERC20(depositToken).transferFrom(msg.sender, address(this), take), "deposit transfer failed");
        if (usdonRefund > 0) usdonToken.mint(msg.sender, usdonRefund);
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
        require(MockToken(quote.asset).transferFrom(msg.sender, address(this), take), "stock transfer failed");
        uint256 out = (quote.quantity * priceUsd) / 1e18;
        require(out >= minimumReceiveAmount, "gm: min receive");
        require(MockToken(receiveToken).transfer(msg.sender, out), "proceeds transfer failed");
        return out;
    }
}

/// 1% fee-on-transfer stock — the user must still be floored on what THEY
/// receive, not on what the router received.
contract TaxedStock is ERC20 {
    constructor() ERC20("TAXon", "TAXon") {}

    function mint(address to, uint256 amt) external {
        _mint(to, amt);
    }

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

        CusdPlusVault impl = new CusdPlusVault(address(usdy), address(usdt), address(im), address(oracle), 1500);
        vault = CusdPlusVault(
            address(new ERC1967Proxy(address(impl), abi.encodeCall(CusdPlusVault.initialize, (treasury))))
        );
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

        ConfioStockRouter routerImpl = new ConfioStockRouter(address(vault), address(usdt), address(usdon), address(gm));
        router = ConfioStockRouter(
            address(new ERC1967Proxy(address(routerImpl), abi.encodeCall(ConfioStockRouter.initialize, (treasury))))
        );
        // sellToSavings mints TO THE USER while the router is msg.sender,
        // so the router must be a registered relay (2026-07-31 gate). This
        // is a DEPLOYMENT REQUIREMENT: setSponsor(router, true) or every
        // sell-into-savings reverts "recipient not caller".
        vm.prank(treasury);
        vault.setSponsor(address(router), true);
        vm.prank(treasury);
        vault.setStockRouter(address(router));
        // User saves $3,000 first (sweep model: cUSD+ is the buying power)
        // Seed through the treasury USDY rail so this stock-router unit test
        // is independent of the ordinary 90 bps USDT perimeter.
        usdy.mint(treasury, 3000e18);
        vm.startPrank(treasury);
        usdy.approve(address(vault), 3000e18);
        vault.depositAndMint(3000e18, user);
        vm.stopPrank();
        vm.startPrank(user);
        vault.approve(address(router), type(uint256).max);
        tsla.approve(address(router), type(uint256).max);
        vm.stopPrank();
    }

    // ── quote helpers (the server builds these from Ondo's attestation) ──

    function _quote(address asset, uint256 quantity, uint8 side) internal returns (GmQuote memory q) {
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
        return _quote(asset, (_buySpend(sharesIn) * 1e18) / PRICE, 0);
    }

    function _buySpend(uint256 sharesIn) internal pure returns (uint256) {
        // Keep this helper local: an external view call here would consume a
        // one-shot vm.prank before _buy reaches the router.
        return Math.mulDiv(sharesIn, 9970, 10_000);
    }

    function _buyFee(uint256 spend) internal pure returns (uint256) {
        return Math.mulDiv(spend, 30, 9970, Math.Rounding.Ceil);
    }

    function _buy(GmQuote memory q, uint256 sharesIn, uint256 maxFeeBps) internal returns (uint256) {
        return router.buyWithSavings(q, "", sharesIn, _buySpend(sharesIn), 0, maxFeeBps);
    }

    function _sellQuote(address asset, uint256 quantity) internal returns (GmQuote memory) {
        return _quote(asset, quantity, 1);
    }

    function test_constructor_rejectsNonContractDependency() public {
        vm.expectRevert(bytes("non-contract dependency"));
        new ConfioStockRouter(user, address(usdt), address(usdon), address(gm));
    }

    function test_constructor_rejectsMismatchedGmUsdon() public {
        MockToken otherUsdon = new MockToken("other USDon");
        vm.expectRevert(bytes("gm usdon mismatch"));
        new ConfioStockRouter(address(vault), address(usdt), address(otherUsdon), address(gm));
    }

    function test_implementationCannotBeInitialized() public {
        ConfioStockRouter impl = new ConfioStockRouter(address(vault), address(usdt), address(usdon), address(gm));
        vm.expectRevert();
        impl.initialize(user);
    }

    function test_uupsUpgrade_isOwnerOnly_andPreservesState() public {
        uint256 sharesIn = 300e18;
        GmQuote memory q = _buyQuote(address(tsla), sharesIn);
        vm.prank(user);
        _buy(q, sharesIn, 30);
        uint256 feesBefore = router.accruedUsdtFees();

        ConfioStockRouter nextImpl = new ConfioStockRouter(address(vault), address(usdt), address(usdon), address(gm));
        vm.prank(user);
        vm.expectRevert();
        router.upgradeToAndCall(address(nextImpl), "");

        vm.prank(treasury);
        router.upgradeToAndCall(address(nextImpl), "");
        assertEq(router.owner(), treasury, "owner preserved");
        assertEq(router.accruedUsdtFees(), feesBefore, "fee accounting preserved");
        assertEq(address(router.CUSD_PLUS()), address(vault), "immutable wiring preserved");
    }

    // ── core behavior ───────────────────────────────────────────────────

    function test_buy_takesExplicitFee_deliversStock() public {
        uint256 sharesIn = 600e18; // $600 of savings at par
        GmQuote memory q = _buyQuote(address(tsla), sharesIn);

        vm.prank(user);
        uint256 stockOut = _buy(q, sharesIn, 100);

        // fee = 0.30% of the redeemed USDT, as an explicit transfer
        uint256 expectedFee = (600e18 * 30) / 10_000;
        assertEq(router.accruedUsdtFees(), expectedFee, "fee accounted in router");
        assertEq(usdt.balanceOf(address(router)), expectedFee, "fee retained in router");
        assertEq(stockOut, q.quantity, "user receives exactly the signed quantity");
        assertEq(tsla.balanceOf(user), stockOut, "stock delivered to user");
        assertEq(vault.balanceOf(user), 3000e18 - sharesIn, "savings reduced");
        // Trade principal is swept; only the explicit fee rests in the router.
        assertEq(usdt.balanceOf(address(router)), expectedFee);
        assertEq(tsla.balanceOf(address(router)), 0);
        assertEq(vault.balanceOf(address(router)), 0);
    }

    function test_buy_doesNotChargeConversionFee() public {
        uint256 sharesIn = 1_000e18;
        GmQuote memory q = _buyQuote(address(tsla), sharesIn);

        vm.prank(user);
        _buy(q, sharesIn, 30);

        uint256 expectedTradeFee = (sharesIn * 30) / 10_000;
        assertEq(router.accruedUsdtFees(), expectedTradeFee, "only 30 bps stock fee");
        assertEq(usdt.balanceOf(address(router)), expectedTradeFee, "no conversion fee retained");
        assertEq(vault.balanceOf(user), 2_000e18, "only input shares consumed");
    }

    function test_buy_returnsAccrualAboveAttestedDebit() public {
        uint256 sharesIn = 600e18;
        GmQuote memory q = _buyQuote(address(tsla), sharesIn);
        uint256 attestedSpend = _buySpend(sharesIn);

        // The quote was prepared at the old pPlus, then USDY accrued before
        // execution. The vault redeems more than the quote+fee requires.
        oracle.setPrice(1.019e18);
        vm.prank(user);
        uint256 stockOut = router.buyWithSavings(q, "", sharesIn, attestedSpend, 0, 30);

        uint256 fee = Math.mulDiv(attestedSpend, 30, 9970, Math.Rounding.Ceil);
        // Vault share -> USDY and Instant Manager USDY -> USDT each round
        // down independently, so mirror both conversions exactly.
        uint256 oraclePrice = oracle.price();
        uint256 redeemed = Math.mulDiv(Math.mulDiv(sharesIn, vault.pPlus(), oraclePrice), oraclePrice, 1e18);
        assertEq(stockOut, q.quantity);
        assertEq(router.accruedUsdtFees(), fee, "only fixed fee accrues");
        assertEq(usdt.balanceOf(user), redeemed - attestedSpend - fee, "accrual excess returned");
        assertEq(usdt.balanceOf(address(router)), fee, "no hidden excess retained");
    }

    function test_sell_reinvestsProceedsIntoSavings() public {
        GmQuote memory bq = _buyQuote(address(tsla), 600e18);
        vm.prank(user);
        uint256 stockOut = _buy(bq, 600e18, 100);
        uint256 sharesBefore = vault.balanceOf(user);

        GmQuote memory sq = _sellQuote(address(tsla), stockOut);
        vm.prank(user);
        uint256 sharesOut = router.sellToSavings(sq, "", 0, 0, 100);

        assertEq(tsla.balanceOf(user), 0);
        assertEq(vault.balanceOf(user), sharesBefore + sharesOut, "proceeds keep earning");
        // round trip cost = buy fee + sell fee on the 600 that traded; the
        // untouched 2,400 of savings is unaffected (mock GM is spread-free)
        uint256 endValue = vault.balanceOf(user); // pPlus == 1e18 (no accrual)
        uint256 expected = 2400e18 + Math.mulDiv(Math.mulDiv(600e18, 9970, 10_000), 9970, 10_000);
        assertApproxEqRel(endValue, expected, 0.0001e18);
        uint256 expectedFees = (600e18 * 30) / 10_000;
        uint256 sellProceeds = (stockOut * PRICE) / 1e18;
        expectedFees += (sellProceeds * 30) / 10_000;
        assertEq(router.accruedUsdtFees(), expectedFees, "buy and sell fees accumulate");
        assertEq(usdt.balanceOf(address(router)), router.accruedUsdtFees(), "router keeps only accrued fees");
        assertGe(vault.backingRatioBps(), 10_000, "vault invariant holds through trades");
    }

    function testFuzz_buyAndSell_feeReserveAlwaysSolvent(uint96 rawShares) public {
        uint256 sharesIn = bound(uint256(rawShares), 1e18, 3000e18);
        GmQuote memory bq = _buyQuote(address(tsla), sharesIn);

        vm.prank(user);
        uint256 stockOut = _buy(bq, sharesIn, 30);
        uint256 expectedFees = _buyFee(_buySpend(sharesIn));
        assertEq(router.accruedUsdtFees(), expectedFees);
        assertEq(usdt.balanceOf(address(router)), expectedFees);

        GmQuote memory sq = _sellQuote(address(tsla), stockOut);
        vm.prank(user);
        router.sellToSavings(sq, "", 0, 0, 30);

        uint256 proceeds = (stockOut * PRICE) / 1e18;
        expectedFees += (proceeds * 30) / 10_000;
        assertEq(router.accruedUsdtFees(), expectedFees);
        assertEq(usdt.balanceOf(address(router)), expectedFees);
    }

    function testFuzz_withdrawAndSweep_cannotInsolventFees(uint96 rawWithdraw, uint96 rawStray) public {
        GmQuote memory q = _buyQuote(address(tsla), 600e18);
        vm.prank(user);
        _buy(q, 600e18, 30);

        uint256 accrued = router.accruedUsdtFees();
        uint256 withdraw = bound(uint256(rawWithdraw), 0, accrued);
        uint256 stray = bound(uint256(rawStray), 0, 1_000_000e18);
        usdt.mint(address(router), stray);

        vm.startPrank(treasury);
        router.withdrawFees(treasury, withdraw);
        router.sweep(address(usdt), treasury, stray);
        vm.stopPrank();

        assertEq(router.accruedUsdtFees(), accrued - withdraw);
        assertEq(usdt.balanceOf(address(router)), accrued - withdraw);
    }

    /// Regression: minSharesOut used to be forwarded as the vault's
    /// minUsdyOut. With USDY above par (p > pPlus, always true live) an
    /// honest shares floor exceeds the achievable USDY out, so every sell
    /// reverted "im slippage". The floor must be enforced on shares, here.
    function test_sell_sharesFloor_enforced_whenUsdyAbovePar() public {
        GmQuote memory bq = _buyQuote(address(tsla), 600e18);
        vm.prank(user);
        uint256 stockOut = _buy(bq, 600e18, 100);

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
        uint256 stockOut = _buy(bq, 600e18, 100);

        GmQuote memory sq = _sellQuote(address(tsla), stockOut);
        vm.prank(user);
        vm.expectRevert(bytes("insufficient shares out"));
        router.sellToSavings(sq, "", 0, type(uint256).max, 100);
    }

    function test_fee_isFixedAtThirtyBps() public view {
        assertEq(router.stockFeeBps(), 30);
    }

    function test_ownerCanWithdrawOnlyAccruedFees() public {
        GmQuote memory q = _buyQuote(address(tsla), 600e18);
        vm.prank(user);
        _buy(q, 600e18, 30);

        uint256 accrued = router.accruedUsdtFees();
        vm.prank(treasury);
        router.withdrawFees(treasury, accrued - 1);

        assertEq(usdt.balanceOf(treasury), accrued - 1);
        assertEq(router.accruedUsdtFees(), 1);
        assertEq(usdt.balanceOf(address(router)), 1);

        vm.prank(treasury);
        vm.expectRevert(bytes("amount exceeds fees"));
        router.withdrawFees(treasury, 2);
    }

    function test_nonOwnerCannotWithdrawFees() public {
        vm.prank(user);
        vm.expectRevert();
        router.withdrawFees(user, 0);
    }

    function test_sweepCannotTakeAccruedFees_butCanRescueStrayUsdt() public {
        GmQuote memory q = _buyQuote(address(tsla), 300e18);
        vm.prank(user);
        _buy(q, 300e18, 30);
        uint256 accrued = router.accruedUsdtFees();
        usdt.mint(address(router), 7e18);

        vm.prank(treasury);
        router.sweep(address(usdt), treasury, 7e18);
        assertEq(usdt.balanceOf(address(router)), accrued);

        vm.prank(treasury);
        vm.expectRevert(bytes("amount includes fees"));
        router.sweep(address(usdt), treasury, 1);
    }

    function test_pause_blocks_trades() public {
        vm.prank(treasury);
        router.pause();
        GmQuote memory q = _buyQuote(address(tsla), 300e18);
        vm.prank(user);
        vm.expectRevert();
        _buy(q, 300e18, 100);
    }

    function test_frozen_vault_user_cannot_trade() public {
        vm.prank(treasury);
        vault.freezeAddress(user);
        GmQuote memory q = _buyQuote(address(tsla), 300e18);
        vm.prank(user);
        vm.expectRevert(bytes("address frozen"));
        _buy(q, 300e18, 100);
    }

    // ── AUDIT P2s (2026-07-31) ──────────────────────────────────────────

    /// The traded asset comes from the SIGNED quote — there is no
    /// caller-supplied token address to substitute, so a user cannot point
    /// the router at an arbitrary contract.
    function test_asset_comesFromSignedQuote() public {
        MockToken other = new MockToken("NVDAon");
        GmQuote memory q = _buyQuote(address(other), 300e18);
        vm.prank(user);
        uint256 stockOut = _buy(q, 300e18, 100);
        assertEq(other.balanceOf(user), stockOut, "settled in the quoted asset");
        assertEq(tsla.balanceOf(user), 0, "untouched asset stays untouched");
    }

    /// The user's authorization must explicitly tolerate the fixed fee.
    function test_maxFeeBps_rejectsTradeBelowFixedFee() public {
        GmQuote memory q = _buyQuote(address(tsla), 300e18);
        vm.prank(user);
        vm.expectRevert(bytes("fee above trade cap"));
        _buy(q, 300e18, 29); // trade accepts less than 0.30%
    }

    /// A partial fill would leave value here behind a live allowance.
    function test_partialFill_reverts_onBuy() public {
        gm.setPartialFill(true);
        GmQuote memory q = _buyQuote(address(tsla), 300e18);
        vm.prank(user);
        vm.expectRevert(bytes("gm: partial fill"));
        _buy(q, 300e18, 100);
    }

    function test_partialFill_reverts_onSell() public {
        GmQuote memory bq = _buyQuote(address(tsla), 600e18);
        vm.prank(user);
        uint256 stockOut = _buy(bq, 600e18, 100);

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
        _buy(q, 300e18, 100);
    }

    /// GM refunds surplus USDon to the CALLER after a non-USDon deposit. It
    /// belongs to the user and must not become owner-sweepable router value.
    function test_usdonRefund_isForwardedToUser() public {
        gm.setUsdonRefund(1234);
        GmQuote memory q = _buyQuote(address(tsla), 300e18);
        vm.prank(user);
        _buy(q, 300e18, 100);

        assertEq(usdon.balanceOf(user), 1234, "refund returned to funding user");
        assertEq(usdon.balanceOf(address(router)), 0, "refund cannot be swept by owner");
        assertEq(router.accruedUsdtFees(), (300e18 * 30) / 10_000);
    }

    // ── CODEX AUDIT 2026-07-31 ──────────────────────────────────────────

    /// GM consumes only quantity*price and refunds the surplus as USDon. A
    /// percentage tolerance allowed a second hidden fee; only a micro-USDT
    /// arithmetic remainder is now accepted.
    function test_overspendVsQuote_reverts() public {
        // Quote for $300 of stock, but spend $600 of savings.
        GmQuote memory q = _quote(address(tsla), (300e18 * 1e18) / PRICE, 0);
        vm.prank(user);
        vm.expectRevert(bytes("overspend vs quote"));
        _buy(q, 600e18, 100);
    }

    /// The legitimate case still works when sharesIn is sized to the quote.
    function test_spendMatchingQuote_passes() public {
        uint256 sharesIn = 300e18;
        GmQuote memory q = _buyQuote(address(tsla), sharesIn);
        vm.prank(user);
        uint256 stockOut = _buy(q, sharesIn, 100);
        assertEq(stockOut, q.quantity);
    }

    function test_microUsdtQuoteRemainder_passes() public {
        uint256 sharesIn = 300e18;
        GmQuote memory q = _buyQuote(address(tsla), sharesIn);
        q.quantity -= 1; // quote cost is 300 wei below net spend

        vm.prank(user);
        assertEq(_buy(q, sharesIn, 30), q.quantity);
    }

    function test_quoteRemainderAboveMicroUsdt_reverts() public {
        uint256 sharesIn = 300e18;
        GmQuote memory q = _buyQuote(address(tsla), sharesIn);
        q.quantity -= router.MAX_QUOTE_REMAINDER() / 300 + 1;

        vm.prank(user);
        vm.expectRevert(bytes("overspend vs quote"));
        _buy(q, sharesIn, 30);
    }

    function test_underspendVsQuote_reverts() public {
        uint256 sharesIn = 300e18;
        GmQuote memory q = _buyQuote(address(tsla), sharesIn);
        q.quantity += 1;

        vm.prank(user);
        vm.expectRevert(bytes("underspend vs quote"));
        _buy(q, sharesIn, 30);
    }

    function test_wrongQuoteSide_revertsLocally() public {
        GmQuote memory buy = _buyQuote(address(tsla), 300e18);
        buy.side = 1;
        vm.prank(user);
        vm.expectRevert(bytes("wrong quote side"));
        _buy(buy, 300e18, 30);

        GmQuote memory sell = _sellQuote(address(tsla), 1e18);
        sell.side = 0;
        vm.prank(user);
        vm.expectRevert(bytes("wrong quote side"));
        router.sellToSavings(sell, "", 0, 0, 30);
    }

    function test_zeroPrice_revertsLocally() public {
        GmQuote memory q = _buyQuote(address(tsla), 300e18);
        q.price = 0;
        vm.prank(user);
        vm.expectRevert(bytes("zero price"));
        _buy(q, 300e18, 30);
    }

    /// [P2] A zero-quantity quote would satisfy every downstream floor while
    /// still consuming savings and charging a fee.
    function test_zeroQuantityQuote_reverts() public {
        GmQuote memory q = _quote(address(tsla), 0, 0);
        vm.prank(user);
        vm.expectRevert(bytes("zero quantity"));
        _buy(q, 300e18, 100);
    }

    /// [P2] Buy-side accounting must measure the router's own USDT delta, so
    /// stray USDT sitting in the router can never join a user's trade.
    function test_strayUsdt_notConsumedByTrade() public {
        usdt.mint(address(router), 500e18); // accident / donation
        uint256 sharesIn = 300e18;
        GmQuote memory q = _buyQuote(address(tsla), sharesIn);

        vm.prank(user);
        uint256 stockOut = _buy(q, sharesIn, 100);

        assertEq(stockOut, q.quantity, "trade sized by the vault delta only");
        // The stray USDT is untouched (still sweepable by the owner).
        uint256 expectedFee = (300e18 * 30) / 10_000;
        assertEq(usdt.balanceOf(address(router)), 500e18 + expectedFee, "stray USDT and fee remain distinct");
        assertEq(router.accruedUsdtFees(), expectedFee, "only earned fee is accounted");
    }

    function test_wrongChainId_reverts() public {
        GmQuote memory q = _buyQuote(address(tsla), 300e18);
        q.chainId = block.chainid + 1;
        vm.prank(user);
        vm.expectRevert(bytes("wrong chain"));
        _buy(q, 300e18, 100);
    }

    // ── Sponsor boundary: cUSD+ trades gated, raw exit permissionless ──

    function test_sellToUsdt_succeedsWithoutSponsoredOrigin_andChargesThirtyBps() public {
        address holder = makeAddr("directHolder");
        tsla.mint(holder, 10e18);
        vm.prank(holder, holder);
        tsla.approve(address(router), type(uint256).max);

        GmQuote memory sq = _sellQuote(address(tsla), 10e18);
        vm.prank(holder, holder);
        uint256 usdtOut = router.sellToUsdt(sq, "", 0, 0, 30);

        assertEq(tsla.balanceOf(holder), 0, "stock redeemed");
        uint256 gross = 3000e18;
        uint256 fee = (gross * 30) / 10_000;
        assertEq(usdtOut, gross - fee, "only the stock fee is deducted");
        assertEq(usdt.balanceOf(holder), usdtOut, "holder receives raw USDT");
        assertEq(vault.balanceOf(holder), 0, "raw exit cannot mint cUSD+");
        assertEq(router.accruedUsdtFees(), fee, "30 bps accrued");
    }

    function test_sellToUsdt_enforcesNetFloor_andRollsBackStockTransfer() public {
        address holder = makeAddr("floorHolder");
        tsla.mint(holder, 1e18);
        vm.prank(holder, holder);
        tsla.approve(address(router), type(uint256).max);

        GmQuote memory sq = _sellQuote(address(tsla), 1e18);
        vm.prank(holder, holder);
        vm.expectRevert("insufficient net usdt out");
        router.sellToUsdt(sq, "", 0, 300e18, 30);

        assertEq(tsla.balanceOf(holder), 1e18, "revert restores stock");
        assertEq(usdt.balanceOf(holder), 0, "no partial payout");
        assertEq(router.accruedUsdtFees(), 0, "no fee accrued on revert");
    }

    function test_sellToUsdt_rejectsFeeCapBelowThirtyBps() public {
        address holder = makeAddr("feeCapHolder");
        tsla.mint(holder, 1e18);
        vm.prank(holder, holder);
        tsla.approve(address(router), type(uint256).max);

        GmQuote memory sq = _sellQuote(address(tsla), 1e18);
        vm.prank(holder, holder);
        vm.expectRevert("fee above trade cap");
        router.sellToUsdt(sq, "", 0, 0, 29);
    }

    function test_buy_rejectsUnrelayedCaller() public {
        GmQuote memory q = _buyQuote(address(tsla), 1e18);
        vm.prank(user, user);
        vm.expectRevert("not sponsored");
        _buy(q, 1e18, 100);
    }

    function test_sellToSavings_requiresSponsoredOrigin() public {
        address relay = makeAddr("otherRelay");
        tsla.mint(user, 10e18);
        vm.prank(user, relay);
        tsla.approve(address(router), type(uint256).max);

        GmQuote memory sq1 = _sellQuote(address(tsla), 1e18);
        vm.prank(user, relay);
        vm.expectRevert("not sponsored");
        router.sellToSavings(sq1, "", 0, 0, 100);

        vm.prank(treasury);
        vault.setSponsor(relay, true);
        GmQuote memory sq2 = _sellQuote(address(tsla), 1e18);
        vm.prank(user, relay);
        uint256 sharesOut = router.sellToSavings(sq2, "", 0, 0, 100);
        assertGt(sharesOut, 0, "sponsored savings settlement succeeds");
    }
}
