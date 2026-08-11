/// <reference types="jest" />

const mockGetAll = jest.fn();
const mockGetInternetCredentials = jest.fn().mockResolvedValue(false);
const mockSetInternetCredentials = jest.fn().mockResolvedValue(true);

jest.mock('react-native-contacts', () => ({
  getAll: (...args: any[]) => mockGetAll(...args),
  checkPermission: jest.fn().mockResolvedValue('authorized'),
}));

jest.mock('react-native-keychain', () => ({
  getInternetCredentials: (...args: any[]) => mockGetInternetCredentials(...args),
  setInternetCredentials: (...args: any[]) => mockSetInternetCredentials(...args),
}));

jest.mock('react-native', () => ({
  Platform: { OS: 'android' },
  PermissionsAndroid: {
    PERMISSIONS: { READ_CONTACTS: 'android.permission.READ_CONTACTS' },
    RESULTS: { GRANTED: 'granted' },
    check: jest.fn().mockResolvedValue(true),
    request: jest.fn().mockResolvedValue('granted'),
  },
}));

import {
  contactService,
  setDefaultPhoneRegion,
  type ContactSyncProgress,
} from '../contactService';

const buildContacts = (count: number) => Array.from({ length: count }, (_, index) => ({
  recordID: `contact-${index}`,
  givenName: 'Contacto',
  familyName: String(index),
  phoneNumbers: [{ number: `31${String(30000000 + index).padStart(8, '0')}` }],
  hasThumbnail: false,
}));

const noMatchesQuery = jest.fn().mockImplementation(({ variables }) => Promise.resolve({
  data: {
    checkUsersByPhones: variables.phoneNumbers.map((phoneNumber: string) => ({
      phoneNumber,
      isOnConfio: false,
    })),
  },
}));

describe('contact sync progress', () => {
  let consoleErrorSpy: jest.SpyInstance;

  beforeAll(() => {
    consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterAll(() => {
    consoleErrorSpy.mockRestore();
  });

  beforeEach(async () => {
    jest.clearAllMocks();
    mockGetInternetCredentials.mockResolvedValue(false);
    mockSetInternetCredentials.mockResolvedValue(true);
    setDefaultPhoneRegion('CO');
    await contactService.setContactOwner(null);
    await contactService.setContactOwner('sender-1', 'CO');
  });

  it('reports every phase with counts a user can watch advance', async () => {
    mockGetAll.mockResolvedValue(buildContacts(320));
    const events: ContactSyncProgress[] = [];

    await expect(
      contactService.syncContacts({ query: noMatchesQuery }, progress => events.push(progress)),
    ).resolves.toBe(true);

    expect(events[0]).toEqual({ phase: 'reading', processed: 0, total: 0 });

    const normalizing = events.filter(event => event.phase === 'normalizing');
    expect(normalizing[0]).toEqual({ phase: 'normalizing', processed: 0, total: 320 });
    // Two intermediate reports at the 150-contact chunk boundaries.
    expect(normalizing.map(event => event.processed)).toEqual([0, 150, 300]);

    const matching = events.filter(event => event.phase === 'matching');
    // 320 unique numbers queried 50 at a time: start plus one report per batch.
    expect(matching.map(event => event.processed)).toEqual([0, 50, 100, 150, 200, 250, 300, 320]);
    expect(matching.every(event => event.total === 320)).toBe(true);

    expect(events[events.length - 1]).toEqual({ phase: 'saving', processed: 0, total: 0 });
  });

  it('never reports past the total', async () => {
    mockGetAll.mockResolvedValue(buildContacts(75));
    const events: ContactSyncProgress[] = [];

    await contactService.syncContacts({ query: noMatchesQuery }, progress => events.push(progress));

    events.forEach(event => {
      if (event.total > 0) expect(event.processed).toBeLessThanOrEqual(event.total);
    });
  });

  it('stops reporting progress once the sync is superseded', async () => {
    mockGetAll.mockResolvedValue(buildContacts(400));
    const events: ContactSyncProgress[] = [];

    const stalePromise = contactService.syncContacts(
      { query: noMatchesQuery },
      progress => events.push(progress),
    );
    // A sign-out mid-sync: the abandoned run must not drive the UI any further.
    await contactService.setContactOwner(null);

    await expect(stalePromise).resolves.toBe(false);
    const countAtAbort = events.length;
    await new Promise(resolve => setTimeout(resolve, 20));
    expect(events.length).toBe(countAtAbort);
    expect(events.some(event => event.phase === 'saving')).toBe(false);
  });

  it('syncs without a progress listener', async () => {
    mockGetAll.mockResolvedValue(buildContacts(10));

    await expect(contactService.syncContacts({ query: noMatchesQuery })).resolves.toBe(true);
  });
});
