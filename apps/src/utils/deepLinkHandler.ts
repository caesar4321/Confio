import { Linking, Platform } from 'react-native';
import Keychain from 'react-native-keychain';
import { NavigationContainerRef } from '@react-navigation/native';
// @ts-ignore
import { PlayInstallReferrer } from 'react-native-play-install-referrer';
import 'react-native-url-polyfill/auto';

const DEFERRED_LINK_KEY = 'confio_deferred_link';
const AUTH_TOKEN_KEY = 'confio_auth_token';
const REFERRER_TIMEOUT = 48 * 60 * 60 * 1000; // 48 hours in milliseconds

export interface DeepLinkData {
  type: 'referral' | 'influencer' | 'achievement' | 'deeplink';
  payload: string;
  timestamp: number;
}

export class DeepLinkHandler {
  private navigation: NavigationContainerRef<any> | null = null;

  constructor() {
    this.handleInitialLink();
    this.setupLinkListener();
  }

  setNavigation(navigation: NavigationContainerRef<any>) {
    this.navigation = navigation;
  }

  private async handleInitialLink() {
    try {
      // Check for initial URL (app was closed)
      const initialUrl = await Linking.getInitialURL();
      if (initialUrl) {
        await this.handleDeepLink(initialUrl);
      } else {
        // If no direct deep link, check for deferred referral (Install Referrer or IP Fingerprint)
        // Only if we don't already have one stored
        const existingDeferred = await this.getDeferredLink();
        if (!existingDeferred) {
          const referralCode = await this.checkReferralStrategies();
          if (referralCode) {
            console.log('Found deferred referral code:', referralCode);
            const linkData: DeepLinkData = {
              type: 'referral',
              payload: referralCode,
              timestamp: Date.now()
            };
            // Always store referral links as deferred so HomeScreen can handle the mutation
            await this.storeDeferredLink(linkData);
          }
        }
      }

      // Check for deferred deep link (stored from previous app launch)
      const deferredLink = await this.getDeferredLink();
      if (deferredLink && this.isWithinTimeout(deferredLink)) {
        await this.processDeferredLink(deferredLink);
      }
    } catch (error) {
      console.error('Error handling initial link:', error);
    }
  }



