// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, stdStorage, StdStorage} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {CusdPlusVault} from "cusd-plus/CusdPlusVault.sol";
import {ConfioStockRouter, IGMTokenManager, GmQuote} from "../ConfioStockRouter.sol";
import {MockToken, MockOracle, MockInstantManager} from "cusd-plus/test/CusdPlusVault.t.sol";
import {MockCusdFeePerimeter} from "cusd-plus/test/MockCusdFeePerimeter.sol";

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
    using stdStorage for StdStorage;

    MockToken usdt;
    MockToken usdy;
    MockToken usdon;
    MockToken tsla;
    MockOracle oracle;
    MockInstantManager im;
    MockGMTokenManager gm;
    CusdPlusVault vault;
    MockCusdFeePerimeter cusd;
    ConfioStockRouter router;

    /// cUSD's single conversion fee (production: 90 bps). Since router v2
    /// stock trades pay it on the cUSD+ exit (buy) and entry (sell).
    uint256 constant FEE = 90;

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
        cusd = new MockCusdFeePerimeter(IERC20(address(usdt)), FEE);
        vm.prank(treasury);
        vault.initializeCusd(address(cusd));
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
        // Seed through the treasury USDY rail so the starting balance is
        // exactly $3,000 of shares; the trades below pay the perimeter.
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

    /// Quote for spending `sharesIn` of savings at par, net of cUSD's exit fee.
    function _buyQuote(address asset, uint256 sharesIn) internal returns (GmQuote memory) {
        return _quote(asset, (_buySpend(sharesIn) * 1e18) / PRICE, 0);
    }

    function _buySpend(uint256 sharesIn) internal pure returns (uint256) {
        // Keep this helper local: an external view call here would consume a
        // one-shot vm.prank before _buy reaches the router.
        return sharesIn - _perimeterFee(sharesIn);
    }

    /// Mirrors cUSD.feeFor: ceil(gross * feeBps / 10_000).
    function _perimeterFee(uint256 gross) internal pure returns (uint256) {
        return Math.mulDiv(gross, FEE, 10_000, Math.Rounding.Ceil);
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
        _buy(q, sharesIn, FEE);
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

    /// Legacy v1 fees (0.30%) may still sit in the router at upgrade time.
    /// v2 never accrues more, but they must stay withdrawable and protected.
    function _seedLegacyFees(uint256 amount) internal {
        stdstore.target(address(router)).sig("accruedUsdtFees()").checked_write(amount);
        usdt.mint(address(router), amount);
    }

    function test_buy_paysPerimeterFeeOnce_deliversStock() public {
        uint256 sharesIn = 600e18; // $600 of savings at par
        GmQuote memory q = _buyQuote(address(tsla), sharesIn);

        vm.prank(user);
        uint256 stockOut = _buy(q, sharesIn, FEE);

        // 0.9% leaves through cUSD's exit perimeter, like any withdrawal.
        assertEq(usdt.balanceOf(address(cusd)), _perimeterFee(600e18), "perimeter fee charged once");
        assertEq(router.accruedUsdtFees(), 0, "router charges nothing of its own");
        assertEq(stockOut, q.quantity, "user receives exactly the signed quantity");
        assertEq(tsla.balanceOf(user), stockOut, "stock delivered to user");
        assertEq(vault.balanceOf(user), 3000e18 - sharesIn, "savings reduced");
        assertEq(usdt.balanceOf(address(router)), 0, "nothing rests in the router");
        assertEq(tsla.balanceOf(address(router)), 0);
        assertEq(vault.balanceOf(address(router)), 0);
    }

    /// No per-product exception: a stock buy costs exactly what a plain
    /// cUSD+ -> USDT withdrawal of the same shares costs.
    function test_buy_costsSameAsPlainWithdrawal() public {
        uint256 sharesIn = 1_000e18;
        address saver = makeAddr("saver");
        usdy.mint(treasury, 1_000e18);
        vm.startPrank(treasury);
        usdy.approve(address(vault), 1_000e18);
        vault.depositAndMint(1_000e18, saver);
        vm.stopPrank();
        vm.prank(saver);
        uint256 withdrawn = vault.redeemToUsdt(sharesIn, 0, saver);

        GmQuote memory q = _buyQuote(address(tsla), sharesIn);
        vm.prank(user);
        _buy(q, sharesIn, FEE);

        // quantity floors to whole stock wei; the router binds within MAX_QUOTE_REMAINDER.
        assertApproxEqAbs(
            Math.mulDiv(q.quantity, PRICE, 1e18), withdrawn, router.MAX_QUOTE_REMAINDER(), "notional == withdrawal"
        );
        assertEq(vault.balanceOf(user), 2_000e18, "only input shares consumed");
    }

    function test_buy_returnsAccrualAboveAttestedDebit() public {
        uint256 sharesIn = 600e18;
        GmQuote memory q = _buyQuote(address(tsla), sharesIn);
        uint256 attestedSpend = _buySpend(sharesIn);

        // The quote was prepared at the old pPlus, then USDY accrued before
        // execution. The vault redeems more than the quote requires.
        oracle.setPrice(1.019e18);
        vm.prank(user);
        uint256 stockOut = router.buyWithSavings(q, "", sharesIn, attestedSpend, 0, FEE);

        // Vault share -> USDY and Instant Manager USDY -> USDT each round
        // down independently, so mirror both conversions exactly, then the
        // perimeter fee on the gross.
        uint256 oraclePrice = oracle.price();
        uint256 gross = Math.mulDiv(Math.mulDiv(sharesIn, vault.pPlus(), oraclePrice), oraclePrice, 1e18);
        uint256 net = gross - _perimeterFee(gross);
        assertEq(stockOut, q.quantity);
        assertEq(router.accruedUsdtFees(), 0, "router accrues nothing");
        assertEq(usdt.balanceOf(user), net - attestedSpend, "accrual excess returned");
        assertEq(usdt.balanceOf(address(router)), 0, "no hidden excess retained");
    }

    function test_sell_reinvestsProceedsIntoSavings() public {
        GmQuote memory bq = _buyQuote(address(tsla), 600e18);
        vm.prank(user);
        uint256 stockOut = _buy(bq, 600e18, FEE);
        uint256 sharesBefore = vault.balanceOf(user);

        GmQuote memory sq = _sellQuote(address(tsla), stockOut);
        vm.prank(user);
        uint256 sharesOut = router.sellToSavings(sq, "", 0, 0, FEE);

        assertEq(tsla.balanceOf(user), 0);
        assertEq(vault.balanceOf(user), sharesBefore + sharesOut, "proceeds keep earning");
        // Round trip = exit fee on the buy + entry fee on the sell; the
        // untouched 2,400 of savings is unaffected (mock GM is spread-free).
        uint256 proceeds = (stockOut * PRICE) / 1e18;
        assertEq(sharesOut, proceeds - _perimeterFee(proceeds), "entry fee charged once");
        assertEq(
            usdt.balanceOf(address(cusd)), _perimeterFee(600e18) + _perimeterFee(proceeds), "both fees at the perimeter"
        );
        assertEq(router.accruedUsdtFees(), 0, "router accrues nothing");
        assertEq(usdt.balanceOf(address(router)), 0, "router keeps nothing");
        assertGe(vault.backingRatioBps(), 10_000, "vault invariant holds through trades");
    }

    function testFuzz_buyAndSell_routerNeverRetainsValue(uint96 rawShares) public {
        uint256 sharesIn = bound(uint256(rawShares), 1e18, 3000e18);
        GmQuote memory bq = _buyQuote(address(tsla), sharesIn);

        vm.prank(user);
        uint256 stockOut = _buy(bq, sharesIn, FEE);
        assertEq(usdt.balanceOf(address(router)), 0);
        assertEq(usdt.balanceOf(address(cusd)), _perimeterFee(sharesIn));

        GmQuote memory sq = _sellQuote(address(tsla), stockOut);
        vm.prank(user);
        router.sellToSavings(sq, "", 0, 0, FEE);

        uint256 proceeds = (stockOut * PRICE) / 1e18;
        assertEq(router.accruedUsdtFees(), 0);
        assertEq(usdt.balanceOf(address(router)), 0);
        assertEq(usdt.balanceOf(address(cusd)), _perimeterFee(sharesIn) + _perimeterFee(proceeds));
    }

    function testFuzz_withdrawAndSweep_cannotInsolventLegacyFees(uint96 rawWithdraw, uint96 rawStray) public {
        _seedLegacyFees(1.8e18);

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
        uint256 reinvest = proceeds - _perimeterFee(proceeds);
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

    function test_routerOwnFeeIsZero_conversionFeeIsLiveFromCusd() public view {
        assertEq(router.stockFeeBps(), 0);
        assertEq(router.conversionFeeBps(), FEE);
    }

    function test_ownerCanWithdrawOnlyAccruedLegacyFees() public {
        _seedLegacyFees(1.8e18);

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
        _seedLegacyFees(0.9e18);
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

    /// The user's authorization must explicitly tolerate the live
    /// conversion fee; any cap other than the legacy 30 below it fails.
    function test_maxFeeBps_bindsLiveConversionFee() public {
        GmQuote memory q = _buyQuote(address(tsla), 300e18);
        vm.prank(user);
        vm.expectRevert(bytes("fee above trade cap"));
        _buy(q, 300e18, FEE - 1);

        vm.prank(user);
        vm.expectRevert(bytes("fee above trade cap"));
        _buy(q, 300e18, 29);

        tsla.mint(user, 1e18);
        GmQuote memory sq = _sellQuote(address(tsla), 1e18);
        vm.prank(user);
        vm.expectRevert(bytes("fee above trade cap"));
        router.sellToSavings(sq, "", 0, 0, 31);
    }

    // ── Transitional legacy path: pre-v2 app builds (maxFeeBps == 30) ───

    /// Old client math: spend = shares * 0.997, fee = ceil(spend*30/9970).
    function _legacySpend(uint256 sharesIn) internal pure returns (uint256) {
        return Math.mulDiv(sharesIn, 9970, 10_000);
    }

    function test_legacyBuy_settlesAtThirtyBps_withoutPerimeter() public {
        uint256 sharesIn = 600e18;
        uint256 spend = _legacySpend(sharesIn);
        GmQuote memory q = _quote(address(tsla), (spend * 1e18) / PRICE, 0);

        vm.prank(user);
        uint256 stockOut = router.buyWithSavings(q, "", sharesIn, spend, 0, 30);

        uint256 fee = Math.mulDiv(spend, 30, 9970, Math.Rounding.Ceil);
        assertEq(stockOut, q.quantity);
        assertEq(router.accruedUsdtFees(), fee, "legacy 30 bps accrued in router");
        assertEq(usdt.balanceOf(address(cusd)), 0, "perimeter not charged");
        assertEq(usdt.balanceOf(address(router)), fee);
    }

    function test_legacySell_settlesAtThirtyBps_withoutPerimeter() public {
        tsla.mint(user, 2e18);
        GmQuote memory sq = _sellQuote(address(tsla), 2e18);
        uint256 proceeds = 600e18;
        uint256 fee = (proceeds * 30) / 10_000;

        vm.prank(user);
        uint256 sharesOut = router.sellToSavings(sq, "", 0, proceeds - fee, 30);

        assertEq(sharesOut, proceeds - fee, "old client's floor met exactly");
        assertEq(router.accruedUsdtFees(), fee);
        assertEq(usdt.balanceOf(address(cusd)), 0, "perimeter not charged");
    }

    /// Codex audit [P1]: oversized shares on the fee-free legacy path would
    /// be a withdrawal that skips the 0.9% perimeter. Only rounding/accrual
    /// excess is tolerated there.
    function test_legacyBuy_rejectsOversizedShares() public {
        uint256 spend = _legacySpend(10e18);
        GmQuote memory q = _quote(address(tsla), (spend * 1e18) / PRICE, 0);
        vm.prank(user);
        vm.expectRevert(bytes("legacy excess too large"));
        router.buyWithSavings(q, "", 2_000e18, spend, 0, 30);
    }

    function test_legacyBuy_toleratesAccrualExcess() public {
        uint256 sharesIn = 600e18;
        uint256 spend = _legacySpend(sharesIn);
        GmQuote memory q = _quote(address(tsla), (spend * 1e18) / PRICE, 0);
        // ~0.25% accrual since the last accrue(): inside the 50 bps bound.
        oracle.setPrice(1.003e18);
        vm.prank(user);
        router.buyWithSavings(q, "", sharesIn, spend, 0, 30);
        assertGt(usdt.balanceOf(user), 0, "accrual excess refunded");

        // A 1.9% jump is far beyond honest staleness and is refused.
        GmQuote memory q2 = _quote(address(tsla), (spend * 1e18) / PRICE, 0);
        oracle.setPrice(1.022e18);
        vm.prank(user);
        vm.expectRevert(bytes("legacy excess too large"));
        router.buyWithSavings(q2, "", sharesIn, spend, 0, 30);
    }

    /// On the v2 path an oversized buy simply pays the exit fee on the excess,
    /// exactly like a withdrawal: nothing escapes the perimeter.
    function test_v2Buy_oversizedSharesPayPerimeterOnExcess() public {
        uint256 spend = _buySpend(10e18);
        GmQuote memory q = _quote(address(tsla), (spend * 1e18) / PRICE, 0);
        vm.prank(user);
        router.buyWithSavings(q, "", 2_000e18, spend, 0, FEE);
        assertEq(usdt.balanceOf(address(cusd)), _perimeterFee(2_000e18), "fee on everything redeemed");
        assertEq(usdt.balanceOf(user), 2_000e18 - _perimeterFee(2_000e18) - spend);
    }

    /// A pre-v2 build's exact buy (shares sized for 0.30%) cannot be pushed
    /// through the 0.9% path: the legacy branch is what keeps it working.
    function test_v2Path_wouldRejectLegacySizedBuy() public {
        uint256 sharesIn = 600e18;
        uint256 spend = _legacySpend(sharesIn);
        GmQuote memory q = _quote(address(tsla), (spend * 1e18) / PRICE, 0);
        vm.prank(user);
        vm.expectRevert(bytes("insufficient redeemed usdt"));
        router.buyWithSavings(q, "", sharesIn, spend, 0, FEE);
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
        assertEq(router.accruedUsdtFees(), 0);
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
        assertEq(_buy(q, sharesIn, FEE), q.quantity);
    }

    function test_quoteRemainderAboveMicroUsdt_reverts() public {
        uint256 sharesIn = 300e18;
        GmQuote memory q = _buyQuote(address(tsla), sharesIn);
        q.quantity -= router.MAX_QUOTE_REMAINDER() / 300 + 1;

        vm.prank(user);
        vm.expectRevert(bytes("overspend vs quote"));
        _buy(q, sharesIn, FEE);
    }

    function test_underspendVsQuote_reverts() public {
        uint256 sharesIn = 300e18;
        GmQuote memory q = _buyQuote(address(tsla), sharesIn);
        q.quantity += 1;

        vm.prank(user);
        vm.expectRevert(bytes("underspend vs quote"));
        _buy(q, sharesIn, FEE);
    }

    function test_wrongQuoteSide_revertsLocally() public {
        GmQuote memory buy = _buyQuote(address(tsla), 300e18);
        buy.side = 1;
        vm.prank(user);
        vm.expectRevert(bytes("wrong quote side"));
        _buy(buy, 300e18, FEE);

        GmQuote memory sell = _sellQuote(address(tsla), 1e18);
        sell.side = 0;
        vm.prank(user);
        vm.expectRevert(bytes("wrong quote side"));
        router.sellToSavings(sell, "", 0, 0, FEE);
    }

    function test_zeroPrice_revertsLocally() public {
        GmQuote memory q = _buyQuote(address(tsla), 300e18);
        q.price = 0;
        vm.prank(user);
        vm.expectRevert(bytes("zero price"));
        _buy(q, 300e18, FEE);
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
        assertEq(usdt.balanceOf(address(router)), 500e18, "stray USDT untouched");
        assertEq(router.accruedUsdtFees(), 0, "nothing accounted as fees");
    }

    function test_wrongChainId_reverts() public {
        GmQuote memory q = _buyQuote(address(tsla), 300e18);
        q.chainId = block.chainid + 1;
        vm.prank(user);
        vm.expectRevert(bytes("wrong chain"));
        _buy(q, 300e18, 100);
    }

    // ── Sponsor boundary: cUSD+ trades gated, raw exit permissionless ──

    function test_sellToUsdt_succeedsWithoutSponsoredOrigin_andChargesNoFee() public {
        address holder = makeAddr("directHolder");
        tsla.mint(holder, 10e18);
        vm.prank(holder, holder);
        tsla.approve(address(router), type(uint256).max);

        GmQuote memory sq = _sellQuote(address(tsla), 10e18);
        vm.prank(holder, holder);
        uint256 usdtOut = router.sellToUsdt(sq, "", 0, 0, 0);

        assertEq(tsla.balanceOf(holder), 0, "stock redeemed");
        assertEq(usdtOut, 3000e18, "no cUSD perimeter crossed, no router fee");
        assertEq(usdt.balanceOf(holder), usdtOut, "holder receives raw USDT");
        assertEq(vault.balanceOf(holder), 0, "raw exit cannot mint cUSD+");
        assertEq(router.accruedUsdtFees(), 0);
        assertEq(usdt.balanceOf(address(cusd)), 0, "perimeter untouched");
    }

    function test_sellToUsdt_enforcesNetFloor_andRollsBackStockTransfer() public {
        address holder = makeAddr("floorHolder");
        tsla.mint(holder, 1e18);
        vm.prank(holder, holder);
        tsla.approve(address(router), type(uint256).max);

        GmQuote memory sq = _sellQuote(address(tsla), 1e18);
        vm.prank(holder, holder);
        vm.expectRevert("insufficient net usdt out");
        router.sellToUsdt(sq, "", 0, 300e18 + 1, 0);

        assertEq(tsla.balanceOf(holder), 1e18, "revert restores stock");
        assertEq(usdt.balanceOf(holder), 0, "no partial payout");
        assertEq(router.accruedUsdtFees(), 0, "nothing accrued on revert");
    }

    /// sellToUsdt never crosses the perimeter, so even a zero cap passes.
    function test_sellToUsdt_acceptsZeroFeeCap() public {
        address holder = makeAddr("feeCapHolder");
        tsla.mint(holder, 1e18);
        vm.prank(holder, holder);
        tsla.approve(address(router), type(uint256).max);

        GmQuote memory sq = _sellQuote(address(tsla), 1e18);
        vm.prank(holder, holder);
        assertEq(router.sellToUsdt(sq, "", 0, 0, 0), 300e18);
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
