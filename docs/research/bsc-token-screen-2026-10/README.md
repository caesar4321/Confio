# BSC token screen for PancakeSwap buy/sell (2026-10-19)

Files: `token_screen.csv` (all 540 candidates, one row each; `final_tier` + `final_reason` are the decision, `tier` + `reason` the raw screen), `proposed_entries.json` (19 new entries in the `cusd_plus/crypto_tokens.json` shape, all `listed: false`; BTCB, ETH, WBNB, XAUT are already in the catalog).

## Final decision (2026-10-19): 23 tokens

| final_tier | Tokens | Count |
|---|---|---|
| home (`featured: true`) | BTCB, ETH, XAUt, SOL, XRP, WBNB (BNB) | 6 |
| catalog | ADA, AVAX, DOT, NEAR, LTC, BCH, LINK, UNI, AAVE, CAKE, FIL, TWT, SFP, DOGE | 14 |
| catalog_capped (`max_order_usd` = 100) | INJ, BEAM, GRAM (V2 routes) | 3 |
| held (not verified against issuer) | STABLE, SOON, AKE | 3 |
| excluded_policy | B (meme), Q (owner + mint, ~1,000 bps @ $1k), GOMINING (pausable + mint), APE (meme-like), ASTER, FF (no demand here; FF linked to DWF Labs), ZEC (privacy coin, Venezuela sanctions optics), TRX (Justin Sun risk; both contracts) | 9 rows / 8 tokens |

Rules behind it: the home screen holds names a LATAM beginner recognises; the catalog holds tokens that are both tradeable (screen below) and in demand, with risk labels; tokens nobody here asks for are not listed just because they pass. An aggregator/solver route (to open ATOM, FET, ZRO, PENDLE, etc.) is deferred until users actually ask for missing coins.

**Memecoin rule, open point:** DOGE is the single memecoin exception, catalog only, never home. The proposed wording "only memecoins in the top 10 by market cap" would exclude DOGE itself (CoinGecko rank 12 on 2026-10-19). Pick a wording that matches the intent, e.g. "only the largest memecoin by market cap" or "top 15". DOGE fork test: buy matched the same-block quote, transfers deliver 100%; RT 52.5 / 57.3 / 102.5 bps at $10 / $100 / $1,000 via USDT-0.01%-WBNB-0.25%-DOGE; Binance-Peg upgradeable proxy.

**Cost shown before buying:** Confío's 0.9% applies on the way in and again on the way out, so a full round trip is about 1.8% plus the DEX cost in this CSV. DOGE at $100: ~1.8% + 0.57% ≈ 2.4%. The pre-trade screen should show that total, not the 0.9% alone.

## Result (screen, before the final decision)

| | count |
|---|---|
| Candidates screened | 540 (CoinGecko top-300 with a BSC contract = 86; PancakeSwap extended + top-100 lists; Binance-Peg majors; BTCB, ETH, WBNB, XAUt) |
| Quotable against USDT at $100 | 509 (31 have no PancakeSwap route) |
| Pass the liquidity bar (RT < 100 bps at $100 AND < 200 bps at $1,000) | **61** |
| ...of which excluded by category | 28 excluded by category: 15 stablecoins, 9 memecoins, 2 tokenized stocks, 1 political (USD1), 1 staking derivative (slisBNB) |
| ...of which below the top-300 size cut or failing the contract screen | SOON, TWT, SFP re-admitted as `catalog_wide`; CGPT, DAO, XVS, PROM, TPT rank > 300; AIOZ (owner EOA + mint) and FORM (blacklist function) fail the contract screen |
| **Tiered (revised rules)** | **33** = **8 featured + 15 catalog + 3 catalog_wide + 7 catalog_capped** |
| Stablecoins (listed separately) | 33 (15 of them pass the liquidity bar) |
| Rejected | 474 |

