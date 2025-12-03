# AWS KMS Setup Guide for Algorand Signing

This guide explains how to set up AWS KMS (Key Management Service) for secure Algorand transaction signing.

## Table of Contents
1. [Why KMS?](#why-kms)
2. [Prerequisites](#prerequisites)
3. [Initial Setup](#initial-setup)
4. [Key Management](#key-management)
5. [Integration](#integration)
6. [Testing](#testing)
7. [Troubleshooting](#troubleshooting)

---

## Why KMS?

### Security Benefits

| Feature | Mnemonic in .env | AWS KMS |
|---------|-----------------|---------|
| Key Storage | Plain text (encrypted by git-crypt) | FIPS 140-2 Level 2 HSM |
| Key Exposure | Loaded in application memory | Retrieved only during signing |
| Access Control | File permissions | IAM policies + MFA |
| Audit Logging | None | CloudTrail logs all access |
| Key Rotation | Manual | Can be automated |
| Backup/Recovery | Manual backup phrase (for recovery only) | AWS managed backups |
| Compliance | Limited | HIPAA, PCI-DSS compliant |

### Cost

- **KMS Key:** $1/month per key
- **API Calls:** $0.03 per 10,000 requests
- **Estimated Monthly Cost:** ~$2-5 for typical usage

---

## Prerequisites

### 1. AWS Account Setup

You need an AWS account with:
- IAM user with KMS permissions
- AWS CLI configured
- boto3 Python library installed

### 2. Install Dependencies

```bash
# Install AWS SDK
myvenv/bin/pip install boto3

# Install AWS CLI (if not already installed)
# macOS
brew install awscli

# Linux
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
```

### 3. Configure AWS Credentials

```bash
# Configure AWS CLI
aws configure

# You'll be prompted for:
# AWS Access Key ID: <your_access_key>
# AWS Secret Access Key: <your_secret_key>
# Default region name: eu-central-2  # IMPORTANT: Use Zurich region
# Default output format: json
```

### 4. Create IAM Policy

Create a custom IAM policy for Confio KMS access:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ConfioKMSAccess",
      "Effect": "Allow",
      "Action": [
        "kms:CreateKey",
        "kms:CreateAlias",
        "kms:UpdateAlias",
        "kms:DescribeKey",
        "kms:ListKeys",
        "kms:ListAliases",
        "kms:ListResourceTags",
        "kms:TagResource",
        "kms:ScheduleKeyDeletion",
        "kms:CancelKeyDeletion"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "eu-central-2"
        }
      }
    },
    {
      "Sid": "ConfioSSMAccess",
      "Effect": "Allow",
      "Action": [
        "ssm:PutParameter",
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:DeleteParameter",
        "ssm:DescribeParameters"
      ],
      "Resource": "arn:aws:ssm:eu-central-2:*:parameter/confio/algorand/*"
    },
    {
      "Sid": "ConfioKMSDecrypt",
      "Effect": "Allow",
      "Action": [
        "kms:Decrypt",
        "kms:DescribeKey"
      ],
      "Resource": "*",
      "Condition": {
        "StringLike": {
          "kms:ViaService": "ssm.eu-central-2.amazonaws.com"
        }
      }
    }
  ]
}
```

Save this as `confio-kms-policy.json` and create the policy:

```bash
aws iam create-policy \
  --policy-name ConfioKMSPolicy \
  --policy-document file://confio-kms-policy.json \
  --region eu-central-2
```

Attach to your IAM user or EC2 instance role:

```bash
aws iam attach-user-policy \
  --user-name your-iam-user \
  --policy-arn arn:aws:iam::YOUR_ACCOUNT_ID:policy/ConfioKMSPolicy
```

---

## Initial Setup

### Option A: Create New Algorand Accounts in KMS

Use this if you're setting up fresh accounts:

```bash
# Run the setup script
DJANGO_SETTINGS_MODULE=config.settings myvenv/bin/python scripts/kms/setup_kms_keys.py --create-new
```

This will:
1. Generate new Algorand keypairs
2. Store private keys encrypted in AWS KMS
3. Output addresses and backup mnemonics
4. Create KMS aliases for easy reference

**⚠️ CRITICAL:** Save the backup mnemonics securely! You'll need them for disaster recovery.

### Option B: Import Existing Accounts into KMS

Use this if you want to migrate your current sponsor accounts:

```bash
# Run the import script
DJANGO_SETTINGS_MODULE=config.settings myvenv/bin/python scripts/kms/setup_kms_keys.py --import-existing
```

You'll be prompted to enter your existing mnemonics securely (input is hidden).

**Note:** After importing, your old `.env` mnemonics can be removed once you verify KMS signing works.

---

## Key Management

### View Keys

```bash
# List all Algorand keys in KMS
DJANGO_SETTINGS_MODULE=config.settings myvenv/bin/python scripts/kms/setup_kms_keys.py --list
```

### Key Architecture in AWS

Your keys are stored in two places:

1. **AWS KMS:** Encryption key (master key)
   - Alias: `alias/confio-mainnet-sponsor` or `alias/confio-testnet-sponsor`
   - Purpose: Encrypts the actual Algorand private key
   - Never leaves AWS infrastructure

2. **AWS Systems Manager Parameter Store:** Encrypted private key
   - Path: `/confio/algorand/confio-mainnet-sponsor/private-key`
   - Encrypted using the KMS key
   - Decrypted on-demand during signing

### Key Rotation (Optional)

For enhanced security, you can rotate keys periodically:

```bash
# 1. Create new key
python scripts/kms/setup_kms_keys.py --create-new

# 2. Transfer funds from old address to new address
# 3. Update contracts to use new admin address
# 4. Schedule old key for deletion (30-day pending period)
```

---

## Integration

### Update Settings

Edit `config/settings.py`:

```python
# Add KMS configuration
USE_KMS_SIGNING = config('USE_KMS_SIGNING', default=False, cast=bool)
KMS_KEY_ALIAS_TESTNET = config('KMS_KEY_ALIAS_TESTNET', default='confio-testnet-sponsor')
KMS_KEY_ALIAS_MAINNET = config('KMS_KEY_ALIAS_MAINNET', default='confio-mainnet-sponsor')
KMS_REGION = config('KMS_REGION', default='eu-central-2')

# Update sponsor address configuration
if USE_KMS_SIGNING:
    from blockchain.kms_manager import AlgorandKMSManager
    kms_manager = AlgorandKMSManager(region_name=KMS_REGION)

    if ENV == 'testnet':
        ALGORAND_SPONSOR_ADDRESS = kms_manager.get_address(KMS_KEY_ALIAS_TESTNET)
    else:
        ALGORAND_SPONSOR_ADDRESS = kms_manager.get_address(KMS_KEY_ALIAS_MAINNET)
else:
    # Fallback to .env (KMS required in production)
    ALGORAND_SPONSOR_ADDRESS = config('ALGORAND_SPONSOR_ADDRESS')
```

### Update `.env` Files

Add to `.env.testnet` and `.env.mainnet`:

```bash
# Enable KMS signing
USE_KMS_SIGNING=True

# KMS configuration
KMS_KEY_ALIAS_TESTNET=confio-testnet-sponsor
KMS_KEY_ALIAS_MAINNET=confio-mainnet-sponsor
KMS_REGION=eu-central-2

# Optional: Keep old backup phrase securely (KMS used for signing)
# ALGORAND_ADMIN_MNEMONIC (backup only, not used for signing)=<your_backup_mnemonic>
```

### Update Signing Code

Replace KMS-based signing with KMS:

**Before (using mnemonic):**
```python
from algosdk import mnemonic

admin_mnemonic = os.environ.get('ALGORAND_ADMIN_MNEMONIC (backup only, not used for signing)')
private_key = mnemonic.to_private_key(admin_mnemonic)
signed_txn = unsigned_txn.sign(private_key)
```

**After (using KMS):**
```python
from blockchain.kms_manager import KMSSigner

signer = KMSSigner(
    key_alias='confio-mainnet-sponsor',  # or from settings
    region_name='eu-central-2'
)
signed_txn = signer.sign_transaction(unsigned_txn)
```

### Update Sponsor Service

Modify `blockchain/algorand_sponsor_service.py`:

```python
from django.conf import settings

class AlgorandSponsorService:
    def __init__(self):
        if settings.USE_KMS_SIGNING:
            from blockchain.kms_manager import KMSSigner
            self.signer = KMSSigner(
                key_alias=settings.KMS_KEY_ALIAS_MAINNET,
                region_name=settings.KMS_REGION
            )
            self.sponsor_address = self.signer.address
        else:
            # Legacy mnemonic-based approach
            from algosdk import mnemonic, account
            admin_mnemonic = settings.ALGORAND_ADMIN_MNEMONIC (backup only, not used for signing)
            self.private_key = mnemonic.to_private_key(admin_mnemonic)
            self.sponsor_address = account.address_from_private_key(self.private_key)
            self.signer = None

    def sign_transaction(self, transaction):
        if self.signer:
            return self.signer.sign_transaction(transaction)
        else:
            return transaction.sign(self.private_key)
```

---

## Testing

### Test on Testnet First

**ALWAYS test KMS signing on testnet before using on mainnet!**

```bash
# 1. Set environment to testnet
export CONFIO_ENV=testnet
export USE_KMS_SIGNING=True

# 2. Test key retrieval
myvenv/bin/python -c "
from blockchain.kms_manager import AlgorandKMSManager
manager = AlgorandKMSManager()
address = manager.get_address('confio-testnet-sponsor')
print(f'Testnet address: {address}')
"

# 3. Test transaction signing
myvenv/bin/python scripts/kms/test_kms_signing.py
```

### Create Test Signing Script

Create `scripts/kms/test_kms_signing.py`:

```python
#!/usr/bin/env python3
"""Test KMS signing with a simple payment transaction"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from algosdk.v2client import algod
from algosdk.transaction import PaymentTxn
from blockchain.kms_manager import KMSSigner

# Connect to testnet
algod_client = algod.AlgodClient("", "https://testnet-api.4160.nodely.dev")

# Initialize KMS signer
signer = KMSSigner('confio-testnet-sponsor')

print(f"Testing KMS signing for address: {signer.address}")

# Create test transaction (0 ALGO to self)
params = algod_client.suggested_params()
unsigned_txn = PaymentTxn(
    sender=signer.address,
    sp=params,
    receiver=signer.address,
    amt=0,
    note=b'KMS signing test'
)

print("Signing transaction with KMS...")
signed_txn = signer.sign_transaction(unsigned_txn)

print("Submitting transaction...")
txid = algod_client.send_transaction(signed_txn)

print(f"✓ SUCCESS! Transaction ID: {txid}")
print(f"View on AlgoExplorer: https://testnet.algoexplorer.io/tx/{txid}")
```

---

## Troubleshooting

### Error: "Access Denied" or "UnauthorizedOperation"

**Cause:** IAM permissions not configured correctly

**Solution:**
1. Verify IAM policy is attached: `aws iam list-attached-user-policies --user-name YOUR_USER`
2. Check policy allows KMS operations in eu-central-2
3. If using EC2, verify instance role has correct permissions

### Error: "Parameter not found"

**Cause:** Private key not stored in Parameter Store

**Solution:**
1. Run setup script again: `python scripts/kms/setup_kms_keys.py --import-existing`
2. Verify parameter exists: `aws ssm get-parameter --name /confio/algorand/confio-testnet-sponsor/private-key --region eu-central-2`

### Error: "KMS key not found"

**Cause:** Key alias doesn't exist

**Solution:**
1. List aliases: `aws kms list-aliases --region eu-central-2`
2. Create key if missing: `python scripts/kms/setup_kms_keys.py --create-new`

### Error: "Signature verification failed"

**Cause:** Wrong key being used for signing

**Solution:**
1. Verify address matches: `python scripts/kms/setup_kms_keys.py --list`
2. Check transaction sender matches KMS address
3. Ensure testnet/mainnet key alias is correct

### Performance Issues

**Symptom:** Slow transaction signing

**Cause:** KMS API calls have network latency (~100-200ms per call)

**Solutions:**
1. Batch transactions when possible
2. Use atomic transfers to group operations
3. Consider caching addresses (don't fetch from KMS every time)
4. For high-throughput scenarios, consider hybrid approach with local HSM

---

## Security Best Practices

### 1. Principle of Least Privilege

Only grant KMS permissions to services that need them:

```json
{
  "Effect": "Allow",
  "Action": ["kms:Decrypt"],
  "Resource": "arn:aws:kms:eu-central-2:*:key/*",
  "Condition": {
    "StringEquals": {
      "kms:ViaService": "ssm.eu-central-2.amazonaws.com"
    }
  }
}
```

### 2. Enable MFA for Key Deletion

Prevent accidental key deletion:

```bash
aws kms put-key-policy \
  --key-id alias/confio-mainnet-sponsor \
  --policy-name default \
  --policy file://kms-policy-with-mfa.json
```

### 3. Monitor with CloudTrail

Enable logging for all KMS operations:

```bash
aws cloudtrail create-trail \
  --name confio-kms-audit \
  --s3-bucket-name confio-audit-logs \
  --region eu-central-2

aws cloudtrail start-logging --name confio-kms-audit
```

### 4. Backup Mnemonics Offline

Store backup mnemonics in:
- Hardware security module (Ledger, Trezor)
- Fireproof safe
- Bank safety deposit box
- Multiple encrypted USB drives in separate locations

**Never store mnemonics in:**
- Email
- Cloud storage (Dropbox, Google Drive)
- Slack/Discord
- Git repository
- Application logs

### 5. Regular Security Audits

- Review CloudTrail logs monthly
- Audit IAM permissions quarterly
- Test disaster recovery procedures annually

---

## Disaster Recovery

### Scenario: AWS Account Compromised

1. **Immediate Actions:**
   - Rotate AWS credentials
   - Schedule KMS keys for deletion
   - Create new KMS keys with backup mnemonics

2. **Recovery:**
   ```bash
   # Create new keys from backup mnemonics
   python scripts/kms/setup_kms_keys.py --import-existing

   # Transfer funds to new addresses
   # Update smart contracts
   ```

### Scenario: Lost Access to AWS Account

1. **Prerequisites:**
   - Must have backup mnemonics stored securely

2. **Recovery:**
   ```bash
   # Restore from mnemonic without KMS
   # Temporarily disable KMS in settings
   export USE_KMS_SIGNING=False

   # Add mnemonic to .env
   ALGORAND_ADMIN_MNEMONIC (backup only, not used for signing)="your 25 word backup mnemonic"

   # Transfer funds to new KMS-managed account
   ```

---

## Migration Checklist

Use this checklist when migrating from mnemonic-based to KMS-based signing:

- [ ] AWS account configured with IAM permissions
- [ ] boto3 installed: `myvenv/bin/pip install boto3`
- [ ] AWS CLI configured for eu-central-2 region
- [ ] KMS keys created or imported
- [ ] Backup mnemonics stored securely (offline)
- [ ] `USE_KMS_SIGNING=True` in .env files
- [ ] settings.py updated with KMS configuration
- [ ] Sponsor service updated to use KMSSigner
- [ ] All scripts updated to use KMS (no hardcoded mnemonics)
- [ ] Tested on testnet successfully
- [ ] Verified transaction on testnet AlgoExplorer
- [ ] CloudTrail logging enabled
- [ ] Team trained on KMS procedures
- [ ] Disaster recovery plan documented
- [ ] Old .env mnemonics removed (keep one offline backup)

---

## Cost Optimization

### Reduce KMS API Calls

1. **Cache Addresses:**
   ```python
   # Don't call KMS every time
   address = manager.get_address(key_alias)  # Cache this

   # Use cached address
   ALGORAND_SPONSOR_ADDRESS = address
   ```

2. **Batch Operations:**
   ```python
   # Sign multiple transactions at once
   signed_txns = signer.sign_transactions([txn1, txn2, txn3])
   ```

3. **Use Address Tags:**
   KMS stores addresses in tags - no decryption needed for address lookups

### Estimated Monthly Costs

**Low Usage (< 1000 transactions/month):**
- KMS Keys: $2 (2 keys × $1/month)
- API Calls: < $1
- **Total: ~$3/month**

**Medium Usage (10,000 transactions/month):**
- KMS Keys: $2
- API Calls: $3 (10,000 × $0.03/10k)
- **Total: ~$5/month**

**High Usage (100,000 transactions/month):**
- KMS Keys: $2
- API Calls: $30 (100,000 × $0.03/10k)
- **Total: ~$32/month**

---

## Support

For issues or questions:
1. Check [Troubleshooting](#troubleshooting) section
2. Review AWS KMS documentation: https://docs.aws.amazon.com/kms/
3. Check CloudTrail logs for detailed error messages
4. Contact security team for production issues

---

**Document Version:** 1.0
**Last Updated:** December 2, 2024
**Maintained By:** Security Team
