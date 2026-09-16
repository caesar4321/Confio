# Local payment monitoring

Use `/confio-control-panel/payment_accounts/infiniajourney/` for end-to-end
incoming and outgoing Infinia transfers. The list is read-only: an operator must
not mark a transfer complete by editing a state field. Related provider
operations, bridge, original receipt and wallet conversion remain available on
the detail page.

Use `/confio-control-panel/payment_accounts/automaticpayin/` for received fiat
that has not started a transfer, including review reasons. A started automatic
pay-in is not proof of wallet delivery. Admission decisions remain under
`/confio-control-panel/payment_accounts/payinadmission/`.

The main dashboard adds direction and **local account country** filters. These
are not the user's phone country or nationality. Completion rate uses started
journeys as its denominator, not quote requests or bank-account openings.
Pending payments unchanged for more than one hour are labelled stalled, never
abandoned: they may already contain customer funds. Incoming completion waits
for the linked wallet conversion. Outgoing fiat is grouped by currency and is
never added together as dollars.

## Website deposited volume

`ramps.metrics.deposited_volume_by_provider` is shared by the dashboard's
all-provider total and the public landing statistics (10-minute cache). It adds:

- Completed incoming legacy ramp records for Koywe, Guardarian and any recorded
  Transak settlements, using one contribution per ramp. A completed, non-deleted
  inbound Confío conversion matching the final currency takes precedence: each
  ramp's final dollar amount preserves its allocation when one conversion settles
  multiple ramps. Otherwise, an actual completed, non-deleted linked USDC deposit
  or uniquely attributed BSC USDT scanner receipt counts at its actual received
  amount. Awaiting mint does not erase an on-chain deposit; provider completion,
  quotes and unverified transaction hashes alone do not count. Guardarian raw
  transactions are not summed again.
- Infinia completed incoming journeys with a completed, non-deleted wallet
  conversion, using exact net USD value (not savings token quantities).
- Cobre completed incoming journeys with a delivered return bridge, using actual
  BSC USDT units divided by 10^18. Cobre currently ends at USDT wallet delivery;
  Infinia ends at the subsequent Confío conversion.

Legacy ramp mirrors attached to journey MoneyFlows are excluded. Outgoing
payments, quotes, intermediate FX legs and unfinished deliveries do not count.
Legacy ramp final amounts retain the existing USD reporting convention (savings
conversion compatibility amounts are net USD, not token shares); no current FX
price is applied to historical payments. The legacy contribution can decrease
by the conversion fee when a gross stablecoin receipt becomes a completed net
Confío conversion. Historical rows without linked delivery evidence are excluded,
not assumed delivered.

There is **no Transak ingestion implementation in this repository**. Its total
is zero unless completed settlement records and linked delivery evidence have been imported; this feature
does not invent a historical figure or backfill data from a provider API.

Dashboard access requires the Infinia journey view permission. The automatic
deposit processing link/count additionally requires its model view permission.
No migration, provider API request, recovery action, or fund movement is needed
to use this monitoring feature.
