// The Home eye toggle's saved choice ("ocultar saldo"), readable from any
// screen that opens a view of the user's money without passing through Home.
import * as Keychain from 'react-native-keychain';

export const PREFERENCES_KEYCHAIN_SERVICE = 'com.confio.preferences';
export const BALANCE_VISIBILITY_KEY = 'balance_visibility';

/** True when the user hid their balances. No saved choice (or an unreadable
 *  keychain) reads as visible, exactly as Home does. */
export async function isBalanceHidden(): Promise<boolean> {
  try {
    const credentials = await Keychain.getInternetCredentials(PREFERENCES_KEYCHAIN_SERVICE);
    return Boolean(credentials && credentials.username === BALANCE_VISIBILITY_KEY
      && credentials.password === 'false');
  } catch {
    return false;
  }
}
