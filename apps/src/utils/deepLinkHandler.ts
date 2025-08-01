import { Linking } from 'react-native';
import * as Keychain from 'react-native-keychain';
import { NavigationContainerRef } from '@react-navigation/native';

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
        
        // If user is not logged in, store as deferred link
        const isLoggedIn = await this.checkUserLoggedIn();
        if (!isLoggedIn) {
          await this.storeDeferredLink(linkData);
          return;
        }
        
        // Process immediately if logged in
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
        
        const isLoggedIn = await this.checkUserLoggedIn();
        if (!isLoggedIn) {
          await this.storeDeferredLink(linkData);
          return;
        }
        
        await this.processDeepLink(linkData);
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
  
  private async storeDeferredLink(linkData: DeepLinkData) {
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
  
  private async getDeferredLink(): Promise<DeepLinkData | null> {
    try {
      const credentials = await Keychain.getInternetCredentials(DEFERRED_LINK_KEY);
      return credentials ? JSON.parse(credentials.password) : null;
    } catch (error) {
      console.error('Error getting deferred link:', error);
      return null;
    }
  }
  
  private async clearDeferredLink() {
    try {
      await Keychain.resetInternetCredentials(DEFERRED_LINK_KEY);
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