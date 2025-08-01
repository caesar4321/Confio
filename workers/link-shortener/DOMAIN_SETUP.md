# Custom Domain Setup Guide for confio.lat

## Prerequisites
- Access to Cloudflare dashboard for confio.lat domain
- Worker already deployed (✅ Done: confio-link-shortener)

## Step 1: Get Your Zone ID

1. Login to [Cloudflare Dashboard](https://dash.cloudflare.com)
2. Click on your domain `confio.lat`
3. On the right sidebar, find and copy your **Zone ID**
   - It looks like: `7c5dae5552338874e5053f2534d2767a`

## Step 2: Update wrangler.toml

Replace `YOUR_ZONE_ID` in wrangler.toml with your actual Zone ID:

```toml
[env.production]
workers_dev = false
routes = [
  { pattern = "confio.lat/*", zone_id = "YOUR_ZONE_ID_HERE" },
  { pattern = "www.confio.lat/*", zone_id = "YOUR_ZONE_ID_HERE" }
]
```

## Step 3: Set Up Routes in Cloudflare Dashboard

### Option A: Using Workers Routes (Recommended)

1. In Cloudflare Dashboard, select your domain `confio.lat`
2. Click **Workers Routes** in the left sidebar
3. Click **Add route**
4. Add these routes:

   **Route 1:**
   - Route: `confio.lat/*`
   - Worker: `confio-link-shortener`
   - Click **Save**

   **Route 2:**
   - Route: `www.confio.lat/*`
   - Worker: `confio-link-shortener`
   - Click **Save**

### Option B: Using Custom Domains (Alternative)

1. Go to **Workers & Pages** in Cloudflare Dashboard
2. Click on `confio-link-shortener`
3. Go to **Custom Domains** tab
4. Click **Add Custom Domain**
5. Enter `confio.lat`
6. Follow the DNS setup if needed

## Step 4: DNS Configuration

Ensure you have these DNS records:

```
Type  Name    Content           Proxy Status
A     @       192.0.2.1         Proxied (Orange Cloud)
A     www     192.0.2.1         Proxied (Orange Cloud)
```

Note: The IP address doesn't matter when proxied through Cloudflare.

## Step 5: Deploy with Custom Domain

After updating wrangler.toml with your Zone ID:

```bash
cd workers/link-shortener
npx wrangler deploy --env production
```

## Step 6: Test Your Setup

1. **Test root domain redirect**:
   ```bash
   curl -I https://confio.lat/
   # Should redirect to landing page
   ```

2. **Test short link**:
   ```bash
   curl -I https://confio.lat/beta2024
   # Should redirect based on user agent
   ```

3. **Test API**:
   ```bash
   curl https://confio.lat/api/links/beta2024
   # Should return link stats
   ```

4. **Test apple-app-site-association**:
   ```bash
   curl https://confio.lat/.well-known/apple-app-site-association
   # Should return JSON configuration
   ```

## Troubleshooting

### "Route pattern must include your zone"
- Make sure your domain is active in Cloudflare
- Verify the zone_id in wrangler.toml matches your domain

### Worker not responding
- Check Workers Routes in dashboard
- Ensure routes are active and pointing to correct worker
- Check worker logs: `npx wrangler tail`

### DNS issues
- Ensure DNS records are proxied (orange cloud)
- Wait 5-10 minutes for DNS propagation

## Next Steps

1. Update Apple App ID and TestFlight URL in wrangler.toml
2. Redeploy with production settings
3. Test iOS Universal Links
4. Set up monitoring and analytics