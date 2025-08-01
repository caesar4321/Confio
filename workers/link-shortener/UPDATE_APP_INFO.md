# How to Update Apple App ID and TestFlight URL

## Step 1: Get Your Apple App ID (Team ID)

1. Go to [Apple Developer Account](https://developer.apple.com/account)
2. Sign in with your Apple ID
3. Look for your **Team ID** in:
   - Membership section
   - Or in Certificates, Identifiers & Profiles
   - It's a 10-character code like `ABC123DEF4`

## Step 2: Get Your TestFlight Public Link

1. Go to [App Store Connect](https://appstoreconnect.apple.com)
2. Select your app
3. Click on **TestFlight** tab
4. Under **Public Link** section:
   - If you have one, copy the code after `/join/`
   - If not, click **Enable Public Link**
   - Example: `https://testflight.apple.com/join/AbCdEfGh`
   - Copy: `AbCdEfGh`

## Step 3: Update wrangler.toml

Edit `/workers/link-shortener/wrangler.toml`:

```toml
[vars]
APPLE_APP_ID = "YOUR_TEAM_ID_HERE"  # e.g., "ABC123DEF4"
ANDROID_PACKAGE_ID = "com.Confio.Confio"
IOS_BUNDLE_ID = "com.Confio.Confio"
TESTFLIGHT_URL = "https://testflight.apple.com/join/YOUR_CODE_HERE"  # e.g., "https://testflight.apple.com/join/AbCdEfGh"
PLAY_STORE_URL = "https://play.google.com/store/apps/details?id=com.Confio.Confio"
LANDING_PAGE_URL = "https://confio.lat"
```

## Step 4: Update Zone ID (from Step 1)

Also update the zone_id in the routes section:

```toml
[env.production]
workers_dev = false
routes = [
  { pattern = "confio.lat/*", zone_id = "YOUR_ZONE_ID_HERE" },
  { pattern = "www.confio.lat/*", zone_id = "YOUR_ZONE_ID_HERE" }
]
```

## Step 5: Redeploy

```bash
cd workers/link-shortener
npx wrangler deploy --env production
```

## Example Complete Configuration

```toml
name = "confio-link-shortener"
main = "src/index.ts"
compatibility_date = "2024-01-01"

# Production environment
[env.production]
workers_dev = false
routes = [
  { pattern = "confio.lat/*", zone_id = "7c5dae5552338874e5053f2534d2767a" },
  { pattern = "www.confio.lat/*", zone_id = "7c5dae5552338874e5053f2534d2767a" }
]

# KV namespaces
[[kv_namespaces]]
binding = "LINKS"
id = "6c2befc8ea7e41f9a755a2c84a8fe0cf"

[[kv_namespaces]]
binding = "ANALYTICS"
id = "dffde50153144ae1ad733007e1d01991"

# Environment variables
[vars]
APPLE_APP_ID = "ABC123DEF4"
ANDROID_PACKAGE_ID = "com.Confio.Confio"
IOS_BUNDLE_ID = "com.Confio.Confio"
TESTFLIGHT_URL = "https://testflight.apple.com/join/AbCdEfGh"
PLAY_STORE_URL = "https://play.google.com/store/apps/details?id=com.Confio.Confio"
LANDING_PAGE_URL = "https://confio.lat"
```

## Verification

After deployment, test the apple-app-site-association:

```bash
curl https://confio.lat/.well-known/apple-app-site-association
```

Should return:
```json
{
  "applinks": {
    "apps": [],
    "details": [
      {
        "appID": "ABC123DEF4.com.Confio.Confio",
        "paths": ["/app/*", "/referral/*", "/achievement/*", "/influencer/*", "/*"]
      }
    ]
  },
  "webcredentials": {
    "apps": ["ABC123DEF4.com.Confio.Confio"]
  }
}
```