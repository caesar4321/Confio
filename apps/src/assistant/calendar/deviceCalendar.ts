// The phone's own calendars (EventKit / Calendar Provider). No Google or Apple
// credential is involved and nothing here talks to a server.
import { NativeModules, PermissionsAndroid, Platform } from 'react-native';

// color and calendarId are optional: today's native readers do not send them, and the screen shows a dot only
// when they do.
export type DeviceCalendar = { id: string; title: string; account: string; color?: string };
export type DeviceEvent = { id: string; title: string; startsAt: number; allDay: boolean; calendarId?: string };

type NativeCalendar = {
  permissionStatus(): Promise<string>;
  requestAccess?(): Promise<string>;
  listCalendars(): Promise<DeviceCalendar[]>;
  listEvents(calendarIds: string[], from: number, until: number): Promise<DeviceEvent[]>;
};

const reader = (): NativeCalendar | undefined => NativeModules.ConfioCalendar;

export const calendarSupported = () => !!reader();

export async function hasCalendarAccess(): Promise<boolean> {
  return (await reader()?.permissionStatus()) === 'granted';
}

export async function requestCalendarAccess(): Promise<boolean> {
  if (!reader()) {
    return false;
  }
  if (Platform.OS === 'android') {
    const result = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.READ_CALENDAR);
    return result === PermissionsAndroid.RESULTS.GRANTED;
  }
  return (await reader()?.requestAccess?.()) === 'granted';
}

export async function listDeviceCalendars(): Promise<DeviceCalendar[]> {
  return (await reader()?.listCalendars()) ?? [];
}

export async function listDeviceEvents(calendarIds: string[], from: number, until: number): Promise<DeviceEvent[]> {
  // An empty choice means no calendars. EventKit would read it as all of them.
  if (!calendarIds.length) {
    return [];
  }
  return (await reader()?.listEvents(calendarIds, from, until)) ?? [];
}
