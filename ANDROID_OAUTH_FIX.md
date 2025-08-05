# Android OAuth Redirect Fix

## Problem
The OAuth redirect was getting stuck in the WebView on Android devices after successful authentication with a white screen. Android WebView/Chrome Custom Tabs don't reliably handle custom scheme redirects (`confio://oauth-callback`).

## Solution: WebView with postMessage Communication

### 1. Success Page with postMessage
The OAuth callback redirects to a success page that uses `postMessage` to communicate with React Native:
```javascript
// oauth_success.html
if (window.ReactNativeWebView) {
  window.ReactNativeWebView.postMessage(JSON.stringify({
    type: 'oauth_success',
    data: authData
  }));
}
```

### 2. React Native WebView Component
Created `OAuthWebView.tsx` that:
- Opens OAuth URL in a WebView (not InAppBrowser)
- Listens for postMessage from the success page
- Parses authentication data
- Closes automatically when done

### 3. WebView Configuration
```typescript
<WebView
  source={{ uri: oauthUrl }}
  onMessage={handleMessage}  // Receives postMessage
  javaScriptEnabled={true}
  domStorageEnabled={true}
  sharedCookiesEnabled={true}
/>
```

### 4. How It Works
1. User taps "Sign in with Google/Apple"
2. App shows WebView with OAuth URL
3. User completes OAuth in WebView
4. OAuth provider redirects to Django callback
5. Django redirects to `/oauth/aptos/success/` page
6. Success page sends postMessage to React Native
7. React Native receives auth data and closes WebView
8. App continues with authenticated user

### 5. Benefits
- **Works on all Android versions**: WebView postMessage is reliable
- **No custom scheme issues**: Uses standard HTTPS throughout
- **Automatic data transfer**: No manual URL parsing needed
- **Clean UX**: Success page shows spinner while data transfers

## Implementation Files
- `apps/src/components/OAuthWebView.tsx` - WebView modal component
- `apps/src/services/webOAuthServiceV2.ts` - OAuth service for WebView
- `prover/templates/oauth_success.html` - Success page with postMessage
- `apps/src/services/authServiceWebView.ts` - Helper to process OAuth results

## Usage Example
```typescript
// In AuthScreen or similar
const [showOAuthWebView, setShowOAuthWebView] = useState(false);
const [oauthProvider, setOAuthProvider] = useState<'google' | 'apple'>('google');

// When sign-in button pressed
const handleGoogleSignIn = () => {
  setOAuthProvider('google');
  setShowOAuthWebView(true);
};

// Render the WebView
<OAuthWebView
  visible={showOAuthWebView}
  provider={oauthProvider}
  onSuccess={handleOAuthSuccess}
  onError={handleOAuthError}
  onClose={() => setShowOAuthWebView(false)}
/>
```