Round-trip = buy then sell, best route each leg, excluding Confío's 0.9% fee. Quotes: PancakeSwap V3 QuoterV2 (tiers 100/500/2500/10000, direct or via WBNB) and V2 router (direct or via WBNB), `latest` block on 2026-10-19, via Multicall3.

## Screen-stage featured tier (8; superseded by Final decision above)

| Symbol | Address | RT bps $10 / $100 / $1,000 | Best buy route | Notes |
|---|---|---|---|---|
| BTCB | `0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c` | 2.0 / 2.2 / 4.1 | USDT-0.01%-BTCB | Binance custody (owner EOA + mint, by design) |
| ETH | `0x2170Ed0880ac9A755fd29B2688956BD959F933F8` | 1.4 / 1.9 / 6.7 | USDT-0.01%-ETH | Binance-Peg, same custody model |
| WBNB | `0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c` | 2.0 / 2.0 / 2.1 | USDT-0.01%-WBNB | wrapped native, no admin |
| XAUt | `0x21cAef8A43163Eea865baeE23b9C2E327696A3bf` | 14.4 / 10.7 / 10.7 | USDT-0.05%-XAUt | Tether Gold, upgradeable proxy, owner is a contract |
| SOL | `0x570A5D26f7765Ecb712C0924E4De545B89fD43dF` | 12.0 / 12.3 / 15.2 | USDT-0.01%-WBNB-0.05%-SOL | Binance-Peg, proxy |
| CAKE | `0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82` | 4.7 / 7.0 / 16.2 | USDT-0.01%-WBNB-0.05%-CAKE | owner is MasterChef-style contract, mint by design |
| ASTER | `0x000Ae314E2A2172a039B26378814C252734f556A` | 9.6 / 12.5 / 29.3 | USDT-0.05%-ASTER | no owner/proxy/mint flags found; young token (rank 52) |
| AAVE | `0xfb6115445Bff7b52FeB98650C87f44907E58f802` | 12.7 / 18.7 / 79.0 | USDT-0.01%-WBNB-0.05%-AAVE | assumed Binance-Peg (proxy); $1,000 cost is the highest of the group |

The featured bar was RT <= 30 bps at $100 and <= 100 bps at $1,000, underlying rank <= 100, clean fork test, plus a judgement call that the project is mainstream. Averaged order is about $9, so the $10 column is the one that matters most today.

## Revised screen tiers (after loosening; superseded by Final decision above)

| Tier | Rule | Count |
|---|---|---|
| featured | RT <= 30 bps @ $100 and <= 100 @ $1,000, underlying rank <= 100, hand-picked mainstream | 8 |
| catalog | RT < 100 @ $100 and < 200 @ $1,000, rank <= 150 | 15 |
| catalog_wide | same liquidity bar, rank 150-300 (SOON, TWT, SFP) | 3 |
| catalog_capped | RT < 150 @ $10 and $100 but >= 100 @ $100 or >= 200 @ $1,000; list with `max_order_usd` (GOMINING, INJ, B, BEAM, GRAM, APE, Q) | 7 |

Capped caps: $100 for GOMINING, INJ, BEAM, GRAM, APE, Q; $1,000 for B (101.6 bps @ $100, 118 @ $1,000). All 10 added tokens passed the same fork test (buy matches same-block quote, transfers deliver 100%); sells were not simulated. Flags to read before listing: GOMINING is pausable with a contract owner and mint function, Q has a contract owner and mint function, INJ is an upgradeable proxy, TWT's owner is an EOA, SOON is an upgradeable proxy. INJ, BEAM, B and GRAM use V2 routes (catalog supports `kind: v2`). The second TRX contract (`0x85EAC5Ac...`) is excluded as a duplicate. The `tier` and `max_order_usd` keys in `proposed_entries.json` are not in the current parser; strip them or add support before merging.

## Screen-stage catalog tier (15; superseded by Final decision above)

