// A team invite link opened before the main screens are up (cold start,
// signed out, a fresh install): kept in the keychain until MainNavigator
// can show it.
import Keychain from 'react-native-keychain';

type Listener = (token: string) => void;

const SERVICE = 'confio.teamInvite';
const listeners = new Set<Listener>();

export const setPendingTeamInvite = async (token: string) => {
  try {
    await Keychain.setGenericPassword('team_invite', token, { service: SERVICE });
  } catch {
    // Still shown now if the main screens are up.
  }
  listeners.forEach((listener) => listener(token));
};

/** The pending token, once: whoever shows it takes it. */
export const takePendingTeamInvite = async (): Promise<string | null> => {
  try {
    const stored = await Keychain.getGenericPassword({ service: SERVICE });
    if (!stored) return null;
    await Keychain.resetGenericPassword({ service: SERVICE });
    return stored.password || null;
  } catch {
    return null;
  }
};

export const onTeamInvite = (listener: Listener) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};
