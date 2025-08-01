# Confío Campaign Links

## 🔗 Active Campaign Links

### 1. WhatsApp Beta Campaign
- **URL**: `https://confio.lat/wa-beta`
- **Purpose**: Track all WhatsApp beta test shares
- **Payload**: `campaign|whatsapp-beta`
- **Created**: August 1, 2025
- **Usage**: Share this link in WhatsApp groups during beta testing

### 2. Referral Program
- **URL**: `https://confio.lat/wa-ref`
- **Purpose**: General user referral tracking
- **Payload**: `campaign|referral-program`
- **Reward**: $2 per successful referral
- **Created**: August 1, 2025
- **Usage**: For users who want to earn by referring friends

### 3. TikTok Influencer Campaign
- **URL**: `https://confio.lat/wa-tiktok`
- **Purpose**: Track TikTok influencer referrals
- **Payload**: `campaign|tiktok-influencers`
- **Hashtags**: #Confio #RetoConfio #LogroConfio #AppDeDolares #DolarDigital
- **Created**: August 1, 2025
- **Usage**: For TikTok creators promoting Confío

## 📱 How Links Work

### Platform Detection
Each link automatically detects the user's platform:

- **iOS** → TestFlight with referral data: `https://testflight.apple.com/join/YOUR_CODE?referrer=campaign%7Cwhatsapp-beta`
- **Android** → Play Store with referrer: `https://play.google.com/store/apps/details?id=com.Confio.Confio&referrer=campaign%7Cwhatsapp-beta`
- **Desktop** → Landing page: `https://confio.lat?c=campaign%7Cwhatsapp-beta&t=referral`

### In-App Handling
The app reads the referral data and:
1. Tracks the installation source
2. Credits the appropriate campaign
3. Unlocks relevant achievements
4. Shows personalized onboarding

## 📊 Analytics Access

### View Campaign Stats
```bash
# WhatsApp Beta Stats
curl https://confio.lat/api/links/wa-beta

# Referral Program Stats
curl https://confio.lat/api/links/wa-ref

# TikTok Campaign Stats
curl https://confio.lat/api/links/wa-tiktok
```

### Admin Dashboard
Access detailed analytics at: `https://confio.lat/dashboard-x7k9m2p5`

## 🚀 Integration with React Native

### Share Button Implementation
```typescript
import { Share, Linking } from 'react-native';

const CAMPAIGN_LINKS = {
  beta: 'https://confio.lat/wa-beta',
  referral: 'https://confio.lat/wa-ref',
  tiktok: 'https://confio.lat/wa-tiktok'
};

export const shareOnWhatsApp = (campaign: 'beta' | 'referral' | 'tiktok') => {
  const link = CAMPAIGN_LINKS[campaign];
  const message = `¡Únete a Confío! 💚\nLa billetera digital para Venezuela.\n\n${link}`;
  
  // Option 1: Direct WhatsApp share
  Linking.openURL(`whatsapp://send?text=${encodeURIComponent(message)}`);
  
  // Option 2: System share sheet
  Share.share({
    message,
    url: link,
    title: 'Comparte Confío'
  });
};
```

### Achievement Integration
```typescript
// In your achievements screen
useEffect(() => {
  const { referralData, referralType } = route.params || {};
  
  if (referralData?.includes('campaign|')) {
    const [, campaign] = referralData.split('|');
    
    switch (campaign) {
      case 'whatsapp-beta':
        unlockAchievement('beta_tester');
        break;
      case 'tiktok-influencers':
        unlockAchievement('social_butterfly');
        break;
      case 'referral-program':
        trackReferralSource(campaign);
        break;
    }
  }
}, [route.params]);
```

## 📈 Monitoring Performance

### Real-time Metrics
- Total clicks per campaign
- Platform distribution (iOS/Android/Desktop)
- Geographic distribution
- Conversion rates (clicks → installs)

### Weekly Reports
Check campaign performance every Monday:
1. Which campaign drives most installs?
2. What's the iOS vs Android split?
3. Which countries are most active?
4. What's the click-to-install conversion rate?

## 🎯 Best Practices

1. **Don't Create New Links for Each Share**: Use these campaign links
2. **Track User-Specific Links Separately**: Only for individual referral tracking
3. **Monitor Regularly**: Check stats weekly to optimize campaigns
4. **A/B Test Messages**: Try different WhatsApp messages to improve conversion
5. **Coordinate with Marketing**: Ensure consistent messaging across campaigns

## 🔒 Security Notes

- Links are public but payloads are encoded
- Analytics data is aggregated (no PII)
- Admin access requires authentication
- All data expires after 90 days