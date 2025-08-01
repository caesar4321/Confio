# Cloudflare Workers Link Shortener Deployment Guide

## Prerequisites

1. Cloudflare account with Workers enabled
2. Node.js 16+ installed
3. Wrangler CLI installed: `npm install -g wrangler`

## Setup Steps

### 1. Configure Cloudflare Account

1. Log in to Cloudflare dashboard
2. Note your Account ID from the right sidebar
3. Create two KV namespaces:
   ```bash
   wrangler kv:namespace create "LINKS"
   wrangler kv:namespace create "ANALYTICS"
   ```
4. Save the namespace IDs from the output

### 2. Update Configuration

Edit `wrangler.toml` with your actual values:

```toml
name = "confio-link-shortener"
account_id = "YOUR_ACCOUNT_ID"

[[kv_namespaces]]
binding = "LINKS"
id = "YOUR_LINKS_NAMESPACE_ID"

[[kv_namespaces]]
binding = "ANALYTICS"
id = "YOUR_ANALYTICS_NAMESPACE_ID"

[vars]
APPLE_APP_ID = "YOUR_APPLE_APP_ID"
ANDROID_PACKAGE_ID = "com.Confio.Confio"
IOS_BUNDLE_ID = "com.Confio.Confio"
TESTFLIGHT_URL = "https://testflight.apple.com/join/YOUR_CODE"
PLAY_STORE_URL = "https://play.google.com/store/apps/details?id=com.Confio.Confio"
LANDING_PAGE_URL = "https://confio.lat"
```

### 3. Deploy to Cloudflare

```bash
# Install dependencies
npm install

# Build TypeScript
npm run build

# Deploy to Cloudflare
wrangler deploy
```

### 4. Configure Custom Domain

1. In Cloudflare dashboard, go to Workers & Pages
2. Select your deployed worker
3. Go to "Custom Domains" tab
4. Add domain: `confio.lat`
5. Add these routes:
   - `confio.lat/*`
   - `www.confio.lat/*`

### 5. Deploy Admin UI

```bash
# Deploy admin interface
wrangler pages deploy public --project-name=confio-admin
```

Access admin UI at: `https://confio-admin.pages.dev/admin.html`

### 6. iOS Universal Links Setup

1. Update your Apple App ID and Team ID in `public/apple-app-site-association`
2. Deploy the file to your domain root:
   ```bash
   # The worker already serves this file at /.well-known/apple-app-site-association
   ```

3. In your iOS app's `Info.plist`, add:
   ```xml
   <key>CFBundleURLTypes</key>
   <array>
       <dict>
           <key>CFBundleURLSchemes</key>
           <array>
               <string>confio</string>
           </array>
       </dict>
   </array>
   ```

4. In your app's entitlements, add:
   ```xml
   <key>com.apple.developer.associated-domains</key>
   <array>
       <string>applinks:confio.lat</string>
   </array>
   ```

## Testing

### Create a test link:
```bash
curl -X POST https://confio.lat/api/links \
  -H "Content-Type: application/json" \
  -d '{
    "type": "referral",
    "payload": "whatsapp|user123",
    "slug": "test123"
  }'
```

### Test redirect:
- iOS: Open `https://confio.lat/test123` on iPhone
- Android: Open `https://confio.lat/test123` on Android
- Desktop: Open `https://confio.lat/test123` on computer

### Check analytics:
```bash
curl https://confio.lat/api/links/test123
```

## Security Considerations

1. Add rate limiting in production:
   ```typescript
   // Add to worker code
   const rateLimit = await env.RATE_LIMITER.get(ip);
   if (rateLimit && parseInt(rateLimit) > 100) {
     return new Response('Rate limited', { status: 429 });
   }
   ```

2. Add authentication to admin endpoints:
   ```typescript
   const auth = request.headers.get('Authorization');
   if (auth !== `Bearer ${env.ADMIN_TOKEN}`) {
     return new Response('Unauthorized', { status: 401 });
   }
   ```

3. Enable Cloudflare security features:
   - WAF rules
   - DDoS protection
   - Bot fight mode

## Monitoring

1. View logs: `wrangler tail`
2. Check KV storage: Cloudflare dashboard → Workers → KV
3. Monitor analytics: Cloudflare dashboard → Analytics → Workers

## Costs

- Workers: Free for up to 100,000 requests/day
- KV storage: Free for up to 1GB storage and 100,000 reads/day
- Custom domain: Included with Cloudflare account

## Troubleshooting

### Links not redirecting properly
- Check KV namespace bindings in wrangler.toml
- Verify environment variables are set correctly
- Check worker logs: `wrangler tail`

### iOS Universal Links not working
- Verify apple-app-site-association is accessible at `https://confio.lat/.well-known/apple-app-site-association`
- Check Team ID and Bundle ID match your app
- Test with Apple's validator: https://search.developer.apple.com/appsearch-validation-tool

### Admin UI not loading
- Check CORS headers in worker
- Verify admin deployment URL
- Check browser console for errors