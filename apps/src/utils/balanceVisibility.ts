// The Home eye toggle's saved choice ("ocultar saldo"), readable from any
// screen that opens a view of the user's money without passing through Home.
import * as Keychain from 'react-native-keychain';

export const PREFERENCES_KEYCHAIN_SERVICE = 'com.confio.preferences';
export const BALANCE_VISIBILITY_KEY = 'balance_visibility';

/** The saved choice: true (show), false (hidden) or null (none saved).
 *  Throws when the keychain can't be read (callers decide how to report). */
export async function loadSavedBalanceVisibility(): Promise<boolean | null> {
  const credentials = await Keychain.getInternetCredentials(PREFERENCES_KEYCHAIN_SERVICE);
  if (!credentials || credentials.username !== BALANCE_VISIBILITY_KEY) return null;
  return credentials.password === 'true';
}

/** True when the user hid their balances. No saved choice (or an unreadable
 *  keychain) reads as visible, exactly as Home does. */
export async function isBalanceHidden(): Promise<boolean> {
  try {
    return (await loadSavedBalanceVisibility()) === false;
  } catch {
    return false;
  }
}
