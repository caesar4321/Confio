// Which calendars this person allowed, on this phone only. Ids, never events.
import * as Keychain from 'react-native-keychain';

export const CALENDAR_CONSENT_VERSION = 1;

// One record per phone, naming its owner, so sign-out can clear it without knowing who that was.
const SERVICE = 'com.confio.assistant.calendar';

export async function readCalendarConsent(userId: string): Promise<string[] | null> {
  const stored = await Keychain.getGenericPassword({ service: SERVICE });
  if (!stored) {
    return null;
  }
  try {
    const { version, owner, calendarIds } = JSON.parse(stored.password);
    const valid = version === CALENDAR_CONSENT_VERSION && owner === userId && Array.isArray(calendarIds)
      && calendarIds.length > 0 && calendarIds.every((id: unknown) => typeof id === 'string');
    return valid ? calendarIds : null;
  } catch {
    // Unreadable means not allowed.
    return null;
  }
}

export async function saveCalendarConsent(userId: string, calendarIds: string[]): Promise<void> {
  const saved = await Keychain.setGenericPassword(
    'calendar',
    JSON.stringify({ version: CALENDAR_CONSENT_VERSION, owner: userId, calendarIds }),
    { service: SERVICE, accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY },
  );
  if (!saved) {
    throw new Error('calendar consent not saved');
  }
}

export async function clearCalendarConsent(): Promise<void> {
  await Keychain.resetGenericPassword({ service: SERVICE });
  if (await Keychain.getGenericPassword({ service: SERVICE })) {
    throw new Error('calendar consent not cleared');
  }
}
