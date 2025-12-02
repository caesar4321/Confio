# Next Steps - Action Plan

## Overview

This document outlines the remaining steps to complete the security remediation and AWS KMS migration after the December 2, 2024 security incident.

---

## ✅ Completed

- [x] Analyzed security breach and identified root cause
- [x] Removed all hardcoded mnemonics from scripts
- [x] Encrypted sensitive scripts with git-crypt
- [x] Generated new secure credentials (testnet & mainnet)
- [x] Implemented AWS KMS integration for secure key management
- [x] Created comprehensive documentation
- [x] Committed security fixes to local repository
- [x] Installed git-filter-repo for history cleanup
- [x] Created git history cleanup script

---

## 🔄 In Progress

### Step 1: Get AWS IAM Permissions

**Status:** WAITING FOR ADMIN

**What's needed:**
- Attach `ConfioKMSPolicy` to IAM user `Julian`

**How to do it:**

See `scripts/kms/SETUP_INSTRUCTIONS.md` for three options:
1. Run commands as AWS admin
2. Use AWS Console to attach policy manually
3. Email instructions to AWS administrator

**Verification:**
```bash
# Once policy is attached, verify:
aws kms list-aliases --region eu-central-2
aws ssm describe-parameters --region eu-central-2

# Both should work without "AccessDenied" errors
```

**Estimated time:** 10-15 minutes (depends on admin availability)

---

## ⏭️ Next Steps (In Order)

### Step 2: Import Keys into AWS KMS

**When:** After IAM permissions are granted
**Estimated time:** 5 minutes

**Commands:**
```bash
cd /Users/julian/Confio

# Import the new secure keys into KMS
DJANGO_SETTINGS_MODULE=config.settings myvenv/bin/python \
  scripts/kms/setup_kms_keys.py --import-existing
```

**Keys now stored in AWS KMS:**

**Testnet:**
```
Address: UQ6WZKLQBQCNAQTOSEWZZXDY376RZTYP2U2ZZT7OIPEGP376HYLTCSL6E4
KMS Alias: alias/confio-testnet-sponsor
Mnemonic: <REDACTED - STORED IN AWS KMS>
```

**Mainnet:**
```
Address: ZS2HK5N7BZV46ZZGDOQBGFTN3JSXGAFVJFG33WAEP47JQMASSSJIQL7HI4
KMS Alias: alias/confio-mainnet-sponsor
Mnemonic: <REDACTED - STORED IN AWS KMS>
```

**What happens:**
- Keys encrypted and stored in AWS KMS (eu-central-2)
- Private keys stored in Parameter Store (encrypted with KMS key)
- KMS aliases created: `confio-testnet-sponsor` and `confio-mainnet-sponsor`

---

### Step 3: Fund New Testnet Address

**When:** After keys are in KMS
**Estimated time:** 2 minutes

**Testnet Address:** `UQ6WZKLQBQCNAQTOSEWZZXDY376RZTYP2U2ZZT7OIPEGP376HYLTCSL6E4`

**How to fund:**
1. Go to testnet faucet: https://bank.testnet.algorand.network/
2. Enter address: `UQ6WZKLQBQCNAQTOSEWZZXDY376RZTYP2U2ZZT7OIPEGP376HYLTCSL6E4`
3. Request 10 ALGO (for testing)

**Verification:**
```bash
# Check balance
curl -s "https://testnet-api.4160.nodely.dev/v2/accounts/UQ6WZKLQBQCNAQTOSEWZZXDY376RZTYP2U2ZZT7OIPEGP376HYLTCSL6E4" \
  | python3 -m json.tool | grep -A 1 "\"amount\""
```

---

### Step 4: Test KMS Signing on Testnet

**When:** After testnet address is funded
**Estimated time:** 3 minutes

**Command:**
```bash
cd /Users/julian/Confio

# Test KMS signing
python scripts/kms/test_kms_signing.py --testnet
```

**What this does:**
- Retrieves address from KMS
- Creates a test transaction (0 ALGO to self)
- Signs transaction using AWS KMS
- Submits to testnet
- Waits for confirmation

**Expected output:**
```
✓ Connected to testnet
✓ KMS signer initialized
  Address: UQ6WZKLQBQCNAQTOSEWZZXDY376RZTYP2U2ZZT7OIPEGP376HYLTCSL6E4
Account Balance: 10.0 ALGO
✓ Transaction created
✓ Transaction signed successfully with KMS
✓ Transaction submitted!
  Transaction ID: <txid>
✓ Transaction confirmed in round <round>

SUCCESS! KMS SIGNING WORKS CORRECTLY
View transaction: https://testnet.algoexplorer.io/tx/<txid>
```

**If it fails:**
- Check IAM permissions
- Verify keys were imported correctly
- Check AWS region is eu-central-2
- See troubleshooting in `docs/AWS_KMS_SETUP.md`

---

### Step 5: Update .env Files

**When:** After testnet signing test passes
**Estimated time:** 5 minutes

**Files to update:**
- `.env.testnet`
- `.env.mainnet`

