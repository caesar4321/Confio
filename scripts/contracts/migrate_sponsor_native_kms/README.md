# Sponsor Native-KMS Migration (mainnet)

One-time migration that moves the Algorand sponsor role from the legacy
SSM-backed Ed25519 key (alias `confio-mainnet-sponsor`, address `ZS2HK…`) to a
new native KMS Ed25519 key (alias `confio-mainnet-sponsor-native-ed25519`,
address `LAOVAX…`). The legacy key kept the raw private key in SSM. The new
key signs inside KMS — the private key never leaves the HSM.

## Run order

All commands assume you are at the repo root, with `aws-vault` configured for
profile `Julian` (the AWS account that owns the new sponsor key).

Each script asks for an explicit typed confirmation before submitting any
mainnet transaction.

1. **Seed ALGO** — send 5 ALGO from legacy → new so the new sponsor can pay
   for its own opt-ins.
   ```
   aws-vault exec Julian -- myvenv/bin/python \
       scripts/contracts/migrate_sponsor_native_kms/seed_algo.py
   ```
2. **ASA opt-ins** — opt the new sponsor into USDC, cUSD, CONFIO.
   ```
   aws-vault exec Julian -- myvenv/bin/python \
       scripts/contracts/migrate_sponsor_native_kms/optin_assets.py
   ```
3. **App opt-ins** — opt the new sponsor into apps `3198259271` (cUSD) and
   `3353218127` (prod presale). The legacy presale `3351520941` is
   intentionally excluded.
   ```
   aws-vault exec Julian -- myvenv/bin/python \
       scripts/contracts/migrate_sponsor_native_kms/optin_apps.py
   ```
4. **Update sponsor on the 6 WPJC6BX-admin contracts** — admin is the
   3-of-5 native KMS multisig. The signing script lives outside the repo
   because it loads multisig key material (KMS ARNs, AWS profiles) that we
   keep off Git. See `.kms-local/migration_2026-05-16/` for the script and
   per-target dry-run output.

5. **Flip prod env + restart services** — update `.env.mainnet`:
   ```
   KMS_KEY_ALIAS=confio-mainnet-sponsor-native-ed25519
   KMS_NATIVE_SIGNING=True
   ALGORAND_SPONSOR_ADDRESS=LAOVAXRX75S76NG67EZCBNMGGV4HAZWY7OTL62HQSDGXTVDQSAU2SKQOHU
   ALGORAND_REWARD_SPONSOR_ADDRESS=LAOVAXRX75S76NG67EZCBNMGGV4HAZWY7OTL62HQSDGXTVDQSAU2SKQOHU
   ```
   Deploy and restart `daphne`, `celery`, `celery-beat` on prod
   (`51.96.174.134`).

6. **Smoke test** — send a small sponsored cUSD payment from a wallet and
   confirm the sponsor on-chain matches the new address.

7. **Drain residual ALGO** — leaves min-balance + 1 ALGO on legacy.
   ```
   aws-vault exec Julian -- myvenv/bin/python \
       scripts/contracts/migrate_sponsor_native_kms/drain_legacy.py
   ```

## Scope notes

- The `p2p_trade` contract (admin `MAI35AB…`, old multisig) is **excluded**
  from this migration — the feature is deprecated and will simply break after
  the cutover.
- Vesting apps (`vesting_pool`, `vesting_susy`, `vesting_julian`) have no
  `sponsor_address` global state and are not touched here.
- Admin rotation is a separate operation; this migration changes the
  `sponsor_address` global state only, leaving the multisig admin in place.

## Code surface added

- `blockchain/kms_manager.py` — new `NativeKMSSigner` class plus
  `KMS_NATIVE_SIGNING`-gated factory selection in
  `get_kms_signer_from_settings()`.
- `config/settings.py` — new `KMS_NATIVE_SIGNING` setting (default `False`,
  flipped to `True` only on mainnet at cutover time).
