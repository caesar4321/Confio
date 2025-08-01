# Secure Setup Guide for Link Shortener Admin

## ⚠️ Security Alert
GitGuardian detected exposed credentials. Follow these steps to secure your deployment.

## Step 1: Git-Crypt Setup

This repository uses git-crypt to securely store credentials. The `wrangler.toml` file is encrypted.

### For authorized users with git-crypt key:
```bash
# Unlock the repository (if not already unlocked)
git-crypt unlock

# The wrangler.toml will contain the actual credentials
```

### For new team members:
1. Ask an existing team member to add your GPG key
2. They will run: `git-crypt add-gpg-user YOUR_GPG_KEY_ID`
3. Pull the latest changes and unlock: `git-crypt unlock`

## Step 2: Generate Secure 128-Character Password

```bash
# Using Python
python3 -c "import secrets; import string; chars = string.ascii_letters + string.digits; print(''.join(secrets.choice(chars) for _ in range(128)))"

# Using OpenSSL
openssl rand -base64 96 | tr -d '\n' | cut -c1-128

# Using Node.js
node -e "console.log(require('crypto').randomBytes(96).toString('base64').replace(/[^a-zA-Z0-9]/g, '').substring(0, 128))"
```

## Step 3: Admin Panel Access

The admin panel is now at a non-obvious URL:
```
https://confio.lat/dashboard-x7k9m2p5
```

**IMPORTANT**: 
- Do NOT share this URL publicly
- Do NOT commit this URL to any public repository
- Store it in your password manager

## Step 4: Additional Security Measures

### 1. IP Allowlist (Optional)
Add IP restrictions in Cloudflare dashboard:
- Go to Security → WAF → Custom Rules
- Create rule: `(http.request.uri.path contains "/dashboard-x7k9m2p5" and ip.src ne YOUR_IP)`
- Action: Block

### 2. Rate Limiting
Add rate limiting for admin panel:
```typescript
// In worker code
const rateLimiter = await env.RATE_LIMITS.get(`admin:${ip}`);
if (rateLimiter && parseInt(rateLimiter) > 5) {
  return new Response('Too many attempts', { status: 429 });
}
```

### 3. Audit Logging
Track all admin actions:
```typescript
await env.ANALYTICS.put(`admin:${Date.now()}`, JSON.stringify({
  action: 'link_created',
  user: env.ADMIN_USERNAME,
  ip: request.headers.get('cf-connecting-ip'),
  timestamp: new Date().toISOString()
}));
```

## Step 5: Remove Exposed Credentials from Git History

Since credentials were already pushed, you need to:

1. **Revoke Current Credentials**: The exposed password is compromised
2. **Clean Git History** (if needed):
   ```bash
   # This rewrites history - coordinate with team
   git filter-branch --force --index-filter \
     "git rm --cached --ignore-unmatch workers/link-shortener/wrangler.toml" \
     --prune-empty --tag-name-filter cat -- --all
   ```
3. **Force Push** (careful!):
   ```bash
   git push origin --force --all
   ```

## Step 6: Regular Security Practices

1. **Rotate Credentials Monthly**:
   ```bash
   npx wrangler secret put ADMIN_PASSWORD
   ```

2. **Monitor Access Logs**:
   ```bash
   npx wrangler tail --format pretty | grep dashboard-x7k9m2p5
   ```

3. **Use 2FA** (Future Enhancement):
   Consider implementing TOTP-based 2FA for admin access

## Environment Variables vs Secrets

### ❌ DON'T: Put in wrangler.toml (visible in git)
```toml
[vars]
ADMIN_PASSWORD = "mysecret"  # NO! This gets committed
```

### ✅ DO: Use Cloudflare Secrets
```bash
npx wrangler secret put ADMIN_PASSWORD
```

## Testing Your Secure Setup

1. **Verify secrets are set**:
   ```bash
   npx wrangler secret list
   ```

2. **Test admin access**:
   ```bash
   curl -u julian:YOUR_128_CHAR_PASSWORD https://confio.lat/dashboard-x7k9m2p5
   ```

3. **Check old URL returns 404**:
   ```bash
   curl https://confio.lat/admin
   # Should return "Invalid link" or 404
   ```

## Emergency Response

If credentials are compromised:

1. **Immediately change password**:
   ```bash
   npx wrangler secret put ADMIN_PASSWORD
   ```

2. **Check access logs** for unauthorized access:
   ```bash
   npx wrangler tail --format pretty
   ```

3. **Audit all recent links** created in admin panel

4. **Consider changing admin URL** in source code

Remember: Security is an ongoing process, not a one-time setup!