**Add these lines:**
```bash
# Enable KMS signing
USE_KMS_SIGNING=True

# KMS configuration
KMS_KEY_ALIAS_TESTNET=confio-testnet-sponsor
KMS_KEY_ALIAS_MAINNET=confio-mainnet-sponsor
KMS_REGION=eu-central-2

# Update sponsor addresses
ALGORAND_SPONSOR_ADDRESS_TESTNET=UQ6WZKLQBQCNAQTOSEWZZXDY376RZTYP2U2ZZT7OIPEGP376HYLTCSL6E4
ALGORAND_SPONSOR_ADDRESS_MAINNET=ZS2HK5N7BZV46ZZGDOQBGFTN3JSXGAFVJFG33WAEP47JQMASSSJIQL7HI4

# Optional: Keep old mnemonic as emergency backup (won't be used if KMS enabled)
# ALGORAND_ADMIN_MNEMONIC=<backup_only>
```

**Commit changes:**
```bash
git add .env.testnet .env.mainnet
git commit -m "Configure AWS KMS for Algorand signing"
```

---

### Step 6: Update Blockchain Services

**When:** After .env files are updated
**Estimated time:** 30-60 minutes

**Files to update:**

1. **`config/settings.py`** - Add KMS configuration
2. **`blockchain/algorand_sponsor_service.py`** - Use KMSSigner
3. **`blockchain/algorand_account_manager.py`** - Update signing
4. **Any other files that use mnemonic-based signing**

**Example changes:**

**Before (settings.py):**
```python
ALGORAND_ADMIN_MNEMONIC = config('ALGORAND_ADMIN_MNEMONIC')
ALGORAND_SPONSOR_ADDRESS = config('ALGORAND_SPONSOR_ADDRESS')
```

**After (settings.py):**
```python
USE_KMS_SIGNING = config('USE_KMS_SIGNING', default=False, cast=bool)

if USE_KMS_SIGNING:
    from blockchain.kms_manager import AlgorandKMSManager
    KMS_KEY_ALIAS = config('KMS_KEY_ALIAS_TESTNET' if ENV == 'testnet' else 'KMS_KEY_ALIAS_MAINNET')
    KMS_REGION = config('KMS_REGION', default='eu-central-2')

    kms_manager = AlgorandKMSManager(region_name=KMS_REGION)
    ALGORAND_SPONSOR_ADDRESS = kms_manager.get_address(KMS_KEY_ALIAS)
else:
    ALGORAND_ADMIN_MNEMONIC = config('ALGORAND_ADMIN_MNEMONIC')
    ALGORAND_SPONSOR_ADDRESS = config('ALGORAND_SPONSOR_ADDRESS')
```

**Before (sponsor_service.py):**
```python
from algosdk import mnemonic

private_key = mnemonic.to_private_key(settings.ALGORAND_ADMIN_MNEMONIC)
signed_txn = unsigned_txn.sign(private_key)
```

**After (sponsor_service.py):**
```python
from blockchain.kms_manager import KMSSigner

if settings.USE_KMS_SIGNING:
    signer = KMSSigner(settings.KMS_KEY_ALIAS)
    signed_txn = signer.sign_transaction(unsigned_txn)
else:
    # Fallback to old method
    from algosdk import mnemonic
    private_key = mnemonic.to_private_key(settings.ALGORAND_ADMIN_MNEMONIC)
    signed_txn = unsigned_txn.sign(private_key)
```

**Testing:**
1. Test all blockchain operations on testnet
2. Verify transactions are signed correctly
3. Check CloudTrail logs show KMS operations

---

### Step 7: Clean Git History

**When:** After services are updated and tested
**Estimated time:** 10 minutes

**⚠️ WARNING:** This rewrites git history!

**Prerequisites:**
- All changes committed
- No uncommitted files
- Team members notified

**Commands:**
```bash
cd /Users/julian/Confio

# Dry run first (preview changes)
./scripts/git/clean_exposed_credentials.sh --dry-run

# Review the output, then execute
./scripts/git/clean_exposed_credentials.sh --execute
```

**What this does:**
- Creates backup branch
- Rewrites all commits to replace compromised mnemonic with `<REDACTED_MNEMONIC>`
- Removes mnemonic from entire git history

**After cleanup:**
```bash
# Verify cleanup worked
git log --all --full-history -S "congress jaguar" | grep commit
# Should return nothing

# Force push to GitHub
git push origin --force --all
git push origin --force --tags
```

**⚠️ CRITICAL:** Notify all team members:
- They MUST delete their local clones
- They MUST clone fresh from GitHub
- DO NOT merge old branches

---

### Step 8: Fund New Mainnet Address

**When:** After git history is cleaned and pushed
**Estimated time:** 5 minutes

**Mainnet Address:** `ZS2HK5N7BZV46ZZGDOQBGFTN3JSXGAFVJFG33WAEP47JQMASSSJIQL7HI4`

**How to fund:**
1. Use your existing mainnet accounts to send ALGO
2. Transfer enough for:
   - Minimum balance requirements (~0.5 ALGO)
   - Transaction fees (~100-500 transactions worth)
   - Total recommendation: 5-10 ALGO initially

