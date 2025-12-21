# Confío Scripts

This directory contains production scripts and utilities for managing the Confío platform, focusing on Algorand blockchain operations, database management, debugging, and system maintenance.

## Directory Structure

```
scripts/
├── admin/          # Administrative & heavy maintenance scripts
├── analytics/      # Data analysis and metrics scripts
├── audit/          # Auditing, verification, and inspection scripts
├── backfill/       # Data backfill and population scripts
├── config/         # Configuration files for deployments
├── contracts/      # Smart contract interaction scripts (bootstrap, fund, etc.)
├── debug/          # Debugging tools and one-off diagnostic scripts
├── deployment/     # Infrastructure and contract deployment scripts
├── migration/      # User migration and account transition scripts
└── utils/          # General utility and cleanup scripts
```

## Contracts Scripts (`contracts/`)

Scripts for interacting with Algorand smart contracts (Payment, Rewards, Presale).

| Script | Purpose | Usage |
|--------|---------|-------|
| `bootstrap_rewards.py` | Bootstrap the rewards system | Deploy/init rewards infrastructure |
| `fund_vault.py` | Fund vault account | Ensure vault has ALGO/ASAs |
| `withdraw_*.py` | Withdrawal operations | Managing contract funds |
| `update_*.py` | Update contract parameters | Updating prices, limits, etc. |

## Audit Scripts (`audit/`)

Scripts for verifying system integrity and inspecting state.

| Script | Purpose |
|--------|---------|
| `audit_balances.py` | Verify user balances against chain |
| `check_user.py` | Inspect user account status |
| `inspect_event_*.py` | Debug specific event logs |
| `verify_graphql_security.py` | Security audit tool |

## Deployment Scripts (`deployment/`)

Infrastructure deployment and server setup.

| Script | Purpose |
|--------|---------|
| `deploy_ec2_systemd.sh` | Deploy systemd services to EC2 |
| `setup_pgbouncer.sh` | Configure database connection pooling |
| `local_rebuild.sh` | Rebuild local development environment |

## Migration Scripts (`migration/`)

Tools for managing user migration between V1/V2 architectures.

| Script | Purpose |
|--------|---------|
| `check_migration_status.py` | Check user migration state |
| `reset_migration.py` | Reset migration flags for testing |
| `investigate_user_migration.py` | Daignose migration issues |

## Debug Scripts (`debug/`)

One-off scripts for diagnosing specific production issues.

| Script | Purpose |
|--------|---------|
| `debug_guardarian.py` | Debug Guardarian transaction flow |
| `debug_ws_flow.py` | Test WebSocket connectivity |
| `dump_user.py` | Dump full user profile JSON |

## Running Scripts

All python scripts require Django environment to be set up. They use the following pattern:

```python
#!/usr/bin/env python3
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

# Script logic here...
```

### Prerequisites

1. **Virtual Environment**: Use `myvenv/bin/python`
2. **Django Settings**: Scripts use `config.settings`
3. **Environment Variables**: Ensure `.env` or `.env.mainnet` is configured
4. **Algorand Access**: Scripts require ALGORAND_ALGOD_ADDRESS and ALGORAND_ALGOD_TOKEN

### Common Patterns

```bash
# Run from project root
cd /Users/julian/Confio

# Run a contract interaction script
myvenv/bin/python scripts/contracts/bootstrap_rewards.py

# Run an audit script
myvenv/bin/python scripts/audit/check_user.py

# Make executable (optional)
chmod +x scripts/audit/check_user.py
./scripts/audit/check_user.py
```

## Important Safety Notes

1. **Production Impact**: Most scripts in `contracts/` and `admin/` modify state on the blockchain or database. Always verify you are running against the intended environment (Mainnet vs Testnet).
2. **Backups**: Before running `backfill/` or `migration/` scripts that modify the DB in bulk, ensure a snapshot exists.
3. **Executables**: Bash scripts in `deployment/` should be reviewed before execution.

```
scripts/
├── deployment/        # Deployment & initialization scripts
├── admin/            # Administrative & maintenance scripts
└── config/           # Configuration files for deployments
```

## Deployment Scripts (`deployment/`)

Scripts for deploying and initializing Algorand smart contracts and blockchain infrastructure.

| Script | Purpose | Usage |
|--------|---------|-------|
| `bootstrap_rewards.py` | Bootstrap the rewards system on Algorand | Deploy initial rewards infrastructure |
| `deploy_fixed_rewards.py` | Deploy fixed rewards contract | Contract deployment to testnet/mainnet |
| `fund_vault.py` | Fund the vault account with ALGO/ASAs | Ensure vault has sufficient balance |

**Example:**
```bash
# Bootstrap rewards system
myvenv/bin/python scripts/deployment/bootstrap_rewards.py

# Deploy rewards contract
myvenv/bin/python scripts/deployment/deploy_fixed_rewards.py

# Fund vault account
myvenv/bin/python scripts/deployment/fund_vault.py
```

## Admin Scripts (`admin/`)

