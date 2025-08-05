# Android 12+ OAuth Redirect Fix

## Problem
On Android 12 and above, OAuth redirects were getting stuck after successful authentication. The InAppBrowser (Chrome Custom Tabs) wasn't closing automatically when redirecting back to the app.

## Root Cause
Android 12 introduced stricter requirements for web intents. Deep links must have properly configured intent filters with specific `scheme`, `host`, and optionally `path` components.

## Solution
Added a properly configured intent filter in `AndroidManifest.xml` specifically for OAuth callbacks:

```xml
<!-- OAuth callback intent filter for Android 12+ -->
<intent-filter>
    <action android:name="android.intent.action.VIEW" />
    <category android:name="android.intent.category.DEFAULT" />
    <category android:name="android.intent.category.BROWSABLE" />
    <data 
        android:scheme="confio" 
        android:host="oauth-callback" />
</intent-filter>
```

This matches the redirect URL used by InAppBrowser: `confio://oauth-callback`

## How It Works

1. User taps "Sign in with Google/Apple"
2. InAppBrowser opens OAuth URL in Chrome Custom Tabs
3. User completes authentication
4. OAuth provider redirects to backend callback URL
5. Backend redirects to `confio://oauth-callback?success=true&...`
6. Android 12+ recognizes the intent filter and opens the app
7. InAppBrowser detects the redirect URL and extracts the parameters
8. InAppBrowser closes automatically and returns the result

## Key Points

- **No WebView**: Following OAuth best practices, we use an external browser (Chrome Custom Tabs)
- **Android 12+ Compatible**: The intent filter follows the required pattern
- **Automatic Closing**: InAppBrowser's `openAuth` method handles the redirect detection
- **Security**: OAuth happens in the system browser, not an embedded WebView

## Testing

1. Build and install the app on Android 12+ device
2. Tap "Sign in with Google"
3. Complete OAuth in Chrome Custom Tabs
4. App should automatically receive the callback and close the browser

## References
- [OAuth 2.0 for Native Apps - RFC 8252](https://datatracker.ietf.org/doc/html/rfc8252)
- [Android 12 Behavior Changes](https://developer.android.com/about/versions/12/behavior-changes-12#web-intent-resolution)