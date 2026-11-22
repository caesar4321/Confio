// Nudges scheduled on the phone. Generic text: a lock screen never shows an event.
import { Platform } from 'react-native';
import notifee, { AndroidImportance, AuthorizationStatus, TriggerType } from '@notifee/react-native';

import { CALENDAR_NUDGE_PREFIX, isCalendarNudge } from './nudge';

const CHANNEL_ID = 'assistant-agenda';
const prefix = (userId: string) => `${CALENDAR_NUDGE_PREFIX}${userId}:`;

export async function scheduledReminders(userId: string): Promise<string[]> {
  const start = prefix(userId);
  const ids = await notifee.getTriggerNotificationIds();
  return ids.filter((id) => id.startsWith(start)).map((id) => id.slice(start.length));
}

export async function scheduleReminder(userId: string, eventId: string, at: number, wanted: () => boolean): Promise<boolean> {
  const permission = await notifee.requestPermission();
  if (permission.authorizationStatus < AuthorizationStatus.AUTHORIZED) {
    return false;
  }
  if (!wanted()) {
    return false;
  }
  if (Platform.OS === 'android') {
    await notifee.createChannel({ id: CHANNEL_ID, name: 'Avisos de tu agenda', importance: AndroidImportance.DEFAULT });
  }
  await notifee.createTriggerNotification(
    {
      id: `${prefix(userId)}${eventId}`,
      title: 'Confío IA',
      body: 'Tienes algo pendiente en tu agenda.',
      android: { channelId: CHANNEL_ID, smallIcon: 'ic_stat_ic_notification', pressAction: { id: 'default' } },
    },
    { type: TriggerType.TIMESTAMP, timestamp: at },
  );
  if (!wanted()) {
    // Closed or revoked while it was being created.
    await cancelReminder(userId, eventId);
    return false;
  }
  return true;
}

export async function cancelReminder(userId: string, eventId: string): Promise<void> {
  await notifee.cancelTriggerNotification(`${prefix(userId)}${eventId}`);
}

/** Every user's nudges on this phone: revoke and sign-out. */
export async function cancelAllReminders(): Promise<void> {
  const [pending, shown] = await Promise.all([notifee.getTriggerNotificationIds(), notifee.getDisplayedNotifications()]);
  const ids = new Set([...pending, ...shown.map((item) => item.id ?? item.notification?.id ?? '')].filter(isCalendarNudge));
  // cancelNotification clears both the scheduled and the delivered one.
  await Promise.all([...ids].map((id) => notifee.cancelNotification(id)));
}

/** Drops nudges for events that moved, were deleted or are no longer allowed. */
export async function pruneReminders(userId: string, liveEventIds: string[]): Promise<string[]> {
  const live = new Set(liveEventIds);
  const ids = await scheduledReminders(userId);
  await Promise.all(ids.filter((id) => !live.has(id)).map((id) => cancelReminder(userId, id)));
  return ids.filter((id) => live.has(id));
}
