# Google OAuth Android Fix - Policy Violation

## Problem
Google is blocking OAuth with error "Access Blocked: Google Policy Violation" on Android.

## Root Cause
Google blocks OAuth in WebViews for security reasons. Additionally, the OAuth client configuration may need adjustments.

## Solution Steps

### 1. Verify OAuth Client Configuration in Google Cloud Console

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select your project
3. Navigate to "APIs & Services" > "Credentials"
4. Find your OAuth 2.0 Client ID

### 2. Update OAuth Client Type
- The OAuth client should be of type **"Web application"** (not Android)
- This is required for the web-based OAuth flow

### 3. Add Authorized Redirect URIs
Add these redirect URIs to your OAuth client:
```
https://confio.lat/prover/oauth/aptos/callback/
http://localhost:8000/prover/oauth/aptos/callback/
```

If using ngrok for development, also add:
```
https://YOUR-NGROK-ID.ngrok.io/prover/oauth/aptos/callback/
```

### 4. Configure OAuth Consent Screen
1. Go to "OAuth consent screen" in Google Cloud Console
2. Ensure all required fields are filled:
   - App name
   - User support email
   - App logo (optional but recommended)
   - Application home page
   - Privacy policy link
   - Terms of service link

### 5. Use InAppBrowser Instead of WebView
The code has been updated to use InAppBrowser (Chrome Custom Tabs) for Google OAuth:
```typescript
// In authService.ts
const useWebView = false; // Google blocks WebView OAuth
```

### 6. Test the Flow
1. Clear app data/cache on Android device
2. Try signing in with Google again
3. The OAuth should open in Chrome Custom Tabs (not WebView)

## Alternative: Use Google Sign-In SDK
If the web-based OAuth continues to fail, consider using the native Google Sign-In SDK:
1. The SDK handles OAuth natively without WebView
2. However, this requires additional configuration and may not work with Aptos Keyless

## Environment Variables to Check
Ensure these are properly set in your `.env` files:
```
GOOGLE_OAUTH_CLIENT_ID=your-web-client-id.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret
```

## Debug Steps
1. Check the OAuth URL being generated in the console logs
2. Verify the redirect URI matches exactly what's in Google Console
3. Ensure the OAuth client ID is for a "Web application" type
4. Check if the app is in production or testing mode in Google Console