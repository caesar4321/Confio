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
  metadata?: {
    invitationId?: string;
    sourceType?: string;
    clickId?: string;
    sessionId?: string;
    channel?: string;
    platform?: string;
    country?: string;
    utmSource?: string;
    utmMedium?: string;
    utmCampaign?: string;
    utmContent?: string;
    utmTerm?: string;
    ttclid?: string;
    fbclid?: string;
    gclid?: string;
  };
}

type ReferralStrategyResult = {
  code: string;
  metadata?: DeepLinkData['metadata'];
};

export class DeepLinkHandler {
  private navigation: NavigationContainerRef<any> | null = null;
  private initializationPromise: Promise<void> | null = null;
  private linkListenerSetup = false;
  private referralListeners = new Set<() => void>();

  constructor() {}

  setNavigation(navigation: NavigationContainerRef<any>) {
    this.navigation = navigation;
  }

  addReferralListener(listener: () => void) {
    this.referralListeners.add(listener);
    return () => {
      this.referralListeners.delete(listener);
    };
  }

  private notifyReferralListeners() {
    this.referralListeners.forEach(listener => {
      try {
        listener();
      } catch (error) {
        console.error('Error notifying referral listener:', error);
      }
    });
  }

  async init() {
    if (!this.initializationPromise) {
      const attempt = this.initialize();
      this.initializationPromise = attempt;
      attempt.catch(() => {
        if (this.initializationPromise === attempt) {
          this.initializationPromise = null;
        }
      });
    }
    return this.initializationPromise;
  }

