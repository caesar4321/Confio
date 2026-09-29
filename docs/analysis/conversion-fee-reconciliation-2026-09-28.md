# Conversion fee reconciliation — 2026-09-28

Read-only production and BSC audit at finalized block 124593997.

| Direction | Gross fee-bearing USDT | Accrued fee USDT |
| --- | ---: | ---: |
| Entry | 33325.310233436000758621 | 299.927792100924006837 |
| Exit | 46827.024484000000000002 | 421.443220356000000002 |

The live contract reports 90 bps. All 167 examined fee events charge
ceil(gross * 90 / 10000) in 18-decimal USDT units, with net + fee = gross.
Event fee sums match both on-chain accrued counters exactly.

The completed conversion ledger provided 166 fee events: 66 cUSD entries,
25 cUSD+ entries, 66 cUSD exits, and 9 cUSD+ exits. An additional on-chain
cUSD redemption at block 122170131 contributes gross USDT 30, fee 0.27,
and net 29.73. Its event owner is the configured treasury Safe, with no matching app account.
It was executed by the Safe on 2026-09-16 and is absent from Conversion and
SponsoredBatch records, explaining why the app-ledger sample omitted it.
Transaction: https://bscscan.com/tx/0x1f96bc2abc5a5e3b24b904759a85c5e933f26600e939b242bee8d8ac95f62d56

The fee-bearing gross exit volume exceeds entry volume by
13501.714250563999241381 USDT, explaining the fee difference of
121.515428255075993165 USDT. These contract counters cover the BSC fee
perimeter introduced on 2026-08-31, not Movido's all-time historical
conversions. Pre-existing balances can exit after the fee system begins.

Contract source uses one feeFor function for both directions and shares the
same counters with cUSD+ settlement. Admin metrics read these counters
on-chain. Internal cUSD/cUSD+ moves are fee-free. Local CusdVaultTest (17)
and CusdSystemTest (7) passed, including rounding and one-fee settlement.
No funds, fees, settings, or production records were changed.

## Follow-up: actual counter increases on September 28

Snapshots bracket the day beginning 00:00 America/La_Paz (04:00 UTC),
from block 124457004 through finalized block 124595178.

| Counter | Start of day | Latest | Increase |
| --- | ---: | ---: | ---: |
| entry | 273.450654345924006836 | 299.927792100924006837 | 26.477137755000000001 |
| exit | 395.406220356000000002 | 421.443220356000000002 | 26.037000000000000000 |

All 11 completed fee-bearing conversions were independently verified against
on-chain counter values immediately before and after their transaction block.
Each delta equals the corresponding event fee exactly. Six entries and five
exits account for the entire daily increases. No fee omission was found.

