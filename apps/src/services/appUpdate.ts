import { Linking, Platform } from 'react-native';
import DeviceInfo from 'react-native-device-info';
import { API_URL } from '../config/env';
import { mobileClientHeaders } from './mobileClientHeaders';

export type AppUpdateStatus = 'current' | 'update_available';

export interface AppUpdatePolicy {
  status: AppUpdateStatus;
  latestVersion: string;
  message: string;
}

const IOS_APP_STORE_ID = '6472662314';
const ANDROID_PACKAGE = 'com.Confio.Confio';
const CHECK_TIMEOUT_MS = 8000;

// The endpoint sits beside GraphQL on the same host, so dev, testnet and
// prod builds each ask their own server.
export const appVersionUrl = (graphqlUrl: string = API_URL): string =>
  graphqlUrl.replace(/graphql\/?$/, 'api/app-version/');

/**
 * Asks the server whether the store has a newer version than this build.
 * A network error or an unexpected answer returns null: no prompt.
 */
export const fetchAppUpdatePolicy = async (): Promise<AppUpdatePolicy | null> => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), CHECK_TIMEOUT_MS);
  try {
    const query = `?platform=${Platform.OS}&version=${encodeURIComponent(DeviceInfo.getVersion())}`;
    const response = await fetch(appVersionUrl() + query, {
      headers: mobileClientHeaders(),
      signal: controller.signal,
    });
    if (!response.ok) return null;
    const body = await response.json();
    if (!['current', 'update_available'].includes(body?.status)) return null;
    return {
      status: body.status,
      latestVersion: typeof body.latestVersion === 'string' ? body.latestVersion : '',
      message: typeof body.message === 'string' ? body.message : '',
    };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
};

// Native store app first; the https page when it is missing (AOSP builds,
// simulators). Android uses market://: React Native's Linking hands the URL
// to Uri.parse, never Intent.parseUri, so an intent:// URL naming Google
// Play would not open Play at all.
export const openAppStore = async (): Promise<void> => {
  const native = Platform.OS === 'ios'
    ? `itms-apps://apps.apple.com/app/id${IOS_APP_STORE_ID}`
    : `market://details?id=${ANDROID_PACKAGE}`;
  const web = Platform.OS === 'ios'
    ? `https://apps.apple.com/app/id${IOS_APP_STORE_ID}`
    : `https://play.google.com/store/apps/details?id=${ANDROID_PACKAGE}`;
  try {
    await Linking.openURL(native);
  } catch {
    await Linking.openURL(web).catch(() => {});
  }
};
