jest.mock('react-native', () => ({ Platform: { OS: 'ios' } }));
jest.mock('@notifee/react-native', () => ({
  __esModule: true,
  default: {
    getTriggerNotificationIds: jest.fn(async () => ['assistant-calendar:7:a', 'push-1']),
    getDisplayedNotifications: jest.fn(async () => [{ id: 'assistant-calendar:8:b' }, { id: 'push-2' }]),
    cancelNotification: jest.fn(async () => undefined),
  },
  AndroidImportance: {},
  AuthorizationStatus: {},
  TriggerType: {},
}));

import notifee from '@notifee/react-native';
import { cancelAllReminders } from '../reminders';

it('clears scheduled and delivered nudges of every user, and nothing else', async () => {
  await cancelAllReminders();
  expect((notifee.cancelNotification as jest.Mock).mock.calls.flat().sort())
    .toEqual(['assistant-calendar:7:a', 'assistant-calendar:8:b']);
});
