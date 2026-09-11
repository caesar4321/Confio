import * as Keychain from 'react-native-keychain';
import { AUTH_KEYCHAIN_SERVICE, AUTH_KEYCHAIN_USERNAME } from '../apollo/client';

/** A successful social sign-in must leave a usable, verified cold-start JWT. */
export async function persistSignInSession(accessToken: string, refreshToken?: string): Promise<void> {
  if (!accessToken) throw new Error('No auth tokens received from server');
  const stored = await Keychain.setGenericPassword(
    AUTH_KEYCHAIN_USERNAME,
    JSON.stringify({ accessToken, refreshToken }),
    {
      service: AUTH_KEYCHAIN_SERVICE,
      username: AUTH_KEYCHAIN_USERNAME,
      accessible: Keychain.ACCESSIBLE.AFTER_FIRST_UNLOCK,
    },
  );
  if (stored === false) throw new Error('Failed to store sign-in session');
  const credentials = await Keychain.getGenericPassword({ service: AUTH_KEYCHAIN_SERVICE });
  let saved: { accessToken?: string; refreshToken?: string } | null = null;
  try {
    saved = credentials ? JSON.parse(credentials.password) : null;
  } catch {
    // A malformed or stale read is not verification of this sign-in.
  }
  if (!saved || saved.accessToken !== accessToken || saved.refreshToken !== refreshToken) {
    throw new Error('Failed to verify sign-in session');
  }
}
