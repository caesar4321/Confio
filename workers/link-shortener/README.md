# Confio Link Shortener

A Cloudflare Workers-based link shortener for Confio's WhatsApp share links during closed-beta (TestFlight). This replaces expensive third-party services like Branch.io with a cost-effective solution.

## Features

- 🔗 Short link generation (confio.lat/abc123)
- 📱 Platform detection (iOS/Android/Desktop)
- 🎯 Deferred deep linking for post-install attribution
- 📊 Analytics tracking
- 🔐 48-hour referral link expiration
- 💰 Cost-effective (free tier covers most usage)

## How It Works

1. **Link Creation**: Marketing team creates short links via admin UI
2. **User Clicks**: User clicks link in WhatsApp
3. **Platform Detection**: Worker detects user's platform
4. **Smart Redirect**:
   - iOS → TestFlight with referral data
   - Android → Play Store with referrer parameter
   - Desktop → Landing page with campaign data
5. **Post-Install**: App reads referral data and navigates to achievements

## Admin Panel

The admin panel is available at a secure URL (not publicly shared).

To set up admin access, see [SECURE_SETUP.md](./SECURE_SETUP.md)

The admin panel allows you to:
- Create short links with custom slugs
- View link statistics and click analytics
- Track platform distribution (iOS/Android/Desktop)
- Monitor campaign performance

## API Endpoints

### Create Link
```bash
POST /api/links
{
  "type": "referral",      # referral|influencer|achievement|deeplink
  "payload": "user123",    # Referral data
  "slug": "promo2024",     # Optional custom slug
  "metadata": {}           # Optional metadata
}
```

### Get Link Stats
```bash
GET /api/links/{slug}
```

## Link Types

- **referral**: User referrals with 48-hour window
- **influencer**: TikTok influencer campaigns
- **achievement**: Direct achievement unlocks
- **deeplink**: Custom deep links

## Deployment

See [DEPLOY.md](./DEPLOY.md) for detailed deployment instructions.

## Development

```bash
# Install dependencies
npm install

# Run locally
wrangler dev

# Deploy to production
wrangler deploy
```

## Cost Analysis

### Branch.io (previous solution)
- Growth Plan: $1,200/month
- 20,000 MAU limit
- Complex integration

### Cloudflare Workers (current solution)
- Workers: Free up to 100k requests/day
- KV Storage: Free up to 1GB
- Estimated cost: $0-5/month

## Security

- Rate limiting per IP
- 48-hour expiration for referral links
- No PII stored
- Analytics data auto-expires after 90 days

## Integration with React Native

The app includes a deep link handler that:
1. Checks for deferred links on app launch
2. Processes referral data after login
3. Navigates to appropriate screens
4. Clears expired links

See `/apps/src/utils/deepLinkHandler.ts` for implementation.