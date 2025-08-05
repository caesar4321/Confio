# Security Procedures for Confío

## 🔐 Secret Management Guidelines

### 1. Environment Variables (.env files)

#### ✅ DO:
- Always use `.env.example` as a template (without actual secrets)
- Ensure `.env` files are in `.gitignore`
- Verify git-crypt encryption with `git-crypt status .env` before committing
- Use placeholder values in documentation and examples
- Rotate credentials immediately if exposed

#### ❌ DON'T:
- Never commit real secrets, even temporarily
- Don't include secrets in commit messages
- Don't hardcode secrets in source code
- Don't share .env files via email/chat

### 2. Pre-Commit Checklist

Before EVERY commit, verify:
```bash
# Check git-crypt status for all sensitive files
git-crypt status

# Look for any unencrypted sensitive files
git-crypt status | grep "NOT ENCRYPTED"

# Verify no secrets in staged files
git diff --staged | grep -E "(SECRET|PRIVATE_KEY|CLIENT_SECRET|API_KEY|TOKEN)"
```

### 3. Git-Crypt Setup

#### Initial Setup (already done):
```bash
# Initialize git-crypt
git-crypt init

# Add git-crypt rules to .gitattributes
.env filter=git-crypt diff=git-crypt
apps/.env filter=git-crypt diff=git-crypt
*.pem filter=git-crypt diff=git-crypt
*.keystore filter=git-crypt diff=git-crypt
*_credentials.csv filter=git-crypt diff=git-crypt
```

#### Daily Usage:
```bash
# Before working with secrets
git-crypt unlock

# After making changes
git-crypt status  # Verify encryption
git add .
git commit -m "chore: update configurations"

# Files are automatically encrypted on commit
```

### 4. OAuth Client ID Changes

⚠️ **CRITICAL**: Changing OAuth Client IDs changes user Aptos addresses!

If you must change OAuth credentials:
1. Keep the same Client ID if possible (only rotate the secret)
2. If Client ID must change, implement a migration plan:
   - Notify users in advance
   - Provide fund transfer tools
   - Support both old and new IDs temporarily

### 5. Emergency Response Plan

If secrets are exposed:
1. **Immediately** rotate the exposed credentials
2. Check if the secret was used maliciously
3. Notify affected users if necessary
4. Review how the exposure happened
5. Update procedures to prevent recurrence

### 6. Recommended Tools

#### A. Pre-commit Hooks
Install pre-commit to catch secrets before they're committed:

```bash
pip install pre-commit
```

Create `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.4.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
  
  - repo: https://github.com/zricethezav/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks
```

#### B. GitHub Secret Scanning
- Enable secret scanning alerts in repository settings
- Configure push protection to block commits with secrets
- Set up email notifications for detected secrets

### 7. Team Guidelines

- New team members must be trained on these procedures
- Regular security audits (monthly) to check for exposed secrets
- Use a password manager for sharing credentials
- Document which services use which credentials

### 8. CI/CD Secrets

For deployment scripts:
- Use GitHub Secrets for CI/CD variables
- Never echo or log secret values
- Use minimal permission scopes
- Rotate CI/CD secrets quarterly

### 9. Development vs Production

- Use different credentials for development and production
- Development credentials should have limited access
- Production credentials should never be on developer machines
- Use environment-specific naming (e.g., `DEV_API_KEY`, `PROD_API_KEY`)

### 10. Audit Trail

Maintain a secret rotation log:
| Date | Secret Type | Reason | Rotated By |
|------|-------------|---------|------------|
| 2025-08-05 | Google OAuth | Exposed in git | Julian |
| ... | ... | ... | ... |

---

## Quick Reference Card

```bash
# Before starting work
git-crypt unlock

# Before committing
git-crypt status
git diff --staged | grep -i secret

# After exposure
1. Rotate credential immediately
2. Update .env file  
3. Ensure git-crypt is active
4. Commit with generic message
5. Document in rotation log
```

## Emergency Contacts

- Security Lead: [Name] - [Contact]
- DevOps Lead: [Name] - [Contact]
- CTO: Julian Moon - [Contact]