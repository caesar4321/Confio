"""No models.

The cUSD+ rail's data now lives with its peers rather than in a rail-private
app: the conversion saga merged into `conversion.Conversion` (one model for
both chains, as SendTransaction already was), the BNB auto-convert ledger
into `blockchain.PendingAutoSwap` (its ALGO/USDC twin), and the 7702
`SponsoredBatch` audit ledger into `blockchain` (it is written by send,
payments, payroll, presale and invites — infrastructure, not savings).

The rail's LOGIC still lives here: vault.py, sponsor_7702.py, eligibility.py,
tasks.py, schema.py, unified.py, prepare_leg_ab.py.
"""
