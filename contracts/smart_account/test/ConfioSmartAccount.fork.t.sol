// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * Live BSC rehearsal of Cuenta inteligente against the REAL contracts:
 * CusdVault (upgraded on the fork to the candidate with decision 32),
 * CusdPlusVault, ConfioStockRouter, ConfioSwapRouter, PancakeSwap and the
 * two Chainlink feeds.
 *
 *   forge test --match-path "test/*.fork.t.sol" \
 *     --fork-url https://bsc-dataseed.bnbchain.org -vv
 *
 * What the fork does on the Safe's behalf (pranked, as the rollout will):
 * upgrade cUSD to the candidate implementation and recognise the factory.
 * The relayer is the live KMS sponsor as tx.origin.
 *
 * What is mocked, and why:
 * - Ondo's GM token manager. A stock trade needs an Ondo-signed quote that
 *   cannot be produced in a test, so GM's code is replaced on the fork by a
 *   stand-in that settles at the quote's own price. The stock ROUTER and
 *   both vaults in those tests are the live ones.
 * - Feed timestamps after a time warp. A forced sale needs the 30-day period
 *   and the notice to pass; the live feeds are then stale by construction.
 *   The live answer is kept and re-stamped. The un-warped tests read the
 *   feeds exactly as they are.
 *
 * Skips (passes as a no-op) when not run against a fork.
 */
import {Test, console2} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {IERC20Metadata} from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Metadata.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {CusdVault} from "cusd-plus/CusdVault.sol";
import {ConfioStockRouter, GmQuote} from "ondo-stocks/ConfioStockRouter.sol";
import {ConfioSwapRouter} from "crypto-swap/ConfioSwapRouter.sol";
import {ConfioSmartAccount} from "../ConfioSmartAccount.sol";
import {ConfioSmartAccountFactory} from "../ConfioSmartAccountFactory.sol";
import {ConfioSmartAccountFeeCollector} from "../ConfioSmartAccountFeeCollector.sol";
import {IConfioSmartAccount} from "../interfaces/IConfioSmartAccount.sol";
import {MockToken} from "./Mocks.sol";

interface ILivePlus {
    function subscribeAndMint(uint256 usdtIn, uint256 minUsdyOut, address recipient) external returns (uint256);
    function isSponsor(address) external view returns (bool);
    function pPlus() external view returns (uint256);
    function accrue() external;
    function balanceOf(address) external view returns (uint256);
    function transfer(address, uint256) external returns (bool);
    function CUSD() external view returns (address);
}

interface IFeed {
    function description() external view returns (string memory);
    function decimals() external view returns (uint8);
    function latestRoundData() external view returns (uint80, int256, uint256, uint256, uint80);
}

/// Stand-in for Ondo's GMTokenManager, etched over the live one. Settles at
/// the quote's price, pays and pulls USDT, no signature check.
contract ForkGM {
    function mintWithAttestation(GmQuote calldata quote, bytes memory, address depositToken, uint256 amount)
        external
        returns (uint256)
    {
        require(IERC20(depositToken).transferFrom(msg.sender, address(this), amount), "deposit failed");
        MockToken(quote.asset).mint(msg.sender, quote.quantity);
        return quote.quantity;
    }

    function redeemWithAttestation(GmQuote calldata quote, bytes memory, address receiveToken, uint256 minOut)
        external
        returns (uint256 out)
    {
        require(IERC20(quote.asset).transferFrom(msg.sender, address(this), quote.quantity), "stock failed");
        out = (quote.quantity * quote.price) / 1e18;
        require(out >= minOut, "gm: min receive");
        require(IERC20(receiveToken).transfer(msg.sender, out), "proceeds failed");
    }
}