  private async initialize() {
    this.setupLinkListener();
    await this.handleInitialLink();
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
          const referral = await this.checkReferralStrategies();
          if (referral) {
            const linkData: DeepLinkData = {
              type: 'referral',
              payload: referral.code,
              timestamp: Date.now(),
              metadata: referral.metadata,
            };
            // Always store referral links as deferred so HomeScreen can handle the mutation
            await this.storeDeferredLink(linkData);
          }
        }
      }

      // Check for deferred deep link (stored from previous app launch)
      const deferredLink = await this.getDeferredLink();
      if (deferredLink) {
        await this.processDeferredLink(deferredLink);
      }
    } catch (error) {
      console.error('Error handling initial link:', error);
      throw error;
    }
  }



  private async checkReferralStrategies(): Promise<ReferralStrategyResult | null> {
    /* MOCK FOR TESTING - UNCOMMENT TO USE
    await new Promise(resolve => setTimeout(resolve, 1000));
    return 'JULIANMOONLUNA';
    */

    // 1. Check Install Referrer (Android only)
    if (Platform.OS === 'android') {
      try {
        const referrerInfo = await new Promise((resolve, reject) => {
          PlayInstallReferrer.getInstallReferrerInfo((value: any, error: any) => {
            if (error) {
              reject(error);
            } else {
              resolve(value);
            }
          });
        }) as any;

        if (referrerInfo && referrerInfo.installReferrer) {
          let ref = referrerInfo.installReferrer;


          // Ignore standard google play params if they don't look like our code
          // Heuristic:
          // 1. If it's a naked code (no utm_), accept it.
          // 2. If it contains utm_, look for 'utm_content' or 'utm_campaign' which might hold our code.

          let potentialCode = ref;
          let metadata: DeepLinkData['metadata'] | undefined;

          // Attempt to handle double-encoded strings
          if (ref.includes('%')) {
            try {
              const decoded = decodeURIComponent(ref);
              if (decoded !== ref) {
                ref = decoded;
                potentialCode = decoded;
              }
            } catch (e) {
              // ignore decoding errors
            }
          }

          if (ref.includes('utm_') || ref.includes('invitation_id=')) {
            // Parse query string style 'key=value&key2=value2'
            // We use new URLSearchParams which handles = and & automatically
            const params = new URLSearchParams(ref);
            const referralCode = params.get('referral_code');
            const content = params.get('utm_content');
            const campaign = params.get('utm_campaign');
            const source = params.get('utm_source');
            const invitationId = params.get('invitation_id');
            const sourceType = params.get('source_type');
            const clickId = params.get('click_id');
            const sessionId = params.get('session_id');
            const channel = params.get('channel');
            const clickPlatform = params.get('platform');
            const country = params.get('country');
            const adUtmContent = params.get('ad_utm_content');
            const utmMedium = params.get('utm_medium');
            const utmTerm = params.get('utm_term');
            const ttclid = params.get('ttclid');
            const fbclid = params.get('fbclid');
            const gclid = params.get('gclid');

            if (
              invitationId || sourceType || clickId || sessionId || channel ||
              clickPlatform || country || source || utmMedium || campaign || adUtmContent || utmTerm ||
              ttclid || fbclid || gclid
            ) {
              metadata = {
                invitationId: invitationId || undefined,
                sourceType: sourceType || undefined,
                clickId: clickId || undefined,
                sessionId: sessionId || undefined,
                channel: channel || undefined,
                platform: clickPlatform || undefined,
                country: country || undefined,
                utmSource: source || undefined,
                utmMedium: utmMedium || undefined,
                utmCampaign: campaign || undefined,
                utmContent: adUtmContent || undefined,
                utmTerm: utmTerm || undefined,
                ttclid: ttclid || undefined,
                fbclid: fbclid || undefined,
                gclid: gclid || undefined,
              };
            }

            if (referralCode) {
              potentialCode = referralCode;
            } else if (content && !content.includes('google')) {
              potentialCode = content;
            } else if (campaign && !campaign.includes('google-play')) {
              potentialCode = campaign;
            } else {
              // Checking for "organic"
              if (ref.includes('medium=organic') || (source && source.includes('google-play'))) {
                // Keep potentialCode as is, it will likely be rejected below
              }
            }
          }

          // But our worker sets `referrer=CODE`. 
          // If the code is simple (alphanumeric), we take it.
          // We fail if it STILL looks like a url param string (contains =) or is one of the restricted keywords
          if (!potentialCode.includes('utm_source') && !potentialCode.includes('gclid') && !potentialCode.includes('=')) {
            return { code: potentialCode, metadata };
          }
        }
      } catch {
      }
    }

    // 2. Check IP Fingerprint (Fallback for Android, Primary for iOS)
    try {
      // Use a short timeout to not block app startup too long
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 3000);

      const response = await fetch('https://confio.lat/api/check-referral', {
        signal: controller.signal as any
      });
      clearTimeout(timeoutId);

      if (response.ok) {
        const data = await response.json();
        if (data.code) {
          const attribution = data.attribution || {};
          return {
            code: data.code,
            metadata: {
              invitationId: attribution.invitation_id || undefined,
              sourceType: attribution.source_type || undefined,
              clickId: attribution.click_id || undefined,
              sessionId: attribution.session_id || undefined,
              channel: attribution.channel || undefined,
              platform: attribution.platform || undefined,
              country: attribution.country || undefined,
              utmSource: attribution.utm_source || undefined,
              utmMedium: attribution.utm_medium || undefined,
              utmCampaign: attribution.utm_campaign || undefined,
              utmContent: attribution.utm_content || undefined,
              utmTerm: attribution.utm_term || undefined,
              ttclid: attribution.ttclid || undefined,
              fbclid: attribution.fbclid || undefined,
              gclid: attribution.gclid || undefined,
            },
          };
        }
      }
    } catch {
    }

    return null;
  }

  private setupLinkListener() {
    if (this.linkListenerSetup) {
      return;
    }

    // Listen for links when app is running
    Linking.addEventListener('url', (event) => {
      if (event.url) {
        this.handleDeepLink(event.url).catch(error => {
          console.error('Error handling warm deep link:', error);
        });
      }
    });
    this.linkListenerSetup = true;
  }

  private async handleDeepLink(url: string) {
    try {
      const parsedUrl = new URL(url);
      const pathParts = parsedUrl.pathname.split('/').filter(Boolean);

      // Public referral links are /invite/{username}. When the app is already
      // installed, Android App Links / iOS Universal Links deliver that URL
      // directly instead of going through the store referrer. Preserve it for
      // HomeScreen, which owns the authenticated setReferrer mutation.
      if (pathParts[0] === 'invite' && pathParts.length >= 2) {
        await this.storeDeferredLink({
          type: 'referral',
          payload: decodeURIComponent(pathParts[1]),
          timestamp: Date.now(),
          metadata: this.metadataFromUrl(parsedUrl),
        });
        this.notifyReferralListeners();
        return;
      }

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
          timestamp: Date.now(),
          metadata: this.metadataFromUrl(parsedUrl),
        };

        // For referral links, always store as deferred so HomeScreen can handle the mutation
        // The influencer program is retired. Do not retain legacy campaign
        // links forever or let them overwrite a valid friend referral.
        if (type === 'influencer') {
          return;
        }
        if (type === 'referral') {
          await this.storeDeferredLink(linkData);
          this.notifyReferralListeners();
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
          timestamp: Date.now(),
          metadata: this.metadataFromUrl(parsedUrl),
        };

        // Always store referral links as deferred so HomeScreen can handle the mutation
        await this.storeDeferredLink(linkData);
        this.notifyReferralListeners();
      }
    } catch (error) {
      console.error('Error handling deep link:', error);
      throw error;
    }
  }

  private metadataFromUrl(parsedUrl: URL): DeepLinkData['metadata'] {
    return {
      invitationId: parsedUrl.searchParams.get('invitation_id') || undefined,
      sourceType: parsedUrl.searchParams.get('source_type') || undefined,
      clickId: parsedUrl.searchParams.get('click_id') || undefined,
      sessionId: parsedUrl.searchParams.get('session_id') || undefined,
      channel: parsedUrl.searchParams.get('channel') || undefined,
      platform: parsedUrl.searchParams.get('platform') || undefined,
      country: parsedUrl.searchParams.get('country') || undefined,
      utmSource: parsedUrl.searchParams.get('utm_source') || undefined,
      utmMedium: parsedUrl.searchParams.get('utm_medium') || undefined,
      utmCampaign: parsedUrl.searchParams.get('utm_campaign') || undefined,
      utmContent: parsedUrl.searchParams.get('utm_content') || undefined,
      utmTerm: parsedUrl.searchParams.get('utm_term') || undefined,
      ttclid: parsedUrl.searchParams.get('ttclid') || undefined,
      fbclid: parsedUrl.searchParams.get('fbclid') || undefined,
      gclid: parsedUrl.searchParams.get('gclid') || undefined,
    };
  }

  private async processDeepLink(linkData: DeepLinkData) {
    if (!this.navigation) {
      await this.storeDeferredLink(linkData);
      return;
    }

    switch (linkData.type) {
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

    await this.clearDeferredLink(linkData);
  }

  private async processDeferredLink(linkData: DeepLinkData) {
    if (linkData.type === 'influencer') {
      await this.clearDeferredLink(linkData);
      return;
    }

    if (linkData.type === 'referral') {
      if (!this.isWithinTimeout(linkData)) {
        await this.clearDeferredLink(linkData);
      }
      // Do not navigate or clear a valid referral here. HomeScreen consumes it
      // only after authentication and clears it after setReferrer succeeds or
      // returns a permanent error.
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
      throw error;
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

  public async clearDeferredLink(expected?: DeepLinkData) {
    try {
      if (expected) {
        const current = await this.getDeferredLink();
        if (!current ||
          current.type !== expected.type ||
          current.payload !== expected.payload ||
          current.timestamp !== expected.timestamp) {
          return false;
        }
      }
      // WORKAROUND: resetInternetCredentials checks arguments as array of maps on some Android versions
      // causing ClassCastException: String cannot be cast to ReadableNativeMap
      // Instead, we overwrite with "null" string which getDeferredLink handles.
      await Keychain.setInternetCredentials(
        DEFERRED_LINK_KEY,
        'deferred_link',
        'null'
      );
      return true;
    } catch (error) {
      console.error('Error clearing deferred link:', error);
      return false;
    }
  }

  // Public method to check and process deferred links after login
  async checkDeferredLinks() {
    await this.init();
    const deferredLink = await this.getDeferredLink();
    if (deferredLink) {
      await this.processDeferredLink(deferredLink);
    }
  }
}

// Singleton instance
export const deepLinkHandler = new DeepLinkHandler();