Scripts for administrative tasks, debugging, and maintenance of the rewards and referral systems.

| Script | Purpose | Usage |
|--------|---------|-------|
| `check_box.py` | Check Algorand box storage state | Debug box storage issues |
| `create_referral_via_service.py` | Create referral via rewards service | Test referral creation flow |
| `create_test_referral_box.py` | Create test referral box on-chain | Testing and debugging |
| `fix_broken_referrer_reward.py` | Fix broken referrer rewards | Repair corrupted reward states |
| `investigate_missing_referrer_confio.py` | Investigate missing CONFIO rewards | Debug missing reward tokens |
| `retry_failed_conversion.py` | Retry failed currency conversions | Recover from conversion failures |
| `retry_sync_reward.py` | Retry syncing rewards to blockchain | Fix sync failures |
| `sync_eligible_reward.py` | Sync eligible rewards from database to chain | Batch sync operations |

**Example:**
```bash
# Check box storage for a specific user
myvenv/bin/python scripts/admin/check_box.py

# Fix broken rewards
myvenv/bin/python scripts/admin/fix_broken_referrer_reward.py

# Sync eligible rewards to blockchain
myvenv/bin/python scripts/admin/sync_eligible_reward.py
```

## Config Files (`config/`)

Configuration files used by deployment and admin scripts.

| File | Purpose | Contents |
|------|---------|----------|
| `confio_token_config.json` | CONFIO token configuration | Token metadata, asset IDs |
| `deployment_info.json` | Deployment information | Contract addresses, app IDs |
| `invite_send_deployment.json` | Invite system deployment config | Invite contract details |

## Running Scripts

All scripts require Django environment to be set up. They use the following pattern:

```python
#!/usr/bin/env python3
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

# Script logic here...
```

### Prerequisites

1. **Virtual Environment**: Use `myvenv/bin/python`
2. **Django Settings**: Scripts use `config.settings`
3. **Environment Variables**: Ensure `.env` or `.env.mainnet` is configured
4. **Algorand Access**: Scripts require ALGORAND_ALGOD_ADDRESS and ALGORAND_ALGOD_TOKEN

### Common Patterns

```bash
# Run from project root
cd /Users/julian/Confio

# Deployment scripts (one-time or infrequent)
myvenv/bin/python scripts/deployment/bootstrap_rewards.py

# Admin scripts (maintenance and debugging)
myvenv/bin/python scripts/admin/sync_eligible_reward.py

# Make executable (optional)
chmod +x scripts/admin/check_box.py
./scripts/admin/check_box.py
```

## Important Notes

### 1. **Production Safety**
- Most scripts interact with the **mainnet** blockchain
- Always verify environment settings before running
- Check ALGORAND_ALGOD_ADDRESS to confirm testnet vs mainnet
- Deployment scripts may consume ALGO for transactions

### 2. **Transaction Fees**
- Deployment scripts will deduct ALGO from sponsor account
- Ensure sufficient ALGO balance before running
- Check transaction fees in Algorand blockchain explorer

### 3. **Database Modifications**
- Admin scripts may modify the database
- Always backup database before running maintenance scripts
- Test on staging environment first when possible

### 4. **Idempotency**
- Not all scripts are idempotent
- Re-running deployment scripts may create duplicate resources
- Check existing state before running scripts

### 5. **Logging**
- Scripts output to stdout/stderr
- Consider redirecting output for production runs:
  ```bash
  myvenv/bin/python scripts/admin/sync_eligible_reward.py 2>&1 | tee sync.log
  ```

## Troubleshooting

### Script fails with "No module named 'config'"
**Solution:** Run from project root directory:
```bash
cd /Users/julian/Confio
myvenv/bin/python scripts/admin/check_box.py
```

### "ALGORAND_ALGOD_ADDRESS not set" error
**Solution:** Ensure environment variables are loaded:
```bash
# Check environment
echo $ALGORAND_ALGOD_ADDRESS

# Load from .env if needed
set -a && source .env.mainnet && set +a
```

### Box storage errors
**Solution:** Use `check_box.py` to investigate:
```bash
myvenv/bin/python scripts/admin/check_box.py
```

### Rewards not syncing
**Solution:** Try retry scripts in order:
```bash
# 1. Retry failed conversions
myvenv/bin/python scripts/admin/retry_failed_conversion.py

# 2. Retry sync
myvenv/bin/python scripts/admin/retry_sync_reward.py

# 3. Sync eligible rewards
myvenv/bin/python scripts/admin/sync_eligible_reward.py
```

## Development

When adding new scripts:
1. Place in appropriate directory (deployment/admin)
2. Include Django setup code at top
3. Add docstring explaining purpose
4. Update this README with script description
5. Make sure script is executable: `chmod +x script.py`
6. Use proper error handling and logging

## Related Documentation

- `/tests/README.md` - Integration tests for blockchain functionality
- `/blockchain/README.md` - Blockchain service documentation
- `/achievements/README.md` - Rewards and achievements system
- `CLAUDE.md` - Project conventions and guidelines
