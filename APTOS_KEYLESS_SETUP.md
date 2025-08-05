# Aptos Keyless Account Setup Guide

## Summary

We've migrated from Sui zkLogin to Aptos Keyless Account. Both systems require web-based OAuth flows to properly handle nonce parameters, which is why native mobile OAuth (Google Sign-In and Apple Sign-In SDKs) result in "nonce mismatch" errors.

## What's Been Done

### 1. Backend (Django)
- Created web OAuth views (`web_oauth_views.py`) to handle the OAuth flow
- OAuth endpoints generate ephemeral key pairs with proper nonces
- OAuth callbacks derive Keyless accounts successfully
- Added OAuth URLs to Django routing
- Created success/error HTML templates for OAuth callbacks

### 2. Frontend (React Native)
- Created `webOAuthService.ts` to handle web-based OAuth flows
- Updated `authService.ts` to use web OAuth first, with fallback to native
- Manually linked `react-native-inappbrowser-reborn` for Android
- Deep linking already configured (`confio://` scheme)

### 3. TypeScript Bridge
- Still running on localhost:3333
- Django communicates with it for Keyless operations

## Setup Instructions

### 1. Install Dependencies

```bash
cd apps
npm install react-native-inappbrowser-reborn

# For iOS
cd ios && pod install
```

### 2. Configure OAuth Credentials

Add to your `.env` file:
```
GOOGLE_OAUTH_CLIENT_ID=your-google-client-id
GOOGLE_OAUTH_CLIENT_SECRET=your-google-client-secret
APPLE_OAUTH_CLIENT_ID=your-apple-client-id  
APPLE_OAUTH_CLIENT_SECRET=your-apple-client-secret
```

### 3. Update OAuth Redirect URIs

In Google Cloud Console:
- Add: `http://localhost:8000/prover/oauth/aptos/callback/`
- Add: `https://yourdomain.com/prover/oauth/aptos/callback/`

In Apple Developer Console:
- Add similar redirect URIs for Apple Sign-In

### 4. Run Services

```bash
# Terminal 1: TypeScript Bridge
cd aptos-keyless-bridge
npm start

# Terminal 2: Django Backend
./myvenv/bin/python manage.py runserver 0.0.0.0:8000

# Terminal 3: React Native
cd apps
npm start
```

## How It Works

1. User taps "Sign in with Google/Apple"
2. App opens in-app browser to Django OAuth endpoint
3. Django generates ephemeral key pair with nonce
4. Django redirects to Google/Apple with the nonce
5. User completes OAuth
6. OAuth provider returns JWT with the nonce
7. Django derives Keyless account (nonce matches!)
8. Success page sends data back to React Native
9. App stores Keyless account and continues

## Troubleshooting

### "Nonce mismatch" error
- This happens when using native OAuth SDKs
- Always use the web-based OAuth flow for Keyless

### InAppBrowser not opening
- Make sure the package is properly linked
- Check that deep linking is configured

### OAuth callback not working
- Verify redirect URIs in OAuth provider console
- Check Django is running and accessible

## Important Notes

1. **Native OAuth won't work** - Both Google Sign-In and Apple Sign-In native SDKs don't support custom nonces required by Aptos Keyless
2. **Same issue as Sui zkLogin** - This is the exact same limitation we had with Sui
3. **Web OAuth is the solution** - Using web-based OAuth flows allows proper nonce handling
4. **User experience** - The in-app browser provides a seamless experience