STABLE, FF, AKE (young or obscure projects, need review); ZEC (privacy coin, delisting risk); FIL, LTC, TRX, ADA, LINK, XRP, NEAR, AVAX, DOT, BCH, UNI (Binance-Peg majors, 28-68 bps at $100, mostly via 0.25% pools). Cost at $100 runs 15-68 bps, plus Confío's 0.9%. Details per row in the CSV.

Custody labels for the peg tokens other than BTCB, ETH and XAUt are inferred from the CoinGecko listing and the bytecode flags (owner EOA + mint, or proxy), not from issuer documents. Verify each before flipping `listed`.

## XAUt address (for comparison with the catalog)

tether.to supported-protocols page (`https://tether.to/en/supported-protocols/`, fetched 2026-10-19) lists the BNB Smart Chain contract for XAU₮ as **`0x21cAef8A43163Eea865baeE23b9C2E327696A3bf`**, byte-for-byte equal to the catalog address. Caveat: the page labels the token "XAU₮", not "XAUt0", so it does not itself say XAUt and XAUt0 are the same token. On-chain the contract returns symbol "XAUt", name "Tether Gold", 6 decimals, an EIP-1967 proxy slot, an owner that is a contract (`0x4dff9b5b...0bf8`), and totalSupply 13.7k units. CoinGecko lists the same address under `tether-gold-tokens` (XAUt0). That satisfies the catalog's `_listing_gate`.

## Contract checks

Bytecode selector scan, EIP-1967 proxy slots, `owner()`, `paused()` for the 86 tokens that came in under 150 bps at $100 and under 400 at $1,000 (`contract_flags` in the CSV; tokens outside this set are `not_scanned`). The scan is bytecode-only; BscScan verified-source review was not done, and an unverified or obfuscated tax function could be missed. Treat flags as a first pass.

Fork simulation (anvil fork, whale-funded account): bought $100 of USDT into each of the 23 tiered tokens through the PancakeSwap routers and compared the amount received to a same-block quote, then transferred half to another address. All 23 matched the quote exactly where the quote was taken on the fork (CAKE, AKE, BTCB, FF, FIL, BCH, ASTER, LINK, ADA, AVAX, NEAR, XAUt) or within 0.7% against a quote from a few minutes earlier (the rest, drift not tax; STABLE +0.6%). Every transfer delivered 100% (no transfer tax). The sell leg was not simulated on the fork; sell cost comes from the quoter. Blacklist or freeze behaviour cannot be detected by this test, only by reading source; only MC, FORM and BABYCAKE showed blacklist functions in bytecode (none are tiered).

## High volume but tiny liquidity

CoinGecko volume is mostly centralized-exchange volume, so this list mostly says the BSC pool is not where the market is. With 24h volume above $5M but round trip >= 150 bps at $100 or >= 300 at $1,000: HTX (91M volume, 3,334 bps at $100), Q (95M, 148/1,019), FET (103M, 240/608), ZRO (103M, 245/617), WBTC (127M, 198/1,319), ATOM, WLFI, BR, PENDLE, GRAM, BTW, and at the extreme COMP, ZAMA, CYBER, KITE, ACE, DEXE, UB, PLUME (all above 8,700 bps at $100, i.e. effectively no pool). CAP and ULTIMA have no route.

## Anomalies and gaps

- DGAI quoted a negative round trip at $100 (-7 bps) and FLOKI (BSC-peg listing) -12,449 bps at $10: stale or mispriced pools. Rejected rather than passed.
- WBTC (a wrapped duplicate of BTC, high CEX volume) fails the bar on BSC, so BTCB remains the only Bitcoin.
- CoinMarketCap's BNB Chain view was not used (no accessible API). Coverage is CoinGecko plus PancakeSwap's lists, whose extended list is old (2021-era tokens), so a recent BSC-native token outside CoinGecko's top 300 would be missed.
- The rank cut for peg tokens uses the underlying asset's CoinGecko rank, not the peg token's own market cap (CoinGecko shows peg supply as market cap).
- Public RPC quotes are not archive-consistent snapshots: the three sizes are separate calls on `latest`, so small drift between columns is expected.
