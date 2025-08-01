# Platform-Specific Flows for Link Shortener

## 🍎 iOS Flow

1. **User clicks**: `confio.lat/beta2024` in WhatsApp
2. **Detection**: User-agent identifies iOS device
3. **Redirect**: 
   - During TestFlight: `https://testflight.apple.com/join/AbCdEfGh?referrer=whatsapp%7Cjulian123`
   - After App Store launch: Direct to App Store with Universal Links
4. **Post-Install**: App reads deferred link data using Universal Links

## 🤖 Android Flow

1. **User clicks**: `confio.lat/beta2024` in WhatsApp
2. **Detection**: User-agent identifies Android device
3. **Redirect**: `https://play.google.com/store/apps/details?id=com.Confio.Confio&referrer=whatsapp%7Cjulian123`
4. **Post-Install**: App retrieves referrer data using Play Store Install Referrer API

### Android Implementation Guide

#### 1. Add Install Referrer Library (React Native)

```bash
npm install react-native-android-referrer
# or
yarn add react-native-android-referrer
```

#### 2. Update Android Manifest

Add to `android/app/src/main/AndroidManifest.xml`:

```xml
<receiver
    android:name="com.android.installreferrer.api.InstallReferrerReceiver"
    android:exported="true">
    <intent-filter>
        <action android:name="com.android.vending.INSTALL_REFERRER" />
    </intent-filter>
</receiver>
```

#### 3. Read Referrer Data in React Native

```typescript
import { getReferrer } from 'react-native-android-referrer';

// In your app initialization
const checkAndroidReferrer = async () => {
  if (Platform.OS === 'android') {
    try {
      const referrer = await getReferrer();
      if (referrer) {
        // Parse the referrer data
        const decodedReferrer = decodeURIComponent(referrer);
        const [type, payload] = decodedReferrer.split('|');
        
        // Handle the referral
        if (type === 'whatsapp') {
          navigation.navigate('Achievements', {
            referralData: payload,
            referralType: 'referral'
          });
        }
      }
    } catch (error) {
      console.error('Error getting referrer:', error);
    }
  }
};
```

## 💻 Desktop Flow

1. **User clicks**: `confio.lat/beta2024` on desktop
2. **Detection**: User-agent identifies desktop browser
3. **Redirect**: `https://confio.lat?c=whatsapp%7Cjulian123&t=referral`
4. **Landing Page**: Shows download options with QR codes

## 📊 Testing Each Platform

### Test iOS (using curl with iOS user agent):
```bash
curl -H "User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)" \
     -I https://confio.lat/beta2024
```

### Test Android (using curl with Android user agent):
```bash
curl -H "User-Agent: Mozilla/5.0 (Linux; Android 11; Pixel 5)" \
     -I https://confio.lat/beta2024
```

### Test Desktop:
```bash
curl -I https://confio.lat/beta2024
```

## 🔧 Customizing Redirects

You can customize the redirect URLs in `wrangler.toml`:

```toml
[vars]
# iOS Settings
TESTFLIGHT_URL = "https://testflight.apple.com/join/YOUR_CODE"
IOS_BUNDLE_ID = "com.Confio.Confio"

# Android Settings
PLAY_STORE_URL = "https://play.google.com/store/apps/details?id=com.Confio.Confio"
ANDROID_PACKAGE_ID = "com.Confio.Confio"

# Desktop Settings
LANDING_PAGE_URL = "https://confio.lat"
```

## 🎯 Benefits Over Branch.io

| Feature | Branch.io | Our Solution |
|---------|-----------|--------------|
| iOS Support | ✅ | ✅ |
| Android Support | ✅ | ✅ |
| Desktop Support | ✅ | ✅ |
| Post-Install Attribution | ✅ | ✅ |
| Analytics | ✅ | ✅ |
| Cost | $1,200/month | Free |
| Setup Complexity | High | Medium |
| Data Ownership | Branch.io | You |

## 🚀 Next Steps for Android

1. Install the Play Store referrer library
2. Update AndroidManifest.xml
3. Implement referrer reading in your app
4. Test with real Android devices
5. Monitor analytics in Cloudflare dashboard