| Bolivia time | Direction | Gross USDT | Fee | Counter before | Counter after | Transaction |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 07:33:22 | entry | 101.02636 | 0.90923724 | 273.450654345924006836 | 274.359891585924006836 | [Receipt](https://bscscan.com/tx/0x506641d4f5c5bc7dff968475b5c7e765536d49f4b46ee3fa0229e07bce2f18c4) |
| 10:22:44 | entry | 10.990000000000000001 | 0.098910000000000001 | 274.359891585924006836 | 274.458801585924006837 | [Receipt](https://bscscan.com/tx/0xa0e53fc6b68ee231e83de82c1aa62eab1a4499780a8f24b31896a5a4d0648387) |
| 11:55:30 | exit | 95 | 0.855 | 395.406220356000000002 | 396.261220356000000002 | [Receipt](https://bscscan.com/tx/0x8b3cfd661dd0cebb07f366c9371c4254e5dbf86fb2382739e023ef95691264a9) |
| 13:04:09 | entry | 653.672961 | 5.883056649 | 274.458801585924006837 | 280.341858234924006837 | [Receipt](https://bscscan.com/tx/0x20cc02e0874916d54b9290ac53f95420d1b2ba818a520f59dfd6e4aa1ba1dfb9) |
| 13:07:52 | exit | 643.75 | 5.79375 | 396.261220356000000002 | 402.054970356000000002 | [Receipt](https://bscscan.com/tx/0xb0ecc456867f71507e03fb9ead5030a3f179b550b9942097018a6e6bb2d6b8b1) |
| 15:20:37 | entry | 1480.656082 | 13.325904738 | 280.341858234924006837 | 293.667762972924006837 | [Receipt](https://bscscan.com/tx/0xd227cc3fb5678ec9c7f3f4e0718b4e4bd42671a0b115dee010492ee7f0c9a3a1) |
| 15:21:54 | exit | 1463.75 | 13.17375 | 402.054970356000000002 | 415.228720356000000002 | [Receipt](https://bscscan.com/tx/0x65253fe5718263e7bc06b840a74b7d8b9a712da22914e53f16b0500a827dc6d9) |
| 15:51:03 | entry | 295.908489 | 2.663176401 | 293.667762972924006837 | 296.330939373924006837 | [Receipt](https://bscscan.com/tx/0x2064a6c895b4ad8e45ec37e82a5d1b7c97be9a8b9a9921dfd0322c3682ca1602) |
| 15:51:59 | exit | 296.75 | 2.67075 | 415.228720356000000002 | 417.899470356000000002 | [Receipt](https://bscscan.com/tx/0x992b075f5dbd8b9300a996fa1f8932e9d0a98af95ac9b495c48916e99bd23121) |
| 16:38:35 | entry | 399.650303 | 3.596852727 | 296.330939373924006837 | 299.927792100924006837 | [Receipt](https://bscscan.com/tx/0xb7a907ad2a2c18483c2cbf5fac896c4da1b7829801ff8b1a95fd45bd2c2a6182) |
| 16:39:47 | exit | 393.75 | 3.54375 | 417.899470356000000002 | 421.443220356000000002 | [Receipt](https://bscscan.com/tx/0xc791ed0417300d9f801ed60642bd719c5bc1995a35e4a2e6751309c2b9cbef19) |

## Exact bridge to all-time Movido

Amounts below use Movido conventions: gross entries, net exits.

| Population | Entries | Exits |
| --- | ---: | ---: |
| Fee-bearing app conversions | 33325.310233436000758621 | 46375.851263644000000000 |
| Historical zero-fee BSC records | 2.654399000000000000 | 725.127057464016416501 |
| Legacy records without BSC fee fields | 79955.435280 | 56768.056021 |
| Total | 113283.399912436000758621 | 103869.034342108016416501 |

All-time net flow is 9414.365570327984342120 USDT-equivalent. This is not wallet supply or a
bank reconciliation. The treasury Safe redemption adds 30 gross / 29.73 net
and 0.27 exit fees to the contract totals, outside these user conversion rows.

September 23 alone includes one fee-bearing exit of 14282.021586 USDT with
128.538194274 USDT exit fees and no new completed entry in that day’s
conversion records. This explains a large part of the accumulated fee gap;
it does not establish the original funding source of that wallet.

Admin renders both counters from the same metrics object, cached for 30
seconds. The cards are server-rendered snapshots rather than live counters.
The reported 299.93 entry balance already includes all six verified entries
on September 28 through the audited block.

## Current holder liabilities and reserves — 21:19 UTC

- BSC cUSD holder supply: 160.21178060419894506; USDT backing excluding fees: 160.21178060419894506.
- BSC cUSD+ holder liability: 736.368170740177935334; USDY reserve value: 745.5398268783337; yield surplus: 9.171656138155673557.
- Legacy Algorand circulating a-cUSD and USDC backing: 5950.843753; source: algorand.
- Combined holder liabilities: 6847.423704344376880394. These are token holder totals, not an attribution to individual app users.
- Conversion fee balances are separate from holder backing. These snapshots do not inventory raw stablecoins in wallets, provider balances, or separate stock holdings, and do not constitute a full lifetime supply reconciliation.
