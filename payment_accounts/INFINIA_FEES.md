# Infinia fee collection

New fee-enabled journeys collect cUSD into the existing account-opening collector.
FX is already in the provider quote. Separately billed processing is added; Colombia
also adds $0.75 per incoming or outgoing blockchain leg. Other countries' gas is
already included. Per Bill Strozberg's clarification, Argentina ITF applies to transfers
between differently named accounts when at least one is a business: 0.6% per bank,
1.2% total. Same-name transfers and transfers between two individuals are exempt.
The banks deduct applicable ITF automatically from the transaction value. Confío
therefore adds no ITF to its collector transfer and does not infer tax liability
from sender-name matching. The provider's resulting amounts remain authoritative;
`itf_usd=0` means zero additional collection, not a claim of tax exemption.
Existing account-opening charges are unchanged.

Outgoing quotes include the fee in the entered budget and bind the destination.
The user signs the collector transfer and bridge funding together. Collected outgoing
fees are not refunded when the bridge returns principal.

Incoming deposits mint and collect in the same signed batch. Collection is capped at
the deposit's mint output, so it cannot consume an existing wallet balance. A deposit
may leave zero cUSD for the user. Confirmed collection records the actual cash amount;
the unpaid invoice balance becomes one durable carry-forward debt. A later fee-enabled
deposit or payout includes that debt. Partial payment can roll the balance forward again.
Reservations prevent two simultaneous quotes from claiming the same debt. Reconciliation
is idempotent; a reorg retracts cash evidence and retains the claim for its original flow.
Unsigned partial-fee instructions can refresh with the mint preview; signed instructions
remain fixed.

Monthly maintenance accrues once per enabled local fiat account per month, starting
with the rollout month. The shared Polygon USDC account is excluded. Closure ends
billing in the following month. Maintenance is collected on a later signed transfer;
its settlement marker can represent cash plus carry-forward, while the flow receipt
records only cash actually collected. Daily accrual also catches missed billing cycles.

## Rollout

Apply migrations 0025 and 0026 and deploy the server with fee flags disabled. Release
the app that signs local mint collector transfers and passes the payout destination
into bridge quotes. Then set `INFINIA_PASS_THROUGH_FEE_COUNTRIES` to the desired ISO2
codes, including Argentina when ready. Old journeys retain their frozen terms.

`INFINIA_PROCESSING_FEE_TIER` is the confirmed contract tier, 0–5 (default 0).
`INFINIA_MAINTENANCE_FEES_ENABLED` enables prospective monthly accrual.
`INFINIA_ACCOUNT_FEE_TIER` is 0–2 (default 0). Configure tiers explicitly from the
provider's billing agreement; the integration does not infer them from user volume.
Previously created invoices remain payable even if new maintenance accrual is disabled.

The daily Celery schedule must run for maintenance accrual. Collector configuration
uses the existing activation collector and validates its cUSD token and treasury.
Cash collection requires confirmed on-chain batch evidence, not just a provider status.
