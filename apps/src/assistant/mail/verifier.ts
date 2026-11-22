// The attempt's secret, kept while the person is in the browser (Android may kill the app).
import * as Keychain from 'react-native-keychain';

const SERVICE = 'com.confio.assistant.mail.connect';

export async function saveVerifier(userId: string, verifier: string, state: string): Promise<void> {
  const saved = await Keychain.setGenericPassword(userId, JSON.stringify({ verifier, state }), {
    service: SERVICE,
    accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  });
  if (!saved) {
    throw new Error('verifier not saved');
  }
}

/** Used up only by the state it was saved with: any app or page can open our link. */
export async function takeVerifier(userId: string, state: string): Promise<string | null> {
  const stored = await Keychain.getGenericPassword({ service: SERVICE });
  if (!stored || stored.username !== userId) {
    return null;
  }
  let saved: { verifier?: string; state?: string };
  try {
    saved = JSON.parse(stored.password);
  } catch {
    return null;
  }
  if (!saved.verifier || saved.state !== state) {
    return null;
  }
  await Keychain.resetGenericPassword({ service: SERVICE });
  return saved.verifier;
}
