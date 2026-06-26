# Confio Ayuda Humanitaria

PuyaPy contract for cUSD humanitarian relief campaigns.

PuyaPy 5.x requires Python 3.12+. The Django app currently uses Python 3.10,
so compile this contract with a separate compiler environment:

```bash
python3.12 -m venv /tmp/confio-puya-venv
/tmp/confio-puya-venv/bin/pip install puyapy
/tmp/confio-puya-venv/bin/python contracts/humanitarian/build_contracts.py
```

The contract is intentionally not a presale fork. It reuses the useful operating
pattern from presale, namely admin-controlled sponsored calls, but the state is
relief-specific:

- `donate(asset_transfer, donation_ref)`: records cUSD sent into the app account.
- `release(recipient, amount, release_ref)`: admin/operator releases a cUSD advance to an approved volunteer.
- `pause()` / `unpause()`: admin circuit breaker.
- `set_admin()` / `set_release_operator()`: admin key rotation and delegated release authority.
- `emergency_withdraw()`: admin-only, pause-gated rescue path.
- `update()`: admin-only application upgrade hook.

Proof URLs are not part of the contract call. Admin publishes proof links in the
Django humanitarian ledger after Julian uploads the content.
