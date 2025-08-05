# OAuth Flow Debug Guide

## Current Implementation

### For Google Sign-In:
- `useWebView = false` → Uses InAppBrowser (Chrome Custom Tabs)
- Should NOT show WebView modal
- Should NOT throw `WEBVIEW_OAUTH_REQUIRED` error

### For Apple Sign-In:
- `useWebView = Platform.OS === 'ios'` → WebView on iOS, InAppBrowser on Android

## Debug Steps

1. **Force Reload the App**
   ```bash
   # In terminal 1 - Metro bundler
   r  # Press 'r' to reload
   
   # Or restart Metro
   npm start -- --reset-cache
   ```

2. **Clear App Data on Android**
   - Settings → Apps → Confio → Storage → Clear Data
   - This removes any cached WebView data

3. **Check Console Logs**
   You should see:
   ```
   [AuthService] Google Sign-In using InAppBrowser (Chrome Custom Tabs)
   [WebOAuth] InAppBrowser available: true
   [WebOAuth] Opening OAuth URL in browser
   ```

4. **Verify Browser Opens**
   - Should see Chrome Custom Tabs (not WebView)
   - Has Chrome UI elements (address bar, menu)
   - NOT embedded in the app

## If Still Getting Policy Violation

The error might be from:
1. **OAuth Client Configuration** - Must be "Web application" type
2. **Redirect URI Mismatch** - Must match exactly in Google Console
3. **Missing OAuth Consent Screen** info

## Quick Test

Add this temporary debug code to AuthScreen:
```typescript
const handleGoogleSignIn = async () => {
  try {
    console.log('=== GOOGLE SIGN IN START ===');
    console.log('Platform:', Platform.OS);
    const result = await authService.signInWithGoogle();
    // ... rest of code
  } catch (error: any) {
    console.log('=== GOOGLE SIGN IN ERROR ===');
    console.log('Error message:', error.message);
    console.log('Full error:', error);
    // ... rest of code
  }
};
```

This will help identify exactly where the flow is failing.