**Verification:**
```bash
# Check balance
curl -s "https://mainnet-api.4160.nodely.dev/v2/accounts/ZS2HK5N7BZV46ZZGDOQBGFTN3JSXGAFVJFG33WAEP47JQMASSSJIQL7HI4" \
  | python3 -m json.tool | grep -A 1 "\"amount\""
```

---

### Step 9: Deploy New Mainnet Contracts

**When:** After mainnet address is funded
**Estimated time:** 2-4 hours

**⚠️ THIS IS THE BIG ONE!**

Your old mainnet contracts are permanently compromised. You need to:

1. **Deploy new CONFIO token contract**
   - New admin: `ZS2HK5N7BZV46ZZGDOQBGFTN3JSXGAFVJFG33WAEP47JQMASSSJIQL7HI4`
   - New asset ID
   - Cannot recover old token (ASA 3198568509)

2. **Deploy new application contracts**
   - Payment contracts
   - Reward contracts
   - P2P exchange contracts
   - All with new admin address

3. **Update mobile app**
   - New contract addresses
   - New asset IDs
   - Deploy updated app to stores

4. **Notify users** (if applicable)
   - Token migration announcement
   - Instructions for users
   - Support for migration issues

**Commands:**
```bash
# Deploy new CONFIO token
# (Your existing deployment scripts, but with new admin)

# Deploy reward contracts
# Deploy payment contracts
# Deploy P2P contracts

# Update mobile app configuration
# Test thoroughly on mainnet
# Submit to app stores
```

**Budget:**
- Contract deployment fees: ~5-10 ALGO
- Testing transactions: ~1-2 ALGO
- Buffer: Keep 10+ ALGO in sponsor account

---

### Step 10: Monitor and Verify

**When:** After mainnet deployment
**Ongoing:** Daily for first week, then weekly

**What to monitor:**

1. **CloudTrail Logs**
```bash
# View KMS operations
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=ResourceType,AttributeValue=AWS::KMS::Key \
  --region eu-central-2 \
  --max-results 50
```

2. **KMS Costs**
```bash
# Check AWS billing dashboard
# Expected: $2-5/month
```

3. **Transaction Success Rate**
- Monitor application logs
- Check for signing errors
- Verify all transactions confirming

4. **Security Alerts**
- Set up CloudWatch alarms for unusual KMS access
- Monitor for unauthorized access attempts

---

## Summary Checklist

Use this checklist to track progress:

### Setup Phase
- [ ] IAM permissions granted to user Julian
- [ ] Keys imported into AWS KMS
- [ ] Testnet address funded (10 ALGO)
- [ ] KMS signing tested successfully on testnet
- [ ] .env files updated with KMS configuration

### Code Updates
- [ ] settings.py updated for KMS
- [ ] Blockchain services updated to use KMSSigner
- [ ] All mnemonic-based signing replaced
- [ ] Tested on testnet
- [ ] Code changes committed

### History Cleanup
- [ ] Git history cleaned (mnemonic removed)
- [ ] Verified cleanup worked
- [ ] Force pushed to GitHub
- [ ] Team members notified to re-clone

### Mainnet Migration
- [ ] Mainnet address funded (5-10 ALGO)
- [ ] New CONFIO token deployed
- [ ] New contracts deployed
- [ ] Mobile app updated
- [ ] Users notified (if applicable)

### Monitoring
- [ ] CloudTrail logging verified
- [ ] CloudWatch alarms configured
- [ ] Daily monitoring set up
- [ ] Incident response plan updated

---

## Estimated Timeline

| Phase | Time | Can Start |
|-------|------|-----------|
| Get IAM permissions | 10-15 min | Now (waiting for admin) |
| Import keys to KMS | 5 min | After IAM permissions |
| Fund & test testnet | 5 min | After keys imported |
| Update .env files | 5 min | After testnet test passes |
| Update blockchain services | 30-60 min | After .env updated |
| Clean git history | 10 min | After services tested |
| Fund mainnet | 5 min | After history cleaned |
| Deploy new contracts | 2-4 hours | After mainnet funded |
| Monitor & verify | Ongoing | After deployment |

**Total estimated time:** 4-6 hours (excluding waiting for admin)

---

## Support Resources

- **AWS KMS Documentation:** `docs/AWS_KMS_SETUP.md`
- **Security Incident Report:** `SECURITY_INCIDENT_REPORT.md`
- **Setup Instructions:** `scripts/kms/SETUP_INSTRUCTIONS.md`
- **IAM Policy:** `scripts/kms/confio-kms-policy.json`
- **Git Cleanup Script:** `scripts/git/clean_exposed_credentials.sh`

---

## Emergency Contacts

If you need help:
1. Check troubleshooting section in `docs/AWS_KMS_SETUP.md`
2. Review AWS CloudTrail logs for detailed errors
3. Verify AWS credentials are configured correctly
4. Check that git-crypt is unlocked for encrypted files

---

**Last Updated:** December 2, 2024
**Status:** Ready to proceed with Step 1 (IAM permissions)