contract ConfioSmartAccountForkTest is Test {
    address constant SAFE = 0xF29A418744E793973BF4eEc676F8a30B2793b623;
    address constant KMS = 0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D;
    address constant CUSD_PLUS = 0x3C29417eb4314155e63d4C7D4507852b87763Ed1;
    address constant CUSD = 0x6101cC370635cF2c7f2725EaB010aC407A8d543F;
    address constant USDT = 0x55d398326f99059fF775485246999027B3197955;
    address constant STOCK_ROUTER = 0x40c8e134BCAf44EEf9e7D184846F36c9862329c3;
    /// settings CRYPTO_SWAP_ROUTER_ADDRESS (mainnet).
    address constant SWAP_ROUTER = 0xA7C27684aB38eC369cB1F4474f279ea503dbF712;
    address constant BTCB = 0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c;
    address constant XAUT = 0x21cAef8A43163Eea865baeE23b9C2E327696A3bf;
    /// ConfioToken v2 (contracts/cusd_plus/DEPLOYMENT.md).
    address constant CONFIO = 0xF5765933764562A51e179F6AF2b19b7a3d506101;
    address constant BTC_FEED = 0x264990fbd0A4796A3E3d8E37C4d5F87a3aCa5Ebf;
    address constant XAU_FEED = 0x86896fEB19D8A607c3b11f2aF50A0f239Bd71CD0;
    /// USDT / USD feed read by Ondo's USDon manager inside every USDT -> USDY
    /// subscription (seen in the fork trace of CusdPlusVault.wrapCusd).
    address constant ONDO_USDT_FEED = 0xB97Ad0E74fa7d920791E90258A6E2085088b4320;

    uint256 constant MONTHLY = 14.99e18;
    uint256 constant ANNUAL = 149.99e18;
    uint8 constant PLUS = 0;
    uint8 constant CUSD_ = 1;
    IConfioSmartAccount.Plan constant M = IConfioSmartAccount.Plan.Monthly;

    ConfioSmartAccountFeeCollector collector;
    ConfioSmartAccount implementation;
    ConfioSmartAccountFactory factory;
    ConfioSmartAccount acct;
    MockToken stock;

    address treasury = makeAddr("forkTreasury");
    address bank = makeAddr("forkBank");
    address alice = makeAddr("forkAlice");
    address bob = makeAddr("forkBob");
    address carol = makeAddr("forkCarol");
    address referrer = makeAddr("forkReferrer");

    function _forked() private view returns (bool) {
        return block.chainid == 56 && CUSD_PLUS.code.length > 0;
    }

    function setUp() public {
        if (!_forked()) return;

        // ── the Safe's cUSD upgrade (decision 32), state preserved ──────
        CusdVault cusd = CusdVault(CUSD);
        assertEq(cusd.owner(), SAFE, "cUSD not Safe-owned");
        uint256 supply = cusd.totalSupply();
        uint256 feeBps = cusd.feeBps();
        uint256 cap = cusd.referralShareCapBps();
        address delegate = cusd.batchDelegate();
        address savings = cusd.savingsVault();
        uint256 fees = cusd.accruedEntryFees() + cusd.accruedExitFees();
        CusdVault candidate = new CusdVault(USDT);
        vm.prank(SAFE);
        cusd.upgradeToAndCall(address(candidate), "");
        assertEq(cusd.totalSupply(), supply);
        assertEq(cusd.feeBps(), feeBps);
        assertEq(cusd.referralShareCapBps(), cap);
        assertEq(cusd.batchDelegate(), delegate);
        assertEq(cusd.savingsVault(), savings);
        assertEq(cusd.accruedEntryFees() + cusd.accruedExitFees(), fees);
        assertTrue(cusd.isFullyBacked());
        assertTrue(cusd.isSponsor(KMS));

        // ── deploy the package ──────────────────────────────────────────
        collector = new ConfioSmartAccountFeeCollector(IERC20(CUSD), IERC20(CUSD_PLUS), treasury);
        address predicted = vm.computeCreateAddress(address(this), vm.getNonce(address(this)) + 2);
        implementation = new ConfioSmartAccount(
            predicted,
            CUSD,
            CUSD_PLUS,
            USDT,
            CONFIO,
            STOCK_ROUTER,
            SWAP_ROUTER,
            address(collector),
            BTCB,
            BTC_FEED,
            XAUT,
            XAU_FEED
        );
        ConfioSmartAccountFactory logic = new ConfioSmartAccountFactory(CUSD_PLUS, STOCK_ROUTER);
        factory = ConfioSmartAccountFactory(
            address(
                new ERC1967Proxy(
                    address(logic),
                    abi.encodeCall(
                        ConfioSmartAccountFactory.initialize, (SAFE, address(implementation), MONTHLY, ANNUAL)
                    )
                )
            )
        );
        assertEq(address(factory), predicted);
        vm.startPrank(SAFE);
        cusd.setSmartAccountFactory(address(factory), true);
        factory.enableInheritance();
        vm.stopPrank();

        // ── dollars, minted through the live perimeter ──────────────────
        deal(USDT, bank, 5_000e18);
        vm.startPrank(bank, KMS);
        IERC20(USDT).approve(CUSD_PLUS, type(uint256).max);
        IERC20(USDT).approve(CUSD, type(uint256).max);
        ILivePlus(CUSD_PLUS).subscribeAndMint(2_000e18, 0, bank);
        cusd.mintWithFee(2_000e18, 0, bank);
        vm.stopPrank();

        vm.prank(alice);
        acct = ConfioSmartAccount(factory.createAccount());
        stock = new MockToken("FORKon", 18);
    }

    // ── helpers ─────────────────────────────────────────────────────────

    function _giveCusd(address to, uint256 amount) private {
        vm.prank(bank);
        IERC20(CUSD).transfer(to, amount);
    }

    function _givePlus(address to, uint256 shares) private {
        vm.prank(bank);
        IERC20(CUSD_PLUS).transfer(to, shares);
    }

    function _bal(address token, address who) private view returns (uint256) {
        return IERC20(token).balanceOf(who);
    }

    function _subscribe() private {
        vm.prank(alice, KMS);
        acct.subscribe(M, type(uint256).max);
    }

    function _route(address a, uint24 fee, address b) private pure returns (bytes memory) {
        return abi.encode(uint8(0), abi.encodePacked(a, fee, b));
    }

    /// The catalog routes: USDT/BTCB fee 100, USDT/XAUt fee 500.
    function _poolFee(address token) private pure returns (uint24) {
        return token == BTCB ? 100 : 500;
    }

    function _buyData(uint8 source, address token, uint256 amountIn) private pure returns (bytes memory) {
        return
            abi.encodeCall(
                ConfioSwapRouter.buy, (source, amountIn, 1, _route(USDT, _poolFee(token), token), token, 1, 90)
            );
    }

    function _sellData(uint8 dest, address token, uint256 amountIn) private pure returns (bytes memory) {
        return
            abi.encodeCall(
                ConfioSwapRouter.sell, (dest, token, amountIn, _route(token, _poolFee(token), USDT), 1, 1, 90)
            );
    }

    function _ownerBuy(uint8 source, address token, uint256 amountIn) private {
        address dollar = source == PLUS ? CUSD_PLUS : CUSD;
        bytes memory data = _buyData(source, token, amountIn);
        vm.prank(alice, KMS);
        acct.trade(SWAP_ROUTER, data, dollar, token, amountIn, 1);
    }

    function _feedPrice(address feed) private view returns (uint256 price, uint256 updatedAt) {
        (, int256 answer,, uint256 at,) = IFeed(feed).latestRoundData();
        return (uint256(answer), at);
    }

    /// Keeps the live answer, re-stamps it at the (warped) block time.
    /// The third feed is not ours: Ondo's USDon manager prices USDT with it
    /// and refuses a stale round (OraclePriceOutdated), so on a warped fork
    /// every cUSD+ entry would fail for a reason that does not exist on
    /// the live chain.
    function _restampFeeds() private {
        _restamp(BTC_FEED);
        _restamp(XAU_FEED);
        _restamp(ONDO_USDT_FEED);
    }

    function _restamp(address feed) private {
        (uint80 round, int256 answer,,, uint80 answeredIn) = IFeed(feed).latestRoundData();
        vm.mockCall(
            feed,
            abi.encodeCall(IFeed.latestRoundData, ()),
            abi.encode(round, answer, block.timestamp, block.timestamp, answeredIn)
        );
    }

    function _toSaleAllowed() private {
        vm.warp(acct.paidUntil());
        vm.prank(KMS, KMS);
        acct.startPaymentNotice();
        vm.warp(block.timestamp + 7 days);
    }

    function _legs(address venue, address token, uint256 maxIn, bytes memory data)
        private
        pure
        returns (IConfioSmartAccount.SaleLeg[] memory legs)
    {
        legs = new IConfioSmartAccount.SaleLeg[](1);
        legs[0] = IConfioSmartAccount.SaleLeg({venue: venue, tokenIn: token, maxIn: maxIn, data: data});
    }

    /// Units of `token` worth `usd` at the live feed price.
    function _unitsFor(address token, address feed, uint256 usd) private view returns (uint256) {
        (uint256 price,) = _feedPrice(feed);
        return (usd * 10 ** (IERC20Metadata(token).decimals() + IFeed(feed).decimals())) / (price * 1e18);
    }

    function _etchGm() private {
        address gm = address(ConfioStockRouter(STOCK_ROUTER).GM());
        vm.etch(gm, address(new ForkGM()).code);
        deal(USDT, gm, 100_000e18);
    }

    function _quote(uint256 quantity, uint256 price, uint8 side) private view returns (GmQuote memory) {
        return GmQuote({
            chainId: block.chainid,
            attestationId: 1,
            userId: bytes32(0),
            asset: address(stock),
            price: price,
            quantity: quantity,
            expiration: block.timestamp + 300,
            side: side,
            additionalData: bytes32(0)
        });
    }

    // ── what the account assumes about the live system ──────────────────

    function test_fork_liveAssumptions() public view {
        if (!_forked()) return;
        // X7: decimals asserted, not assumed.
        assertEq(IERC20Metadata(CUSD).decimals(), 18);
        assertEq(IERC20Metadata(CUSD_PLUS).decimals(), 18);
        assertEq(IERC20Metadata(USDT).decimals(), 18);
        assertEq(IERC20Metadata(BTCB).decimals(), 18);
        assertEq(IERC20Metadata(XAUT).decimals(), 6);
        assertEq(IERC20Metadata(CONFIO).decimals(), 18);
        // The relayer key is in both sponsor sets; both routers are relays.
        assertTrue(ILivePlus(CUSD_PLUS).isSponsor(KMS));
        assertTrue(CusdVault(CUSD).isSponsor(KMS));
        assertTrue(ILivePlus(CUSD_PLUS).isSponsor(STOCK_ROUTER));
        assertTrue(ILivePlus(CUSD_PLUS).isSponsor(SWAP_ROUTER));
        assertTrue(CusdVault(CUSD).isSponsor(SWAP_ROUTER));
        assertEq(ILivePlus(CUSD_PLUS).CUSD(), CUSD);
        // The deployed swap router is wired to the live vault and Safe (X1
        // itself, the bytecode match, is not done here).
        assertEq(address(ConfioSwapRouter(SWAP_ROUTER).VAULT()), CUSD_PLUS);
        assertEq(ConfioSwapRouter(SWAP_ROUTER).owner(), SAFE);
        assertEq(address(ConfioStockRouter(STOCK_ROUTER).VAULT()), CUSD_PLUS);
        assertEq(ConfioStockRouter(STOCK_ROUTER).VERSION(), 3);
        assertGt(ILivePlus(CUSD_PLUS).pPlus(), 1e18, "pPlus is a USD price per share");
        assertLe(CusdVault(CUSD).feeBps(), 90);
        // The clone and the implementation.
        assertEq(acct.FACTORY(), address(factory));
        assertEq(factory.predictAddress(alice), address(acct));
        assertLt(address(implementation).code.length, 24_576);
    }

    /// C2: the two live feeds, read as they are.
    function test_fork_liveFeeds() public view {
        if (!_forked()) return;
        assertEq(IFeed(BTC_FEED).description(), "BTC / USD");
        assertEq(IFeed(XAU_FEED).description(), "XAU / USD");
        assertEq(IFeed(BTC_FEED).decimals(), 8);
        assertEq(IFeed(XAU_FEED).decimals(), 8);
        (uint256 btc, uint256 btcAt) = _feedPrice(BTC_FEED);
        (uint256 xau, uint256 xauAt) = _feedPrice(XAU_FEED);
        console2.log("BTC / USD (8 dec):", btc, "age s:", block.timestamp - btcAt);
        console2.log("XAU / USD (8 dec):", xau, "age s:", block.timestamp - xauAt);
        assertGt(btc, 1_000e8);
        assertGt(xau, 500e8);
        assertLe(block.timestamp - btcAt, 1 hours, "BTC feed older than the account's maximum age");
        // The gold feed stops while the gold market is closed: informative.
        if (block.timestamp - xauAt > 26 hours) console2.log("XAU feed is stale now (market closed)");
    }

    // ── subscription and the fee, live vaults ───────────────────────────

    function test_fork_subscribe_inCusd_thenRenew_andSweep() public {
        if (!_forked()) return;
        _giveCusd(address(acct), 40e18);
        _subscribe();
        assertEq(_bal(CUSD, address(collector)), MONTHLY);
        assertEq(acct.paidUntil(), block.timestamp + 30 days);

        vm.warp(acct.paidUntil());
        vm.prank(KMS, KMS);
        acct.collectFee();
        assertEq(_bal(CUSD, address(collector)), 2 * MONTHLY);
        vm.prank(KMS, KMS);
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.collectFee();

        collector.sweep();
        assertEq(_bal(CUSD, treasury), 2 * MONTHLY);
    }

    function test_fork_subscribe_inCusdPlus_inKind_noConversionFee() public {
        if (!_forked()) return;
        _givePlus(address(acct), 30e18);
        uint256 fees = CusdVault(CUSD).accruedEntryFees() + CusdVault(CUSD).accruedExitFees();
        _subscribe();
        uint256 p = ILivePlus(CUSD_PLUS).pPlus();
        uint256 expected = (MONTHLY * 1e18 + p - 1) / p;
        assertEq(_bal(CUSD_PLUS, address(collector)), expected, "shares = ceil(fee / pPlus)");
        assertLt(expected, MONTHLY, "fewer shares than dollars: pPlus > 1");
        assertEq(_bal(CUSD_PLUS, address(acct)), 30e18 - expected);
        assertEq(CusdVault(CUSD).accruedEntryFees() + CusdVault(CUSD).accruedExitFees(), fees, "no conversion fee");
        collector.sweep(IERC20(CUSD_PLUS));
        assertEq(_bal(CUSD_PLUS, treasury), expected);
    }

    // ── trading, live swap router and PancakeSwap ───────────────────────

    function test_fork_trade_bitcoinAndGold_roundTrip_andLivePriceVsFeed() public {
        if (!_forked()) return;
        _giveCusd(address(acct), MONTHLY + 50e18);
        _givePlus(address(acct), 50e18);
        _subscribe();

        _ownerBuy(CUSD_, BTCB, 50e18);
        _ownerBuy(PLUS, XAUT, 50e18);
        uint256 btc = _bal(BTCB, address(acct));
        uint256 gold = _bal(XAUT, address(acct));
        assertGt(btc, 0);
        assertGt(gold, 0);
        assertEq(IERC20(CUSD).allowance(address(acct), SWAP_ROUTER), 0);
        assertEq(IERC20(CUSD_PLUS).allowance(address(acct), SWAP_ROUTER), 0);

        // Sell back and hold the live execution to the live feeds, the same
        // arithmetic as the forced-sale check: dollars per unit sold are at
        // most 3% under the feed after the 0.9% entry fee.
        uint256 cusdBefore = _bal(CUSD, address(acct));
        bytes memory sellBtc = _sellData(CUSD_, BTCB, btc);
        vm.prank(alice, KMS);
        acct.trade(SWAP_ROUTER, sellBtc, BTCB, CUSD, btc, 1);
        uint256 got = _bal(CUSD, address(acct)) - cusdBefore;
        (uint256 price,) = _feedPrice(BTC_FEED);
        uint256 refUsd = (btc * price) / 1e8;
        console2.log("BTCB sale: got / feed value (bps):", (got * 10_000) / refUsd);
        assertGe(got, (refUsd * 9_910 * 9_700) / 1e8, "live BTCB execution below the feed tolerance");
        assertLe(got, refUsd, "more than the feed value");

        (uint256 xauPrice, uint256 xauAt) = _feedPrice(XAU_FEED);
        uint256 plusBefore = _bal(CUSD_PLUS, address(acct));
        bytes memory sellGold = _sellData(PLUS, XAUT, gold);
        vm.prank(alice, KMS);
        acct.trade(SWAP_ROUTER, sellGold, XAUT, CUSD_PLUS, gold, 1);
        uint256 gotUsd = ((_bal(CUSD_PLUS, address(acct)) - plusBefore) * ILivePlus(CUSD_PLUS).pPlus()) / 1e18;
        uint256 goldRef = (gold * xauPrice * 1e18) / 1e14;
        console2.log("XAUt sale: got / feed value (bps):", (gotUsd * 10_000) / goldRef);
        if (block.timestamp - xauAt <= 26 hours) {
            assertGe(gotUsd, (goldRef * 9_910 * 9_700) / 1e8, "live XAUt execution below the feed tolerance");
        }
        assertEq(IERC20(BTCB).allowance(address(acct), SWAP_ROUTER), 0);
        assertEq(IERC20(XAUT).allowance(address(acct), SWAP_ROUTER), 0);
    }

    // ── rules, live vaults ──────────────────────────────────────────────

    function _rule(IConfioSmartAccount.RuleKind kind, address tokenIn, uint256 amountUsd)
        private
        pure
        returns (IConfioSmartAccount.RuleInput memory r)
    {
        r.kind = kind;
        r.frequency = IConfioSmartAccount.Frequency.Daily;
        r.tokenIn = tokenIn;
        r.amountUsd = amountUsd;
    }

    function _createRule(IConfioSmartAccount.RuleInput memory r) private returns (uint256 id) {
        vm.prank(alice, KMS);
        id = acct.createRule(r);
    }

    function _run(uint256 id, bytes memory data) private {
        vm.prank(KMS, KMS);
        acct.executeRule(id, data, address(0), 0);
    }

    function test_fork_sendRules_everyDollarCombination() public {
        if (!_forked()) return;
        _giveCusd(address(acct), MONTHLY + 100e18);
        _givePlus(address(acct), 100e18);
        _subscribe();
        IConfioSmartAccount.RuleInput memory r = _rule(IConfioSmartAccount.RuleKind.Send, CUSD, 20e18);
        r.payee = carol;
        uint256 fromCusd = _createRule(r);
        r.tokenIn = CUSD_PLUS;
        uint256 fromPlus = _createRule(r);
        uint256 p = ILivePlus(CUSD_PLUS).pPlus();
        uint256 fees = CusdVault(CUSD).accruedEntryFees() + CusdVault(CUSD).accruedExitFees();

        // cUSD -> cUSD payee, in kind.
        _run(fromCusd, abi.encode(CUSD_, uint256(20e18)));
        assertEq(_bal(CUSD, carol), 20e18);
        // cUSD+ -> cUSD+ payee, in kind.
        _run(fromPlus, abi.encode(PLUS, uint256(1)));
        uint256 shares = (20e18 * 1e18 + p - 1) / p;
        assertEq(_bal(CUSD_PLUS, carol), shares);

        vm.warp(block.timestamp + 1 days);
        _restampFeeds();
        uint256 acctPlus = _bal(CUSD_PLUS, address(acct));
        uint256 acctCusd = _bal(CUSD, address(acct));
        // cUSD -> cUSD+ payee: live wrapCusd, minted straight to the payee.
        _run(fromCusd, abi.encode(PLUS, uint256(1)));
        uint256 wrapped = _bal(CUSD_PLUS, carol) - shares;
        console2.log("wrap 20 cUSD -> shares worth (1e18 USD):", (wrapped * ILivePlus(CUSD_PLUS).pPlus()) / 1e18);
        assertApproxEqRel((wrapped * ILivePlus(CUSD_PLUS).pPlus()) / 1e18, 20e18, 0.005e18, "fee-free wrap");
        assertEq(_bal(CUSD_PLUS, address(acct)), acctPlus, "the account holds none of the other dollar");
        // cUSD+ -> cUSD payee: live unwrapToCusd.
        _run(fromPlus, abi.encode(CUSD_, uint256(1)));
        uint256 unwrapped = _bal(CUSD, carol) - 20e18;
        console2.log("unwrap US$20 of cUSD+ -> cUSD:", unwrapped);
        assertApproxEqRel(unwrapped, 20e18, 0.005e18, "fee-free unwrap");
        assertEq(_bal(CUSD, address(acct)), acctCusd - 20e18, "only the cUSD rule's own spend");

        assertEq(CusdVault(CUSD).accruedEntryFees() + CusdVault(CUSD).accruedExitFees(), fees, "no conversion fee");
        assertEq(IERC20(CUSD).allowance(address(acct), CUSD_PLUS), 0);
    }

    function test_fork_payoutRules_fromBothDollars() public {
        if (!_forked()) return;
        _giveCusd(address(acct), MONTHLY + 100e18);
        _givePlus(address(acct), 100e18);
        _subscribe();
        IConfioSmartAccount.RuleInput memory r = _rule(IConfioSmartAccount.RuleKind.Payout, CUSD, 50e18);
        r.payoutRef = keccak256("br_pix:destination");
        uint256 fromCusd = _createRule(r);
        r.tokenIn = CUSD_PLUS;
        uint256 fromPlus = _createRule(r);
        address bridge = makeAddr("forkBridgeDeposit");

        _run(fromCusd, abi.encode(bridge, uint256(49.5e18)));
        assertEq(_bal(USDT, bridge), 49.55e18, "cUSD exit: 0.9% fee");
        _run(fromPlus, abi.encode(bridge, uint256(49e18)));
        uint256 second = _bal(USDT, bridge) - 49.55e18;
        console2.log("payout of US$50 of cUSD+ -> USDT:", second);
        assertApproxEqRel(second, 49.55e18, 0.005e18, "cUSD+ exit: 0.9% fee");
        assertEq(_bal(USDT, address(acct)), 0);
    }

    function test_fork_buyRule_bitcoin_withReferral() public {
        if (!_forked()) return;
        _giveCusd(address(acct), MONTHLY + 100e18);
        _subscribe();
        IConfioSmartAccount.RuleInput memory r = _rule(IConfioSmartAccount.RuleKind.Buy, CUSD, 50e18);
        r.tokenOut = BTCB;
        uint256 id = _createRule(r);
        bytes memory data = abi.encode(SWAP_ROUTER, _buyData(CUSD_, BTCB, 50e18), uint256(1));
        uint256 cap = CusdVault(CUSD).referralShareCapBps();

        // Decision 32 on the live (upgraded) vault: the account arms.
        vm.prank(KMS, KMS);
        acct.executeRule(id, data, referrer, cap);
        assertGt(_bal(BTCB, address(acct)), 0);
        assertEq(_bal(CUSD, address(acct)), 50e18);
        uint256 fee = CusdVault(CUSD).feeFor(50e18);
        assertEq(_bal(CUSD, referrer), (fee * cap) / 10_000, "the referrer's share of the exit fee");
        assertEq(IERC20(CUSD).allowance(address(acct), SWAP_ROUTER), 0);
    }

    // ── USDT conversion, live vaults ────────────────────────────────────

    function test_fork_convertUsdt_toBothDollars() public {
        if (!_forked()) return;
        _giveCusd(address(acct), MONTHLY);
        _subscribe();
        uint256 floor = (100e18 * (10_000 - 90 - 50)) / 10_000;

        deal(USDT, address(acct), 100e18);
        vm.prank(KMS, KMS);
        acct.convertUsdt(CUSD_, floor, address(0), 0);
        assertEq(_bal(CUSD, address(acct)), 99.1e18);

        deal(USDT, address(acct), 100e18);
        uint256 before = _bal(CUSD_PLUS, address(acct));
        vm.prank(KMS, KMS);
        acct.convertUsdt(PLUS, floor, address(0), 0);
        uint256 usd = ((_bal(CUSD_PLUS, address(acct)) - before) * ILivePlus(CUSD_PLUS).pPlus()) / 1e18;
        console2.log("100 USDT -> cUSD+ worth (1e18 USD):", usd);
        // The live entry lands inside the account's hard-coded tolerance.
        assertGe(usd, floor);
        assertEq(_bal(USDT, address(acct)), 0);
        assertEq(IERC20(USDT).allowance(address(acct), CUSD_PLUS), 0);
        assertEq(IERC20(USDT).allowance(address(acct), CUSD), 0);
    }

    // ── forced sales, live router, pools and feed answers ───────────────

    function _forcedCryptoSale(address token, address feed, uint8 dest) private {
        _giveCusd(address(acct), MONTHLY + 60e18);
        _subscribe();
        _ownerBuy(CUSD_, token, 60e18);
        assertEq(_bal(CUSD, address(acct)), 0);
        _toSaleAllowed();

        // Net proceeds aimed at fee + 2%: inside [shortfall, shortfall*1.05+1].
        uint256 amount = _unitsFor(token, feed, (MONTHLY * 10_300) / 10_000);
        IConfioSmartAccount.SaleLeg[] memory legs = _legs(SWAP_ROUTER, token, amount, _sellData(dest, token, amount));

        // The live feed is 37 days old on the warped fork: refused. (Ondo's
        // own feed is re-stamped first so that the refusal seen is ours.)
        _restamp(ONDO_USDT_FEED);
        vm.prank(KMS, KMS);
        vm.expectRevert(ConfioSmartAccount.StaleFeed.selector);
        acct.forcedSale(legs, 0, address(0), 0);

        _restampFeeds();
        uint64 period = acct.paidUntil();
        uint256 before = _bal(token, address(acct));
        vm.prank(KMS, KMS);
        acct.forcedSale(legs, MONTHLY, address(0), 0);
        assertEq(before - _bal(token, address(acct)), amount);
        assertEq(acct.forcedSaleForPeriod(), period);
        assertEq(acct.paidUntil(), block.timestamp + 30 days);
        assertEq(acct.billingStatus(), 0);
        assertLt(acct.dollarsUsd(), 1.8e18, "only the margin is left");
        assertEq(_bal(token, alice) + _bal(CUSD, alice) + _bal(CUSD_PLUS, alice), 0, "nothing to the owner");
        assertEq(IERC20(token).allowance(address(acct), SWAP_ROUTER), 0);
        if (dest == CUSD_) assertEq(_bal(CUSD, address(collector)), 2 * MONTHLY);
        else assertGt(_bal(CUSD_PLUS, address(collector)), 0);
    }

    function test_fork_forcedSale_bitcoin_toCusd() public {
        if (!_forked()) return;
        _forcedCryptoSale(BTCB, BTC_FEED, CUSD_);
    }

    function test_fork_forcedSale_bitcoin_toCusdPlus() public {
        if (!_forked()) return;
        _forcedCryptoSale(BTCB, BTC_FEED, PLUS);
    }

    function test_fork_forcedSale_gold_toCusdPlus() public {
        if (!_forked()) return;
        _forcedCryptoSale(XAUT, XAU_FEED, PLUS);
    }

    /// A route that is not the market (a wrong-fee pool) is held to the feed
    /// like any other: the sale either meets the tolerance or is refused.
    function test_fork_forcedSale_feedBindsTheRoute() public {
        if (!_forked()) return;
        _giveCusd(address(acct), MONTHLY + 60e18);
        _subscribe();
        _ownerBuy(CUSD_, BTCB, 60e18);
        _toSaleAllowed();
        _restampFeeds();
        // The feed says bitcoin is worth 10% more than the pool pays.
        (uint80 round, int256 answer,,, uint80 answeredIn) = IFeed(BTC_FEED).latestRoundData();
        vm.mockCall(
            BTC_FEED,
            abi.encodeCall(IFeed.latestRoundData, ()),
            abi.encode(round, (answer * 110) / 100, block.timestamp, block.timestamp, answeredIn)
        );
        uint256 amount = _unitsFor(BTCB, BTC_FEED, (MONTHLY * 11_300) / 10_000);
        vm.prank(KMS, KMS);
        vm.expectRevert(ConfioSmartAccount.BelowFeed.selector);
        acct.forcedSale(_legs(SWAP_ROUTER, BTCB, amount, _sellData(CUSD_, BTCB, amount)), 0, address(0), 0);
    }

    // ── stocks: live router and vault, GM mocked ────────────────────────

    function test_fork_stock_buyRule_thenForcedSale_gmMocked() public {
        if (!_forked()) return;
        _etchGm();
        _givePlus(address(acct), 80e18);
        _subscribe();
        uint256 price = 250e18;

        // A buy rule through the live ConfioStockRouter.buyWithSavings.
        IConfioSmartAccount.RuleInput memory r = _rule(IConfioSmartAccount.RuleKind.Buy, CUSD_PLUS, 50e18);
        r.tokenOut = address(stock);
        uint256 id = _createRule(r);
        ILivePlus(CUSD_PLUS).accrue();
        uint256 p = ILivePlus(CUSD_PLUS).pPlus();
        uint256 sharesIn = (50e18 * 1e18 + p - 1) / p;
        // Spend 90% of the redeemed USDT: the rest would return as USDT (N6)
        // and cost a second entry fee in convertUsdt, so the rule refuses
        // more than one cent of it (audit P3).
        uint256 quantity = (((50e18 * 9_910) / 10_000) * 90 / 100) * 1e18 / price;
        bytes memory buy = abi.encodeCall(
            ConfioStockRouter.buyWithSavings,
            (_quote(quantity, price, 0), "", sharesIn, (quantity * price) / 1e18, 1, 90)
        );
        vm.prank(KMS, KMS);
        vm.expectRevert(ConfioSmartAccount.Slippage.selector);
        acct.executeRule(id, abi.encode(STOCK_ROUTER, buy, quantity), address(0), 0);

        // The live redemption of sharesIn, measured through the owner's own
        // trade (no such limit there) and rolled back.
        uint256 snap = vm.snapshotState();
        vm.prank(alice, KMS);
        acct.trade(STOCK_ROUTER, buy, CUSD_PLUS, address(stock), sharesIn, 1);
        uint256 net = (quantity * price) / 1e18 + _bal(USDT, address(acct));
        vm.revertToState(snap);

        // The relayer spends the whole redemption: what is left is the
        // quote's rounding.
        quantity = (net * 1e18) / price;
        uint256 spend = (quantity * price) / 1e18;
        buy = abi.encodeCall(ConfioStockRouter.buyWithSavings, (_quote(quantity, price, 0), "", sharesIn, spend, 1, 90));
        _run(id, abi.encode(STOCK_ROUTER, buy, quantity));
        assertEq(stock.balanceOf(address(acct)), quantity);
        assertLe(_bal(USDT, address(acct)), 1e16, "at most a cent of USDT left");
        assertEq(IERC20(CUSD_PLUS).allowance(address(acct), STOCK_ROUTER), 0);

        // The owner empties the dollars; the next period is paid by a
        // forced sale of the stock through sellToSavings.
        uint256 left = _bal(CUSD_PLUS, address(acct));
        vm.prank(alice, KMS);
        acct.withdraw(CUSD_PLUS, left);
        _toSaleAllowed();
        _restampFeeds();
        uint256 sellQuantity = (((MONTHLY * 10_200) / 10_000) * 10_000 / 9_910) * 1e18 / price;
        bytes memory sell =
            abi.encodeCall(ConfioStockRouter.sellToSavings, (_quote(sellQuantity, price, 1), "", 1, 1, 90));
        uint64 period = acct.paidUntil();
        vm.prank(KMS, KMS);
        acct.forcedSale(_legs(STOCK_ROUTER, address(stock), sellQuantity, sell), MONTHLY, address(0), 0);
        assertEq(stock.balanceOf(address(acct)), quantity - sellQuantity);
        assertEq(acct.forcedSaleForPeriod(), period);
        assertEq(acct.billingStatus(), 0);
        assertGt(_bal(CUSD_PLUS, address(collector)), 0, "fee in cUSD+ shares, same call");
        assertEq(stock.allowance(address(acct), STOCK_ROUTER), 0);
    }

    // ── referral on the upgraded live vault ─────────────────────────────

    function test_fork_referral_onUsdtConversion_andEoaArmingUnchanged() public {
        if (!_forked()) return;
        _giveCusd(address(acct), MONTHLY);
        _subscribe();
        uint256 cap = CusdVault(CUSD).referralShareCapBps();
        deal(USDT, address(acct), 100e18);
        vm.prank(KMS, KMS);
        acct.convertUsdt(CUSD_, 98.6e18, referrer, cap);
        assertEq(_bal(CUSD, referrer), (0.9e18 * cap) / 10_000);
        assertTrue(CusdVault(CUSD).isFullyBacked());

        // An arbitrary contract still cannot arm on the live vault.
        vm.prank(address(this), KMS);
        vm.expectRevert(bytes("not a Confio account"));
        CusdVault(CUSD).armReferral(referrer, cap);
    }

    // ── rollout step 2 on the fork: the whole inheritance flow ──────────

    /// Designation, acceptance, claim, cancel by an unrelated signed action,
    /// cooldown, second claim, full window, execution, inherited withdrawal
    /// to the wallet and to the new owner's own account, with the claim
    /// steps sent as plain self-paid transactions (6.7).
    function test_fork_inheritance_fullFlow() public {
        if (!_forked()) return;
        _giveCusd(address(acct), ANNUAL + ANNUAL + 100e18);
        _givePlus(address(acct), 50e18);
        vm.prank(alice, KMS);
        acct.subscribe(IConfioSmartAccount.Plan.Annual, type(uint256).max);
        _ownerBuy(CUSD_, BTCB, 50e18);
        uint256 btc = _bal(BTCB, address(acct));

        // Designation and acceptance: only with the live KMS relayer's
        // approval for exactly that step (invariant 18).
        vm.prank(alice, KMS);
        vm.expectRevert(ConfioSmartAccount.NotApproved.selector);
        acct.setBeneficiary(bob, 90 days);
        vm.prank(KMS, KMS);
        factory.approveDesignation(address(acct), bob, 90 days);
        vm.prank(alice, KMS);
        acct.setBeneficiary(bob, 90 days);
        vm.prank(bob, KMS);
        vm.expectRevert(ConfioSmartAccount.NotApproved.selector);
        acct.acceptBeneficiary();
        vm.prank(KMS, KMS);
        factory.approveAcceptance(address(acct), bob);
        vm.prank(bob, KMS);
        acct.acceptBeneficiary();

        // First claim, cancelled by an unrelated owner-signed action.
        vm.prank(bob, bob);
        acct.initiateClaim();
        vm.warp(block.timestamp + 60 days);
        vm.prank(alice, KMS);
        acct.cancelClaim();
        assertEq(acct.claimCooldownUntil(), block.timestamp + 30 days);
        vm.prank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.Cooldown.selector);
        acct.initiateClaim();

        // Cooldown, second claim, the full window.
        vm.warp(block.timestamp + 30 days);
        vm.prank(bob, bob);
        acct.initiateClaim();
        vm.warp(block.timestamp + 90 days - 1);
        vm.prank(bob, bob);
        vm.expectRevert(ConfioSmartAccount.TooEarly.selector);
        acct.executeClaim();
        vm.warp(block.timestamp + 1);
        vm.prank(bob, bob);
        acct.executeClaim();
        assertEq(acct.owner(), bob);
        assertTrue(acct.inherited());
        assertEq(_bal(BTCB, address(acct)), btc, "nothing moved at execution");

        // Inherited withdrawal: to the wallet, directly, no sponsor.
        uint256 cusdAll = _bal(CUSD, address(acct));
        vm.startPrank(bob, bob);
        acct.withdraw(BTCB, btc, bob);
        acct.withdraw(CUSD, cusdAll / 2, bob);
        vm.expectRevert(ConfioSmartAccount.BadDestination.selector);
        acct.withdraw(CUSD, 1, alice);
        vm.stopPrank();
        assertEq(_bal(BTCB, bob), btc);

        // And to the new owner's own Cuenta inteligente.
        vm.prank(bob);
        address bobs = factory.createAccount();
        address[] memory tokens = new address[](2);
        tokens[0] = CUSD;
        tokens[1] = CUSD_PLUS;
        vm.prank(bob, bob);
        acct.withdrawAll(tokens, bobs);
        assertEq(_bal(CUSD, bobs), cusdAll - cusdAll / 2);
        assertEq(_bal(CUSD_PLUS, bobs), 50e18);
        assertEq(_bal(CUSD, address(acct)) + _bal(CUSD_PLUS, address(acct)), 0);
        assertEq(_bal(CUSD, alice) + _bal(CUSD_PLUS, alice) + _bal(BTCB, alice), 0, "nothing to the old owner");

        // The old owner's key and the relayer are dead on this account.
        vm.prank(alice, KMS);
        vm.expectRevert(ConfioSmartAccount.NotOwner.selector);
        acct.withdraw(CUSD, 0);
        vm.prank(KMS, KMS);
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.collectFee();
    }

    /// Found on the fork, not in the spec: Ondo's Instant Manager has a
    /// US$1 minimum (minimumDepositUSD), so USDT dust under about US$1.01
    /// cannot enter cUSD+. It stays as USDT (withdrawable, returnable) until
    /// more arrives; the cUSD entry has no minimum.
    function test_fork_convertUsdt_dustBelowOndoMinimum_cannotEnterCusdPlus() public {
        if (!_forked()) return;
        _giveCusd(address(acct), MONTHLY);
        _subscribe();
        deal(USDT, address(acct), 0.9e18);
        vm.prank(KMS, KMS);
        vm.expectRevert();
        acct.convertUsdt(PLUS, 0.89e18, address(0), 0);
        vm.prank(KMS, KMS);
        acct.convertUsdt(CUSD_, 0.89e18, address(0), 0);
        assertEq(_bal(USDT, address(acct)), 0);
    }

    /// Cancel and return against the live tokens.
    function test_fork_cancelAndReturn() public {
        if (!_forked()) return;
        _giveCusd(address(acct), MONTHLY + 10e18);
        _givePlus(address(acct), 10e18);
        _subscribe();
        _ownerBuy(CUSD_, XAUT, 5e18);
        uint256 gold = _bal(XAUT, address(acct));
        vm.prank(alice, KMS);
        acct.cancelSubscription();
        vm.expectRevert(ConfioSmartAccount.BadState.selector);
        acct.returnAsset(CUSD);
        vm.warp(acct.paidUntil());
        acct.returnAsset(CUSD);
        acct.returnAsset(CUSD_PLUS);
        acct.returnAsset(XAUT);
        assertEq(_bal(CUSD, alice), 5e18);
        assertEq(_bal(CUSD_PLUS, alice), 10e18);
        assertEq(_bal(XAUT, alice), gold, "X2: XAUt moves to and from the account without a tax");
    }
}