  private async checkReferralStrategies(): Promise<string | null> {
    /* MOCK FOR TESTING - UNCOMMENT TO USE
    console.log('[DeepLink] Using MOCKED Play Store referrer value');
    await new Promise(resolve => setTimeout(resolve, 1000));
    return 'JULIANMOONLUNA';
    */

    // 1. Check Install Referrer (Android only)
    if (Platform.OS === 'android') {
      try {
        console.log('[DeepLink] Checking Play Install Referrer (New Lib)...');

        const referrerInfo = await new Promise((resolve, reject) => {
          PlayInstallReferrer.getInstallReferrerInfo((value: any, error: any) => {
            if (error) {
              reject(error);
            } else {
              resolve(value);
            }
          });
        }) as any;

        console.log(`[DeepLink] Install Referrer raw data: ${JSON.stringify(referrerInfo)}`);

        if (referrerInfo && referrerInfo.installReferrer) {
          let ref = referrerInfo.installReferrer;
          console.log(`[DeepLink] Raw referrer string: ${ref}`);


          // Ignore standard google play params if they don't look like our code
          // Heuristic:
          // 1. If it's a naked code (no utm_), accept it.
          // 2. If it contains utm_, look for 'utm_content' or 'utm_campaign' which might hold our code.

          let potentialCode = ref;

          // Attempt to handle double-encoded strings
          if (ref.includes('%')) {
            try {
              const decoded = decodeURIComponent(ref);
              if (decoded !== ref) {
                console.log(`[DeepLink] Decoded referrer: ${decoded}`);
                ref = decoded;
                potentialCode = decoded;
              }
            } catch (e) {
              // ignore decoding errors
            }
          }

          if (ref.includes('utm_')) {
            // Parse query string style 'key=value&key2=value2'
            // We use new URLSearchParams which handles = and & automatically
            const params = new URLSearchParams(ref);
            const content = params.get('utm_content');
            const campaign = params.get('utm_campaign');
            const source = params.get('utm_source');

            console.log(`[DeepLink] Parsed UTMs - content: ${content}, campaign: ${campaign}, source: ${source}`);

            if (content && !content.includes('google')) {
              potentialCode = content;
              console.log(`[DeepLink] Extracted potential code from utm_content: ${potentialCode}`);
            } else if (campaign && !campaign.includes('google-play')) {
              potentialCode = campaign;
              console.log(`[DeepLink] Extracted potential code from utm_campaign: ${potentialCode}`);
            } else {
              // Checking for "organic"
              if (ref.includes('medium=organic') || (source && source.includes('google-play'))) {
                console.log(`[DeepLink] Ignored organic/play-store install (no custom referrer params)`);
                // Keep potentialCode as is, it will likely be rejected below
              }
            }
          }

          // But our worker sets `referrer=CODE`. 
          // If the code is simple (alphanumeric), we take it.
          // We fail if it STILL looks like a url param string (contains =) or is one of the restricted keywords
          if (!potentialCode.includes('utm_source') && !potentialCode.includes('gclid') && !potentialCode.includes('=')) {
            console.log(`[DeepLink] Accepting referrer string: ${potentialCode}`);
            return potentialCode;
          } else {
            console.log(`[DeepLink] Rejected referrer string (contains utm/gclid or format invalid): ${potentialCode}`);
          }
        } else {
          console.log('[DeepLink] Install Referrer returned no referrer property');
        }
      } catch (e: any) {
        console.log(`[DeepLink] Install Referrer check failed or threw error: ${e?.message || e}`);
      }
    }

    // 2. Check IP Fingerprint (Fallback for Android, Primary for iOS)
    try {
      console.log('[DeepLink] Checking IP fingerprint for referral code...');
      // Use a short timeout to not block app startup too long
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 3000);

      const response = await fetch('https://confio.lat/api/check-referral', {
        signal: controller.signal as any
      });
      clearTimeout(timeoutId);

      console.log(`[DeepLink] IP fingerprint response status: ${response.status}`);

      if (response.ok) {
        const data = await response.json();
        console.log(`[DeepLink] IP fingerprint data: ${JSON.stringify(data)}`);
        if (data.code) {
          console.log(`[DeepLink] Found referral code via IP fingerprint: ${data.code}`);
          return data.code;
        } else {
          console.log('[DeepLink] No referral code found for this IP');
        }
      }
    } catch (e: any) {
      console.log(`[DeepLink] IP Fingerprint check failed: ${e?.message || e}`);
    }

