# EC2 Deployment Steps After Git History Cleanup

## Summary of Changes
- Git history cleaned to remove plaintext secrets from 787 commits
- Force pushed to GitHub (commit hash changed: e376021d → 7fe2bce6)
- All secrets now fetched from AWS Secrets Manager instead of .env files
- .env files cleaned but remain git-crypt encrypted

## Prerequisites
✅ EC2 IAM policy already includes Guardarian secret
✅ All secrets created in AWS Secrets Manager:
   - RDS_SECRET (database password)
   - prod/django-secret (Django SECRET_KEY)
   - prod/twilio-api (Twilio API key and secret)
   - prod/telegram-bot (Telegram bot token)
   - prod/guardarian-api-key (Guardarian API key)

## Step 1: Verify EC2 IAM Role Policy

1. Go to AWS Console → IAM → Roles
2. Find role: `ConfioS3PresignRole` (or whatever role is attached to your EC2 instance)
3. Check if the role has a policy with these permissions:
   - secretsmanager:GetSecretValue for all 5 secrets listed above
   - ssm:GetParameter for /confio/* parameters
   - kms:Decrypt for key `26fb79ac-af37-454e-80bc-eded48220488`

4. If NOT present, attach the policy from `/Users/julian/Confio/tmp/ec2-secrets-policy.json`:
   ```bash
   # On your local Mac:
   aws iam put-role-policy \
     --role-name ConfioS3PresignRole \
     --policy-name SecretsManagerAccess \
     --policy-document file:///Users/julian/Confio/tmp/ec2-secrets-policy.json \
     --region eu-central-2
   ```

## Step 2: SSH to EC2 and Update Repository

```bash
# SSH to EC2
ssh ec2-user@<your-ec2-ip>

# Navigate to your Django project directory
cd /path/to/Confio  # Replace with actual path

# IMPORTANT: Backup current directory first
cd ..
cp -r Confio Confio-backup-before-history-cleanup
cd Confio

# Check git-crypt status
git-crypt status | head -20

# Unlock git-crypt before force pull (if locked)
git-crypt unlock /path/to/git-crypt.key  # Use your key path

# Force pull the cleaned history
git fetch origin
git reset --hard origin/main

# Verify commit hash changed
git log -1
# Should show commit hash: 7fe2bce6 (new cleaned history)

# Verify git-crypt still works
git-crypt status | head -20
# .env files should still show as "encrypted"
```

## Step 3: Install boto3 (if not already installed)

```bash
# Activate your virtual environment
source myvenv/bin/activate  # Or wherever your venv is

# Install boto3 for AWS Secrets Manager access
pip install boto3==1.37.34

# Verify installation
python -c "import boto3; print(boto3.__version__)"
```

## Step 4: Test Secrets Fetching

```bash
# Test if EC2 can fetch secrets
python -c "
from config.secrets import get_secret
try:
    secret = get_secret('prod/django-secret')
    print('✅ Successfully fetched Django secret')
except Exception as e:
    print(f'❌ Failed to fetch secret: {e}')
"

# Test all secrets
python -c "
from config.secrets import get_secret
secrets = [
    'RDS_SECRET',
    'prod/django-secret',
    'prod/twilio-api',
    'prod/telegram-bot',
    'prod/guardarian-api-key'
]
for secret_name in secrets:
    try:
        get_secret(secret_name)
        print(f'✅ {secret_name}')
    except Exception as e:
        print(f'❌ {secret_name}: {e}')
"
```

## Step 5: Restart Django Application

```bash
# Restart your Django application (method depends on your setup)

# If using systemd:
sudo systemctl restart confio.service  # Replace with your service name
sudo systemctl status confio.service

# If using supervisord:
sudo supervisorctl restart confio
sudo supervisorctl status

# If running manually:
# Kill existing Django process
pkill -f "manage.py runserver"
# Start new process
source myvenv/bin/activate
python manage.py runserver 0.0.0.0:8000

# Check Django logs for errors
tail -f /var/log/confio/django.log  # Replace with your log path
```

## Step 6: Verify Production Functionality

Test the following features to ensure secrets are working:

1. **Database Connection** (RDS_SECRET)
   ```bash
   python manage.py dbshell
   # Should connect successfully
   \q
   ```

2. **Django Admin Login** (prod/django-secret)
   - Open browser: `https://your-domain/admin/`
   - Should load without errors

3. **Twilio SMS** (prod/twilio-api)
   - Test phone verification flow in your app
   - Check Twilio logs for successful API calls

4. **Telegram Bot** (prod/telegram-bot)
   - Send test message to your bot
   - Verify bot responds

5. **Guardarian Integration** (prod/guardarian-api-key)
   - Test payment flow that uses Guardarian
   - Check API responses

## Step 7: Monitor Logs

```bash
# Check Django logs for any secret-related errors
tail -f /var/log/confio/django.log | grep -i "secret\|boto3\|aws"

# Check for any application errors
tail -f /var/log/confio/error.log
```

## Troubleshooting

### Error: "Access denied to secret"
- Verify EC2 IAM role has correct policy (Step 1)
- Check AWS region is `eu-central-2`
- Verify secret ARN matches region

### Error: "boto3 not available"
- Install boto3: `pip install boto3==1.37.34`
- Restart Django application

### Error: "Secret not found"
- Verify secret name exactly matches (case-sensitive)
- Check secret exists in eu-central-2 region
- Run: `aws secretsmanager list-secrets --region eu-central-2`

### Error: "git-crypt: decryption failed"
- Re-unlock git-crypt: `git-crypt unlock /path/to/key`
- If key missing, restore from backup on Mac

### Application won't start
- Check Django settings: `python manage.py check`
- Test secret fetching manually (Step 4)
- Check emergency fallback to .env files is working

## Rollback Plan (if needed)

If deployment fails and you need to rollback:

```bash
# On EC2
cd /path/to/Confio
git reflog
git reset --hard <previous-commit-hash>  # Use e376021d (old hash)
git push origin main --force

# On Mac
cd /Users/julian/Confio
git fetch origin
git reset --hard origin/main
```

## Cleanup After Success

Once everything works:

```bash
# On EC2
rm -rf /path/to/Confio-backup-before-history-cleanup

# On your Mac
rm -rf /Users/julian/Confio-OLD
rm -rf /Users/julian/Confio-backup.git
rm -rf /Users/julian/Confio-clean.git
```

## Notes

- **Single Source of Truth**: All secrets now come from AWS Secrets Manager
- **Emergency Fallback**: If AWS fails, app falls back to .env files (still encrypted with git-crypt)
- **Caching**: Secrets cached in memory with @lru_cache to reduce AWS API calls
- **Audit**: All secret access logged in CloudTrail
- **Git History**: Cleaned 787 commits, removed 6 plaintext secrets