    return null;
  }

  private setupLinkListener() {
    // Listen for links when app is running
    Linking.addEventListener('url', (event) => {
      if (event.url) {
        this.handleDeepLink(event.url);
      }
    });
  }

  private async handleDeepLink(url: string) {
    try {
      const parsedUrl = new URL(url);
      const pathParts = parsedUrl.pathname.split('/').filter(Boolean);

      // Handle different URL patterns
      // confio.lat/app/referral/[payload]
      // confio.lat/app/achievement/[payload]
      // confio.lat/app/influencer/[payload]

      if (pathParts[0] === 'app' && pathParts.length >= 3) {
        const type = pathParts[1] as DeepLinkData['type'];
        const payload = decodeURIComponent(pathParts[2]);

        const linkData: DeepLinkData = {
          type,
          payload,
          timestamp: Date.now()
        };

        // For referral links, always store as deferred so HomeScreen can handle the mutation
        if (type === 'referral' || type === 'influencer') {
          await this.storeDeferredLink(linkData);
          return;
        }

        // For other link types, process immediately if logged in
        const isLoggedIn = await this.checkUserLoggedIn();
        if (!isLoggedIn) {
          await this.storeDeferredLink(linkData);
          return;
        }
        await this.processDeepLink(linkData);
      }

      // Handle TestFlight referrer parameter
      const referrer = parsedUrl.searchParams.get('referrer');
      if (referrer) {
        const linkData: DeepLinkData = {
          type: 'referral',
          payload: referrer,
          timestamp: Date.now()
        };

        // Always store referral links as deferred so HomeScreen can handle the mutation
        await this.storeDeferredLink(linkData);
      }
    } catch (error) {
      console.error('Error handling deep link:', error);
    }
  }

  private async processDeepLink(linkData: DeepLinkData) {
    if (!this.navigation) {
      console.warn('Navigation not set, storing link for later');
      await this.storeDeferredLink(linkData);
      return;
    }

    switch (linkData.type) {
      case 'referral':
      case 'influencer':
        // Navigate to achievements screen with referral data
        // Or if we want to show it on HomeScreen, we might just store it in context?
        // But for now, let's keep existing navigation behavior if applicable
        // The user wants HomeScreen to update.
        this.navigation.navigate('Achievements', {
          referralData: linkData.payload,
          referralType: linkData.type
        });
        break;

      case 'achievement':
        // Navigate to specific achievement
        this.navigation.navigate('Achievements', {
          achievementId: linkData.payload
        });
        break;

      case 'deeplink':
        // Handle custom deep links
        const [screen, ...params] = linkData.payload.split('|');
        this.navigation.navigate(screen, { params: params.join('|') });
        break;
    }

    // Clear deferred link after processing
    // await this.clearDeferredLink(); 
    // WAIT: The user wants to show "Locked Reward" UNTIL it is unlocked.
    // If we clear it, we lose the info that the user was referred.
    // However, usually we send this to the backend upon signup.
    // If logic is "Show on Home Screen" even before signup?
    // "Apps/src/screens/HomeScreen.tsx" uses `userProfile` so it assumes logged in.
    // If the user logs in, we should send this referral code to the backend.

    // For the "Locked Reward" display in HomeScreen:
    // It should check if the user HAS a referrer pending.
    // If we claim it (send to backend), the backend should return the status "Locked".
    // So we don't need to keep it in local storage indefinitely if the backend knows.

    await this.clearDeferredLink();
  }

  private async processDeferredLink(linkData: DeepLinkData) {
    // Special handling for referral links - check 48h window
    if ((linkData.type === 'referral' || linkData.type === 'influencer') &&
      !this.isWithinTimeout(linkData)) {
      console.log('Referral link expired (>48h)');
      await this.clearDeferredLink();
      return;
    }

    await this.processDeepLink(linkData);
  }

  private isWithinTimeout(linkData: DeepLinkData): boolean {
    if (linkData.type !== 'referral' && linkData.type !== 'influencer') {
      return true; // Other link types don't expire
    }

    const elapsed = Date.now() - linkData.timestamp;
    return elapsed < REFERRER_TIMEOUT;
  }

  private async checkUserLoggedIn(): Promise<boolean> {
    try {
      // Check if user has auth tokens
      const credentials = await Keychain.getInternetCredentials(AUTH_TOKEN_KEY);
      return !!credentials;
    } catch {
      return false;
    }
  }


  public async storeDeferredLink(linkData: DeepLinkData) {
    try {
      await Keychain.setInternetCredentials(
        DEFERRED_LINK_KEY,
        'deferred_link',
        JSON.stringify(linkData)
      );
    } catch (error) {
      console.error('Error storing deferred link:', error);
    }
  }

  public async getDeferredLink(): Promise<DeepLinkData | null> {
    try {
      const credentials = await Keychain.getInternetCredentials(DEFERRED_LINK_KEY);
      // Check for explicit 'null' string which we use to soft-clear the link
      if (!credentials || credentials.password === 'null') {
        return null;
      }
      return JSON.parse(credentials.password);
    } catch (error) {
      console.error('Error getting deferred link:', error);
      return null;
    }
  }

  public async clearDeferredLink() {
    try {
      // WORKAROUND: resetInternetCredentials checks arguments as array of maps on some Android versions
      // causing ClassCastException: String cannot be cast to ReadableNativeMap
      // Instead, we overwrite with "null" string which getDeferredLink handles.
      console.log('[DeepLink] Soft-clearing deferred link via setInternetCredentials');
      await Keychain.setInternetCredentials(
        DEFERRED_LINK_KEY,
        'deferred_link',
        'null'
      );
    } catch (error) {
      console.error('Error clearing deferred link:', error);
    }
  }

  // Public method to check and process deferred links after login
  async checkDeferredLinks() {
    const deferredLink = await this.getDeferredLink();
    if (deferredLink && this.isWithinTimeout(deferredLink)) {
      await this.processDeferredLink(deferredLink);
    }
  }
}

// Singleton instance
export const deepLinkHandler = new DeepLinkHandler();